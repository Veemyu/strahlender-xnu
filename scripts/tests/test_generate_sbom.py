"""SBOM generator tests: the output must be valid SPDX/CycloneDX structure and cover the Cargo lock."""
import importlib.util
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("generate_sbom", ROOT / "scripts/sbom/generate_sbom.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)


class SbomGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.components = gen.build_components()
        gen.write_outputs(cls.out, cls.components, gen.root_component())
        cls.spdx = json.loads((cls.out / "strahlender-xnu.spdx.json").read_text(encoding="utf-8"))
        cls.cdx = json.loads((cls.out / "strahlender-xnu.cdx.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_spdx_identifiers_are_unique_and_valid(self):
        ids = [p["SPDXID"] for p in self.spdx["packages"]]
        self.assertEqual(len(ids), len(set(ids)))
        for spdx_id in ids:
            self.assertRegex(spdx_id, r"^SPDXRef-[A-Za-z0-9.-]+$")

    def test_every_relationship_points_to_a_known_element(self):
        known = {p["SPDXID"] for p in self.spdx["packages"]} | {"SPDXRef-DOCUMENT"}
        for rel in self.spdx["relationships"]:
            self.assertIn(rel["spdxElementId"], known)
            self.assertIn(rel["relatedSpdxElement"], known)

    def test_every_cargo_lock_package_is_listed_with_checksum(self):
        lock = tomllib.loads((ROOT / "installer/Cargo.lock").read_text(encoding="utf-8"))
        registry = [p for p in lock["package"] if "source" in p]
        crates = {c["purl"]: c for c in self.components.values() if c["category"] == "rust-crate"}
        for pkg in registry:
            purl = f"pkg:cargo/{pkg['name']}@{pkg['version']}"
            self.assertIn(purl, crates, purl)
            self.assertEqual(crates[purl]["sha256"], pkg["checksum"], purl)

    def test_no_duplicate_purls_in_catalogue(self):
        purls = [c["purl"] for c in gen.CATALOG]
        self.assertEqual(len(purls), len(set(purls)))

    def test_licence_expressions_use_spdx_operators(self):
        for comp in self.components.values():
            # Cargo's 'MIT/Apache-2.0' must have been turned into 'MIT OR Apache-2.0'.
            self.assertNotIn("/", comp["license"], comp["purl"])
        self.assertEqual(gen.normalize_license("MIT/Apache-2.0"), "MIT OR Apache-2.0")
        self.assertEqual(gen.normalize_license("Unlicense/MIT"), "Unlicense OR MIT")

    def test_cyclonedx_refs_are_unique_and_dependencies_resolve(self):
        refs = [c["bom-ref"] for c in self.cdx["components"]]
        self.assertEqual(len(refs), len(set(refs)))
        known = set(refs) | {"root"}
        for dep in self.cdx["dependencies"]:
            self.assertIn(dep["ref"], known)
            for target in dep["dependsOn"]:
                self.assertIn(target, known)

    def test_uncommitted_installer_is_marked_as_uncommitted(self):
        installer = self.components["pkg:cargo/strahlender-xnu-installer@0.1.0"]
        self.assertEqual(installer["tracked"], gen.UNCOMMITTED)
        self.assertEqual(installer["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
