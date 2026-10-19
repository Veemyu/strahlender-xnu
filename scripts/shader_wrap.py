#!/usr/bin/env python3
"""ShaderLab-Wrapper-Generator: Maxwell-Blobs (als HLSL uebersetzt) -> Unity-.shader-Datei.

Eigener Code des strahlender-xnu-Projekts. Eingaben (alle lokal unter work/shaders/, nicht im Repo):
  inventory.json   Properties, Tags, Render-States, Parameter-Layouts je Pass und Stufe (scripts/shader_inventory.py)
  mapping.json     (optional) Programm-Id je (Bundle, Shader, SubShader, Pass, Stufe, SubProgram); ohne die Datei zaehlt
                   das Inventar die Programme in derselben Reihenfolge auf
  prog_blob.json   Programm-Id -> Blob-Hash (scripts/shader_fidelity.py index)
  blobs/<hash>.bin Maxwell-Blobs (scripts/shader_extract_blobs.py)
und das Werkzeug shader_translator/build/maxwell2msl (--lang hlsl).

Ausgabe: <name>.shader (ein SubShader, eine feste Keyword-Variante je Pass) und <name>.wrap.json (Zuordnungen
fuer Tests und die Massenfertigung). Ohne --also steht ein Pass im Shader; davor steht der GrabPass des Originals
(Inventar-Pass vom Typ Grab, z. B. _BackgroundTexture beim Wasser) und dahinter ein UsePass (z. B. der Legacy-Schattenwurf
der Mitake-Shader), beides in Originalreihenfolge. --also PASS[:KW,KW] setzt weitere Normal-Paesse (typisch den
SHADOWCASTER-Pass) in denselben SubShader: Unity nimmt den Schattenwurf aus dem Shader des Materials. Die Abbildung der
Hardware-Konstantenpuffer ist in docs/shader-unity-integration.md beschrieben:
  cbuf 0  Treiberdaten              -> Nullen (static uint4-Feld)
  cbuf 1  Compiler-Konstanten       -> static const uint4-Feld mit den Bytes hinter dem Code des Blobs
  cbuf 2  Handle-Tabellen           -> Nullen (die Werte werden nie benutzt; Texturen laufen ueber Namen)
  cbuf 3+ Unity-Block, Bindung k-3  -> Modus "named": je Wort der Wert des Unity-Uniforms, das dort liegt
                                       (Namen/Offsets aus constantBuffers des Inventars); Modus "array": ein
                                       float4-Feld mxav_cb<k> / mxaf_cb<k>, das ein Test exakt fuellt
"""
import argparse
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "work" / "shaders"
TRANSLATOR = REPO / "shader_translator" / "build" / "maxwell2msl"

# Unity VertexAttribute (inputChannels[].source) -> HLSL-Semantik
CHANNEL_SEMANTIC = {0: "POSITION", 1: "NORMAL", 2: "TANGENT", 3: "COLOR"}
for _i in range(8):
    CHANNEL_SEMANTIC[4 + _i] = f"TEXCOORD{_i}"

TEX_HLSL = {"2D": "Texture2D<float4>", "3D": "Texture3D<float4>", "Cube": "TextureCube<float4>",
            "2DArray": "Texture2DArray<float4>", "CubeArray": "TextureCubeArray<float4>"}
TEX_HLSL_SHADOW = {"2D": "Texture2D<float>", "Cube": "TextureCube<float>", "2DArray": "Texture2DArray<float>",
                   "CubeArray": "TextureCubeArray<float>"}
TYPENAME_DIM = {"1d": "1D", "2d": "2D", "3d": "3D", "cube": "Cube", "2d_array": "2DArray", "cube_array": "CubeArray",
                "1d_array": "1DArray"}
PROP_FLAGS = [(1, "HideInInspector"), (2, "PerRendererData"), (4, "NoScaleOffset"), (8, "Normal"), (16, "HDR"),
              (32, "Gamma")]
COLMASK_BITS = [(8, "R"), (4, "G"), (2, "B"), (1, "A")]
ZTEST = {"Disabled": "Always", "Never": "Never", "Less": "Less", "Equal": "Equal", "LEqual": "LEqual",
         "Greater": "Greater", "NotEqual": "NotEqual", "GEqual": "GEqual", "Always": "Always"}


class WrapError(Exception):
    pass


# Exakte Arithmetik im Unity-Metal-Pfad (docs/shader-unity-integration.md, Abschnitt Mathematische Treue):
# disable_fastmath schaltet Metals Fast-Math (FMA-Verschmelzung, Naeherungen fuer Division/sin/cos) ab,
# skip_optimizations verhindert, dass FXC a*b+c zu einem mad (spaeter fma) verschmilzt und isnan() wegfaltet.
EXACT_PRAGMAS = ("disable_fastmath", "skip_optimizations metal")


