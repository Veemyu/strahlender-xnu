"""Tests for scripts/shader_wrap.py: synthetic inputs only (no game content, no Unity, no Metal)."""
import argparse
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import shader_wrap as sw  # noqa: E402


def vec(name, off, n=1, arr=0):
    return {"name": name, "offset": off, "components": n, "arraySize": arr, "kind": "vector"}


def mat(name, off, n=16, arr=0):
    return {"name": name, "offset": off, "components": n, "arraySize": arr, "kind": "matrix"}


class Members(unittest.TestCase):
    def test_words_and_types(self):
        self.assertEqual(sw.hlsl_member_type(vec("a", 0, 1)), "float")
        self.assertEqual(sw.hlsl_member_type(vec("a", 0, 3)), "float3")
        self.assertEqual(sw.hlsl_member_type(mat("m", 0)), "float4x4")
        self.assertEqual(sw.hlsl_member_type(mat("m", 0, 9)), "float3x3")
        with self.assertRaises(sw.WrapError):
            sw.hlsl_member_type(mat("m", 0, 12))
        self.assertEqual(sw.declaration(vec("v", 0, 4, 3)), "float4 v[3]")
        self.assertEqual(sw.member_words(vec("a", 0, 3)), 3)
        self.assertEqual(sw.member_words(vec("a", 0, 1, 4)), 16)   # Arrayelemente beginnen auf 16 Byte
        self.assertEqual(sw.member_words(mat("m", 0)), 16)
        self.assertEqual(sw.member_words(mat("m", 0, 9)), 12)
        self.assertEqual(sw.member_words(mat("m", 0, 16, 2)), 32)

    def test_word_expr_vectors(self):
        v = vec("_Col", 0, 3)
        self.assertEqual([sw.word_expr(v, e) for e in range(4)], ["_Col.x", "_Col.y", "_Col.z", None])
        self.assertEqual(sw.word_expr(vec("_F", 0, 1), 0), "_F")
        arr = vec("_A", 0, 2, 2)
        self.assertEqual([sw.word_expr(arr, e) for e in range(8)],
                         ["_A[0].x", "_A[0].y", None, None, "_A[1].x", "_A[1].y", None, None])
        self.assertEqual(sw.word_expr(vec("_S", 0, 1, 2), 4), "_S[1]")

    def test_word_expr_matrix_is_column_major(self):
        m = mat("unity_ObjectToWorld", 0)
        # row r of the block = column r of the matrix: word 4*c + r = M[r][c]
        self.assertEqual(sw.word_expr(m, 0), "unity_ObjectToWorld[0][0]")
        self.assertEqual(sw.word_expr(m, 1), "unity_ObjectToWorld[1][0]")
        self.assertEqual(sw.word_expr(m, 4), "unity_ObjectToWorld[0][1]")
        self.assertEqual(sw.word_expr(m, 12), "unity_ObjectToWorld[0][3]")   # Verschiebung steht in Spalte 3
        self.assertEqual(sw.word_expr(m, 15), "unity_ObjectToWorld[3][3]")
        m2 = mat("M", 0, 16, 2)
        self.assertEqual(sw.word_expr(m2, 16 + 4), "M[1][0][1]")
        m3 = mat("N", 0, 9)
        self.assertEqual(sw.word_expr(m3, 5), "N[1][1]")
        self.assertIsNone(sw.word_expr(m3, 3))  # filler word of the third column

    def test_rows(self):
        cb = {"name": "VGlobals", "size": 80, "members": [vec("_Time", 0, 4), vec("_Scale", 16, 1), vec("_Off", 20, 2),
                                                            mat("unity_MatrixVP", 32)]}
        rows = sw.rows_for_block(cb, 6)
        self.assertEqual(rows[0], ["_Time.x", "_Time.y", "_Time.z", "_Time.w"])
        self.assertEqual(rows[1], ["_Scale", "_Off.x", "_Off.y", None])
        self.assertEqual(rows[2][0], "unity_MatrixVP[0][0]")
        self.assertEqual(rows[2][3], "unity_MatrixVP[3][0]")
        self.assertEqual(rows[5][3], "unity_MatrixVP[3][3]")
        self.assertEqual(sw.uint4_row(rows[1]), "uint4(asuint(_Scale), asuint(_Off.x), asuint(_Off.y), 0u)")
        # fewer rows than the block: truncated, no error
        self.assertEqual(len(sw.rows_for_block(cb, 3)), 3)


