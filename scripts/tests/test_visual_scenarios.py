"""Tests für scripts/visual_scenarios.py und die mitgelieferte Szenarioliste."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import visual_scenarios as vs  # noqa: E402
from test_visual_compare import Tmp  # noqa: E402


class RealFileTests(unittest.TestCase):
    def setUp(self):
        self.data = vs.load()

    def test_shipped_file_valid(self):
        self.assertEqual(vs.validate(self.data), [])

    def test_required_zones_present(self):
        zones = {s["zone"] for s in vs.merged(self.data) if s["runner"] == "field"}
        self.assertTrue({422, 425, 54, 367, 167} <= zones)
        names = [s["name"] for s in vs.merged(self.data)]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(s["width"] == 1280 and s["height"] == 720 for s in vs.merged(self.data)))

    def test_export_and_hours(self):
        exp = vs.export_field(self.data, tag="quick")
        self.assertTrue(all(i["width"] == 1280 for i in exp["items"]))
        self.assertTrue(any(i["name"] == "field_z167_h12" and i["hasCell"] for i in exp["items"]))
        exp2 = vs.export_field(self.data, hours={"field_z167_h12": 11.93})
        self.assertEqual(next(i for i in exp2["items"] if i["name"] == "field_z167_h12")["hour"], 11.93)

    def test_sequences_end_with_quit_and_cover_shots(self):
        for seq in self.data["sequences"].values():
            self.assertEqual(seq["lines"][-1], "quit")
        game = {s["name"] for s in vs.merged(self.data) if s["runner"] == "game"}
        shots = {n for s in self.data["sequences"].values() for n in vs.shots_of(s)}
        self.assertEqual(game, shots)

    def test_ref_map_points_to_known_scenarios(self):
        ref = json.loads((Path(vs.ROOT) / "scripts" / "visual" / "ref_map.json").read_text(encoding="utf-8"))
        names = {s["name"] for s in vs.merged(self.data)}
        for v in ref["views"]:
            for u in v["unity"]:
                self.assertIn(u, names)


class ValidateTests(unittest.TestCase):
    def test_detects_errors(self):
        bad = {"defaults": {"width": 1280, "height": 720, "runner": "field", "kind": "field", "hour": 12, "settle_frames": 10},
               "sequences": {"s": {"lines": ["shot x", "wait 1"]}},
               "scenarios": [{"name": "a", "zone": 1, "facing": "up"}, {"name": "a", "zone": 1, "cell": [1, 2], "facing": "north"},
                             {"name": "g", "runner": "game", "kind": "ui", "sequence": "s"}]}
        errs = "\n".join(vs.validate(bad))
        self.assertIn("cell oder locator", errs)
        self.assertIn("doppelt", errs)
        self.assertIn("facing", errs)
        self.assertIn("kein 'shot g'", errs)
        self.assertIn("ohne Szenario", errs)
        self.assertIn("quit", errs)


class MarkTests(Tmp):
    def test_mark_requested_union(self):
        vs.mark_requested(self.tmp, ["a", "b"], "editor")
        vs.mark_requested(self.tmp, ["b", "c"])
        cap = json.loads((self.tmp / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(cap["requested"], ["a", "b", "c"])
        self.assertEqual(cap["mode"], "editor")


if __name__ == "__main__":
    unittest.main()
