#!/usr/bin/env python3
"""Inventar des Spielcodes aus dem IL2CPP-Dump (nur Standardbibliothek, streamend).

Liest work/il2cpp/dump.cs (Typen, Basisklassen, Namespaces) und
work/il2cpp/script.json (Methodenzahl je Klasse) und gibt Markdown-Tabellen aus.
Optional Quervergleich mit tools/opendpr/Assets/Scripts (nur Zaehlung nach Name).
Aufruf: scripts/dump_stats.py [--top-ns 60] [--no-opendpr] > ausgabe.md
"""
import argparse
import bisect
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "work/il2cpp/dump.cs"
SCRIPT = ROOT / "work/il2cpp/script.json"
OPENDPR = ROOT / "tools/opendpr/Assets/Scripts"

RE_IMAGE = re.compile(r"^// Image (\d+): (\S+) - (\d+)")
RE_TYPE = re.compile(r"(class|struct|enum|interface) (.+?)(?: : (.+?))? // TypeDefIndex: (\d+)$")
RE_NAME = re.compile(r'^      "Name": "(.*)",$')
RE_INST = re.compile(r"\bstatic\b.*\b_?[Ii]nstance;")
SAVE_RX = re.compile(r"Save|PlayerWork|PlayerPrefs", re.I)
MGR_RX = re.compile(r"(Manager|System|Controller|Provider)$")
ECS_BASES = {"IComponentData", "ISystem", "SystemBase", "ComponentSystem", "JobComponentSystem",
             "IJob", "IJobParallelFor", "IJobEntity", "IBufferElementData", "ISharedComponentData"}
ECS_NS = ("Unity.Entities", "Unity.Jobs", "Unity.Burst", "Unity.Collections", "Unity.Mathematics",
          "Unity.Transforms", "Unity.Rendering")
KINDS = ("class", "struct", "enum", "interface")


def strip_generics(s):
    """Entfernt <...> nach einem Bezeichner; Compilertypen wie <>c bleiben."""
    out, depth, prev = [], 0, ""
    for ch in s:
        if ch == "<" and (depth > 0 or prev.isalnum() or prev == "_"):
            depth += 1
        elif ch == ">" and depth > 0:
            depth -= 1
        elif depth == 0:
            out.append(ch)
            prev = ch
    return "".join(out)


def split_top(s):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def short(name):
    return strip_generics(name).split(".")[-1]


def is_generated(name):
    return "DisplayClass" in name or bool(re.search(r"(^|\.)<", name))


def image_group(img):
    n = img[:-4] if img.endswith(".dll") else img
    if n == "Assembly-CSharp":
        return "Assembly-CSharp (Spielcode)"
    if n == "AssetAssistant":
        return "AssetAssistant (SmartPoint-Framework)"
    if n.startswith("DOTween"):
        return "DOTween"
    if n == "Unity.TextMeshPro":
        return "TextMeshPro"
    if n == "Unity.Timeline":
        return "Unity Timeline"
    if n == "UnityEngine.UI":
        return "Unity UI (uGUI)"
    if n.startswith("UnityEngine"):
        return "UnityEngine (Module)"
    if n == "nn":
        return "nn (Nintendo-Switch-SDK)"
    if n == "DebugLog":
        return "DebugLog"
    return ".NET-BCL / Mono"


