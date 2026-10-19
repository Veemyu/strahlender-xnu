"""Tests für scripts/visual_compare.py – ausschließlich synthetische Bilder (keine Spielinhalte)."""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import visual_compare as vc  # noqa: E402
from visual_compare import np, Image  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parents[2] / "work" / "visual" / "auto" / "_test_tmp"


def noise_scene(w=320, h=180, seed=1):
    """Texturiertes Testbild (Gras-artiges Rauschen mit Blöcken), damit keine Flach-/Leer-Flags entstehen."""
    rng = np.random.RandomState(seed)
    lo, hi = np.array([40, 80, 20]), np.array([160, 200, 120])   # grasartige Farben: weder weiß noch magenta/cyan
    base = (lo + rng.rand(h // 4, w // 4, 3) * (hi - lo)).astype(np.uint8)
    img = np.kron(base, np.ones((4, 4, 1), dtype=np.uint8))
    img = np.clip(img.astype(np.int16) + rng.randint(-12, 12, size=img.shape), 0, 255).astype(np.uint8)
    return img


def save(path, arr):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = TMP_ROOT / self.id().split(".")[-1]
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        try:
            TMP_ROOT.rmdir()
        except OSError:
            pass


class MetricsTests(unittest.TestCase):
    def test_ssim_identical_and_different(self):
        a = noise_scene(seed=1)
        b = noise_scene(seed=2)
        self.assertAlmostEqual(vc.ssim(a, a), 1.0, places=6)
        self.assertLess(vc.ssim(a, b), 0.5)

    def test_laplace_variance_blur_lower(self):
        a = noise_scene()
        blur = (vc.box_mean(a[..., 0].astype(np.float64), 5)).astype(np.uint8)
        b = np.stack([np.pad(blur, ((0, 4), (0, 4)), mode="edge")] * 3, axis=-1)[:a.shape[0], :a.shape[1]]
        self.assertLess(vc.laplace_variance(b), vc.laplace_variance(a) * 0.2)

    def test_compare_images_numbers(self):
        a = noise_scene()
        b = np.clip(a.astype(np.int16) + 30, 0, 255).astype(np.uint8)
        r = vc.compare_images(a, b)
        self.assertGreater(r["mean_abs_diff"], 20)
        self.assertAlmostEqual(r["mean_shift"], 30, delta=6)
        self.assertEqual(r["changed_fraction"], 1.0)
        same = vc.compare_images(a, a)
        self.assertEqual(same["mean_abs_diff"], 0.0)
        self.assertEqual(same["violations"], [])

    def test_components_rectangle(self):
        m = np.zeros((50, 80), dtype=bool)
        m[10:30, 20:60] = True
        m[40:45, 5:8] = True
        cs = vc.components(m)
        self.assertEqual(len(cs), 2)
        self.assertEqual(cs[0]["area"], 800)
        self.assertEqual(cs[0]["bbox"], (20, 10, 60, 30))
        self.assertEqual(cs[0]["rect"], 1.0)

    def test_components_diagonal_connected_by_runs(self):
        m = np.zeros((10, 10), dtype=bool)
        m[0:3, 0:3] = True
        m[3:6, 2:5] = True      # überlappt in Spalte 2 mit dem ersten Block
        self.assertEqual(len(vc.components(m)), 1)


class AnomalyTests(unittest.TestCase):
    def flags(self, img, kind="field"):
        return {f["flag"] for f in vc.anomalies(img, kind)["flags"]}

    def test_good_image_has_no_flags(self):
        self.assertEqual(self.flags(noise_scene(640, 360)), set())

    def test_white_quad_flagged(self):
        img = noise_scene(640, 360)
        img[100:180, 200:330] = 255
        self.assertIn("weisse_flaeche", self.flags(img))
        self.assertNotIn("weisse_flaeche", self.flags(img, "ui"))

    def test_thin_white_curved_shape_not_flagged(self):
        img = noise_scene(640, 360)
        for i in range(0, 120):
            img[60 + i // 2:64 + i // 2, 100 + i:104 + i] = 255   # dünne Diagonale: Rechteckigkeit gering
        self.assertNotIn("weisse_flaeche", self.flags(img))

    def test_flat_water_region_flagged(self):
        img = noise_scene(640, 360)
        img[200:360, 0:640] = (68, 155, 250)
        self.assertIn("flach_gross", self.flags(img))
        self.assertNotIn("flach_gross", self.flags(img, "room"))

    def test_black_side_bars(self):
        img = noise_scene(640, 360)
        img[:, :40] = 0
        img[:, -40:] = 0
        an = vc.anomalies(img)
        self.assertIn("balken", {f["flag"] for f in an["flags"]})
        self.assertEqual(an["stats"]["content_box"], [40, 0, 600, 360])

    def test_magenta_and_cyan(self):
        img = noise_scene(640, 360)
        img[10:60, 10:90] = (255, 0, 255)
        img[100:150, 10:90] = (0, 255, 255)
        f = self.flags(img)
        self.assertIn("magenta", f)
        self.assertIn("cyan", f)
        self.assertIn("magenta", self.flags(img, "ui"))

    def test_empty_and_mean_out_of_range(self):
        black = np.zeros((90, 160, 3), dtype=np.uint8)
        self.assertIn("leer_konstant", self.flags(black))
        white = np.full((90, 160, 3), 255, dtype=np.uint8)
        f = self.flags(white)
        self.assertIn("leer_konstant", f)
        self.assertIn("mittel_ausserhalb", f)

    def test_large_black_area(self):
        img = noise_scene(640, 360)
        img[40:340, 150:500] = 0
        self.assertIn("schwarze_flaeche", self.flags(img))

    def test_hud_text_cluster(self):
        img = noise_scene(1280, 720)
        img[:90, :400] = 20
        rng = np.random.RandomState(5)
        for i in range(60):
            x, y = rng.randint(5, 380), rng.randint(5, 80)
            img[y:y + 6, x:x + 3] = 255
        self.assertIn("hud_text", self.flags(img))

    def test_allowed_flag_not_active(self):
        img = noise_scene(640, 360)
        img[100:180, 200:330] = 255
        res = vc.anomalies(img, "field", allow=["weisse_flaeche"])
        self.assertEqual(vc.active_flags(res), [])
        self.assertEqual(vc.error_flags(res), [])


class EvaluateTests(Tmp):
    def make_run(self, name, imgs):
        for n, a in imgs.items():
            save(self.tmp / name / "shots" / (n + ".png"), a)
        return self.tmp / name

    def test_regression_exit_codes_and_report(self):
        good = noise_scene(seed=3)
        base = self.make_run("base", {"a": good, "b": noise_scene(seed=4)})
        # Lauf 1: identisch -> kein Problem
        run1 = self.make_run("run1", {"a": good, "b": noise_scene(seed=4)})
        rep, code = vc.evaluate(run1, base, {}, log=lambda *_: None)
        self.assertEqual(code, 0)
        self.assertTrue((run1 / "report.md").is_file())
        self.assertTrue((run1 / "report.json").is_file())
        sheets = list((run1 / "contact").glob("*.png"))
        self.assertTrue(any(p.name.startswith("uebersicht") for p in sheets))
        self.assertTrue(any(p.name.startswith("vergleich") for p in sheets))
        md = (run1 / "report.md").read_text(encoding="utf-8")
        self.assertIn("Zur manuellen/Agenten-Sichtung", md)
        # Lauf 2: Bild a stark verändert + weiße Quads -> Regression
        bad = good.copy()
        bad[20:100, 50:200] = 255
        bad = np.clip(bad.astype(np.int16) + 70, 0, 255).astype(np.uint8)
        run2 = self.make_run("run2", {"a": bad, "b": noise_scene(seed=4)})
        rep, code = vc.evaluate(run2, base, {}, log=lambda *_: None)
        self.assertEqual(code, 1)
        ra = next(r for r in rep["images"] if r["name"] == "a")
        self.assertTrue(ra["violations"])
        self.assertTrue((run2 / "diff" / "a.png").is_file())

    def test_known_flags_in_baseline_do_not_regress(self):
        quad = noise_scene(seed=3)
        quad[20:100, 50:200] = 255
        base = self.make_run("base", {"a": quad})
        run = self.make_run("run", {"a": quad})
        rep, code = vc.evaluate(run, base, {}, log=lambda *_: None)
        self.assertEqual(code, 0)
        self.assertIn("weisse_flaeche", rep["images"][0]["flags"])
        self.assertEqual(rep["images"][0]["new_flags"], [])

    def test_missing_requested_scenario_fails_and_strict_new(self):
        run = self.make_run("run", {"a": noise_scene()})
        (run / "capture.json").write_text(json.dumps({"requested": ["a", "b"]}), encoding="utf-8")
        rep, code = vc.evaluate(run, None, {"a": {}, "b": {}}, log=lambda *_: None)
        self.assertEqual(code, 1)
        self.assertEqual(rep["summary"]["missing"], 1)
        # nicht angeforderte Szenarien zählen nicht als fehlend
        (run / "capture.json").write_text(json.dumps({"requested": ["a"]}), encoding="utf-8")
        rep, code = vc.evaluate(run, None, {"a": {}, "b": {}}, log=lambda *_: None)
        self.assertEqual(code, 0)
        # --strict: Fehlerflag ohne Baseline
        quad = noise_scene()
        quad[20:100, 50:200] = 255
        run2 = self.make_run("run2", {"q": quad})
        rep, code = vc.evaluate(run2, None, {}, strict=True, log=lambda *_: None)
        self.assertEqual(code, 1)
        rep, code = vc.evaluate(run2, None, {}, strict=False, log=lambda *_: None)
        self.assertEqual(code, 0)

    def test_accept_roundtrip(self):
        run = self.make_run("run", {"a": noise_scene()})
        base = self.tmp / "baseline"
        vc.accept_run(run, base, {}, log=lambda *_: None)
        self.assertTrue((base / "shots" / "a.png").is_file())
        meta = json.loads((base / "baseline.json").read_text(encoding="utf-8"))
        self.assertIn("a", meta["images"])
        vc.accept_run(run, base, {}, log=lambda *_: None)
        self.assertTrue((self.tmp / "baseline.alt" / "shots" / "a.png").is_file())


if __name__ == "__main__":
    unittest.main()