class Properties(unittest.TestCase):
    def test_property_lines(self):
        props = [
            {"name": "_MainTex", "label": "Main Texture", "type": "Texture", "flags": 4, "attributes": [], "texDim": "2D",
             "defaultTexture": "black"},
            {"name": "_Color", "label": "Tint", "type": "Color", "flags": 16, "attributes": [], "default": [1, 0.5, 0, 1]},
            {"name": "_Cut", "label": "Cut", "type": "Range", "flags": 0, "attributes": [], "default": [0.25, 0, 1]},
            {"name": "_SrcBlend", "label": "Src", "type": "Float", "flags": 1, "attributes": ["Enum(UnityEngine.Rendering.BlendMode)"],
             "default": [1.0]},
            {"name": "_V", "label": 'a"b', "type": "Vector", "flags": 0, "attributes": [], "default": [1, 2, 3, 4]},
            {"name": "_Cube", "label": "C", "type": "Texture", "flags": 0, "attributes": [], "texDim": "Cube"},
        ]
        out = [l.strip() for l in sw.property_lines(props)]
        self.assertEqual(out[0], '[NoScaleOffset] _MainTex ("Main Texture", 2D) = "black" {}')
        self.assertEqual(out[1], '[HDR] _Color ("Tint", Color) = (1, 0.5, 0, 1)')
        self.assertEqual(out[2], '_Cut ("Cut", Range(0, 1)) = 0.25')
        self.assertEqual(out[3], '[HideInInspector] [Enum(UnityEngine.Rendering.BlendMode)] _SrcBlend ("Src", Float) = 1')
        self.assertEqual(out[4], "_V (\"a'b\", Vector) = (1, 2, 3, 4)")
        self.assertEqual(out[5], '_Cube ("C", Cube) = "white" {}')


class RenderState(unittest.TestCase):
    base = {"rtBlend": [{"srcBlend": "One", "destBlend": "Zero", "srcBlendAlpha": "One", "destBlendAlpha": "Zero",
                         "blendOp": "Add", "blendOpAlpha": "Add", "colMask": 15}], "rtSeparateBlend": False,
            "zTest": "LEqual", "culling": "Back", "zWrite": 1.0, "zClip": 1.0, "offsetFactor": 0.0, "offsetUnits": 0.0,
            "alphaToMask": 0.0, "stencilReadMask": 255.0, "stencilWriteMask": 255.0, "stencilRef": 0.0,
            "stencilOp": {"pass": "Keep", "fail": "Keep", "zFail": "Keep", "comp": "Always"},
            "stencilOpFront": {"pass": "Keep", "fail": "Keep", "zFail": "Keep", "comp": "Always"},
            "stencilOpBack": {"pass": "Keep", "fail": "Keep", "zFail": "Keep", "comp": "Always"}}

    def state(self, **kw):
        s = json.loads(json.dumps(self.base))
        for k, v in kw.items():
            s[k] = v
        return s

    def test_defaults(self):
        self.assertEqual(sw.render_state_lines(self.base), ["ZTest LEqual", "ZWrite On", "Cull Back"])

    def test_blend_and_masks(self):
        s = self.state()
        s["rtBlend"][0].update(srcBlend="SrcAlpha", destBlend="OneMinusSrcAlpha", srcBlendAlpha="One", destBlendAlpha="OneMinusSrcAlpha",
                               colMask=14, blendOp="Max", blendOpAlpha="Max")
        lines = sw.render_state_lines(s)
        self.assertIn("Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha", lines)
        self.assertIn("BlendOp Max", lines)
        self.assertIn("ColorMask RGB", lines)   # 14 = R+G+B without alpha
        s["rtBlend"][0]["colMask"] = 0
        self.assertIn("ColorMask 0", sw.render_state_lines(s))

    def test_properties_replace_values(self):
        s = self.state(zTest="Disabled", zTest_prop="unity_GUIZTestMode", culling_prop="_CullMode", zWrite_prop="_ZW")
        s["rtBlend"][0].update(srcBlend_prop="_SrcBlend", destBlend_prop="_DstBlend", srcBlendAlpha_prop="_SrcBlend",
                               destBlendAlpha_prop="_DstBlend", colMask_prop="_ColorMask", blendOp_prop="_BlendOp",
                               blendOpAlpha_prop="_BlendOp")
        lines = sw.render_state_lines(s)
        self.assertIn("Blend [_SrcBlend] [_DstBlend]", lines)
        self.assertIn("BlendOp [_BlendOp]", lines)
        self.assertIn("ColorMask [_ColorMask]", lines)
        self.assertIn("ZTest [unity_GUIZTestMode]", lines)
        self.assertIn("Cull [_CullMode]", lines)
        self.assertIn("ZWrite [_ZW]", lines)

    def test_disabled_ztest_is_always(self):
        self.assertIn("ZTest Always", sw.render_state_lines(self.state(zTest="Disabled")))

    def test_offset_alpha_to_mask_zclip(self):
        lines = sw.render_state_lines(self.state(offsetFactor=-1.0, offsetUnits=-2.0, alphaToMask=1.0, zClip=0.0))
        self.assertIn("Offset -1.0, -2.0", lines)
        self.assertIn("AlphaToMask On", lines)
        self.assertIn("ZClip False", lines)

    def test_stencil(self):
        self.assertFalse([l for l in sw.render_state_lines(self.base) if "Stencil" in l])
        s = self.state(stencilRef=1.0)
        s["stencilOp"] = {"pass": "Replace", "fail": "Keep", "zFail": "Keep", "comp": "Always"}
        text = "\n".join(sw.render_state_lines(s))
        self.assertIn("Stencil {", text)
        self.assertIn("Ref 1", text)
        self.assertIn("Pass Replace", text)
        self.assertIn("ReadMask 255", text)
        s = self.state()
        s["stencilOp"]["comp"] = "Disabled"
        s["stencilOp"]["comp_prop"] = "_StencilComp"
        s["stencilRef_prop"] = "_Stencil"
        text = "\n".join(sw.render_state_lines(s))
        self.assertIn("Comp [_StencilComp]", text)
        self.assertIn("Ref [_Stencil]", text)
        s = self.state()
        s["stencilOpFront"] = {"pass": "IncrWrap", "fail": "Keep", "zFail": "Keep", "comp": "Equal"}
        text = "\n".join(sw.render_state_lines(s))
        self.assertIn("CompFront Equal", text)
        self.assertIn("PassFront IncrWrap", text)
        self.assertIn("CompBack Always", text)


