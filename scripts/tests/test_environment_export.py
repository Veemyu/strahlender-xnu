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


if __name__ == "__main__":
    unittest.main()
