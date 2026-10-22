#!/usr/bin/env python3
"""Numerical fidelity test: Maxwell->MSL translation (maxwell2msl) against the Ryujinx reference (SPIR-V -> MSL).

For program pairs (vertex + fragment) that occur in BOTH sources (bundle blob and Ryujinx SPIR-V, matched
through work/shaders/mapping.json), deterministic inputs are generated from the interface of the reference shader
(vertex attributes, constant buffers, synthetic textures). The harness (scripts/shader_harness) renders
(a) the reference and (b) our translation with identical state; scripts/shader_compare.py compares the images.
On deviations two mixed variants are rendered (reference VS + our FS, our VS + reference FS), which narrow the
error down to one stage.

Usage (from the repo root, all data local under work/shaders/):
  python3 scripts/shader_fidelity.py index                    # program -> blob hash (needs UnityPy, once)
  python3 scripts/shader_fidelity.py run --count 120          # sample (alternating per shader)
  python3 scripts/shader_fidelity.py run --all --jobs 4       # all admissible pairs
  python3 scripts/shader_fidelity.py run --only 1 2 100       # specific cache indices

Thresholds (justified in docs/shaders.md): passed = max. deviation <= 1 step per channel (1/255, the
rounding limit of rgba8Unorm); "marginal" = <= 3; otherwise failed. Result: work/shaders/fidelity_report.json,
images under work/shaders/out/fidelity/ (not in the repo).
Standard library only (index additionally UnityPy).
"""
import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shader_compare as sc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work" / "shaders"
TRANSLATOR = ROOT / "shader_translator" / "build" / "maxwell2msl"
HARNESS = WORK / "build" / "release" / "shader-harness"

IMAGE_SIZE = 128
VERTEX_BUFFER_SLOT = 30      # as in the harness examples: outside the cbuf slots
CBUF_BYTES = 65536           # the Ryujinx modules declare float4[4096]
GRID = 12                    # grid of 12x12 cells
CLEAR = (0.25, 0.5, 0.75, 0.5)
PASS_DIFF = 1                # 1/255 per channel
NEAR_DIFF = 3
MIN_COVERAGE = 0.02          # share of pixels that differ from the clear color for the image to be meaningful
PROFILES = ("identity", "dense", "hash", "signed", "small", "half", "identity@1", "identity@2", "identity@3", "dense@1", "dense@2",
            "dense@3", "identity%1", "identity%2", "identity%3", "identity%4", "identity%5", "identity%6", "dense%1", "dense%2",
            "dense%3", "dense%4", "hash#1", "signed#1", "small#1", "hash#2", "signed#2", "small#2", "hash#3", "signed#3",
            "hash#4", "signed#4", "hash#5", "signed#5", "identity%7", "identity%8", "identity%9", "identity%10", "dense%5",
            "dense%6", "dense%7", "dense%8")
TEXTURE_TABLE_BASE = 0x568   # see maxwell2msl --info (assumption: handle table in cbuf 2)


# --------------------------------------------------------------------------- Reading the reference MSL
def split_params(sig):
    """Splits the parameter list of an MSL function at commas outside <...>."""
    out, depth, cur = [], 0, []
    for ch in sig:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


TEX_NAME_RE = re.compile(r"_tex_cb(\d+)_([0-9A-Fa-f]+)$")


def tex_key_from_name(name):
    """Ryujinx name of a bindless texture -> (texture word offset, sampler word offset) in bytes, or None.

    Example: fp_tex_cb196610_1056805A -> (0x568, 0x168). The upper half of the hex value carries the word index of the
    texture word (0x10568 -> 0x568), the lower 12 bits the word index of the sampler word (0x5A * 4 = 0x168)."""
    m = TEX_NAME_RE.search(name)
    if not m:
        return None
    v = int(m.group(2), 16)
    return ((v >> 12) & 0xFFFF, (v & 0xFFF) * 4)


