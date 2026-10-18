#!/usr/bin/env python3
"""Handler-Orakel der Kampf-Scheibe 3: fuehrt die ECHTEN Handler-Funktionen (Tokusei, Item, Waza) aus work/elf im Unicorn-Orakel aus.

Je (Nummer, Ereignis) laufen N zufaellige Szenarien im echten EventSystem: Variablen setzen, Ereignis aufrufen, Variablen und
Aufrufprotokoll als Zahlen speichern. Die Pokemon-/Feldabfragen (BTL_POKEPARAM.*, Common.GetWeather, IsFriendPokeID, ...) sind
Stubs mit Testwerten (Pruefstufe [OK]); der Handler selbst, Common.GetEventVar/MulEventVar/RewriteEventVar und das Ereignissystem sind echt.

Voraussetzung: work/battleevents/handler_map.json (scripts/battle_handler_map.py).
Aufruf: PYTHONPATH=tools/pydeps python3 scripts/battle_oracle_handlers.py [--out DIR] [--cases N]
Ausgabe: unity/Assets/Tests/EditMode/Fixtures/BattleHandlers.json (nur Zahlen)
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_handler_priority as bhp  # noqa: E402
import battle_oracle as bo  # noqa: E402
import battle_oracle_heap as bh  # noqa: E402

ROOT = bh.ROOT
MAP = ROOT / "work/battleevents/handler_map.json"

# Umgesetzte Nummern (spiegeln die Registrierung in HandlersSlice3.cs / WazaHandlers.cs; der Unity-Test prueft die Gleichheit)
TOKUSEI = [1, 4, 8, 14, 32, 33, 34, 37, 47, 69, 74, 75, 77, 79, 81, 86, 89, 91, 92, 97, 98, 101, 105, 126, 132, 134, 135, 136, 137, 138,
           146, 147, 162, 169, 177, 181, 196, 198, 200, 202, 203, 204, 205, 212, 217, 218, 231, 233, 246, 247, 249, 252, 239, 242]
ITEM = [222, 237, 238, 239, 240, 241, 242, 233, 243, 244, 246, 247, 248, 249, 250, 251, 314, 315, 317, 254, 318, 298, 299, 300, 301, 302,
        303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313, 644, 284, 285, 282, 283, 296, 232, 326, 266, 276, 213, 255, 226, 227, 258,
        257, 274, 259, 256, 225, 215, 289, 290, 291, 292, 293, 294, 539, 543, 640, 1123, 879,
        220, 265, 267, 268]
WAZA = [371, 372, 754, 755, 512, 474, 788, 74, 246, 702, 599, 602, 674, 86, 473, 540, 548, 776, 213, 234, 235, 236, 659, 46, 18, 59, 101,
        69, 162, 717, 492, 206, 610, 573, 329, 744, 781, 782, 533, 663, 745, 89, 16, 239, 57, 23, 34, 407]
CLASSES = {"Tokusei": (TOKUSEI, 4, 7), "Item": (ITEM, 5, 8), "Waza": (WAZA, 0, 1)}

FN3 = {
    "bpp_getvalue": 0x20DD010, "bpp_hpfull": 0x20DDCE0, "bpp_monsno": 0x20DCFB0, "bpp_item": 0x20DFD50, "bpp_matchtype": 0x20DFAD0,
    "get_weather": 0x1E0B850, "get_local_weather": 0x1E0B900, "is_friend": 0x1E0A040, "check_field": 0x1E0A260, "waza_flag": 0x2072BF0,
    "bpp_contflag": 0x20DFA30,
}
SPECIAL_MONS = [0x84, 0x16E, 0x68, 0x69, 0x17C, 0x17D, 0x53, 0x71, 25, 1, 0]
ID_LABELS = {"POKEID", "POKEID_ATK", "POKEID_DEF", "SWAP_POKEID"}
GETVAR = re.compile(r"(?:GetEventVar|MulEventVar|RewriteEventVar)\(param_1,(0x[0-9a-f]+|\d+)")


def labels_by_name():
    src = (ROOT / "unity/Assets/Scripts/BattleEvents/EventIds.cs").read_text()
    body = src.split("enum EventVarLabel")[1].split("}")[0]
    return {n: int(v) for n, v in re.findall(r"([A-Z0-9_]+) = (\d+)", body)}


NAMES = labels_by_name()
BY_ID = {v: k for k, v in NAMES.items()}


class Closure:
    """Variable-Labels, die ein Handler samt Hilfsfunktionen der Klasse liest oder aendert, und die Reinheitsanalyse."""

    def __init__(self, cls):
        self.funcs = bhp.split_funcs(bhp.DECOMP / f"Dpr_Battle_Logic_Handler_{cls}.c")
        self.by_name = {n.replace("$$", "__").replace(".", "_"): a for a, (n, _t) in self.funcs.items()}
        self.info = bhp.analyze(cls)

    def labels(self, addr, seen=None):
        seen = seen if seen is not None else set()
        if addr in seen:
            return set()
        seen.add(addr)
        text = self.funcs[addr][1]
        out = {int(m, 16) if m.startswith("0x") else int(m) for m in GETVAR.findall(text)}
        if "GetEventVar_DAMAGE_TYPE" in text:
            out.add(NAMES["DAMAGE_TYPE"])
        if "MulWazaBasePower" in text:
            out.add(NAMES["WAZA_POWER"])
        for c in bhp.CALL.findall(text):
            if c in self.by_name:
                out |= self.labels(self.by_name[c], seen)
        return out


def install_stubs(o):
    if getattr(o, "_h3_stubs", False):
        return
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_LR, UC_ARM64_REG_PC

    def cfg(p):
        return o.world.pokes[p]

    def value(_o, p, vid):
        c = cfg(p)
        table = {13: c["hp"], 14: c["hp"], 15: c["maxHp"], 16: c["maxHp"], 17: c["level"], 18: c["tokusei"], 19: c["tokuseiEff"], 20: c["sex"]}
        return table.get(vid & 0xFFFFFFFF, 0)

    o.stub(FN3["bpp_getvalue"], value)
    o.stub(FN3["bpp_hpfull"], lambda _o, p, _b: int(cfg(p)["hp"] == cfg(p)["maxHp"]))
    o.stub(FN3["bpp_monsno"], lambda _o, p, _b: cfg(p)["monsNo"])
    o.stub(FN3["bpp_item"], lambda _o, p, _b: cfg(p)["item"])
    o.stub(FN3["bpp_matchtype"], lambda _o, p, t: int((t & 0xFF) in cfg(p)["types"]))
    o.stub(FN3["bpp_contflag"], lambda _o, p, f: int((f & 0xFFFFFFFF) in cfg(p)["contFlags"]))
    o.stub(FN3["get_weather"], lambda _o, _a, _b: o.world.env["weather"])
    o.stub(FN3["get_local_weather"], lambda _o, _a, _b: o.world.env["localWeather"])
    o.stub(FN3["check_field"], lambda _o, _a, ptr: int(o.read_u32(ptr) in o.world.env["fieldEffects"]))
    o.stub(FN3["waza_flag"], lambda _o, _id, flag: int((flag & 0xFFFFFFFF) in o.world.env["wazaFlags"]))
    target = FN3["is_friend"] - bh.IMAGE_BASE

    def friend(uc, address, size, _user):
        if address != target:
            return
        a = uc.reg_read(UC_ARM64_REG_X1) & 0xFF
        b = uc.reg_read(UC_ARM64_REG_X2) & 0xFF
        uc.reg_write(UC_ARM64_REG_X0, int(a % 2 == b % 2))
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    o._u.hook_add(UC_HOOK_CODE, friend, begin=target, end=target)
    o._h3_stubs = True


def random_poke(rnd):
    maxhp = rnd.randint(1, 400)
    sick = sorted(rnd.sample([4, 5, 6, 16], rnd.randint(0, 2)))
    tokusei = rnd.choice([rnd.randint(0, 270), 0x39, 0x3A])
    return {"sick": sick, "gas": 0, "hensin": int(rnd.random() < 0.25),
            "gmode": int(rnd.random() < 0.25), "turnFlags": sorted(rnd.sample([1, 2, 9, 0x12], rnd.randint(0, 2))),
            "hp": maxhp if rnd.random() < 0.4 else rnd.randint(0, maxhp), "maxHp": maxhp, "level": rnd.randint(1, 100),
            "sex": rnd.choice([0, 1, 2]), "tokusei": tokusei, "tokuseiEff": 0 if 16 in sick else tokusei,
            "item": rnd.choice([0, 0, rnd.randint(1, 600)]), "monsNo": rnd.choice(SPECIAL_MONS + [rnd.randint(0, 900)]),
            "types": sorted(rnd.sample(range(18), rnd.randint(0, 2))), "contFlags": sorted(rnd.sample([3, 4, 5, 8], rnd.randint(0, 3)))}


def random_value(rnd, label, me):
    name = BY_ID.get(label, "")
    if name in ID_LABELS:
        return me if rnd.random() < 0.5 else rnd.randint(0, 3)
    if name in ("WAZA_TYPE", "POKE_TYPE"):
        return rnd.choice([0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, rnd.randint(0, 17)])
    if name == "DAMAGE_TYPE":
        return rnd.randint(0, 2)
    if name == "TYPEAFF":
        return rnd.randint(0, 13)
    if name == "WEATHER":
        return rnd.randint(0, 7)
    if name.endswith("_FLAG") or name in ("ENABLE_FLAG", "CAN_AIM_TARGET"):
        return rnd.randint(0, 1)
    if name == "POKE_HIDE":
        return rnd.randint(0, 6)
    if name == "WAZAID":
        return rnd.randint(1, 800)
    if name in ("WAZA_POWER", "HIT_PER"):
        return rnd.choice([0, 20, 50, 51, 60, 61, 80, 100, rnd.randint(0, 250)])
    if name == "CRITICAL_RANK":
        return rnd.randint(-3, 8)
    if name == "VOLUME":
        return rnd.randint(-6, 6)
    if name in ("STATUS_TYPE", "VID", "SICKID"):
        return rnd.choice([0, 5, 6, 9, 10, 11, rnd.randint(0, 14)])
    if name in ("WAZA_PRI", "TURN_COUNT"):
        return rnd.randint(-3, 8)
    if name in ("ADD_PER", "ADD_DEFAULT_PER"):
        return rnd.choice([0, 0, 10, 20, 0x4000, 0x7FFF, 0x8001, rnd.randint(0, 100)])
    return rnd.choice([0, 1, 2, 7, 8, 0x1000, rnd.randint(0, 3000), rnd.randint(-5, 300)])


def make_case(o, rnd, cls, number, event, addr, ftype, pri, labels):
    me = rnd.randint(0, 3)
    pokes = {str(i): random_poke(rnd) for i in range(4)}
    env = {"pokes": pokes, "fieldEffects": [2] if rnd.random() < 0.4 else [], "ommitHensin": [], "ommitG": [],
           "itemParam": rnd.choice([0, 10, 20, 30, 50, 100, 120, -50, rnd.randint(-120, 400), rnd.randint(0, 5000)]),
           "weather": rnd.randint(0, 7), "localWeather": rnd.randint(0, 7),
           "wazaFlags": sorted(rnd.sample([7, 8, 0xC], rnd.randint(0, 3)))}
    steps = [["push"]]
    for label in sorted(labels):
        name = BY_ID.get(label, "")
        v = random_value(rnd, label, me)
        if name in ID_LABELS:
            steps.append(["const", label, v])
            continue
        kind = rnd.choice(["set", "set", "once", "mul"])
        if kind == "mul":
            lo, hi = rnd.choice([(0x29, 0x20000), (0x19A, 0x20000), (0, 0)])
            steps.append(["mulset", label, rnd.choice([0x1000, 0x800, 0x2000]), lo, hi])
        else:
            steps.append([kind, label, v])
    steps.append(["call", event])
    for label in sorted(labels):
        steps.append(["val", label])
    spec = {"type": ftype, "subID": number, "mainPri": pri, "subPri": rnd.randint(0, 300), "dependID": me,
            "entries": [{"event": event, "ops": [], "real": addr}]}
    case = {"cls": cls, "no": number, "event": event, "env": env, "adds": [spec], "steps": steps}
    case.update(bh.run_call_case(o, case))
    return case


def generate(n_cases):
    o = bh.EventOracle()
    hmap = json.loads(MAP.read_text())
    out = []
    skipped = []
    for cls, (numbers, ftype, pri) in CLASSES.items():
        o.prepare(bh.decomp_text(f"Dpr_Battle_Logic_Handler_{cls}.c"))
        install_stubs(o)
        closure = Closure(cls)
        for number in numbers:
            entries = hmap[cls][str(number)]["entries"]
            for event, _name, addr in entries:
                if closure.info.get(addr, {"impure": ["?"]})["impure"]:
                    skipped.append([cls, number, event, "Wirkungsebene"])
                    continue
                rnd = random.Random(f"xnu-handlers3-{cls}-{number}-{event}")
                labels = closure.labels(addr)
                try:
                    for _ in range(n_cases):
                        out.append(make_case(o, rnd, cls, number, event, addr, ftype, pri, labels))
                except bh.GuestError as e:
                    skipped.append([cls, number, event, str(e)[:60]])
    return {"cases": out, "skipped": skipped}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(bo.DEFAULT_OUT))
    ap.add_argument("--cases", type=int, default=14)
    args = ap.parse_args()
    data = generate(args.cases)
    path = Path(args.out) / "BattleHandlers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    called = sum(1 for c in data["cases"] if any(e[0] >= 0 for e in c["log"]))
    print(f"{len(data['cases'])} Faelle ({called} mit Handleraufruf), {len(data['skipped'])} Eintraege uebersprungen -> {path}")
    for s in data["skipped"]:
        print("  uebersprungen:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
