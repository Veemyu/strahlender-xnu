"""Tests für scripts/visual_ref.py (Ryujinx-Referenzvergleich) – synthetische Bilder."""
import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import visual_ref as vr  # noqa: E402
import visual_compare as vc  # noqa: E402
from visual_compare import np, Image  # noqa: E402
from test_visual_compare import noise_scene, save, Tmp  # noqa: E402


MAP = {
    "normalize": {"width": 320, "height": 180, "crop_bars": True},
    "compare": {"grid": [8, 8], "cell_bad_mad": 28.0, "max_shift_px": 24, "gates": {"ssim_matched_min": 0.5}},
    "views": [
        {"view": "ref_a", "unity": ["u_a"], "mask": [[0, 0, 0.3, 0.2]]},
        {"view": "ref_b", "unity": ["u_b"]},
        {"view": "ref_c", "unity": ["u_c"], "optional": True},
    ],
}


class NormalizeTests(unittest.TestCase):
    def test_bars_and_aspect(self):
        img = noise_scene(640, 360)
        padded = np.zeros((400, 800, 3), dtype=np.uint8)
        padded[20:380, 80:720] = img
        n = vr.normalize(padded, 320, 180)
        self.assertEqual(n.shape, (180, 320, 3))
        self.assertGreater(float(n.mean()), 40)   # Ränder weg
        wide = noise_scene(800, 300)
        self.assertEqual(vr.normalize(wide, 320, 180).shape, (180, 320, 3))

    def test_game_hour(self):
        self.assertAlmostEqual(vr.game_hour(12 * 3600, 0), 12.0)
        self.assertAlmostEqual(vr.game_hour(12 * 3600, -1800), 11.5)
        self.assertAlmostEqual(vr.game_hour(0, -3600), 23.0)


class CompareTests(unittest.TestCase):
    def test_brightness_and_shift_compensated(self):
        ref = noise_scene(320, 180, seed=7)
        ref[60:120, 100:220] = (200, 90, 60)
        uni = np.clip(ref.astype(np.float32) * 0.7 + 8, 0, 255).astype(np.uint8)
        uni = np.roll(uni, (4, -8), axis=(0, 1))
        m, *_ = vr.compare_pair(ref, uni, None, max_shift=24)
        self.assertEqual(m["shift"], [8, -4])
        self.assertLess(m["mad_matched"], m["mad"])
        self.assertLess(m["mad_matched"], 6)
        self.assertGreater(m["ssim_matched"], 0.6)
        self.assertLess(m["laplace_ratio"], 0.8)
        self.assertEqual(m["bad_cells"], 0)

    def test_color_cast_and_bad_cell(self):
        ref = noise_scene(320, 180, seed=7)
        uni = ref.copy()
        uni[:, :, 0] = np.clip(uni[:, :, 0].astype(np.int16) + 60, 0, 255).astype(np.uint8)
        m, *_ = vr.compare_pair(ref, uni, None, align=False)
        self.assertGreater(m["color_cast"][0], 1.15)
        uni2 = ref.copy()
        uni2[0:22, 0:40] = 255 - uni2[0:22, 0:40]      # Zelle A1 zerstört
        m2, *_ = vr.compare_pair(ref, uni2, None, align=False)
        self.assertEqual(m2["worst_cells"][0]["cell"], "A1")
        self.assertGreaterEqual(m2["bad_cells"], 1)

    def test_mask_excludes_region(self):
        ref = noise_scene(320, 180, seed=7)
        uni = ref.copy()
        uni[0:36, 0:96] = 0       # Debug-Text-Bereich
        masked, *_ = vr.compare_pair(ref, uni, [[0, 0, 0.3, 0.2]], align=False)
        unmasked, *_ = vr.compare_pair(ref, uni, None, align=False)
        self.assertLess(masked["mad"], unmasked["mad"] * 0.2)
        self.assertLess(masked["valid_fraction"], 1.0)

    def test_match_hist_identity_on_equal(self):
        a = noise_scene(64, 36)
        v = np.ones(a.shape[:2], dtype=bool)
        out = vr.match_hist(a, a, v)
        self.assertLess(float(np.abs(out.astype(int) - a.astype(int)).mean()), 1.5)