def parse_ref_msl(text):
    """Reads the interface of the entry point main0 from the spirv-cross MSL.

    Returns {'stage', 'attrs': [(loc, type)], 'buffers': [(name, slot, kind, index)], 'textures': [...], 'unsupported': [...]}.
    kind of a buffer: 'cbuf' (name vp_c<k>/fp_c<k>), 'support' (support_buffer) or 'other'."""
    m = re.search(r"^(vertex|fragment)\s+[\w:<>]+\s+main0\((.*?)\)\s*$", text, re.M)
    if not m:
        raise ValueError("main0 not found")
    res = {"stage": m.group(1), "attrs": [], "buffers": [], "textures": [], "unsupported": []}
    samplers = {}
    textures = []
    for p in split_params(m.group(2)):
        am = re.search(r"\[\[(\w+)(?:\((\d+)\))?\]\]\s*$", p)
        if not am:
            continue
        kind, idx = am.group(1), int(am.group(2)) if am.group(2) else None
        head = p[:am.start()].strip()
        name = re.split(r"[ &*]+", head)[-1]
        if kind == "buffer":
            cm = re.match(r"^[vf]p_c(\d+)$", name)
            if cm:
                res["buffers"].append((name, idx, "cbuf", int(cm.group(1))))
            elif name == "support_buffer":
                res["buffers"].append((name, idx, "support", 0))
            else:
                res["buffers"].append((name, idx, "other", 0))
                res["unsupported"].append(f"buffer {name}")
        elif kind == "texture":
            ttype = head.split()[0]
            textures.append({"name": name, "slot": idx, "type": ttype})
        elif kind == "sampler":
            samplers[name] = idx
    for t in textures:
        t["sampler_slot"] = samplers.get(t["name"] + "Smplr", t["slot"])
        t["key"] = tex_key_from_name(t["name"])
        if t["type"] != "texture2d<float>":
            res["unsupported"].append(f"texture type {t['type']}")
        if t["key"] is None:
            res["unsupported"].append(f"texture name {t['name']}")
        res["textures"].append(t)
    for am in re.finditer(r"(\w+)\s+\w+\s+\[\[attribute\((\d+)\)\]\]", text):
        res["attrs"].append((int(am.group(2)), am.group(1)))
    return res


# --------------------------------------------------------------------------- deterministic inputs
def _mix(i, seed):
    x = (i * 0x9E3779B1 + seed * 0x85EBCA6B + 0x165667B1) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return x


def hash01(i, seed):
    return _mix(i, seed) / 4294967296.0


def parse_profile(profile):
    """'name', 'name@shift' (matrix grid shifted by shift vec4), 'name%n' (shift per cbuf from a hash),
    'name#seed' or combinations -> (name, shift, seed, per_cbuf_variant)."""
    m = re.match(r"^([a-z]+)(?:@(\d+))?(?:%(\d+))?(?:#(\d+))?$", profile)
    if not m:
        raise ValueError(f"unknown profile {profile}")
    return m.group(1), int(m.group(2) or 0), int(m.group(4) or 0), int(m.group(3) or 0)


def cbuf_bytes(profile, size=CBUF_BYTES, seed=1, k=0):
    """Constant buffer contents (little-endian float32). Profiles:
    identity: every four consecutive vec4 form an identity matrix (matrices become the identity),
    dense: 0.25 plus 0.5 on the diagonal, hash: random in [0.1, 1], signed: random in [-0.5, 0.5],
    small: random in [0.02, 0.2], half: 0.5 (w = 1).
    '@s' shifts the matrix grid by s vec4 (matrices that do not start on 64 bytes), '%n' shifts it differently per
    cbuf index k, '#s' changes the randomness."""
    name, shift, extra, variant = parse_profile(profile)
    if variant:
        shift = _mix(k + 1, variant) % 4
    seed = seed + 1000 * extra
    n = size // 4
    vals = []
    for i in range(n):
        vec, comp = divmod(i, 4)
        diag = comp == (vec + shift) % 4
        if name == "identity":
            v = 1.0 if diag else 0.0
        elif name == "dense":
            v = 0.25 + (0.5 if diag else 0.0)
        elif name == "hash":
            v = 0.1 + 0.9 * hash01(i, seed)
        elif name == "small":
            v = 0.02 + 0.18 * hash01(i, seed + 3)
        elif name == "half":
            v = 0.5 if comp != 3 else 1.0
        elif name == "signed":
            v = hash01(i, seed + 7) - 0.5
        else:
            raise ValueError(f"unknown profile {profile}")
        vals.append(v)
    return struct.pack(f"<{n}f", *vals)


