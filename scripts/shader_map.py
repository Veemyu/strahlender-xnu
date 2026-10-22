#!/usr/bin/env python3
"""Maps the Switch shader programs of the Unity bundles to the entries of the Ryujinx shader cache.

Idea: every bundle program is a GLSLC binary (NVN) with embedded Maxwell code plus the
shader program header (SPH, 0x50 bytes). The Ryujinx guest.data entry contains exactly SPH + code
of the variant. Compared byte by byte (prefix of the blob code from the SPH on).

Usage (from the repo root):
    PYTHONPATH=tools/pydeps python3 scripts/shader_map.py [--out work/shaders/mapping.json]

Read only. Writes only the JSON file (numbers, names, indices; no binary data).
"""
import argparse
import hashlib
import json
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import UnityPy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shader_inventory as si  # noqa: E402

CACHE = Path("Ryujinx/games/0100000011d90000/cache/shader")
NVN_MAGIC = 0x0C07513C
CTRL_MAGIC = 0x98761234
SPH_SIZE = 0x50
KEY_LEN = 32
STAGE_NAMES = {0: "vertex", 1: "fragment"}


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def parse_nvn(d):
    """Parses a bundle program. Returns None if the pattern does not match."""
    if len(d) < 0x80 or u32(d, 0) != NVN_MAGIC:
        return None
    nkw = u32(d, 0x18)
    pos = 0x1C
    kws = []
    lkws = []
    for target in (kws, lkws):  # first global, then local keywords: [count]{[length][text\0, rounded up to 4]}
        for _ in range(nkw):
            ln = u32(d, pos)
            target.append(d[pos + 4:pos + 4 + ln].decode("ascii", "replace"))
            pos = (pos + 4 + ln + 3) & ~3
        if target is kws:
            nkw = u32(d, pos)
            pos += 4
    hdr = pos
    if u32(d, hdr + 0x14) != CTRL_MAGIC:
        return None
    m = d.find(b"\x78\x56\x34\x12", hdr + 0x18)
    if m < 0:
        return None
    return {"version": u32(d, 4), "keywords": kws, "localKeywords": lkws, "total": u32(d, hdr), "stage": u32(d, hdr + 4),
            "dataOffset": u32(d, hdr + 0xC), "dataSize": u32(d, hdr + 0x10),
            "sph": m + 0x30, "headerEnd": hdr + 0x18}


def load_guest():
    toc = (CACHE / "guest.toc").read_bytes()
    data = (CACHE / "guest.data").read_bytes()
    n = (len(toc) - 32) // 16
    out = []
    for i in range(n):
        off, cs, cbs, h = struct.unpack_from("<IIII", toc, 32 + 16 * i)
        algo = data[off + cbs]
        body = data[off + cbs + 1:]
        if algo == 1:
            code = zlib.decompressobj(-15).decompress(body, cs)
        elif algo == 0:
            code = body[:cs]
        else:
            import brotli
            code = brotli.Decompressor().process(bytes(body[:max(cs * 2, 65536)]))[:cs]
        out.append({"index": i, "code": code, "cb1": cbs, "hash": h})
    return out


