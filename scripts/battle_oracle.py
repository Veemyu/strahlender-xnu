#!/usr/bin/env python3
"""Emulations-Orakel fuer die Kampfmathematik (Scheibe 1).

Laedt work/elf/main.patched.elf in Unicorn (AArch64), wendet die relativen Relokationen an, bereitet minimale
IL2CPP-Strukturen (Klassenobjekte mit statischen Feldern, Arrays) vor und fuehrt die ECHTEN Spielfunktionen aus.
Die Ergebnisse landen als reine Zahlen-JSON-Fixtures in unity/Assets/Tests/EditMode/Fixtures/.

Adressen: Ghidra-Adresse = ELF-vaddr + 0x100000 (Image Base). Alle Funktionsadressen unten sind Ghidra-Adressen.

Aufruf:  PYTHONPATH=tools/pydeps python3 scripts/battle_oracle.py [--out DIR] [--only NAME ...]
Die Eingaben werden aus einem festen Seed erzeugt, damit die Fixtures reproduzierbar sind.
"""
import argparse
import json
import random
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELF = ROOT / "work/elf/main.patched.elf"
DUMP = ROOT / "work/il2cpp/dump.cs"
SCRIPT_JSON = ROOT / "work/il2cpp/script.json"
METADATA = ROOT / "work/romfs/Data/Managed/Metadata/global-metadata.dat"
DECOMP_DIR = ROOT / "work/decomp"
DEFAULT_OUT = ROOT / "unity/Assets/Tests/EditMode/Fixtures"
IMAGE_BASE = 0x100000

R_AARCH64_RELATIVE = 1027

STACK_TOP = 0x7F000000
STACK_SIZE = 0x100000
HEAP_BASE = 0x60000000
HEAP_SIZE = 0x1000000
SENTINEL = 0x7D000000  # Ruecksprungziel; Emulation endet hier


# ---------------------------------------------------------------------------------------------------------------
# Reine Hilfslogik (ohne Unicorn testbar, siehe scripts/tests/test_battle_oracle.py)
# ---------------------------------------------------------------------------------------------------------------

def to_u32(v):
    return v & 0xFFFFFFFF


def to_s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def parse_elf_segments(data):
    """Liefert die PT_LOAD-Segmente als Liste von (vaddr, file_offset, file_size, mem_size)."""
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    segs = []
    for i in range(phnum):
        p_type, _flags, off, vaddr, _paddr, filesz, memsz, _align = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
        if p_type == 1:
            segs.append((vaddr, off, filesz, memsz))
    return segs