def mesh(locations, grid=GRID):
    """Grid of grid x grid cells. Attribute with the smallest location = position, all others gradients in [0, 1].
    Returns (vertex bytes, stride, indices)."""
    locs = sorted(locations)
    verts = []
    for gy in range(grid + 1):
        for gx in range(grid + 1):
            u, v = gx / grid, gy / grid
            for j, loc in enumerate(locs):
                if j == 0:
                    verts += [0.9 * (2 * u - 1), 0.9 * (2 * v - 1), 0.25 + 0.5 * u * v, 1.0]
                else:
                    k = hash01(loc, 3)
                    verts += [u, v, 0.25 + 0.5 * k, 1.0 - 0.5 * ((gx + gy) % 2) * 0.0]
    idx = []
    for gy in range(grid):
        for gx in range(grid):
            a = gy * (grid + 1) + gx
            b, c, d = a + 1, a + grid + 1, a + grid + 2
            idx += [a, b, c, b, d, c]
    return struct.pack(f"<{len(verts)}f", *verts), 16 * max(len(locs), 1), idx


def texture_spec(key):
    """Synthetic texture for a (texture word, sampler word) key: checkerboard (with alternating alpha) or
    gradient, colors from the hash. The alpha varies because many shaders (text, masks) read only the alpha channel."""
    tex_off = key[0] if key else 0
    n = (tex_off - TEXTURE_TABLE_BASE) // 8 if tex_off >= TEXTURE_TABLE_BASE else tex_off
    h = [hash01(n, s) for s in range(8)]
    if n % 3 == 1:
        return {"kind": "gradient", "size": 64}
    a_hi, a_lo = (1.0, 0.15) if n % 3 == 0 else (0.9, 0.55)
    return {"kind": "checker", "size": 64, "cells": 4 * (1 + n % 4),
            "colorA": [0.55 + 0.45 * h[0], 0.55 + 0.45 * h[1], 0.55 + 0.45 * h[2], a_hi],
            "colorB": [0.45 * h[3], 0.45 * h[4], 0.45 * h[5], a_lo]}


# --------------------------------------------------------------------------- Choosing the pairs
def pick_pairs(mapping, prog_blob, have_spv, have_blob, count=None, seed=0):
    """Pairs (cache entry, vertex blob, fragment blob) that occur in both sources.

    Per cache entry the first candidate pair with the same keyword set. Without count all; with count alternating
    across the shaders (deterministically shuffled), so one shader with thousands of variants does not fill the sample."""
    out = []
    seen = set()
    for e in mapping["cacheEntries"]:
        if e.get("status") != "full":
            continue
        idx = e["index"]
        if not (have_spv(idx, "vert") and have_spv(idx, "frag")):
            continue
        for c in e.get("candidates", []):
            if not c.get("pairs"):
                continue
            vp, fp = c["pairs"][0]
            vh, fh = prog_blob[vp], prog_blob[fp]
            if not vh or not fh or not have_blob(vh) or not have_blob(fh):
                continue
            if (vh, fh) in seen:
                break
            seen.add((vh, fh))
            out.append({"index": idx, "shader": c["shader"], "vs": vh, "fs": fh, "bundle": c.get("bundle", "")})
            break
    if count is None:
        return out
    groups = {}
    for p in out:
        groups.setdefault(p["shader"], []).append(p)
    names = sorted(groups)
    for n in names:
        groups[n].sort(key=lambda p: _mix(p["index"], seed))
    picked = []
    rnd = 0
    while len(picked) < count and any(len(groups[n]) > rnd for n in names):
        for n in names:
            if len(groups[n]) > rnd and len(picked) < count:
                picked.append(groups[n][rnd])
        rnd += 1
    return sorted(picked, key=lambda p: p["index"])


# --------------------------------------------------------------------------- Calling the tools
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def find_spirv_cross():
    for c in [os.environ.get("SPIRV_CROSS"), "/opt/homebrew/bin/spirv-cross", "/usr/local/bin/spirv-cross"]:
        if c and os.access(c, os.X_OK):
            return c
    for d in os.environ.get("PATH", "").split(":"):
        if os.access(f"{d}/spirv-cross", os.X_OK):
            return f"{d}/spirv-cross"
    raise SystemExit("spirv-cross not found (SPIRV_CROSS=<path>)")


def cbuf_file(stage_short, k, profile):
    """File name of the cbuf contents. Cbuf 1 (compiler constants) comes from the blob and applies to all profiles."""
    return f"cb_{stage_short}_1.bin" if k == 1 else f"cb_{stage_short}_{k}_{profile}.bin"


