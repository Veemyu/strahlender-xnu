#!/usr/bin/env python3
"""Zeigt Handler-Pseudocode aus work/decomp/battle_all ohne IL2CPP-Rauschen (nur Ausgabe auf stdout, nur lesen).

Aufruf: python3 scripts/battle_pseudo_view.py Tokusei 0x1a3f7b0 [weitere Adressen]
Entfernt Klasseninit-Bloecke, Variablendeklarationen und ersetzt EventVar-Nummern durch Namen.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECOMP = ROOT / "work/decomp/battle_all"


def labels():
    src = (ROOT / "unity/Assets/Scripts/BattleEvents/EventIds.cs").read_text()
    body = src.split("enum EventVarLabel")[1].split("}")[0]
    return {int(v): n for n, v in re.findall(r"([A-Z0-9_]+) = (\d+)", body)}


def events():
    src = (ROOT / "unity/Assets/Scripts/BattleEvents/EventIds.cs").read_text()
    body = src.split("enum EventId")[1].split("}")[0]
    return {int(v): n for n, v in re.findall(r"([A-Z0-9_]+) = (\d+)", body)}


INIT1 = re.compile(r"if \(\(DAT_[0-9a-f]+ & 1\) == 0\) \{.*?\n\s*DAT_[0-9a-f]+ = 1;\s*\}\n", re.S)
INIT2 = re.compile(r"if \(\(\(\*\((?:byte|ushort) \*\)[^;{}]*?\{\s*FUN_003afbe0\(\);\s*(?:[A-Za-z0-9_]+ = [^;]*;\s*)?\}\n", re.S)
DECL = re.compile(r"^\s+(?:undefined\d?|u?long|u?int|byte|char|short|ushort|bool|float|code|undefined \*|void \*)[ \*]+[A-Za-z_0-9]+(?:\[\d+\])?;\n", re.M)
VAR = re.compile(r"Dpr_Battle_Logic_Common__(GetEventVar|MulEventVar|RewriteEventVar)\(param_1,(0x[0-9a-f]+|\d+)")


def simplify(text, lab):
    text = INIT1.sub("", text)
    text = INIT2.sub("", text)
    text = DECL.sub("", text)
    text = VAR.sub(lambda m: f"{m.group(1)}({lab.get(int(m.group(2), 0), m.group(2))}", text)
    text = text.replace("Dpr_Battle_Logic_", "")
    text = re.sub(r"^\s+(?:lVar\d+ = \*\(long \*\)puVar1;|puVar1 = PTR_DAT_[0-9a-f]+;)\n", "", text, flags=re.M)
    text = re.sub(r"\(undefined8 param_1,uint param_2\)", "(args, pokeId)", text)
    return re.sub(r"\n\s*\n", "\n", text)


def main():
    cls, addrs = sys.argv[1], {int(a, 16) for a in sys.argv[2:]}
    lab = labels()
    path = DECOMP / f"Dpr_Battle_Logic_Handler_{cls}.c"
    for part in re.split(r"\n(?=// 0x[0-9a-f]+ )", path.read_text()):
        h = re.match(r"// 0x([0-9a-f]+) ", part)
        if h and int(h.group(1), 16) in addrs:
            print(simplify(part, lab))


if __name__ == "__main__":
    main()
