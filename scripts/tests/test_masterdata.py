"""Tests für scripts/masterdata_export.py – ausschließlich synthetische Daten (keine Bundles, kein UnityPy)."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import masterdata_export as md  # noqa: E402


def node(t, name, children=()):
    return NS(m_Type=t, m_Name=name, m_Children=list(children))


def array_node(elem_type, name, elem_children=()):
    """Unity-Layout: Feld trägt den Elementtyp und hat ein Kind 'Array' mit size + data."""
    data = node(elem_type, "data", elem_children)
    return node(elem_type, name, [node("Array", "Array", [node("int", "size"), data])])


def synthetic_root():
    sheet_fields = [node("unsigned short", "no"), node("SInt8", "delta"), node("string", "label"),
                    array_node("unsigned short", "values")]
    return node("Base", "Base", [
        node("PPtr<GameObject>", "m_GameObject"), node("UInt8", "m_Enabled"),
        node("PPtr<MonoScript>", "m_Script"), node("string", "m_Name"),
        array_node("SheetThing", "Thing", sheet_fields),
        node("float", "scale"),
    ])


DUMP = """\
// Namespace: Demo
[Serializable]
public class ThingTable : ScriptableObject // TypeDefIndex: 1
{
	// Fields
	public ThingTable.SheetThing[] Thing; // 0x18
	public float scale; // 0x20
	public const int Limit = 5;
	public static int Counter; // 0x0

	// Methods

	// RVA: 0x1 Offset: 0x2 VA: 0x1
	public void .ctor() { }
}

// Namespace: 
[Serializable]
public class ThingTable.SheetThing : SheetBase // TypeDefIndex: 2
{
	// Fields
	public ushort no; // 0x10
	public sbyte delta; // 0x12
	public string label; // 0x18
	public ushort[] values; // 0x20
}

