#!/usr/bin/env python3
"""Gast-Heap-Helfer und Ereignissystem-Orakel fuer die Kampf-Scheibe 2.

Baut auf scripts/battle_oracle.py (Unicorn, AArch64) auf und ergaenzt:
  * DumpTypes   - liest Klassenfelder (Name, Offset, Typ) aus work/il2cpp/dump.cs,
  * GuestHeap   - legt Objekte/Arrays mit den Offsets aus dump.cs im Gastspeicher an,
  * EventOracle - IL2CPP-Stubs (Objekt-Allokation, Ausnahmen), "yield"-Stubs fuer Delegat-Aufrufe
                  (Handler laufen als Python-Funktion ausserhalb der Emulation und duerfen verschachtelt echte
                  Gastfunktionen aufrufen), Methodenzeiger-Slots fuer Delegat-Konstruktion.
  * Szenarien, die die ECHTEN Funktionen von EventFactorContainer, EventSystem, EventVar* ausfuehren und die
    Ergebnisse als reine Zahlen nach unity/Assets/Tests/EditMode/Fixtures/BattleEvents*.json schreiben.

Adressen: Ghidra-Adresse = Il2CppDumper-RVA + 0x100000 (= ELF-vaddr + 0x100000).
Aufruf:  PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_heap.py [--out DIR] [--only NAME ...] [--tables]
"""
import argparse
import json
import random
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_oracle as bo  # noqa: E402

ROOT = bo.ROOT
IMAGE_BASE = bo.IMAGE_BASE
SENTINEL = bo.SENTINEL
STACK_TOP = bo.STACK_TOP
DEFAULT_OUT = bo.DEFAULT_OUT

PRIM_SIZES = {"byte": 1, "sbyte": 1, "bool": 1, "short": 2, "ushort": 2, "char": 2, "int": 4, "uint": 4,
              "float": 4, "long": 8, "ulong": 8, "double": 8, "IntPtr": 8, "UIntPtr": 8}
PRIM_FMT = {"byte": "B", "sbyte": "b", "bool": "B", "short": "h", "ushort": "H", "char": "H", "int": "i", "uint": "I",
            "float": "f", "long": "q", "ulong": "Q", "double": "d", "IntPtr": "Q", "UIntPtr": "Q"}


# ---------------------------------------------------------------------------------------------------------------
# dump.cs: Klassenfelder
# ---------------------------------------------------------------------------------------------------------------

class Field:
    def __init__(self, name, type_name, offset, static):
        self.name, self.type_name, self.offset, self.static = name, type_name, offset, static

    def __repr__(self):
        return f"Field({self.name}:{self.type_name}@{self.offset:#x}{' static' if self.static else ''})"


_FIELD_RE = re.compile(r"^\t(?:public |private |protected |internal )+(static )?(?:readonly )?([^\s;=]+(?: <[^>]*>)?(?:\[\])?) (\w+)(?: = [^;]*)?; // 0x([0-9A-Fa-f]+)\s*$")


def parse_class_fields(dump_text, class_name, type_index=None):
    """Instanz- und statische Felder einer Klasse/Struktur (Name wie im Dump, z. B. 'EventFactor.Data')."""
    pat = re.compile(r"^(?:public |private |internal |protected )*(?:sealed |static |abstract )*(?:class|struct|enum) "
                     + re.escape(class_name) + r"(?: :[^\n/]*)? // TypeDefIndex: (\d+)", re.M)
    found = None
    for m in pat.finditer(dump_text):
        if type_index is None or int(m.group(1)) == type_index:
            found = m
            break
    if found is None:
        raise KeyError(class_name)
    end = dump_text.find("\n}\n", found.end())
    body = dump_text[found.end():end]
    fields = {}
    for line in body.split("\n"):
        if line.startswith("\t// Methods") or line.startswith("\t// Properties"):
            break
        fm = _FIELD_RE.match(line)
        if fm:
            fields[fm.group(3)] = Field(fm.group(3), fm.group(2), int(fm.group(4), 16), bool(fm.group(1)))
    return fields


def parse_enum_consts(dump_text, enum_name):
    """Konstanten eines Enums: Name -> Wert."""
    pat = re.compile(r"^(?:public |private |internal )*enum " + re.escape(enum_name) + r" // TypeDefIndex: \d+", re.M)
    m = pat.search(dump_text)
    if m is None:
        raise KeyError(enum_name)
    end = dump_text.find("\n}\n", m.end())
    out = {}
    for cm in re.finditer(r"const [\w.]+ (\w+) = (-?\d+);", dump_text[m.end():end]):
        out[cm.group(1)] = int(cm.group(2))
    return out


def parse_method_rvas(dump_text, class_name, type_index=None):
    """Methodenname -> Liste der Ghidra-Adressen (Dump-RVA + 0x100000) einer Klasse."""
    pat = re.compile(r"^(?:public |private |internal |protected )*(?:sealed |static |abstract )*(?:class|struct) "
                     + re.escape(class_name) + r"(?: :[^\n/]*)? // TypeDefIndex: (\d+)", re.M)
    for m in pat.finditer(dump_text):
        if type_index is not None and int(m.group(1)) != type_index:
            continue
        end = dump_text.find("\n}\n", m.end())
        out = {}
        for mm in re.finditer(r"// RVA: 0x([0-9A-F]+) Offset: 0x[0-9A-F]+ VA: 0x[0-9A-F]+(?: Slot: \d+)?\n\t[^\n]*? ([\w.]+)\(", dump_text[m.end():end]):
            out.setdefault(mm.group(2), []).append(int(mm.group(1), 16) + IMAGE_BASE)
        return out
    raise KeyError(class_name)


class DumpTypes:
    def __init__(self, text=None):
        self.text = text if text is not None else bo.DUMP.read_text(errors="replace")
        self._cache = {}

    def fields(self, class_name, type_index=None):
        key = (class_name, type_index)
        if key not in self._cache:
            self._cache[key] = parse_class_fields(self.text, class_name, type_index)
        return self._cache[key]

    def field_size(self, f):
        t = f.type_name
        if t in PRIM_SIZES:
            return PRIM_SIZES[t]
        return 4 if t[0].isupper() and "." in t or t in ("EventID", "EventFactorType", "EventPriority") else 8