def translate_ours(blob_path, stage, out_msl, out_info, vs_out_mask=None, cbuf1=None, extra=()):
    cmd = [str(TRANSLATOR), "--stage", stage, str(blob_path), "-o", str(out_msl), "--info", str(out_info), *extra]
    if cbuf1:
        cmd += ["--cbuf1", str(cbuf1)]
    if vs_out_mask:
        cmd += ["--vs-out-mask", f"{vs_out_mask:x}"]
    r = run(cmd)
    if r.returncode != 0:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "translation failed"
    return json.loads(Path(out_info).read_text()), None


def ref_msl(spv_path, out_msl):
    r = run([find_spirv_cross(), str(spv_path), "--msl", "--msl-version", "20300"])
    if r.returncode != 0:
        return None, r.stderr.strip()[:200]
    Path(out_msl).write_text(r.stdout)
    return r.stdout, None


# --------------------------------------------------------------------------- Spec and rendering
def side_resources(kind, stage, info, ref):
    """Bindings of one side ('ours' from the resource map JSON, 'ref' from the reference MSL).
    Returns {'cbufs': {slot: cbuf_index}, 'textures': [{'slot', 'sampler_slot', 'key'}], 'support_slot': int|None}."""
    if kind == "ours":
        cbufs = {c["metalBuffer"]: c["index"] for c in info["constantBuffers"]}
        tex = []
        for t in info["textures"]:
            key = (t["textureWordOffset"], t.get("samplerWordOffset", -1)) if t.get("bindless") else (t["handleOffset"], -1)
            tex.append({"slot": t["metalTexture"], "sampler_slot": t["metalSampler"], "key": key})
        return {"cbufs": cbufs, "textures": tex, "support_slot": None}
    cbufs = {slot: k for (_, slot, kd, k) in ref["buffers"] if kd == "cbuf"}
    support = next((slot for (_, slot, kd, _) in ref["buffers"] if kd == "support"), None)
    tex = [{"slot": t["slot"], "sampler_slot": t["sampler_slot"], "key": t["key"]} for t in ref["textures"]]
    return {"cbufs": cbufs, "textures": tex, "support_slot": support}


def make_spec(d, vs_src, fs_src, vs_res, fs_res, locs, profile):
    """Spec dict for the harness. d: work folder of the pair (files relative to it)."""
    spec = {
        "size": [IMAGE_SIZE, IMAGE_SIZE], "clearColor": list(CLEAR),
        "vertex": {"msl": vs_src}, "fragment": {"msl": fs_src},
        "topology": "triangle", "indices": None, "indexType": "uint16",
        "vertexBuffers": [{"slot": VERTEX_BUFFER_SLOT, "file": "vertices.bin", "stride": 16 * max(len(locs), 1)}],
        "attributes": [{"location": loc, "buffer": VERTEX_BUFFER_SLOT, "offset": 16 * j, "format": "float4"}
                       for j, loc in enumerate(sorted(locs))],
        "buffers": [], "textures": [], "state": {"cull": "none"},
    }
    for stage_name, res in (("vertex", vs_res), ("fragment", fs_res)):
        short = "vs" if stage_name == "vertex" else "fs"
        for slot, k in sorted(res["cbufs"].items()):
            spec["buffers"].append({"stage": stage_name, "slot": slot, "size": CBUF_BYTES, "file": cbuf_file(short, k, profile)})
        if res["support_slot"] is not None:
            spec["buffers"].append({"stage": stage_name, "slot": res["support_slot"], "size": 1344, "file": "support.bin"})
        for t in res["textures"]:
            spec["textures"].append({"stage": stage_name, "slot": t["slot"], "samplerSlot": t["sampler_slot"],
                                     "generate": texture_spec(t["key"]), "mipmaps": True,
                                     "sampler": {"min": "linear", "mag": "linear", "mip": "linear", "address": "repeat"}})
    return spec


def harness_render(spec, spec_path, png_path, timeout=120):
    Path(spec_path).write_text(json.dumps(spec))
    r = run([str(HARNESS), "render", str(spec_path), "--out", str(png_path)], timeout=timeout)
    if r.returncode != 0:
        return None, (r.stderr.strip() or r.stdout.strip()).splitlines()[-1][:300] if (r.stderr or r.stdout).strip() else f"Exit {r.returncode}"
    return r.stdout, None


