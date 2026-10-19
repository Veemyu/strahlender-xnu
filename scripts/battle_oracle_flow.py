#!/usr/bin/env python3
"""Emulations-Orakel der Kampf-Scheibe 4 (Kampfablauf): fuehrt ECHTE ARM64-Funktionen aus work/elf/main.patched.elf aus.

Geprueft werden die reinen Ablauf-Regeln (nur Zahlen als Fixtures, synthetische Eingaben mit festem Seed):
  actpri     ActPri.* (Sortierschluessel einer Aktion)                                [O]
  sickcont   SICKCONT.Make*/Get* (Dauer eines Zustands, 64 Bit)                        [O]
  sickturn   BTL_POKEPARAM.WazaSick_TurnCheck / CheckNemuriWakeUp / CheckKonranWakeUp / CalcSickDamage
             auf synthetischem Gast-Speicher (Zustands-/Zaehler-Arrays)                [O]
  escape     Section_Escape_Sub.checkEscapeEnableByAgi (Fluchtformel, echter RNG)      [OK]
  sort       Section_SortActionOrder.sort (Reihenfolge, Gleichstand-Zuege, echter RNG) [OK]
  agility    EventLauncher.Event_CalcAgility (Paralyse, Deckel, Bereich der Ordnung)   [OK]
  confdmg    Section_ConfDamage.calcDamage (Verwirrungsschaden, echter RNG)            [OK]
  tables     tables..cctor: Reihenfolge der Rundenende-Zustaende                       [O]
[OK] = die geprueften Funktionen laufen echt, Nachbarfunktionen (Pokemon-Abfragen, Ereignisse) sind Stubs mit Testwerten.

Aufruf:  PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_flow.py [--out DIR] [--only NAME ...]
Ausgabe: unity/Assets/Tests/EditMode/Fixtures/BattleFlow.json
"""
import argparse
import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_oracle as bo  # noqa: E402

ROOT = bo.ROOT
OUT_DEFAULT = bo.DEFAULT_OUT
IB = bo.IMAGE_BASE

CALC_CLASS_SLOT = 0x4C7F038


def decomp(name):
    return bo.read_decomp("battle_all/Dpr_Battle_Logic_" + name + ".c")


def rng_of(name):
    return random.Random("xnu-battle-slice4-" + name)


def u32(v):
    return v & 0xFFFFFFFF


def u64(v):
    return v & 0xFFFFFFFFFFFFFFFF


def calc_statics(o):
    return o.u64(o.u64(o.u64(CALC_CLASS_SLOT - IB)) + 0xB8)


def install_rng(o, seed):
    """Setzt einen frischen echten Xoroshiro128+ als calc.g_RandSys; liefert das Zufallsobjekt."""
    rnd = bo.make_random_object(o, seed)
    o.write(calc_statics(o), struct.pack("<Q", rnd))
    return rnd


def next_rand(o, rnd):
    return str(o.call(0x18D8FF0, o.u64(rnd + 0x10)))


