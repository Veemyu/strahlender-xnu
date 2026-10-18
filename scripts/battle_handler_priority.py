#!/usr/bin/env python3
"""Priorisierte Handler-Liste (Kampf-Scheibe 3): Haeufigkeit in den Stammdaten x Einfachheit im Pseudocode.

Liest work/battleevents/handler_map.json (scripts/battle_handler_map.py), work/masterdata (PersonalTable, TrainerTable,
WazaOboeTable) und work/decomp/battle_all (nur lesen). Ausgabe: work/battleevents/handler_priority.json (nur Zahlen/IDs).
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECOMP = ROOT / "work/decomp/battle_all"
MASTER = ROOT / "work/masterdata"
OUT = ROOT / "work/battleevents/handler_priority.json"

CALL = re.compile(r"\b((?:Dpr_[A-Za-z0-9_]+|FUN_[0-9a-f]+|thunk_FUN_[0-9a-f]+))\(")
NOISE = {"FUN_003afbe0", "thunk_FUN_00364fe0"}
# Aufrufe, die ohne Wirkungs-/Meldungsebene im Orakel laufen (Variablen, Lesezugriffe auf das Pokemon, Mathe)
PURE = {
    "Dpr_Battle_Logic_Common__GetEventVar", "Dpr_Battle_Logic_Common__RewriteEventVar", "Dpr_Battle_Logic_Common__MulEventVar",
    "Dpr_Battle_Logic_Common__GetPokeParam", "Dpr_Battle_Logic_Common__GetSubID", "Dpr_Battle_Logic_Common__GetWorkValue",
    "Dpr_Battle_Logic_Common__SetWorkValue", "Dpr_Battle_Logic_Common__GetEventVar_DAMAGE_TYPE",
    "Dpr_Battle_Logic_Common__RewriteEventVar_FAIL_CAUSE", "Dpr_Battle_Logic_Common__MulWazaBasePower",
    "Dpr_Battle_Logic_EventFactor__GetSubID", "Dpr_Battle_Logic_EventSystem__EVENTVAR_GetValue",
    "Dpr_Battle_Logic_BTL_POKEPARAM__GetValue", "Dpr_Battle_Logic_BTL_POKEPARAM__CheckSick", "Dpr_Battle_Logic_BTL_POKEPARAM__IsMatchType",
    "Dpr_Battle_Logic_BTL_POKEPARAM__GetItem", "Dpr_Battle_Logic_BTL_POKEPARAM__GetMonsNo", "Dpr_Battle_Logic_BTL_POKEPARAM__IsDead",
    "Dpr_Battle_Logic_BTL_POKEPARAM__IsHPFull", "Dpr_Battle_Logic_BTL_POKEPARAM__TURNFLAG_Get", "Dpr_Battle_Logic_BTL_POKEPARAM__HENSIN_Check",
    "Dpr_Battle_Logic_BTL_POKEPARAM__GetID", "Dpr_Battle_Logic_BTL_POKEPARAM__CONTFLAG_Get", "Dpr_Battle_Logic_BTL_POKEPARAM__IsGMode",
    "Dpr_Battle_Logic_calc__ITEM_GetParam", "Dpr_Battle_Logic_calc__QuotMaxHP", "Dpr_Battle_Logic_calc__IsShineWeather",
    "Dpr_Battle_Logic_calc__IsRainWeather", "Dpr_Battle_Logic_Common__GetLocalWeather", "Dpr_Battle_Logic_Common__GetWeather",
    "Dpr_Battle_Logic_Common__PokeIDtoSide", "Dpr_Battle_Logic_Common__IsFriendPokeID", "Dpr_Battle_Logic_Common__CheckFieldEffect",
    "Dpr_Battle_Logic_WAZADATA__GetFlag", "Dpr_Battle_Logic_WAZADATA__GetCategory", "Dpr_Battle_Logic_Handler_Item__item_AttackValue_to_Ratio",
    "Dpr_Battle_Logic_BTL_POKEPARAM__IsRaidBoss", "Dpr_Battle_Logic_BTL_POKEPARAM__COUNTER_Get",
}


def split_funcs(path):
    out = {}
    for part in re.split(r"\n(?=// 0x[0-9a-f]+ )", path.read_text()):
        h = re.match(r"// 0x([0-9a-f]+) (\S+)", part)
        if h:
            out[int(h.group(1), 16)] = (h.group(2), part)
    return out


def analyze(cls):
    funcs = split_funcs(DECOMP / f"Dpr_Battle_Logic_Handler_{cls}.c")
    by_name = {n.replace("$$", "__").replace(".", "_"): a for a, (n, _t) in funcs.items()}
    own = {}
    for a, (n, t) in funcs.items():
        own[a] = {c for c in CALL.findall(t)} - NOISE
    info = {}

    def closure(a, seen=None):
        seen = seen if seen is not None else set()
        if a in seen:
            return set()
        seen.add(a)
        res = set()
        for c in own.get(a, ()):
            b = by_name.get(c)
            if b is not None:
                res |= closure(b, seen)      # Hilfsfunktion der Klasse: Aufrufe zaehlen mit
            else:
                res.add(c)
        return res

    for a, (n, t) in funcs.items():
        info[a] = {"lines": len(t.splitlines()), "impure": sorted(c for c in closure(a) if c not in PURE)}
    return info


def usage():
    use = {"Tokusei": collections.Counter(), "TokuseiTrainer": collections.Counter(), "ItemTrainer": collections.Counter(),
           "ItemWild": collections.Counter(), "WazaLearn": collections.Counter(), "WazaTrainer": collections.Counter()}
    pt = json.loads((MASTER / "pml_personal/PersonalTable.json").read_text())["instances"][0]["data"]["Personal"]
    for p in pt:
        if p.get("valid_flag"):
            for t in {p["tokusei1"], p["tokusei2"], p["tokusei3"]}:
                use["Tokusei"][t] += 1
            for i in (p["item1"], p["item2"], p["item3"]):
                if i:
                    use["ItemWild"][i] += 1
    wo = json.loads((MASTER / "pml_personal/WazaOboeTable.json").read_text())["instances"][0]["data"]["WazaOboe"]
    for row in wo:
        ar = row["ar"]
        for w in {ar[i + 1] for i in range(0, len(ar), 2)}:
            use["WazaLearn"][w] += 1
    tp = json.loads((MASTER / "dpr_masterdatas/TrainerTable.json").read_text())["instances"][0]["data"]["TrainerPoke"]
    for row in tp:
        for n in range(1, 7):
            if row.get(f"P{n}MonsNo"):
                use["TokuseiTrainer"][row[f"P{n}Tokusei"]] += 1
                if row[f"P{n}Item"]:
                    use["ItemTrainer"][row[f"P{n}Item"]] += 1
                for k in range(1, 5):
                    if row[f"P{n}Waza{k}"]:
                        use["WazaTrainer"][row[f"P{n}Waza{k}"]] += 1
    return use


def main():
    hmap = json.loads((ROOT / "work/battleevents/handler_map.json").read_text())
    use = usage()
    result = {}
    for cls in ("Tokusei", "Item", "Waza"):
        info = analyze(cls)
        rows = []
        for num, ent in hmap[cls].items():
            num = int(num)
            funcs = {e[2] for e in ent["entries"]}
            impure = sorted({c for f in funcs for c in info.get(f, {"impure": []})["impure"]})
            lines = sum(info.get(f, {"lines": 0})["lines"] for f in funcs)
            if cls == "Tokusei":
                u = [use["Tokusei"][num], use["TokuseiTrainer"][num]]
            elif cls == "Item":
                u = [use["ItemWild"][num], use["ItemTrainer"][num]]
            else:
                u = [use["WazaLearn"][num], use["WazaTrainer"][num]]
            rows.append({"no": num, "table": ent["table"], "events": sorted({e[0] for e in ent["entries"]}),
                         "funcs": sorted(funcs), "lines": lines, "pure": not impure, "impure": impure, "use": u})
        result[cls] = rows
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    for cls, rows in result.items():
        pure = [r for r in rows if r["pure"]]
        print(cls, len(rows), "Nummern,", len(pure), "rein (Orakel ohne Wirkungsebene)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
