#!/usr/bin/env python3
"""Exports all unique Maxwell blobs of the Switch shader programs to work/shaders/blobs/.

Input: the Unity bundles with the Switch shaders (platform 19), default Dpr/shaders and Effects/fxparticle
(with --extra additionally resources.assets and tmpshader). For each program the Maxwell blob (from the NVN header
0x12345678 to the end of the program; the container fields data offset/size do not always cover the code, the
translator finds the end of the code itself) is cut out, deduplicated by SHA-1 and stored as <hash>.bin, plus
index.json (hash, stage, size, programs/shaders per hash, source bundle, codeHash = hash over SPH + code only).

Usage (from the repo root):
    PYTHONPATH=tools/pydeps python3 scripts/shader_extract_blobs.py [--out work/shaders/blobs] [--extra]

The output contains game data and belongs only under work/ (gitignored), never in the repo.
The parser functions (parse_program, blob_hash) need only the standard library; UnityPy and lz4 are imported only
when reading the bundles.
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
    """Parses a Unity shader program (Switch). Returns a dict with stage ('vs'/'fs'/None), keywords, blob (bytes)."""
    if u32(d, 0) != PROGRAM_MAGIC:
        raise ValueError("magic 0x0C07513C missing")
    nkw = u32(d, 0x18)
    pos = 0x1C
    lists = []
    for _ in range(2):  # global, then local keywords: [count]{[length][text\0, rounded up to 4]}
        if nkw > 4096:
            raise ValueError("implausible keyword count")
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
        raise ValueError("control magic 0x98761234 missing")
    m = d.find(BLOB_MAGIC, hdr + 0x18)
    if m < 0:
        raise ValueError("Maxwell blob (0x12345678) not found")
    return {"stage": STAGE_NAMES.get(u32(d, hdr + 4)), "keywords": lists[0] + lists[1], "blob": bytes(d[m:]),
            "version": u32(d, 4)}


def blob_hash(blob):
    return hashlib.sha1(blob).hexdigest()[:16]


def code_end(blob):
    """End of the Maxwell code in the blob (NVN header 0x30 + SPH 0x50, then groups of four). Same rule as the
    translator: the code ends before the unconditional jump to itself (padding after EXIT) or before the first
    zero word; compiler constants and other data follow."""
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
    """programs: iterable of (bundle, shader, pass name, stage key, keywords, bytes). Writes blobs, returns the index."""
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
            parse_fail.append({"bundle": bundle, "shader": shader, "error": "unknown stage"})
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
    import lz4.block  # noqa: F401  (needed by shader_inventory)
    import UnityPy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import shader_inventory as si  # read only: blob class for the segments

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
    ap.add_argument("--extra", action="store_true", help="also read resources.assets and tmpshader")
    args = ap.parse_args()
    out = Path(args.out)
    if "work" not in out.parts:
        sys.exit("Abort: the blobs are game data and may only be placed under work/.")
    paths = BUNDLES + (EXTRA if args.extra else [])
    summary = collect(iter_bundle_programs(paths), out)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
