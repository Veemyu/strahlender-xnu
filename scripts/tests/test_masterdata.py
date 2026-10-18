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


if __name__ == "__main__":
    unittest.main()
