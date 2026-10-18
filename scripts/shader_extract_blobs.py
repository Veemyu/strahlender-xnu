#!/usr/bin/env python3
"""Exportiert alle eindeutigen Maxwell-Blobs der Switch-Shaderprogramme nach work/shaders/blobs/.

Eingabe: die Unity-Bundles mit den Switch-Shadern (Plattform 19), Standard Dpr/shaders und Effects/fxparticle
(mit --extra zusaetzlich resources.assets und tmpshader). Je Programm wird der Maxwell-Blob (ab dem NVN-Kopf
0x12345678 bis zum Ende des Programms; die Container-Felder Datenoffset/-groesse umfassen den Code nicht immer, der
Uebersetzer findet das Codeende selbst) ausgeschnitten, per SHA-1 dedupliziert und als <hash>.bin abgelegt, dazu
index.json (Hash, Stufe, Groesse, Programme/Shader je Hash, Quellbundle, codeHash = Hash nur ueber SPH + Code).

Aufruf (aus dem Repo-Root):
    PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py [--out work/shaders/blobs] [--extra]

Die Ausgabe enthaelt Spieldaten und gehoert nur unter work/ (gitignored), nie ins Repo.
Die Parser-Funktionen (parse_program, blob_hash) brauchen nur die Standardbibliothek; UnityPy und lz4 werden erst
beim Lesen der Bundles importiert.
"""
import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

PROGRAM_MAGIC = 0x0C07513C
CONTROL_MAGIC = 0x98761234
BLOB_MAGIC = b"\x78\x56\x34\x12"
STAGE_NAMES = {0: "vs", 1: "fs"}

BUNDLES = [
    "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/shaders",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Effects/fxparticle",
]
EXTRA = ["work/romfs/Data/resources.assets",
         "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/tmpshader"]


def u32(d, o):
    if o < 0 or o + 4 > len(d):
        raise ValueError("abgeschnittener Container")
    return struct.unpack_from("<I", d, o)[0]


def parse_program(d):
    """Zerlegt ein Unity-Shaderprogramm (Switch). Liefert dict mit stage ('vs'/'fs'/None), keywords, blob (bytes)."""
    if u32(d, 0) != PROGRAM_MAGIC:
        raise ValueError("Magic 0x0C07513C fehlt")
    nkw = u32(d, 0x18)
    pos = 0x1C
    lists = []
    for _ in range(2):  # globale, dann lokale Keywords: [Anzahl]{[Laenge][Text\0, auf 4 aufgerundet]}
        if nkw > 4096:
            raise ValueError("unplausible Keyword-Anzahl")
        kws = []
        for _ in range(nkw):
            ln = u32(d, pos)
            if ln > 4096:
                raise ValueError("unplausible Keyword-Laenge")
            kws.append(d[pos + 4:pos + 4 + max(ln - 1, 0)].decode("ascii", "replace"))
            pos = (pos + 4 + ln + 3) & ~3
        lists.append(kws)
        if len(lists) == 1:
            nkw = u32(d, pos)
            pos += 4
    hdr = pos
    if u32(d, hdr + 0x14) != CONTROL_MAGIC:
        raise ValueError("Control-Magic 0x98761234 fehlt")
    m = d.find(BLOB_MAGIC, hdr + 0x18)
    if m < 0:
        raise ValueError("Maxwell-Blob (0x12345678) nicht gefunden")
    return {"stage": STAGE_NAMES.get(u32(d, hdr + 4)), "keywords": lists[0] + lists[1], "blob": bytes(d[m:]),
            "version": u32(d, 4)}


def blob_hash(blob):
    return hashlib.sha1(blob).hexdigest()[:16]


