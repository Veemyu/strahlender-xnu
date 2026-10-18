#!/usr/bin/env python3
"""Emulations-Orakel fuer Pokemon-Parameter (Pml.PokePara, Strang B: Slot-Layout, Verschluesselung, Accessor).

Wie scripts/battle_oracle.py: laedt work/elf/main.patched.elf in Unicorn (AArch64) und fuehrt die ECHTEN Spielfunktionen
(Pml.PokePara.Encoder, Accessor inkl. Block-Mischung) auf synthetischen Slots aus. Ergebnis sind reine Zahlen-JSONs
(Bytes als Hex-Strings synthetischer Zufallsdaten) unter unity/Assets/Tests/EditMode/Fixtures/PokePara*.json.
Es werden keine echten Spielstaende gelesen.

Adressen: Ghidra-Adresse = Il2CppDumper-RVA + 0x100000. Aufruf:
    PYTHONPATH=tools/pydeps python3 scripts/pokepara_oracle.py [--out DIR] [--only NAME ...]
Die Eingaben stammen aus einem festen Seed (reproduzierbar).
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
DEFAULT_OUT = bo.DEFAULT_OUT
IMAGE_BASE = bo.IMAGE_BASE

CORE_SIZE = 0x148
CALC_SIZE = 0x10
HEADER_SIZE = 8
BLOCK_SIZE = 0x50
ENC_LEN = 0x140
SLOT_SIZE = CORE_SIZE + CALC_SIZE

# Ghidra-Adressen der Spielfunktionen
ADDR_CHECKSUM = 0x2152460      # Encoder.CalcChecksum(ptr, len)
ADDR_ENCODE = 0x21524D0        # Encoder.Encode(ptr, len, seed)
ADDR_NEXT_RAND = 0x2152500     # Encoder.CalcNextRandCode(ref seed)
ADDR_DECODE = 0x2152520        # Encoder.Decode(ptr, len, seed)
ADDR_BLOCK_POS = 0x25A3E00     # Accessor.GetCoreDataBlockPos(rnd, blockId)
ADDR_IS_RARE_COLOR = 0x25AD790  # CalcTool.IsRareColor(id, colorRnd)
ADDR_ACCESSOR_CCTOR = 0x25AC480
ADDR_UPDATE_ENCODE = 0x25A3F20  # Accessor.UpdateChecksumAndEncode
PTR_ACCESSOR_CLASS = 0x4CD8868
ADDR_GFL_ASSERT = (0x2DCB2E0, 0x2DCB2F0)
ADDR_OFFSET_TO_STRING_DATA = 0x23C4D80
ADDR_MEMCPY = 0x279F290        # UnsafeUtility.MemCpy(dst, src, size)
ADDR_MEMCLEAR = 0x279F350      # UnsafeUtility.MemClear(ptr, size)

ACCESSOR_C = ROOT / "work/decomp/battle_all/Pml_PokePara_Accessor.c"
ENCODER_C = ROOT / "work/decomp/battle_all/Pml_PokePara_Encoder.c"


# ---------------------------------------------------------------------------------------------------------------
# Reine Hilfslogik (ohne Unicorn; Gegenprobe zur Spielfunktion, siehe scripts/tests/test_pokepara_oracle.py)
# ---------------------------------------------------------------------------------------------------------------

def py_checksum(buf):
    """Summe der 16-Bit-Woerter (LE) in 32 Bit, wie Encoder.CalcChecksum; bei ungerader Laenge zaehlt das letzte Byte nicht."""
    total = 0
    for i in range(0, len(buf) // 2 * 2, 2):
        total += buf[i] | (buf[i + 1] << 8)
    return total & 0xFFFFFFFF


def py_keystream(seed, words):
    s = seed & 0xFFFFFFFF
    for _ in range(words):
        s = (s * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        yield s >> 16


def py_crypt(buf, seed):
    """Encode == Decode: jedes 16-Bit-Wort XOR obere 16 Bit des naechsten LCG-Zustands."""
    out = bytearray(buf)
    for i, k in zip(range(0, len(out) // 2 * 2, 2), py_keystream(seed, len(out) // 2)):
        w = (out[i] | (out[i + 1] << 8)) ^ k
        out[i] = w & 0xFF
        out[i + 1] = w >> 8
    return bytes(out)


def hexs(b):
    return bytes(b).hex()


def unhex(s):
    return bytes.fromhex(s)


# ---------------------------------------------------------------------------------------------------------------
# Emulator-Aufbau
# ---------------------------------------------------------------------------------------------------------------

def new_pokepara_oracle():
    o = bo.new_oracle()
    for a in ADDR_GFL_ASSERT:
        o.stub(a)
    o.stub(ADDR_OFFSET_TO_STRING_DATA, lambda _o, _a, _b: 0x14)
    o.stub(ADDR_MEMCLEAR, lambda oo, ptr, size: oo.write(ptr, bytes(size)))
    o.stub(ADDR_MEMCPY, lambda oo, dst, src: oo.write(dst, oo.read(src, oo.arg(2))) if src else oo.write(dst, bytes(oo.arg(2))))
    src = ACCESSOR_C.read_text()
    o.prepare(src)
    o.prepare(ENCODER_C.read_text())
    _klass, statics = o.make_class(PTR_ACCESSOR_CLASS, [])
    o.call(ADDR_ACCESSOR_CCTOR, max_insns=2000000)
    o.accessor_statics = statics
    return o


class Slot:
    """Ein Accessor-Objekt im Emulator: +0x10 Calc-Array, +0x18 Core-Array, +0x20 'kodiert', +0x21 'FastMode'."""

    def __init__(self, o, plain_core, plain_calc):
        self.o = o
        self.obj = o.alloc(0x40)
        self.core = o.make_array(1, list(plain_core))
        self.calc = o.make_array(1, list(plain_calc))
        o.write(self.obj + 0x10, struct.pack("<Q", self.calc))
        o.write(self.obj + 0x18, struct.pack("<Q", self.core))
        o.write(self.obj + 0x20, b"\x00\x00")
        o.call(ADDR_UPDATE_ENCODE, self.obj)
        assert o.read(self.obj + 0x20, 1) == b"\x01", "Slot nicht kodiert"

    def encoded(self):
        return self.o.read(self.core + 0x20, CORE_SIZE) + self.o.read(self.calc + 0x20, CALC_SIZE)

    def load_encoded(self, blob):
        self.o.write(self.core + 0x20, blob[:CORE_SIZE])
        self.o.write(self.calc + 0x20, blob[CORE_SIZE:])
        self.o.write(self.obj + 0x20, b"\x01\x00")


def random_plain(rng, force_rnd=None, clear_bad_egg=True):
    core = bytearray(rng.randbytes(CORE_SIZE))
    if force_rnd is not None:
        struct.pack_into("<I", core, 0, force_rnd)
    if clear_bad_egg:
        core[4] &= ~0x04  # Kopf-Bit 2: fuseiTamago (Bad Egg) aus, sonst liefert der Accessor Ersatzdaten
    calc = bytearray(rng.randbytes(CALC_SIZE))
    return bytes(core), bytes(calc)


# ---------------------------------------------------------------------------------------------------------------
# Getter- und Setter-Tabellen (Name, Ghidra-Adresse wird aus dem Export gelesen)
# ---------------------------------------------------------------------------------------------------------------

# (Name, Argumentart, Rueckgabebreite in Byte)
GETTERS = [
    ("GetPersonalRnd", None, 4), ("GetColorRnd", None, 4), ("GetCheckSum", None, 2), ("IsFuseiTamago", None, 1),
    ("GetSick", None, 4), ("GetMonsNo", None, 2), ("GetItemNo", None, 2), ("GetID", None, 4), ("GetExp", None, 4),
    ("GetFriendship", None, 1), ("GetTokuseiNo", None, 2), ("GetBoxMark", None, 2), ("GetLangId", None, 1),
    ("GetEffortHp", None, 1), ("GetEffortAtk", None, 1), ("GetEffortDef", None, 1), ("GetEffortSpAtk", None, 1),
    ("GetEffortSpDef", None, 1), ("GetEffortAgi", None, 1),
    ("GetStyle", None, 1), ("GetBeautiful", None, 1), ("GetCute", None, 1), ("GetClever", None, 1), ("GetStrong", None, 1),
    ("GetFur", None, 1), ("GetEquipRibbonNo", None, 1),
    ("GetTalentHp", None, 4), ("GetTalentAtk", None, 4), ("GetTalentDef", None, 4), ("GetTalentSpAtk", None, 4),
    ("GetTalentSpDef", None, 4), ("GetTalentAgi", None, 4), ("GetEffortG", None, 1),
    ("IsEventPokemon", None, 1), ("GetOfficialBattleEnableFlag", None, 1), ("GetSex", None, 1), ("GetFormNo", None, 2),
    ("GetSeikaku", None, 1), ("GetSeikakuHosei", None, 1), ("IsTokusei1", None, 1), ("IsTokusei2", None, 1),
    ("IsTokusei3", None, 1), ("IsFavorite", None, 1), ("IsSpecialGEnable", None, 1), ("IsTamago", None, 1),
    ("HaveNickName", None, 1), ("GetCassetteVersion", None, 1),
    ("GetTamagoGetYear", None, 1), ("GetTamagoGetMonth", None, 1), ("GetTamagoGetDay", None, 1),
    ("GetBirthYear", None, 1), ("GetBirthMonth", None, 1), ("GetBirthDay", None, 1),
    ("GetGetPlace", None, 2), ("GetBirthPlace", None, 2), ("GetPokerus", None, 1), ("GetGetBall", None, 1),
    ("GetGetLevel", None, 1), ("GetOyasex", None, 1),
    ("GetLevel", None, 1), ("GetHp", None, 2), ("GetMaxHp", None, 2), ("GetAtk", None, 2), ("GetDef", None, 2),
    ("GetSpAtk", None, 2), ("GetSpDef", None, 2), ("GetAgi", None, 2), ("GetGState", None, 1),
    ("GetEnjoy", None, 1), ("GetNadenadeValue", None, 1), ("GetOthersFriendshipTrainerID", None, 2),
    ("GetOwnedOthersFlag", None, 1), ("GetOriginalFriendship", None, 1), ("GetOthersFriendship", None, 1),
    ("GetMemoriesLevel", None, 1), ("GetMemoriesCode", None, 1), ("GetMemoriesData", None, 2), ("GetMemoriesFeel", None, 1),
    ("GetOthersMemoriesLevel", None, 1), ("GetOthersMemoriesCode", None, 1), ("GetOthersMemoriesData", None, 2),
    ("GetOthersMemoriesFeel", None, 1), ("GetPastParentsSex", None, 1), ("GetPastParentsLangID", None, 1),
    ("GetMultiPurposeWork", None, 4), ("GetTrainingFlag", None, 1), ("GetCampFriendship", None, 4), ("GetPalma", None, 4),
    ("GetTalentHeight", None, 1), ("GetTalentWeight", None, 1), ("GetBattleRomMark", None, 1), ("GetDprIllegalFlag", None, 1),
    ("GetBankUniqueID", None, 8),
    # mit Index
    ("HaveRibbon", (0, 128), 1), ("GetLumpingRibbon", (0, 2), 1),
    ("GetWazaNo", (0, 4), 2), ("GetPP", (0, 4), 1), ("GetWazaPPUpCount", (0, 4), 1), ("GetTamagoWazaNo", (0, 4), 2),
    ("GetWazaRecordFlag", (0, 0x70), 1), ("GetPokeJobFlag", (0, 0x70), 1),
]

# (Name, Argumentliste als Breiten in Byte; Indexargumente sind ('idx', n) mit Wertebereich 0..n-1)
SETTERS = [
    ("SetPersonalRnd", [4]), ("SetColorRnd", [4]), ("SetSick", [4]), ("SetMonsNo", [2]), ("SetItemNo", [2]), ("SetID", [4]),
    ("SetExp", [4]), ("SetFriendship", [1]), ("SetTokuseiNo", [2]), ("SetBoxMark", [2]), ("SetLangId", [1]),
    ("SetEffortHp", [1]), ("SetEffortAtk", [1]), ("SetEffortDef", [1]), ("SetEffortSpAtk", [1]), ("SetEffortSpDef", [1]),
    ("SetEffortAgi", [1]), ("SetStyle", [1]), ("SetBeautiful", [1]), ("SetCute", [1]), ("SetClever", [1]), ("SetStrong", [1]),
    ("SetFur", [1]), ("SetRibbon", [("idx", 128)]), ("RemoveRibbon", [("idx", 128)]),
    ("SetLumpingRibbon", [("idx", 2), 1]), ("SetEquipRibbonNo", [1]),
    ("SetWazaNo", [("idx", 4), 2]), ("SetPP", [("idx", 4), 1]), ("SetWazaPPUpCount", [("idx", 4), 1]),
    ("SetTamagoWazaNo", [("idx", 4), 2]),
    ("SetTalentHp", [4]), ("SetTalentAtk", [4]), ("SetTalentDef", [4]), ("SetTalentSpAtk", [4]), ("SetTalentSpDef", [4]),
    ("SetTalentAgi", [4]), ("SetEffortG", [1]),
    ("SetEventPokemonFlag", [1]), ("SetOfficialBattleEnableFlag", [1]), ("SetSex", [1]), ("SetFormNo", [2]),
    ("SetSeikaku", [1]), ("SetSeikakuHosei", [1]), ("SetTamagoFlag", [1]), ("SetTokusei1Flag", [1]), ("SetTokusei2Flag", [1]),
    ("SetTokusei3Flag", [1]), ("SetFavoriteFlag", [1]), ("SetSpecialGFlag", [1]), ("SetNickNameFlag", [1]),
    ("SetCassetteVersion", [1]), ("SetTamagoGetYear", [1]), ("SetTamagoGetMonth", [1]), ("SetTamagoGetDay", [1]),
    ("SetBirthYear", [1]), ("SetBirthMonth", [1]), ("SetBirthDay", [1]), ("SetGetPlace", [2]), ("SetBirthPlace", [2]),
    ("SetPokerus", [1]), ("SetGetBall", [1]), ("SetGetLevel", [1]), ("SetOyasex", [1]),
    ("SetLevel", [1]), ("SetMaxHp", [2]), ("SetHp", [2]), ("SetAtk", [2]), ("SetDef", [2]), ("SetSpAtk", [2]),
    ("SetSpDef", [2]), ("SetAgi", [2]), ("SetGState", [1]), ("SetEnjoy", [1]), ("SetNadenadeValue", [1]),
    ("SetOthersFriendshipTrainerID", [2]), ("SetOwnedOthersFlag", [1]), ("SetOriginalFriendship", [1]),
    ("SetOthersFriendship", [1]), ("SetMemoriesLevel", [1]), ("SetMemoriesCode", [1]), ("SetMemoriesData", [2]),
    ("SetMemoriesFeel", [1]), ("SetOthersMemoriesLevel", [1]), ("SetOthersMemoriesCode", [1]),
    ("SetOthersMemoriesData", [2]), ("SetOthersMemoriesFeel", [1]), ("SetPastParentsSex", [1]),
    ("SetPastParentsLangID", [1]), ("SetMultiPurposeWork", [4]), ("SetTrainingFlag", [1]),
    ("SetWazaRecordFlag", [("idx", 0x70), ("idx", 2)]), ("SetPokeJobFlag", [("idx", 0x70), ("idx", 2)]),
    ("SetBankUniqueID", [8]), ("ClearBankUniqueID", []), ("ClearWazaRecordFlag", []), ("ClearPokeJobFlag", []),
    ("SetCampFriendship", [1]), ("SetPalma", [4]), ("SetTalentHeight", [1]), ("SetTalentWeight", [1]),
    ("SetBattleRomMark", [1]), ("RemoveAllRibbon", []), ("SetDprIllegalFlag", [1]),
]

# Setter mit Zeichenkette (System.String): Name, Zeichenanzahl-Obergrenze
STRING_SETTERS = ["SetNickName", "SetOyaName", "SetPastParentsName"]


def accessor_addresses():
    """Name -> Ghidra-Adresse aus dem Pseudocode-Export (Kopfzeile `// 0xADRESSE Pml_PokePara_Accessor$$Name`)."""
    out = {}
    for m in re.finditer(r"(?m)^// (0x[0-9a-f]+) Pml_PokePara_Accessor\$\$(\w+)$", ACCESSOR_C.read_text()):
        out.setdefault(m.group(2), int(m.group(1), 16))
    return out


def mask_of(width):
    return (1 << (8 * width)) - 1


def make_string(o, chars):
    """System.String: Laenge bei +0x10, Zeichen ab +0x14 (UTF-16, abschliessende 0)."""
    p = o.alloc(0x20 + 2 * len(chars) + 2)
    o.write(p + 0x10, struct.pack("<I", len(chars)))
    o.write(p + 0x14, b"".join(struct.pack("<H", c) for c in chars) + b"\x00\x00")
    return p


# ---------------------------------------------------------------------------------------------------------------
# Fixture-Gruppen
# ---------------------------------------------------------------------------------------------------------------

def rng_for(name):
    return random.Random("xnu-pokepara-" + name)


def gen_codec():
    o = new_pokepara_oracle()
    rng = rng_for("codec")
    buf_addr = o.alloc(0x400)
    seed_addr = o.alloc(16)

    checksum = []
    for n in (0, 2, 4, 6, 16, 0x140, 0x148, 0x10):
        for _ in range(3):
            data = rng.randbytes(n)
            o.write(buf_addr, data)
            out = o.call(ADDR_CHECKSUM, buf_addr, n) & 0xFFFFFFFF
            checksum.append({"data": hexs(data), "sum": out})
    for _ in range(3):
        data = bytes([0xFF] * 0x140)
        o.write(buf_addr, data)
        checksum.append({"data": hexs(data), "sum": o.call(ADDR_CHECKSUM, buf_addr, 0x140) & 0xFFFFFFFF})

    crypt = []
    seeds = [0, 1, 0xFFFFFFFF, 0x80000000, 0x6073] + [rng.getrandbits(32) for _ in range(11)]
    for seed in seeds:
        for n in (0x10, 0x140):
            data = rng.randbytes(n)
            o.write(buf_addr, data)
            o.call(ADDR_ENCODE, buf_addr, n, seed)
            enc = o.read(buf_addr, n)
            o.write(buf_addr, enc)
            o.call(ADDR_DECODE, buf_addr, n, seed)
            dec = o.read(buf_addr, n)
            crypt.append({"seed": seed, "plain": hexs(data), "encoded": hexs(enc), "decodedAgain": hexs(dec)})

    next_rand = []
    for seed in seeds:
        o.write(seed_addr, struct.pack("<I", seed))
        out = o.call(ADDR_NEXT_RAND, seed_addr)
        new_state = struct.unpack("<I", o.read(seed_addr, 4))[0]
        next_rand.append({"seed": seed, "state": new_state, "code": out & 0xFFFF})

    block_pos = []
    rnds = [shift << 13 for shift in range(32)] + [rng.getrandbits(32) for _ in range(40)]
    for rnd in rnds:
        row = [o.call(ADDR_BLOCK_POS, rnd, b) & 0xFF for b in range(4)]
        block_pos.append({"rnd": rnd, "pos": row})

    rare = []
    for i in range(48):
        tid = rng.getrandbits(32)
        crnd = rng.getrandbits(32)
        if i % 2 == 0:
            # Farbzufall so waehlen, dass die Verrechnung unter 16 faellt (Shiny)
            x = (tid & 0xFFF0) ^ (tid >> 16) ^ (crnd >> 16)
            crnd = (crnd & 0xFFFF0000) | (x & 0xFFF0) | rng.getrandbits(4)
        rare.append({"id": tid, "colorRnd": crnd, "rare": o.call(ADDR_IS_RARE_COLOR, tid, crnd) & 1})

    statics = o.accessor_statics
    table = [o.read_elems(r, "B", 4) for r in o.read_ptr_array(o.u64(statics + 0x20))]
    return {
        "doc": "Pml.PokePara.Encoder und Block-Mischung (Accessor.GetCoreDataBlockPos), ausgefuehrt in Unicorn. Eingaben synthetisch (Zufall, fester Seed).",
        "checksum": checksum,
        "crypt": crypt,
        "nextRand": next_rand,
        "blockPos": block_pos,
        "shuffleTable": table,
        "rare": rare,
    }


def read_getter(o, addrs, slot, name, arg, width):
    a = addrs[name]
    args = [slot.obj] if arg is None else [slot.obj, arg]
    value = o.call(a, *args, max_insns=500000) & mask_of(width)
    return str(value) if width == 8 else value  # 64-Bit-Werte stehen als Strings im JSON


def gen_accessor():
    o = new_pokepara_oracle()
    addrs = accessor_addresses()
    rng = rng_for("accessor")
    slots = []
    n_slots = 32
    for i in range(n_slots):
        # Variationen: zufaellige Seeds; einzelne Slots mit gesetztem/geloeschtem 'ownedByOthers', alle 32 Mischindizes abgedeckt
        rnd = ((i % 32) << 13) | rng.getrandbits(13) | (rng.getrandbits(14) << 18)
        core, calc = random_plain(rng, force_rnd=rnd)
        slot = Slot(o, core, calc)
        entry = {"rnd": rnd, "plainCore": hexs(slot_plain_core(o, slot)), "plainCalc": hexs(calc), "slot": hexs(slot.encoded())}
        get = {}
        for name, rng_spec, width in GETTERS:
            if rng_spec is None:
                get[name] = read_getter(o, addrs, slot, name, None, width)
            else:
                lo, hi = rng_spec
                get[name] = [read_getter(o, addrs, slot, name, k, width) for k in range(lo, hi)]
        assert hexs(slot.encoded()) == entry["slot"], "Getter haben den Slot veraendert"
        entry["get"] = get
        slots.append(entry)
    return {
        "doc": "Echte Accessor-Getter (Pml.PokePara.Accessor) auf synthetischen, vom Spiel selbst kodierten Slots. 'plainCore' ist die Eingabe vor Pruefsumme+Kodierung (Pruefsumme im Kopf wird vom Spiel gesetzt).",
        "slots": slots,
    }


def slot_plain_core(o, slot):
    """Klartext-Kern nach der Kodierung des Spiels: Entschluesseln mit der Referenzimplementierung (Pruefsumme eingesetzt)."""
    enc = o.read(slot.core + 0x20, CORE_SIZE)
    rnd = struct.unpack_from("<I", enc, 0)[0]
    return enc[:HEADER_SIZE] + py_crypt(enc[HEADER_SIZE:], rnd)


def gen_setters():
    o = new_pokepara_oracle()
    addrs = accessor_addresses()
    rng = rng_for("setters")
    bases = []
    base_slots = []
    for i in range(6):
        core, calc = random_plain(rng, force_rnd=((i * 5 + 1) << 13) | rng.getrandbits(13) | (rng.getrandbits(14) << 18))
        bases.append((core, calc))
        base_slots.append(hexs(Slot(o, core, calc).encoded()))
    cases = []
    for name, spec in SETTERS:
        for rep in range(3):
            b = (len(cases) + rep) % len(bases)
            core, calc = bases[b]
            slot = Slot(o, core, calc)
            args = []
            for s in spec:
                if isinstance(s, tuple):
                    args.append(rng.randrange(s[1]))
                else:
                    args.append(rng.getrandbits(8 * s) if rep != 2 else mask_of(s))
            if name in ("SetWazaRecordFlag", "SetPokeJobFlag"):
                args[1] = rep & 1
            o.call(addrs[name], slot.obj, *args, max_insns=500000)
            cases.append({"setter": name, "base": b, "args": [str(a) if a > 0xFFFFFFFF else a for a in args], "after": hexs(slot.encoded())})
    string_cases = []
    for name in STRING_SETTERS:
        for length in (0, 1, 5, 12, 13, 20):
            chars = [rng.randrange(1, 0xD000) for _ in range(length)]
            b = length % len(bases)
            core, calc = bases[b]
            slot = Slot(o, core, calc)
            o.call(addrs[name], slot.obj, make_string(o, chars), max_insns=500000)
            string_cases.append({"setter": name, "base": b, "chars": chars, "after": hexs(slot.encoded())})
    return {
        "doc": "Echte Accessor-Setter: Basis-Slot (vom Spiel kodiert, Index 'base') und Slot nach dem Aufruf. Argumente: Zahlen bzw. Zeichencodes.",
        "bases": base_slots,
        "cases": cases,
        "stringCases": string_cases,
    }


GROUPS = {
    "codec": ("PokeParaCodec.json", gen_codec),
    "accessor": ("PokeParaAccessor.json", gen_accessor),
    "setters": ("PokeParaSetters.json", gen_setters),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", nargs="*", choices=sorted(GROUPS), help="nur diese Gruppen")
    args = ap.parse_args(argv)
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
