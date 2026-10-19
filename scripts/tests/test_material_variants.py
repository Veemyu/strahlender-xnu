"""Tests fuer scripts/material_variants.py und scripts/material_export.py (synthetisch, ohne Spielinhalt, ohne UnityPy)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import material_export as me  # noqa: E402
import material_variants as mv  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "unity" / "Assets" / "Tests" / "EditMode" / "Fixtures" / "variant_resolution_cases.json"


class VariantCases(unittest.TestCase):
    def test_shared_cases(self):
        data = json.loads(FIXTURE.read_text())
        idx = mv.Index(data["variants"])
        for c in data["cases"]:
            with self.subTest(c["name"]):
                r = mv.resolve(idx, c["shader"], c["pass"], c["keywords"], c["instancing"])
                e = c["expect"]
                self.assertEqual(r["file"], e["file"])
                self.assertEqual(r["quality"], e["quality"])
                for k in ("role", "ignored", "missing"):
                    if k in e:
                        self.assertEqual(r[k], e[k], k)

    def test_role_detection(self):
        self.assertEqual(mv.role_of({"SHADOWS_DEPTH"}), "shadow")
        self.assertEqual(mv.role_of({"DIRECTIONAL"}), "forward")
        self.assertEqual(mv.role_of({"DIRECTIONAL"}, "SHADOWCASTER"), "shadow")
        self.assertEqual(mv.role_of(set(), "FORWARDADD"), "add")
        self.assertEqual(mv.role_of({"SHADOWS_DEPTH"}, "FORWARDBASE"), "forward")


class Export(unittest.TestCase):
    def material(self):
        return {
            "m_Name": "M_Test", "m_Shader": {"m_FileID": 1, "m_PathID": 42}, "m_ShaderKeywords": "_B _A",
            "m_CustomRenderQueue": 2450, "stringTagMap": [["RenderType", "TransparentCutout"]], "disabledShaderPasses": ["X"],
            "m_EnableInstancingVariants": True,
            "m_SavedProperties": {
                "m_TexEnvs": [["_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 7}, "m_Scale": {"x": 2.0, "y": 3.0}, "m_Offset": {"x": 0.5, "y": 0.0}}],
                              ["_BumpTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 0}, "m_Scale": {"x": 1.0, "y": 1.0}, "m_Offset": {"x": 0.0, "y": 0.0}}]],
                "m_Floats": [["_Cutoff", 0.25]],
                "m_Colors": [["_Color", {"r": 1.0, "g": 0.5, "b": 0.25, "a": 1.0}]],
            },
        }

    def test_convert(self):
        inv = {"shaders": [{"bundle": "shaders", "pathId": 42, "name": "Test/Lit"}], "extraShaders": []}
        res = me.ShaderResolver(inv, {"CAB-abc": "shaders"})
        m = me.convert_material(self.material(), ["archive:/CAB-abc/CAB-abc"], res,
                                {(0, 7): {"texName": "T_Test", "width": 64, "height": 32, "format": 12}})
        self.assertEqual(m["shader"], "Test/Lit")
        self.assertEqual(m["keywords"], ["_A", "_B"])
        self.assertEqual(m["renderQueue"], 2450)
        self.assertEqual(m["tags"], {"RenderType": "TransparentCutout"})
        self.assertTrue(m["instancing"])
        self.assertEqual(m["floats"], {"_Cutoff": 0.25})
        self.assertEqual(m["colors"]["_Color"], [1.0, 0.5, 0.25, 1.0])
        self.assertEqual(m["textures"]["_MainTex"]["texName"], "T_Test")
        self.assertEqual(m["textures"]["_MainTex"]["scale"], [2.0, 3.0])
        self.assertNotIn("pathId", m["textures"]["_BumpTex"])

    def test_unknown_shader(self):
        res = me.ShaderResolver({"shaders": [], "extraShaders": []}, {})
        m = me.convert_material(self.material(), ["archive:/CAB-zzz/CAB-zzz"], res)
        self.assertIsNone(m["shader"])
        self.assertEqual(m["shaderRef"], [1, 42])

    def test_local_shader_ref_is_not_resolved(self):
        res = me.ShaderResolver({"shaders": [{"bundle": "shaders", "pathId": 42, "name": "X"}], "extraShaders": []}, {"CAB-abc": "shaders"})
        self.assertIsNone(res.resolve(0, 42, []))


if __name__ == "__main__":
    unittest.main()