def code_end(blob):
    """Ende des Maxwell-Codes im Blob (NVN-Kopf 0x30 + SPH 0x50, danach Vierergruppen). Gleiche Regel wie der
    Uebersetzer: der Code endet vor dem unbedingten Sprung auf sich selbst (Padding nach EXIT) bzw. vor dem ersten
    Nullwort; danach folgen Compiler-Konstanten und andere Daten."""
    base = 0x80
    n = min((len(blob) - base) // 8, 65536)
    end = 0
    for i in range(n):
        if i % 4 == 0:
            continue
        w = struct.unpack_from("<Q", blob, base + 8 * i)[0]
        if (w & 0xfff0000000000020) == 0xe240000000000000 and (w >> 16) & 0xf == 7 and end:
            off = (w >> 20) & 0xffffff
            off -= 1 << 24 if off & 0x800000 else 0
            t = 8 * i + 8 + off
            if t >= 0 and (t // 8) % 4 == 0:
                t += 8
            if t == 8 * i:
                break
        if w == 0 and i > 4:
            break
        end = i + 1
    return base + 8 * end


def code_hash(blob):
    return hashlib.sha1(blob[0x30:code_end(blob)]).hexdigest()[:16]


def collect(programs, out_dir):
    """programs: Iterable von (bundle, shader, pass-Name, stage-Schluessel, keywords, bytes). Schreibt Blobs, liefert Index."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = {}
    total = 0
    parse_fail = []
    for bundle, shader, raw in programs:
        total += 1
        try:
            p = parse_program(raw)
        except ValueError as e:
            parse_fail.append({"bundle": bundle, "shader": shader, "error": str(e)})
            continue
        if p["stage"] is None:
            parse_fail.append({"bundle": bundle, "shader": shader, "error": "unbekannte Stufe"})
            continue
        h = blob_hash(p["blob"])
        e = entries.get(h)
        if e is None:
            (out_dir / f"{h}.bin").write_bytes(p["blob"])
            e = entries[h] = {"hash": h, "stage": p["stage"], "size": len(p["blob"]), "codeHash": code_hash(p["blob"]), "programs": 0, "bundles": set(),
                              "shaders": set()}
        e["programs"] += 1
        e["bundles"].add(bundle)
        e["shaders"].add(shader)
    index = []
    for h in sorted(entries):
        e = entries[h]
        e["bundles"] = sorted(e["bundles"])
        e["shaders"] = sorted(e["shaders"])
        index.append(e)
    summary = {"programs": total, "parsed": total - len(parse_fail), "parseFailures": len(parse_fail), "unique": len(index), "uniqueCodes": len({e["codeHash"] for e in index}),
               "uniqueByStage": dict(Counter(e["stage"] for e in index))}
    (out_dir / "index.json").write_text(json.dumps({"summary": summary, "parseFailureList": parse_fail[:100], "blobs": index},
                                                   indent=1))
    return summary


def iter_bundle_programs(paths):
    import lz4.block  # noqa: F401  (von shader_inventory benoetigt)
    import UnityPy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import shader_inventory as si  # nur lesend: Blob-Klasse fuer die Segmente

    for bpath in paths:
        bundle = Path(bpath).name
        env = UnityPy.load(bpath)
        for o in env.objects:
            if o.type.name != "Shader":
                continue
            tt = o.read_typetree()
            blob = si.Blob(tt)
            parsed = tt["m_ParsedForm"]
            for ss in parsed["m_SubShaders"]:
                for ps in ss["m_Passes"]:
                    for stage_key in ("progVertex", "progFragment"):
                        for sp in ps[stage_key]["m_SubPrograms"]:
                            yield bundle, parsed["m_Name"], bytes(blob.get(sp["m_BlobIndex"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="work/shaders/blobs", help="Zielordner (unter work/)")
    ap.add_argument("--extra", action="store_true", help="auch resources.assets und tmpshader lesen")
    args = ap.parse_args()
    out = Path(args.out)
    if "work" not in out.parts:
        sys.exit("Abbruch: Die Blobs sind Spieldaten und duerfen nur unter work/ liegen.")
    paths = BUNDLES + (EXTRA if args.extra else [])
    summary = collect(iter_bundle_programs(paths), out)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