# ---------------------------------------------------------------------------------------------------------------
def gen_actpri():
    o = bo.new_oracle()
    o.prepare(decomp("ActPri"))
    r = rng_of("actpri")
    make, change_agi, change_waza = 0x1BBD360, 0x1BBD380, 0x1BBD390
    get_waza, get_sp, get_op, get_dom = 0x1BBD3A0, 0x1BBD3B0, 0x1BBD3C0, 0x1BBD3D0
    set_dom, set_sp, to_handler, to_org = 0x1BBD3E0, 0x1BBD3F0, 0x1BBD400, 0x1BBD410
    cases = []
    for i in range(500):
        big = i % 5 == 0
        d, op, wz, sp = (r.getrandbits(32) if big else r.randint(0, 7), r.getrandbits(32) if big else r.randint(0, 7),
                         r.getrandbits(32) if big else r.randint(0, 20), r.getrandbits(32) if big else r.randint(0, 2))
        ag = r.getrandbits(32) if big else r.randint(0, 10000)
        made = u32(o.call(make, d, op, wz, sp, ag))
        pri = r.getrandbits(32) if i % 3 == 0 else made
        v = r.getrandbits(32)
        cases.append({
            "dominant": d, "operation": op, "wazaPri": wz, "spPri": sp, "agility": ag, "make": made,
            "pri": pri, "value": v,
            "changeAgility": u32(o.call(change_agi, pri, v)), "changeWazaPriority": u32(o.call(change_waza, pri, v)),
            "getWazaPri": u32(o.call(get_waza, pri)), "getSpPri": u32(o.call(get_sp, pri)), "getOperationPri": u32(o.call(get_op, pri)),
            "getDominantPri": u32(o.call(get_dom, pri)), "setDominantPri": u32(o.call(set_dom, pri, v)),
            "setSpPri": u32(o.call(set_sp, pri, v)), "toHandlerPri": u32(o.call(to_handler, pri)),
            "toWazaOrgPri": bo.to_s32(o.call(to_org, pri)),
        })
    return {"doc": "Dpr.Battle.Logic.ActPri (echte Funktionen).", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
def gen_sickcont():
    o = bo.new_oracle()
    src = decomp("SICKCONT")
    o.prepare(src)
    o.prepare(decomp("BTL_SICKCONT"))
    r = rng_of("sickcont")
    A = {
        "makeNull": 0x21D4600, "makeTurn": 0x21D4680, "makeTurnParam": 0x21D46F0, "makePoke": 0x21D4770, "makePermanent": 0x21D47D0,
        "makePermanentInc": 0x21D4820, "makePermanentParam": 0x21D4880, "makePermanentIncParam": 0x21D48E0, "makePokeTurn": 0x21D4960,
        "makePokeTurnParam": 0x21D49E0, "makeMoudokuCont": 0x21D4A70,
    }
    G = {"isNull": 0x21D4640, "isMoudokuCont": 0x21D4AD0, "getPokeID": 0x21D4B40, "getTurnMax": 0x21D4C60, "getParam": 0x21D4DE0, "getFlag": 0x21D4FC0}
    cell = o.alloc(16)
    cases = []

    def getters(packed):
        o.write(cell, struct.pack("<Q", packed))
        out = {}
        for k, a in G.items():
            res = o.call(a, cell)
            out[k] = res & 0xFFFFFFFF if k not in ("isNull", "isMoudokuCont") else res & 1
        return out

    def add(kind, args):
        packed = u64(o.call(A[kind], *args))
        c = {"kind": kind, "args": args, "packed": str(packed)}
        c.update(getters(packed))
        cases.append(c)

    for i in range(600):
        cause = r.choice([0, 1, 5, 12, 31, 0x1F, 40, 255]) if i % 3 == 0 else r.randint(0, 31)
        turns = r.choice([0, 1, 4, 63, 64, 100]) if i % 4 == 0 else r.randint(0, 15)
        param = r.choice([0, 0xFFFF, 0x1FFFF, 0x1234, 165]) if i % 4 == 0 else r.randint(0, 600)
        pid = r.choice([0, 5, 63, 64, 100]) if i % 4 == 0 else r.randint(0, 11)
        kind = r.choice(list(A))
        arg_counts = {"makeNull": 0, "makeTurn": 2, "makeTurnParam": 3, "makePoke": 2, "makePermanent": 1, "makePermanentInc": 2,
                      "makePermanentParam": 2, "makePermanentIncParam": 3, "makePokeTurn": 3, "makePokeTurnParam": 4, "makeMoudokuCont": 1}
        pool = {
            "makeTurn": [cause, turns], "makeTurnParam": [cause, turns, param], "makePoke": [cause, pid], "makePermanent": [cause],
            "makePermanentInc": [cause, turns], "makePermanentParam": [cause, param], "makePermanentIncParam": [cause, turns, param],
            "makePokeTurn": [cause, pid, turns], "makePokeTurnParam": [cause, pid, turns, param], "makeMoudokuCont": [cause], "makeNull": [],
        }
        add(kind, pool[kind][:arg_counts[kind]])
    return {"doc": "Dpr.Battle.Logic.SICKCONT: Make*/Get* (echte Funktionen); packed als String (64 Bit).", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
class SickWorld:
    """Synthetisches BTL_POKEPARAM: Core (+0x10) mit Zustands-Array (+0x48, ulong[]) und Zaehler-Array (+0x50, byte[])."""

    COUNT = 45

    def __init__(self, o):
        self.o = o
        self.poke = o.alloc(0x200)
        self.core = o.alloc(0x100)
        o.write(self.poke + 0x10, struct.pack("<Q", self.core))
        self.cfg = {"maxHp": 100, "tokusei": 0, "effTokusei": 0}
        o.stub(0x20DD010, lambda o_, a, b: self.cfg["maxHp"] if (b & 0xFFFFFFFF) == 0xF else (self.cfg["effTokusei"] if (b & 0xFFFFFFFF) == 0x13 else 0))
        o.stub(0x20DB9A0, lambda o_, a, b: 0)  # IsGMode

    def load(self, conts, counters, tokusei=0, max_hp=100, eff_tokusei=0):
        o = self.o
        self.cfg.update(maxHp=max_hp, tokusei=tokusei, effTokusei=eff_tokusei)
        carr = o.make_array(8, conts)
        narr = o.make_array(1, counters)
        o.write(self.core + 0x48, struct.pack("<Q", carr))
        o.write(self.core + 0x50, struct.pack("<Q", narr))
        o.write(self.poke + 0x38, struct.pack("<H", tokusei))
        o.write(self.poke + 0xA0, struct.pack("<Q", 0))
        self.carr, self.narr = carr, narr

    def conts(self):
        return [str(v) for v in self.o.read_elems(self.carr, "Q", self.COUNT)]

    def counters(self):
        return self.o.read_elems(self.narr, "B", self.COUNT)


def random_cont(r, kind):
    """Dauer-Werte ueber die echten Make-Funktionen sind nicht noetig: Bitmuster nach dem Layout, plus Zufall."""
    t = {"none": 0, "perm": 1, "turn": 2, "poke": 3, "poketurn": 4}[kind]
    cause = r.randint(0, 31)
    count = r.randint(0, 15) if r.random() < 0.8 else r.randint(0, 63)
    param = r.randint(0, 300)
    val = t | cause << 3 | count << 8
    if t == 4:
        val |= r.randint(0, 11) << 14 | param << 20
    else:
        val |= param << 14
    return val


def gen_sickturn():
    o = bo.new_oracle()
    bo.setup_calc_class(o)
    for name in ("BTL_POKEPARAM", "SICKCONT", "BTL_SICKCONT"):
        o.prepare(decomp(name))
    world = SickWorld(o)
    r = rng_of("sickturn")
    out_cont, out_flag = o.alloc(16), o.alloc(16)
    kinds = ["none", "perm", "turn", "poke", "poketurn"]
    turn_cases, nemuri_cases, konran_cases, dmg_cases = [], [], [], []
    for i in range(700):
        conts = [bo.SICKCONT_NULL if hasattr(bo, "SICKCONT_NULL") else (0x1F << 3)] * SickWorld.COUNT
        counters = [0] * SickWorld.COUNT
        sick = r.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 20, 21, 23, 36, 43, 44])
        kind = r.choice(kinds) if i % 2 else r.choice(["perm", "turn", "turn", "poketurn"])
        conts[sick] = random_cont(r, kind)
        if kind == "perm" and r.random() < 0.5:
            conts[sick] = (conts[sick] & ~(0x3F << 8)) | (r.choice([0, 0xF, 3, 1]) << 8)
        counters[sick] = r.choice([0, 0, 1, 2, 3, 14, 15, 63, 200, 255]) if i % 3 == 0 else r.randint(0, 6)
        world.load(conts, counters)
        o.write(out_cont, struct.pack("<Q", 0xDEAD))
        o.write(out_flag, b"\xAA")
        ret = o.call(0x20E10F0, world.poke, sick, out_cont, out_flag) & 0xFF
        turn_cases.append({
            "sick": sick, "conts": [str(c) for c in conts[:SickWorld.COUNT]], "counters": counters,
            "ret": ret & 1, "outCont": str(o.u64(out_cont)), "outFlag": o.read(out_flag, 1)[0],
            "contsAfter": world.conts(), "countersAfter": world.counters(),
        })

    for i in range(300):
        conts = [0x1F << 3] * SickWorld.COUNT
        counters = [0] * SickWorld.COUNT
        tokusei = r.choice([0, 0x30, 0x30, 1, 100, 213])
        kind = r.choice(["none", "turn", "turn", "perm", "poketurn"])
        conts[2] = random_cont(r, kind)
        conts[6] = random_cont(r, r.choice(["none", "turn", "turn", "poke"]))
        counters[2] = r.randint(0, 6) if i % 4 else r.choice([0, 255, 200])
        counters[6] = r.randint(0, 6) if i % 4 else r.choice([0, 255, 200])
        world.load(conts, counters, tokusei=tokusei)
        res = o.call(0x20E1370, world.poke) & 1
        nemuri_cases.append({"cont": str(conts[2]), "counter": counters[2], "tokusei": tokusei, "ret": res, "counterAfter": world.counters()[2]})
        world.load(conts, counters, tokusei=tokusei)
        res = o.call(0x20E1520, world.poke) & 1
        konran_cases.append({"cont": str(conts[6]), "counter": counters[6], "ret": res, "counterAfter": world.counters()[6]})

    for i in range(500):
        conts = [0x1F << 3] * SickWorld.COUNT
        counters = [0] * SickWorld.COUNT
        sick = r.choice([4, 5, 5, 9, 10, 8, 1, 2, 6])
        kind = r.choice(["perm", "perm", "turn", "none"])
        conts[sick] = random_cont(r, kind)
        if sick == 5 and r.random() < 0.6:
            conts[sick] = 1 | r.randint(0, 31) << 3 | 0xF << 8
        counters[sick] = r.randint(0, 15)
        if sick == 9 and r.random() < 0.7:
            conts[2] = random_cont(r, "turn")
        max_hp = r.choice([1, 5, 15, 16, 17, 100, 241, 999, 65535]) if i % 3 == 0 else r.randint(1, 400)
        eff = 213 if i % 7 == 0 else r.choice([0, 20, 108])
        world.load(conts, counters, max_hp=max_hp, eff_tokusei=eff)
        res = u32(o.call(0x20DE0C0, world.poke, sick))
        dmg_cases.append({"sick": sick, "conts": [str(c) for c in conts], "counters": counters, "maxHp": max_hp, "effTokusei": eff, "damage": res})
    return {"doc": "BTL_POKEPARAM: WazaSick_TurnCheck, CheckNemuriWakeUp, CheckKonranWakeUp, CalcSickDamage auf synthetischem Gast-Speicher.",
            "turnCheck": turn_cases, "nemuri": nemuri_cases, "konran": konran_cases, "sickDamage": dmg_cases}