# --------------------------------------------------------------------------- Inventar
def ident(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def find_shader(inv, name, bundle=None):
    cands = [s for s in inv.get("shaders", []) + inv.get("extraShaders", [])
             if s["name"] == name and (bundle is None or s.get("bundle") == bundle)]
    if not cands:
        raise WrapError(f"Shader '{name}' nicht im Inventar")
    if len(cands) > 1:
        raise WrapError(f"Shader '{name}' mehrfach ({', '.join(sorted({c.get('bundle', '?') for c in cands}))}): --bundle angeben")
    return cands[0]


def select_entry(pass_, stage, keywords):
    """Stufeneintrag (Index = SubProgram) mit genau dieser Keyword-Menge (globale + lokale)."""
    want = set(keywords or [])
    found = []
    for i, e in enumerate(pass_["stages"].get(stage, [])):
        if set(e.get("globalKeywords", [])) | set(e.get("localKeywords", [])) == want:
            found.append((i, e))
    if not found:
        have = [sorted(set(e.get("globalKeywords", [])) | set(e.get("localKeywords", [])))
                for e in pass_["stages"].get(stage, [])]
        raise WrapError(f"keine {stage}-Variante mit Keywords {sorted(want)}; vorhanden: {have[:6]}")
    return found[0]


def program_index(mapping):
    out = {}
    for p in mapping["programs"]:
        out[(p["bundle"], p["shader"], p["subShader"], p["pass"], p["stage"], p["subProgram"])] = p["id"]
    return out


@functools.lru_cache(maxsize=None)
def program_index_cached(mapping_path):
    return program_index(load_json(mapping_path))


@functools.lru_cache(maxsize=None)
def program_index_from_inventory(inventory_path):
    """Programm-Id = Aufzaehlungsreihenfolge im Inventar (Shader, SubShader, Pass, Vertex vor Fragment, SubProgram);
    identisch zu mapping.json (an allen 14.342 Programmen geprueft), ohne den Ryujinx-Cache zu brauchen."""
    inv = load_json(inventory_path)
    out, pid = {}, 0
    for s in inv["shaders"] + inv.get("extraShaders", []):
        for si_, ss in enumerate(s["subShaders"]):
            for pi, p in enumerate(ss["passes"]):
                for st in ("vertex", "fragment"):
                    for k, _e in enumerate(p["stages"][st]):
                        out[(s.get("bundle"), s["name"], si_, pi, st, k)] = pid
                        pid += 1
    return out


# --------------------------------------------------------------------------- Layouts
def hlsl_member_type(m):
    n, kind = m["components"], m["kind"]
    if m["name"] in RAW_UINT_EXPRS and n == 1:
        return "uint"
    if kind == "matrix":
        if n == 16:
            base = "float4x4"
        elif n == 9:
            base = "float3x3"
        else:
            raise WrapError(f"Matrix mit {n} Komponenten ({m['name']}) nicht unterstuetzt")
    else:
        base = "float" if n == 1 else f"float{n}"
    return base


def declaration(m):
    arr = f"[{m['arraySize']}]" if m.get("arraySize") else ""
    return f"{hlsl_member_type(m)} {m['name']}{arr}"


def member_words(m):
    """Anzahl 4-Byte-Woerter, die das Mitglied im Block belegt (Arrayelemente beginnen auf 16 Byte)."""
    n, kind = m["components"], m["kind"]
    if kind == "matrix":
        per = 16 if n == 16 else 12  # float3x3: drei Zeilen zu 16 Byte
    elif m.get("arraySize"):
        per = 4
    else:
        per = n
    return per * max(m.get("arraySize", 0), 1)


def word_expr(m, e):
    """HLSL-Ausdruck (float) fuer das Wort e (ab dem Mitglied-Offset) oder None (Fuellbyte)."""
    n, kind, arr = m["components"], m["kind"], m.get("arraySize", 0)
    name = m["name"]
    comps = "xyzw"
    if kind == "matrix":
        per = 16 if n == 16 else 12
        idx, e = divmod(e, per)
        col, row = divmod(e, 4)  # Zeile des Blocks = Spalte der Matrix (spaltenweise Ablage, wie GLSL mat4)
        dim = 4 if n == 16 else 3
        if row >= dim or col >= dim:
            return None
        base = f"{name}[{idx}]" if arr else name
        return f"{base}[{row}][{col}]"
    if arr:
        idx, k = divmod(e, 4)
        if k >= n:
            return None
        base = f"{name}[{idx}]"
        return base if n == 1 else f"{base}.{comps[k]}"
    if e >= n:
        return None
    return name if n == 1 else f"{name}.{comps[e]}"


def block_layout(entry, binding):
    """(Name, Größe, Mitglieder) des Unity-Blocks mit dieser Bindungsnummer oder None."""
    names = [b["name"] for b in entry.get("cbBindings", []) if b["index"] == binding]
    if not names:
        return None
    for cb in entry.get("constantBuffers", []):
        if cb["name"] == names[0]:
            return cb
    return None


def rows_for_block(cb, rows):
    """Je Zeile vier Ausdruecke (str) oder None; rows = Anzahl der Zeilen (4 Woerter)."""
    cells = [[None] * 4 for _ in range(rows)]
    for m in cb["members"]:
        base = m["offset"] // 4
        for e in range(member_words(m)):
            w = base + e
            if w // 4 >= rows:
                break
            ex = word_expr(m, e)
            if ex is not None:
                cells[w // 4][w % 4] = ex
    return cells


def uint4_row(cells):
    parts = [c if c and c in RAW_UINT_EXPRS else (f"asuint({c})" if c else "0u") for c in cells]
    return f"uint4({', '.join(parts)})"


# Uniforms, die Unity als Ganzzahl schreibt (die Bits stehen unveraendert im Block)
RAW_UINT_EXPRS = {"unity_BaseInstanceID"}
INSTANCING_ARRAY_SIZE = 500  # UNITY_INSTANCED_ARRAY_SIZE des Built-in-Pfads (500 * 128 Byte < 64 KB)


def instancing_struct(cb):
    """Erste Struktur des Unity-Instancing-Blocks (z. B. unity_Builtins0Array) oder None."""
    structs = cb.get("structs") or []
    return structs[0] if structs else None


def instancing_decl(cb, st):
    """cbuffer-Text mit dem Strukturfeld; Luecken zwischen den Mitgliedern werden aufgefuellt (Schrittweite = structSize)."""
    mems, cur, pad = [], 0, 0

    def fill(upto):
        nonlocal cur, pad
        while cur < upto:
            n = min((upto - cur) // 4, 4 - (cur // 4) % 4)
            mems.append(f"float{'' if n == 1 else n} mx_pad{pad};")
            pad += 1
            cur += n * 4

    for m in st["members"]:
        fill(m["offset"])
        mems.append(f"{declaration(m)};")
        cur = m["offset"] + member_words(m) * 4
    fill(st["structSize"])
    body = " ".join(mems)
    return f"cbuffer {cb['name']} {{ struct {{ {body} }} {st['name']}[{INSTANCING_ARRAY_SIZE}]; }}"


def instancing_reader(fname, st):
    """HLSL-Funktion: Wort an Byte-Offset off des (Instanz-)Feldes, wie die Maxwell-Befehle es lesen."""
    lines = [f"uint {fname}(uint off)", "{",
             f"    uint e = min(off / {st['structSize']}u, {INSTANCING_ARRAY_SIZE - 1}u);",
             f"    switch ((off % {st['structSize']}u) >> 2)", "    {"]
    for m in st["members"]:
        mm = dict(m, name=f"{st['name']}[e].{m['name']}", arraySize=m.get("arraySize", 0))
        for e in range(member_words(m)):
            ex = word_expr(mm, e)
            if ex is not None:
                lines.append(f"        case {m['offset'] // 4 + e}: return asuint({ex});")
    lines += ["        default: return 0u;", "    }", "}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- Properties und Zustand
def fmt(v):
    r = repr(float(v))
    return r[:-2] if r.endswith(".0") else r


def property_lines(props):
    out = []
    for p in props:
        attrs = [f"[{n}]" for f, n in PROP_FLAGS if p.get("flags", 0) & f]
        attrs += [f"[{a}]" for a in p.get("attributes", [])]
        label = p.get("label", p["name"]).replace('"', "'")
        t = p["type"]
        if t == "Texture":
            dim = p.get("texDim", "2D")
            dim = "2D" if dim in ("None", "Any") else dim
            decl = f'{p["name"]} ("{label}", {dim}) = "{p.get("defaultTexture", "white")}" {{}}'
        elif t == "Color":
            d = p.get("default", [0, 0, 0, 0])
            decl = f'{p["name"]} ("{label}", Color) = ({", ".join(fmt(x) for x in d)})'
        elif t == "Vector":
            d = p.get("default", [0, 0, 0, 0])
            decl = f'{p["name"]} ("{label}", Vector) = ({", ".join(fmt(x) for x in d)})'
        elif t == "Range":
            d = p.get("default", [0, 0, 1])
            decl = f'{p["name"]} ("{label}", Range({fmt(d[1])}, {fmt(d[2])})) = {fmt(d[0])}'
        else:
            d = p.get("default", [0])
            decl = f'{p["name"]} ("{label}", Float) = {fmt(d[0])}'
        out.append("        " + " ".join(attrs + [decl]))
    return out


def _v(state, key, default=None):
    """Wert oder [Material-Eigenschaft]."""
    prop = state.get(key + "_prop")
    return f"[{prop}]" if prop else state.get(key, default)


def _num(v):
    return str(int(v)) if isinstance(v, (int, float)) else v


def render_state_lines(state):
    out = []
    rbs = state.get("rtBlend", [])
    for i, rb in enumerate(rbs[:8] if state.get("rtSeparateBlend") else rbs[:1]):
        idx = f"{i} " if state.get("rtSeparateBlend") else ""
        s, d = _v(rb, "srcBlend"), _v(rb, "destBlend")
        sa, da = _v(rb, "srcBlendAlpha"), _v(rb, "destBlendAlpha")
        has_prop = any(k.endswith("_prop") for k in rb)
        if has_prop or (s, d) != ("One", "Zero") or (sa, da) != ("One", "Zero"):
            out.append(f"Blend {idx}{s} {d}" + (f", {sa} {da}" if (sa, da) != (s, d) else ""))
        op, opa = _v(rb, "blendOp"), _v(rb, "blendOpAlpha")
        if has_prop or op != "Add" or opa != "Add":
            out.append(f"BlendOp {idx}{op}" + (f", {opa}" if opa != op else ""))
        cm = rb.get("colMask_prop")
        if cm:
            out.append(f"ColorMask [{cm}]" + (f" {i}" if state.get("rtSeparateBlend") else ""))
        elif rb.get("colMask", 15) != 15:
            letters = "".join(l for b, l in COLMASK_BITS if rb["colMask"] & b) or "0"
            out.append(f"ColorMask {letters}" + (f" {i}" if state.get("rtSeparateBlend") else ""))
    zt = state.get("zTest_prop")
    out.append(f"ZTest [{zt}]" if zt else f"ZTest {ZTEST.get(state.get('zTest', 'LEqual'), 'LEqual')}")
    zw = state.get("zWrite_prop")
    out.append(f"ZWrite [{zw}]" if zw else f"ZWrite {'On' if state.get('zWrite', 1) else 'Off'}")
    cp = state.get("culling_prop")
    out.append(f"Cull [{cp}]" if cp else f"Cull {state.get('culling', 'Back')}")
    if state.get("offsetFactor") or state.get("offsetUnits") or state.get("offsetFactor_prop") or state.get("offsetUnits_prop"):
        out.append(f"Offset {_v(state, 'offsetFactor', 0)}, {_v(state, 'offsetUnits', 0)}")
    if state.get("alphaToMask"):
        out.append("AlphaToMask On")
    if "zClip" in state and not state["zClip"]:
        out.append("ZClip False")
    out += stencil_lines(state)
    return out


def stencil_lines(state):
    so = state.get("stencilOp", {})
    fr, bk = state.get("stencilOpFront", {}), state.get("stencilOpBack", {})
    dflt = {"pass": "Keep", "fail": "Keep", "zFail": "Keep", "comp": "Always"}

    def plain(d):
        return {k: d.get(k, dflt[k]) for k in dflt}

    comp = _v(so, "comp", "Always")
    comp = "Always" if comp == "Disabled" else comp
    props = any(k.endswith("_prop") for k in list(state) + list(so))
    active = props or comp != "Always" or any(so.get(k, "Keep") != "Keep" for k in ("pass", "fail", "zFail"))
    split = plain(fr) != dflt or plain(bk) != dflt
    if not (active or split):
        return []
    lines = ["Stencil {"]
    lines.append(f"    Ref {_num(_v(state, 'stencilRef', 0))}")
    for key, nm in (("stencilReadMask", "ReadMask"), ("stencilWriteMask", "WriteMask")):
        lines.append(f"    {nm} {_num(_v(state, key, 255))}")
    if split:
        for suffix, d in (("Front", fr), ("Back", bk)):
            d = plain(d)
            c = "Always" if d["comp"] == "Disabled" else d["comp"]
            lines.append(f"    Comp{suffix} {c}\n    Pass{suffix} {d['pass']}\n    Fail{suffix} {d['fail']}\n    ZFail{suffix} {d['zFail']}")
    else:
        lines.append(f"    Comp {comp}\n    Pass {_v(so, 'pass', 'Keep')}\n    Fail {so.get('fail', 'Keep')}\n    ZFail {so.get('zFail', 'Keep')}")
    lines.append("}")
    return lines


# --------------------------------------------------------------------------- Uebersetzer
def run_translator(blob, stage, workdir, tag, vs_out_mask=None, extra=(), translator=None):
    """-> (hlsl_text, info_dict, cbuf1_bytes). Wirft WrapError, wenn die Uebersetzung scheitert."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    hlsl, info, c1 = workdir / f"{tag}.hlsl", workdir / f"{tag}.info.json", workdir / f"{tag}.cbuf1.bin"
    cmd = [str(translator or TRANSLATOR), "--lang", "hlsl", "--stage", stage, str(blob), "-o", str(hlsl), "--info",
           str(info), "--cbuf1", str(c1)]
    if vs_out_mask:
        cmd += ["--vs-out-mask", f"{vs_out_mask:x}"]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise WrapError(f"maxwell2msl {blob}: {r.stderr.strip() or r.returncode}")
    return hlsl.read_text(), json.loads(info.read_text()), c1.read_bytes()


# --------------------------------------------------------------------------- Zusammenbau
class Stage:
    """Alles, was zu einer Stufe (Vertex oder Fragment) gehoert."""

    def __init__(self, kind, entry, hlsl, info, cbuf1):
        self.kind, self.entry, self.hlsl, self.info, self.cbuf1 = kind, entry, hlsl, info, cbuf1
        self.prefix = "mxv" if kind == "vertex" else "mxf"

    def cbufs(self):
        return {c["index"]: c for c in self.info["constantBuffers"]}


def cbuf_rows(info_cb):
    """Zeilen (4 Woerter), die der Shader ansprechen darf; dynamisch gelesene Puffer: bis 4096 Zeilen."""
    if info_cb["dynamic"]:
        return 4096
    return max((info_cb["size"] + 15) // 16, 1)


def build_stage_block(st, mode, uniforms, arrays, warnings, extras=None, manifest_inst=None):
    """Quelltext von Fuellfunktion und Makros der Stufe. uniforms: name -> Deklaration (gemeinsam), arrays: Feldnamen,
    extras: Name -> stufenuebergreifende Deklaration (Instancing-cbuffer), manifest_inst: Instancing-Bloecke fuers Manifest."""
    extras = {} if extras is None else extras
    manifest_inst = [] if manifest_inst is None else manifest_inst
    p = st.prefix
    decl, fill, defs, undefs = [], [], [], []
    cbs = st.cbufs()
    for k in sorted(cbs):
        icb = cbs[k]
        rows = cbuf_rows(icb)
        name = f"{p}_cb{k}"
        defs.append(f"#define mx_cb{k} {name}")
        undefs.append(f"#undef mx_cb{k}")
        if k == 0 or k == 2:
            decl.append(f"static uint4 {name}[{rows}];  // cbuf {k}: {'Treiberdaten' if k == 0 else 'Handle-Tabellen'}, nie ausgewertet: Nullen")
            if k == 0:
                warnings.append(f"{st.kind}: cbuf 0 (Treiberdaten) wird gelesen und mit Nullen belegt")
                if st.info.get("usesGlobalMemory"):
                    # Zeile 17 (0x110) = Adresse des Speicherpuffers 0; mit Nullen ist die Gast-Adresse der Byte-Offset
                    if icb.get("staticMinOffset", -1) != 0x110 or icb.get("staticEndOffset", 0) > 0x118:
                        raise WrapError(f"{st.kind}: mehr als ein Speicherpuffer (cbuf 0 Bereich {icb.get('staticMinOffset')}..{icb.get('staticEndOffset')})")
                    bufs = st.entry.get("buffers", [])
                    if len(bufs) != 1:
                        raise WrapError(f"{st.kind}: {len(bufs)} Speicherpuffer im Inventar (erwartet 1)")
                    extras["buf:" + bufs[0]["name"]] = f"ByteAddressBuffer {bufs[0]['name']};"
                    defs.append(f"#define mx_gmem {bufs[0]['name']}")
                    undefs.append("#undef mx_gmem")
                    manifest_inst.append({"buffer": bufs[0]["name"]})
        elif k == 1:
            data = st.cbuf1
            nrows = min(rows, (len(data) + 15) // 16)
            words = [int.from_bytes((data[i * 16:(i + 1) * 16] + b"\0" * 16)[j * 4:(j + 1) * 4], "little")
                     for i in range(nrows) for j in range(4)]
            body = ",\n    ".join("uint4(" + ", ".join(f"0x{w:08x}u" for w in words[i * 4:(i + 1) * 4]) + ")" for i in range(nrows))
            decl.append(f"static const uint4 {name}[{max(nrows, 1)}] = {{\n    {body}\n}};  // cbuf 1: Compiler-Konstanten (Blob hinter dem Code)")
        elif icb["dynamic"] and mode != "array":
            cb = block_layout(st.entry, k - 3)
            stt = instancing_struct(cb) if cb else None
            if stt is None:
                raise WrapError(f"{st.kind}: cbuf {k} wird mit Register-Index gelesen, aber ohne Instancing-Struktur im Inventar")
            fname = f"{p}_cbr{k}"
            extras[cb["name"]] = instancing_decl(cb, stt)
            decl.append(instancing_reader(fname, stt))
            defs.append(f"#define mx_cbr{k} {fname}")
            undefs.append(f"#undef mx_cbr{k}")
            srows = max((icb["staticEndOffset"] + 15) // 16, 1) if icb.get("staticEndOffset", -1) > 0 else 1
            decl.append(f"static uint4 {name}[{srows}];")
            if icb.get("staticEndOffset", -1) > 0:
                warnings.append(f"{st.kind}: cbuf {k} (Instancing) wird auch mit festem Offset gelesen: Nullen")
            manifest_inst.append({"cbuf": k, "block": cb["name"], "struct": stt["name"], "stride": stt["structSize"]})
        else:
            decl.append(f"static uint4 {name}[{rows}];")
            binding = k - 3
            if mode == "array":
                aname = ("mxav" if st.kind == "vertex" else "mxaf") + f"_cb{k}"
                arrays[aname] = rows
                fill.append(f"    for (int i = 0; i < {rows}; i++) {name}[i] = asuint({aname}[i]);")
            else:
                cb = block_layout(st.entry, binding)
                if cb is None:
                    warnings.append(f"{st.kind}: cbuf {k} (Bindung {binding}) hat keinen Block im Inventar: Nullen")
                    continue
                for m in cb["members"]:
                    d = declaration(m)
                    if m["name"] in uniforms and uniforms[m["name"]] != d:
                        raise WrapError(f"Uniform {m['name']} mit zwei Typen: {uniforms[m['name']]} / {d}")
                    uniforms[m["name"]] = d
                cells = rows_for_block(cb, rows)
                if cb["size"] > icb["size"] + 15:
                    warnings.append(f"{st.kind}: Block {cb['name']} ({cb['size']} Byte) groesser als vom Shader gelesen ({icb['size']})")
                for r, row in enumerate(cells):
                    if any(row):
                        fill.append(f"    {name}[{r}] = {uint4_row(row)};")
    return decl, fill, defs, undefs


def texture_bindings(st, warnings):
    """[(slot, property_name, dim, shadow)] aus Ressourcenkarte und Stufeneintrag."""
    out = []
    # Der Texturwort-Index im Maxwell-Code entspricht dem Feld "sampler" des Inventars (m_SamplerIndex), das Samplerwort
    # dem Feld "index" (an 31.000 Texturabrufen belegt, scripts/tests: test_texture_table_uses_sampler_field).
    by_index = {t["sampler"]: t for t in st.entry.get("textures", [])}
    for t in st.info["textures"]:
        if not t.get("bindless") or t.get("textureTableIndex", -1) < 0:
            raise WrapError(f"{st.kind}: Textur-Slot {t['slot']} ohne Tabellenindex (nicht bindlos)")
        ut = by_index.get(t["textureTableIndex"])
        if ut is None:
            raise WrapError(f"{st.kind}: Textur-Tabellenindex {t['textureTableIndex']} fehlt im Inventar")
        dim = TYPENAME_DIM.get(t["typeName"], "2D")
        if dim != ut["dim"] and ut["dim"] != "Any":
            warnings.append(f"{st.kind}: Textur {ut['name']}: Shader nutzt {dim}, Unity-Dimension {ut['dim']}")
        out.append((t["slot"], ut["name"], dim, bool(t["shadow"])))
    return out


def vertex_inputs(st):
    """[(Ort, Semantik)] aus inputChannels (source = Unity-VertexAttribute, target = Attribut-Ort des Shaders)."""
    mp = {c["target"]: c["source"] for c in st.entry.get("inputChannels", [])}
    out = []
    for inp in st.info["inputs"]:
        loc = inp["location"]
        if loc not in mp or mp[loc] not in CHANNEL_SEMANTIC:
            raise WrapError(f"Vertexattribut a{loc} ohne Unity-Kanal (inputChannels)")
        out.append((loc, CHANNEL_SEMANTIC[mp[loc]]))
    return out


def build_shader(shader, sub_idx, pass_idx, keywords, vs, fs, mode="named", renderers="metal", extra_pragmas=(),
                 shader_name=None, color_mask=None, no_cull=False, parts=None, before=(), after=()):
    """-> (shader_text, manifest, warnings). vs/fs sind Stage-Objekte.

    before/after: fertige Zeilen (GrabPass-/UsePass-Bloecke), die vor bzw. hinter dem erzeugten Pass stehen.
    parts: wird mit head/block/tail (Zeilenlisten) gefuellt, damit combine_passes mehrere Paesse in einen SubShader setzt."""
    ss = shader["subShaders"][sub_idx]
    pas = ss["passes"][pass_idx]
    warnings = []
    uniforms, arrays, extras, inst = {}, {}, {}, []
    sdecl = {}
    for st in (vs, fs):
        sdecl[st.kind] = build_stage_block(st, mode, uniforms, arrays, warnings, extras, inst)
    vs_in = vertex_inputs(vs)
    vs_out = {o["location"] for o in vs.info["outputs"]}
    fs_in = [i for i in fs.info["inputs"] if i["location"] in vs_out]
    missing = [i["location"] for i in fs.info["inputs"] if i["location"] not in vs_out]
    if missing:
        warnings.append(f"Fragment liest Varyings {missing}, die der Vertex-Shader nicht schreibt (Null)")
    texs = {"vertex": texture_bindings(vs, warnings), "fragment": texture_bindings(fs, warnings)}
    props = {p["name"] for p in shader.get("properties", [])}

    L = []
    name = shader_name or f"XNU/Generated/{ident(shader['name'])}_s{sub_idx}_p{pass_idx}_{mode}"
    L.append(f'Shader "{name}"')
    L.append("{")
    L.append("    // erzeugt von scripts/shader_wrap.py; Quelle: " + shader["name"] +
             f" (SubShader {sub_idx}, Pass {pass_idx}), Keywords: {' '.join(sorted(keywords)) or '-'}")
    L.append("    Properties")
    L.append("    {")
    L += property_lines(shader.get("properties", []))
    # Texturen, die der Shader nutzt, aber das Inventar nicht als Eigenschaft fuehrt, sind ein Fehler im Inventar
    for kind in ("vertex", "fragment"):
        for _slot, tname, _dim, _sh in texs[kind]:
            if tname not in props:
                warnings.append(f"Texturname {tname} ist keine Material-Eigenschaft des Shaders")
    L.append("    }")
    L.append("    SubShader")
    L.append("    {")
    tags = ss.get("tags", {})
    if tags:
        L.append("        Tags { " + " ".join(f'"{k}"="{v}"' for k, v in tags.items()) + " }")
    if ss.get("lod"):
        L.append(f"        LOD {ss['lod']}")
    head_end = len(L)
    L.extend(before)
    L.append("        Pass")
    L.append("        {")
    if pas.get("name"):
        L.append(f'            Name "{pas["name"]}"')
    ptags = {k: v for k, v in pas.get("tags", {}).items() if k not in tags}
    if ptags:
        L.append("            Tags { " + " ".join(f'"{k}"="{v}"' for k, v in ptags.items()) + " }")
    for ln in render_state_lines(pas["state"]):
        if color_mask and ln.startswith("ColorMask"):
            continue
        if color_mask and ln.startswith("Blend "):  # Testhilfe: undurchsichtig, damit auch Alpha 0 sichtbar bleibt
            ln = "Blend Off"
        if no_cull and ln.startswith("Cull"):
            ln = "Cull Off"
        L.append("            " + ln)
    if color_mask:  # Testhilfe: z. B. Tiefen-Vorpass-Shader mit ColorMask 0 sichtbar machen
        L.append(f"            ColorMask {color_mask}")
    L.append("")
    L.append("            HLSLPROGRAM")
    L.append("            #pragma target 5.0")
    if renderers:
        L.append(f"            #pragma only_renderers {renderers}")
    for pr in extra_pragmas:
        L.append(f"            #pragma {pr}")
    kwset = set(keywords)
    procedural = "PROCEDURAL_INSTANCING_ON" in kwset
    if "INSTANCING_ON" in kwset or procedural:
        L.append("            #pragma multi_compile_instancing")
        if procedural:
            L.append("            #pragma instancing_options procedural:mx_proc_setup")
    L.append("            #pragma vertex mx_vert")
    L.append("            #pragma fragment mx_frag")
    L.append("            #define MX_EXTERNAL_RESOURCES")
    L.append("")
    if procedural:
        L.append("            void mx_proc_setup() {}")
    for d in extras.values():
        L.append("            " + d)
    # Uniforms
    if mode == "named":
        for d in uniforms.values():
            L.append(f"            {d};")
    else:
        for aname, n in arrays.items():
            L.append(f"            float4 {aname}[{n}];")
    tex_decl = {}
    for kind in ("vertex", "fragment"):
        for _slot, tname, dim, shadow in texs[kind]:
            tex_decl[tname] = (dim, shadow)
    for tname, (dim, shadow) in tex_decl.items():
        ty = (TEX_HLSL_SHADOW if shadow else TEX_HLSL).get(dim)
        if ty is None:
            raise WrapError(f"Texturdimension {dim} nicht unterstuetzt")
        L.append(f"            {ty} {tname};")
        L.append(f"            {'SamplerComparisonState' if shadow else 'SamplerState'} sampler{tname};")
    L.append("")
    # Stufen: Snippet des Uebersetzers mit stufenbezogenen Makros
    for st in (vs, fs):
        decl, fill, defs, undefs = sdecl[st.kind]
        for ln in decl:
            L.append("            " + ln.replace("\n", "\n            "))
        for slot, tname, _d, _s in texs[st.kind]:
            defs.append(f"#define mx_t{slot} {tname}")
            defs.append(f"#define mx_s{slot} sampler{tname}")
            defs.append(f"#define tsize{slot} {st.prefix}_tsize{slot}")
            defs.append(f"#define tlevels{slot} {st.prefix}_tlevels{slot}")
            undefs += [f"#undef mx_t{slot}", f"#undef mx_s{slot}", f"#undef tsize{slot}", f"#undef tlevels{slot}"]
        for ln in defs:
            L.append("            " + ln)
        L.append(f"            // ---- {st.kind} (Maxwell-HLSL)")
        L.append(st.hlsl.rstrip("\n"))
        for ln in undefs:
            L.append("            " + ln)
        L.append(f"            void {st.prefix}_fill()")
        L.append("            {")
        L += ["            " + ln for ln in fill]
        L.append("            }")
        L.append("")
    # Wrapper-Strukturen und Einstiegspunkte
    L.append("            struct MxAppdata")
    L.append("            {")
    for loc, sem in vs_in:
        L.append(f"                float4 a{loc} : {sem};")
    if not vs_in:
        L.append("                float4 unused_ : POSITION;")
    L.append("            };")
    L.append("            struct MxV2f")
    L.append("            {")
    L.append("                float4 pos : SV_POSITION;")
    for i in fs_in:
        mod = "nointerpolation " if i.get("interpolation") == "flat" else ""
        L.append(f"                {mod}float4 v{i['location']} : TEXCOORD{i['location']};")
    L.append("            };")
    L.append("            MxV2f mx_vert(MxAppdata a, uint vid : SV_VertexID, uint iid : SV_InstanceID)")
    L.append("            {")
    L.append("                mxv_fill();")
    L.append("                MxVIn i_ = (MxVIn)0;")
    for loc, _sem in vs_in:
        L.append(f"                i_.a{loc} = a.a{loc};")
    L.append("                MxVOut o = mx_vs(i_, vid, iid);")
    L.append("                MxV2f r;")
    L.append("                r.pos = o.pos;")
    for i in fs_in:
        L.append(f"                r.v{i['location']} = o.v{i['location']};")
    L.append("                return r;")
    L.append("            }")
    outs = [o for o in fs.info["outputs"]]
    L.append("            struct MxFragOut")
    L.append("            {")
    for o in outs:
        L.append(f"                float4 c{o['renderTarget']} : SV_Target{o['renderTarget']};")
    if fs.info["writesDepth"]:
        L.append("                float depth : SV_Depth;")
    L.append("            };")
    L.append("            MxFragOut mx_frag(MxV2f v, bool front : SV_IsFrontFace)")
    L.append("            {")
    L.append("                mxf_fill();")
    L.append("                MxFIn f = (MxFIn)0;")
    L.append("                f.pos = float4(v.pos.xyz, 1.0 / v.pos.w);  // Unitys SV_Position.w ist w (HLSLcc kehrt Metals 1/w um), Maxwell und Metal liefern 1/w")
    for i in fs_in:
        L.append(f"                f.v{i['location']} = v.v{i['location']};")
    L.append("                MxFOut o = mx_fs(f, front);")
    L.append("                MxFragOut r;")
    for o in outs:
        L.append(f"                r.c{o['renderTarget']} = o.c{o['renderTarget']};")
    if fs.info["writesDepth"]:
        L.append("                r.depth = o.depth;")
    L.append("                return r;")
    L.append("            }")
    L.append("            ENDHLSL")
    L.append("        }")
    block_end = len(L)
    L.extend(after)
    L.append("    }")
    L.append("}")
    manifest = {
        "shader": shader["name"], "unityShader": name, "subShader": sub_idx, "pass": pass_idx, "mode": mode,
        "keywords": sorted(keywords), "arrays": arrays,
        "vertexInputs": [{"location": loc, "semantic": sem} for loc, sem in vs_in],
        "varyings": [{"location": i["location"], "interpolation": i.get("interpolation")} for i in fs_in],
        "textures": {k: [{"slot": s, "property": n, "dim": d, "shadow": sh} for s, n, d, sh in v] for k, v in texs.items()},
        "uniforms": sorted(uniforms), "renderTargets": [o["renderTarget"] for o in outs],
        "writesDepth": fs.info["writesDepth"], "usesDiscard": fs.info["usesDiscard"],
        "cbufs": {k: sorted(st.cbufs()) for k, st in (("vertex", vs), ("fragment", fs))},
        "instancing": inst, "warnings": warnings,
    }
    if parts is not None:
        parts.update(head=L[:head_end], block=L[head_end:block_end + len(after)], tail=L[block_end + len(after):])
    return "\n".join(L) + "\n", manifest, warnings


def grab_lines(p):
    """GrabPass-Block eines Inventar-Passes (benannte Textur oder Standard _GrabTexture)."""
    return ["        GrabPass { " + (f'"{p["textureName"]}" ' if p.get("textureName") else "") + "}"]


def use_lines(p):
    return [f'        UsePass "{p["useName"]}"']


def aux_blocks(ss, pass_idx):
    """(before, after): Grab-Pass unmittelbar vor und UsePass-Paesse unmittelbar nach dem Pass (Reihenfolge wie im Original)."""
    passes = ss["passes"]
    before, after = [], []
    if pass_idx > 0 and passes[pass_idx - 1]["type"] == "Grab":
        before = grab_lines(passes[pass_idx - 1])
    j = pass_idx + 1
    while j < len(passes) and passes[j]["type"] == "Use":
        after += use_lines(passes[j])
        j += 1
    return before, after


def combine_passes(results):
    """results: Liste (parts, manifest) in Pass-Reihenfolge -> ein Shader mit mehreren Paessen (Kopf des ersten)."""
    head = results[0][0]["head"]
    tail = results[0][0]["tail"]
    body = []
    for parts, _m in results:
        body += parts["block"]
    return "\n".join(head + body + tail) + "\n"


# --------------------------------------------------------------------------- Kommandozeile
@functools.lru_cache(maxsize=None)
def load_json(path):
    return json.loads(Path(path).read_text())


def translate_pass(args, shader, sub, pass_index, keywords, pidx, prog_blob):
    """Uebersetzt Vertex- und Fragmentstufe eines Passes -> {'vertex': Stage, 'fragment': Stage}."""
    pas = shader["subShaders"][sub]["passes"][pass_index]
    stages = {}
    work = Path(args.workdir)
    tag0 = f"{ident(shader['name'])}_s{sub}_p{pass_index}"
    vs_mask = None
    for kind in ("vertex", "fragment"):
        i, entry = select_entry(pas, kind, keywords)
        pid = pidx.get((shader.get("bundle"), shader["name"], sub, pass_index, kind, i))
        if pid is None:
            raise WrapError(f"kein Programm fuer {kind} {i} in mapping.json")
        h = prog_blob[pid]
        if not h:
            raise WrapError(f"Programm {pid} ohne Blob")
        blob = Path(args.blobs) / f"{h}.bin"
        hlsl, info, c1 = run_translator(blob, "vs" if kind == "vertex" else "fs", work, f"{tag0}_{kind[0]}s",
                                        vs_mask if kind == "fragment" else None, args.translator_args,
                                        getattr(args, "translator", None))
        if kind == "vertex":
            vs_mask = int(info["outMask"], 16)
        stages[kind] = Stage(kind, entry, hlsl, info, c1)
        stages[kind].blob = h
    return stages


def parse_also(spec):
    """'3:SHADOWS_DEPTH,_SWING_ON' -> (3, ['SHADOWS_DEPTH', '_SWING_ON'])"""
    idx, _, kws = spec.partition(":")
    return int(idx), [k for k in kws.split(",") if k]


def wrap(args):
    inv = load_json(str(args.inventory))
    prog_blob = load_json(str(args.prog_blob))
    shader = find_shader(inv, args.shader, args.bundle)
    ss = shader["subShaders"][args.sub]
    pidx = program_index_cached(str(args.mapping)) if args.mapping else program_index_from_inventory(str(args.inventory))
    pragmas = ([] if args.fast_math else list(EXACT_PRAGMAS)) + list(args.pragma)
    also = [parse_also(a) for a in (getattr(args, "also", None) or [])]
    use_aux = not getattr(args, "no_aux", False)
    # Hauptpass (mit Grab davor/UsePass danach), dann die zusaetzlichen Normal-Paesse in der angegebenen Reihenfolge
    todo = [(args.pass_index, list(args.keywords), True)] + [(i, k, False) for i, k in also]
    results, blobs, manifest0 = [], {}, None
    text = None
    for n, (pi, kws, main) in enumerate(todo):
        if ss["passes"][pi]["type"] != "Normal":
            raise WrapError(f"Pass {pi} ist kein Normal-Pass ({ss['passes'][pi]['type']})")
        stages = translate_pass(args, shader, args.sub, pi, kws, pidx, prog_blob)
        before, after = aux_blocks(ss, pi) if (main and use_aux) else ([], [])
        parts = {}
        t, manifest, warnings = build_shader(shader, args.sub, pi, kws, stages["vertex"], stages["fragment"], args.mode,
                                             args.renderers, pragmas, args.name, args.color_mask,
                                             getattr(args, "no_cull", False), parts, before, after)
        manifest["blobs"] = {k: s.blob for k, s in stages.items()}
        if before or after:
            manifest["auxPasses"] = {"grab": [l.strip() for l in before], "use": [l.strip() for l in after]}
        results.append((parts, manifest, warnings))
        if n == 0:
            text, manifest0 = t, manifest
    if len(results) > 1:
        text = combine_passes([(r[0], r[1]) for r in results])
        manifest0 = dict(manifest0)
        manifest0["passes"] = [r[1] for r in results]
        manifest0["warnings"] = [w for r in results for w in r[2]]
    warnings = manifest0["warnings"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    out.with_suffix(".wrap.json").write_text(json.dumps(manifest0, indent=1))
    for w in warnings:
        print("WARNUNG:", w, file=sys.stderr)
    print(f"{out} ({len(text)} Zeichen, Modus {args.mode}, {len(results)} Pass/Paesse)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shader", help="Shadername laut Inventar, z. B. 'Custom/ProceduralPlane/Footprint'")
    ap.add_argument("--bundle", help="Bundle, falls der Name mehrfach vorkommt")
    ap.add_argument("--sub", type=int, default=0, help="SubShader-Index")
    ap.add_argument("--pass", dest="pass_index", type=int, default=0, help="Pass-Index")
    ap.add_argument("--keywords", nargs="*", default=[], help="Keyword-Menge der Variante (global + lokal)")
    ap.add_argument("--mode", choices=("named", "array"), default="named", help="Abbildung der Konstantenpuffer")
    ap.add_argument("--out", required=True, help="Ausgabedatei .shader (daneben .wrap.json)")
    ap.add_argument("--name", help="Unity-Shadername (Standard: XNU/Generated/...)")
    ap.add_argument("--renderers", default="metal", help="#pragma only_renderers (leer: alle)")
    ap.add_argument("--pragma", action="append", default=[], help="zusaetzliches #pragma (z. B. 'multi_compile_instancing')")
    ap.add_argument("--fast-math", action="store_true",
                    help="ohne die Pragmas fuer exakte Arithmetik (Standard: disable_fastmath + skip_optimizations <renderer>)")
    ap.add_argument("--translator-args", nargs="*", default=[], help="weitere Optionen fuer maxwell2msl")
    ap.add_argument("--color-mask", help="Testhilfe: ersetzt den ColorMask des Passes (z. B. RGBA) und schaltet Blend aus")
    ap.add_argument("--no-cull", action="store_true", help="Testhilfe: Cull Off")
    ap.add_argument("--also", action="append", default=[], metavar="PASS[:KW,KW]",
                    help="weiterer Normal-Pass mit eigener Keyword-Menge im selben SubShader (z. B. Schattenwurf '3:SHADOWS_DEPTH'); "
                         "ein Material = ein Shader mit mehreren Paessen")
    ap.add_argument("--no-aux", action="store_true",
                    help="GrabPass vor und UsePass hinter dem Hauptpass nicht uebernehmen (Standard: uebernehmen)")
    ap.add_argument("--inventory", default=str(WORK / "inventory.json"))
    ap.add_argument("--mapping", default=None, help="optional: mapping.json statt der Aufzaehlung aus dem Inventar")
    ap.add_argument("--prog-blob", default=str(WORK / "prog_blob.json"))
    ap.add_argument("--blobs", default=str(WORK / "blobs"))
    ap.add_argument("--workdir", default=str(WORK / "unity-lab" / "wrap"))
    args = ap.parse_args(argv)
    try:
        return wrap(args)
    except WrapError as e:
        print(f"shader_wrap: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