def load_shared():
    toc = (CACHE / "shared.toc").read_bytes()
    data = (CACHE / "shared.data").read_bytes()
    n = (len(toc) - 32) // 8
    res = []
    for i in range(n):
        off = struct.unpack_from("<Q", toc, 32 + 8 * i)[0]
        algo = data[off]
        body = data[off + 1:]
        if algo == 1:
            head = zlib.decompressobj(-15).decompress(body, 64)
        elif algo == 0:
            head = body[:64]
        else:
            import brotli
            head = brotli.Decompressor().process(bytes(body[:4096]))[:64]
        mask = u32(head, 0)
        stages = [b for b in range(6) if mask >> b & 1] or [0]  # mask 0 = compute
        guests = [struct.unpack_from("<i", head, 4 + 4 * k)[0] for k in range(len(stages))]
        res.append({"index": i, "mask": mask, "stages": dict(zip(stages, guests))})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/shaders/mapping.json")
    args = ap.parse_args()

    guest = load_guest()
    shared = load_shared()
    print("guest", len(guest), "shared", len(shared), file=sys.stderr)

    by_key = defaultdict(list)
    for g in guest:
        c = g["code"]
        if len(c) >= SPH_SIZE + KEY_LEN and c[0] & 0x1F in (1, 2):
            by_key[bytes(c[SPH_SIZE:SPH_SIZE + KEY_LEN])].append(g["index"])

    programs = []  # one entry per bundle program
    guest_hits = defaultdict(list)  # guest index -> program indices
    guest_hits_codeonly = defaultdict(list)
    parse_fail = 0
    tiers = Counter()
    sizes_unique = {}

    for bpath in si.BUNDLES + si.EXTRA_SOURCES:
        env = UnityPy.load(bpath)
        for o in env.objects:
            if o.type.name != "Shader":
                continue
            tt = o.read_typetree()
            parsed = tt["m_ParsedForm"]
            blob = si.Blob(tt)
            sname = parsed["m_Name"]
            for ssi, ss in enumerate(parsed["m_SubShaders"]):
                for psi, ps in enumerate(ss["m_Passes"]):
                    names = {i: n for n, i in ps["m_NameIndices"]}
                    for stage_key in ("progVertex", "progFragment"):
                        for spi, sp in enumerate(ps[stage_key]["m_SubPrograms"]):
                            d = bytes(blob.get(sp["m_BlobIndex"]))
                            info = parse_nvn(d)
                            pid = len(programs)
                            rec = {"id": pid, "bundle": Path(bpath).name, "shader": sname, "subShader": ssi, "pass": psi,
                                   "stage": stage_key[4:].lower(), "subProgram": spi, "blobIndex": sp["m_BlobIndex"],
                                   "blobSize": len(d),
                                   "keywords": [names.get(i, f"#{i}") for i in sp["m_GlobalKeywordIndices"] + sp["m_LocalKeywordIndices"]]}
                            if info is None:
                                parse_fail += 1
                                rec["parsed"] = False
                                programs.append(rec)
                                continue
                            rec["parsed"] = True
                            rec["blobKeywords"] = info["keywords"] + info["localKeywords"]
                            rec["kwMatch"] = sorted(rec["blobKeywords"]) == sorted(rec["keywords"])
                            rec["nvnStage"] = STAGE_NAMES.get(info["stage"], info["stage"])
                            sph = info["sph"]
                            code = d[sph:]
                            digest = hashlib.sha1(code[:info["dataOffset"] + info["dataSize"] - sph]).hexdigest()[:16] if info["dataOffset"] + info["dataSize"] > sph else None
                            rec["codeHash"] = digest
                            rec["sphWord0"] = hex(u32(d, sph))
                            key = bytes(d[sph + SPH_SIZE:sph + SPH_SIZE + KEY_LEN])
                            for gi in by_key.get(key, ()):
                                g = guest[gi]["code"]
                                if d[sph:sph + len(g)] == g:
                                    guest_hits[gi].append(pid)
                                    rec.setdefault("guestFull", []).append(gi)
                                elif d[sph + SPH_SIZE:sph + len(g)] == g[SPH_SIZE:]:
                                    guest_hits_codeonly[gi].append(pid)
                                    rec.setdefault("guestCodeOnly", []).append(gi)
                            programs.append(rec)

    # Guest entries without a hit: substring search (code without SPH) in the raw blob of every shader
    unmatched = [g for g in guest if g["index"] not in guest_hits and g["index"] not in guest_hits_codeonly]
    print("without prefix hit:", len(unmatched), file=sys.stderr)
    substr_hits = {}
    if unmatched:
        needles = {}
        for g in unmatched:
            c = g["code"]
            start = SPH_SIZE + 16 if (c[0] & 0x1F in (1, 2)) else 16
            if len(c) >= start + 48:
                needles[g["index"]] = bytes(c[start:start + 48])
        for bpath in si.BUNDLES + si.EXTRA_SOURCES:
            env = UnityPy.load(bpath)
            for o in env.objects:
                if o.type.name != "Shader":
                    continue
                tt = o.read_typetree()
                blob = si.Blob(tt)
                big = b"".join(blob.segments)
                for gi, nd in needles.items():
                    if gi in substr_hits:
                        continue
                    p = big.find(nd)
                    if p >= 0:
                        substr_hits[gi] = {"shader": tt["m_ParsedForm"]["m_Name"], "offset": p}
                del big, blob

    # Cache entries (shared) -> bundle programs
    stage_idx = {1: "vertex", 5: "fragment"}
    prog_by_id = {p["id"]: p for p in programs}
    cache_entries = []
    covered_variants = set()
    summary = Counter()
    for sh in shared:
        e = {"index": sh["index"], "mask": sh["mask"], "guest": {}, "match": {}, "candidates": []}
        stage_progs = {}
        for bit, gi in sh["stages"].items():
            sname = stage_idx.get(bit, f"bit{bit}")
            e["guest"][sname] = gi
            hits = guest_hits.get(gi, []) or guest_hits_codeonly.get(gi, [])
            e["match"][sname] = len(hits)
            stage_progs[sname] = hits
        ok_v = stage_progs.get("vertex")
        ok_f = stage_progs.get("fragment")
        if sh["mask"] and ok_v and ok_f:
            vp = defaultdict(list)
            for pid in ok_v:
                p = prog_by_id[pid]
                vp[(p["bundle"], p["shader"], p["subShader"], p["pass"])].append(pid)
            fp = defaultdict(list)
            for pid in ok_f:
                p = prog_by_id[pid]
                fp[(p["bundle"], p["shader"], p["subShader"], p["pass"])].append(pid)
            for k in vp:
                if k in fp:
                    kwsets = lambda ids: sorted({tuple(sorted(prog_by_id[i]["blobKeywords"])) for i in ids})  # noqa: E731
                    cand = {"bundle": k[0], "shader": k[1], "subShader": k[2], "pass": k[3],
                            "vertexPrograms": vp[k], "fragmentPrograms": fp[k],
                            "vertexKeywordSets": [list(t) for t in kwsets(vp[k])],
                            "fragmentKeywordSets": [list(t) for t in kwsets(fp[k])]}
                    # Pairing: vertex and fragment program with the same keyword set = the same variant
                    eq = [(v, f) for v in vp[k] for f in fp[k]
                          if sorted(prog_by_id[v]["blobKeywords"]) == sorted(prog_by_id[f]["blobKeywords"])]
                    cand["pairKind"] = "same_keywords" if eq else "no_common_set"
                    cand["pairs"] = eq[:20]
                    cand["pairCount"] = len(eq)
                    for v, f in eq:
                        covered_variants.add((k[0], k[1], k[2], k[3], tuple(sorted(prog_by_id[v]["blobKeywords"]))))
                    e["candidates"].append(cand)
        e["status"] = ("compute" if sh["mask"] == 0 else
                       "full" if e["candidates"] else
                       "one_stage_only" if (ok_v or ok_f) else "none")
        summary["cache_" + e["status"]] += 1
        if e["candidates"]:
            shaders = {c["shader"] for c in e["candidates"]}
            summary["cache_full_shader_unique" if len(shaders) == 1 else "cache_full_shader_ambiguous"] += 1
            passes = {(c["shader"], c["subShader"], c["pass"]) for c in e["candidates"]}
            summary["cache_full_pass_unique" if len(passes) == 1 else "cache_full_pass_ambiguous"] += 1
            if len(e["candidates"]) == 1:
                c = e["candidates"][0]
                if len(c["vertexPrograms"]) == 1 and len(c["fragmentPrograms"]) == 1:
                    summary["cache_full_variant_unique"] += 1
            vs = {(c["shader"], c["subShader"], c["pass"], tuple(sorted(prog_by_id[v]["blobKeywords"])))
                  for c in e["candidates"] for v, _f in c["pairs"]}
            if len(vs) == 1 and all(c["pairCount"] <= 20 for c in e["candidates"]):
                summary["cache_full_keyword_variant_unique"] += 1
            elif not vs:
                summary["cache_full_without_common_keyword_set"] += 1
        cache_entries.append(e)

    matched_prog_ids = {pid for lst in guest_hits.values() for pid in lst} | {pid for lst in guest_hits_codeonly.values() for pid in lst}
    # Variants = keyword sets that occur in the vertex and fragment list of the same pass
    vsets = defaultdict(lambda: [set(), set()])
    for p in programs:
        vsets[(p["bundle"], p["shader"], p["subShader"], p["pass"])][0 if p["stage"] == "vertex" else 1].add(tuple(sorted(p["blobKeywords"])))
    all_variants = {(*k, kw) for k, (a, b) in vsets.items() for kw in a & b}
    core = ("shaders", "fxparticle")
    variant_stats = {
        "variantsEqualSetsTotal": len(all_variants),
        "variantsEqualSetsCovered": len(all_variants & covered_variants),
        "variantsEqualSetsTotalCore64": sum(1 for v in all_variants if v[0] in core),
        "variantsEqualSetsCoveredCore64": sum(1 for v in all_variants & covered_variants if v[0] in core),
        "bundleProgramsCore64": sum(1 for p in programs if p["bundle"] in core),
        "bundleProgramsInCacheCore64": sum(1 for p in programs if p["bundle"] in core and p["id"] in matched_prog_ids),
        "bundleUniqueCodeHashesCore64": len({p["codeHash"] for p in programs if p["bundle"] in core}),
        "bundleUniqueCodeHashesInCacheCore64": len({p["codeHash"] for p in programs if p["bundle"] in core and p["id"] in matched_prog_ids}),
        "bundleUniqueCodeHashesInCache": len({p["codeHash"] for p in programs if p["id"] in matched_prog_ids}),
        "guestMatchedCore64": len({gi for gi, pids in guest_hits.items() if any(programs[pid]["bundle"] in core for pid in pids)}),
        "cacheEntriesWithCore64Candidate": sum(1 for e in cache_entries if any(c["bundle"] in core for c in e["candidates"])),
    }
    stats = {
        "bundlePrograms": len(programs), "bundleProgramsParsed": len(programs) - parse_fail,
        "bundleKeywordListsEqualTypetree": sum(1 for p in programs if p.get("kwMatch")),
        "bundleProgramsByStage": dict(Counter(p["stage"] for p in programs)),
        "bundleUniqueCodeHashes": len({p.get("codeHash") for p in programs if p.get("codeHash")}),
        "guestEntries": len(guest), "guestMatchedFull": len(guest_hits), "guestMatchedCodeOnly": len(guest_hits_codeonly),
        "guestUnmatched": len(unmatched), "guestUnmatchedSubstringHits": len(substr_hits),
        "guestByType": dict(Counter(("compute" if g["code"][0] & 0x1F not in (1, 2) else
                                     "vertex" if g["code"][0] & 0x1F == 1 else "fragment") for g in guest)),
        "bundleProgramsInCache": len(matched_prog_ids),
        "bundleProgramsInCacheByStage": dict(Counter(prog_by_id[i]["stage"] for i in matched_prog_ids)),
        "sharedEntries": len(shared), "sharedStageMasks": {hex(k): v for k, v in Counter(s["mask"] for s in shared).items()},
        **variant_stats,
        **dict(summary),
    }
    per_shader = defaultdict(lambda: Counter())
    for p in programs:
        key = f'{p["bundle"]}: {p["shader"]}'
        per_shader[key]["programs"] += 1
        if p["id"] in matched_prog_ids:
            per_shader[key]["inCache"] += 1
    for e in cache_entries:
        for key in {f'{c["bundle"]}: {c["shader"]}' for c in e["candidates"]}:
            per_shader[key]["cacheEntries"] += 1
    stats["perShader"] = {k: dict(v) for k, v in sorted(per_shader.items())}

    unm = []
    for g in unmatched:
        unm.append({"index": g["index"], "size": len(g["code"]), "cb1": g["cb1"], "sphWord0": hex(u32(g["code"], 0)),
                    "substring": substr_hits.get(g["index"])})
    out = {"method": "byte comparison: guest code (SPH+Maxwell) == prefix of the blob from the SPH on (SPH = position of 0x12345678 + 0x30)",
           "stats": stats, "unmatchedGuest": unm, "cacheEntries": cache_entries,
           "programs": [{k: v for k, v in p.items()} for p in programs]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False))
    print(json.dumps({k: v for k, v in stats.items() if k != "perShader"}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
