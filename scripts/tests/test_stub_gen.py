"""Tests für scripts/stub_gen.py und scripts/stub_dump.py: ausschließlich synthetische TypeTree-/Dump-Fragmente
mit erfundenen Namen (keine Bundles, kein UnityPy, keine Spieldaten)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import stub_dump as sd  # noqa: E402
import stub_gen as sg  # noqa: E402

TMP_ROOT = os.path.join(HERE, "..", "..", "work", "stubs", "testtmp")
sg.STUB_IMAGES.add("ToyTween")  # erfundene Fremd-Assembly, die wie DOTween gestubbt wird

DUMP = """// Image 0: mscorlib.dll - 0
// Image 1: UnityEngine.CoreModule.dll - 10
// Image 2: UnityEngine.UI.dll - 30
// Image 3: ToyTween.dll - 40
// Image 4: Assembly-CSharp.dll - 50

// Namespace: System.Collections.Generic
public class List<T> // TypeDefIndex: 1
{}

// Namespace: UnityEngine
public class Object // TypeDefIndex: 10
{}

// Namespace: UnityEngine
public class Component : Object // TypeDefIndex: 11
{}

// Namespace: UnityEngine
public class Behaviour : Component // TypeDefIndex: 12
{}

// Namespace: UnityEngine
public class MonoBehaviour : Behaviour // TypeDefIndex: 13
{}

// Namespace: UnityEngine
public struct Vector3 // TypeDefIndex: 14
{}

// Namespace: UnityEngine
public class Sprite : Object // TypeDefIndex: 15
{}

// Namespace: UnityEngine.UI
public class Selectable : MonoBehaviour // TypeDefIndex: 30
{
	// Fields
	private bool m_Interactable; // 0x10
}

// Namespace: ToyTween
public enum EaseKind // TypeDefIndex: 40
{
	// Fields
	public int value__; // 0x0
	public const EaseKind Linear = 0;
	public const EaseKind Smooth = 1;
}

// Namespace: ToyTween
public class TweenBase : MonoBehaviour // TypeDefIndex: 41
{
	// Fields
	public EaseKind ease; // 0x18
}

// Namespace: Toy.Game
public enum WidgetMode // TypeDefIndex: 50
{
	// Fields
	public int value__; // 0x0
	public const WidgetMode Idle = 0;
	public const WidgetMode Busy = 2;
}

// Namespace: Toy.Game
[Serializable]
public class Gadget // TypeDefIndex: 51
{
	// Fields
	public int power; // 0x10
	[SerializeField] // RVA: 0x1 Offset: 0x2 VA: 0x1
	private string tag; // 0x18
}

// Namespace: Toy.Game
public enum Gadget.Slot // TypeDefIndex: 52
{
	// Fields
	public int value__; // 0x0
	public const Gadget.Slot Left = 0;
	public const Gadget.Slot Right = 1;
}

// Namespace: Toy.Game
public abstract class WidgetBase : MonoBehaviour // TypeDefIndex: 53
{
	// Fields
	[SerializeField] // RVA: 0x1 Offset: 0x2 VA: 0x1
	protected float speed; // 0x18
	private int hidden; // 0x1C

	// Methods

	// RVA: 0x10 Offset: 0x11 VA: 0x10
	public void .ctor() { }
}

// Namespace: Toy.Game
public class Widget : WidgetBase // TypeDefIndex: 54
{
	// Fields
	public int count; // 0x20
	[SerializeField] // RVA: 0x1 Offset: 0x2 VA: 0x1
	private Sprite icon; // 0x28
	public Gadget[] gadgets; // 0x30
	public List<Gadget> moreGadgets; // 0x38
	public WidgetMode mode; // 0x40
	public Vector3 offset; // 0x44
	public Gadget.Slot slot; // 0x50
	public static int Counter; // 0x0
	private Action<int> callback; // 0x58
}