class Selection(unittest.TestCase):
    pas = {"stages": {"vertex": [{"globalKeywords": ["A"], "localKeywords": []}, {"globalKeywords": [], "localKeywords": []}],
                      "fragment": [{"globalKeywords": [], "localKeywords": ["B", "A"]}]}}

    def test_select_entry(self):
        self.assertEqual(sw.select_entry(self.pas, "vertex", [])[0], 1)
        self.assertEqual(sw.select_entry(self.pas, "vertex", ["A"])[0], 0)
        self.assertEqual(sw.select_entry(self.pas, "fragment", ["A", "B"])[0], 0)   # Reihenfolge egal, lokal + global
        with self.assertRaises(sw.WrapError) as cm:
            sw.select_entry(self.pas, "fragment", ["Z"])
        self.assertIn("no fragment variant", str(cm.exception))

    def test_find_shader(self):
        inv = {"shaders": [{"name": "X/Y", "bundle": "b1"}, {"name": "X/Y", "bundle": "b2"}], "extraShaders": [{"name": "Z", "bundle": "r"}]}
        self.assertEqual(sw.find_shader(inv, "Z")["bundle"], "r")
        self.assertEqual(sw.find_shader(inv, "X/Y", "b2")["bundle"], "b2")
        with self.assertRaises(sw.WrapError):
            sw.find_shader(inv, "X/Y")
        with self.assertRaises(sw.WrapError):
            sw.find_shader(inv, "none")

    def test_ident(self):
        self.assertEqual(sw.ident("Delphis/Map/Standard"), "Delphis_Map_Standard")
        self.assertEqual(sw.ident("UI/Blur (x)"), "UI_Blur__x_")


def make_info(stage, **kw):
    info = {"stage": stage, "language": "hlsl", "cbufMask": "0x0", "constantBuffers": [], "textures": [], "inputs": [],
            "outputs": [], "outMask": "0x0", "writesDepth": False, "usesDiscard": False}
    info.update(kw)
    return info


SHADER = {
    "name": "Test/Wrap", "bundle": "b",
    "properties": [{"name": "_MainTex", "label": "Tex", "type": "Texture", "flags": 0, "attributes": [], "texDim": "2D"},
                   {"name": "_Tint", "label": "Tint", "type": "Color", "flags": 0, "attributes": [], "default": [1, 1, 1, 1]}],
    "subShaders": [{"lod": 100, "tags": {"QUEUE": "Transparent"}, "passes": [{
        "type": "Normal", "name": "FWD", "tags": {"LIGHTMODE": "FORWARDBASE"}, "state": RenderState.base, "stages": {}}]}],
}
VS_ENTRY = {"inputChannels": [{"source": 0, "target": 0}, {"source": 4, "target": 1}],
            "constantBuffers": [{"name": "VGlobals", "size": 96, "members": [mat("unity_MatrixVP", 0), vec("_Tint", 64, 4)]}],
            "cbBindings": [{"name": "VGlobals", "index": 0}], "textures": []}
FS_ENTRY = {"inputChannels": [], "constantBuffers": [{"name": "PGlobals", "size": 16, "members": [vec("_Cut", 0, 1)]}],
            "cbBindings": [{"name": "PGlobals", "index": 0}],
            "textures": [{"name": "_MainTex", "index": 0, "sampler": 0, "dim": "2D"}]}