# ---------------------------------------------------------------------------------------------------------------
def gen_escape():
    o = bo.new_oracle()
    bo.setup_calc_class(o)
    o.prepare(decomp("Section_Escape_Sub"))
    r = rng_of("escape")
    section, own, foe = o.alloc(0x100), o.alloc(0x100), o.alloc(0x100)
    agi = {}
    o.stub(0x21D64B0, lambda o_, a, b: foe)                       # Section.GetPokeParam(clientID 1, 0)
    o.stub(0x20DD9E0, lambda o_, a, b: agi[a])                    # BTL_POKEPARAM.GetValue_Base(AGILITY)
    cases = []
    for i in range(900):
        a = r.choice([0, 1, 10, 65535, 70000]) if i % 11 == 0 else r.randint(1, 400)
        b = r.choice([0, 1, 65535]) if i % 13 == 0 else r.randint(1, 400)
        if i % 3 == 0:
            b = max(1, a + r.randint(-20, 60))
        tries = r.choice([0, 1, 2, 3, 4, 5, 255, 256, 257]) if i % 5 == 0 else r.randint(0, 6)
        seed = r.getrandbits(48)
        agi[own], agi[foe] = a, b
        rnd = install_rng(o, seed)
        res = o.call(0x22B73C0, section, own, tries) & 1
        cases.append({"own": a, "foe": b, "tries": tries, "seed": str(seed), "ok": res, "nextRand": next_rand(o, rnd)})
    return {"doc": "Section_Escape_Sub.checkEscapeEnableByAgi (echt) mit ersetzten Pokemon-Abfragen; nextRand prueft die Zahl der Zuege.", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
def gen_sort():
    o = bo.new_oracle()
    bo.setup_calc_class(o)
    o.prepare(decomp("Section_SortActionOrder"))
    r = rng_of("sort")
    section, container = o.alloc(0x100), o.alloc(0x100)
    state = {"items": []}

    def get(o_, a, b):
        return state["items"][b & 0xFF]

    def swap(o_, a, b):
        i, j = b & 0xFF, o_.arg(2) & 0xFF
        state["items"][i], state["items"][j] = state["items"][j], state["items"][i]
        return None

    o.stub(0x2142AE0, get)
    o.stub(0x2142B30, swap)
    cases = []
    for i in range(700):
        n = r.choice([2, 2, 2, 3, 4, 5, 6])
        pool = [r.getrandbits(32)] if i % 4 == 0 else [r.randint(0, 3) for _ in range(3)]
        pris = [r.choice(pool) if i % 4 else r.getrandbits(32) for _ in range(n)]
        if i % 4 == 0:
            pris = [r.choice([5, 5, 7, 9]) for _ in range(n)]
        elems = []
        for k, pri in enumerate(pris):
            e = o.alloc(0x80)
            o.write(e + 0x10, struct.pack("<I", k))
            o.write(e + 0x40, struct.pack("<I", pri))
            elems.append(e)
        state["items"] = list(elems)
        o.write(container + 0x18, bytes([n]))
        seed = r.getrandbits(48)
        rnd = install_rng(o, seed)
        o.call(0x22CD470, section, container)
        order = [struct.unpack("<I", o.read(e + 0x10, 4))[0] for e in state["items"]]
        cases.append({"pris": pris, "seed": str(seed), "order": order, "nextRand": next_rand(o, rnd)})
    return {"doc": "Section_SortActionOrder.sort (echt) mit Python-Container; order = urspruengliche Indizes in Endreihenfolge.", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
class AgiModel(bo.EventModel):
    def _call(self, event_id):
        if event_id == 0x13:
            f = self.frames[-1]
            f[0x38] = self.cfg["ratio"]
            f[0x51] = self.cfg["trick"]
            if "genAfter" in self.cfg:
                f[0x59] = self.cfg["genAfter"]


def gen_agility():
    o = bo.new_oracle()
    bo.setup_calc_class(o)
    o.prepare(bo.read_decomp("battle_all/Dpr_Battle_Logic_EventLauncher.c"))
    model = AgiModel(o)
    launcher, evsys, mainmod, poke = (o.alloc(0x100) for _ in range(4))
    o.write(launcher + 0x10, struct.pack("<Q", mainmod))
    o.write(launcher + 0x18, struct.pack("<Q", evsys))
    r = rng_of("agility")
    cases = []
    for i in range(900):
        value = r.choice([0, 1, 5, 65535, 9999, 10000, 20000]) if i % 6 == 0 else r.randint(1, 800)
        ratio = r.choice([0x1000, 0x1000, 0x800, 0x2000, 0x1800, 0x666, 0x19A, 0x20000, 0x4000])
        sick = r.choice([0, 0, 1, 2, 4])
        trick = r.choice([0, 1])
        flag = r.choice([1, 1, 0])
        gen_after = r.choice([None, 0, 1])
        model.cfg = {"values": {12: value}, "sick": sick, "ratio": ratio, "trick": trick}
        if gen_after is not None:
            model.cfg["genAfter"] = gen_after
        res = to_i = bo.to_s32(o.call(0x1E179A0, launcher, poke, flag))
        cases.append({"value": value, "ratioIn": ratio, "sick": sick, "trick": trick, "flag": flag,
                      "genAfter": -1 if gen_after is None else gen_after, "out": res})
    return {"doc": "Event_CalcAgility (echt); Handler-Ergebnisse (Verhaeltnis, Bereich der Ordnung, Paralyse-Flag) sind Eingaben.", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
def gen_confdmg():
    o = bo.new_oracle()
    bo.setup_calc_class(o)
    o.prepare(decomp("Section_ConfDamage"))
    section, poke = o.alloc(0x100), o.alloc(0x100)
    vals = {}
    o.stub(0x20DD010, lambda o_, a, b: vals.get(b & 0xFFFFFFFF, 0))
    r = rng_of("confdmg")
    cases = []
    for i in range(500):
        atk = r.choice([1, 5, 999, 4000, 70000]) if i % 6 == 0 else r.randint(1, 600)
        dfn = r.choice([0, 1, 999]) if i % 9 == 0 else r.randint(1, 600)
        level = r.choice([1, 100, 255]) if i % 7 == 0 else r.randint(1, 100)
        vals.clear()
        vals.update({8: atk, 9: dfn, 0x11: level})
        seed = r.getrandbits(48)
        rnd = install_rng(o, seed)
        res = u32(o.call(0x22B56A0, section, poke))
        cases.append({"atk": atk, "def": dfn, "level": level, "seed": str(seed), "damage": res, "nextRand": next_rand(o, rnd)})
    return {"doc": "Section_ConfDamage.calcDamage (echt) mit ersetzten Wertabfragen.", "cases": cases}


# ---------------------------------------------------------------------------------------------------------------
def gen_tables():
    o = bo.new_oracle()
    src = bo.read_decomp("battle_all/Dpr_Battle_Logic_tables.c")
    statics = o.run_cctor(0x207ABF0, 0x4C7F040, src)
    order = o.read_elems(o.u64(statics + 0x110), "i")
    return {"doc": "tables..cctor: tables.GetTurnCheckWazaSickByOrder (Zustaende in Rundenende-Reihenfolge, 0 beendet).", "turnCheckSickOrder": order}


GROUPS = {
    "actpri": gen_actpri, "sickcont": gen_sickcont, "sickturn": gen_sickturn, "escape": gen_escape, "sort": gen_sort,
    "agility": gen_agility, "confdmg": gen_confdmg, "tables": gen_tables,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--only", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args(argv)
    out = {"doc": "Orakel der Kampf-Scheibe 4 (Ablauf). Erzeugt von scripts/battle_oracle_flow.py. Nur Zahlen."}
    for name, fn in GROUPS.items():
        if args.only and name not in args.only:
            continue
        data = fn()
        out[name] = data
        n = sum(len(v) for v in data.values() if isinstance(v, list))
        print(f"{name}: {n} Eintraege")
    path = Path(args.out) / ("BattleFlow.json" if not args.only else "BattleFlow." + "-".join(args.only) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    print("geschrieben:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
