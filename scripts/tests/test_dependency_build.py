"""Offline dependency recipes use synthetic inputs only; never invoke VCS or download."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.recomp import dependency_build as dependencies
from scripts.recomp import portable_build as build
from scripts.tests.test_windows_build import pe


class DependencyBuildTests(unittest.TestCase):
    def test_notice_collection_preserves_spdx_directories_and_authorship_without_source_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            files = ("LICENSE.md", "LICENSES/Apache-2.0.txt", "LICENSES/MIT.txt",
                     "third_party/tool/AUTHORS.txt", "third_party/tool/COPYRIGHT",
                     "third_party/tool/NOTICE", "src/check_copyright.py", "src/implementation.c")
            for name in files:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            output = root / "notices"
            dependencies.collect_notices(source, output)
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()},
                             set(files[:-2]))
            for name in files[:-2]:
                self.assertEqual((output / name).read_bytes(), (source / name).read_bytes())
            with self.assertRaisesRegex(ValueError, "outside"):
                dependencies.collect_notices(source, source / "notices")

    def test_qt_bundle_keeps_the_three_modules_the_host_links_and_their_licence_texts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            qt = root / "qt"
            for name in ("include/QtCore/qglobal.h", "include/QtGui/QVulkanInstance", "include/QtWidgets/QApplication",
                         "include/QtNetwork/QTcpSocket", "lib/libQt6Core.a", "lib/libQt6Gui.a", "lib/libQt6Widgets.a",
                         "lib/libQt6Network.a", "bin/Qt6Core.dll", "bin/Qt6Gui.dll", "bin/Qt6Widgets.dll", "bin/Qt6Network.dll",
                         "plugins/platforms/qwindows.dll", "plugins/styles/qmodernwindowsstyle.dll", "plugins/sqldrivers/x.dll"):
                (qt / name).parent.mkdir(parents=True, exist_ok=True)
                (qt / name).write_bytes(name.encode())
            source = root / "qtbase.tar.xz"
            with tarfile.open(source, "w:xz") as archive:
                for name, data in (("qtbase-6.12.0/LICENSES/LGPL-3.0-only.txt", b"lgpl"), ("qtbase-6.12.0/LICENSE.LGPL3", b"l3"),
                                   ("qtbase-6.12.0/src/3rdparty/freetype/LICENSE.TXT", b"ftl"),
                                   ("qtbase-6.12.0/src/3rdparty/freetype/src/skip/LICENSE", b"too deep"),
                                   ("qtbase-6.12.0/src/main.cpp", b"code")):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            notices = dependencies.qt_notices(source, root / "notices")
            self.assertTrue((notices / "src/3rdparty/freetype/LICENSE.TXT").is_file())
            selected = build.windows.profile("x86_64", "x86_64")
            identity = {"path": str(root / "bin/x86_64-w64-mingw32-clang.exe"), "sha256": "c" * 64, "version": "v", "triple": "t"}
            with patch.object(build, "compiler_identity", return_value=identity):
                result = dependencies.build_qt(qt, notices, root / "bundle", "clang", selected, "6.12.0")
            files = {p.relative_to(result).as_posix() for p in result.rglob("*") if p.is_file()}
            self.assertIn("lib/libQt6Widgets.a", files)
            self.assertIn("bin/Qt6Core.dll", files)
            self.assertIn("plugins/platforms/qwindows.dll", files)
            self.assertNotIn("lib/libQt6Network.a", files)
            self.assertNotIn("plugins/sqldrivers/x.dll", files)
            self.assertIn("notices/qt/LICENSES/LGPL-3.0-only.txt", files)
            self.assertIn("notices/qt/src/3rdparty/freetype/LICENSE.TXT", files)
            self.assertNotIn("notices/qt/src/main.cpp", files)
            record = json.loads((result / "build.json").read_text())
            self.assertEqual(record["qt"], {"linkage": "shared", "cxx_runtime": "libc++", "version": "6.12.0",
                                            "minimum_windows_build": 19045, "cxx_compiler_sha256": "c" * 64})
            with self.assertRaisesRegex(ValueError, "existing"):
                dependencies.build_qt(qt, notices, result, "clang", selected, "6.12.0")

    def test_hactool_preserves_distinct_embedded_license_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.mkdir()
            files = ("cJSON.c", "ConvertUTF.c", "ConvertUTF.h", "lz4.c", "lz4.h")
            for name in files:
                (source / name).write_bytes((name + ": unmodified upstream notice and code").encode())
            dependencies.collect_notices(source, root / "notices", "hactool")
            for name in files:
                self.assertEqual((root / "notices" / "embedded-source" / name).read_bytes(),
                                 (source / name).read_bytes())

    def test_pinned_description_never_invokes_vcs(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "version.py"
            for argument in ("directory", "repo_path"):
                path.write_text(f"def describe({argument}):\n    raise AssertionError('VCS invoked')\n")
                receipt = dependencies.pin_build_description(path, "pinned-revision")
                namespace = {}
                exec(compile(path.read_text(), str(path), "exec"), namespace)
                self.assertEqual(namespace["describe"]("unused"), "pinned-revision")
                self.assertNotEqual(receipt["before"], receipt["after"])
            path.write_text("def changed_upstream():\n    pass\n")
            with self.assertRaisesRegex(ValueError, "changed"):
                dependencies.pin_build_description(path, "pin")

    def test_source_digest_size_and_safe_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            archive = root / "synthetic-pin.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("../outside.txt")
                member.size = 1
                output.addfile(member, io.BytesIO(b"x"))
            item = {"revision": "pin", "size_bytes": archive.stat().st_size,
                    "sha256": build.windows.sha256(archive)}
            with self.assertRaises(tarfile.FilterError):
                dependencies.extract_source(root, "synthetic", root / "source", {"synthetic": item})
            self.assertFalse((root / "outside.txt").exists())
            item["size_bytes"] += 1
            with self.assertRaisesRegex(ValueError, "checksum/size"):
                dependencies.extract_source(root, "synthetic", root / "rejected", {"synthetic": item})
            self.assertFalse((root / "rejected").exists())

    def test_prebuilt_import_integrity_architecture_closure_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            entries = {"ffmpeg/LICENSE.txt": b"synthetic license", "ffmpeg/doc/manual.txt": b"documentation"}
            for name in ("avcodec", "avformat", "avutil"):
                entries[f"ffmpeg/include/lib{name}/{name}.h"] = b"synthetic header"
                entries[f"ffmpeg/lib/lib{name}.dll.a"] = b"synthetic import library"
            for name, imports in (("avcodec-62", ["avutil-60.dll", "swresample-6.dll"]),
                                  ("avformat-62", ["avcodec-62.dll"]),
                                  ("avutil-60", ["kernel32.dll"]), ("swresample-6", ["avutil-60.dll"])):
                entries[f"ffmpeg/bin/{name}.dll"] = pe(root / (name + ".dll"), imports).read_bytes()
            entries["ffmpeg/bin/ffmpeg.exe"] = b"must not ship"
            entries["ffmpeg/bin/unused.dll"] = b"not part of measured closure"
            archive = root / "ffmpeg.zip"
            actual_contract = build.windows.contract()
            def contract():
                with zipfile.ZipFile(archive, "w") as output:
                    for name, contents in entries.items():
                        output.writestr(name, contents)
                return {**actual_contract, "components": [{"id": "ffmpeg", "version": "synthetic",
                         "qualification": "Not redistributable yet", "artifacts": [{
                             "target": "x86_64", "size_bytes": archive.stat().st_size,
                             "sha256": build.windows.sha256(archive), "archive_root": "ffmpeg",
                             "expanded_size_bytes": sum(map(len, entries.values()))}]}]}
            selected = build.windows.profile("x86_64", "x86_64")
            with patch.object(build.windows, "contract", return_value=contract()):
                destination = dependencies.import_ffmpeg(archive, root / "bundle", selected)
                record = json.loads((destination / "build.json").read_text())
                self.assertFalse(record["qualified"])
                self.assertEqual({p.name for p in (destination / "bin").iterdir()},
                                 {"avcodec-62.dll", "avformat-62.dll", "avutil-60.dll", "swresample-6.dll"})
                build.verified_bundle(destination, selected)
                license_archive = root / "ffmpeg-pin.tar.gz"
                with tarfile.open(license_archive, "w:gz") as tar:
                    for name in ("COPYING.GPLv3", "COPYING.LGPLv3"):
                        member = tarfile.TarInfo("older-source/" + name)
                        member.size = 7
                        tar.addfile(member, io.BytesIO(b"license"))
                license_pin = {"revision": "pin", "size_bytes": license_archive.stat().st_size,
                               "sha256": build.windows.sha256(license_archive)}
                with patch.object(dependencies, "source_lock", return_value={"ffmpeg": license_pin}):
                    supplemented = dependencies.import_ffmpeg(archive, root / "license-complete", selected, root)
                supplement_record = json.loads((supplemented / "build.json").read_text())
                self.assertFalse(supplement_record["qualified"])
                self.assertIn("NOT corresponding source", supplement_record["license_texts"]["scope"])
                self.assertEqual((supplemented / "notices/ffmpeg/COPYING.GPLv3").read_bytes(), b"license")
                build.verified_bundle(supplemented, selected)
                with self.assertRaisesRegex(ValueError, "existing"):
                    dependencies.import_ffmpeg(archive, destination, selected)
                (destination / "bin/avutil-60.dll").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    build.verified_bundle(destination, selected)
                archive.write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "checksum/size"):
                    dependencies.import_ffmpeg(archive, root / "tampered", selected)
                self.assertFalse((root / "tampered").exists())
            for invalid in ("ffmpeg/../outside", "ffmpeg/C:drive", "ffmpeg//outside"):
                entries[invalid] = b"invalid"
                with patch.object(build.windows, "contract", return_value=contract()):
                    with self.assertRaisesRegex(ValueError, "Unsafe"):
                        dependencies.import_ffmpeg(archive, root / "unsafe", selected)
                del entries[invalid]
                self.assertFalse((root / "unsafe").exists())
            del entries["ffmpeg/bin/swresample-6.dll"]
            with patch.object(build.windows, "contract", return_value=contract()):
                with self.assertRaisesRegex(ValueError, "Missing DLL"):
                    dependencies.import_ffmpeg(archive, root / "missing", selected)
            self.assertFalse((root / "missing").exists())
            self.assertEqual(list(root.glob("ffmpeg-import-*")), [])

    def test_unpinned_ffmpeg_download_is_imported_with_prepared_license_texts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            entries = {"ffmpeg-n8.1/LICENSE.txt": b"lgpl", "ffmpeg-n8.1/doc/manual.txt": b"doc"}
            for name in ("avcodec", "avformat", "avutil"):
                entries[f"ffmpeg-n8.1/include/lib{name}/{name}.h"] = b"header"
                entries[f"ffmpeg-n8.1/lib/lib{name}.dll.a"] = b"import"
            for name, imports in (("avcodec-62", ["avutil-60.dll"]), ("avformat-62", ["avcodec-62.dll"]), ("avutil-60", ["kernel32.dll"])):
                entries[f"ffmpeg-n8.1/bin/{name}.dll"] = pe(root / (name + ".dll"), imports).read_bytes()
            archive = root / "ffmpeg.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for name, contents in entries.items():
                    output.writestr(name, contents)
            texts = root / "texts"
            texts.mkdir()
            for name in ("COPYING.GPLv3", "COPYING.LGPLv3"):
                (texts / name).write_bytes(b"text")
            selected = build.windows.profile("x86_64", "x86_64")
            no_pin = {**build.windows.contract(), "components": [{"id": "ffmpeg", "artifacts": []}]}
            with patch.object(build.windows, "contract", return_value=no_pin):
                bundle = dependencies.import_ffmpeg(archive, root / "bundle", selected, license_dir=texts)
            record = json.loads((bundle / "build.json").read_text())
            self.assertEqual(record["version"], "ffmpeg-n8.1")
            self.assertEqual(record["artifact"]["sha256"], build.windows.sha256(archive))
            self.assertTrue((bundle / "notices/ffmpeg/COPYING.LGPLv3").is_file())
            build.verified_bundle(bundle, selected)


if __name__ == "__main__":
    unittest.main()