def stages(vs_extra=None, fs_extra=None, c1=b""):
    vs_info = make_info("vs", constantBuffers=[
        {"index": 3, "size": 256, "dynamic": False}], inputs=[{"location": 0, "components": "xyzw"}, {"location": 1, "components": "xy"}],
        outputs=[{"location": 0, "components": "xy"}, {"location": 2, "components": "xyzw"}], outMask="0x5")
    fs_info = make_info("fs", constantBuffers=[{"index": 1, "size": 256, "dynamic": False}, {"index": 2, "size": 1536, "dynamic": False},
                                                {"index": 3, "size": 256, "dynamic": False}],
                        textures=[{"slot": 0, "bindless": True, "textureTableIndex": 0, "typeName": "2d", "shadow": False}],
                        inputs=[{"location": 0, "components": "xy", "interpolation": "perspective"},
                                {"location": 2, "components": "xyzw", "interpolation": "flat"},
                                {"location": 5, "components": "x", "interpolation": "perspective"}],
                        outputs=[{"renderTarget": 0, "components": "xyzw"}], writesDepth=True)
    vs_info.update(vs_extra or {})
    fs_info.update(fs_extra or {})
    return (sw.Stage("vertex", VS_ENTRY, "// VSBODY\n#ifndef MX_PRELUDE_DEFINED\n#endif\nMxVOut mx_vs(MxVIn i_, uint vid, uint iid);", vs_info, b""),
            sw.Stage("fragment", FS_ENTRY, "// FSBODY\nMxFOut mx_fs(MxFIn i_, bool front_facing);", fs_info, c1))


