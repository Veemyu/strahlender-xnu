#!/usr/bin/env python3
"""Stammdaten aus den UnityFS-Bundles des Dumps lesen (TypeTree-basiert, ohne Unity).

Die Bundles enthalten serialisierte ScriptableObjects (MonoBehaviour) mit vollstaendigem TypeTree.
UnityPy (MIT) liest sie; installiert wird es nur unter tools/pydeps:

    pip install --target tools/pydeps UnityPy

Unterbefehle:
    survey   Bundles untersuchen: Klassen, Instanzen, Feldschema; Abgleich mit work/il2cpp/dump.cs
             -> work/masterdata/_survey.json (+ Tabelle auf stdout)
    export   Alle MonoBehaviour-Instanzen der Daten-Bundles als JSON nach work/masterdata/<bundle>/<Klasse>.json
    counts   Instanz- und Zeilenzahlen aller exportierten Dateien -> work/masterdata/_counts.json
    scan     Bundles ausserhalb von Environments/Pokemon Database nach Tabellenklassen durchsuchen -> _scan.json

Mit --set extra (oder all) kommen die weiteren Bundles aus EXTRA_BUNDLES dazu (Zonen, Begegnungen, Event-Skripte,
Untergrund usw.); Instanzen tragen dort zusaetzlich "path_id", PPtr-Verweise innerhalb des Bundles sind um
"target_class"/"target_name" ergaenzt. Ohne --set bleibt alles wie in Teil 1.

Ausgaben liegen nur unter work/ (gitignored). Audio-Assets werden nie gelesen: es werden ausschliesslich
MonoScript- und MonoBehaviour-Objekte angefasst.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_ASSETS = os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant")
DEFAULT_OUT = os.path.join(ROOT, "work", "masterdata")
DEFAULT_DUMP = os.path.join(ROOT, "work", "il2cpp", "dump.cs")

# Bundle-Pfad relativ zu AssetAssistant -> Kurzname (Ausgabeordner)
DATA_BUNDLES = {
    "Dpr/masterdatas": "dpr_masterdatas",
    "Pml/personal_masterdatas": "pml_personal",
    "Battle/battle_masterdatas": "battle_masterdatas",
    "UIs/masterdatas/uimasterdatas": "ui_masterdatas",
    "Effects/masterdatas/effectdatabase": "effect_database",
    "Contest/md/contest_masterdatas": "contest_masterdatas",
    "GMS/md/gms_masterdatas": "gms_masterdatas",
    "FureaiHiroba/fureai/masterdata": "fureai_masterdata",
    "UnderGround/masterdata": "underground_masterdata",
    "Union/unionroom/masterdata": "union_masterdata",
}
# Texte: pro Sprache ein Bundle mit MsbtData-Objekten (nur mit --messages exportiert)
MESSAGE_BUNDLES = {"Message/english": "msg_english", "Message/german": "msg_german", "Message/common_msbt": "msg_common"}

# Weitere Daten-Bundles (Teil 2, Option --set extra|all): Bundle -> (Kurzname, Klassenfilter).
# Klassenfilter: None = alle Klassen im Namespace XLSXContent; sonst Menge erlaubter Klassennamen.
# Die Bundles enthalten teils auch Texturen/Prefabs; gelesen werden wie immer nur MonoScript/MonoBehaviour.
EXTRA_BUNDLES = {
    "Dpr/scriptableobjects/gamesettings": ("gamesettings", None),
    "Dpr/ev_script": ("ev_script", {"EvData"}),
    "UnderGround/data/ugdata": ("ug_data", None),
    "LightStone/uglightstonedata": ("lightstone", None),  # Schema weicht vom Dump ab (neuere Variante)
    "UnderGround/lightstone/prefabs/lightstonemanager": ("lightstone_ug", None),  # Schema wie im Dump
    "Dpr/spfishing": ("spfishing", None),
    "Dpr/statueeffectdata": ("statueeffect", None),
    "StatuePlacementEdit/sb/sbcontroller": ("secretbase", None),
    "DigFossil/dig/digfossilcontroller": ("digfossil", None),
    "FureaiHiroba/fieldwalking": ("fieldwalking", None),
    "Dpr/scenes/title": ("title", {"TitleSettings"}),
}

# Bundles/Ordner, die der Scan (Befehl scan) nicht oeffnet: riesige Modell-/Umgebungsdaten ohne Tabellen.
SCAN_SKIP_TOP = {"Environments", "Pokemon Database"}
SCAN_MAX_BYTES = 120 * 1024 * 1024

BOILERPLATE = ("m_GameObject", "m_Enabled", "m_Script", "m_Name")

# TypeTree-Typ -> C#-Typ
PRIMITIVES = {
    "SInt8": "sbyte", "UInt8": "byte", "char": "byte", "bool": "bool",
    "SInt16": "short", "short": "short", "UInt16": "ushort", "unsigned short": "ushort",
    "SInt32": "int", "int": "int", "UInt32": "uint", "unsigned int": "uint", "Type*": "int",
    "SInt64": "long", "long long": "long", "UInt64": "ulong", "unsigned long long": "ulong",
    "float": "float", "double": "double", "string": "string",
}


# --- Schema aus dem TypeTree ----------------------------------------------------------------

def describe_node(node):
    """Beschreibt einen TypeTree-Knoten als kompaktes Schema-Dict (name, type, ggf. fields/element)."""
    t = node.m_Type
    children = list(getattr(node, "m_Children", None) or [])
    # Arrays tragen den Elementtyp als Typnamen und haben ein einziges Kind "Array" (size + data);
    # Strings haben intern ebenfalls ein Array-Kind (chars) und bleiben Primitive.
    arr = children[0] if len(children) == 1 and children[0].m_Type == "Array" else None
    if t != "string" and (arr is not None or t == "Array"):
        arr = arr if arr is not None else node
        data = next((c for c in (arr.m_Children or []) if c.m_Name == "data"), None)
        return {"name": node.m_Name, "type": "array", "element": describe_node(data) if data else None}
    if t in PRIMITIVES:
        return {"name": node.m_Name, "type": PRIMITIVES[t]}
    if t.startswith("PPtr"):
        return {"name": node.m_Name, "type": "pptr"}
    return {"name": node.m_Name, "type": t, "fields": [describe_node(c) for c in children]}


def class_schema(root):
    """Felder einer MonoBehaviour-Klasse ohne Unity-Boilerplate."""
    return [describe_node(c) for c in (root.m_Children or []) if c.m_Name not in BOILERPLATE]


def schema_signature(fields):
    """Stabile Kurzform des Schemas zum Gruppieren gleicher Klassen."""
    def sig(f):
        if f["type"] == "array":
            return f["name"] + ":[" + (sig(f["element"]) if f["element"] else "?") + "]"
        if "fields" in f:
            return f["name"] + ":" + f["type"] + "{" + ",".join(sig(x) for x in f["fields"]) + "}"
        return f["name"] + ":" + f["type"]
    return ";".join(sig(f) for f in fields)


# --- dump.cs ---------------------------------------------------------------------------------

_CLASS_RE = re.compile(r"^(?:public |internal |private |protected )?(?:sealed |abstract |static )*"
                       r"(?:class|struct) ([\w.<>,`]+)(?: : ([^/,]*?)(?:,[^/]*?)?)? // TypeDefIndex: (\d+)")
_FIELD_RE = re.compile(r"^\t(?:public|private|protected|internal)\s+(?!static|const)(?:readonly\s+)?"
                       r"(.+?)\s+(\w+); // (0x[0-9A-Fa-f]+)\s*$")


def parse_dump(lines):
    """Liest Klassen mit Feldern und Offsets aus einem il2cpp-dump.cs.

    Rueckgabe: {"Namespace.Klasse": {"fields": [(name, typ, offset)], "name": ..., "namespace": ...}}.
    Verschachtelte Klassen heissen im Dump 'Aussen.Innen' und stehen im leeren Namespace.
    """
    out = {}
    ns = ""
    cur = None
    in_fields = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("// Namespace:"):
            ns = line[len("// Namespace:"):].strip()
            continue
        m = _CLASS_RE.match(line)
        if m:
            name = m.group(1)
            cur = {"name": name, "namespace": ns, "base": (m.group(2) or "").strip(), "fields": []}
            out[(ns + "." if ns else "") + name] = cur
            in_fields = False
            continue
        if cur is None:
            continue
        if line.strip() == "// Fields":
            in_fields = True
        elif line.strip() in ("// Methods", "// Properties", "// Events"):
            in_fields = False
        elif line == "}":
            cur = None
            in_fields = False
        elif in_fields:
            fm = _FIELD_RE.match(line)
            if fm:
                cur["fields"].append((fm.group(2), fm.group(1), int(fm.group(3), 16)))
    return out


def _by_name(dump, name):
    """Klasse nur ueber ihren Namen finden (Namespace egal); nur bei eindeutigem Treffer."""
    hits = [c for c in dump.values() if c["name"] == name]
    return hits[0] if len(hits) == 1 else None


def resolve_fields(dump, dc, depth=0):
    """Felder inkl. geerbter Basisklassen (Basisfelder zuerst, wie im Speicherlayout)."""
    base = dc.get("base")
    inherited = []
    if base and depth < 8:
        for cand in (dc["namespace"] + "." + base if dc["namespace"] else base, base):
            if cand in dump:
                inherited = resolve_fields(dump, dump[cand], depth + 1)
                break
        else:
            hit = _by_name(dump, base)
            if hit:
                inherited = resolve_fields(dump, hit, depth + 1)
    return inherited + dc["fields"]


def find_dump_class(dump, namespace, name, owner=None):
    """Sucht die Dump-Klasse zu einem TypeTree-Typ. Verschachtelte Typen: erst 'Owner.Name'."""
    cands = []
    if owner:
        cands.append(owner + "." + name)
    cands.append((namespace + "." if namespace else "") + name)
    cands.append(name)
    for c in cands:
        if c in dump:
            return c, dump[c]
    hit = _by_name(dump, name)
    if hit:
        return (hit["namespace"] + "." if hit["namespace"] else "") + hit["name"], hit
    return None, None


def compare_with_dump(dump, namespace, class_name, fields):
    """Vergleicht Feldnamen (in Reihenfolge) einer TypeTree-Klasse samt Unterstrukturen mit dem Dump."""
    key, dc = find_dump_class(dump, namespace, class_name)
    result = {"dump_class": key, "match": False, "offsets": {}, "nested": {}}
    if dc is None:
        return result
    tt_names = [f["name"] for f in fields]
    all_fields = resolve_fields(dump, dc)
    dump_names = [f[0] for f in all_fields]
    result["offsets"] = {f[0]: f[2] for f in all_fields}
    result["missing_in_dump"] = [n for n in tt_names if n not in dump_names]
    result["extra_in_dump"] = [n for n in dump_names if n not in tt_names]
    result["match"] = not result["missing_in_dump"]
    for f in fields:
        el = f["element"] if f["type"] == "array" else f
        if el and "fields" in el:
            sub_key, sub = find_dump_class(dump, "", el["type"], owner=dc["name"])
            if sub is None:
                result["nested"][f["name"]] = {"dump_class": None, "match": False}
                continue
            sub_tt = [x["name"] for x in el["fields"]]
            sub_fields = resolve_fields(dump, sub)
            sub_dump = [x[0] for x in sub_fields]
            result["nested"][f["name"]] = {
                "dump_class": sub_key,
                "match": all(n in sub_dump for n in sub_tt),
                "same_order": [n for n in sub_dump if n in sub_tt] == sub_tt,
                "offsets": {x[0]: x[2] for x in sub_fields},
            }
    return result


# --- Bundles lesen ------------------------------------------------------------------------------

def load_unitypy():
    sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
    try:
        import UnityPy  # noqa: WPS433
    except ImportError:
        sys.exit("UnityPy fehlt: pip install --target tools/pydeps UnityPy")
    return UnityPy


def read_bundle(unitypy, path, with_ids=False):
    """Liefert Instanz-Records [{class, namespace, assembly, name, schema, data}] eines Bundles.

    Es werden nur MonoScript und MonoBehaviour gelesen (keine Audio-/Textur-/Mesh-Objekte).
    with_ids=True haengt jedem Record die Objekt-ID des Bundles (path_id) an, damit PPtr-Verweise aufgeloest werden koennen.
    """
    env = unitypy.load(path)
    scripts = {}
    for o in env.objects:
        if o.type.name == "MonoScript":
            s = o.read()
            scripts[(o.assets_file.name, o.path_id)] = (s.m_ClassName, s.m_Namespace, s.m_AssemblyName)
    records = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        data = o.read_typetree()
        script = data.get("m_Script") or {}
        cls, ns, asm = scripts.get((o.assets_file.name, script.get("m_PathID")), (None, "", ""))
        root = o.serialized_type.node
        rec = {
            "class": cls, "namespace": ns, "assembly": asm,
            "name": data.get("m_Name", ""),
            "schema": class_schema(root),
            "data": {k: v for k, v in data.items() if k not in BOILERPLATE},
        }
        if with_ids:
            rec["path_id"] = o.path_id
        records.append(rec)
    return records


def group_by_class(records):
    groups = {}
    for r in records:
        groups.setdefault(r["class"], []).append(r)
    return groups


def count_rows(data):
    """Zeilenzahl je Top-Level-Liste einer Instanz."""
    return {k: len(v) for k, v in data.items() if isinstance(v, list)}


def survey_bundle(records, dump=None):
    classes = []
    unresolved = sum(1 for r in records if not r["class"])
    for cls, recs in sorted(group_by_class(records).items(), key=lambda kv: str(kv[0])):
        if not cls:
            continue
        first = recs[0]
        entry = {
            "class": cls, "namespace": first["namespace"], "assembly": first["assembly"],
            "instances": len(recs),
            "schema": first["schema"],
            "uniform_schema": len({schema_signature(r["schema"]) for r in recs}) == 1,
            "rows": count_rows(first["data"]) if len(recs) == 1 else None,
        }
        if dump is not None:
            entry["dump"] = compare_with_dump(dump, first["namespace"], cls, first["schema"])
        classes.append(entry)
    return {"objects": len(records), "unresolved_scripts": unresolved, "classes": classes}


# --- Export -------------------------------------------------------------------------------------

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def export_records(records, bundle_key, out_dir):
    """Schreibt pro Klasse <out_dir>/<Klasse>.json: {class, namespace, assembly, bundle, instances:[{name, data}]}.

    Hat ein Record eine path_id (read_bundle(with_ids=True)), steht sie als "path_id" in der Instanz.
    """
    written = []
    for cls, recs in group_by_class(records).items():
        if not cls:
            continue
        instances = []
        for r in recs:
            inst = {"name": r["name"], "data": r["data"]}
            if "path_id" in r:
                inst["path_id"] = r["path_id"]
            instances.append(inst)
        doc = {
            "class": cls, "namespace": recs[0]["namespace"], "assembly": recs[0]["assembly"],
            "bundle": bundle_key,
            "instances": instances,
        }
        path = os.path.join(out_dir, cls + ".json")
        write_json(path, doc)
        written.append(path)
    return written


# --- Teil 2: Filter, PPtr-Aufloesung, Zaehler, Skript-Statistik ---------------------------------

def want_class(namespace, cls, allow=None):
    """Klassenfilter fuer EXTRA_BUNDLES: allow=None -> nur Namespace XLSXContent, sonst Klassennamen aus allow."""
    if not cls:
        return False
    if allow is None:
        return namespace == "XLSXContent"
    return cls in allow


def filter_records(records, allow=None):
    return [r for r in records if want_class(r["namespace"], r["class"], allow)]


def is_pptr(value):
    return isinstance(value, dict) and set(value) >= {"m_FileID", "m_PathID"} and len(value) == 2


def resolve_pptr_names(records):
    """Ergaenzt PPtr-Verweise auf Objekte desselben Bundles um 'target_class' und 'target_name' (in place).

    Verweise auf andere Dateien (m_FileID != 0) oder nicht vorhandene Objekte bleiben unveraendert.
    Rueckgabe: (aufgeloest, offen).
    """
    index = {r["path_id"]: (r["class"], r["name"]) for r in records if "path_id" in r}
    counts = [0, 0]

    def walk(v):
        if isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            if is_pptr(v):
                hit = index.get(v["m_PathID"]) if v["m_FileID"] == 0 and v["m_PathID"] != 0 else None
                if hit:
                    v["target_class"], v["target_name"] = hit
                    counts[0] += 1
                else:
                    counts[1] += 1
                return
            for x in v.values():
                walk(x)

    for r in records:
        walk(r["data"])
    return counts[0], counts[1]


def table_counts(doc):
    """Kennzahlen einer exportierten Klassendatei: Instanzzahl und Zeilen je Sheet (Summe ueber Instanzen)."""
    rows = {}
    for inst in doc.get("instances", []):
        for k, v in (inst.get("data") or {}).items():
            if isinstance(v, list):
                rows[k] = rows.get(k, 0) + len(v)
    return {"class": doc.get("class"), "bundle": doc.get("bundle"), "instances": len(doc.get("instances", [])), "rows": rows}


def ev_stats(instances):
    """Struktur-Kennzahlen exportierter EvData-Instanzen (Skript-Bytecode wird nicht interpretiert).

    Ein Skript hat Label + Commands; ein Command ist eine Liste von Argumenten {argType, data}.
    Rueckgabe: Dateien, Skripte, Befehle, Argumente, Histogramm der argType-Werte, Zahl verschiedener
    Befehlskennungen (erstes Argument mit argType 0), Zahl Stringtabellen-Eintraege.
    """
    scripts = commands = args = strings = 0
    arg_types = {}
    opcodes = set()
    for inst in instances:
        data = inst.get("data") or {}
        strings += len(data.get("StrList") or [])
        for sc in data.get("Scripts") or []:
            scripts += 1
            for cmd in sc.get("Commands") or []:
                commands += 1
                for i, a in enumerate(cmd.get("Arg") or []):
                    args += 1
                    t = a.get("argType")
                    arg_types[t] = arg_types.get(t, 0) + 1
                    if i == 0 and t == 0:
                        opcodes.add(a.get("data"))
    return {"files": len(instances), "scripts": scripts, "commands": commands, "args": args,
            "arg_types": dict(sorted(arg_types.items())), "distinct_opcodes": len(opcodes), "strings": strings}


def _bundles(args):
    sel = dict(DATA_BUNDLES)
    if args.messages:
        sel.update(MESSAGE_BUNDLES)
    return sel


def _targets(args):
    """Liste (Bundle, Kurzname, Klassenfilter, extra) gemaess --set; extra=False: unveraendertes Verhalten von Teil 1."""
    which = getattr(args, "set", "base")
    targets = []
    if which in ("base", "all"):
        targets += [(rel, short, None, False) for rel, short in _bundles(args).items()]
    if which in ("extra", "all"):
        targets += [(rel, short, allow, True) for rel, (short, allow) in EXTRA_BUNDLES.items()]
    return targets


def _load_records(unitypy, path, allow, extra):
    if not extra:
        return read_bundle(unitypy, path)
    records = read_bundle(unitypy, path, with_ids=True)
    resolve_pptr_names(records)  # vor dem Filtern, damit auch Verweise auf nicht exportierte Klassen einen Namen bekommen
    return filter_records(records, allow)


def cmd_survey(args):
    unitypy = load_unitypy()
    dump = None
    if os.path.exists(args.dump):
        with open(args.dump, encoding="utf-8", errors="replace") as f:
            dump = parse_dump(f)
    result = {}
    result_extra = {}
    for rel, short, allow, extra in _targets(args):
        path = os.path.join(args.assets, rel)
        if not os.path.exists(path):
            print("fehlt:", rel, file=sys.stderr)
            continue
        info = survey_bundle(_load_records(unitypy, path, allow, extra), dump)
        (result_extra if extra else result)[rel] = info
        print("%-42s %5d Objekte, %3d Klassen" % (rel, info["objects"], len(info["classes"])))
        for c in info["classes"]:
            d = c.get("dump", {})
            print("   %-28s x%-4d Felder:%-3d dump:%s" % (c["class"], c["instances"], len(c["schema"]),
                  "ok" if d.get("match") else "ABWEICHUNG"))
    for data, name in ((result, "_survey.json"), (result_extra, "_survey_extra.json")):
        if data:
            write_json(os.path.join(args.out, name), data)
            print("->", os.path.join(args.out, name))


def cmd_export(args):
    unitypy = load_unitypy()
    total = 0
    for rel, short, allow, extra in _targets(args):
        path = os.path.join(args.assets, rel)
        if not os.path.exists(path):
            print("fehlt:", rel, file=sys.stderr)
            continue
        written = export_records(_load_records(unitypy, path, allow, extra), rel, os.path.join(args.out, short))
        total += len(written)
        print("%-42s -> %d Dateien" % (rel, len(written)))
    print("fertig:", total, "Dateien in", args.out)


def cmd_counts(args):
    """Zaehlt Instanzen und Zeilen aller exportierten JSON-Dateien -> <out>/_counts.json (nur Zahlen)."""
    result = {}
    for dp, dn, fn in os.walk(args.out):
        dn.sort()
        for f in sorted(fn):
            if not f.endswith(".json") or f.startswith("_"):
                continue
            with open(os.path.join(dp, f), encoding="utf-8") as fh:
                doc = json.load(fh)
            result[os.path.relpath(os.path.join(dp, f), args.out)] = table_counts(doc)
    write_json(os.path.join(args.out, "_counts.json"), result)
    for k, v in result.items():
        print("%-58s inst=%-5d %s" % (k, v["instances"], v["rows"]))
    print("->", os.path.join(args.out, "_counts.json"))


def cmd_scan(args):
    """Listet je Bundle (ausser SCAN_SKIP_TOP) die enthaltenen Tabellenklassen (XLSXContent, Dpr.Message, EvData).

    Es werden nur MonoScript-Objekte gelesen. Ergebnis: <out>/_scan.json.
    """
    unitypy = load_unitypy()
    result = {}
    for top in sorted(os.listdir(args.assets)):
        if top in SCAN_SKIP_TOP or not os.path.isdir(os.path.join(args.assets, top)):
            continue
        for dp, dn, fn in os.walk(os.path.join(args.assets, top)):
            dn.sort()
            for f in sorted(fn):
                path = os.path.join(dp, f)
                if os.path.getsize(path) > SCAN_MAX_BYTES:
                    continue
                try:
                    env = unitypy.load(path)
                    names = set()
                    for o in env.objects:
                        if o.type.name == "MonoScript":
                            s = o.read()
                            if scan_wanted(s.m_Namespace, s.m_ClassName):
                                names.add(s.m_Namespace + "." + s.m_ClassName)
                except Exception as exc:  # noqa: BLE001 - kaputte/andere Dateien einfach auslassen
                    print("uebersprungen:", path, exc, file=sys.stderr)
                    continue
                if names:
                    result[os.path.relpath(path, args.assets)] = sorted(names)
    write_json(os.path.join(args.out, "_scan.json"), result)
    print(len(result), "Bundles mit Tabellenklassen ->", os.path.join(args.out, "_scan.json"))


def scan_wanted(namespace, cls):
    return namespace in ("XLSXContent", "Dpr.Message") or cls in ("EvData", "TagPlaceData")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["survey", "export", "counts", "scan"])
    p.add_argument("--assets", default=DEFAULT_ASSETS, help="AssetAssistant-Ordner")
    p.add_argument("--out", default=DEFAULT_OUT, help="Ausgabeordner (unter work/)")
    p.add_argument("--dump", default=DEFAULT_DUMP, help="il2cpp dump.cs fuer den Abgleich")
    p.add_argument("--messages", action="store_true", help="auch Message-Bundles (MsbtData) einbeziehen")
    p.add_argument("--set", choices=["base", "extra", "all"], default="base",
                   help="base = Teil 1 (Standard), extra = weitere Bundles (EXTRA_BUNDLES), all = beides")
    args = p.parse_args(argv)
    {"survey": cmd_survey, "export": cmd_export, "counts": cmd_counts, "scan": cmd_scan}[args.command](args)


if __name__ == "__main__":
    main()
