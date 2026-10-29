import unittest

from scripts.recomp import resolve_qt


class ResolveQtTests(unittest.TestCase):
    def test_newest_qt_with_the_llvm_mingw_kit_and_the_newest_toolchain_tool(self):
        qt = "6.8.3 6.10.1 6.12.0 6.13.0\n5.15.2"
        archs = {"6.13.0": "win64_msvc2022_64 win64_mingw", "6.12.0": "win64_msvc2022_64 win64_llvm_mingw", "6.10.1": "win64_llvm_mingw"}
        tools = "tools_cmake\ntools_llvm_mingw1706\ntools_llvm_mingw2217\ntools_ninja"
        result = resolve_qt.pick(qt, lambda version: archs.get(version, ""), tools)
        self.assertEqual(result, {"qt": "6.12.0", "arch": "win64_llvm_mingw", "tool": "tools_llvm_mingw2217",
                                  "variant": "qt.tools.win64_llvm_mingw2217"})

    def test_missing_kit_or_tool_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "offers"):
            resolve_qt.pick("6.12.0", lambda version: "win64_mingw", "tools_llvm_mingw1")
        with self.assertRaisesRegex(ValueError, "tool"):
            resolve_qt.pick("6.12.0", lambda version: "win64_llvm_mingw", "tools_cmake")


if __name__ == "__main__":
    unittest.main()