class Build(unittest.TestCase):
    def build(self, mode="named", **kw):
        vs, fs = stages(**kw.pop("stage_kw", {}))
        return sw.build_shader(SHADER, 0, 0, ["KW_A"], vs, fs, mode, kw.pop("renderers", "metal"),
                               kw.pop("pragmas", sw.EXACT_PRAGMAS), None, kw.pop("color_mask", None))

    def test_structure_named(self):
        text, man, warn = self.build()
        self.assertTrue(text.startswith('Shader "XNU/Generated/Test_Wrap_s0_p0_named"'))
        self.assertIn("_MainTex", text)
        self.assertIn('Tags { "QUEUE"="Transparent" }', text)
        self.assertIn("LOD 100", text)
        self.assertIn('Name "FWD"', text)
        self.assertIn('Tags { "LIGHTMODE"="FORWARDBASE" }', text)
        self.assertIn("HLSLPROGRAM", text)
        self.assertIn("#pragma target 5.0", text)
        self.assertIn("#pragma only_renderers metal", text)
        self.assertIn("#pragma disable_fastmath", text)
        self.assertIn("#pragma skip_optimizations metal", text)
        self.assertIn("#define MX_EXTERNAL_RESOURCES", text)
        # uniforms declared exactly once (the shared name _Tint appears only in the vertex block, _Cut in the fragment block)
        self.assertEqual(text.count("float4x4 unity_MatrixVP;"), 1)
        self.assertEqual(text.count("float _Cut;"), 1)
        self.assertIn("Texture2D<float4> _MainTex;", text)
        self.assertIn("SamplerState sampler_MainTex;", text)
        # Konstantenpuffer: VS Bindung 0 -> cbuf 3, FS Bindung 0 -> cbuf 3, cbuf 1 / 2 Sonderfaelle
        self.assertIn("static uint4 mxv_cb3[16];", text)
        self.assertIn("#define mx_cb3 mxv_cb3", text)
        self.assertIn("#define mx_cb3 mxf_cb3", text)
        self.assertIn("mxv_cb3[0] = uint4(asuint(unity_MatrixVP[0][0]), asuint(unity_MatrixVP[1][0]), asuint(unity_MatrixVP[2][0]), asuint(unity_MatrixVP[3][0]));", text)
        self.assertIn("mxv_cb3[4] = uint4(asuint(_Tint.x), asuint(_Tint.y), asuint(_Tint.z), asuint(_Tint.w));", text)
        self.assertIn("mxf_cb3[0] = uint4(asuint(_Cut), 0u, 0u, 0u);", text)
        self.assertIn("static uint4 mxf_cb2[96];", text)
        self.assertIn("#define mx_t0 _MainTex", text)
        self.assertIn("#define mx_s0 sampler_MainTex", text)
        self.assertIn("#define tsize0 mxf_tsize0", text)
        self.assertIn("#undef mx_cb3", text)

    def test_interface(self):
        text, man, _ = self.build()
        self.assertIn("float4 a0 : POSITION;", text)
        self.assertIn("float4 a1 : TEXCOORD0;", text)
        self.assertIn("float4 pos : SV_POSITION;", text)
        self.assertIn("float4 v0 : TEXCOORD0;", text)
        self.assertIn("nointerpolation float4 v2 : TEXCOORD2;", text)
        self.assertNotIn("v5 : TEXCOORD5", text)          # not written by the vertex shader
        self.assertIn("float4 c0 : SV_Target0;", text)
        self.assertIn("float depth : SV_Depth;", text)
        self.assertIn("r.depth = o.depth;", text)
        self.assertIn("f.pos = float4(v.pos.xyz, 1.0 / v.pos.w);", text)   # SV_Position.w: Unity liefert w, die Vorlage 1/w
        self.assertIn("MxFOut o = mx_fs(f, front);", text)
        self.assertIn("bool front : SV_IsFrontFace", text)
        self.assertEqual(man["varyings"], [{"location": 0, "interpolation": "perspective"}, {"location": 2, "interpolation": "flat"}])
        self.assertTrue(any("varyings [5]" in w for w in man["warnings"]))
        self.assertEqual(man["vertexInputs"], [{"location": 0, "semantic": "POSITION"}, {"location": 1, "semantic": "TEXCOORD0"}])
        self.assertEqual(man["textures"]["fragment"][0]["property"], "_MainTex")

    def test_array_mode(self):
        text, man, _ = self.build("array")
        self.assertIn("float4 mxav_cb3[16];", text)
        self.assertIn("float4 mxaf_cb3[16];", text)
        self.assertIn("mxv_cb3[i] = asuint(mxav_cb3[i]);", text)
        self.assertNotIn("float4x4 unity_MatrixVP;", text)
        self.assertEqual(man["arrays"], {"mxav_cb3": 16, "mxaf_cb3": 16})

    def test_int_uniform_words_are_converted(self):
        # The original reads the word as int (float(int(cb))): the float property 1.0 must not arrive as the bit pattern 0x3F800000.
        vs, fs = stages()
        fs.hlsl += "\n    r1 = asuint(float(int(mx_cb3[0][0])));\n"
        text, _, _ = sw.build_shader(SHADER, 0, 0, ["KW_A"], vs, fs, "named", "metal", sw.EXACT_PRAGMAS, None, None)
        self.assertIn("asuint(int(_Cut))", text)
        text2, _, _ = self.build()
        self.assertNotIn("asuint(int(_Cut))", text2)
        self.assertIn("asuint(_Cut)", text2)

    def test_compiler_constants_literal(self):
        c1 = (0x3F800000).to_bytes(4, "little") + (0x40000000).to_bytes(4, "little") + b"\0" * 8 + (0xDEADBEEF).to_bytes(4, "little")
        text, _, _ = self.build(stage_kw={"c1": c1})
        self.assertIn("static const uint4 mxf_cb1[2] = {", text)
        self.assertIn("uint4(0x3f800000u, 0x40000000u, 0x00000000u, 0x00000000u)", text)
        self.assertIn("uint4(0xdeadbeefu, 0x00000000u, 0x00000000u, 0x00000000u)", text)

    def instanced(self):
        vs, fs = stages(vs_extra={"constantBuffers": [{"index": 3, "size": 256, "dynamic": False},
                                                       {"index": 4, "size": 65536, "dynamic": True,
                                                        "staticMinOffset": -1, "staticEndOffset": -1}]})
        st = {"name": "unity_Builtins0Array", "offset": 0, "arraySize": 2, "structSize": 128,
              "members": [mat("unity_ObjectToWorldArray", 0), mat("unity_WorldToObjectArray", 64)]}
        vs.entry = dict(VS_ENTRY, cbBindings=VS_ENTRY["cbBindings"] + [{"name": "UnityInstancing_PerDraw0", "index": 1}],
                        constantBuffers=VS_ENTRY["constantBuffers"] + [
                            {"name": "UnityInstancing_PerDraw0", "size": 256, "members": [], "structs": [st]}])
        return vs, fs

    def test_instancing_named_mode(self):
        vs, fs = self.instanced()
        text, man, _ = sw.build_shader(SHADER, 0, 0, ["INSTANCING_ON"], vs, fs, "named")
        self.assertIn("#pragma multi_compile_instancing", text)
        self.assertNotIn("instancing_options", text)
        self.assertIn("cbuffer UnityInstancing_PerDraw0 { struct { float4x4 unity_ObjectToWorldArray;", text)
        self.assertIn("float4x4 unity_WorldToObjectArray; } unity_Builtins0Array[500]; }", text)
        self.assertIn("uint mxv_cbr4(uint off)", text)
        self.assertIn("uint e = min(off / 128u, 499u);", text)
        # word 0 = M[0][0], word 1 = M[1][0] (row of the block = column of the matrix), second matrix from word 16
        self.assertIn("case 0: return asuint(unity_Builtins0Array[e].unity_ObjectToWorldArray[0][0]);", text)
        self.assertIn("case 1: return asuint(unity_Builtins0Array[e].unity_ObjectToWorldArray[1][0]);", text)
        self.assertIn("case 16: return asuint(unity_Builtins0Array[e].unity_WorldToObjectArray[0][0]);", text)
        self.assertIn("#define mx_cbr4 mxv_cbr4", text)
        self.assertIn("#undef mx_cbr4", text)
        self.assertEqual(man["instancing"], [{"cbuf": 4, "block": "UnityInstancing_PerDraw0", "struct": "unity_Builtins0Array", "stride": 128}])

    def test_instancing_struct_padding(self):
        cb = {"name": "UnityInstancing_PerDraw2"}
        st = {"name": "unity_Builtins2Array", "structSize": 112, "members": [vec("unity_SHBrArray", 48, 4)]}
        decl = sw.instancing_decl(cb, st)
        self.assertIn("float4 mx_pad0; float4 mx_pad1; float4 mx_pad2; float4 unity_SHBrArray;", decl)
        self.assertIn("float4 mx_pad3; float4 mx_pad4; float4 mx_pad5; } unity_Builtins2Array[500]", decl)

    def test_base_instance_id_is_uint(self):
        vs, fs = stages()
        vs.entry = dict(VS_ENTRY, constantBuffers=[{"name": "VGlobals", "size": 96, "members": [vec("unity_BaseInstanceID", 0, 1)]}])
        text, _, _ = sw.build_shader(SHADER, 0, 0, [], vs, fs, "named")
        self.assertIn("uint unity_BaseInstanceID;", text)
        self.assertNotIn("asuint(unity_BaseInstanceID)", text)

    def test_storage_buffer_and_procedural_instancing(self):
        vs, fs = stages(vs_extra={"usesGlobalMemory": True, "constantBuffers": [
            {"index": 0, "size": 512, "dynamic": False, "staticMinOffset": 272, "staticEndOffset": 280},
            {"index": 3, "size": 256, "dynamic": False}]})
        vs.entry = dict(VS_ENTRY, buffers=[{"name": "unity_ParticleInstanceData", "index": 512}])
        text, man, _ = sw.build_shader(SHADER, 0, 0, ["PROCEDURAL_INSTANCING_ON"], vs, fs, "named")
        self.assertIn("ByteAddressBuffer unity_ParticleInstanceData;", text)
        self.assertIn("#define mx_gmem unity_ParticleInstanceData", text)
        self.assertIn("#pragma instancing_options procedural:mx_proc_setup", text)
        self.assertIn("void mx_proc_setup() {}", text)
        self.assertEqual(man["instancing"], [{"buffer": "unity_ParticleInstanceData"}])
        vs.info["constantBuffers"][0]["staticEndOffset"] = 296  # zweiter Speicherpuffer
        with self.assertRaises(sw.WrapError):
            sw.build_shader(SHADER, 0, 0, [], vs, fs, "named")

    def test_texture_table_uses_sampler_field(self):
        # Maxwell texture index 1 belongs to the entry with sampler == 1 (here _MainTex), not to the one with index == 1
        vs, fs = stages(fs_extra={"textures": [{"slot": 0, "bindless": True, "textureTableIndex": 1, "typeName": "2d", "shadow": False}]})
        fs.entry = dict(FS_ENTRY, textures=[{"name": "_Other", "index": 1, "sampler": 0, "dim": "2D"},
                                            {"name": "_MainTex", "index": 0, "sampler": 1, "dim": "2D"}])
        _, man, _ = sw.build_shader(SHADER, 0, 0, [], vs, fs, "named")
        self.assertEqual(man["textures"]["fragment"][0]["property"], "_MainTex")

    def test_dynamic_cbuf_needs_array_mode(self):
        dyn = {"constantBuffers": [{"index": 4, "size": 65536, "dynamic": True}]}
        with self.assertRaises(sw.WrapError) as cm:
            self.build(stage_kw={"vs_extra": dyn})
        self.assertIn("instancing", str(cm.exception))
        text, _, _ = self.build("array", stage_kw={"vs_extra": dyn})
        self.assertIn("float4 mxav_cb4[4096];", text)

    def test_unmapped_buffer_warns(self):
        _, man, _ = self.build(stage_kw={"fs_extra": {"constantBuffers": [{"index": 7, "size": 256, "dynamic": False}]}})
        self.assertTrue(any("cbuf 7" in w for w in man["warnings"]))

    def test_cbuf0_warns(self):
        _, man, _ = self.build(stage_kw={"vs_extra": {"constantBuffers": [{"index": 0, "size": 256, "dynamic": False}]}})
        self.assertTrue(any("cbuf 0" in w for w in man["warnings"]))

    def test_conflicting_uniform_types(self):
        vs, fs = stages()
        fs.entry = dict(FS_ENTRY, constantBuffers=[{"name": "PGlobals", "size": 16, "members": [vec("_Tint", 0, 3)]}])
        with self.assertRaises(sw.WrapError):
            sw.build_shader(SHADER, 0, 0, [], vs, fs)

    def test_missing_input_channel(self):
        vs, fs = stages()
        vs.entry = dict(VS_ENTRY, inputChannels=[{"source": 0, "target": 0}])
        with self.assertRaises(sw.WrapError):
            sw.build_shader(SHADER, 0, 0, [], vs, fs)

    def test_no_renderers_and_color_mask(self):
        text, _, _ = self.build(renderers="", pragmas=[], color_mask="RGBA")
        self.assertNotIn("only_renderers", text)
        self.assertNotIn("disable_fastmath", text)
        self.assertIn("ColorMask RGBA", text)
        self.assertEqual(text.count("ColorMask"), 1)

    def test_texture_without_table_index(self):
        vs, fs = stages(fs_extra={"textures": [{"slot": 0, "bindless": False, "textureTableIndex": -1, "typeName": "2d", "shadow": False}]})
        with self.assertRaises(sw.WrapError):
            sw.build_shader(SHADER, 0, 0, [], vs, fs)