# ---------------------------------------------------------------------------------------------------------------
# Gast-Heap
# ---------------------------------------------------------------------------------------------------------------

class GuestHeap:
    """Objekte im Gastspeicher mit den Feldoffsets aus dump.cs.

    Feldzugriffe laufen ueber Namen; Groesse/Format kommen aus dem Dump-Typ. Referenzfelder sind 8 Byte, Enums
    werden ueber ``enum_sizes`` (Name -> Groesse) aufgeloest, damit nichts geraten wird.
    """
    DEFAULT_SIZE = 0x100

    def __init__(self, oracle, dump, enum_sizes=None):
        self.o = oracle
        self.dump = dump
        self.enum_sizes = enum_sizes or {}

    def new(self, class_name, size=None, type_index=None):
        if size is None:
            size = self.DEFAULT_SIZE
        return self.o.alloc(size)

    def _field(self, class_name, field, type_index=None):
        f = self.dump.fields(class_name, type_index)[field]
        if f.static:
            raise ValueError(f"{class_name}.{field} ist statisch")
        t = f.type_name
        if t in PRIM_FMT:
            return f, PRIM_FMT[t]
        if t in self.enum_sizes:
            return f, {1: "B", 2: "H", 4: "I"}[self.enum_sizes[t]]
        return f, "Q"

    def set(self, ptr, class_name, field, value, type_index=None):
        f, fmt = self._field(class_name, field, type_index)
        if fmt in "fd":
            blob = struct.pack("<" + fmt, value)
        else:
            size = struct.calcsize(fmt)
            blob = (int(value) & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        self.o.write(ptr + f.offset, blob)

    def get(self, ptr, class_name, field, type_index=None):
        f, fmt = self._field(class_name, field, type_index)
        size = struct.calcsize(fmt)
        return struct.unpack("<" + fmt, self.o.read(ptr + f.offset, size))[0]

    def offset(self, class_name, field, type_index=None):
        return self.dump.fields(class_name, type_index)[field].offset


# ---------------------------------------------------------------------------------------------------------------
# Orakel mit IL2CPP-Stubs und "yield"-Stubs
# ---------------------------------------------------------------------------------------------------------------

class GuestError(Exception):
    pass


OBJECT_NEW = 0x366700     # thunk_FUN_00366700: il2cpp_object_new(klass)
THROW_INDEX = 0x35C83C    # thunk_FUN_0035c83c: IndexOutOfRange-Ausnahme erzeugen
THROW_CAST = 0x35CDA0     # thunk_FUN_0035cda0: InvalidCast-Ausnahme erzeugen
THROW_RAISE = 0x3AFBC0    # FUN_003afbc0: Ausnahme ausloesen


class EventOracle(bo.Oracle):
    """Oracle + Objekt-Allokation, Ausnahmen als Fehler, yield-Stubs und verschachtelte Aufrufe."""

    NESTED_STACK = 0x4000

    def __init__(self):
        super().__init__()
        self.install_runtime_stubs()
        self._pending = None
        self._error = None
        self._yield_handlers = {}
        self._depth = 0
        self.stub(OBJECT_NEW, lambda o, a, b: o.alloc(0x100))
        for addr in (THROW_INDEX, THROW_CAST, THROW_RAISE):
            self._error_stub(addr)

    # -- Heap ---------------------------------------------------------------------------------------------------
    def alloc(self, size):
        """Wie Oracle.alloc, aber der Block ist garantiert genullt (der Heap wird zwischen Szenarien zurueckgesetzt)."""
        p = super().alloc(size)
        self.write(p, bytes((size + 15) & ~15))
        return p

    def heap_mark(self):
        return self._heap_ptr

    def heap_reset(self, mark):
        self._heap_ptr = mark

    # -- Fehler -------------------------------------------------------------------------------------------------
    def _error_stub(self, ghidra_addr):
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_PC
        target = ghidra_addr - IMAGE_BASE

        def hook(uc, address, size, _user):
            if address != target:
                return
            self._error = f"Gast-Ausnahme bei {ghidra_addr:#x} (LR={uc.reg_read(UC_ARM64_REG_LR) + IMAGE_BASE:#x})"
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
            uc.emu_stop()

        self._u.hook_add(UC_HOOK_CODE, hook, begin=target, end=target)

    # -- yield-Stubs --------------------------------------------------------------------------------------------
    def yield_stub(self, ghidra_addr, handler):
        """handler(oracle, x0..x3) laeuft ausserhalb der Emulation und liefert den Rueckgabewert (oder None)."""
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_LR, UC_ARM64_REG_PC
        target = ghidra_addr - IMAGE_BASE
        self._yield_handlers[target] = handler

        def hook(uc, address, size, _user):
            if address != target:
                return
            args = tuple(uc.reg_read(UC_ARM64_REG_X0 + i) for i in range(4))
            self._pending = (target, args)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
            uc.emu_stop()

        self._u.hook_add(UC_HOOK_CODE, hook, begin=target, end=target)

    def run(self, ghidra_addr, *args, max_insns=5_000_000):
        """Wie Oracle.call, aber mit yield-Stubs und verschachtelten Aufrufen (eigener Stack je Tiefe)."""
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_PC
        u = self._u
        for i, a in enumerate(args):
            u.reg_write(UC_ARM64_REG_X0 + i, a & 0xFFFFFFFFFFFFFFFF)
        u.reg_write(self._reg["sp"], STACK_TOP - 0x1000 - self._depth * self.NESTED_STACK)
        u.reg_write(self._reg["lr"], SENTINEL)
        pc = ghidra_addr - IMAGE_BASE
        while True:
            self._pending = None
            self._error = None
            u.emu_start(pc, SENTINEL, count=max_insns)
            if self._error:
                raise GuestError(self._error)
            if self._pending is None:
                break
            target, a = self._pending
            ctx = u.context_save()
            self._depth += 1
            try:
                ret = self._yield_handlers[target](self, *a)
            finally:
                self._depth -= 1
            u.context_restore(ctx)
            if ret is not None:
                u.reg_write(UC_ARM64_REG_X0, ret & 0xFFFFFFFFFFFFFFFF)
            pc = u.reg_read(UC_ARM64_REG_PC)
        return u.reg_read(self._x0)

    # -- Methodenzeiger-Slots -------------------------------------------------------------------------------------
    def populate_method_slots(self):
        """Jeder Metadaten-Methoden-Slot zeigt auf einen Datensatz [Methodenzeiger (vaddr), Ghidra-Adresse]."""
        sm = json.loads(bo.SCRIPT_JSON.read_text())
        self.method_names = {m["Address"] + IMAGE_BASE: m["Name"] for m in sm["ScriptMethod"]}
        self.slot_method = {}
        rec_base = self.alloc(16 * len(sm["ScriptMetadataMethod"]))
        for i, m in enumerate(sm["ScriptMetadataMethod"]):
            rec = rec_base + 16 * i
            self.write(rec, struct.pack("<QQ", m["MethodAddress"], m["MethodAddress"] + IMAGE_BASE))
            self.write(m["Address"], struct.pack("<Q", rec))
            self.slot_method[rec] = m["MethodAddress"] + IMAGE_BASE
        return self.method_names

    def method_name(self, ghidra_addr):
        return self.method_names.get(ghidra_addr, f"sub_{ghidra_addr:x}")

    def read_u32(self, vaddr):
        return struct.unpack("<I", self.read(vaddr, 4))[0]

    def read_u16(self, vaddr):
        return struct.unpack("<H", self.read(vaddr, 2))[0]


def decomp_text(name):
    return (bo.DECOMP_DIR / "battle_all" / name).read_text()


# ---------------------------------------------------------------------------------------------------------------
# Echte Funktionen des Ereignissystems (Ghidra-Adressen)
# ---------------------------------------------------------------------------------------------------------------

FN = {
    "container_ctor": 0x1E13270, "container_add": 0x1E13AB0, "container_remove": 0x1E13C40,
    "seek_type": 0x1E13C90, "seek_type_dep": 0x1E13CD0, "get_next": 0x1E13D20,
    "es_ctor": 0x19F41D0, "es_add": 0x19F4740, "es_remove": 0x19F4780, "es_remove_isolate": 0x19F4800,
    "es_sleep": 0x19F48C0, "es_wake": 0x19F4940, "es_wake_all": 0x19F49C0,
    "call": 0x19F4A00, "call_force": 0x19F4BA0, "call_target": 0x19F4C70,
    "push": 0x19F5510, "pop": 0x19F56A0, "check_cleared": 0x19F5880, "set": 0x19F5950, "const": 0x19F5B60,
    "once": 0x19F5C60, "recover": 0x19F5D60, "mulset": 0x19F5E10, "rewrite": 0x19F5F10, "mul": 0x19F5FC0,
    "get": 0x19F60A0, "get_if": 0x19F6100,
    "attach_skip": 0x1E0A0B0, "set_recall": 0x1E0A400, "tmp_item": 0x1E12840, "convert_isolate": 0x1E0A490,
    "set_work": 0x1E09DE0, "get_work": 0x1E09D60,
    "handler_invoke": 0x1E12B80, "skip_invoke": 0x1E12F40,
    "pokecon_get": 0x2137310, "pokecon_get_const": 0x2137250,
    "bpp_check_sick": 0x20D8B30, "bpp_gas": 0x20DDB80, "bpp_hensin": 0x20DD470, "bpp_gmode": 0x20DB9A0,
    "bpp_turnflag": 0x20DFE70, "ommit_hensin": 0x2079980, "ommit_g": 0x2079A30, "item_param": 0x20752A0,
}

DECOMP_FILES = [
    "Dpr_Battle_Logic_EventFactor.c", "Dpr_Battle_Logic_EventFactor_Data.c", "Dpr_Battle_Logic_EventFactorContainer.c",
    "Dpr_Battle_Logic_EventSystem.c", "Dpr_Battle_Logic_EventVar.c", "Dpr_Battle_Logic_EventVarSet.c",
    "Dpr_Battle_Logic_EventVarStack.c", "Dpr_Battle_Logic_EventVarSetStack.c",
    "Dpr_Battle_Logic_EventFactor_EventHandlerArgs.c", "Dpr_Battle_Logic_EventFactor_SkipCheckHandlerArgs.c",
    "Dpr_Battle_Logic_Common.c",
]

# Datenfelder (Offsets aus dump.cs, siehe tests): EventFactor.Data
D_TABLE, D_SKIP, D_TYPE, D_PRI, D_SUBID, D_DEPEND, D_POKEID, D_LEVEL, D_NUM = 0x10, 0x18, 0x20, 0x24, 0x28, 0x2A, 0x2B, 0x2C, 0x30
D_CALLING, D_RECALL, D_RMRES, D_SLEEP, D_TMPITEM, D_EXIST, D_WORK = 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x40
S_LEVEL = 0x58          # EventSystem.m_eventLevel
S_VARSTACK, S_SETSTACK, S_CURSET = 0x40, 0x48, 0x50


class EventWorld:
    """Ein EventSystem samt Container, BattleEnv und simulierten Pokemon im Gastspeicher; alle Operationen
    laufen ueber die echten Gastfunktionen."""

    def __init__(self, o, env=None):
        self.o = o
        self.mark = o.heap_mark()
        self.env = env or {}
        self.effects = {}          # Delegat-Zeiger -> (event, ops | ("real", adresse))
        self.skip_rules = {}       # Delegat-Zeiger -> Regelliste
        self.added = []            # Faktorzeiger in Registrierungsreihenfolge
        self.log = []
        self.pokes = {}            # Poke-Zeiger -> Konfiguration
        self.poke_by_id = {}
        if not getattr(o, "_event_stubs", False):
            for name in DECOMP_FILES:
                o.prepare(decomp_text(name))
            self._install_stubs()
            o._event_stubs = True
        o.world = self
        self._build()

    # -- Aufbau -------------------------------------------------------------------------------------------------
    def _build(self):
        o = self.o
        self.container = o.alloc(0x40)
        o.run(FN["container_ctor"], self.container)
        benv = o.alloc(0x100)
        o.write(benv + 0x30, struct.pack("<Q", self.container))
        pokecon = o.alloc(0x40)
        o.write(benv + 0x10, struct.pack("<Q", pokecon))
        fstatus = o.alloc(0x40)
        o.write(benv + 0x18, struct.pack("<Q", fstatus))
        fdata = o.alloc(0x80)
        o.write(fstatus + 0x10, struct.pack("<Q", fdata))
        effects = o.make_array(1, [1 if i in self.env.get("fieldEffects", []) else 0 for i in range(10)])
        o.write(fdata + 0x48, struct.pack("<Q", effects))
        self.benv, self.pokecon = benv, pokecon
        setup = o.alloc(0x80)
        o.write(setup + 0x18, struct.pack("<Q", benv))
        slot = o.alloc(8)
        o.write(slot, struct.pack("<Q", setup))
        self.es = o.alloc(0x80)
        o.run(FN["es_ctor"], self.es, slot)
        for pid, cfg in self.env.get("pokes", {}).items():
            ptr = o.alloc(0x20)
            self.pokes[ptr] = cfg
            self.poke_by_id[int(pid)] = ptr

    def _install_stubs(self):
        """Stubs werden einmal je Orakel installiert und greifen auf ``o.world`` (das aktuelle Szenario) zu."""
        o = self.o
        o.yield_stub(FN["handler_invoke"], lambda *a: o.world._invoke_handler(*a))
        o.yield_stub(FN["skip_invoke"], lambda *a: o.world._invoke_skip(*a))
        get_poke = lambda _o, _pc, pid: o.world.poke_by_id.get(pid & 0xFF, 0)  # noqa: E731
        o.stub(FN["pokecon_get"], get_poke)
        o.stub(FN["pokecon_get_const"], get_poke)
        o.stub(FN["bpp_check_sick"], lambda _o, p, sid: int(sid in o.world.pokes[p].get("sick", [])))
        o.stub(FN["bpp_gas"], lambda _o, p, _b: int(o.world.pokes[p].get("gas", 0)))
        o.stub(FN["bpp_hensin"], lambda _o, p, _b: int(o.world.pokes[p].get("hensin", 0)))
        o.stub(FN["bpp_gmode"], lambda _o, p, _b: int(o.world.pokes[p].get("gmode", 0)))
        o.stub(FN["bpp_turnflag"], lambda _o, p, f: int(f in o.world.pokes[p].get("turnFlags", [])))
        o.stub(FN["ommit_hensin"], lambda _o, sub, _b: int((sub & 0xFFFF) in o.world.env.get("ommitHensin", [])))
        o.stub(FN["ommit_g"], lambda _o, sub, _b: int((sub & 0xFFFF) in o.world.env.get("ommitG", [])))
        o.stub(FN["item_param"], lambda _o, _item, _pid: o.world.env.get("itemParam", 0))

    def release(self):
        self.o.heap_reset(self.mark)

    # -- Zugriffe -----------------------------------------------------------------------------------------------
    def u8(self, a):
        return self.o.read(a, 1)[0]

    def i32(self, a):
        return bo.to_s32(self.o.read_u32(a))

    def data(self, factor):
        return self.o.u64(factor + 0x28)

    def instance_id(self, factor):
        return self.o.read_u16(factor + 0x10)

    def level(self):
        return self.o.read_u32(self.es + S_LEVEL)

    def es_call(self, name, *args):
        return self.o.run(FN[name], self.es, *args)

    # -- Faktor anlegen -----------------------------------------------------------------------------------------
    def add_factor(self, spec):
        o = self.o
        entries = spec.get("entries", [])
        table = []
        for ent in entries:
            tbl = o.alloc(0x20)
            dg = o.alloc(0x30)
            o.write(tbl + 0x10, struct.pack("<H", ent["event"]))
            o.write(tbl + 0x18, struct.pack("<Q", dg))
            self.effects[dg] = (ent["event"], ent.get("ops", []), ent.get("real"))
            table.append(tbl)
        arr = o.make_ptr_array(table)
        num = spec.get("num", len(entries))
        args = (spec["type"], spec["subID"], spec["mainPri"], spec["subPri"], spec["dependID"], arr, num)
        # EventSystem.AddFactor @0x19f4740 uebergibt dem Container die aktuelle Ereignistiefe (m_eventLevel) als Faktor-Stufe
        factor = self.es_call("es_add", *args)
        if factor and spec.get("skip") is not None:
            dg = o.alloc(0x30)
            self.skip_rules[dg] = spec["skip"]
            o.run(FN["attach_skip"], factor, dg)
        self.added.append(factor)
        return factor

    # -- Handler-Aufruf (yield) ---------------------------------------------------------------------------------
    def _invoke_handler(self, o, dg, args_slot, depend, _x3):
        event, ops, real = self.effects[dg]
        args = o.u64(args_slot)
        factor = o.u64(args + 0x50)
        self.log.append([event, self.instance_id(factor), depend & 0xFF, self.level()])
        if real is not None:
            o.run(real, args_slot, depend & 0xFF)
        self.exec_ops(ops, factor)
        return None

    def _invoke_skip(self, o, dg, args_slot, _x2, _x3):
        args = o.u64(args_slot)
        event = o.read_u16(args + 0x28)
        ftype = self.u8(args + 0x2A)
        sub = o.read_u16(args + 0x2C)
        for rule in self.skip_rules[dg]:
            if all(r == -1 or r == v for r, v in zip(rule, (event, ftype, sub))):
                return 1
        return 0

    # -- Operationen (Szenario-Schritte und Handler-Rumpf) -------------------------------------------------------
    def exec_ops(self, ops, my_factor=None):
        for op in ops:
            self.exec_op(op, my_factor)

    def exec_op(self, op, my_factor=None):
        o = self.o
        name = op[0]
        if name in ("call", "call_force"):
            if self.level() < 4:
                self.es_call(name, op[1])
        elif name == "call_target":
            if self.level() < 4:
                self.es_call("call_target", op[1], op[2])
        elif name in ("push", "pop", "check_cleared", "remove_isolate", "wake_all"):
            self.es_call({"remove_isolate": "es_remove_isolate", "wake_all": "es_wake_all"}.get(name, name))
        elif name in ("set", "const", "once", "mul"):
            self.es_call(name, op[1], op[2] & 0xFFFFFFFF)
        elif name == "mulset":
            self.es_call("mulset", op[1], op[2] & 0xFFFFFFFF, op[3] & 0xFFFFFFFF, op[4] & 0xFFFFFFFF)
        elif name == "recover":
            self.es_call("recover", op[1])
        elif name == "rewrite":
            r = self.es_call("rewrite", op[1], op[2] & 0xFFFFFFFF)
            self.log.append([-2, op[1], r & 1, 0])
        elif name == "val":
            self.log.append([-1, op[1], bo.to_s32(self.es_call("get", op[1])), 0])
        elif name == "remove_self":
            self.es_call("es_remove", my_factor)
        elif name == "remove":
            if op[1] < len(self.added):
                self.es_call("es_remove", self.added[op[1]])
        elif name == "recall":
            o.run(FN["set_recall"], my_factor)
        elif name == "tmpitem":
            o.run(FN["tmp_item"], my_factor if my_factor else self.added[op[1]])
        elif name == "setwork":
            o.run(FN["set_work"], my_factor, op[1], op[2] & 0xFFFFFFFF)
        elif name == "getwork":
            self.log.append([-3, op[1], bo.to_s32(o.run(FN["get_work"], my_factor, op[1])), 0])
        elif name == "add":
            if len(self.added) < 14:
                self.add_factor(op[1])
        elif name == "sleep":
            self.es_call("es_sleep", op[1], op[2])
        elif name == "wake":
            self.es_call("es_wake", op[1], op[2])
        elif name == "isolate":
            o.run(FN["convert_isolate"], self.added[op[1]])
        else:
            raise ValueError(op)

    # -- Zustand auslesen ---------------------------------------------------------------------------------------
    def factor_list(self):
        """Faktoren in Aufrufreihenfolge (Kopf der laufenden Liste an)."""
        o = self.o
        out = []
        f = o.u64(self.container + 0x18)
        while f:
            d = self.data(f)
            out.append([self.instance_id(f), self.u8(d + D_TYPE), o.read_u16(d + D_SUBID), o.read_u32(d + D_PRI),
                        self.u8(d + D_DEPEND), self.u8(d + D_POKEID), o.read_u32(d + D_NUM) & 0xFF, o.read_u32(d + D_LEVEL),
                        self.u8(d + D_CALLING), self.u8(d + D_RECALL), self.u8(d + D_RMRES), self.u8(d + D_SLEEP),
                        self.u8(d + D_TMPITEM), self.u8(d + D_EXIST)])
            f = o.u64(f + 0x20)
        return out

    def stored_count(self):
        n, f = 0, self.o.u64(self.container + 0x20)
        while f:
            n += 1
            f = self.o.u64(f + 0x20)
        return n

    def snapshot_vars(self):
        """Alle belegten Slots des EventVar-Stapels: [index, label, state, value, min, max]."""
        o = self.o
        stack = o.u64(self.es + S_VARSTACK)
        arr = o.u64(stack + 0x10)
        out = []
        for i in range(o.read_u32(arr + 0x18)):
            var = o.u64(arr + 0x20 + 8 * i)
            label = o.read_u16(var + 0x10)
            if label:
                out.append([i, label, self.u8(var + 0x12), self.i32(var + 0x14), self.i32(var + 0x18), self.i32(var + 0x1C)])
        return out

    def stack_pointers(self):
        o = self.o
        return [o.read_u32(o.u64(self.es + S_VARSTACK) + 0x18), o.read_u32(o.u64(self.es + S_SETSTACK) + 0x18)]


# ---------------------------------------------------------------------------------------------------------------
# Szenarien -> Fixtures
# ---------------------------------------------------------------------------------------------------------------

def rng_for(name):
    return random.Random("xnu-battle-events-" + name)


def _fresh():
    o = EventOracle()
    return o


def gen_var(o=None):
    """EventVar-Rechnungen und Stapel: zufaellige Operationsfolgen gegen die echten EVENTVAR_*-Funktionen."""
    o = o or _fresh()
    rnd = rng_for("var")
    labels = [2, 3, 4, 0x12, 0x16, 0x1B, 0x2E, 0x33, 0x34, 0x35, 0x38, 0x3D, 0x4C, 0x5A, 0x73, 123, 124, 200]
    ratios = [0x1000, 0x800, 0x2000, 0x1800, 0x14CD, 0xC00, 0x1333, 0, 1, 0x10000, -0x1000]
    cases = []
    for ci in range(70):
        ops = [["push"]]
        pool = rnd.sample(labels, 5)
        n = rnd.randint(6, 40) if ci < 60 else 200
        for _ in range(n):
            k = rnd.random()
            lab = rnd.choice(pool)
            val = rnd.choice([0, 1, -1, 0x1000, 100, 0x7FFFFFFF, -0x80000000, rnd.randint(-5000, 5000), rnd.randint(0, 0x30000)])
            if k < 0.07:
                ops.append(["push"])
            elif k < 0.14:
                ops.append(["pop"])
            elif k < 0.22:
                ops.append(["set", lab, val])
            elif k < 0.29:
                ops.append(["const", lab, val])
            elif k < 0.36:
                ops.append(["once", lab, val])
            elif k < 0.46:
                lo, hi = rnd.choice([(0, 0), (0x29, 0x20000), (0x19A, 0x20000), (0x29, 0x200000), (5, 0), (0, 100), (-50, 50)])
                ops.append(["mulset", lab, val, lo, hi])
            elif k < 0.56:
                ops.append(["rewrite", lab, val])
            elif k < 0.70:
                ops.append(["mul", lab, rnd.choice(ratios)])
            elif k < 0.85:
                ops.append(["get", lab])
            elif k < 0.93:
                ops.append(["getif", lab])
            elif k < 0.97:
                ops.append(["recover", lab])
            else:
                ops.append(["check_cleared"])
        cases.append(run_var_case(o, ops))
    return {"cases": cases}


def run_var_case(o, ops):
    w = EventWorld(o)
    out = []
    for op in ops:
        name = op[0]
        ret = 0
        if name == "get":
            ret = bo.to_s32(w.es_call("get", op[1]))
        elif name == "getif":
            buf = o.alloc(16)
            flag = w.es_call("get_if", op[1], buf) & 1
            ret = [flag, bo.to_s32(o.read_u32(buf))]
        elif name == "rewrite":
            ret = w.es_call("rewrite", op[1], op[2] & 0xFFFFFFFF) & 1
        else:
            w.exec_op(op)
        sp = w.stack_pointers()
        out.append([ret, sp[0], sp[1]] if not isinstance(ret, list) else [ret[0], ret[1], sp[0], sp[1]])
    snap = w.snapshot_vars()
    w.release()
    return {"ops": ops, "out": out, "slots": snap}


def spec_random(rnd, allow_ops=True, depth=0):
    ftype = rnd.choice([0, 0, 1, 2, 3, 4, 5, 6, 7, 8])
    ents = []
    for _ in range(rnd.randint(1, 3)):
        ev = rnd.choice([1, 1, 2, 2, 3, 3, 0x8E])
        ents.append({"event": ev, "ops": ops_random(rnd, depth) if allow_ops else []})
    spec = {"type": ftype, "subID": rnd.randint(0, 300), "mainPri": rnd.randint(0, 9),
            "subPri": rnd.choice([0, 1, rnd.randint(0, 600), rnd.randint(0, 0xFFFFFF)]),
            "dependID": rnd.choice([0, 1, 2, 3, 0x1F]), "entries": ents}
    if rnd.random() < 0.12:
        spec["skip"] = [[rnd.choice([-1, 1, 2, 3, 4, 5]), rnd.choice([-1, 0, 4, 5]), rnd.choice([-1, 5, 10, 100])] for _ in range(rnd.randint(1, 2))]
    return spec


def ops_random(rnd, depth=0):
    ops = []
    for _ in range(rnd.randint(0, 4)):
        k = rnd.random()
        if k < 0.14:
            ops.append(["remove_self"])
        elif k < 0.24:
            ops.append(["remove", rnd.randint(0, 5)])
        elif k < 0.40:
            ops.append(["call", rnd.choice([1, 2, 3])])
        elif k < 0.45:
            ops.append(["call_force", rnd.choice([1, 2, 3])])
        elif k < 0.50:
            ops.append(["call_target", rnd.choice([1, 2, 3]), rnd.choice([0, 4, 5, 9])])
        elif k < 0.55:
            ops.append(["recall"])
        elif k < 0.62:
            ops.append(["push"])
        elif k < 0.68:
            ops.append(["pop"])
        elif k < 0.76:
            ops.append(["set", rnd.choice([3, 4, 0x38]), rnd.randint(-100, 5000)])
        elif k < 0.82:
            ops.append(["mul", 0x38, rnd.choice([0x800, 0x1000, 0x2000, 0x14CD])])
        elif k < 0.87:
            ops.append(["val", rnd.choice([3, 4, 0x38])])
        elif k < 0.91:
            ops.append(["setwork", rnd.randint(0, 6), rnd.randint(-9, 99)])
        elif k < 0.94:
            ops.append(["getwork", rnd.randint(0, 6)])
        elif k < 0.97 and depth < 1:
            ops.append(["add", spec_random(rnd, True, depth + 1)])
        else:
            ops.append(["sleep", rnd.choice([0, 1, 2, 3]), rnd.choice([0, 4, 5])])
    return ops


def random_env(rnd):
    pokes = {}
    for pid in range(0, 4):
        pokes[str(pid)] = {"sick": [s for s in (0x10, 0x13) if rnd.random() < 0.2], "gas": int(rnd.random() < 0.1),
                           "hensin": int(rnd.random() < 0.2), "gmode": int(rnd.random() < 0.2),
                           "turnFlags": [9] if rnd.random() < 0.2 else []}
    return {"pokes": pokes, "fieldEffects": [5] if rnd.random() < 0.25 else [],
            "ommitHensin": [rnd.randint(0, 300) for _ in range(40)], "ommitG": [rnd.randint(0, 300) for _ in range(40)]}


def run_call_case(o, case):
    w = EventWorld(o, case["env"])
    for spec in case["adds"]:
        w.add_factor(spec)
    w.log.clear()
    for step in case["steps"]:
        w.exec_op(step)
    res = {"log": w.log, "after": w.factor_list(), "stored": w.stored_count(), "level": w.level(), "vars": w.snapshot_vars(),
           "sp": w.stack_pointers()}
    w.release()
    return res


def gen_call(o=None):
    """Aufruf-Schleife: CallEvent mit Handlern, die Faktoren entfernen/hinzufuegen, verschachtelt aufrufen, Variablen aendern."""
    o = o or _fresh()
    rnd = rng_for("call")
    cases = []
    for _ in range(160):
        case = {"env": random_env(rnd), "adds": [spec_random(rnd) for _ in range(rnd.randint(3, 10))], "steps": [["push"]]}
        for pid in (3, 4, 0x38):
            case["steps"].append(["set", pid, rnd.randint(0, 2000)])
        for _ in range(rnd.randint(1, 4)):
            k = rnd.random()
            ev = rnd.choice([1, 2, 3, 1, 2, 3, 0x8E])
            if k < 0.6:
                case["steps"].append(["call", ev])
            elif k < 0.75:
                case["steps"].append(["call_force", ev])
            elif k < 0.9:
                case["steps"].append(["call_target", ev, rnd.choice([0, 1, 4, 5, 9])])
            else:
                case["steps"].append(["wake_all"])
        case["steps"].append(["val", 0x38])
        case.update(run_call_case(o, case))
        cases.append(case)
    return {"cases": cases}


def gen_order(o=None):
    """Registrierung/Reihenfolge: AddFactor/RemoveFactor, Prioritaeten, Gleichstand, Seek/GetNext, Pool-Erschoepfung."""
    o = o or _fresh()
    rnd = rng_for("order")
    cases = []
    for ci in range(60):
        n = rnd.randint(2, 30)
        specs = []
        for _ in range(n):
            s = {"type": rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8]), "subID": rnd.randint(0, 300), "mainPri": rnd.randint(0, 9),
                 "subPri": rnd.choice([0, 1, 5, rnd.randint(0, 800), rnd.randint(0, 0xFFFFFF)]),
                 "dependID": rnd.choice([0, 1, 2, 3, 4, 5]), "entries": [{"event": rnd.randint(1, 4)}]}
            specs.append(s)
        removes = rnd.sample(range(n), rnd.randint(0, n // 2))
        queries = [[rnd.choice([0, 1, 2, 3, 4, 5]), rnd.choice([0, 1, 2, 3, 4, 5])] for _ in range(4)]
        w = EventWorld(o)
        for s in specs:
            w.add_factor(s)
        for k in removes:
            w.es_call("es_remove", w.added[k])
        order = w.factor_list()
        seek = []
        for ftype, dep in queries:
            first_t = o.run(FN["seek_type"], w.container, ftype)
            first_td = o.run(FN["seek_type_dep"], w.container, ftype, dep)
            seq_t, seq_td = [], []
            f = first_t
            while f and len(seq_t) < 80:
                seq_t.append(w.instance_id(f))
                f = o.run(FN["get_next"], w.container, f, 1)
            f = first_td
            while f and len(seq_td) < 80:
                seq_td.append(w.instance_id(f))
                f = o.run(FN["get_next"], w.container, f, 0)
            seek.append({"type": ftype, "depend": dep, "byType": seq_t, "byTypeDepend": seq_td,
                         "firstType": w.instance_id(first_t) if first_t else -1,
                         "firstTypeDepend": w.instance_id(first_td) if first_td else -1})
        cases.append({"adds": specs, "removes": removes, "order": order, "stored": w.stored_count(), "seek": seek,
                      "ids": [w.instance_id(f) if f else -1 for f in w.added]})
        w.release()
    # Pool-Erschoepfung: 172 Faktoren, der 173. liefert null
    w = EventWorld(o)
    specs = [{"type": 4, "subID": i, "mainPri": 7, "subPri": i % 7, "dependID": i % 6, "entries": [{"event": 1}]} for i in range(175)]
    for s in specs:
        w.add_factor(s)
    cases.append({"adds": specs, "removes": [], "order": w.factor_list(), "stored": w.stored_count(), "seek": [],
                  "ids": [w.instance_id(f) if f else -1 for f in w.added]})
    w.release()
    return {"cases": cases}


HANDLERS = [
    # (Name, Faktortyp, Haupt-prioritaet, Id (subID), Ereignis, Ghidra-Adresse des echten Handlers)
    ("Tikaramoti", 4, 7, 37, 74, 0x1A3F7B0),
    ("AtuiSibou", 4, 7, 47, 74, 0x1A3F640),
    ("Fukugan", 4, 7, 14, 64, 0x1A40A00),
    ("Tekunisyan", 4, 7, 101, 70, 0x1A43500),
    ("KodawariHachimaki", 5, 8, 220, 74, 0x1A12600),
    ("KoukakuLens", 5, 8, 265, 64, 0x1A10D30),
    ("MonosiriMegane", 5, 8, 267, 70, 0x1A11A80),
    ("TatuzinNoObi", 5, 8, 268, 90, 0x1A13910),
    ("InotiNoTama", 5, 8, 270, 90, 0x1A13CF0),
]
ITEM_RATIO_FN = 0x1A05D30


def gen_handlers(o=None):
    """Die echten Handler-Funktionen (Tokusei/Item) laufen im echten Ereignissystem; Variablen vorher/nachher als Zahlen."""
    o = o or _fresh()
    o.prepare(decomp_text("Dpr_Battle_Logic_Handler_Tokusei.c"))
    o.prepare(decomp_text("Dpr_Battle_Logic_Handler_Item.c"))
    rnd = rng_for("handlers")
    cases = []
    for name, ftype, pri, hid, event, addr in HANDLERS:
        for _ in range(80):
            my = rnd.randint(0, 3)
            atk = my if rnd.random() < 0.6 else rnd.randint(0, 3)
            dfn = my if rnd.random() < 0.5 else rnd.randint(0, 3)
            env = random_env(rnd)
            env["itemParam"] = rnd.choice([0, 10, 20, 30, 50, -50, -100, -99, rnd.randint(-120, 400), rnd.randint(0, 5000)])
            env["pokes"][str(my)]["gmode"] = int(rnd.random() < 0.3)
            env["pokes"][str(my)]["sick"] = []
            env["pokes"][str(my)]["gas"] = 0
            env["pokes"][str(my)]["hensin"] = 0
            env["fieldEffects"] = []
            env["ommitHensin"] = []
            env["ommitG"] = []
            spec = {"type": ftype, "subID": hid, "mainPri": pri, "subPri": rnd.randint(0, 400), "dependID": my,
                    "entries": [{"event": event, "ops": [], "real": addr}]}
            start_ratio = rnd.choice([0x1000, 0x1000, 0x800, 0x2000, 0x1333])
            lo, hi = rnd.choice([(0x29, 0x20000), (0x19A, 0x20000), (0, 0)])
            steps = [["push"], ["const", 3, atk], ["const", 4, dfn], ["const", 27, rnd.choice([0, 1, 1, 2, 2])],
                     ["const", 22, rnd.choice([0, 9, 14, 14, 9, 5, 17, 18])], ["const", 61, rnd.randint(0, 13)],
                     ["once", 51, rnd.choice([0, 20, 40, 60, 61, 80, rnd.randint(0, 250)])],
                     ["mulset", 56, start_ratio, lo, hi], ["mulset", 52, rnd.choice([0x1000, 0x1000, 0x800]), 0x29, 0x200000],
                     ["call", event], ["val", 56], ["val", 52]]
            case = {"handler": name, "event": event, "env": env, "adds": [spec], "steps": steps}
            case.update(run_call_case(o, case))
            cases.append(case)
    # item_AttackValue_to_Ratio: echter Gleitkomma-Code gegen die C#-Formel
    ratios = []
    world_env = {"itemParam": 0}
    w = EventWorld(o, world_env)
    f = w.add_factor({"type": 5, "subID": 268, "mainPri": 8, "subPri": 0, "dependID": 0, "entries": []})
    for v in list(range(-150, 700)) + [rnd.randint(-5000, 100000) for _ in range(200)]:
        w.env["itemParam"] = v
        ratios.append([v, bo.to_s32(o.run(ITEM_RATIO_FN, f))])
    w.release()
    return {"cases": cases, "itemRatios": ratios}


HANDLER_CLASSES = {
    # Klasse: (.cctor-Adresse, PTR_DAT-Slot der Klasse, TypeDefIndex im Dump); die cctor-Pseudocodes von Tokusei/Item/Waza fehlen
    # im Export (Decompiler-Timeout), die echten .cctor laufen hier stattdessen in Unicorn.
    "Tokusei": (0x1A64ED0, 0x4C8BB58, 11059),
    "Item": (0x1A22680, 0x4C89668, 11045),
    "Waza": (0x1929850, 0x4C7EF68, 11064),
    "Side": (0x1A3CB90, 0x4C7F078, 11056),
    "Field": (0x1A04220, 0x4C89428, 11042),
    "Pos": (0x1A37240, 0x4C84EE0, 11050),
    "DefaultPowerUp": (0x1A01A90, 0x4C893D8, 11039),
    "RaidBoss": (0x1A38260, 0x4C8B770, 11053),
}


def gen_handler_tables(o=None):
    """Fuehrt die echten .cctor der Handler-Klassen aus und liest die Tabellen Ereignis -> Handler-Funktion aus.

    Rueckgabe: {Klasse: {Tabellenname: [[eventID, Methodenname], ...]}}. Die Methodenzeiger stammen aus den
    Metadaten-Slots (populate_method_slots), die Namen aus script.json.
    """
    o = o or _fresh()
    o.populate_method_slots()
    dump = DumpTypes()
    out = {}
    for cls, (cctor, ptr, type_index) in HANDLER_CLASSES.items():
        fields = dump.fields(cls, type_index)
        _klass, statics = o.make_class(ptr, [])
        o.run(cctor, max_insns=50_000_000)
        tables = {}
        for name, f in fields.items():
            if not (f.static and name.startswith("HandlerTable_")):
                continue
            arr = o.u64(statics + f.offset)
            entries = []
            if arr:
                for i in range(o.read_u32(arr + 0x18)):
                    elem = o.u64(arr + 0x20 + 8 * i)
                    delegate = o.u64(elem + 0x18)
                    method = o.u64(delegate + 0x10) if delegate else 0
                    entries.append([o.read_u16(elem + 0x10), o.method_name(method + IMAGE_BASE) if method else None])
            tables[name] = entries
        out[cls] = tables
    return out


def summarize_handler_tables(tables):
    """Zahlen je Klasse: Tabellen, Eintraege, verschiedene Handler-Funktionen, Ereignis-Haeufigkeit."""
    summary = {}
    for cls, tbls in tables.items():
        entries = [e for t in tbls.values() for e in t]
        freq = {}
        for ev, _name in entries:
            freq[ev] = freq.get(ev, 0) + 1
        summary[cls] = {
            "tables": len(tbls), "entries": len(entries), "distinctFunctions": len({n for _e, n in entries}),
            "maxEntriesPerTable": max((len(t) for t in tbls.values()), default=0),
            "eventFrequency": dict(sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))),
        }
    return summary


