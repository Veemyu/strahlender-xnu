import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import environment_export as ee  # noqa: E402


def rec(cls, name, data, pid):
    return {"class": cls, "name": name, "data": data, "path_id": pid}


class EnvironmentExportTests(unittest.TestCase):
    def test_zone_mapping_and_stats(self):
        env_a = rec("EnvironmentSettings", "A", {"CloudShadowEnable": 1, "Morning": {"x": 1}, "Daytime": {"x": 2}, "FogMode": 2}, 10)
        env_b = rec("EnvironmentSettings", "B", {"FixedTime": 1}, 11)
        zones = [
            {"RenderSettings": {"m_FileID": 0, "m_PathID": 10}, "ZoneID": 5, "Weather": 2, "FixedTime": 1, "ReflectionCamera": 0},
            {"RenderSettings": {"m_FileID": 0, "m_PathID": 0}, "ZoneID": 6, "Weather": 0, "FixedTime": 0, "ReflectionCamera": 1},
            {"RenderSettings": {"m_FileID": 0, "m_PathID": 10}, "ZoneID": 7},
        ]
        mi = rec("MapInfo", "m", {"ZoneData": zones}, 1)
        other = rec("FieldEncountTable", "t", {}, 2)
        s, z, st = ee.build_documents([env_a, env_b, mi, other])
        self.assertEqual(["A", "B"], [x["name"] for x in s["settings"]])
        self.assertTrue(s["settings"][0]["cloudShadowEnable"])
        self.assertEqual({"Morning", "Daytime"}, set(s["settings"][0]["periods"]))
        self.assertEqual(["A", None, "A"], [x["settings"] for x in z["zones"]])
        self.assertEqual(2, z["zones"][0]["weather"])
        self.assertTrue(z["zones"][0]["fixedTime"])
        self.assertEqual({"settings": 2, "zones": 3, "zonesWithSettings": 2, "settingsUsedByZones": 1}, st)

    def test_ignores_other_classes(self):
        s, z, st = ee.build_documents([rec("Other", "o", {}, 1)])
        self.assertEqual([], s["settings"])
        self.assertEqual([], z["zones"])

    def test_scene_document(self):
        ctrl = {"_ShadowDistance": 45.0, "_ShadowNearPlaneOffset": 15.0, "_CloudSpeed": {"x": 0.5, "y": 0.25},
                "_CloudTiling": {"x": 0.1, "y": 0.2}, "_ShadowColor": {"r": 0.1, "g": 0.2, "b": 0.3, "a": 1.0},
                "_NoiseTex": {"m_FileID": 0, "m_PathID": 7}, "_SnowTex": {"m_FileID": 2, "m_PathID": 9},
                "_CloudShadowTex": {"m_FileID": 0, "m_PathID": 0}}
        render = {"m_Fog": False, "m_AmbientMode": 0, "m_SkyboxMaterial": {"m_FileID": 0, "m_PathID": 0},
                  "m_AmbientSkyColor": {"r": 1, "g": 0.5, "b": 0, "a": 1}}
        cam = {"m_ClearFlags": 2, "m_BackGroundColor": {"r": 0, "g": 0, "b": 0, "a": 0}, "m_CullingMask": {"m_Bits": 5}, "m_HDR": True}
        light = {"m_Type": 1, "m_Intensity": 1.5, "m_Shadows": {"m_Type": 2, "m_Bias": 0.05, "m_NormalBias": 0.4}}
        d = ee.scene_document(ctrl, render, {7: "noise"}, [("Main Camera", cam)], [("Sun", light)])
        c = d["controller"]
        self.assertEqual(45.0, c["_ShadowDistance"])
        self.assertEqual([0.5, 0.25], c["cloudSpeed"])
        self.assertEqual([0.1, 0.2, 0.3, 1.0], c["shadowColor"])
        self.assertEqual({"_NoiseTex": "noise", "_SnowTex": "extern", "_CloudShadowTex": None, "_SnowNormalTex": None,
                          "_EnvironmentMap": None}, c["textures"])
        self.assertFalse(d["renderSettings"]["skybox"])
        self.assertEqual([1, 0.5, 0, 1], d["renderSettings"]["ambientSky"])
        self.assertEqual(2, d["cameras"][0]["clearFlags"])
        self.assertEqual(5, d["cameras"][0]["cullingMask"])
        self.assertEqual(2, d["lights"][0]["shadows"])


if __name__ == "__main__":
    unittest.main()