class EndToEnd(unittest.TestCase):
    """wrap() with inventory, mapping and a fake translator (writes fixed outputs)."""

    FAKE = textwrap.dedent('''\
        #!/usr/bin/env python3
        import json, sys
        a = sys.argv[1:]
        out, info, c1 = a[a.index("-o") + 1], a[a.index("--info") + 1], a[a.index("--cbuf1") + 1]
        stage = a[a.index("--stage") + 1]
        mask = a[a.index("--vs-out-mask") + 1] if "--vs-out-mask" in a else ""
        if "FAIL" in open([x for x in a if x.endswith(".bin")][0]).read():
            sys.stderr.write("maxwell2msl: translation failed: hlsl: global memory\\n"); sys.exit(1)
        open(out, "w").write("// fake " + stage + " mask=" + mask + "\\n")
        open(c1, "wb").write(b"\\0" * 16)
        base = {"stage": stage, "language": "hlsl", "constantBuffers": [], "textures": [], "inputs": [], "outputs": [],
                "outMask": "0x1", "writesDepth": False, "usesDiscard": False}
        if stage == "fs":
            base["outputs"] = [{"renderTarget": 0, "components": "xyzw"}]
            base["inputs"] = [{"location": 0, "components": "xy", "interpolation": "perspective"}]
        else:
            base["inputs"] = [{"location": 0, "components": "xyzw"}]
            base["outputs"] = [{"location": 0, "components": "xy"}]
        json.dump(base, open(info, "w"))
        ''')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "blobs").mkdir()
        for h, body in (("aa", "vs"), ("bb", "fs"), ("cc", "FAIL")):
            (d / "blobs" / f"{h}.bin").write_text(body)
        fake = d / "fake_translator.py"
        fake.write_text(self.FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        shader = {"name": "T/S", "bundle": "b", "properties": [], "subShaders": [{"lod": 0, "tags": {}, "passes": [{
            "type": "Normal", "name": "", "tags": {}, "state": RenderState.base,
            "stages": {"vertex": [{"globalKeywords": [], "localKeywords": [], "inputChannels": [{"source": 0, "target": 0}],
                                   "constantBuffers": [], "cbBindings": [], "textures": []}] * 2,
                       "fragment": [{"globalKeywords": [], "localKeywords": [], "inputChannels": [], "constantBuffers": [],
                                     "cbBindings": [], "textures": []}] * 2}}]}]}
        (d / "inv.json").write_text(json.dumps({"shaders": [shader], "extraShaders": []}))
        progs = [{"id": i, "bundle": "b", "shader": "T/S", "subShader": 0, "pass": 0, "stage": st, "subProgram": sp}
                 for i, (st, sp) in enumerate([("vertex", 0), ("fragment", 0), ("vertex", 1), ("fragment", 1)])]
        (d / "map.json").write_text(json.dumps({"programs": progs}))
        (d / "pb.json").write_text(json.dumps(["aa", "bb", "cc", "bb"]))
        self.d = d
        sw.load_json.cache_clear()
        sw.program_index_cached.cache_clear()

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, **kw):
        d = self.d
        base = dict(shader="T/S", bundle="b", sub=0, pass_index=0, keywords=[], mode="named", out=str(d / "o" / "x.shader"), name=None,
                    renderers="metal", pragma=[], fast_math=False, translator_args=[], color_mask=None, inventory=str(d / "inv.json"),
                    mapping=str(d / "map.json"), prog_blob=str(d / "pb.json"), blobs=str(d / "blobs"), workdir=str(d / "work"),
                    translator=str(d / "fake_translator.py"))
        base.update(kw)
        return argparse.Namespace(**base)

    def test_wrap_writes_shader_and_manifest(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sw.wrap(self.args()), 0)
        text = (self.d / "o" / "x.shader").read_text()
        self.assertIn("// fake vs mask=", text)
        self.assertIn("// fake fs mask=1", text)     # --vs-out-mask comes from the output mask of the vertex shader
        man = json.loads((self.d / "o" / "x.wrap.json").read_text())
        self.assertEqual(man["blobs"], {"vertex": "aa", "fragment": "bb"})
        self.assertEqual(man["mode"], "named")

    def test_failing_translation_is_reported(self):
        # the fake translator rejects the blob "cc" (like maxwell2msl for global memory)
        with self.assertRaises(sw.WrapError) as cm:
            sw.run_translator(self.d / "blobs" / "cc.bin", "vs", self.d / "w2", "t", None, (), self.d / "fake_translator.py")
        self.assertIn("global memory", str(cm.exception))

    def test_main_returns_1_on_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = sw.main(["No/Such", "--out", str(self.d / "z.shader"), "--inventory", str(self.d / "inv.json"),
                          "--mapping", str(self.d / "map.json"), "--prog-blob", str(self.d / "pb.json")])
        self.assertEqual(rc, 1)
        self.assertIn("not in the inventory", err.getvalue())

    def test_unknown_keywords(self):
        with self.assertRaises(sw.WrapError):
            sw.wrap(self.args(keywords=["NOPE"]))