GROUPS = {
    "var": ("BattleEventsVar.json", gen_var),
    "order": ("BattleEventsOrder.json", gen_order),
    "call": ("BattleEventsCall.json", gen_call),
    "handlers": ("BattleEventsHandlers.json", gen_handlers),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", nargs="*", choices=sorted(GROUPS))
    ap.add_argument("--tables", metavar="DATEI", nargs="?", const=str(ROOT / "work/battleevents/handler_tables.json"),
                    help="nur die Handler-Tabellen (Ereignis -> Funktion je Klasse) auslesen und mit Zusammenfassung speichern")
    args = ap.parse_args(argv)
    if args.tables:
        tables = gen_handler_tables()
        summary = summarize_handler_tables(tables)
        path = Path(args.tables)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tables": tables, "summary": summary}, indent=1) + "\n")
        for cls, s in summary.items():
            print(f"{cls}: {s['tables']} Tabellen, {s['entries']} Eintraege, {s['distinctFunctions']} Funktionen")
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    o = EventOracle()
    for name, (filename, fn) in GROUPS.items():
        if args.only and name not in args.only:
            continue
        data = fn(o)
        (out / filename).write_text(json.dumps(data, separators=(",", ":")) + "\n")
        print(f"{name}: {filename} ({len(data['cases'])} Faelle)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