# (Praefix, Modul, Kategorie); laengster Treffer gewinnt, Namespace-Regeln
MODULE_RULES = [
    ("Dpr.Battle.Logic", "Dpr.Battle.Logic", "Spiellogik"),
    ("Dpr.Battle.View", "Dpr.Battle.View", "Spiellogik"),
    ("Dpr.BattleMatching", "Dpr.BattleMatching", "Netzwerk"),
    ("Dpr.Battle", "Dpr.Battle (Rest)", "Spiellogik"),
    ("Dpr.Field", "Dpr.Field.*", "Spiellogik"),
    ("Dpr.UI", "Dpr.UI.*", "Spiellogik (UI)"),
    ("Dpr.SecretBase", "Dpr.SecretBase", "Spiellogik"),
    ("Dpr.SequenceEditor", "Dpr.SequenceEditor (Sequenz-/Cutscene-Befehle)", "Spiellogik (Sequenzen)"),
    ("Dpr.Contest", "Dpr.Contest", "Spiellogik"),
    ("Dpr.UnderGround", "Dpr.UnderGround", "Spiellogik"),
    ("Dpr.NetworkUtils", "Dpr.NetworkUtils / GMS / NetworkDbg (Online)", "Netzwerk"),
    ("Dpr.GMS", "Dpr.NetworkUtils / GMS / NetworkDbg (Online)", "Netzwerk"),
    ("Dpr.NetworkDbg", "Dpr.NetworkUtils / GMS / NetworkDbg (Online)", "Netzwerk"),
    ("Dpr.Security", "Dpr.NetworkUtils / GMS / NetworkDbg (Online)", "Netzwerk"),
    ("Dpr.NX", "Dpr.NetworkUtils / GMS / NetworkDbg (Online)", "Netzwerk"),
    ("Dpr.Message", "Dpr.Message / MsgWindow / MessageViewer", "Spiellogik (Text/UI)"),
    ("Dpr.MsgWindow", "Dpr.Message / MsgWindow / MessageViewer", "Spiellogik (Text/UI)"),
    ("Dpr.MessageViewer", "Dpr.Message / MsgWindow / MessageViewer", "Spiellogik (Text/UI)"),
    ("Dpr", "Dpr.* (sonstige Spielmodule)", "Spiellogik"),
    ("Pml.PokePara", "Pml.PokePara", "Spiellogik"),
    ("Pml", "Pml.* (Pokemon-Bibliothek, Rest)", "Spiellogik"),
    ("DPData", "DPData (Datenmodell/Tabellen)", "Daten"),
    ("XLSXContent", "XLSXContent (Excel-Tabellen)", "Daten"),
    ("poketool", "poketool", "Spiellogik"),
    ("Effect", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("Audio", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("Ug", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("FieldCommon", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("FieldDoor", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("FieldWall", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("GameData", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("AttributeData", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("ScriptableObjectFormat", "Effect / Audio / Ug / Field* (kleine Spielnamespaces)", "Spiellogik"),
    ("Xoroshiro128Plus", "Xoroshiro128Plus (Zufall)", "Spiellogik"),
    ("SmartPoint", "SmartPoint.* (Studio-Framework)", "Framework"),
    ("AK", "Wwise (AK.* / Ak*)", "Middleware"),
    ("NexPlugin", "NEX / INL1 / NexAssets (Nintendo-Netzwerk)", "Middleware"),
    ("NexAssets", "NEX / INL1 / NexAssets (Nintendo-Netzwerk)", "Middleware"),
    ("INL1", "NEX / INL1 / NexAssets (Nintendo-Netzwerk)", "Middleware"),
    ("Nintendo", "Nintendo.MessageStudio / nn", "Middleware"),
    ("nn", "Nintendo.MessageStudio / nn", "Middleware"),
    ("DG.Tweening", "DOTween (DG.Tweening)", "Middleware"),
    ("DG", "DOTween (DG.Tweening)", "Middleware"),
    ("TMPro", "TextMeshPro", "Middleware"),
    ("UnityEngine.UI", "Unity UI (uGUI)", "Engine"),
    ("UnityEngine", "UnityEngine.*", "Engine"),
    ("Unity", "Unity.* (Timeline, Mathematik, ...)", "Engine"),
    ("System", ".NET-BCL (System.*)", "Engine-BCL"),
    ("Mono", ".NET-BCL (Mono.*)", "Engine-BCL"),
    ("Microsoft", ".NET-BCL (Mono.*)", "Engine-BCL"),
]
RULES = sorted(MODULE_RULES, key=lambda r: -len(r[0]))

# Namespace-lose Typen im Spielassembly: Namenspraefix -> (Modul, Kategorie)
NONS_RULES = [
    (re.compile(r"^(AK|Ak|Wwise)"), ("Wwise (AK.* / Ak*)", "Middleware")),
    (re.compile(r"^(Pia|Ilca|Matchmake)"),
     ("Pia / Ilca (Nintendo-Netzwerk-Plugins, nach Namen vermutet)", "Middleware")),
    (re.compile(r"^(MeshNormalSmoother|StabilizationScrollRect|StaticQueue)"),
     ("Hilfsklassen (Engine-nah)", "Framework")),
    (re.compile(r"^(Debug)"), ("Debug-Klassen ohne Namespace", "Debug")),
]


def classify(ns, name, grp):
    if grp not in ("Assembly-CSharp (Spielcode)", "AssetAssistant (SmartPoint-Framework)"):
        if grp == "DOTween":
            return "DOTween (DG.Tweening)", "Middleware"
        if grp == "TextMeshPro":
            return "TextMeshPro", "Middleware"
        if grp == "nn (Nintendo-Switch-SDK)":
            return "Nintendo.MessageStudio / nn", "Middleware"
        if grp == "DebugLog":
            return "DebugLog", "Debug"
        if grp == "Unity Timeline":
            return "Unity Timeline", "Engine"
        if grp == "Unity UI (uGUI)":
            return "Unity UI (uGUI)", "Engine"
        if grp == "UnityEngine (Module)":
            return "UnityEngine.*", "Engine"
        return ".NET-BCL / Mono", "Engine-BCL"
    if ns:
        for pre, mod, cat in RULES:
            if ns == pre or ns.startswith(pre + "."):
                return mod, cat
        return "Sonstige Namespaces", "Spiellogik"
    top = name.split(".")[0]
    for rx, res in NONS_RULES:
        if rx.match(top):
            return res
    return "Spiel-Typen ohne Namespace (global)", "Spiellogik"


def resolve_nested_ns(types):
    """Verschachtelte Typen stehen im Dump ohne Namespace; vom aeusseren Typ uebernehmen."""
    outer = {}
    for t in types:
        if "." not in strip_generics(t["name"]) and t["ns"]:
            outer[(t["img"], strip_generics(t["name"]))] = t["ns"]
    for t in types:
        n = strip_generics(t["name"])
        if "." in n and not t["ns"]:
            ns = outer.get((t["img"], n.split(".")[0]))
            if ns:
                t["ns"] = ns
                t["key"] = ns + "." + n


def parse_dump():
    images, starts = [], []
    types = []
    ns = ""
    cur = None
    with open(DUMP, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("// Image "):
                m = RE_IMAGE.match(line)
                if m:
                    images.append(m.group(2))
                    starts.append(int(m.group(3)))
                continue
            if line.startswith("// Namespace: "):
                ns = line[14:].strip()
                continue
            if line[0] == "\t":
                if cur is not None and not cur["inst"] and "static" in line and "nstance" in line \
                        and RE_INST.search(line):
                    cur["inst"] = True
                continue
            if "// TypeDefIndex:" in line:
                m = RE_TYPE.search(line.rstrip("\n"))
                if not m:
                    continue
                kind, name, bases, idx = m.group(1), m.group(2), m.group(3), int(m.group(4))
                img = images[bisect.bisect_right(starts, idx) - 1]
                bl = split_top(bases) if bases else []
                cur = {"kind": kind, "ns": ns, "name": name, "img": img, "bases": bl, "inst": False,
                       "key": (ns + "." if ns else "") + strip_generics(name)}
                types.append(cur)
    resolve_nested_ns(types)
    return types


def count_methods():
    cnt = Counter()
    inside = False
    with open(SCRIPT, encoding="utf-8") as f:
        for line in f:
            if not inside:
                if line.startswith('  "ScriptMethod"'):
                    inside = True
                continue
            if line.startswith('  "'):
                break
            m = RE_NAME.match(line)
            if not m:
                continue
            raw = m.group(1)
            if "\\" in raw:
                raw = json.loads('"' + raw + '"')
            cls = raw.split("$$", 1)[0]
            cnt[strip_generics(cls)] += 1
    return cnt


def table(headers, rows, align=None):
    out = ["| " + " | ".join(headers) + " |"]
    al = align or ["l"] + ["r"] * (len(headers) - 1)
    out.append("|" + "|".join("---:" if a == "r" else "---" for a in al) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fmt(n):
    return f"{n:,}".replace(",", ".")


def base_chain_flags(types):
    """Abgeleitet-von-Pruefung ueber Kurznamen (grob, Namenskollisionen moeglich)."""
    parent = defaultdict(set)
    for t in types:
        if t["kind"] == "class" and t["bases"]:
            b = t["bases"][0]
            if not re.match(r"^I[A-Z]", short(b)):
                parent[short(t["name"])].add(short(b))
    memo = {}

    def derives(n, target, seen=()):
        if n == target:
            return True
        k = (n, target)
        if k in memo:
            return memo[k]
        res = False
        if n not in seen:
            res = any(derives(p, target, seen + (n,)) for p in parent.get(n, ()))
        memo[k] = res
        return res

    return derives


def opendpr_scan():
    if not OPENDPR.is_dir():
        return None
    rx_t = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|internal|private|protected|static|sealed|abstract|"
                      r"partial|unsafe|readonly|new)\s+)*(class|struct|enum|interface)\s+(\w+)", re.M)
    rx_ns = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
    per_folder = Counter()
    lines = Counter()
    names = defaultdict(set)
    nsnames = set()
    nfiles = 0
    for p in OPENDPR.rglob("*.cs"):
        rel = p.relative_to(OPENDPR).parts
        fk = rel[0] if len(rel) > 1 else "(Wurzel)"
        per_folder[fk] += 1
        nfiles += 1
        txt = p.read_text(encoding="utf-8", errors="replace")
        lines[fk] += txt.count("\n") + 1
        m = rx_ns.search(txt)
        ns = m.group(1) if m else ""
        for kind, nm in rx_t.findall(txt):
            names[nm].add(kind)
            nsnames.add((ns, nm))
    return nfiles, per_folder, lines, names, nsnames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-ns", type=int, default=60)
    ap.add_argument("--no-opendpr", action="store_true")
    args = ap.parse_args()

    types = parse_dump()
    mcount = count_methods()
    derives = base_chain_flags(types)

    keyset = set()
    for t in types:
        t["grp"] = image_group(t["img"])
        t["gen"] = is_generated(t["name"])
        t["mod"], t["cat"] = classify(t["ns"], t["name"], t["grp"])
        t["methods"] = 0
        keyset.add(t["key"])
    # Methoden je Schluessel; bei doppelten Schluesseln (Generics-Arity) auf den ersten Typ buchen
    first = {}
    for t in types:
        first.setdefault(t["key"], t)
    matched = 0
    for k, n in mcount.items():
        if k in first:
            first[k]["methods"] += n
            matched += n
    total_m = sum(mcount.values())

    print(f"## Rohzahlen\n\n- Typen im Dump: {fmt(len(types))}\n- ScriptMethod-Eintraege: {fmt(total_m)} "
          f"(davon einem Dump-Typ zugeordnet: {fmt(matched)}, {matched * 100 / total_m:.1f} %)\n")

    # 1) Assembly-Gruppen
    def agg(keyf, items):
        d = defaultdict(lambda: [Counter(), 0, 0])
        for t in items:
            e = d[keyf(t)]
            e[0][t["kind"]] += 1
            e[1] += t["methods"]
            e[2] += t["gen"]
        return d

    def rows_of(d, order=None):
        rows = []
        for k, (c, m, g) in d.items():
            tot = sum(c.values())
            rows.append((k, c["class"], c["struct"], c["enum"], c["interface"], tot, g, m))
        rows.sort(key=lambda r: -r[5])
        tc = [sum(r[i] for r in rows) for i in range(1, 8)]
        rows = [[r[0]] + [fmt(x) for x in r[1:]] for r in rows]
        rows.append(["**Summe**"] + [f"**{fmt(x)}**" for x in tc])
        return rows

    H = ["Name", "Klassen", "Strukturen", "Enums", "Interfaces", "Typen gesamt", "davon Compiler-Hilfstypen",
         "Methoden"]
    print("## Assembly-Gruppen\n")
    print(table(H, rows_of(agg(lambda t: t["grp"], types))))
    print("\n## Einzelne Assemblies (Images)\n")
    print(table(H, rows_of(agg(lambda t: t["img"], types))))

    # 2) Namespaces
    d = agg(lambda t: (t["ns"] or "(global)"), types)
    allrows = sorted(((k, c, m, g) for k, (c, m, g) in d.items()), key=lambda r: -sum(r[1].values()))
    print(f"\n## Namespaces (gesamt: {len(allrows)}; Top {args.top_ns} nach Typenzahl)\n")
    rows = []
    for k, c, m, g in allrows[:args.top_ns]:
        rows.append([k, c["class"], c["struct"], c["enum"], c["interface"], sum(c.values()), m])
    rest = allrows[args.top_ns:]
    if rest:
        rows.append(["(" + str(len(rest)) + " weitere Namespaces)", sum(r[1]["class"] for r in rest),
                     sum(r[1]["struct"] for r in rest), sum(r[1]["enum"] for r in rest),
                     sum(r[1]["interface"] for r in rest), sum(sum(r[1].values()) for r in rest),
                     sum(r[2] for r in rest)])
    print(table(["Namespace", "Klassen", "Strukturen", "Enums", "Interfaces", "Typen", "Methoden"],
                [[r[0]] + [fmt(x) for x in r[1:]] for r in rows]))

    # 3) Top 30 Klassen
    def top30(items, title):
        cl = sorted((t for t in items if t["methods"] > 0), key=lambda t: -t["methods"])[:30]
        print(f"\n## {title}\n")
        print(table(["#", "Klasse", "Gruppe/Modul", "Methoden"],
                    [[i + 1, t["key"], t["grp"].split(" (")[0] if t["grp"] != "Assembly-CSharp (Spielcode)" else t["mod"],
                      fmt(t["methods"])] for i, t in enumerate(cl)], ["r", "l", "l", "r"]))

    top30(types, "Groesste 30 Klassen nach Methodenzahl (alle Assemblies)")
    top30([t for t in types if t["grp"].startswith("Assembly-CSharp")],
          "Groesste 30 Klassen nach Methodenzahl (nur Assembly-CSharp)")

    # 4) Modulkarte
    mods = defaultdict(lambda: [Counter(), 0, 0, ""])
    for t in types:
        e = mods[t["mod"]]
        e[0][t["kind"]] += 1
        e[1] += t["methods"]
        e[2] += 1
        e[3] = t["cat"]
    cats = defaultdict(lambda: [0, 0, 0])
    print("\n## Modulkarte\n")
    rows = []
    for k, (c, m, n, cat) in sorted(mods.items(), key=lambda kv: -kv[1][1]):
        rows.append([k, cat, n, c["class"], m])
        hk = cat.split(" (")[0]
        cats[hk][0] += n
        cats[hk][1] += c["class"]
        cats[hk][2] += m
    print(table(["Modul", "Kategorie", "Typen", "davon Klassen", "Methoden"],
                [[r[0], r[1]] + [fmt(x) for x in r[2:]] for r in rows], ["l", "l", "r", "r", "r"]))
    tt = sum(v[0] for v in cats.values())
    tm = sum(v[2] for v in cats.values())
    print("\n## Hauptkategorien (Summe der Modulkarte, Untertypen wie UI/Sequenzen eingerechnet)\n")
    print(table(["Kategorie", "Typen", "Anteil Typen", "Methoden", "Anteil Methoden"],
                [[k, fmt(v[0]), f"{v[0] * 100 / tt:.1f} %", fmt(v[2]), f"{v[2] * 100 / tm:.1f} %"]
                 for k, v in sorted(cats.items(), key=lambda kv: -kv[1][2])]))

    # 5) Manager/Systeme
    ac = [t for t in types if t["grp"].startswith("Assembly-CSharp") and not t["gen"]]
    mg = [t for t in ac if t["kind"] == "class" and MGR_RX.search(short(t["name"]))]
    print("\n## Manager-/System-/Controller-/Provider-Klassen (Assembly-CSharp, ohne Compilertypen)\n")
    suff = Counter(MGR_RX.search(short(t["name"])).group(1) for t in mg)
    nested = sum(1 for t in mg if "." in t["name"])
    print(f"Gesamt {len(mg)} (davon verschachtelt: {nested}); " +
          ", ".join(f"{k}: {v}" for k, v in suff.most_common()) + "\n")

    def singleton(t):
        bs = " ".join(t["bases"])
        return "Singleton" in bs or "Provider<" in bs or t["inst"]

    sg = [t for t in mg if singleton(t)]
    print(f"Davon mit Singleton-Merkmal (Basisklasse Singleton/Provider<T> oder statisches Instance-Feld): "
          f"{len(sg)}\n")
    print(table(["Modul", "Manager-Typen", "mit Singleton-Merkmal"],
                [[k, v[0], v[1]] for k, v in sorted(
                    ((m, [sum(1 for t in mg if t["mod"] == m), sum(1 for t in sg if t["mod"] == m)])
                     for m in {t["mod"] for t in mg}), key=lambda kv: -kv[1][0])], ["l", "r", "r"]))
    print("\nNamen (nicht verschachtelt):\n")
    for s in ("Manager", "System", "Controller", "Provider"):
        nm = sorted(t["key"] for t in mg if "." not in t["name"] and short(t["name"]).endswith(s))
        print(f"- **{s}** ({len(nm)}): " + ", ".join(nm))
    # Basisklassen der Spiel-"System"-Typen
    bs = Counter(short(t["bases"][0]) if t["bases"] else "(Object)"
                 for t in mg if short(t["name"]).endswith("System"))
    print("\nBasisklassen der *System-Typen: " + ", ".join(f"{k} ({v})" for k, v in bs.most_common(10)))

    # 6) MonoBehaviour
    print("\n## MonoBehaviour- und ScriptableObject-Ableitungen\n")
    rows = []
    for tgt in ("MonoBehaviour", "ScriptableObject"):
        sel = [t for t in types if t["kind"] == "class" and short(t["name"]) != tgt
               and t["bases"] and derives(short(t["name"]), tgt)]
        by = Counter(t["grp"] for t in sel)
        rows.append([tgt, fmt(len(sel)), ", ".join(f"{k.split(' (')[0]}: {v}" for k, v in by.most_common(6))])
    print(table(["Basis", "Typen (direkt/indirekt)", "Verteilung nach Gruppe"], rows, ["l", "r", "l"]))
    mbc = Counter(t["mod"] for t in ac if t["kind"] == "class" and t["bases"]
                  and derives(short(t["name"]), "MonoBehaviour"))
    print("\nMonoBehaviour im Spielassembly nach Modul: " + ", ".join(f"{k}: {v}" for k, v in mbc.most_common(12)))

    # 7) Save-Bezug
    sv = [t for t in ac if t["kind"] != "enum" and "." not in t["name"] and SAVE_RX.search(t["name"])]
    print(f"\n## Klassen mit Save-Bezug (Name enthaelt Save/PlayerWork/PlayerPrefs; Assembly-CSharp, Typen ohne Enums)\n")
    print(f"{len(sv)} Typen, zusammen {fmt(sum(t['methods'] for t in sv))} Methoden.\n")
    print(", ".join(f"{t['key']} ({t['methods']})" for t in sorted(sv, key=lambda t: -t["methods"])))
    nsv = [t for t in types if t["grp"].startswith("Assembly-CSharp") and t["kind"] != "enum"
           and "." in t["name"] and "PlayerWork" in t["name"].split(".")[0]]
    print(f"\nVerschachtelte Typen in PlayerWork: {len(nsv)}")

    # 8) Wwise
    ww = [t for t in types if re.match(r"^(AK|Ak|Wwise)", t["ns"] or t["name"]) or t["ns"].startswith("AK")]
    ww_game = [t for t in ww if t["grp"].startswith("Assembly-CSharp")]
    byk = Counter(t["kind"] for t in ww_game)
    print("\n## Wwise/Ak-Bezug\n")
    print(f"Typen: {len(ww_game)} ({', '.join(f'{k}: {v}' for k, v in byk.items())}), "
          f"Methoden: {fmt(sum(t['methods'] for t in ww_game))}.\n")
    wt = Counter((t["ns"] or "(global)") for t in ww_game)
    print("Verteilung: " + ", ".join(f"{k}: {v}" for k, v in wt.most_common(6)))
    wcl = sorted((t for t in ww_game if t["methods"]), key=lambda t: -t["methods"])[:10]
    print("\nGroesste Wwise-Klassen: " + ", ".join(f"{t['key']} ({t['methods']})" for t in wcl))
    aud = [t for t in ac if t["kind"] == "class" and not t["gen"] and re.search(r"Audio|Sound|Sound", short(t["name"]))
           and t not in ww_game]
    print(f"\nSpielklassen mit Audio-/Sound-Namen (Anbindung an Wwise, nicht Middleware selbst): {len(aud)}, "
          f"{fmt(sum(t['methods'] for t in aud))} Methoden.")

    # 9) ECS / DOTS
    print("\n## ECS / DOTS\n")
    e1 = [t for t in types if t["ns"].startswith(ECS_NS)]
    e2 = [t for t in types if any(short(b) in ECS_BASES for b in t["bases"])]
    imgs = [i for i in dict.fromkeys(t["img"] for t in types) if "Entities" in i or "Burst" in i or "Jobs" in i]
    print(f"- Assemblies mit Entities/Burst/Jobs im Namen: {len(imgs)} {imgs}")
    print(f"- Typen in Unity.Entities/Jobs/Burst/Collections/Mathematics/...-Namespaces: {len(e1)} "
          + str(dict(Counter((t['ns'], t['grp'].split(' (')[0]) for t in e1))))
    print(f"- Typen mit ECS-typischen Basisschnittstellen (IComponentData, ISystem, SystemBase, IJob...): {len(e2)}"
          + ("; " + ", ".join(t['key'] for t in e2[:10]) if e2 else ""))

    # 10) opendpr
    if args.no_opendpr:
        return
    sc = opendpr_scan()
    if not sc:
        print("\n(opendpr nicht gefunden)", file=sys.stderr)
        return
    nfiles, per_folder, lines, names, nsnames = sc
    print("\n## opendpr: Dateien pro Ordner (Assets/Scripts, .cs)\n")
    print(f"Insgesamt {fmt(nfiles)} .cs-Dateien, {fmt(sum(lines.values()))} Zeilen, "
          f"{fmt(len(names))} deklarierte Typnamen.\n")
    print(table(["Ordner", ".cs-Dateien", "Zeilen"], [[k, fmt(v), fmt(lines[k])] for k, v in per_folder.most_common()]))

    game = [t for t in types if t["grp"] in ("Assembly-CSharp (Spielcode)", "AssetAssistant (SmartPoint-Framework)")
            and not t["gen"]]
    top = [t for t in game if "." not in strip_generics(t["name"])]

    def cov(items, label):
        hit = [t for t in items if short(t["name"]) in names]
        meth = sum(t["methods"] for t in items)
        mh = sum(t["methods"] for t in hit)
        return [label, fmt(len(items)), fmt(len(hit)), f"{len(hit) * 100 / max(1, len(items)):.1f} %",
                fmt(meth), fmt(mh), f"{mh * 100 / max(1, meth):.1f} %"]

    print("\n## Abdeckung per Klassenname (Dump -> opendpr)\n")
    print("Nur Namensvergleich (Kurzname ohne Generics). Methoden = ScriptMethod-Eintraege der Dump-Typen mit Treffer.\n")
    rows = [cov(game, "Alle Spieltypen (ohne Compilertypen, inkl. verschachtelt)"),
            cov(top, "Nur Top-Level-Typen")]
    for k in KINDS:
        rows.append(cov([t for t in top if t["kind"] == k], f"Top-Level: {k}"))
    strict = [t for t in top if (t["ns"], short(t["name"])) in nsnames]
    rows.append(["Top-Level mit passendem Namespace + Name", fmt(len(top)), fmt(len(strict)),
                 f"{len(strict) * 100 / len(top):.1f} %", "", "", ""])
    print(table(["Menge", "Dump-Typen", "in opendpr", "Anteil", "Methoden", "Methoden in Treffern", "Anteil"], rows))

    print("\n### Abdeckung je Modul (Top-Level-Typen, nur Spielcode-Module)\n")
    bymod = defaultdict(list)
    for t in top:
        bymod[t["mod"]].append(t)
    rows = [cov(v, k) for k, v in sorted(bymod.items(), key=lambda kv: -len(kv[1]))]
    print(table(["Modul", "Dump-Typen", "in opendpr", "Anteil", "Methoden", "Methoden in Treffern", "Anteil"], rows))

    gnames = {short(t["name"]) for t in types}
    only = sorted(n for n in names if n not in gnames)
    print(f"\nTypnamen in opendpr ohne Entsprechung im Dump (Kurzname): {len(only)} von {len(names)}")


if __name__ == "__main__":
    main()