class ImportAndRunTests(Tmp):
    def test_import_order_rename_and_idempotent(self):
        raw = self.tmp / "raw"
        dest = self.tmp / "ref"
        t = time.time() - 100
        for i, name in enumerate(["s1.png", "s2.png", "ref_b__x.png", "x.png", "free_r_1__y.png"]):
            save(raw / name, noise_scene(640, 360, seed=i))
            os.utime(raw / name, (t + i, t + i))
        done, state = vr.import_new(raw, dest, MAP, offset_seconds=-1800, log=lambda *_: None)
        views = {n: v for n, v, _ in done}
        self.assertEqual(views["ref_b__x.png"], "ref_b")          # Umbenennung belegt die Ansicht
        self.assertEqual(views["s1.png"], "ref_a")                # Reihenfolge füllt die freien Ansichten
        self.assertEqual(views["s2.png"], "ref_c")
        self.assertEqual(views["free_r_1__y.png"], "free_r_1")
        self.assertNotIn("x.png", views)                           # Original einer umbenannten Kopie wird nicht noch einmal zugeordnet
        self.assertTrue((dest / "views" / "ref_a.png").is_file())
        with Image.open(dest / "views" / "ref_a.png") as im:
            self.assertEqual(im.size, (320, 180))
        again, _ = vr.import_new(raw, dest, MAP, log=lambda *_: None)
        self.assertEqual(again, [])
        # --since ignoriert ältere Dateien
        save(raw / "old.png", noise_scene(64, 36))
        os.utime(raw / "old.png", (t - 1000, t - 1000))
        again, st = vr.import_new(raw, dest, MAP, log=lambda *_: None, since=t - 500)
        self.assertEqual(again, [])
        self.assertTrue(st["files"]["old.png"]["ignored"])

    def test_compare_run_writes_report_and_sheet(self):
        refd = self.tmp / "ref"
        ref = noise_scene(1280, 720, seed=2)
        save(refd / "views" / "ref_a.png", ref)
        save(refd / "views" / "ref_b.png", noise_scene(1280, 720, seed=9))
        (refd / "assignments.json").write_text(json.dumps({"views": {"ref_a": {"file": "x", "game_hour": 12.2}}}), encoding="utf-8")
        run = self.tmp / "run"
        save(run / "shots" / "u_a.png", np.clip(ref.astype(np.int16) - 20, 0, 255).astype(np.uint8))
        save(run / "shots" / "u_b.png", noise_scene(1280, 720, seed=11))
        rep, code = vr.compare_run(run, refd, MAP, gate=True, log=lambda *_: None)
        by = {r["view"]: r for r in rep["results"]}
        self.assertEqual(by["ref_a"]["status"], "verglichen")
        self.assertEqual(by["ref_a"]["game_hour"], 12.2)
        self.assertGreater(by["ref_a"]["metrics"]["ssim_matched"], 0.8)
        self.assertEqual(by["ref_c"]["status"], "keine Referenz")
        self.assertEqual(code, 1)                                   # ref_b ist unabhängig -> Schwelle verletzt
        self.assertIn("ref_b", rep["problems"][0])
        self.assertTrue((run / "ref_report.md").is_file())
        self.assertTrue((run / "contact" / "ref_01.png").is_file())
        self.assertTrue((run / "ref" / "ref_a_heatmap.png").is_file())
        rep2, code2 = vr.compare_run(run, refd, MAP, gate=False, log=lambda *_: None)
        self.assertEqual(code2, 0)

    def test_import_recomp_by_name_alias_and_change(self):
        raw1, raw2 = self.tmp / "mac", self.tmp / "linux"
        dest = self.tmp / "recomp"
        amap = json.loads(json.dumps(MAP))
        amap["views"][1]["aliases"] = ["gate2_b"]
        save(raw1 / "ref_a__x.png", noise_scene(640, 360, seed=1))
        save(raw1 / "gate2_b_metal.png", noise_scene(1920, 1080, seed=2))
        save(raw1 / "frame_01200.png", noise_scene(64, 36, seed=3))          # nicht zugeordnet: übergangen
        save(raw2 / "free_t__y.png", noise_scene(320, 180, seed=4))
        done, st = vr.import_recomp([raw1, raw2], dest, amap, log=lambda *_: None)
        self.assertEqual(sorted(v for _, v in done), ["free_t", "ref_a", "ref_b"])
        self.assertNotIn("frame_01200.png", json.dumps(st["files"]))
        with Image.open(dest / "views" / "ref_b.png") as im:
            self.assertEqual(im.size, (320, 180))
        again, _ = vr.import_recomp([raw1, raw2], dest, amap, log=lambda *_: None)
        self.assertEqual(again, [])
        save(raw1 / "gate2_b_metal.png", noise_scene(1920, 1080, seed=9))      # Datei geändert -> erneut
        again, _ = vr.import_recomp([raw1, raw2], dest, amap, log=lambda *_: None)
        self.assertEqual([v for _, v in again], ["ref_b"])
        everything, _ = vr.import_recomp([raw1], self.tmp / "r2", amap, log=lambda *_: None, all_free=True)
        self.assertIn("free_frame_01200", [v for _, v in everything])

    def test_refs_compare_two_sources(self):
        a, b = self.tmp / "a", self.tmp / "b"
        base = noise_scene(1280, 720, seed=5)
        save(a / "views" / "ref_a.png", np.clip(base.astype(np.int16) + 15, 0, 255).astype(np.uint8))
        save(b / "views" / "ref_a.png", base)
        save(b / "views" / "ref_b.png", base)
        rep = vr.refs_compare(a, b, MAP, self.tmp / "out", "recomp", "ryujinx", log=lambda *_: None)
        by = {r["view"]: r for r in rep["results"]}
        self.assertEqual(by["ref_a"]["status"], "verglichen")
        self.assertGreater(by["ref_a"]["metrics"]["ssim_matched"], 0.9)
        self.assertIn("recomp", by["ref_b"]["status"])
        md = (self.tmp / "out" / "ref_report.md").read_text(encoding="utf-8")
        self.assertIn("Quellenvergleich (recomp ↔ ryujinx)", md)

    def test_cache_report(self):
        used = self.tmp / "used.json"
        used.write_text(json.dumps([{"shader": "a", "keywords": []}] * 120), encoding="utf-8")
        txt = vr.cache_report(["guest=19584:1222", "vulkan_nvidia=45376:0"], used)
        self.assertIn("1222 Einträge", txt)
        self.assertIn("2834 Einträge", txt)
        self.assertIn("120", txt)
        self.assertIn("10.2", txt)


if __name__ == "__main__":
    unittest.main()