def image_stats(img):
    w, h, px = img
    clear = bytes(min(255, max(0, round(c * 255))) for c in CLEAR)
    covered = 0
    colors = set()
    for p in range(w * h):
        o = p * 4
        if bytes(px[o:o + 4]) != clear:
            covered += 1
            if len(colors) < 8:
                colors.add(bytes(px[o:o + 4]))
    return {"coverage": covered / (w * h), "distinctColors": len(colors)}


def classify(metrics):
    """passed / marginal / failed by the largest deviation per channel."""
    if metrics["max_abs_diff"] <= PASS_DIFF:
        return "passed"
    if metrics["max_abs_diff"] <= NEAR_DIFF:
        return "marginal"
    return "failed"


def jsonable(m):
    return {k: (None if isinstance(v, float) and math.isinf(v) else v) for k, v in m.items()}


def attr_locations(ref_vs, info_vs):
    return sorted({loc for loc, _ in ref_vs["attrs"]} | {i["location"] for i in info_vs["inputs"]})


def cleanup_pair_dir(d, keep_profile):
    """Deletes the cbuf files of the profiles not chosen (up to several MB per pair)."""
    for f in Path(d).glob("cb_*_*.bin"):
        if not f.name.endswith(f"_{keep_profile}.bin") and f.name not in ("cb_vs_1.bin", "cb_fs_1.bin"):
            f.unlink()


def run_pair(pair, outdir, imgdir):
    """Runs one pair and cleans up afterwards."""
    res = _run_pair(pair, outdir, imgdir)
    cleanup_pair_dir(Path(outdir) / str(pair["index"]), res.get("profile", "-"))
    return res


