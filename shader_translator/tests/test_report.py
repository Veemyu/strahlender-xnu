#!/usr/bin/env python3
"""Tests fuer survey_report.py mit synthetischen Eingaben (keine Spieldaten)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import survey_report as sr  # noqa: E402


def entry(h, stage, code, programs, bundles=("shaders",)):
    return {"hash": h, "stage": stage, "size": 100, "codeHash": code, "programs": programs, "bundles": list(bundles), "shaders": ["S"]}


def row(h, translatable, unknown=(), forms=(), us=10, insts=5):
    return {"file": f"x/{h}.bin", "stage": "fs", "bytes": 100, "insts": insts, "translatable": translatable, "us": us,
            "unknownOpcodes": [{"name": n, "bits": "0x000", "count": c, "example": "0x0"} for n, c in unknown],
            "unsupportedForms": [{"name": n, "count": c, "example": "0x0"} for n, c in forms]}


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        d = Path(self.tmp.name)
        index = {"blobs": [
            entry("a", "vs", "c1", 10),
            entry("b", "fs", "c2", 5),               # nur bindless
            entry("c", "fs", "c3", 3),               # bindless + HSETP2
            entry("d", "fs", "c3", 2),               # gleicher Code wie c, anderer Blob (Konstanten)
            entry("e", "fs", "c4", 1, ("fxparticle",)),  # nur HSETP2
        ]}
        rows = [row("a", True), row("b", False, forms=[("bindless tex", 2)]),
                row("c", False, unknown=[("op7e8", 1)], forms=[("bindless tex", 1)]),
                row("d", False, unknown=[("op7e8", 1)], forms=[("bindless tex", 1)]),
                row("e", False, unknown=[("op7e8", 4)])]
        (d / "index.json").write_text(json.dumps(index))
        (d / "survey.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.d = d

    def tearDown(self):
        self.tmp.cleanup()

    def rep(self, bundles=None):
        shaders = sr.load(self.d / "index.json", self.d / "survey.jsonl", bundles)
        return sr.summarize(shaders)

    def test_counts(self):
        cov = self.rep()["coverage"]
        self.assertEqual((cov["all"]["blobs"], cov["all"]["blobsOk"]), (5, 1))
        self.assertEqual((cov["all"]["codes"], cov["all"]["codesOk"]), (4, 1))
        self.assertEqual((cov["all"]["programs"], cov["all"]["programsOk"]), (21, 10))
        self.assertEqual((cov["vs"]["blobs"], cov["vs"]["blobsOk"]), (1, 1))
        self.assertEqual((cov["fs"]["blobs"], cov["fs"]["blobsOk"]), (4, 0))

    def test_ranking(self):
        miss = {m["name"]: m for m in self.rep()["missing"]}
        self.assertEqual(miss["bindless tex"]["blobs"], 3)
        self.assertEqual(miss["bindless tex"]["codes"], 2)
        self.assertEqual(miss["bindless tex"]["occurrences"], 4)
        self.assertEqual(miss["bindless tex"]["blockedOnlyByThis"], 1)
        self.assertEqual(miss["op7e8"]["blobs"], 3)
        self.assertEqual(miss["op7e8"]["blockedOnlyByThis"], 1)
        self.assertEqual(miss["op7e8"]["programs"], 3 + 2 + 1)
        self.assertIn("HSETP2", miss["op7e8"]["meaning"])

    def test_greedy_reaches_everything(self):
        rep = self.rep()
        order = [g["implement"] for g in rep["greedyOrder"]]
        self.assertEqual(set(order), {"form:bindless tex", "unknown:op7e8"})
        self.assertEqual(rep["greedyOrder"][-1]["cumulativeBlobs"], 5)
        self.assertEqual(rep["greedyOrder"][-1]["cumulativeProgramShare"], 1.0)
        self.assertEqual(rep["stillBlockedAfterGreedy"], 0)

    def test_bundle_filter(self):
        cov = self.rep(["fxparticle"])["coverage"]
        self.assertEqual(cov["all"]["blobs"], 1)

    def test_timing_and_render(self):
        rep = self.rep()
        self.assertEqual(rep["timing"]["shaders"], 5)
        self.assertEqual(rep["timing"]["instructionsTotal"], 25)
        text = sr.render(rep, None, 1.5)
        self.assertIn("bindless tex", text)
        self.assertIn("Wandzeit des Laufs 1.5 s", text)

    def test_input_error_counts_as_problem(self):
        d = self.d
        rows = [json.loads(line) for line in (d / "survey.jsonl").read_text().splitlines()]
        rows[0] = {"file": "x/a.bin", "inputError": "kaputt"}
        (d / "survey.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.assertEqual(self.rep()["coverage"]["all"]["blobsOk"], 0)


if __name__ == "__main__":
    unittest.main()