def parse_dynamic(data, segs):
    """Liest DT_RELA/DT_RELASZ aus dem PT_DYNAMIC-Segment."""
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    for i in range(phnum):
        p_type, _flags, off, _vaddr, _paddr, filesz, _memsz, _align = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
        if p_type == 2:
            dyn = {}
            for j in range(filesz // 16):
                tag, val = struct.unpack_from("<qQ", data, off + j * 16)
                if tag == 0:
                    break
                dyn.setdefault(tag, val)
            return dyn
    return {}


def vaddr_to_offset(segs, vaddr):
    for va, off, filesz, _memsz in segs:
        if va <= vaddr < va + filesz:
            return off + (vaddr - va)
    raise KeyError(hex(vaddr))


def decomp_dat_flags(source):
    """Alle DAT_xxxxxxxx, die als IL2CPP-Init-Flag (`DAT_x & 1) == 0`) geprueft werden (Ghidra-Adressen)."""
    return sorted({int(m, 16) for m in re.findall(r"\(DAT_([0-9a-f]{8}) & 1\) == 0", source)})


def parse_array_hashes(dump_text, metadata=None):
    """hash -> Rohbytes der statischen Array-Initialisierer (RVA-Felder) der Spielassembly.

    Grosse Initialisierer stehen als `__StaticArrayInitTypeSize=N` mit Metadaten-Offset; kleine (<= 8 Byte) stehen als
    int/uint/long/ulong-Konstante direkt im Dump (Little Endian).
    """
    out = {}
    if metadata is not None:
        for m in re.finditer(r"__StaticArrayInitTypeSize=(\d+) ([0-9A-F]{40}) /\*Metadata offset 0x([0-9A-F]+)\*/", dump_text):
            off, size = int(m.group(3), 16), int(m.group(1))
            out[m.group(2)] = metadata[off:off + size]
    sizes = {"int": 4, "uint": 4, "long": 8, "ulong": 8, "short": 2, "ushort": 2, "byte": 1, "sbyte": 1}
    for m in re.finditer(r"internal static readonly (int|uint|long|ulong|short|ushort|byte|sbyte) ([0-9A-F]{40}) = (-?\d+);", dump_text):
        n = sizes[m.group(1)]
        out[m.group(2)] = (int(m.group(3)) & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
    return out


def growth_exp(curve, n):
    """Erfahrung fuer Level n nach den klassischen Wachstumsformeln (Ganzzahldivision, Level 1 = 0).

    curve: 0 mittel-schnell, 1 unregelmaessig, 2 schwankend, 3 mittel-langsam, 4 schnell, 5 langsam.
    """
    if n <= 1:
        return 0
    c = n ** 3
    if curve == 0:
        v = c
    elif curve == 1:
        if n <= 50:
            v = c * (100 - n) // 50
        elif n <= 68:
            v = c * (150 - n) // 100
        elif n <= 98:
            v = c * ((1911 - 10 * n) // 3) // 500
        else:
            v = c * (160 - n) // 100
    elif curve == 2:
        if n <= 15:
            v = c * ((n + 1) // 3 + 24) // 50
        elif n <= 35:
            v = c * (n + 14) // 50
        else:
            v = c * (n // 2 + 32) // 50
    elif curve == 3:
        v = 6 * c // 5 - 15 * n * n + 100 * n - 140
    elif curve == 4:
        v = 4 * c // 5
    elif curve == 5:
        v = 5 * c // 4
    else:
        raise ValueError(curve)
    return max(v, 0)


GROWTH_ROW_CURVE = [0, 1, 2, 3, 4, 5, 0, 0]


def verify_growth(path):
    """Vergleicht GrowTable.json (Masterdata, nur lesend) mit den Formeln; liefert (geprueft, abweichend)."""
    return verify_growth_rows(json.loads(Path(path).read_text())["instances"][0]["data"]["Data"])


def verify_growth_rows(rows):
    checked = bad = 0
    for row, curve in zip(rows, GROWTH_ROW_CURVE):
        for n, exp in enumerate(row["exps"]):
            if n == 0:
                continue
            checked += 1
            if growth_exp(curve, n) != exp:
                bad += 1
    return checked, bad


# ---------------------------------------------------------------------------------------------------------------
# Emulator
# ---------------------------------------------------------------------------------------------------------------

class Oracle:
    def __init__(self):
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_ALL
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
        self._u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self._prot_all = UC_PROT_ALL
        self._reg = {"x0": UC_ARM64_REG_X0, "sp": UC_ARM64_REG_SP, "lr": UC_ARM64_REG_LR, "pc": UC_ARM64_REG_PC}
        self._x0 = UC_ARM64_REG_X0
        self.data = ELF.read_bytes()
        self.segs = parse_elf_segments(self.data)
        self._heap_ptr = HEAP_BASE
        self._load()
        self.meta = METADATA.read_bytes() if METADATA.exists() else None
        self._script_meta = None
        self._alloc_hook = None

    # -- Laden -------------------------------------------------------------------------------------------------
    def _load(self):
        u = self._u
        top = max(va + memsz for va, _o, _f, memsz in self.segs)
        top = (top + 0xFFFF) & ~0xFFFF
        u.mem_map(0, top, self._prot_all)  # Seite 0 bleibt nullgefuellt: IL2CPP-Klassenpruefungen lesen dort 0
        for va, off, filesz, _memsz in self.segs:
            u.mem_write(va, self.data[off:off + filesz])
        dyn = parse_dynamic(self.data, self.segs)
        rela, relasz = dyn.get(7), dyn.get(8)
        # RELA-Eintraege in den Speicher schreiben (nur RELATIVE; Symbolrelokationen werden nicht gebraucht)
        raw = self.data[vaddr_to_offset(self.segs, rela):vaddr_to_offset(self.segs, rela) + relasz]
        pending = []
        for i in range(0, len(raw), 24):
            off, info, addend = struct.unpack_from("<QQq", raw, i)
            if (info & 0xFFFFFFFF) == R_AARCH64_RELATIVE:
                pending.append((off, addend))
        self.relative_relocs = len(pending)
        for off, addend in pending:
            u.mem_write(off, struct.pack("<Q", addend & 0xFFFFFFFFFFFFFFFF))
        u.mem_map(STACK_TOP - STACK_SIZE, STACK_SIZE, self._prot_all)
        u.mem_map(HEAP_BASE, HEAP_SIZE, self._prot_all)
        u.mem_map(SENTINEL, 0x1000, self._prot_all)
        from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1
        u.reg_write(UC_ARM64_REG_CPACR_EL1, 0x300000)  # FP/SIMD freischalten

    # -- Speicher ----------------------------------------------------------------------------------------------
    def read(self, vaddr, n):
        return bytes(self._u.mem_read(vaddr, n))

    def write(self, vaddr, blob):
        self._u.mem_write(vaddr, blob)

    def u64(self, vaddr):
        return struct.unpack("<Q", self.read(vaddr, 8))[0]

    def set_flag(self, ghidra_addr):
        self.write(ghidra_addr - IMAGE_BASE, b"\x01")

    def alloc(self, size):
        size = (size + 15) & ~15
        p = self._heap_ptr
        self._heap_ptr += size
        if self._heap_ptr > HEAP_BASE + HEAP_SIZE:
            raise MemoryError("Orakel-Heap voll")
        return p

    def make_array(self, elem_size, values, signed=False):
        """IL2CPP-Array: Kopf 0x18 Byte, Laenge bei +0x18, Elemente ab +0x20."""
        p = self.alloc(0x20 + elem_size * len(values))
        fmt = {1: "b" if signed else "B", 2: "h" if signed else "H", 4: "i" if signed else "I", 8: "q" if signed else "Q"}[elem_size]
        self.write(p + 0x18, struct.pack("<I", len(values)))
        self.write(p + 0x20, b"".join(struct.pack("<" + fmt, v) for v in values))
        return p

    def make_ptr_array(self, ptrs):
        return self.make_array(8, ptrs)

    def make_class(self, ptr_dat_ghidra_addr, static_fields):
        """Haengt ein Klassenobjekt an den Zeiger-Slot PTR_DAT_xxx; static_fields: Liste von 8-Byte-Werten ab Offset 0."""
        slot = self.u64(ptr_dat_ghidra_addr - IMAGE_BASE)  # relozierter Zeiger -> Adresse des Laufzeit-Slots
        klass = self.alloc(0x200)
        statics = self.alloc(0x100)
        for i, v in enumerate(static_fields):
            self.write(statics + 8 * i, struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))
        self.write(klass + 0xB8, struct.pack("<Q", statics))
        self.write(slot, struct.pack("<Q", klass))
        return klass, statics

    # -- Metadaten ---------------------------------------------------------------------------------------------
    def script_meta(self):
        if self._script_meta is None:
            sm = json.loads(SCRIPT_JSON.read_text())["ScriptMetadata"]
            self._script_meta = {m["Address"]: m["Name"] for m in sm}
        return self._script_meta

    def field_blob(self, ptr_dat_ghidra_addr, arrays):
        """Liefert die Rohbytes eines statischen Array-Initialisierers (Feldname -> Metadaten-Blob)."""
        slot = self.u64(ptr_dat_ghidra_addr - IMAGE_BASE)
        name = self.script_meta().get(slot)
        if not name or not name.startswith("Field$<PrivateImplementationDetails>."):
            raise KeyError(f"kein Initialisierer-Feld bei {hex(ptr_dat_ghidra_addr)} (Slot {hex(slot)}, {name})")
        h = name.split(".")[-1]
        return arrays[h]

    # -- Aufrufe -----------------------------------------------------------------------------------------------
    def arg(self, i):
        from unicorn.arm64_const import UC_ARM64_REG_X0
        return self._u.reg_read(UC_ARM64_REG_X0 + i)

    def stack_arg(self, i):
        """i-tes Stack-Argument (8 Byte) im Aufruf, siehe call(stack_args=...)."""
        return struct.unpack("<Q", self.read(self._u.reg_read(self._reg["sp"]) + 8 * i, 8))[0]

    def call(self, ghidra_addr, *args, stack_args=(), max_insns=200000):
        from unicorn.arm64_const import UC_ARM64_REG_X0
        u = self._u
        for i, a in enumerate(args):
            u.reg_write(UC_ARM64_REG_X0 + i, a & 0xFFFFFFFFFFFFFFFF)
        sp = STACK_TOP - 0x1000
        for i, a in enumerate(stack_args):
            self.write(sp + 8 * i, struct.pack("<Q", a & 0xFFFFFFFFFFFFFFFF))
        u.reg_write(self._reg["sp"], sp)
        u.reg_write(self._reg["lr"], SENTINEL)
        u.emu_start(ghidra_addr - IMAGE_BASE, SENTINEL, count=max_insns)
        return u.reg_read(self._x0)

    def prepare(self, func_name_regex_source):
        """Setzt alle Init-Flags der Funktion (aus dem dekompilierten Text) auf 1."""
        for a in decomp_dat_flags(func_name_regex_source):
            self.set_flag(a)

    # -- Stubs und Klassenkonstruktoren --------------------------------------------------------------------------
    def stub(self, ghidra_addr, fn=None):
        """Ersetzt eine Funktion: fn(oracle, x0, x1) -> Rueckgabewert (None: x0 bleibt), danach sofort RET."""
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_LR, UC_ARM64_REG_PC
        target = ghidra_addr - IMAGE_BASE

        def hook(uc, address, size, _user):
            if address != target:
                return
            x0 = uc.reg_read(UC_ARM64_REG_X0)
            x1 = uc.reg_read(UC_ARM64_REG_X1)
            ret = fn(self, x0, x1) if fn else None
            if ret is not None:
                uc.reg_write(UC_ARM64_REG_X0, ret & 0xFFFFFFFFFFFFFFFF)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

        self._u.hook_add(UC_HOOK_CODE, hook, begin=target, end=target)

    def install_runtime_stubs(self):
        """Minimale IL2CPP-Laufzeit: Array-Allokation, Kopieren von Initialisierer-Blobs, leere Barrieren."""
        arrays = load_dump_arrays()
        # Jedes Initialisierer-Feld bekommt einen Datensatz [u32 Groesse][Daten]; der Slot zeigt darauf.
        for slot, name in self.script_meta().items():
            if not name.startswith("Field$<PrivateImplementationDetails>."):
                continue
            h = name.split(".")[-1]
            if h not in arrays:
                continue
            blob = arrays[h]
            size = len(blob)
            rec = self.alloc(4 + size)
            self.write(rec, struct.pack("<I", size) + blob)
            self.write(slot, struct.pack("<Q", rec))

        def new_array(o, _klass, length):
            p = o.alloc(0x20 + 8 * length)
            o.write(p + 0x18, struct.pack("<I", length))
            return p

        def init_array(o, array, handle):
            size = struct.unpack("<I", o.read(handle, 4))[0]
            o.write(array + 0x20, o.read(handle + 4, size))
            return None

        self.stub(0x3AFB10, lambda o, a, b: o.alloc(0x4000))  # mehrdimensionale Arrays: nur Platzhalter
        self.stub(0x3AFB00, new_array)          # il2cpp_array_new_specific
        self.stub(0x3AFC10, lambda o, a, b: a)  # Array-Typpruefung beim Setzen: immer erfolgreich
        self.stub(0x3AB52C)                     # GC-Schreibbarriere
        self.stub(0x364FE0)                     # Klassen-/Methodeninitialisierung
        self.stub(0x3AFBE0)                     # Klassen-Konstruktor-Anstoss
        self.stub(0x23C4CE0, init_array)        # RuntimeHelpers.InitializeArray

    def run_cctor(self, cctor_addr, klass_ptr_dat, source_text):
        """Fuehrt den echten .cctor aus; liefert die Adresse des statischen Feldblocks der Klasse."""
        self.prepare(source_text)
        _klass, statics = self.make_class(klass_ptr_dat, [])
        self.call(cctor_addr, max_insns=2000000)
        return statics

    def read_ptr_array(self, arr):
        n = struct.unpack("<I", self.read(arr + 0x18, 4))[0]
        return [self.u64(arr + 0x20 + 8 * i) for i in range(n)]

    def read_elems(self, arr, fmt, n=None):
        count = n if n is not None else struct.unpack("<I", self.read(arr + 0x18, 4))[0]
        size = struct.calcsize(fmt)
        return [struct.unpack_from("<" + fmt, self.read(arr + 0x20, size * count), i * size)[0] for i in range(count)]


def load_dump_arrays():
    meta = METADATA.read_bytes() if METADATA.exists() else None
    return parse_array_hashes(DUMP.read_text(errors="replace"), meta)


# ---------------------------------------------------------------------------------------------------------------
# Fixture-Erzeugung: jede Gruppe ruft die echten Funktionen auf und speichert nur Zahlen.
# ---------------------------------------------------------------------------------------------------------------

def read_decomp(name):
    return (DECOMP_DIR / name).read_text()


def rng_for(name):
    return random.Random("xnu-battle-slice1-" + name)


def new_oracle():
    o = Oracle()
    o.install_runtime_stubs()
    return o


def setup_calc_class(o, rand_seed=None):
    """Fuehrt den echten calc-.cctor aus; optional wird g_RandSys mit dem echten Xoroshiro128+ belegt."""
    src = read_decomp("battle1/Dpr_Battle_Logic_calc.c")
    statics = o.run_cctor(0x2076D40, 0x4C7F038, src)
    o.prepare(src)
    if rand_seed is not None:
        random_obj = make_random_object(o, rand_seed)
        o.write(statics, struct.pack("<Q", random_obj))
    return statics


def make_random_object(o, seed):
    """Dpr.Battle.Logic.Random mit echtem Xoroshiro128Plus (Konstruktor aus dem Spielcode)."""
    o.prepare(read_decomp("battle1b/Xoroshiro128Plus_Xoroshiro128Plus.c"))
    xoro = o.alloc(0x40)
    o.call(0x18D84E0, xoro, seed)
    rnd = o.alloc(0x40)
    o.write(rnd + 0x10, struct.pack("<Q", xoro))
    o.write(rnd + 0x18, struct.pack("<Q", seed & 0xFFFFFFFFFFFFFFFF))
    return rnd


def gen_tables():
    o = new_oracle()
    nat_src = read_decomp("battle1/Pml_PokePara_CalcTool.c")
    st = o.run_cctor(0x25AEC40, 0x4CD0AC0, nat_src)
    nature = [o.read_elems(r, "b", 5) for r in o.read_ptr_array(o.u64(st))]
    ta_src = read_decomp("battle1/Pml_Battle_TypeAffinity.c")
    st = o.run_cctor(0x1C29E00, 0x4C873D8, ta_src)
    type_rows = [o.read_elems(r, "B", 18) for r in o.read_ptr_array(o.u64(st))]
    value_table = o.read_elems(o.u64(st + 8), "I", 14)
    calc = setup_calc_class(o)
    rank = o.read_elems(o.u64(calc + 0x28), "H", 13)
    hit = o.read_elems(o.u64(calc + 0x30), "H", 13)
    return {
        "doc": "Tabellen, ausgelesen durch Ausfuehren der echten .cctor (Unicorn). Nur Zahlen.",
        "natureColumns": ["atk", "def", "spatk", "spdef", "agi"],
        "natureTable": nature,
        "typeChart": type_rows,
        "typeValueTable": value_table,
        "statusRankNumDen": [[v & 0xFF, v >> 8] for v in rank],
        "hitRankNumDen": [[v & 0xFF, v >> 8] for v in hit],
        "criticalTable": o.read_elems(o.u64(calc + 0x38), "B", 4),
        "penaltyCoef": o.read_elems(o.u64(calc + 0x40), "B", 9),
    }


def gen_stats():
    o = new_oracle()
    src = read_decomp("battle1/Pml_PokePara_CalcTool.c")
    o.run_cctor(0x25AEC40, 0x4CD0AC0, src)
    o.prepare(src)
    r = rng_for("stats")
    out = {"doc": "Pml.PokePara.CalcTool: Statuswerte. Ergebnisse sind die unteren 16 Bit von w0."}

    hp = []
    for i in range(160):
        mons = 292 if i % 17 == 0 else r.randint(1, 493)
        level = r.choice([1, 2, 5, 50, 100]) if i % 3 == 0 else r.randint(1, 100)
        base = r.choice([1, 10, 255]) if i % 5 == 0 else r.randint(1, 255)
        iv = r.choice([0, 31]) if i % 4 == 0 else r.randint(0, 31)
        ev = r.choice([0, 252, 255, 510]) if i % 6 == 0 else r.randint(0, 255)
        res = o.call(0x25AD1B0, mons, level, base, iv, ev) & 0xFFFF
        hp.append({"monsno": mons, "level": level, "base": base, "iv": iv, "ev": ev, "out": res})
    out["calcMaxHp"] = hp

    names = {"calcAtk": 0x25AD200, "calcDef": 0x25AD3C0, "calcSpAtk": 0x25AD480, "calcSpDef": 0x25AD540, "calcAgi": 0x25AD600}
    for key, addr in names.items():
        cases = []
        for i in range(200):
            nature = i % 25
            level = r.choice([1, 50, 100]) if i % 3 == 0 else r.randint(1, 100)
            base = r.choice([5, 100, 255]) if i % 5 == 0 else r.randint(1, 255)
            iv = r.choice([0, 31]) if i % 4 == 0 else r.randint(0, 31)
            ev = r.choice([0, 252, 255]) if i % 6 == 0 else r.randint(0, 255)
            res = o.call(addr, level, base, iv, ev, nature) & 0xFFFF
            cases.append({"level": level, "base": base, "iv": iv, "ev": ev, "nature": nature, "out": res})
        out[key] = cases

    corr = []
    for i in range(300):
        value = r.choice([0, 1, 595, 596, 597, 1000, 5000, 65535]) if i % 4 == 0 else r.randint(1, 700)
        nature = r.randint(0, 24)
        pid = [1, 2, 3, 4, 5, 0, 6][i % 7] if i % 7 else r.randint(1, 5)
        res = o.call(0x25AD2C0, value, nature, pid) & 0xFFFF
        corr.append({"value": value, "nature": nature, "powerId": pid, "out": res})
    out["correctedPower"] = corr

    trans = []
    for nature in range(25):
        for pid in range(0, 7):
            res = o.call(0x25AD6C0, nature, pid) & 0xFF
            trans.append({"nature": nature, "powerId": pid, "out": res - 256 if res > 127 else res})
    out["powerTransform"] = trans
    return out


def gen_types():
    o = new_oracle()
    src = read_decomp("battle1/Pml_Battle_TypeAffinity.c")
    o.run_cctor(0x1C29E00, 0x4C873D8, src)
    o.prepare(src)
    calc = []
    for w in range(19):
        for p in range(19):
            for inv in (0, 1):
                calc.append({"waza": w, "poke": p, "inverse": inv, "out": o.call(0x1C296C0, w, p, inv) & 0xFFFFFFFF})
    mul = []
    for a in range(14):
        for b in range(14):
            mul.append({"a": a, "b": b, "out": to_s32(o.call(0x1C298C0, a, b))})
    return {"doc": "Pml.Battle.TypeAffinity.CalcAffinity (Einzeltyp) und MulAffinity.", "calcAffinity": calc, "mulAffinity": mul}


def gen_calc():
    o = new_oracle()
    setup_calc_class(o)
    r = rng_for("calc")
    out = {"doc": "Dpr.Battle.Logic.calc: Hilfsfunktionen der Kampfmathematik."}

    base = []
    for i in range(200):
        power = r.choice([1, 40, 250]) if i % 4 == 0 else r.randint(1, 250)
        atk = r.choice([1, 999, 4000]) if i % 5 == 0 else r.randint(1, 700)
        level = r.choice([1, 100]) if i % 6 == 0 else r.randint(1, 100)
        dfn = 0 if i % 23 == 0 else (r.choice([1, 5, 999]) if i % 7 == 0 else r.randint(1, 700))
        res = to_u32(o.call(0x20747E0, power, atk, level, dfn))
        base.append({"power": power, "atk": atk, "level": level, "def": dfn, "out": res})
    out["damageBase"] = base

    aff = []
    for aff_id in range(0, 16):
        for k in range(14):
            raw = r.choice([0, 1, 5, 63, 64, 65, 1000, 4095, 99999, 0x7FFFFFFF, 0xFFFFFFFF]) if k < 8 else r.randint(1, 600)
            aff.append({"raw": raw, "aff": aff_id, "out": o.call(0x2074820, raw, aff_id) & 0xFFFFFFFF})
    out["affDamage"] = aff

    for key, addr in (("mulRatio", 0x2074B00), ("mulRatioOverZero", 0x2074B20), ("mulRatioInt", 0x2074BB0)):
        cases = []
        for i in range(220):
            a = r.choice([0, 1, 2, 3, 4095, 4096, 100000, 1000000, 3000000]) if i % 4 == 0 else r.randint(0, 800)
            b = r.choice([0x800, 0x1000, 0x1800, 0x1333, 0x2000, 0xC00, 0x666, 0x555, 0x4000, 0x20000]) if i % 2 == 0 else r.randint(0, 0x2000)
            if key == "mulRatioInt":
                b = r.choice([50, 100, 150, 75, 120, 1]) if i % 2 == 0 else r.randint(0, 300)
            cases.append({"a": a, "b": b, "out": to_u32(o.call(addr, a, b))})
        out[key] = cases

    weather = []
    for w in range(9):
        for t in range(19):
            weather.append({"weather": w, "type": t, "out": o.call(0x2075830, w, t) & 0xFFFFFFFF})
    out["weatherRatio"] = weather

    rank = []
    for i in range(240):
        idx = i % 15 if i < 195 else r.choice([13, 20, 255])
        value = r.choice([1, 2, 99, 100, 999, 65535, 70000]) if i % 5 == 0 else r.randint(1, 800)
        rank.append({"value": value, "rank": idx, "out": o.call(0x2074EA0, value, idx) & 0xFFFFFFFF})
    out["statusRank"] = rank

    hit = []
    for i in range(240):
        idx = i % 15 if i < 195 else r.choice([13, 20, 255])
        per = r.choice([0, 1, 30, 50, 95, 100, 255]) if i % 4 == 0 else r.randint(0, 100)
        hit.append({"hitPer": per, "rank": idx, "out": o.call(0x20750B0, per, idx) & 0xFFFFFFFF})
    out["hitPer"] = hit

    rv = []
    for i in range(120):
        v = r.randint(-50, 50)
        lo = r.randint(-10, 10)
        hi = lo + r.randint(0, 20) if i % 9 else lo - r.randint(1, 5)
        rv.append({"value": v, "lo": lo, "hi": hi, "out": to_s32(o.call(0x2075F20, v, lo, hi))})
    out["roundValue"] = rv
    return out


def gen_exp():
    o = new_oracle()
    setup_calc_class(o)
    exp_src = read_decomp("battle1c/Dpr_Battle_Logic_Exp.c")
    o.prepare(exp_src)
    r = rng_for("exp")
    out = {"doc": "Dpr.Battle.Logic.Exp: Erfahrungspunkte pro Empfaenger."}

    adj = []
    for i in range(200):
        exp = r.choice([1, 2, 5, 100, 5000]) if i % 4 == 0 else r.randint(1, 1500)
        recv = r.randint(1, 100)
        foe = r.randint(1, 100)
        adj.append({"exp": exp, "receiverLevel": recv, "foeLevel": foe, "out": to_s32(o.call(0x19F8040, exp, recv, foe))})
    out["adjustLevel"] = adj

    base = []
    for i in range(80):
        lv = r.randint(0, 100)
        be = r.randint(0, 400)
        base.append({"level": lv, "baseExp": be, "out": to_u32(o.call(0x19F8000, lv, be))})
    out["baseExp"] = base
    share_inputs = [0, 1, 2, 3, 4, 5, 99, 100, 101, 12345, 0x7FFFFFFF, 0xFFFFFFFF] + [r.randint(0, 5000) for _ in range(48)]
    out["shareExp"] = [{"exp": e, "out": to_u32(o.call(0x19F8030, e))} for e in share_inputs]

    calc = []
    param = o.alloc(0x40)
    cell = o.alloc(8)
    result = o.alloc(0x20)
    o.write(cell, struct.pack("<Q", param))
    for i in range(400):
        p = {
            "competitor": r.randint(0, 4),
            "playerLanguage": r.randint(0, 9),
            "levelCap": r.choice([100, 20, 50, 5]) if i % 3 else 100,
            "foeBaseExp": r.choice([0, 1, 20, 64, 112, 270, 608]) if i % 4 == 0 else r.randint(30, 300),
            "foeLevel": r.randint(1, 100),
            "receiverLevel": r.randint(1, 100),
            "friendship": r.choice([0, 100, 219, 220, 255]) if i % 3 == 0 else r.randint(0, 255),
            "receiverLanguage": r.randint(0, 9),
            "participated": r.randint(0, 1),
            "expShare": r.randint(0, 1),
            "luckyEgg": r.randint(0, 1),
            "evoCancel": r.randint(0, 1),
            "isMyPoke": r.randint(0, 1),
        }
        if i % 3 == 0:
            p["receiverLanguage"] = p["playerLanguage"]
        o.write(param + 0x10, struct.pack("<IIIIIIII", p["competitor"], p["playerLanguage"], p["levelCap"],
                                          p["foeBaseExp"], p["foeLevel"], p["receiverLevel"], p["friendship"], p["receiverLanguage"]))
        o.write(param + 0x30, bytes([p["participated"], p["expShare"], p["luckyEgg"], p["evoCancel"], p["isMyPoke"]]))
        o.write(result + 0x10, b"\xAA" * 8)
        o.call(0x19F7D70, cell, result)
        exp_out = struct.unpack("<I", o.read(result + 0x10, 4))[0]
        by_share, bonus = o.read(result + 0x14, 2)
        p.update({"out": exp_out, "byExpShare": by_share, "hasBonus": bonus})
        calc.append(p)
    out["calcExp"] = calc
    return out


def gen_rng():
    o = new_oracle()
    setup_calc_class(o)
    xsrc = read_decomp("battle1b/Xoroshiro128Plus_Xoroshiro128Plus.c")
    o.prepare(xsrc)
    seeds = [0, 1, 2, 42, 0x7FFFFFFF, 0xFFFFFFFF80000000, 0xFFFFFFFFFFFFFFFF, 0x9E3779B97F4A7C15, 123456789, 0xDEADBEEFCAFEBABE]
    r = rng_for("rng")
    seeds += [r.getrandbits(64) for _ in range(30)]
    seeds += [(r.getrandbits(32) - (1 << 31)) & 0xFFFFFFFFFFFFFFFF for _ in range(10)]  # wie Random.Initialize(): int, vorzeichenerweitert
    streams = []
    for seed in seeds:
        xoro = o.alloc(0x40)
        o.call(0x18D84E0, xoro, seed)
        state0, state1 = struct.unpack("<QQ", o.read(xoro + 0x20, 16))
        ulongs = [o.call(0x18D8FF0, xoro) for _ in range(6)]
        uints = [o.call(0x18D9010, xoro) & 0xFFFFFFFF for _ in range(3)]
        streams.append({"seed": str(seed), "state0": str(state0), "state1": str(state1),
                        "nextULong": [str(v) for v in ulongs], "nextUInt": uints})
    mods = []
    maxes = [1, 2, 3, 10, 16, 100, 101, 255, 1000, 65536, 0xFFFFFFFF, 0, 0x7FFFFFFFFFFFFFFF]
    for seed in seeds[:20]:
        rnd = make_random_object(o, seed)
        draws = []
        for k in range(12):
            m = maxes[k % len(maxes)]
            draws.append({"max": str(m), "out": str(o.call(0x21D3290, rnd, m))})
        mods.append({"seed": str(seed), "draws": draws})
    return {"doc": "Xoroshiro128Plus (Konstruktor mit Seed, NextULong/NextUInt) und Random.GetValue(max). Zahlen als Strings (64 Bit).",
            "streams": streams, "bounded": mods}


class EventModel:
    """Minimaler Ersatz fuer EventSystem/BTL_POKEPARAM: Handler-Ergebnisse sind Eingaben des Testfalls."""

    FINAL_RATIO_EVENT = 0x5A

    def __init__(self, o):
        self.o = o
        self.frames = []
        self.cfg = {}
        self.mulrange = {}
        o.stub(0x19F5510, lambda o_, a, b: self._push())
        o.stub(0x19F56A0, lambda o_, a, b: self._pop())
        o.stub(0x19F5B60, lambda o_, a, b: self._set(b, o_.arg(2)))
        o.stub(0x19F5950, lambda o_, a, b: self._set(b, o_.arg(2)))
        o.stub(0x19F5C60, lambda o_, a, b: self._set(b, o_.arg(2)))
        o.stub(0x19F5E10, lambda o_, a, b: self._set_mul(b, o_.arg(2), o_.arg(3), o_.arg(4)))
        o.stub(0x19F60A0, lambda o_, a, b: self._get(b))
        o.stub(0x19F4A00, lambda o_, a, b: self._call(b & 0xFFFF))
        o.stub(0x1E1D790, lambda o_, a, b: 0)                   # Event_CheckKinomiEffectUp
        o.stub(0x1E14E20, lambda o_, a, b: self.cfg["power"])   # Event_getWazaPower
        o.stub(0x1E15010, self._attack)                          # Event_getAttackPower
        o.stub(0x1E153D0, lambda o_, a, b: self.cfg["defense"]) # Event_getDefenderGuard
        o.stub(0x1E15740, lambda o_, a, b: self.cfg["stab"])    # Event_CalcTypeMatchRatio
        o.stub(0x20DD010, lambda o_, a, b: self.cfg.get("values", {}).get(b & 0xFFFFFFFF, 0))  # BTL_POKEPARAM.GetValue(vid)
        o.stub(0x20DDE40, lambda o_, a, b: self.cfg.get("sick", 0))  # GetPokeSick
        o.stub(0x20DB9A0, lambda o_, a, b: 0)                   # IsGMode
        o.stub(0x20D8A50, lambda o_, a, b: 0)                   # GetID
        # nur fuer die Trefferpruefung
        o.stub(0x19F5FC0, lambda o_, a, b: self._mul(b, o_.arg(2)))                        # EVENTVAR_MulValue
        o.stub(0x21D6E10, lambda o_, a, b: self.cfg.get("mustHit", 0))                      # SectionUtil.CheckMustHit
        o.stub(0x212DE60, lambda o_, a, b: self.cfg.get("competitor", 0))                   # MainModule.GetCompetitor
        o.stub(0x1E19710, lambda o_, a, b: self.cfg.get("hitCancel", 0))                    # Event_IsCalcHitCancel
        o.stub(0x20D8B30, lambda o_, a, b: self.cfg.get("sickFlags", {}).get(b & 0xFFFFFFFF, 0))  # BTL_POKEPARAM.CheckSick(id)
        o.stub(0x1E16A30, lambda o_, a, b: self.cfg.get("hitPer", 0))                       # Event_getHitPer
        o.stub(0x20DFE70, lambda o_, a, b: self.cfg.get("turnFlags", {}).get(b & 0xFFFFFFFF, 0))  # TURNFLAG_Get
        o.stub(0x21D6B00, lambda o_, a, b: self.cfg.get("friendship", 0))                   # SectionUtil.GetFriendship
        o.stub(0x2072C30, lambda o_, a, b: self.cfg.get("wazaCritRank", 0))                 # WAZADATA.GetCriticalRank
        o.stub(0x20E0C10, lambda o_, a, b: self.cfg.get("pokeCritRank", 0))                 # BTL_POKEPARAM.GetCriticalRank

    def _push(self):
        self.frames.append({})
        self.mulrange = getattr(self, "mulrange", {})

    def _pop(self):
        self.frames.pop()

    def _set(self, label, value):
        self.frames[-1][label & 0xFFFF] = to_s32(value)

    def _set_mul(self, label, init, mul_min, mul_max):
        self.frames[-1][label & 0xFFFF] = to_s32(init)
        self.mulrange[label & 0xFFFF] = (to_s32(mul_min), to_s32(mul_max))

    def _mul(self, label, ratio):
        # EVENTVAR_MulValue (0x19F5FC0): (Wert * Faktor + 0x800) >> 12, danach in [min, max] geklemmt, falls eines <> 0
        label &= 0xFFFF
        lo, hi = self.mulrange.get(label, (0, 0))
        v = (self.frames[-1][label] * to_s32(ratio) + 0x800) >> 12
        if lo != 0 or hi != 0:
            v = min(max(v, lo), hi)
        self.frames[-1][label] = to_s32(v)

    def _get(self, label):
        return self.frames[-1].get(label & 0xFFFF, 0) & 0xFFFFFFFF

    def _call(self, event_id):
        if event_id == self.FINAL_RATIO_EVENT:
            self.frames[-1][0x38] = self.cfg["finalRatio"]
        elif event_id == 0x43:  # Volltreffer-Handler: duerfen Stufe aendern oder Volltreffer verbieten
            f = self.frames[-1]
            f[0x2F] = self.cfg["critRankAfter"]
            f[0x48] = self.cfg["critForbid"]
        elif event_id == 0x3F:  # Treffer-Handler: duerfen Treffer-/Fluchtstufe, Ignorier-Flag und Faktor veraendern
            f = self.frames[-1]
            f[0x2A] = self.cfg["accAfter"]
            f[0x2B] = self.cfg["evaAfter"]
            f[0x52] = self.cfg["ignoreEva"]
            self._mul(0x38, self.cfg["accRatio"])

    def _attack(self, o, _a, _b):
        o.write(o.arg(5), bytes([self.cfg["ignoreBurn"]]))
        return self.cfg["attack"]


def gen_damage():
    o = new_oracle()
    setup_calc_class(o)
    ev_src = read_decomp("battle1/Dpr_Battle_Logic_EventLauncher.c")
    o.prepare(ev_src)
    o.prepare(read_decomp("battle1b/Dpr_Battle_Logic_EventLauncher.c"))
    model = EventModel(o)
    statics_slot = o.u64(0x4C7F038 - IMAGE_BASE)
    calc_klass = o.u64(statics_slot)
    calc_statics = o.u64(calc_klass + 0xB8)
    launcher, mainmod, evsys, attacker, defender, waza, out_cell = (o.alloc(0x100) for _ in range(7))
    o.write(launcher + 0x10, struct.pack("<Q", mainmod))
    o.write(launcher + 0x18, struct.pack("<Q", evsys))
    r = rng_for("damage")
    cases = []
    stabs = [0x1000, 0x1800, 0x2000, 0x1000, 0x1800]
    ratios = [0x1000, 0x1000, 0x1000, 0xC00, 0x2000, 0x1800, 0x1333, 0x800, 0x666]
    for i in range(500):
        c = {
            "power": r.choice([1, 20, 40, 60, 90, 120, 150, 250]) if i % 2 else r.randint(1, 250),
            "attack": r.choice([1, 50, 150, 300, 600]) if i % 3 == 0 else r.randint(10, 500),
            "defense": r.choice([1, 50, 150, 300, 600]) if i % 4 == 0 else r.randint(10, 500),
            "level": r.choice([1, 5, 50, 100]) if i % 3 == 0 else r.randint(1, 100),
            "targetRatio": r.choice(ratios[:4]) if i % 3 == 0 else 0x1000,
            "weather": r.randint(0, 7),
            "wazaType": r.choice([r.randint(0, 17), 9, 10, 18]),
            "physical": r.randint(0, 1),
            "critical": 1 if i % 5 == 0 else 0,
            "fixedRoll": 1 if i % 11 == 0 else 0,
            "typeAff": r.choice([7, 7, 6, 8, 5, 9, 0, 4, 10, 3, 11, 1, 13]),
            "stab": r.choice(stabs),
            "burned": r.randint(0, 1),
            "ignoreBurn": 1 if i % 9 == 0 else 0,
            "finalRatio": r.choice(ratios),
            "seed": r.getrandbits(48),
        }
        c["sick"] = 4 if c["burned"] else r.choice([0, 1, 2, 3, 5])
        model.cfg = {"power": c["power"], "attack": c["attack"], "defense": c["defense"], "stab": c["stab"],
                     "values": {0x11: c["level"]}, "sick": c["sick"], "ignoreBurn": c["ignoreBurn"], "finalRatio": c["finalRatio"]}
        # WazaParam: +0x1e Typ, +0x20 Schadenstyp (1 = physisch, 2 = speziell)
        o.write(waza + 0x1E, bytes([c["wazaType"]]))
        o.write(waza + 0x20, struct.pack("<I", 1 if c["physical"] else 2))
        rnd = make_random_object(o, c["seed"])
        o.write(calc_statics, struct.pack("<Q", rnd))
        o.write(out_cell, b"\x00\x00")
        res = o.call(0x1E14710, launcher, attacker, defender, waza, c["typeAff"], c["targetRatio"], c["critical"], c["fixedRoll"],
                     stack_args=(0, c["weather"], out_cell))
        dmg = struct.unpack("<H", o.read(out_cell, 2))[0]
        # Zustand der Zufallsquelle nach dem Aufruf: naechster Wert aus dem echten Generator
        xoro = o.u64(rnd + 0x10)
        c["out"] = dmg
        c["nextRand"] = str(o.call(0x18D8FF0, xoro))
        c["fixedDamage"] = res & 1
        c["seed"] = str(c["seed"])
        cases.append(c)
    return {"doc": "Event_CalcDamage (echter Code) mit ersetzten Ereignis-/Handler-Funktionen; Handler-Ergebnisse (Basiskraft, Angriff, Abwehr, "
                   "STAB-Verhaeltnis, Endfaktor) sind Eingaben.", "cases": cases}


def gen_hit():
    o = new_oracle()
    setup_calc_class(o)
    o.prepare(read_decomp("battle1/Dpr_Battle_Logic_EventLauncher.c"))
    model = EventModel(o)
    calc_statics = o.u64(o.u64(o.u64(0x4C7F038 - IMAGE_BASE)) + 0xB8)
    launcher, mainmod, evsys, helper, attacker, defender, waza, flag_cell = (o.alloc(0x100) for _ in range(8))
    o.write(launcher + 0x10, struct.pack("<Q", mainmod))
    o.write(launcher + 0x18, struct.pack("<Q", evsys))
    o.write(launcher + 0x20, struct.pack("<Q", helper))
    r = rng_for("hit")
    cases = []
    for i in range(600):
        c = {
            "hitPer": r.choice([1, 30, 50, 70, 85, 90, 95, 100, 101, 255]) if i % 2 else r.randint(1, 100),
            "accStage": r.choice([6, 6, 6, 0, 12, 3, 9]) if i % 2 else r.randint(0, 12),
            "evaStage": r.choice([6, 6, 6, 0, 12, 3, 9]) if i % 3 else r.randint(0, 12),
            "ignoreEva": 1 if i % 13 == 0 else 0,
            "accRatio": r.choice([0x1000, 0x1000, 0x1000, 0x14CD, 0xCCD, 0x2000, 0x800]),
            "turnFlag14": 1 if i % 7 == 0 else 0,
            "foresight": 1 if i % 5 == 0 else 0,
            "autoHitSick": 1 if i % 53 == 0 else 0,
            "mustHit": 1 if i % 61 == 0 else 0,
            "competitor": 4 if i % 59 == 0 else r.randint(0, 3),
            "hitCancel": 1 if i % 67 == 0 else 0,
            "friendship": 255 if i % 6 == 0 else r.choice([0, 100]),
            "seed": r.getrandbits(48),
        }
        c["accAfter"] = c["accStage"] if i % 4 else r.randint(0, 12)
        c["evaAfter"] = c["evaStage"] if i % 4 else r.randint(0, 12)
        model.cfg = {
            "hitPer": c["hitPer"], "values": {6: c["accStage"], 7: c["evaStage"]}, "accAfter": c["accAfter"], "evaAfter": c["evaAfter"],
            "ignoreEva": c["ignoreEva"], "accRatio": c["accRatio"],
            "turnFlags": {0xE: c["turnFlag14"]}, "sickFlags": {0x11: c["foresight"], 0x21: c["autoHitSick"]},
            "mustHit": c["mustHit"], "competitor": c["competitor"], "hitCancel": c["hitCancel"], "friendship": c["friendship"],
        }
        rnd = make_random_object(o, c["seed"])
        o.write(calc_statics, struct.pack("<Q", rnd))
        o.write(flag_cell, b"\xAA")
        res = o.call(0x1E19350, launcher, attacker, defender, waza, flag_cell)
        c["hit"] = res & 1
        c["friendshipFlag"] = o.read(flag_cell, 1)[0]
        c["nextRand"] = str(o.call(0x18D8FF0, o.u64(rnd + 0x10)))
        c["seed"] = str(c["seed"])
        cases.append(c)
    return {"doc": "Event_CheckHit (echter Code) mit ersetzten Zustands-/Handler-Funktionen. friendshipFlag: 1, wenn die Zuneigungs-Abwehr gegriffen hat.", "cases": cases}


def gen_crit():
    o = new_oracle()
    setup_calc_class(o)
    o.prepare(read_decomp("battle1b/Dpr_Battle_Logic_EventLauncher.c"))
    model = EventModel(o)
    calc_statics = o.u64(o.u64(o.u64(0x4C7F038 - IMAGE_BASE)) + 0xB8)
    launcher, mainmod, evsys, helper, attacker, defender, flag_cell = (o.alloc(0x100) for _ in range(7))
    o.write(launcher + 0x10, struct.pack("<Q", mainmod))
    o.write(launcher + 0x18, struct.pack("<Q", evsys))
    o.write(launcher + 0x20, struct.pack("<Q", helper))
    r = rng_for("crit")
    cases = []
    for i in range(400):
        c = {
            "wazaRank": 6 if i % 17 == 0 else r.choice([0, 0, 0, 1, 2]),
            "pokeRank": r.choice([0, 0, 1, 2, 3]),
            "rankAfter": r.randint(0, 9),
            "forbid": 1 if i % 19 == 0 else 0,
            "competitor": 4 if i % 23 == 0 else r.randint(0, 3),
            "friendship": 255 if i % 5 == 0 else 0,
            "seed": r.getrandbits(48),
        }
        if i % 3:
            c["rankAfter"] = min(3, c["pokeRank"] + c["wazaRank"]) if c["wazaRank"] != 6 else 6
        model.cfg = {"wazaCritRank": c["wazaRank"], "pokeCritRank": c["pokeRank"], "critRankAfter": c["rankAfter"], "critForbid": c["forbid"],
                     "competitor": c["competitor"], "friendship": c["friendship"]}
        rnd = make_random_object(o, c["seed"])
        o.write(calc_statics, struct.pack("<Q", rnd))
        o.write(flag_cell, b"\x00")
        res = o.call(0x1E144D0, launcher, attacker, defender, c["wazaRank"], flag_cell)
        c["critical"] = res & 1
        c["friendshipFlag"] = o.read(flag_cell, 1)[0]
        c["nextRand"] = str(o.call(0x18D8FF0, o.u64(rnd + 0x10)))
        c["seed"] = str(c["seed"])
        cases.append(c)
    return {"doc": "Event_CheckCritical (echter Code) mit ersetzten Zustands-/Handler-Funktionen; wazaRank 6 = Volltreffer garantiert. "
                   "friendshipFlag: Volltreffer durch Zuneigungs-Bonus.", "cases": cases}


def gen_rnguse():
    o = new_oracle()
    setup_calc_class(o)
    r = rng_for("rnguse")
    calc_statics = o.u64(o.u64(o.u64(0x4C7F038 - IMAGE_BASE)) + 0xB8)
    out = {"doc": "calc.IsOccurPer, calc.RandRange, calc.HitCountStd, calc.CheckCritical mit echtem Xoroshiro128+ (je Fall frisch aus dem Seed)."}
    def fresh(seed):
        rnd = make_random_object(o, seed)
        o.write(calc_statics, struct.pack("<Q", rnd))
        return rnd
    def nxt(rnd):
        return str(o.call(0x18D8FF0, o.u64(rnd + 0x10)))
    occ, rng, mh, cc = [], [], [], []
    for i in range(160):
        seed = r.getrandbits(48)
        rnd = fresh(seed)
        per = r.choice([0, 1, 10, 30, 50, 99, 100, 101, 200]) if i % 3 == 0 else r.randint(0, 100)
        occ.append({"seed": str(seed), "percent": per, "out": o.call(0x2075E20, per) & 1, "nextRand": nxt(rnd)})
        seed = r.getrandbits(48)
        rnd = fresh(seed)
        lo, hi = r.randint(0, 20), r.randint(0, 40)
        rng.append({"seed": str(seed), "a": lo, "b": hi, "out": to_u32(o.call(0x2074A10, lo, hi)), "nextRand": nxt(rnd)})
        seed = r.getrandbits(48)
        rnd = fresh(seed)
        kind = r.choice([5, 5, 5, 2, 3, 4, 1, 0])
        mh.append({"seed": str(seed), "wazaHitCount": kind, "out": o.call(0x2075AE0, kind) & 0xFF, "nextRand": nxt(rnd)})
        seed = r.getrandbits(48)
        rnd = fresh(seed)
        rank = r.randint(0, 3)
        div = r.choice([1, 1, 2, 3])
        cc.append({"seed": str(seed), "rank": rank, "divisor": div, "out": o.call(0x2075170, rank, div) & 1, "nextRand": nxt(rnd)})
    out["isOccurPer"], out["randRange"], out["hitCountStd"], out["checkCritical"] = occ, rng, mh, cc
    return out


GROUPS = {
    "tables": ("BattleTables.json", gen_tables),
    "stats": ("BattleStats.json", gen_stats),
    "types": ("BattleTypes.json", gen_types),
    "calc": ("BattleCalc.json", gen_calc),
    "exp": ("BattleExp.json", gen_exp),
    "rng": ("BattleRng.json", gen_rng),
    "damage": ("BattleDamage.json", gen_damage),
    "hit": ("BattleHit.json", gen_hit),
    "crit": ("BattleCrit.json", gen_crit),
    "rnguse": ("BattleRngUse.json", gen_rnguse),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", nargs="*", choices=sorted(GROUPS), help="nur diese Gruppen")
    ap.add_argument("--verify-growth", action="store_true", help="GrowTable.json gegen die Wachstumsformeln pruefen und beenden")
    args = ap.parse_args(argv)
    if args.verify_growth:
        checked, bad = verify_growth(ROOT / "work/masterdata/pml_personal/GrowTable.json")
        print(f"Wachstum: {checked} Werte geprueft, {bad} Abweichungen")
        return 1 if bad else 0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (filename, fn) in GROUPS.items():
        if args.only and name not in args.only:
            continue
        data = fn()
        (out_dir / filename).write_text(json.dumps(data, indent=1) + "\n")
        count = sum(len(v) for v in data.values() if isinstance(v, list))
        print(f"{name}: {filename} ({count} Eintraege)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

