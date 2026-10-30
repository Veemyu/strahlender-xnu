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

    def test_patched_window_runtime_is_included_with_its_license_and_location(self):
        runtime = self.components["pkg:cargo/iced_winit@0.14.1"]
        self.assertEqual(runtime["license"], "MIT")
        self.assertIn("installer/vendor/iced_winit", runtime["evidence"])

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

    def test_installer_is_marked_as_tracked(self):
        installer = self.components["pkg:cargo/strahlender-xnu-installer@0.1.0"]
        self.assertEqual(installer["tracked"], gen.TRACKED)
        self.assertEqual(installer["license"], "MIT")

    def test_extract_crate_and_its_dependencies_are_listed(self):
        extract = self.components["pkg:cargo/bdsp-extract@0.1.0"]
        self.assertEqual(extract["category"], "application")
        self.assertIn("installer/extract/Cargo.lock", extract["evidence"])
        self.assertTrue(any(d.startswith("pkg:cargo/sha2@") for d in extract["depends_on"]))


class WindowsEnvironmentTest(unittest.TestCase):
    def test_resolved_lock_files_become_components(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            contract = {"components": [
                {"id": "SDL3", "source": "https://github.com/libsdl-org/SDL", "license": "Zlib", "version": "3.4.2",
                 "source_archive": {"sha256": "ab" * 32}},
                {"id": "qt", "source": "https://www.qt.io", "license": "LicenseRef-Qt-audit", "qualification": "LGPL notes"}]}
            sources = {"sources": {"shaderc": {"repository": "google/shaderc", "license": "Apache-2.0",
                                               "version": "v2026.1", "revision": "c" * 40, "sha256": "cd" * 32}}}
            (folder / "windows-dependencies.json").write_text(json.dumps(contract))
            (folder / "windows-sources.json").write_text(json.dumps(sources))
            (folder / "qt.json").write_text(json.dumps({"qt": "6.12.0"}))
            found = {c["name"]: c for c in gen.windows_components(folder)}
            self.assertEqual(found["SDL3"]["purl"], "pkg:generic/windows-SDL3@3.4.2")
            self.assertEqual(found["SDL3"]["sha256"], "ab" * 32)
            self.assertEqual(found["qt"]["version"], "6.12.0")
            self.assertIn("LicenseRef-Qt-audit", gen.LICENSE_REFS)
            self.assertEqual(found["shaderc"]["purl"], "pkg:github/google/shaderc@" + "c" * 40)
            self.assertTrue(all(c["distribution"] == gen.SHIPPED for c in found.values()))


if __name__ == "__main__":
    unittest.main()