def _run_pair(pair, outdir, imgdir):
    """Runs one pair completely. Returns a result dict (always with 'status')."""
    idx = pair["index"]
    d = Path(outdir) / str(idx)
    d.mkdir(parents=True, exist_ok=True)
    res = {"index": idx, "shader": pair["shader"], "vs": pair["vs"], "fs": pair["fs"]}
    blobs = WORK / "blobs"
    spv = WORK / "spirv"
    # Reference
    ref = {}
    for st, name in (("vs", "vert"), ("fs", "frag")):
        text, err = ref_msl(spv / f"{idx}_{name}.spv", d / f"ref_{st}.metal")
        if err:
            return {**res, "status": "ref_error", "detail": err}
        try:
            ref[st] = parse_ref_msl(text)
        except ValueError as e:
            return {**res, "status": "ref_error", "detail": str(e)}
    unsup = ref["vs"]["unsupported"] + ref["fs"]["unsupported"]
    if unsup:
        return {**res, "status": "unsupported", "detail": "; ".join(sorted(set(unsup)))}
    # Translation
    info = {}
    info["vs"], err = translate_ours(blobs / f"{pair['vs']}.bin", "vs", d / "ours_vs.metal", d / "ours_vs.json", cbuf1=d / "cb_vs_1.bin")
    if err:
        return {**res, "status": "translation_failed", "detail": "vs: " + err}
    mask = int(info["vs"]["outMask"], 16)
    info["fs"], err = translate_ours(blobs / f"{pair['fs']}.bin", "fs", d / "ours_fs.metal", d / "ours_fs.json", mask, cbuf1=d / "cb_fs_1.bin")
    if err:
        return {**res, "status": "translation_failed", "detail": "fs: " + err}
    if info["vs"].get("usesGlobalMemory") or info["fs"].get("usesGlobalMemory"):
        return {**res, "status": "unsupported", "detail": "global memory"}
    locs = attr_locations(ref["vs"], info["vs"])
    vb, _stride, indices = mesh(locs)
    (d / "vertices.bin").write_bytes(vb)
    (d / "support.bin").write_bytes(struct.pack("<344f", *([0.0] * 17 + [1.0] * 73 + [0.0] * 254)))
    sides = {("ref", "vs"): side_resources("ref", "vs", None, ref["vs"]), ("ref", "fs"): side_resources("ref", "fs", None, ref["fs"]),
             ("ours", "vs"): side_resources("ours", "vs", info["vs"], None), ("ours", "fs"): side_resources("ours", "fs", info["fs"], None)}
    src = {("ref", "vs"): "ref_vs.metal", ("ref", "fs"): "ref_fs.metal", ("ours", "vs"): "ours_vs.metal", ("ours", "fs"): "ours_fs.metal"}
    imgdir = Path(imgdir)
    imgdir.mkdir(parents=True, exist_ok=True)

    def prepare(profile):  # constant buffer files of the profile (per stage and cbuf, shared by both sides)
        for (_kind, st), r in sides.items():
            for k in set(r["cbufs"].values()):
                f = d / cbuf_file(st, k, profile)
                if k != 1 and not f.exists():
                    f.write_bytes(cbuf_bytes(profile, seed=idx + k, k=k))

    def variant(name, vk, fk, profile):
        prepare(profile)
        spec = make_spec(d, src[(vk, "vs")], src[(fk, "fs")], sides[(vk, "vs")], sides[(fk, "fs")], locs, profile)
        spec["indices"] = indices
        png = imgdir / f"{idx}_{name}.png"
        _out, err = harness_render(spec, d / f"spec_{name}.json", png)
        if err:
            return None, err
        return sc.read_png(png), None

    # Render the reference; the first input profile with a meaningful image wins, otherwise the one with the largest coverage
    best = None
    for profile in PROFILES:
        img, err = variant("ref", "ref", "ref", profile)
        if err:
            return {**res, "status": "ref_render_error", "detail": err}
        stats = image_stats(img)
        good = stats["coverage"] >= MIN_COVERAGE and stats["distinctColors"] >= 2
        if best is None or (good, stats["coverage"]) > (best[0], best[1]["coverage"]):
            best = (good, stats, profile, img)
        if good:
            break
    ok, stats, profile, ref_img = best
    sc.write_png(imgdir / f"{idx}_ref.png", *ref_img)
    res.update({"profile": profile, "coverage": round(stats["coverage"], 4), "distinctColors": stats["distinctColors"],
                "textures": len(sides[("ref", "fs")]["textures"]) + len(sides[("ref", "vs")]["textures"])})
    if not ok:
        return {**res, "status": "not_meaningful",
                "detail": "reference image single-colored" if stats["coverage"] >= MIN_COVERAGE else "reference image almost empty (everything discarded/outside)"}
    ref_img = sc.read_png(imgdir / f"{idx}_ref.png")

    ours_img, err = variant("ours", "ours", "ours", profile)
    if err:
        return {**res, "status": "ours_render_error", "detail": err}
    m = sc.compare(ref_img, ours_img)
    res.update({"maxDiff": m["max_abs_diff"], "meanDiff": round(m["mean_abs_diff"], 5), "pixelsOver1": sc.compare(ref_img, ours_img, 1)["pixels_over"],
                "psnr": None if math.isinf(m["psnr"]) else round(m["psnr"], 2)})
    res["status"] = classify(m)
    if res["status"] != "passed":
        w, h, px = sc.diff_image(ref_img, ours_img, gain=8)
        sc.write_png(imgdir / f"{idx}_diff.png", w, h, px)
        # Ryujinx does not round to fp16 between two half-precision instructions (it removes the pack/unpack pair), the
        # hardware does. The --half-compat variant reproduces the Ryujinx behavior and separates this deviation.
        for st in ("vs", "fs"):
            _i, err = translate_ours(blobs / f"{pair[st]}.bin", st, d / f"oursc_{st}.metal", d / f"oursc_{st}.json",
                                     mask if st == "fs" else None, extra=("--half-compat",))
            if err:
                res["compat"] = {"error": err}
                break
            sides[("oursc", st)] = sides[("ours", st)]
            src[("oursc", st)] = f"oursc_{st}.metal"
        if "compat" not in res:
            cimg, err = variant("oursc", "oursc", "oursc", profile)
            if err:
                res["compat"] = {"error": err}
            else:
                cm = sc.compare(ref_img, cimg)
                res["compat"] = {"maxDiff": cm["max_abs_diff"], "pixelsOver1": sc.compare(ref_img, cimg, 1)["pixels_over"],
                                 "status": classify(cm)}
        mixed = {}
        for name, vk, fk in (("refvs_oursfs", "ref", "ours"), ("oursvs_reffs", "ours", "ref")):
            img, err = variant(name, vk, fk, profile)
            if err:
                mixed[name] = {"error": err}
            else:
                mm = sc.compare(ref_img, img)
                mixed[name] = {"maxDiff": mm["max_abs_diff"], "status": classify(mm)}
        res["mixed"] = mixed
        a, b = mixed["refvs_oursfs"].get("status"), mixed["oursvs_reffs"].get("status")
        res["stage"] = ("fragment" if a != "passed" and b == "passed" else
                        "vertex" if b != "passed" and a == "passed" else
                        "both" if a != "passed" and b != "passed" else "interplay")
    return res