// Namespace: 
public class SheetBase // TypeDefIndex: 3
{
	// Fields
	public int baseValue; // 0x10
}
"""


class TestSchema(unittest.TestCase):
    def test_describe_primitives_arrays_and_structs(self):
        fields = md.class_schema(synthetic_root())
        self.assertEqual([f["name"] for f in fields], ["Thing", "scale"])
        thing = fields[0]
        self.assertEqual(thing["type"], "array")
        el = thing["element"]
        self.assertEqual(el["type"], "SheetThing")
        types = {f["name"]: f["type"] for f in el["fields"]}
        self.assertEqual(types, {"no": "ushort", "delta": "sbyte", "label": "string", "values": "array"})
        values = [f for f in el["fields"] if f["name"] == "values"][0]
        self.assertEqual(values["element"]["type"], "ushort")
        self.assertEqual(fields[1]["type"], "float")

    def test_string_is_not_array(self):
        s = node("string", "s", [node("Array", "Array", [node("int", "size"), node("char", "data")])])
        self.assertEqual(md.describe_node(s), {"name": "s", "type": "string"})

    def test_signature_stable_and_discriminating(self):
        a = md.class_schema(synthetic_root())
        b = md.class_schema(synthetic_root())
        self.assertEqual(md.schema_signature(a), md.schema_signature(b))
        b[1]["type"] = "double"
        self.assertNotEqual(md.schema_signature(a), md.schema_signature(b))


class TestDump(unittest.TestCase):
    def setUp(self):
        self.dump = md.parse_dump(DUMP.splitlines())

    def test_parse_classes_fields_offsets(self):
        t = self.dump["Demo.ThingTable"]
        self.assertEqual([f[0] for f in t["fields"]], ["Thing", "scale"])  # static/const ausgelassen
        self.assertEqual(t["fields"][0][2], 0x18)
        sheet = self.dump["ThingTable.SheetThing"]
        self.assertEqual(sheet["base"], "SheetBase")
        self.assertEqual(sheet["fields"][2], ("label", "string", 0x18))

    def test_inherited_fields_come_first(self):
        names = [f[0] for f in md.resolve_fields(self.dump, self.dump["ThingTable.SheetThing"])]
        self.assertEqual(names[0], "baseValue")
        self.assertIn("values", names)

    def test_compare_matches_nested(self):
        fields = md.class_schema(synthetic_root())
        res = md.compare_with_dump(self.dump, "Demo", "ThingTable", fields)
        self.assertTrue(res["match"])
        self.assertEqual(res["offsets"]["scale"], 0x20)
        nested = res["nested"]["Thing"]
        self.assertTrue(nested["match"])
        self.assertTrue(nested["same_order"])
        self.assertEqual(nested["offsets"]["no"], 0x10)

    def test_compare_detects_missing_field(self):
        fields = md.class_schema(synthetic_root())
        fields.append({"name": "ghost", "type": "int"})
        res = md.compare_with_dump(self.dump, "Demo", "ThingTable", fields)
        self.assertFalse(res["match"])
        self.assertEqual(res["missing_in_dump"], ["ghost"])

    def test_unknown_class(self):
        res = md.compare_with_dump(self.dump, "Demo", "Nope", [])
        self.assertIsNone(res["dump_class"])
        self.assertFalse(res["match"])


class TestExport(unittest.TestCase):
    def records(self):
        schema = md.class_schema(synthetic_root())
        return [
            {"class": "ThingTable", "namespace": "Demo", "assembly": "Assembly-CSharp.dll", "name": "ThingTable",
             "schema": schema, "data": {"Thing": [{"no": 1, "delta": -2, "label": "x", "values": [1, 2]}], "scale": 1.5}},
            {"class": "Place", "namespace": "Demo", "assembly": "Assembly-CSharp.dll", "name": "a", "schema": [], "data": {"Data": []}},
            {"class": "Place", "namespace": "Demo", "assembly": "Assembly-CSharp.dll", "name": "b", "schema": [], "data": {"Data": []}},
            {"class": None, "namespace": "", "assembly": "", "name": "orphan", "schema": [], "data": {}},
        ]

    def test_export_writes_one_file_per_class(self):
        with tempfile.TemporaryDirectory() as out:
            written = md.export_records(self.records(), "Synthetic/bundle", out)
            self.assertEqual(sorted(os.path.basename(p) for p in written), ["Place.json", "ThingTable.json"])
            with open(os.path.join(out, "Place.json"), encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(doc["bundle"], "Synthetic/bundle")
            self.assertEqual([i["name"] for i in doc["instances"]], ["a", "b"])
            with open(os.path.join(out, "ThingTable.json"), encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(doc["instances"][0]["data"]["Thing"][0]["values"], [1, 2])

    def test_survey_counts(self):
        info = md.survey_bundle(self.records(), md.parse_dump(DUMP.splitlines()))
        self.assertEqual(info["objects"], 4)
        by = {c["class"]: c for c in info["classes"] if c["class"]}
        self.assertEqual(by["Place"]["instances"], 2)
        self.assertIsNone(by["Place"]["rows"])
        self.assertEqual(by["ThingTable"]["rows"], {"Thing": 1})
        self.assertTrue(by["ThingTable"]["dump"]["match"])

    def test_output_is_valid_utf8_json_for_csharp_reader(self):
        with tempfile.TemporaryDirectory() as out:
            rec = self.records()[:1]
            rec[0]["data"]["Thing"][0]["label"] = "Übung\n\"q\""
            md.export_records(rec, "b", out)
            with open(os.path.join(out, "ThingTable.json"), "rb") as f:
                raw = f.read()
            self.assertNotIn(b"\n", raw)  # Zeilenumbrüche im String sind escaped
            self.assertEqual(json.loads(raw.decode("utf-8"))["instances"][0]["data"]["Thing"][0]["label"], "Übung\n\"q\"")


class TestPart2(unittest.TestCase):
    def rec(self, cls, ns, name, path_id=None, data=None):
        r = {"class": cls, "namespace": ns, "assembly": "Assembly-CSharp.dll", "name": name, "schema": [], "data": data or {}}
        if path_id is not None:
            r["path_id"] = path_id
        return r

    def test_want_class_default_namespace_and_allow_list(self):
        self.assertTrue(md.want_class("XLSXContent", "ZoneTable"))
        self.assertFalse(md.want_class("UnityEngine.UI", "Image"))
        self.assertFalse(md.want_class("XLSXContent", None))
        self.assertTrue(md.want_class("", "EvData", {"EvData"}))
        self.assertFalse(md.want_class("XLSXContent", "ZoneTable", {"EvData"}))

    def test_filter_records(self):
        recs = [self.rec("A", "XLSXContent", "a"), self.rec("B", "Other", "b"), self.rec(None, "", "c")]
        self.assertEqual([r["name"] for r in md.filter_records(recs)], ["a"])
        self.assertEqual([r["name"] for r in md.filter_records(recs, {"B"})], ["b"])

    def test_resolve_pptr_names_in_place(self):
        target = self.rec("AttributeBlock", "XLSXContent", "block_a", path_id=42)
        owner = self.rec("Matrix", "XLSXContent", "m", path_id=1, data={
            "Blocks": [{"m_FileID": 0, "m_PathID": 42}, {"m_FileID": 0, "m_PathID": 0}, {"m_FileID": 0, "m_PathID": 99}],
            "Nested": {"Ref": {"m_FileID": 0, "m_PathID": 42}},
            "Foreign": {"m_FileID": 2, "m_PathID": 42},
            "Plain": {"m_FileID": 0, "m_PathID": 42, "extra": 1},
        })
        resolved, open_ = md.resolve_pptr_names([target, owner])
        self.assertEqual((resolved, open_), (2, 3))
        blocks = owner["data"]["Blocks"]
        self.assertEqual(blocks[0]["target_name"], "block_a")
        self.assertEqual(blocks[0]["target_class"], "AttributeBlock")
        self.assertNotIn("target_name", blocks[1])   # PathID 0 = leer
        self.assertNotIn("target_name", blocks[2])   # unbekanntes Objekt
        self.assertEqual(owner["data"]["Nested"]["Ref"]["target_name"], "block_a")
        self.assertNotIn("target_name", owner["data"]["Foreign"])   # andere Datei
        self.assertNotIn("target_name", owner["data"]["Plain"])     # kein reines PPtr-Objekt

    def test_export_records_writes_path_id_only_when_present(self):
        recs = [self.rec("Thing", "XLSXContent", "a", path_id=7, data={"Data": []}),
                self.rec("Other", "XLSXContent", "b", data={"Data": []})]
        with tempfile.TemporaryDirectory() as out:
            md.export_records(recs, "Synthetic/b", out)
            with open(os.path.join(out, "Thing.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["instances"][0]["path_id"], 7)
            with open(os.path.join(out, "Other.json"), encoding="utf-8") as f:
                self.assertNotIn("path_id", json.load(f)["instances"][0])

    def test_table_counts_sums_rows_over_instances(self):
        doc = {"class": "MapWarp", "bundle": "b", "instances": [
            {"name": "a", "data": {"Data": [1, 2], "Scale": 1.5}}, {"name": "b", "data": {"Data": [3]}}, {"name": "c", "data": {}}]}
        self.assertEqual(md.table_counts(doc), {"class": "MapWarp", "bundle": "b", "instances": 3, "rows": {"Data": 3}})

    def test_ev_stats_counts_structure_only(self):
        def cmd(*args):
            return {"Arg": [{"argType": t, "data": d} for t, d in args]}
        instances = [
            {"name": "x", "data": {"StrList": ["a", "b"], "Scripts": [
                {"Label": "l1", "Commands": [cmd((0, 4), (1, 1065353216), (5, 0)), cmd((0, 4)), {"Arg": []}]},
                {"Label": "l2", "Commands": [cmd((0, 9), (2, 3))]}]}},
            {"name": "y", "data": {"StrList": [], "Scripts": []}},
        ]
        s = md.ev_stats(instances)
        self.assertEqual(s["files"], 2)
        self.assertEqual(s["scripts"], 2)
        self.assertEqual(s["commands"], 4)
        self.assertEqual(s["args"], 6)
        self.assertEqual(s["arg_types"], {0: 3, 1: 1, 2: 1, 5: 1})
        self.assertEqual(s["distinct_opcodes"], 2)
        self.assertEqual(s["strings"], 2)

    def test_scan_wanted(self):
        self.assertTrue(md.scan_wanted("XLSXContent", "AnyTable"))
        self.assertTrue(md.scan_wanted("Dpr.Message", "MsbtData"))
        self.assertTrue(md.scan_wanted("", "EvData"))
        self.assertFalse(md.scan_wanted("UnityEngine", "Image"))

    def test_targets_default_is_part_one_only(self):
        args = NS(set="base", messages=False)
        targets = md._targets(args)
        self.assertEqual({t[0] for t in targets}, set(md.DATA_BUNDLES))
        self.assertTrue(all(allow is None and not extra for _, _, allow, extra in targets))
        extra = md._targets(NS(set="extra", messages=False))
        self.assertEqual({t[0] for t in extra}, set(md.EXTRA_BUNDLES))
        self.assertTrue(all(e for _, _, _, e in extra))
        both = md._targets(NS(set="all", messages=True))
        self.assertEqual(len(both), len(md.DATA_BUNDLES) + len(md.MESSAGE_BUNDLES) + len(md.EXTRA_BUNDLES))

    def test_extra_bundles_do_not_collide_with_base_output_folders(self):
        base = set(md.DATA_BUNDLES.values()) | set(md.MESSAGE_BUNDLES.values())
        extra = [short for short, _ in md.EXTRA_BUNDLES.values()]
        self.assertFalse(base & set(extra))
        self.assertEqual(len(extra), len(set(extra)))
        self.assertFalse(set(md.EXTRA_BUNDLES) & set(md.DATA_BUNDLES))

    def test_audio_bundles_are_never_targets(self):
        for rel in list(md.DATA_BUNDLES) + list(md.MESSAGE_BUNDLES) + list(md.EXTRA_BUNDLES):
            self.assertNotIn("audio", rel.lower())
            self.assertNotIn("sound", rel.lower())

    def test_counts_command_writes_numbers_only(self):
        with tempfile.TemporaryDirectory() as out:
            md.write_json(os.path.join(out, "grp", "T.json"), {"class": "T", "bundle": "b", "instances": [{"name": "t", "data": {"Rows": [1, 2, 3]}}]})
            md.write_json(os.path.join(out, "_survey.json"), {"ignored": True})
            md.cmd_counts(NS(out=out))
            with open(os.path.join(out, "_counts.json"), encoding="utf-8") as f:
                counts = json.load(f)
            self.assertEqual(list(counts), [os.path.join("grp", "T.json")])
            self.assertEqual(counts[os.path.join("grp", "T.json")]["rows"], {"Rows": 3})


if __name__ == "__main__":
    unittest.main()
