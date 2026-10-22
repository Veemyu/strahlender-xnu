#!/usr/bin/env python3
"""ShaderLab wrapper generator: Maxwell blobs (translated to HLSL) -> Unity .shader file.

Own code of the strahlender-xnu project. Inputs (all local under work/shaders/, not in the repo):
  inventory.json   properties, tags, render states, parameter layouts per pass and stage (scripts/shader_inventory.py)
  mapping.json     (optional) program ID per (bundle, shader, subshader, pass, stage, subprogram); without the file the
                   inventory enumerates the programs in the same order
  prog_blob.json   program ID -> blob hash (scripts/shader_fidelity.py index)
  blobs/<hash>.bin Maxwell blobs (scripts/shader_extract_blobs.py)
and the tool shader_translator/build/maxwell2msl (--lang hlsl).

Output: <name>.shader (one SubShader, one fixed keyword variant per pass) and <name>.wrap.json (mappings
for tests and mass production). Without --also there is one pass in the shader; before it comes the original's GrabPass
(inventory pass of type Grab, e.g. _BackgroundTexture for water) and after it a UsePass (e.g. the legacy shadow caster
of the Mitake shaders), both in original order. --also PASS[:KW,KW] adds further normal passes (typically the
SHADOWCASTER pass) to the same SubShader: Unity takes the shadow caster from the material's shader. The mapping of the
hardware constant buffers is described in docs/shader-unity-integration.md:
  cbuf 0  driver data               -> zeros (static uint4 array)
  cbuf 1  compiler constants        -> static const uint4 array with the bytes behind the blob's code
  cbuf 2  handle tables             -> zeros (the values are never used; textures go by name)
  cbuf 3+ Unity block, binding k-3  -> mode "named": per word the value of the Unity uniform located there
                                       (names/offsets from constantBuffers of the inventory); mode "array": one
                                       float4 array mxav_cb<k> / mxaf_cb<k> that a test fills exactly
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

# Unity VertexAttribute (inputChannels[].source) -> HLSL semantic
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


# Exact arithmetic in the Unity Metal path (docs/shader-unity-integration.md, section mathematical fidelity):
# disable_fastmath turns off Metal's fast math (FMA fusion, approximations for division/sin/cos),
# skip_optimizations prevents FXC from fusing a*b+c into a mad (later fma) and folding away isnan().
EXACT_PRAGMAS = ("disable_fastmath", "skip_optimizations metal")


# --------------------------------------------------------------------------- Inventory
def ident(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def find_shader(inv, name, bundle=None):
    cands = [s for s in inv.get("shaders", []) + inv.get("extraShaders", [])
             if s["name"] == name and (bundle is None or s.get("bundle") == bundle)]
    if not cands:
        raise WrapError(f"Shader '{name}' not in the inventory")
    if len(cands) > 1:
        raise WrapError(f"Shader '{name}' occurs several times ({', '.join(sorted({c.get('bundle', '?') for c in cands}))}): give --bundle")
    return cands[0]


def select_entry(pass_, stage, keywords):
    """Stage entry (index = SubProgram) with exactly this keyword set (global + local)."""
    want = set(keywords or [])
    found = []
    for i, e in enumerate(pass_["stages"].get(stage, [])):
        if set(e.get("globalKeywords", [])) | set(e.get("localKeywords", [])) == want:
            found.append((i, e))
    if not found:
        have = [sorted(set(e.get("globalKeywords", [])) | set(e.get("localKeywords", [])))
                for e in pass_["stages"].get(stage, [])]
        raise WrapError(f"no {stage} variant with keywords {sorted(want)}; available: {have[:6]}")
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
    """Program ID = enumeration order in the inventory (shader, subshader, pass, vertex before fragment, subprogram);
    identical to mapping.json (checked on all 14,342 programs), without needing the Ryujinx cache."""
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
            raise WrapError(f"Matrix with {n} components ({m['name']}) not supported")
    else:
        base = "float" if n == 1 else f"float{n}"
    return base


def declaration(m):
    arr = f"[{m['arraySize']}]" if m.get("arraySize") else ""
    return f"{hlsl_member_type(m)} {m['name']}{arr}"


def member_words(m):
    """Number of 4-byte words the member occupies in the block (array elements start on 16 bytes)."""
    n, kind = m["components"], m["kind"]
    if kind == "matrix":
        per = 16 if n == 16 else 12  # float3x3: three rows of 16 bytes
    elif m.get("arraySize"):
        per = 4
    else:
        per = n
    return per * max(m.get("arraySize", 0), 1)


def word_expr(m, e):
    """HLSL expression (float) for word e (from the member offset) or None (filler byte)."""
    n, kind, arr = m["components"], m["kind"], m.get("arraySize", 0)
    name = m["name"]
    comps = "xyzw"
    if kind == "matrix":
        per = 16 if n == 16 else 12
        idx, e = divmod(e, per)
        col, row = divmod(e, 4)  # row of the block = column of the matrix (column-major layout, like GLSL mat4)
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
    """(name, size, members) of the Unity block with this binding number, or None."""
    names = [b["name"] for b in entry.get("cbBindings", []) if b["index"] == binding]
    if not names:
        return None
    for cb in entry.get("constantBuffers", []):
        if cb["name"] == names[0]:
            return cb
    return None


def rows_for_block(cb, rows):
    """Four expressions (str) or None per row; rows = number of rows (4 words)."""
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


# Uniforms that Unity writes as an integer (the bits stay unchanged in the block)
RAW_UINT_EXPRS = {"unity_BaseInstanceID"}
INSTANCING_ARRAY_SIZE = 500  # UNITY_INSTANCED_ARRAY_SIZE of the built-in path (500 * 128 bytes < 64 KB)


def instancing_struct(cb):
    """First struct of the Unity instancing block (e.g. unity_Builtins0Array) or None."""
    structs = cb.get("structs") or []
    return structs[0] if structs else None


def instancing_decl(cb, st):
    """cbuffer text with the struct array; gaps between the members are padded (stride = structSize)."""
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
    """HLSL function: word at byte offset off of the (instance) array, as the Maxwell instructions read it."""
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


# --------------------------------------------------------------------------- Properties and state
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
    """Value or [material property]."""
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


# --------------------------------------------------------------------------- Translator
def run_translator(blob, stage, workdir, tag, vs_out_mask=None, extra=(), translator=None):
    """-> (hlsl_text, info_dict, cbuf1_bytes). Raises WrapError if the translation fails."""
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


# --------------------------------------------------------------------------- Assembly
class Stage:
    """Everything that belongs to one stage (vertex or fragment)."""

    def __init__(self, kind, entry, hlsl, info, cbuf1):
        self.kind, self.entry, self.hlsl, self.info, self.cbuf1 = kind, entry, hlsl, info, cbuf1
        self.prefix = "mxv" if kind == "vertex" else "mxf"

    def cbufs(self):
        return {c["index"]: c for c in self.info["constantBuffers"]}


def cbuf_rows(info_cb):
    """Rows (4 words) the shader may address; dynamically read buffers: up to 4096 rows."""
    if info_cb["dynamic"]:
        return 4096
    return max((info_cb["size"] + 15) // 16, 1)


def build_stage_block(st, mode, uniforms, arrays, warnings, extras=None, manifest_inst=None):
    """Source text of the fill function and macros of the stage. uniforms: name -> declaration (shared), arrays: array names,
    extras: name -> cross-stage declaration (instancing cbuffer), manifest_inst: instancing blocks for the manifest."""
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
            decl.append(f"static uint4 {name}[{rows}];  // cbuf {k}: {'driver data' if k == 0 else 'handle tables'}, never evaluated: zeros")
            if k == 0:
                warnings.append(f"{st.kind}: cbuf 0 (driver data) is read and filled with zeros")
                if st.info.get("usesGlobalMemory"):
                    # row 17 (0x110) = address of storage buffer 0; with zeros the guest address is the byte offset
                    if icb.get("staticMinOffset", -1) != 0x110 or icb.get("staticEndOffset", 0) > 0x118:
                        raise WrapError(f"{st.kind}: more than one storage buffer (cbuf 0 range {icb.get('staticMinOffset')}..{icb.get('staticEndOffset')})")
                    bufs = st.entry.get("buffers", [])
                    if len(bufs) != 1:
                        raise WrapError(f"{st.kind}: {len(bufs)} storage buffers in the inventory (expected 1)")
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
            decl.append(f"static const uint4 {name}[{max(nrows, 1)}] = {{\n    {body}\n}};  // cbuf 1: compiler constants (blob behind the code)")
        elif icb["dynamic"] and mode != "array":
            cb = block_layout(st.entry, k - 3)
            stt = instancing_struct(cb) if cb else None
            if stt is None:
                raise WrapError(f"{st.kind}: cbuf {k} is read with a register index, but there is no instancing struct in the inventory")
            fname = f"{p}_cbr{k}"
            extras[cb["name"]] = instancing_decl(cb, stt)
            decl.append(instancing_reader(fname, stt))
            defs.append(f"#define mx_cbr{k} {fname}")
            undefs.append(f"#undef mx_cbr{k}")
            srows = max((icb["staticEndOffset"] + 15) // 16, 1) if icb.get("staticEndOffset", -1) > 0 else 1
            decl.append(f"static uint4 {name}[{srows}];")
            if icb.get("staticEndOffset", -1) > 0:
                warnings.append(f"{st.kind}: cbuf {k} (instancing) is also read with a fixed offset: zeros")
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
                    warnings.append(f"{st.kind}: cbuf {k} (binding {binding}) has no block in the inventory: zeros")
                    continue
                for m in cb["members"]:
                    d = declaration(m)
                    if m["name"] in uniforms and uniforms[m["name"]] != d:
                        raise WrapError(f"Uniform {m['name']} with two types: {uniforms[m['name']]} / {d}")
                    uniforms[m["name"]] = d
                cells = rows_for_block(cb, rows)
                # Integer uniforms (_BaseColorAddEnable, _Cascade, _ColorMapUvIndex …): the original reads the word as int
                # (float(int(cb))). Unity properties are float; the bits of 1.0 would be int 1065353216 (Inf/NaN in the image).
                for m_ in re.finditer(rf"(?:float\(int\(|float\(uint\(|\bint\(|\bas(?:int|uint)\()mx_cb{k}\[(\d+)\]\[(\d)\]", st.hlsl):
                    r_, c_ = int(m_.group(1)), int(m_.group(2))
                    if r_ < len(cells) and cells[r_][c_] and cells[r_][c_] not in RAW_UINT_EXPRS and not cells[r_][c_].startswith("int("):
                        cells[r_][c_] = f"int({cells[r_][c_]})"
                if cb["size"] > icb["size"] + 15:
                    warnings.append(f"{st.kind}: block {cb['name']} ({cb['size']} bytes) is larger than what the shader reads ({icb['size']})")
                for r, row in enumerate(cells):
                    if any(row):
                        fill.append(f"    {name}[{r}] = {uint4_row(row)};")
    return decl, fill, defs, undefs


def texture_bindings(st, warnings):
    """[(slot, property_name, dim, shadow)] from the resource map and the stage entry."""
    out = []
    # The texture word index in the Maxwell code corresponds to the inventory field "sampler" (m_SamplerIndex), the sampler word
    # to the field "index" (verified on 31,000 texture fetches, scripts/tests: test_texture_table_uses_sampler_field).
    by_index = {t["sampler"]: t for t in st.entry.get("textures", [])}
    for t in st.info["textures"]:
        if not t.get("bindless") or t.get("textureTableIndex", -1) < 0:
            raise WrapError(f"{st.kind}: texture slot {t['slot']} without table index (not bindless)")
        ut = by_index.get(t["textureTableIndex"])
        if ut is None:
            raise WrapError(f"{st.kind}: texture table index {t['textureTableIndex']} missing in the inventory")
        dim = TYPENAME_DIM.get(t["typeName"], "2D")
        if dim != ut["dim"] and ut["dim"] != "Any":
            warnings.append(f"{st.kind}: texture {ut['name']}: shader uses {dim}, Unity dimension {ut['dim']}")
        out.append((t["slot"], ut["name"], dim, bool(t["shadow"])))
    return out


def vertex_inputs(st):
    """[(location, semantic)] from inputChannels (source = Unity VertexAttribute, target = attribute location of the shader)."""
    mp = {c["target"]: c["source"] for c in st.entry.get("inputChannels", [])}
    out = []
    for inp in st.info["inputs"]:
        loc = inp["location"]
        if loc not in mp or mp[loc] not in CHANNEL_SEMANTIC:
            raise WrapError(f"Vertex attribute a{loc} without Unity channel (inputChannels)")
        out.append((loc, CHANNEL_SEMANTIC[mp[loc]]))
    return out


def build_shader(shader, sub_idx, pass_idx, keywords, vs, fs, mode="named", renderers="metal", extra_pragmas=(),
                 shader_name=None, color_mask=None, no_cull=False, parts=None, before=(), after=()):
    """-> (shader_text, manifest, warnings). vs/fs are Stage objects.

    before/after: finished lines (GrabPass/UsePass blocks) placed before/after the generated pass.
    parts: filled with head/block/tail (line lists) so combine_passes can put several passes into one SubShader."""
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
        warnings.append(f"Fragment reads varyings {missing} that the vertex shader does not write (zero)")
    texs = {"vertex": texture_bindings(vs, warnings), "fragment": texture_bindings(fs, warnings)}
    props = {p["name"] for p in shader.get("properties", [])}

    L = []
    name = shader_name or f"XNU/Generated/{ident(shader['name'])}_s{sub_idx}_p{pass_idx}_{mode}"
    L.append(f'Shader "{name}"')
    L.append("{")
    L.append("    // generated by scripts/shader_wrap.py; source: " + shader["name"] +
             f" (SubShader {sub_idx}, Pass {pass_idx}), Keywords: {' '.join(sorted(keywords)) or '-'}")
    L.append("    Properties")
    L.append("    {")
    L += property_lines(shader.get("properties", []))
    # textures the shader uses but the inventory does not list as a property are an error in the inventory
    for kind in ("vertex", "fragment"):
        for _slot, tname, _dim, _sh in texs[kind]:
            if tname not in props:
                warnings.append(f"Texture name {tname} is not a material property of the shader")
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
        if color_mask and ln.startswith("Blend "):  # test aid: opaque, so alpha 0 stays visible too
            ln = "Blend Off"
        if no_cull and ln.startswith("Cull"):
            ln = "Cull Off"
        L.append("            " + ln)
    if color_mask:  # test aid: e.g. make depth prepass shaders with ColorMask 0 visible
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
            raise WrapError(f"Texture dimension {dim} not supported")
        L.append(f"            {ty} {tname};")
        L.append(f"            {'SamplerComparisonState' if shadow else 'SamplerState'} sampler{tname};")
    L.append("")
    # Stages: snippet of the translator with per-stage macros
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
    # Wrapper structs and entry points
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
    L.append("                f.pos = float4(v.pos.xyz, 1.0 / v.pos.w);  // Unity's SV_Position.w is w (HLSLcc inverts Metal's 1/w), Maxwell and Metal deliver 1/w")
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
    """GrabPass block of an inventory pass (named texture or the default _GrabTexture)."""
    return ["        GrabPass { " + (f'"{p["textureName"]}" ' if p.get("textureName") else "") + "}"]


def use_lines(p):
    return [f'        UsePass "{p["useName"]}"']


def aux_blocks(ss, pass_idx):
    """(before, after): grab pass directly before and UsePass passes directly after the pass (order as in the original)."""
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
    """results: list (parts, manifest) in pass order -> one shader with several passes (head of the first)."""
    head = results[0][0]["head"]
    tail = results[0][0]["tail"]
    body = []
    for parts, _m in results:
        body += parts["block"]
    return "\n".join(head + body + tail) + "\n"


# --------------------------------------------------------------------------- Command line
@functools.lru_cache(maxsize=None)
def load_json(path):
    return json.loads(Path(path).read_text())


def translate_pass(args, shader, sub, pass_index, keywords, pidx, prog_blob):
    """Translates the vertex and fragment stage of a pass -> {'vertex': Stage, 'fragment': Stage}."""
    pas = shader["subShaders"][sub]["passes"][pass_index]
    stages = {}
    work = Path(args.workdir)
    tag0 = f"{ident(shader['name'])}_s{sub}_p{pass_index}"
    vs_mask = None
    for kind in ("vertex", "fragment"):
        i, entry = select_entry(pas, kind, keywords)
        pid = pidx.get((shader.get("bundle"), shader["name"], sub, pass_index, kind, i))
        if pid is None:
            raise WrapError(f"no program for {kind} {i} in mapping.json")
        h = prog_blob[pid]
        if not h:
            raise WrapError(f"Program {pid} without blob")
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
    # main pass (with grab before/UsePass after), then the additional normal passes in the given order
    todo = [(args.pass_index, list(args.keywords), True)] + [(i, k, False) for i, k in also]
    results, blobs, manifest0 = [], {}, None
    text = None
    for n, (pi, kws, main) in enumerate(todo):
        if ss["passes"][pi]["type"] != "Normal":
            raise WrapError(f"Pass {pi} is not a normal pass ({ss['passes'][pi]['type']})")
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
        print("WARNING:", w, file=sys.stderr)
    print(f"{out} ({len(text)} characters, mode {args.mode}, {len(results)} pass(es))")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shader", help="shader name per inventory, e.g. 'Custom/ProceduralPlane/Footprint'")
    ap.add_argument("--bundle", help="bundle, if the name occurs several times")
    ap.add_argument("--sub", type=int, default=0, help="SubShader index")
    ap.add_argument("--pass", dest="pass_index", type=int, default=0, help="pass index")
    ap.add_argument("--keywords", nargs="*", default=[], help="keyword set of the variant (global + local)")
    ap.add_argument("--mode", choices=("named", "array"), default="named", help="mapping of the constant buffers")
    ap.add_argument("--out", required=True, help="output file .shader (next to it .wrap.json)")
    ap.add_argument("--name", help="Unity shader name (default: XNU/Generated/...)")
    ap.add_argument("--renderers", default="metal", help="#pragma only_renderers (empty: all)")
    ap.add_argument("--pragma", action="append", default=[], help="additional #pragma (e.g. 'multi_compile_instancing')")
    ap.add_argument("--fast-math", action="store_true",
                    help="without the pragmas for exact arithmetic (default: disable_fastmath + skip_optimizations <renderer>)")
    ap.add_argument("--translator-args", nargs="*", default=[], help="further options for maxwell2msl")
    ap.add_argument("--color-mask", help="test aid: replaces the pass's ColorMask (e.g. RGBA) and switches blend off")
    ap.add_argument("--no-cull", action="store_true", help="test aid: Cull Off")
    ap.add_argument("--also", action="append", default=[], metavar="PASS[:KW,KW]",
                    help="further normal pass with its own keyword set in the same SubShader (e.g. shadow caster '3:SHADOWS_DEPTH'); "
                         "one material = one shader with several passes")
    ap.add_argument("--no-aux", action="store_true",
                    help="do not take over the GrabPass before and the UsePass after the main pass (default: take over)")
    ap.add_argument("--inventory", default=str(WORK / "inventory.json"))
    ap.add_argument("--mapping", default=None, help="optional: mapping.json instead of the enumeration from the inventory")
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