# --------------------------------------------------------------------------- Commands
def cmd_index(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import shader_extract_blobs as eb
    import shader_inventory as si
    paths = list(si.BUNDLES) + list(si.EXTRA_SOURCES)
    out = []
    for _bundle, _shader, raw in eb.iter_bundle_programs(paths):
        try:
            p = eb.parse_program(raw)
            out.append(eb.blob_hash(p["blob"]) if p["stage"] else None)
        except ValueError:
            out.append(None)
    dst = WORK / "prog_blob.json"
    dst.write_text(json.dumps(out))
    print(f"{len(out)} programs, {sum(1 for h in out if h)} with blob -> {dst}")


def load_pairs(args):
    mapping = json.loads((WORK / "mapping.json").read_text())
    pb_path = WORK / "prog_blob.json"
    if not pb_path.exists():
        raise SystemExit(f"{pb_path} missing: first run `python3 scripts/shader_fidelity.py index` (needs PYTHONPATH=tools/pydeps)")
    prog_blob = json.loads(pb_path.read_text())
    have_spv = lambda i, st: (WORK / "spirv" / f"{i}_{st}.spv").exists()  # noqa: E731
    have_blob = lambda h: (WORK / "blobs" / f"{h}.bin").exists()  # noqa: E731
    pairs = pick_pairs(mapping, prog_blob, have_spv, have_blob, None if args.all or args.only else args.count, args.seed)
    if args.only:
        pairs = [p for p in pick_pairs(mapping, prog_blob, have_spv, have_blob) if p["index"] in set(args.only)]
    return pairs


def summarize(results):
    from collections import Counter
    c = Counter(r["status"] for r in results)
    valid = [r for r in results if r["status"] in ("passed", "marginal", "failed")]
    # with reproduced Ryujinx behavior for half precision: passed if exact or in the compatibility variant
    compat_ok = sum(1 for r in valid if r["status"] == "passed" or r.get("compat", {}).get("status") == "passed")
    return {"pairs": len(results), "byStatus": dict(c), "valid": len(valid),
            "passRate": round(c["passed"] / len(valid), 4) if valid else None,
            "withinNear": round((c["passed"] + c["marginal"]) / len(valid), 4) if valid else None,
            "passedOnlyWithHalfCompat": compat_ok - c["passed"],
            "passRateHalfCompat": round(compat_ok / len(valid), 4) if valid else None}


def cmd_run(args):
    for p, what in ((TRANSLATOR, "make -C shader_translator"), (HARNESS, "swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build")):
        if not p.exists():
            raise SystemExit(f"{p} missing: {what}")
    pairs = load_pairs(args)
    print(f"{len(pairs)} pairs", file=sys.stderr)
    outdir = WORK / "fidelity"
    imgdir = WORK / "out" / "fidelity"
    results = []

    def one(p):
        try:
            return run_pair(p, outdir, imgdir)
        except Exception as e:  # one broken pair must not end the run
            return {"index": p["index"], "shader": p["shader"], "status": "script_error", "detail": repr(e)[:200]}

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for i, r in enumerate(ex.map(one, pairs), 1):
            results.append(r)
            extra = f" max={r['maxDiff']}" if "maxDiff" in r else (f" {r.get('detail', '')[:60]}" if r["status"] != "passed" else "")
            print(f"[{i}/{len(pairs)}] {r['index']:5d} {r['shader'][:38]:38s} {r['status']}{extra}", flush=True)
    summary = summarize(results)
    report = Path(args.report)
    report.write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(json.dumps(summary, ensure_ascii=False))
    print(f"Report: {report}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="program ID -> blob hash (work/shaders/prog_blob.json)").set_defaults(fn=cmd_index)
    r = sub.add_parser("run", help="render and compare pairs")
    r.add_argument("--count", type=int, default=120, help="sample size (default 120)")
    r.add_argument("--all", action="store_true", help="all admissible pairs")
    r.add_argument("--only", type=int, nargs="*", help="only these cache indices")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--jobs", type=int, default=3)
    r.add_argument("--report", default=str(WORK / "fidelity_report.json"))
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
