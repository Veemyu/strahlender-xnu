"""The native generator finds Unicorn in tools/pydeps without PYTHONPATH (documented dev setup)."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.tests.test_windows_build import pe


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_codegen_build_unicorn", ROOT / "scripts/recomp/native-generator/build.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class UnicornLookupTests(unittest.TestCase):
    def package(self, tools):
        package = tools / "pydeps/unicorn"
        (package / "include/unicorn").mkdir(parents=True)
        (package / "lib").mkdir()
        (package / "include/unicorn/unicorn.h").write_text(
            "#define UC_API_MAJOR 2\n#define UC_API_MINOR 1\n#define UC_API_PATCH 4\n")
        for name in ("libunicorn.2.dylib", "libunicorn.so.2"):
            (package / "lib" / name).write_bytes(b"library")
        pe(package / "lib/unicorn.dll")  # the Windows build inspects the DLL, so it must be a real (empty) PE image
        return package

    def test_tools_pydeps_is_used_when_the_package_is_not_importable(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(builder.os.environ, {"TOOLS_DIR": folder}), \
                mock.patch.object(builder.importlib.util, "find_spec", return_value=None):
            package = self.package(Path(folder))
            found = builder.unicorn_dependency()
        self.assertEqual(found["root"], package.resolve())

    def test_environment_root_wins_over_tools_pydeps(self):
        with tempfile.TemporaryDirectory() as tools, tempfile.TemporaryDirectory() as explicit, \
                mock.patch.dict(builder.os.environ, {"TOOLS_DIR": tools}), \
                mock.patch.object(builder.importlib.util, "find_spec", return_value=None):
            self.package(Path(tools))
            other = self.package(Path(explicit))
            found = builder.unicorn_dependency(other)
        self.assertEqual(found["root"], other.resolve())

    def test_missing_everywhere_returns_none(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(builder.os.environ, {"TOOLS_DIR": folder}), \
                mock.patch.object(builder.importlib.util, "find_spec", return_value=None):
            self.assertIsNone(builder.unicorn_dependency())


if __name__ == "__main__":
    unittest.main()