class AuxAndCombine(unittest.TestCase):
    SS = {"passes": [{"type": "Grab", "textureName": "_BackgroundTexture"}, {"type": "Normal"},
                     {"type": "Use", "useName": "Legacy Shaders/VertexLit/SHADOWCASTER"}, {"type": "Grab", "textureName": ""},
                     {"type": "Normal"}]}

    def test_aux_blocks(self):
        before, after = sw.aux_blocks(self.SS, 1)
        self.assertEqual(['        GrabPass { "_BackgroundTexture" }'], before)
        self.assertEqual(['        UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"'], after)
        before, after = sw.aux_blocks(self.SS, 4)
        self.assertEqual(["        GrabPass { }"], before)   # unbenannt: Unity-Standard _GrabTexture
        self.assertEqual([], after)
        self.assertEqual(([], []), sw.aux_blocks({"passes": [{"type": "Normal"}]}, 0))

    def test_parse_also(self):
        self.assertEqual((3, ["SHADOWS_DEPTH", "_SWING_ON"]), sw.parse_also("3:SHADOWS_DEPTH,_SWING_ON"))
        self.assertEqual((1, []), sw.parse_also("1"))

    def test_grab_before_and_use_after_pass(self):
        vs, fs = stages()
        before, after = sw.aux_blocks(self.SS, 1)
        text, _m, _w = sw.build_shader(SHADER, 0, 0, ["KW_A"], vs, fs, before=before, after=after)
        i_grab, i_pass, i_use = text.index("GrabPass"), text.index("        Pass\n"), text.index("UsePass")
        self.assertLess(i_grab, i_pass)
        self.assertLess(i_pass, i_use)
        plain, _m, _w = sw.build_shader(SHADER, 0, 0, ["KW_A"], vs, fs)
        self.assertNotIn("GrabPass", plain)
        self.assertEqual(1, plain.count("        Pass\n"))

    def test_combine_two_passes_into_one_subshader(self):
        vs, fs = stages()
        p1, p2 = {}, {}
        sw.build_shader(SHADER, 0, 0, ["KW_A"], vs, fs, parts=p1)
        sw.build_shader(SHADER, 0, 0, ["SHADOWS_DEPTH"], vs, fs, parts=p2)
        text = sw.combine_passes([(p1, {}), (p2, {})])
        self.assertEqual(2, text.count("        Pass\n"))
        self.assertEqual(1, text.count("    SubShader\n"))
        self.assertEqual(1, text.count('Shader "XNU/Generated/'))
        self.assertEqual(1, text.count("    Properties\n"))
        self.assertTrue(text.rstrip().endswith("}"))
        self.assertEqual(text.count("{"), text.count("}"))


