"""Tests für scripts/battle_oracle_heap.py.

Reine Logik (dump.cs-Parser, Gast-Heap, Tabellen-Zusammenfassung) läuft immer mit synthetischen Daten; die Tests mit echter
Emulation (Ereignissystem im Unicorn) werden übersprungen, wenn Unicorn oder das ELF fehlen.
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import battle_oracle_heap as bh  # noqa: E402

SYNTH_DUMP = """
// Namespace: Dpr.Battle.Logic
public sealed class EventFactor.Data // TypeDefIndex: 100
{
	// Fields
	public const uint EVENT_HANDLER_WORK_ELEMS = 7;
	public int[] work; // 0x40
	public EventPriority priority; // 0x24
	public ushort subID; // 0x28
	public byte dependID; // 0x2A
	public bool existFlag; // 0x39
	private static readonly byte[] Table; // 0x8

	// Methods
	// RVA: 0x10 Offset: 0x10 VA: 0x10
	public void Clear() { }
	// RVA: 0x20 Offset: 0x20 VA: 0x20
	public void .ctor() { }
}
// Namespace: Dpr.Battle.Logic
public sealed class Other // TypeDefIndex: 101
{
	public int x; // 0x10
}
// Namespace:
public enum EventPriority // TypeDefIndex: 102
{
	public byte value__; // 0x0
	public const EventPriority WAZA = 1;
	public const EventPriority TOKUSEI = 7;
}
"""


class FakeOracle:
    """Minimaler Ersatz für Oracle: ein flacher Speicher mit Zuteiler."""

    def __init__(self):
        self.mem = bytearray(0x1000)
        self.next = 0x100

    def alloc(self, size):
        p = self.next
        self.next += (size + 15) & ~15
        return p

    def write(self, addr, blob):
        self.mem[addr:addr + len(blob)] = blob

    def read(self, addr, n):
        return bytes(self.mem[addr:addr + n])


class DumpParserTests(unittest.TestCase):
    def test_instance_and_static_fields_with_offsets(self):
        fields = bh.parse_class_fields(SYNTH_DUMP, "EventFactor.Data")
        self.assertEqual(fields["work"].offset, 0x40)
        self.assertEqual(fields["priority"].offset, 0x24)
        self.assertEqual(fields["dependID"].type_name, "byte")
        self.assertTrue(fields["Table"].static)
        self.assertFalse(fields["subID"].static)
        self.assertNotIn("EVENT_HANDLER_WORK_ELEMS", fields)  # Konstanten haben keinen Offset
        self.assertNotIn("Clear", fields)

    def test_type_index_selects_the_class_and_unknown_raises(self):
        self.assertEqual(bh.parse_class_fields(SYNTH_DUMP, "Other", 101)["x"].offset, 0x10)
        with self.assertRaises(KeyError):
            bh.parse_class_fields(SYNTH_DUMP, "Other", 999)
        with self.assertRaises(KeyError):
            bh.parse_class_fields(SYNTH_DUMP, "Nope")

    def test_enum_constants(self):
        self.assertEqual(bh.parse_enum_consts(SYNTH_DUMP, "EventPriority"), {"WAZA": 1, "TOKUSEI": 7})

    def test_method_rvas_are_shifted_to_ghidra_addresses(self):
        rvas = bh.parse_method_rvas(SYNTH_DUMP, "EventFactor.Data")
        self.assertEqual(rvas["Clear"], [0x10 + bh.IMAGE_BASE])
        self.assertEqual(rvas[".ctor"], [0x20 + bh.IMAGE_BASE])


class GuestHeapTests(unittest.TestCase):
    def setUp(self):
        self.o = FakeOracle()
        self.heap = bh.GuestHeap(self.o, bh.DumpTypes(SYNTH_DUMP), enum_sizes={"EventPriority": 1})

    def test_set_get_round_trip_uses_field_widths(self):
        p = self.heap.new("EventFactor.Data")
        self.heap.set(p, "EventFactor.Data", "subID", 0x1234)
        self.heap.set(p, "EventFactor.Data", "dependID", 0x1FF)       # wird auf 8 Bit gekürzt
        self.heap.set(p, "EventFactor.Data", "priority", 7)
        self.heap.set(p, "EventFactor.Data", "work", 0x1122334455667788)
        self.assertEqual(self.o.read(p + 0x28, 2), b"\x34\x12")
        self.assertEqual(self.heap.get(p, "EventFactor.Data", "dependID"), 0xFF)
        self.assertEqual(self.heap.get(p, "EventFactor.Data", "priority"), 7)
        self.assertEqual(struct.unpack("<Q", self.o.read(p + 0x40, 8))[0], 0x1122334455667788)
        self.assertEqual(self.heap.offset("EventFactor.Data", "existFlag"), 0x39)

    def test_static_fields_are_rejected(self):
        p = self.heap.new("EventFactor.Data")
        with self.assertRaises(ValueError):
            self.heap.set(p, "EventFactor.Data", "Table", 1)


class TableSummaryTests(unittest.TestCase):
    def test_counts_entries_functions_and_event_frequency(self):
        tables = {"Tokusei": {"HandlerTable_A": [[74, "f"], [64, "g"]], "HandlerTable_B": [[74, "f"]], "HandlerTable_C": []}}
        s = bh.summarize_handler_tables(tables)["Tokusei"]
        self.assertEqual((s["tables"], s["entries"], s["distinctFunctions"], s["maxEntriesPerTable"]), (3, 3, 2, 2))
        self.assertEqual(list(s["eventFrequency"].items()), [(74, 2), (64, 1)])


class EmulationTests(unittest.TestCase):
    """Echte Ereignissystem-Funktionen im Unicorn (nur mit ELF und Unicorn)."""

    @classmethod
    def setUpClass(cls):
        if not bh.bo.ELF.exists():
            raise unittest.SkipTest("work/elf/main.patched.elf fehlt")
        try:
            import unicorn  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("unicorn nicht installiert (PYTHONPATH=tools/pydeps)")
        cls.oracle = bh.EventOracle()

    def test_event_var_rules_of_the_real_functions(self):
        w = bh.EventWorld(self.oracle)
        try:
            w.exec_op(["push"])
            w.exec_op(["mulset", 56, 0x1000, 0x29, 0x20000])
            w.exec_op(["mul", 56, 0x14CD])
            self.assertEqual(bh.bo.to_s32(w.es_call("get", 56)), 0x14CD)
            w.exec_op(["const", 3, 7])
            self.assertEqual(w.es_call("rewrite", 3, 9) & 1, 0)       # Konstanten sind nicht umschreibbar
            w.exec_op(["once", 51, 40])
            self.assertEqual(w.es_call("rewrite", 51, 50) & 1, 1)
            self.assertEqual(w.es_call("rewrite", 51, 60) & 1, 0)     # nur einmal
            self.assertEqual(bh.bo.to_s32(w.es_call("get", 51)), 50)
            w.exec_op(["push"])
            self.assertEqual(w.es_call("get", 51), 0)                  # innerer Rahmen sieht äußere Variablen nicht
            w.exec_op(["pop"])
            self.assertEqual(bh.bo.to_s32(w.es_call("get", 51)), 50)
        finally:
            w.release()

    def test_priority_sorting_and_instance_ids_of_the_real_container(self):
        w = bh.EventWorld(self.oracle)
        try:
            def spec(ftype, pri, sub_pri, sub):
                return {"type": ftype, "subID": sub, "mainPri": pri, "subPri": sub_pri, "dependID": 0, "entries": [{"event": 1}]}
            for s in (spec(5, 8, 100, 1), spec(4, 7, 200, 2), spec(4, 7, 50, 3), spec(0, 1, 0, 4), spec(4, 7, 200, 5)):
                w.add_factor(s)
            order = [(f[0], f[2], f[3]) for f in w.factor_list()]
            # Attacke, schnelle Fähigkeit, gleich schnelle (später registriert), langsame Fähigkeit, Item; Instanz-IDs von oben
            self.assertEqual([sub for _i, sub, _p in order], [4, 2, 5, 3, 1])
            self.assertEqual([i for i, _s, _p in order], [168, 170, 167, 169, 171])
            self.assertEqual(order[0][2], 0x8000000)
        finally:
            w.release()

    def test_handler_can_remove_itself_while_it_runs(self):
        w = bh.EventWorld(self.oracle)
        try:
            w.add_factor({"type": 4, "subID": 1, "mainPri": 7, "subPri": 0, "dependID": 0,
                          "entries": [{"event": 1, "ops": [["remove_self"]]}]})
            w.exec_op(["push"])
            w.exec_op(["call", 1])
            self.assertEqual(w.factor_list(), [])
            self.assertEqual(w.stored_count(), 172)
            self.assertEqual(w.log, [[1, 171, 0, 1]])
        finally:
            w.release()


if __name__ == "__main__":
    unittest.main()
