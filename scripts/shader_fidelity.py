#!/usr/bin/env python3
"""Numerischer Treue-Test: Maxwell->MSL-Uebersetzung (maxwell2msl) gegen die Ryujinx-Referenz (SPIR-V -> MSL).

Fuer Programmpaare (Vertex + Fragment), die in BEIDEN Quellen vorkommen (Bundle-Blob und Ryujinx-SPIR-V, Zuordnung
ueber work/shaders/mapping.json), werden aus der Schnittstelle des Referenz-Shaders deterministische Eingaben
erzeugt (Vertexattribute, Konstantenpuffer, synthetische Texturen). Das Harness (scripts/shader_harness) rendert
(a) die Referenz und (b) unsere Uebersetzung mit identischem Zustand; scripts/shader_compare.py vergleicht die Bilder.
Bei Abweichungen werden zwei Mischvarianten gerendert (Referenz-VS + unser FS, unser VS + Referenz-FS), die den
Fehler auf eine Stufe eingrenzen.

Aufruf (aus dem Repo-Wurzelverzeichnis, alle Daten lokal unter work/shaders/):
  python3 scripts/shader_fidelity.py index                    # Programm -> Blob-Hash (braucht UnityPy, einmalig)
  python3 scripts/shader_fidelity.py run --count 120          # Stichprobe (je Shader abwechselnd)
  python3 scripts/shader_fidelity.py run --all --jobs 4       # alle zulaessigen Paare
  python3 scripts/shader_fidelity.py run --only 1 2 100       # bestimmte Cache-Indizes

Schwellen (begruendet in docs/shaders.md): bestanden = max. Abweichung <= 1 Stufe je Kanal (1/255, die
Rundungsgrenze von rgba8Unorm); "knapp" = <= 3; sonst durchgefallen. Ergebnis: work/shaders/fidelity_report.json,
Bilder unter work/shaders/out/fidelity/ (nicht im Repo).
Nur Standardbibliothek (index zusaetzlich UnityPy).
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
VERTEX_BUFFER_SLOT = 30      # wie in den Harness-Beispielen: ausserhalb der Cbuf-Slots
CBUF_BYTES = 65536           # die Ryujinx-Module deklarieren float4[4096]
GRID = 12                    # Gitter 12x12 Zellen
CLEAR = (0.25, 0.5, 0.75, 0.5)
PASS_DIFF = 1                # 1/255 je Kanal
NEAR_DIFF = 3
MIN_COVERAGE = 0.02          # Anteil Pixel, die von der Clear-Farbe abweichen, damit das Bild aussagekraeftig ist
PROFILES = ("identity", "dense", "hash", "signed", "small", "half", "identity@1", "identity@2", "identity@3", "dense@1", "dense@2",
            "dense@3", "identity%1", "identity%2", "identity%3", "identity%4", "identity%5", "identity%6", "dense%1", "dense%2",
            "dense%3", "dense%4", "hash#1", "signed#1", "small#1", "hash#2", "signed#2", "small#2", "hash#3", "signed#3",
            "hash#4", "signed#4", "hash#5", "signed#5", "identity%7", "identity%8", "identity%9", "identity%10", "dense%5",
            "dense%6", "dense%7", "dense%8")
TEXTURE_TABLE_BASE = 0x568   # siehe maxwell2msl --info (Annahme: Handle-Tabelle in cbuf 2)


# --------------------------------------------------------------------------- Referenz-MSL lesen
def split_params(sig):
    """Teilt die Parameterliste einer MSL-Funktion an Kommas ausserhalb von <...>."""
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
    """Ryujinx-Name einer bindlosen Textur -> (Texturwort-Offset, Samplerwort-Offset) in Bytes, oder None.

    Beispiel: fp_tex_cb196610_1056805A -> (0x568, 0x168). Die obere Haelfte des Hexwerts traegt den Wortindex des
    Texturworts (0x10568 -> 0x568), die unteren 12 Bit den Wortindex des Samplerworts (0x5A * 4 = 0x168)."""
    m = TEX_NAME_RE.search(name)
    if not m:
        return None
    v = int(m.group(2), 16)
    return ((v >> 12) & 0xFFFF, (v & 0xFFF) * 4)


def parse_ref_msl(text):
    """Liest die Schnittstelle des Einstiegspunkts main0 aus dem spirv-cross-MSL.

    Liefert {'stage', 'attrs': [(loc, typ)], 'buffers': [(name, slot, kind, index)], 'textures': [...], 'unsupported': [...]}.
    kind eines Puffers: 'cbuf' (name vp_c<k>/fp_c<k>), 'support' (support_buffer) oder 'other'."""
    m = re.search(r"^(vertex|fragment)\s+[\w:<>]+\s+main0\((.*?)\)\s*$", text, re.M)
    if not m:
        raise ValueError("main0 nicht gefunden")
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


# --------------------------------------------------------------------------- deterministische Eingaben
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
    """'name', 'name@shift' (Matrixraster um shift vec4 verschoben), 'name%n' (Verschiebung je Cbuf aus einem Hash),
    'name#seed' oder Kombinationen -> (name, shift, seed, per_cbuf_variant)."""
    m = re.match(r"^([a-z]+)(?:@(\d+))?(?:%(\d+))?(?:#(\d+))?$", profile)
    if not m:
        raise ValueError(f"unbekanntes Profil {profile}")
    return m.group(1), int(m.group(2) or 0), int(m.group(4) or 0), int(m.group(3) or 0)


def cbuf_bytes(profile, size=CBUF_BYTES, seed=1, k=0):
    """Konstantenpuffer-Inhalt (little-endian float32). Profile:
    identity: je vier aufeinanderfolgende vec4 eine Einheitsmatrix (Matrizen werden zur Identitaet),
    dense: 0.25 plus 0.5 auf der Diagonalen, hash: Zufall in [0.1, 1], signed: Zufall in [-0.5, 0.5],
    small: Zufall in [0.02, 0.2], half: 0.5 (w = 1).
    '@s' verschiebt das Matrixraster um s vec4 (Matrizen, die nicht auf 64 Byte beginnen), '%n' verschiebt es je
    Cbuf-Index k verschieden, '#s' aendert den Zufall."""
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
            raise ValueError(f"unbekanntes Profil {profile}")
        vals.append(v)
    return struct.pack(f"<{n}f", *vals)


def mesh(locations, grid=GRID):
    """Gitter aus grid x grid Zellen. Attribut mit der kleinsten Location = Position, alle anderen Verlaeufe in [0, 1].
    Liefert (vertexbytes, stride, indices)."""
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
    """Synthetische Textur zu einem (Texturwort, Samplerwort)-Schluessel: Schachbrett (mit wechselndem Alpha) oder
    Verlauf, Farben aus dem Hash. Das Alpha variiert, weil viele Shader (Schrift, Masken) nur den Alphakanal lesen."""
    tex_off = key[0] if key else 0
    n = (tex_off - TEXTURE_TABLE_BASE) // 8 if tex_off >= TEXTURE_TABLE_BASE else tex_off
    h = [hash01(n, s) for s in range(8)]
    if n % 3 == 1:
        return {"kind": "gradient", "size": 64}
    a_hi, a_lo = (1.0, 0.15) if n % 3 == 0 else (0.9, 0.55)
    return {"kind": "checker", "size": 64, "cells": 4 * (1 + n % 4),
            "colorA": [0.55 + 0.45 * h[0], 0.55 + 0.45 * h[1], 0.55 + 0.45 * h[2], a_hi],
            "colorB": [0.45 * h[3], 0.45 * h[4], 0.45 * h[5], a_lo]}


# --------------------------------------------------------------------------- Auswahl der Paare
def pick_pairs(mapping, prog_blob, have_spv, have_blob, count=None, seed=0):
    """Paare (Cache-Eintrag, Vertex-Blob, Fragment-Blob), die in beiden Quellen vorkommen.

    Je Cache-Eintrag das erste Kandidatenpaar mit gleicher Keyword-Menge. Ohne count alle; mit count abwechselnd
    ueber die Shader (deterministisch gemischt), damit nicht ein Shader mit tausenden Varianten die Stichprobe fuellt."""
    out = []
    seen = set()
    for e in mapping["cacheEntries"]:
        if e.get("status") != "voll":
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


# --------------------------------------------------------------------------- Werkzeuge aufrufen
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def find_spirv_cross():
    for c in [os.environ.get("SPIRV_CROSS"), "/opt/homebrew/bin/spirv-cross", "/usr/local/bin/spirv-cross"]:
        if c and os.access(c, os.X_OK):
            return c
    for d in os.environ.get("PATH", "").split(":"):
        if os.access(f"{d}/spirv-cross", os.X_OK):
            return f"{d}/spirv-cross"
    raise SystemExit("spirv-cross nicht gefunden (SPIRV_CROSS=<Pfad>)")


def cbuf_file(stage_short, k, profile):
    """Dateiname des Cbuf-Inhalts. Cbuf 1 (Compiler-Konstanten) kommt aus dem Blob und gilt fuer alle Profile."""
    return f"cb_{stage_short}_1.bin" if k == 1 else f"cb_{stage_short}_{k}_{profile}.bin"


def translate_ours(blob_path, stage, out_msl, out_info, vs_out_mask=None, cbuf1=None, extra=()):
    cmd = [str(TRANSLATOR), "--stage", stage, str(blob_path), "-o", str(out_msl), "--info", str(out_info), *extra]
    if cbuf1:
        cmd += ["--cbuf1", str(cbuf1)]
    if vs_out_mask:
        cmd += ["--vs-out-mask", f"{vs_out_mask:x}"]
    r = run(cmd)
    if r.returncode != 0:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "Uebersetzung fehlgeschlagen"
    return json.loads(Path(out_info).read_text()), None


def ref_msl(spv_path, out_msl):
    r = run([find_spirv_cross(), str(spv_path), "--msl", "--msl-version", "20300"])
    if r.returncode != 0:
        return None, r.stderr.strip()[:200]
    Path(out_msl).write_text(r.stdout)
    return r.stdout, None


# --------------------------------------------------------------------------- Spec und Rendern
def side_resources(kind, stage, info, ref):
    """Bindings einer Seite ('ours' aus dem Resource-Map-JSON, 'ref' aus dem Referenz-MSL).
    Liefert {'cbufs': {slot: cbuf_index}, 'textures': [{'slot', 'sampler_slot', 'key'}], 'support_slot': int|None}."""
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
    """Spec-Dict fuer das Harness. d: Arbeitsordner des Paars (Dateien relativ zu ihm)."""
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
    """bestanden / knapp / durchgefallen nach der groessten Abweichung je Kanal."""
    if metrics["max_abs_diff"] <= PASS_DIFF:
        return "bestanden"
    if metrics["max_abs_diff"] <= NEAR_DIFF:
        return "knapp"
    return "durchgefallen"


def jsonable(m):
    return {k: (None if isinstance(v, float) and math.isinf(v) else v) for k, v in m.items()}


def attr_locations(ref_vs, info_vs):
    return sorted({loc for loc, _ in ref_vs["attrs"]} | {i["location"] for i in info_vs["inputs"]})


def cleanup_pair_dir(d, keep_profile):
    """Loescht die Cbuf-Dateien der nicht gewaehlten Profile (je Paar bis zu mehrere MB)."""
    for f in Path(d).glob("cb_*_*.bin"):
        if not f.name.endswith(f"_{keep_profile}.bin") and f.name not in ("cb_vs_1.bin", "cb_fs_1.bin"):
            f.unlink()


def run_pair(pair, outdir, imgdir):
    """Fuehrt ein Paar aus und raeumt danach auf."""
    res = _run_pair(pair, outdir, imgdir)
    cleanup_pair_dir(Path(outdir) / str(pair["index"]), res.get("profile", "-"))
    return res


def _run_pair(pair, outdir, imgdir):
    """Fuehrt ein Paar komplett aus. Liefert ein Ergebnis-Dict (immer mit 'status')."""
    idx = pair["index"]
    d = Path(outdir) / str(idx)
    d.mkdir(parents=True, exist_ok=True)
    res = {"index": idx, "shader": pair["shader"], "vs": pair["vs"], "fs": pair["fs"]}
    blobs = WORK / "blobs"
    spv = WORK / "spirv"
    # Referenz
    ref = {}
    for st, name in (("vs", "vert"), ("fs", "frag")):
        text, err = ref_msl(spv / f"{idx}_{name}.spv", d / f"ref_{st}.metal")
        if err:
            return {**res, "status": "ref_fehler", "detail": err}
        try:
            ref[st] = parse_ref_msl(text)
        except ValueError as e:
            return {**res, "status": "ref_fehler", "detail": str(e)}
    unsup = ref["vs"]["unsupported"] + ref["fs"]["unsupported"]
    if unsup:
        return {**res, "status": "nicht_unterstuetzt", "detail": "; ".join(sorted(set(unsup)))}
    # Uebersetzung
    info = {}
    info["vs"], err = translate_ours(blobs / f"{pair['vs']}.bin", "vs", d / "ours_vs.metal", d / "ours_vs.json", cbuf1=d / "cb_vs_1.bin")
    if err:
        return {**res, "status": "uebersetzung_fehlt", "detail": "vs: " + err}
    mask = int(info["vs"]["outMask"], 16)
    info["fs"], err = translate_ours(blobs / f"{pair['fs']}.bin", "fs", d / "ours_fs.metal", d / "ours_fs.json", mask, cbuf1=d / "cb_fs_1.bin")
    if err:
        return {**res, "status": "uebersetzung_fehlt", "detail": "fs: " + err}
    if info["vs"].get("usesGlobalMemory") or info["fs"].get("usesGlobalMemory"):
        return {**res, "status": "nicht_unterstuetzt", "detail": "globaler Speicher"}
    locs = attr_locations(ref["vs"], info["vs"])
    vb, _stride, indices = mesh(locs)
    (d / "vertices.bin").write_bytes(vb)
    (d / "support.bin").write_bytes(struct.pack("<344f", *([0.0] * 17 + [1.0] * 73 + [0.0] * 254)))
    sides = {("ref", "vs"): side_resources("ref", "vs", None, ref["vs"]), ("ref", "fs"): side_resources("ref", "fs", None, ref["fs"]),
             ("ours", "vs"): side_resources("ours", "vs", info["vs"], None), ("ours", "fs"): side_resources("ours", "fs", info["fs"], None)}
    src = {("ref", "vs"): "ref_vs.metal", ("ref", "fs"): "ref_fs.metal", ("ours", "vs"): "ours_vs.metal", ("ours", "fs"): "ours_fs.metal"}
    imgdir = Path(imgdir)
    imgdir.mkdir(parents=True, exist_ok=True)

    def prepare(profile):  # Konstantenpuffer-Dateien des Profils (je Stufe und Cbuf, von beiden Seiten gemeinsam genutzt)
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

    # Referenz rendern; das erste Eingabeprofil mit aussagekraeftigem Bild gewinnt, sonst das mit der groessten Abdeckung
    best = None
    for profile in PROFILES:
        img, err = variant("ref", "ref", "ref", profile)
        if err:
            return {**res, "status": "ref_render_fehler", "detail": err}
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
        return {**res, "status": "nicht_aussagekraeftig",
                "detail": "Referenzbild einfarbig" if stats["coverage"] >= MIN_COVERAGE else "Referenzbild fast leer (alles verworfen/ausserhalb)"}
    ref_img = sc.read_png(imgdir / f"{idx}_ref.png")

    ours_img, err = variant("ours", "ours", "ours", profile)
    if err:
        return {**res, "status": "ours_render_fehler", "detail": err}
    m = sc.compare(ref_img, ours_img)
    res.update({"maxDiff": m["max_abs_diff"], "meanDiff": round(m["mean_abs_diff"], 5), "pixelsOver1": sc.compare(ref_img, ours_img, 1)["pixels_over"],
                "psnr": None if math.isinf(m["psnr"]) else round(m["psnr"], 2)})
    res["status"] = classify(m)
    if res["status"] != "bestanden":
        w, h, px = sc.diff_image(ref_img, ours_img, gain=8)
        sc.write_png(imgdir / f"{idx}_diff.png", w, h, px)
        # Ryujinx rundet zwischen zwei Halbpraezisions-Befehlen nicht auf fp16 (es entfernt das Pack/Unpack-Paar), die
        # Hardware schon. Die Variante --half-compat bildet das Ryujinx-Verhalten nach und trennt diese Abweichung ab.
        for st in ("vs", "fs"):
            _i, err = translate_ours(blobs / f"{pair[st]}.bin", st, d / f"oursc_{st}.metal", d / f"oursc_{st}.json",
                                     mask if st == "fs" else None, extra=("--half-compat",))
            if err:
                res["compat"] = {"fehler": err}
                break
            sides[("oursc", st)] = sides[("ours", st)]
            src[("oursc", st)] = f"oursc_{st}.metal"
        if "compat" not in res:
            cimg, err = variant("oursc", "oursc", "oursc", profile)
            if err:
                res["compat"] = {"fehler": err}
            else:
                cm = sc.compare(ref_img, cimg)
                res["compat"] = {"maxDiff": cm["max_abs_diff"], "pixelsOver1": sc.compare(ref_img, cimg, 1)["pixels_over"],
                                 "status": classify(cm)}
        mixed = {}
        for name, vk, fk in (("refvs_oursfs", "ref", "ours"), ("oursvs_reffs", "ours", "ref")):
            img, err = variant(name, vk, fk, profile)
            if err:
                mixed[name] = {"fehler": err}
            else:
                mm = sc.compare(ref_img, img)
                mixed[name] = {"maxDiff": mm["max_abs_diff"], "status": classify(mm)}
        res["mixed"] = mixed
        a, b = mixed["refvs_oursfs"].get("status"), mixed["oursvs_reffs"].get("status")
        res["stufe"] = ("fragment" if a != "bestanden" and b == "bestanden" else
                        "vertex" if b != "bestanden" and a == "bestanden" else
                        "beide" if a != "bestanden" and b != "bestanden" else "zusammenspiel")
    return res


# --------------------------------------------------------------------------- Kommandos
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
    print(f"{len(out)} Programme, {sum(1 for h in out if h)} mit Blob -> {dst}")


def load_pairs(args):
    mapping = json.loads((WORK / "mapping.json").read_text())
    pb_path = WORK / "prog_blob.json"
    if not pb_path.exists():
        raise SystemExit(f"{pb_path} fehlt: erst `python3 scripts/shader_fidelity.py index` (braucht PYTHONPATH=tools/pydeps)")
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
    valid = [r for r in results if r["status"] in ("bestanden", "knapp", "durchgefallen")]
    # mit nachgebildetem Ryujinx-Verhalten bei Halbpraezision: bestanden, wenn exakt oder in der Kompatibilitaetsvariante
    compat_ok = sum(1 for r in valid if r["status"] == "bestanden" or r.get("compat", {}).get("status") == "bestanden")
    return {"pairs": len(results), "byStatus": dict(c), "valid": len(valid),
            "passRate": round(c["bestanden"] / len(valid), 4) if valid else None,
            "withinNear": round((c["bestanden"] + c["knapp"]) / len(valid), 4) if valid else None,
            "passedOnlyWithHalfCompat": compat_ok - c["bestanden"],
            "passRateHalfCompat": round(compat_ok / len(valid), 4) if valid else None}


def cmd_run(args):
    for p, what in ((TRANSLATOR, "make -C shader_translator"), (HARNESS, "swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build")):
        if not p.exists():
            raise SystemExit(f"{p} fehlt: {what}")
    pairs = load_pairs(args)
    print(f"{len(pairs)} Paare", file=sys.stderr)
    outdir = WORK / "fidelity"
    imgdir = WORK / "out" / "fidelity"
    results = []

    def one(p):
        try:
            return run_pair(p, outdir, imgdir)
        except Exception as e:  # ein defektes Paar darf den Lauf nicht beenden
            return {"index": p["index"], "shader": p["shader"], "status": "skriptfehler", "detail": repr(e)[:200]}

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for i, r in enumerate(ex.map(one, pairs), 1):
            results.append(r)
            extra = f" max={r['maxDiff']}" if "maxDiff" in r else (f" {r.get('detail', '')[:60]}" if r["status"] != "bestanden" else "")
            print(f"[{i}/{len(pairs)}] {r['index']:5d} {r['shader'][:38]:38s} {r['status']}{extra}", flush=True)
    summary = summarize(results)
    report = Path(args.report)
    report.write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(json.dumps(summary, ensure_ascii=False))
    print(f"Bericht: {report}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="Programm-ID -> Blob-Hash (work/shaders/prog_blob.json)").set_defaults(fn=cmd_index)
    r = sub.add_parser("run", help="Paare rendern und vergleichen")
    r.add_argument("--count", type=int, default=120, help="Stichprobengroesse (Standard 120)")
    r.add_argument("--all", action="store_true", help="alle zulaessigen Paare")
    r.add_argument("--only", type=int, nargs="*", help="nur diese Cache-Indizes")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--jobs", type=int, default=3)
    r.add_argument("--report", default=str(WORK / "fidelity_report.json"))
    r.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
