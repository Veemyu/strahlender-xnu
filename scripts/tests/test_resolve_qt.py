import unittest

from scripts.recomp import resolve_qt

LISTING = '<a href="qt6_693/">a</a><a href="qt6_6110/">b</a><a href="qt6_6130/">c</a><a href="qt6_6120/">d</a>' \
          '<a href="tools_llvm_mingw1706/">t</a><a href="tools_llvm_mingw2217/">t</a>'


def updates(name, version, archives):
    return "<Updates><PackageUpdate><Name>%s</Name><Version>%s</Version><DownloadableArchives>%s</DownloadableArchives></PackageUpdate></Updates>" % (name, version, archives)


class ResolveQtTests(unittest.TestCase):
    def fetch(self, url):
        base = resolve_qt.BASE
        if url == base:
            return LISTING
        if url == base + "qt6_6120/qt6_6120_llvm_mingw/Updates.xml":
            return updates("qt.qt6.6120.win64_llvm_mingw", "6.12.0-0-2026", "qtsvg-x.7z, qtbase-Windows-X86_64.7z")
        if url == base + "tools_llvm_mingw2217/Updates.xml":
            return updates("qt.tools.win64_llvm_mingw2217", "22.1.7-2026", "llvm_mingw2217.7z")
        raise OSError("not found: " + url)  # 6.13 has no LLVM-MinGW kit

    def test_newest_qt_with_the_llvm_mingw_kit_and_the_newest_toolchain(self):
        found = resolve_qt.resolve(self.fetch)
        self.assertEqual(found["qt"], "6.12.0")
        self.assertTrue(found["qtbase"].endswith("qt.qt6.6120.win64_llvm_mingw/6.12.0-0-2026qtbase-Windows-X86_64.7z"))
        self.assertTrue(found["toolchain"].endswith("tools_llvm_mingw2217/qt.tools.win64_llvm_mingw2217/22.1.7-2026llvm_mingw2217.7z"))
        self.assertTrue(found["source"].endswith("/qt/6.12/6.12.0/submodules/qtbase-everywhere-src-6.12.0.tar.xz"))

    def test_no_kit_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "LLVM-MinGW kit"):
            resolve_qt.resolve(lambda url: LISTING if url == resolve_qt.BASE else (_ for _ in ()).throw(OSError("x")))


if __name__ == "__main__":
    unittest.main()