// Namespace: Toy.Game
public class Knob : Selectable // TypeDefIndex: 55
{
	// Fields
	[SerializeField] // RVA: 0x1 Offset: 0x2 VA: 0x1
	private float turn; // 0x30
}

// Namespace: Toy.Game.Editor
public class Probe : MonoBehaviour // TypeDefIndex: 56
{
	// Fields
	public int level; // 0x18
}

// Namespace: Toy.Game
public abstract class Holder<T> : MonoBehaviour // TypeDefIndex: 57
{
	// Fields
	public T item; // 0x18
}

// Namespace: Toy.Game
public enum Holder.State<T> // TypeDefIndex: 58
{
	// Fields
	public int value__; // 0x0
	public const Holder.State<T> Open = 0;
}

// Namespace: Toy.Game
public class Chest : Holder<Chest> // TypeDefIndex: 59
{
	// Fields
	public Holder.State<Chest> state; // 0x20
}

// Namespace: ToyTween
public class TweenClip : TweenBase // TypeDefIndex: 42
{
	// Fields
	public float length; // 0x20
}

// Namespace: UnityEngine
public sealed class Mouse // TypeDefIndex: 16
{}

// Namespace: Toy.UI
public class Mouse : MonoBehaviour // TypeDefIndex: 61
{}

