#!/usr/bin/env python3
"""Stammdaten aus den UnityFS-Bundles des Dumps lesen (TypeTree-basiert, ohne Unity).

Die Bundles enthalten serialisierte ScriptableObjects (MonoBehaviour) mit vollstaendigem TypeTree.
UnityPy (MIT) liest sie; installiert wird es nur unter tools/pydeps:

    pip install --target tools/pydeps UnityPy

Unterbefehle:
    survey   Bundles untersuchen: Klassen, Instanzen, Feldschema; Abgleich mit work/il2cpp/dump.cs
             -> work/masterdata/_survey.json (+ Tabelle auf stdout)
    export   Alle MonoBehaviour-Instanzen der Daten-Bundles als JSON nach work/masterdata/<bundle>/<Klasse>.json

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


def read_bundle(unitypy, path):
    """Liefert Instanz-Records [{class, namespace, assembly, name, schema, data}] eines Bundles.

    Es werden nur MonoScript und MonoBehaviour gelesen (keine Audio-/Textur-/Mesh-Objekte).
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
        records.append({
            "class": cls, "namespace": ns, "assembly": asm,
            "name": data.get("m_Name", ""),
            "schema": class_schema(root),
            "data": {k: v for k, v in data.items() if k not in BOILERPLATE},
        })
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
    """Schreibt pro Klasse <out_dir>/<Klasse>.json: {class, namespace, assembly, bundle, instances:[{name, data}]}."""
    written = []
    for cls, recs in group_by_class(records).items():
        if not cls:
            continue
        doc = {
            "class": cls, "namespace": recs[0]["namespace"], "assembly": recs[0]["assembly"],
            "bundle": bundle_key,
            "instances": [{"name": r["name"], "data": r["data"]} for r in recs],
        }
        path = os.path.join(out_dir, cls + ".json")
        write_json(path, doc)
        written.append(path)
    return written


def _bundles(args):
    sel = dict(DATA_BUNDLES)
    if args.messages:
        sel.update(MESSAGE_BUNDLES)
    return sel


def cmd_survey(args):
    unitypy = load_unitypy()
    dump = None
    if os.path.exists(args.dump):
        with open(args.dump, encoding="utf-8", errors="replace") as f:
            dump = parse_dump(f)
    result = {}
    for rel, short in _bundles(args).items():
        path = os.path.join(args.assets, rel)
        if not os.path.exists(path):
            print("fehlt:", rel, file=sys.stderr)
            continue
        info = survey_bundle(read_bundle(unitypy, path), dump)
        result[rel] = info
        print("%-42s %5d Objekte, %3d Klassen" % (rel, info["objects"], len(info["classes"])))
        for c in info["classes"]:
            d = c.get("dump", {})
            print("   %-28s x%-4d Felder:%-3d dump:%s" % (c["class"], c["instances"], len(c["schema"]),
                  "ok" if d.get("match") else "ABWEICHUNG"))
    write_json(os.path.join(args.out, "_survey.json"), result)
    print("->", os.path.join(args.out, "_survey.json"))


def cmd_export(args):
    unitypy = load_unitypy()
    total = 0
    for rel, short in _bundles(args).items():
        path = os.path.join(args.assets, rel)
        if not os.path.exists(path):
            print("fehlt:", rel, file=sys.stderr)
            continue
        written = export_records(read_bundle(unitypy, path), rel, os.path.join(args.out, short))
        total += len(written)
        print("%-42s -> %d Dateien" % (rel, len(written)))
    print("fertig:", total, "Dateien in", args.out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["survey", "export"])
    p.add_argument("--assets", default=DEFAULT_ASSETS, help="AssetAssistant-Ordner")
    p.add_argument("--out", default=DEFAULT_OUT, help="Ausgabeordner (unter work/)")
    p.add_argument("--dump", default=DEFAULT_DUMP, help="il2cpp dump.cs fuer den Abgleich")
    p.add_argument("--messages", action="store_true", help="auch Message-Bundles (MsbtData) einbeziehen")
    args = p.parse_args(argv)
    {"survey": cmd_survey, "export": cmd_export}[args.command](args)


if __name__ == "__main__":
    main()