class ShadowPartner(unittest.TestCase):
    @staticmethod
    def pass_(tag, keysets):
        ent = [{"globalKeywords": list(k), "localKeywords": []} for k in keysets]
        return {"type": "Normal", "tags": {"LIGHTMODE": tag}, "stages": {"vertex": ent, "fragment": ent}}

    def test_partner_selection(self):
        import shader_wrap_all as wa
        ss = {"passes": [
            self.pass_("FORWARDBASE", [("DIRECTIONAL",)]),
            self.pass_("SHADOWCASTER", [("SHADOWS_DEPTH",), ("INSTANCING_ON", "SHADOWS_DEPTH"), ("SHADOWS_DEPTH", "_ALPHATEST_ON")])]}
        self.assertEqual((1, ["SHADOWS_DEPTH"]), wa.shadow_partner(ss, 0, ("DIRECTIONAL", "SHADOWS_SCREEN")))
        self.assertEqual((1, ["INSTANCING_ON", "SHADOWS_DEPTH"]), wa.shadow_partner(ss, 0, ("DIRECTIONAL", "INSTANCING_ON")))
        self.assertEqual((1, ["SHADOWS_DEPTH", "_ALPHATEST_ON"]), wa.shadow_partner(ss, 0, ("DIRECTIONAL", "_ALPHATEST_ON", "_CASCADE_SINGLE")))
        # INSTANCING_ON without a matching variant: fall back to non-instancing
        self.assertEqual((1, ["SHADOWS_DEPTH", "_ALPHATEST_ON"]),
                         wa.shadow_partner(ss, 0, ("INSTANCING_ON", "_ALPHATEST_ON")))
        self.assertIsNone(wa.shadow_partner({"passes": [self.pass_("FORWARDBASE", [("DIRECTIONAL",)])]}, 0, ("DIRECTIONAL",)))


if __name__ == "__main__":
    unittest.main()