// Namespace: Toy.Game
public class Pad : MonoBehaviour // TypeDefIndex: 62
{
	// Fields
	[SerializeField] // RVA: 0x1 Offset: 0x2 VA: 0x1
	private Mouse mouse; // 0x18
}
""".split("\n")


def n(t, name, children=(), flag=0, size=4):
    return [t, name, flag, size, list(children)]


def ptr(target, name):
    return n("PPtr<$%s>" % target, name, [n("int", "m_FileID"), n("SInt64", "m_PathID", size=8)], size=12)


def arr(elem_node, name):
    data = list(elem_node)
    data[1] = "data"
    node = list(elem_node)
    node[1] = name
    node[4] = [n("Array", "Array", [n("int", "size"), data], size=-1)]
    return node


def string(name):
    return n("string", name, [n("Array", "Array", [n("int", "size"), n("char", "data", size=1)], size=-1)], size=-1)


def vec3(name):
    return n("Vector3f", name, [n("float", "x"), n("float", "y"), n("float", "z")], size=12)


def root(*fields):
    base = [ptr("GameObject", "m_GameObject"), n("UInt8", "m_Enabled", flag=0x4101, size=1),
            ptr("MonoScript", "m_Script"), string("m_Name")]
    return n("MonoBehaviour", "Base", base + list(fields), size=-1)


def gadget_node(name="x"):
    return n("Gadget", name, [n("int", "power"), string("tag")], size=-1)


def widget_tree():
    return root(n("float", "speed"), n("int", "count"), ptr("Sprite", "icon"), arr(gadget_node(), "gadgets"),
                arr(gadget_node(), "moreGadgets"), n("int", "mode"), vec3("offset"), n("int", "slot"))


def scan_for(entries):
    """entries: [(Schluessel, Instanzen, Komponenten, Baum)]"""
    classes, schemas = {}, {}
    for key, inst, comp, tree in entries:
        h = sg.schema_hash(tree) if tree else "-"
        if tree:
            schemas[h] = tree
        classes[key] = {"instances": inst, "components": comp, "bundles": 1, "groups": {}, "schemas": {h: inst}}
    return {"version": 1, "classes": classes, "schemas": schemas}


def make_gen(entries, dump=True):
    types, images = sd.parse_dump(DUMP)
    idx = sd.DumpIndex(types, images)
    return sg.Generator(scan_for(entries), idx, use_dump=dump).run()


class DumpParserTests(unittest.TestCase):
    def setUp(self):
        self.types, self.images = sd.parse_dump(DUMP)
        self.idx = sd.DumpIndex(self.types, self.images)

    def test_images_and_type_images(self):
        self.assertEqual(len(self.images), 5)
        t = self.idx.resolve("Widget")
        self.assertEqual(t.image, "Assembly-CSharp")
        self.assertEqual(self.idx.resolve("Selectable").image, "UnityEngine.UI")

    def test_fields_and_attributes(self):
        w = self.idx.resolve("WidgetBase")
        self.assertEqual([f["name"] for f in w.fields], ["speed", "hidden"])
        self.assertIn("SerializeField", w.fields[0]["attrs"])
        self.assertTrue(w.is_abstract)
        g = self.idx.resolve("Gadget")
        self.assertIn("Serializable", g.attrs)
        # Methoden und statische Zeilen verfälschen die Felder nicht
        wi = self.idx.resolve("Widget")
        self.assertIn("Counter", [f["name"] for f in wi.fields])
        self.assertEqual(len([f for f in wi.fields if f["name"] == ".ctor"]), 0)

    def test_enum_values_and_base(self):
        e = self.idx.resolve("WidgetMode")
        self.assertEqual(e.enum_values, [("Idle", "0"), ("Busy", "2")])
        self.assertEqual(e.enum_base, "int")

    def test_nested_type_gets_outer_namespace(self):
        s = self.idx.resolve("Gadget.Slot")
        self.assertEqual((s.ns, s.name), ("Toy.Game", "Gadget.Slot"))
        self.assertEqual(s.outer.name, "Gadget")

    def test_generic_names_and_arity(self):
        h = self.idx.resolve("Holder<Chest>")
        self.assertEqual((h.name, h.arity, h.gen), ("Holder", 1, ["T"]))
        self.assertIsNone(self.idx.resolve("Holder"))

    def test_chain_ends_at_unity_object(self):
        chain = self.idx.chain(self.idx.resolve("Widget"))
        self.assertEqual([c.name for c in chain], ["Widget", "WidgetBase", "MonoBehaviour", "Behaviour", "Component", "Object"])
        self.assertTrue(self.idx.is_unity_object(self.idx.resolve("Widget")))
        self.assertFalse(self.idx.is_unity_object(self.idx.resolve("Gadget")))

    def test_split_generic(self):
        self.assertEqual(sd.split_generic("Dictionary<string, List<int>>"), ("Dictionary", ["string", "List<int>"]))
        self.assertEqual(sd.split_generic("Plain"), ("Plain", []))


class TypeTreeHelperTests(unittest.TestCase):
    def test_array_parts_and_classify(self):
        a = arr(gadget_node(), "gadgets")
        self.assertEqual(sg.array_parts(a)[0], "Gadget")
        self.assertEqual(sg.classify(a), "array")
        self.assertIsNone(sg.array_parts(string("s")))
        self.assertEqual(sg.classify(string("s")), "string")
        self.assertEqual(sg.classify(n("int", "i")), "prim")
        self.assertEqual(sg.classify(ptr("Sprite", "p")), "pptr")
        self.assertEqual(sg.classify(vec3("v")), "unity")
        self.assertEqual(sg.classify(gadget_node()), "class")
        ev = n("UnityEvent", "e", [n("PersistentCallGroup", "m_PersistentCalls", [])], size=-1)
        self.assertEqual(sg.classify(ev), "event")

    def test_bool_and_schema_hash_is_stable(self):
        self.assertTrue(sg.is_bool(n("UInt8", "b", flag=0x4100, size=1)))
        self.assertFalse(sg.is_bool(n("UInt8", "b", flag=0x0, size=1)))
        self.assertEqual(sg.schema_hash(widget_tree()), sg.schema_hash(widget_tree()))

    def test_csharp_ident(self):
        self.assertEqual(sg.csharp_ident("class"), "@class")
        self.assertEqual(sg.csharp_ident("1abc"), "_1abc")
        self.assertEqual(sg.csharp_ident("a-b"), "a_b")


class GeneratorTests(unittest.TestCase):
    def widget_gen(self, dump=True):
        return make_gen([("Assembly-CSharp.dll|Toy.Game|Widget", 5, 5, widget_tree())], dump=dump)

    def test_class_binding_and_inheritance_split(self):
        g = self.widget_gen()
        w = g.units[("Toy.Game", "Widget", 0)]
        b = g.units[("Toy.Game", "WidgetBase", 0)]
        self.assertEqual(list(b.fields), ["speed"])
        self.assertEqual(list(w.fields), ["count", "icon", "gadgets", "moreGadgets", "mode", "offset", "slot"])
        self.assertEqual(w.base, "global::Toy.Game.WidgetBase")
        self.assertEqual(b.base, "global::UnityEngine.MonoBehaviour")
        self.assertTrue(b.abstract)
        self.assertNotIn("hidden", b.fields)  # nicht serialisiert: kommt im TypeTree nicht vor

    def test_field_types_use_dump_names(self):
        g = self.widget_gen()
        w = g.units[("Toy.Game", "Widget", 0)]
        self.assertEqual(w.fields["mode"]["type"], "global::Toy.Game.WidgetMode")
        self.assertEqual(w.fields["gadgets"]["type"], "global::Toy.Game.Gadget[]")
        self.assertEqual(w.fields["moreGadgets"]["type"], "global::System.Collections.Generic.List<global::Toy.Game.Gadget>")
        self.assertEqual(w.fields["icon"]["type"], "global::UnityEngine.Sprite")
        self.assertFalse(w.fields["icon"]["public"])
        self.assertTrue(w.fields["count"]["public"])
        self.assertEqual(w.fields["offset"]["type"], "global::UnityEngine.Vector3")
        self.assertEqual(w.fields["slot"]["type"], "global::Toy.Game.Gadget.Slot")

    def test_helper_types_are_generated(self):
        g = self.widget_gen()
        gad = g.units[("Toy.Game", "Gadget", 0)]
        self.assertEqual(list(gad.fields), ["power", "tag"])
        self.assertEqual(gad.fields["tag"]["type"], "string")
        self.assertFalse(gad.fields["tag"]["public"])
        mode = g.units[("Toy.Game", "WidgetMode", 0)]
        self.assertEqual(mode.kind, "enum")
        self.assertEqual(mode.enum_values, [("Idle", "0"), ("Busy", "2")])
        self.assertNotIn(("UnityEngine", "Vector3", 0), g.units)  # Engine-Typen werden nie gestubbt

    def test_emitted_text(self):
        g = self.widget_gen()
        files = sg.emit_all(g)
        text = files["Toy/Game/Widget.cs"]
        self.assertIn("namespace Toy.Game", text)
        self.assertIn("public partial class Widget : global::Toy.Game.WidgetBase", text)
        self.assertIn("[global::UnityEngine.SerializeField] private global::UnityEngine.Sprite icon;", text)
        self.assertIn("public int count;", text)
        self.assertNotIn("(", text.split("#pragma")[1].replace("[global::UnityEngine.SerializeField]", "").replace("[global::System", ""))
        base = files["Toy/Game/WidgetBase.cs"]
        self.assertIn("public abstract partial class WidgetBase : global::UnityEngine.MonoBehaviour", base)
        self.assertIn("[global::UnityEngine.SerializeField] private float speed;", base)
        enum = files["Toy/Game/WidgetMode.cs"]
        self.assertIn("public enum WidgetMode : int", enum)
        self.assertIn("Busy = 2,", enum)
        # verschachtelter Enum liegt in der Datei des Aeusseren
        self.assertIn("public enum Slot : int", files["Toy/Game/Gadget.cs"])
        self.assertNotIn("Toy/Game/Gadget_Slot.cs", files)

    def test_unserialized_dump_members_do_not_leak(self):
        g = self.widget_gen()
        w = g.units[("Toy.Game", "Widget", 0)]
        self.assertNotIn("Counter", w.fields)
        self.assertNotIn("callback", w.fields)

    def test_external_base_fields_are_not_redeclared(self):
        tree = root(n("UInt8", "m_Interactable", flag=0x4100, size=1), n("float", "turn"))
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Knob", 3, 3, tree)])
        k = g.units[("Toy.Game", "Knob", 0)]
        self.assertEqual(list(k.fields), ["turn"])
        self.assertEqual(k.base, "global::UnityEngine.UI.Selectable")
        self.assertEqual(g.stats["fields_from_external_base"], 1)
        self.assertNotIn(("UnityEngine.UI", "Selectable", 0), g.units)

    def test_foreign_assembly_gets_asmdef_and_reference(self):
        tree = root(n("float", "length"))
        g = make_gen([("Assembly-CSharp.dll|ToyTween|TweenClip", 2, 2, tree)])
        files = sg.emit_all(g)
        self.assertIn("_asm/ToyTween/ToyTween.asmdef", files)
        self.assertEqual(json.loads(files["_asm/ToyTween/ToyTween.asmdef"])["name"], "ToyTween")
        # Aufrufer in Assembly-CSharp referenziert die asmdef implizit (autoReferenced), Rueckrichtung gibt es nicht
        self.assertTrue(json.loads(files["_asm/ToyTween/ToyTween.asmdef"])["autoReferenced"])
        self.assertTrue(any(p.startswith("_asm/ToyTween/ToyTween/") and p.endswith("TweenBase.cs") for p in files))
        self.assertEqual(g.stats.get("asm_violations", 0), 0)
        self.assertEqual(g.units[("ToyTween", "TweenClip", 0)].asm, "ToyTween")

    def test_special_directory_names_are_defused(self):
        tree = root(n("int", "level"))
        g = make_gen([("Assembly-CSharp.dll|Toy.Game.Editor|Probe", 1, 1, tree)])
        files = sg.emit_all(g)
        self.assertIn("Toy/Game/Editor_/Probe.cs", files)
        self.assertIn("namespace Toy.Game.Editor", files["Toy/Game/Editor_/Probe.cs"])

    def test_generic_base_and_hoisted_nested_enum(self):
        tree = root(n("int", "state"))
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Chest", 1, 1, tree)])
        files = sg.emit_all(g)
        chest = files["Toy/Game/Chest.cs"]
        self.assertIn("public partial class Chest : global::Toy.Game.Holder<global::Toy.Game.Chest>", chest)
        self.assertIn("global::Toy.Game.Holder_State state;", chest)
        self.assertIn("public enum Holder_State : int", files["Toy/Game/Holder_State.cs"])
        self.assertIn("public abstract partial class Holder<T> : global::UnityEngine.MonoBehaviour", files["Toy/Game/Holder_G1.cs"])

    def test_typetree_only_mode(self):
        g = self.widget_gen(dump=False)
        w = g.units[("Toy.Game", "Widget", 0)]
        # ohne Dump: alles auf der Blattklasse, Basis MonoBehaviour, Enum als int, Hilfstyp aus dem Knotentyp
        self.assertEqual(w.base, "global::UnityEngine.MonoBehaviour")
        self.assertEqual(list(w.fields)[:3], ["speed", "count", "icon"])
        self.assertEqual(w.fields["mode"]["type"], "int")
        self.assertEqual(w.fields["icon"]["type"], "global::UnityEngine.Sprite")
        self.assertEqual(w.fields["gadgets"]["type"], "global::Xnu.Stubs.Auto.Gadget[]")
        self.assertIn(("Xnu.Stubs.Auto", "Gadget", 0), g.units)

    def test_unknown_pptr_target_falls_back_to_object(self):
        tree = root(ptr("MysteryThing", "target"))
        g = make_gen([("Assembly-CSharp.dll|Other|NoDump", 1, 1, tree)])
        u = g.units[("Other", "NoDump", 0)]
        self.assertEqual(u.fields["target"]["type"], "global::UnityEngine.Object")
        self.assertEqual(g.gaps["pptr_target_unknown"], 1)
        self.assertEqual(g.stats["classes_without_dump"], 1)

    def test_pptr_prefers_unity_object_over_same_named_static_engine_class(self):
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Pad", 1, 1, root(ptr("Mouse", "mouse")))])
        self.assertEqual(g.units[("Toy.Game", "Pad", 0)].fields["mouse"]["type"], "global::Toy.UI.Mouse")

    def test_unicode_field_names_are_kept(self):
        self.assertEqual(sg.csharp_ident("種類"), "種類")
        tree = root(n("int", "種類"))
        g = make_gen([("Assembly-CSharp.dll|Other|Table", 1, 0, tree)])
        self.assertIn("public int 種類;", sg.emit_all(g)["Other/Table.cs"])

    def test_scriptable_object_base_without_dump(self):
        g = make_gen([("Assembly-CSharp.dll|Other|DataTable", 1, 0, root(n("int", "rows")))])
        self.assertEqual(g.units[("Other", "DataTable", 0)].base, "global::UnityEngine.ScriptableObject")

    def test_provided_classes_are_skipped(self):
        g = make_gen([("UnityEngine.UI.dll|UnityEngine.UI|Selectable", 9, 9, root(n("int", "x")))])
        self.assertEqual(g.stats["classes_provided_skipped"], 1)
        self.assertEqual(g.units, {})

    def test_dump_only_class_without_typetree(self):
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Widget", 1, 1, None)])
        w = g.units[("Toy.Game", "Widget", 0)]
        self.assertEqual(list(w.fields), ["count", "icon", "gadgets", "moreGadgets", "mode", "offset", "slot"])
        self.assertEqual(g.stats["classes_dump_only"], 1)
        self.assertEqual(list(g.units[("Toy.Game", "WidgetBase", 0)].fields), ["speed"])

    def test_deterministic_output(self):
        a = sg.emit_all(self.widget_gen())
        b = sg.emit_all(self.widget_gen())
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), list(sorted(a)) if False else sorted(b))
        m1 = json.dumps(sg.build_manifest(self.widget_gen(), a), sort_keys=True)
        m2 = json.dumps(sg.build_manifest(self.widget_gen(), b), sort_keys=True)
        self.assertEqual(m1, m2)

    def test_manifest_and_report(self):
        g = self.widget_gen()
        files = sg.emit_all(g)
        m = sg.build_manifest(g, files)
        names = [c["name"] for c in m["classes"]]
        self.assertIn("Widget", names)
        w = [c for c in m["classes"] if c["name"] == "Widget"][0]
        self.assertEqual(w["origin"], "script")
        self.assertEqual(w["fields"][0]["name"], "count")
        r = sg.build_report(g, g.scan)
        self.assertEqual(r["script_classes"], 1)
        self.assertEqual(r["script_instances"], 5)
        self.assertEqual(r["by_kind"]["enum"], 2)


class WriteTreeTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        import tempfile
        self.td = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.out = os.path.join(self.td.name, "XnuStubs")

    def tearDown(self):
        self.td.cleanup()

    def test_idempotent_and_stale_removal(self):
        g1 = make_gen([("Assembly-CSharp.dll|Toy.Game|Widget", 5, 5, widget_tree())])
        f1 = sg.emit_all(g1)
        m1 = sg.build_manifest(g1, f1)
        new, chg, rem = sg.write_tree(self.out, f1, m1, False)
        self.assertEqual((new, chg, rem), (len(f1), 0, 0))
        self.assertEqual(sg.write_tree(self.out, f1, m1, False), (0, 0, 0))
        # eine .meta von Unity neben einer erzeugten Datei darf beim Entfernen mit verschwinden
        stale = os.path.join(self.out, "Toy", "Game", "Widget.cs")
        with open(stale + ".meta", "w") as f:
            f.write("x")
        g2 = make_gen([("Assembly-CSharp.dll|Toy.Game|Knob", 1, 1, root(n("float", "turn")))])
        f2 = sg.emit_all(g2)
        new, chg, rem = sg.write_tree(self.out, f2, sg.build_manifest(g2, f2), False)
        self.assertGreater(rem, 0)
        self.assertFalse(os.path.exists(stale))
        self.assertFalse(os.path.exists(stale + ".meta"))
        self.assertTrue(os.path.exists(os.path.join(self.out, "Toy", "Game", "Knob.cs")))

    def test_dry_run_writes_nothing(self):
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Widget", 5, 5, widget_tree())])
        f = sg.emit_all(g)
        new, _, _ = sg.write_tree(self.out, f, sg.build_manifest(g, f), True)
        self.assertEqual(new, len(f))
        self.assertFalse(os.path.exists(self.out))

    def test_changed_file_is_rewritten(self):
        g = make_gen([("Assembly-CSharp.dll|Toy.Game|Widget", 5, 5, widget_tree())])
        f = sg.emit_all(g)
        m = sg.build_manifest(g, f)
        sg.write_tree(self.out, f, m, False)
        f["Toy/Game/Widget.cs"] += "// geaendert\n"
        self.assertEqual(sg.write_tree(self.out, f, m, False), (0, 1, 0))


class ConflictTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        import tempfile
        self.td = tempfile.TemporaryDirectory(dir=TMP_ROOT)

    def tearDown(self):
        self.td.cleanup()

    def run_conflicts(self, source):
        from types import SimpleNamespace as NS
        scripts = os.path.join(self.td.name, "Scripts")
        os.makedirs(scripts)
        with open(os.path.join(scripts, "A.cs"), "w", encoding="utf-8") as f:
            f.write(source)
        man = os.path.join(self.td.name, "manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump({"classes": [{"namespace": "Toy.Game", "name": "Widget"}, {"namespace": "", "name": "Gizmo"}]}, f)
        return sg.cmd_conflicts(NS(manifest=man, scripts=scripts))

    def test_same_full_name_is_reported(self):
        self.assertEqual(self.run_conflicts("namespace Toy.Game\n{\n    public sealed class Widget { }\n}\n"), 1)

    def test_same_short_name_in_other_namespace_is_fine(self):
        self.assertEqual(self.run_conflicts("namespace Xnu.UI\n{\n    public class Widget { }\n}\nclass Other { }\n"), 0)

    def test_global_namespace_collision(self):
        self.assertEqual(self.run_conflicts("public class Gizmo { }\n"), 1)


class AggregateScanTests(unittest.TestCase):
    def test_aggregate_resolves_scripts_and_counts(self):
        tree = widget_tree()
        h = sg.schema_hash(tree)
        results = [
            {"path": os.path.join(sg.ASSETS, "a"), "group": "UIs", "scene": False, "container": 2, "objects": 10, "error": None, "cabs": ["cab-1"],
             "deps": [], "scripts": {"cab-1|7": ["Assembly-CSharp.dll", "Toy.Game", "Widget"]},
             "uses": [{"script": "cab-1|7", "n": 3, "comp": 2, "schema": h, "cab": "cab-1"}], "schemas": {h: tree}},
            {"path": os.path.join(sg.ASSETS, "b"), "group": "Dpr", "scene": True, "container": 1, "objects": 5, "error": None, "cabs": ["cab-2"],
             "deps": ["cab-1"], "scripts": {},
             "uses": [{"script": "cab-1|7", "n": 1, "comp": 1, "schema": h, "cab": "cab-2"}], "schemas": {h: tree}},
        ]
        out = sg.aggregate_scan(results)
        c = out["classes"]["Assembly-CSharp.dll|Toy.Game|Widget"]
        self.assertEqual((c["instances"], c["components"], c["bundles"]), (4, 3, 2))
        self.assertEqual(c["groups"]["Dpr"]["scene_bundles"], 1)
        self.assertEqual(c["schemas"], {h: 4})
        self.assertEqual(out["groups"]["UIs"]["container"], 2)
        self.assertEqual(out["bundles"]["b"]["deps"], ["cab-1"])
        self.assertEqual(out["unresolved_instances"], {})


if __name__ == "__main__":
    unittest.main()
