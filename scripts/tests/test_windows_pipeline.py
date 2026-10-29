import os
import contextlib
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.install import driver, windows_pipeline as pipeline
from scripts.recomp import portable_build as build, windows_support as windows
from scripts.tests.test_windows_build import pe


class WindowsPipelineTests(unittest.TestCase):
    def test_installer_does_not_accept_runtime_controller_settings(self):
        arguments = ["build", "--root", ".", "--work", ".", "--target", "windows",
                     "--base", "synthetic.nsp", "--prod-keys", "synthetic.keys"]
        with patch.object(driver, "build") as execute, contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as failure:
            driver.main([*arguments, "--joycons", "single"])
        execute.assert_not_called()
        self.assertEqual(failure.exception.code, 2)

    def test_isolated_python_driver_uses_utf8_jsonl_without_system_pythonpath(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-I", "-B", root / "scripts/install/driver.py",
                 "preflight", "--root", root, "--work", temporary, "--tools-dir", temporary,
                 "--target", "windows", "--windows-catalog",
                 Path(temporary) / "missing-\u65e5\u672c\u8a9e.json"],
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 4)
            events = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
            self.assertEqual(events[-1], {"event": "result", "ok": False, "code": 4})
            self.assertTrue(any(event["event"] == "error" for event in events))

    def package(self, root, contents=b"synthetic binary"):
        root.mkdir()
        (root / "BDSP.exe").write_bytes(contents)
        (root / "romfs").mkdir()
        (root / "romfs/data.bin").write_bytes(b"synthetic data")
        record = {"schema": 1, "target": windows.profile("x86_64"),
                  "files": {p.relative_to(root).as_posix(): windows.sha256(p)
                            for p in root.rglob("*") if p.is_file()}}
        build.atomic_json(root / "package.json", record)
        return root

    def test_installed_package_preserves_external_saves_and_refuses_modified_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = self.package(root / "package")
            (root / "user/saves").mkdir(parents=True)
            save = root / "user/saves/player.bin"
            save.write_bytes(b"user save")
            events = []
            emit = lambda event, **fields: events.append({"event": event, **fields})
            installed = pipeline.install_package(package, root / "user/app", emit)
            self.assertEqual(installed.read_bytes(), b"synthetic binary")
            self.assertEqual(events[-1]["path"], str(installed))
            pipeline.install_package(package, installed.parent, emit)
            self.assertEqual(save.read_bytes(), b"user save")
            (installed.parent / "romfs/data.bin").write_bytes(b"user modified")
            with self.assertRaises(FileExistsError):
                pipeline.install_package(package, installed.parent, emit)
            self.assertEqual((installed.parent / "romfs/data.bin").read_bytes(), b"user modified")
            self.assertEqual(save.read_bytes(), b"user save")
            (package / "untracked-tool.exe").write_bytes(b"tool")
            with self.assertRaisesRegex(ValueError, "added"):
                pipeline.install_package(package, root / "other", emit)
            self.assertFalse((root / "other").exists())

    @unittest.skipUnless(os.name == "nt", "Mocks sys.platform and needs executable-file semantics of Windows; runs on Windows only")
    def test_catalog_tracks_generator_closure_and_entire_toolchain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "llvm/bin").mkdir(parents=True)
            compiler = root / "llvm/bin/clang.exe"
            compiler.write_bytes(b"synthetic compiler")
            (compiler.parent / "lld.exe").write_bytes(b"synthetic linker")
            generator = pe(root / "generator.exe", imports=("unicorn.dll",))
            pe(root / "unicorn.dll")
            bundles = {}
            for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt"):
                bundles[name] = root / name
                bundles[name].mkdir()
                (bundles[name] / "build.json").write_text("{}")
            selected = windows.profile("x86_64")
            identity = {"path": str(compiler)}
            with patch.object(build, "compiler_identity", return_value=identity), \
                    patch.object(build, "verified_bundle", side_effect=lambda path, _: Path(path).resolve()):
                with patch.object(build, "qt_development", return_value=bundles["qt"]) as qt_check:
                    catalog = pipeline.write_catalog(root / "catalog.json", compiler, generator, selected, **bundles)
                    self.assertIn("qt", pipeline.read_catalog(catalog, "x86_64")[3])
                    self.assertEqual(qt_check.call_count, 2)
                    without_qt = {name: path for name, path in bundles.items() if name != "qt"}
                    with self.assertRaisesRegex(ValueError, "required"):
                        pipeline.write_catalog(root / "no-qt.json", compiler, generator, selected, **without_qt)
                record = json.loads(catalog.read_text())
                self.assertIn("llvm/bin/lld.exe", {Path(n).as_posix() for n in record["files"]})
                record["files"].pop("unicorn.dll")
                build.atomic_json(catalog, record)
                with self.assertRaisesRegex(ValueError, "untracked"):
                    pipeline.read_catalog(catalog, "x86_64")
                with self.assertRaises(ValueError):
                    pipeline.read_catalog(catalog, "aarch64")

    def test_pipeline_stage_order_and_failed_compile_never_publishes_or_installs(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / "work/exefs").mkdir(parents=True)
                for name in ("rtld", "main", "sdk", "subsdk0", "main.npdm"):
                    (root / "work/exefs" / name).write_bytes(b"synthetic")
                (root / "work/romfs").mkdir()
                args = SimpleNamespace(root=root, work=root / "work", windows_catalog=root / "catalog",
                                       target="windows", base=root / "input", prod_keys=root / "selected.keys",
                                       update=None, install_root=root / "install", clean_build=False)
                selected = windows.profile("x86_64")
                bundles = {name: root / name for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt")}
                plugin = bundles["qt"] / "plugins/platforms/qwindows.dll"
                plugin.parent.mkdir(parents=True)
                pe(plugin, ("kernel32.dll",))
                events, installed = [], []
                emit = lambda event, **fields: events.append({"event": event, **fields})
                def package(*arguments, **options):
                    expected = {"img", "romfs", "exefs/main.npdm", "icons/windows",
                                "plugins/platforms/qwindows.dll", "qt.conf", "lproj"}
                    self.assertEqual(options["data"]["plugins/platforms/qwindows.dll"], plugin)
                    self.assertEqual(options["data"]["qt.conf"].read_text(), "[Paths]\nPrefix=.\nPlugins=plugins\n")
                    self.assertIn("qt", options["notice_trees"])
                    self.assertEqual(set(options["data"]), expected)
                    return self.package(Path(arguments[3]))
                with ExitStack() as stack:
                    stack.enter_context(patch.object(pipeline, "prerequisites",
                        return_value=(selected, root / "cc.exe", root / "gen.exe", bundles)))
                    for name in ("generate", "generated_inventory", "images", "compile_runtime",
                                 "graphical_libraries", "runtime_dll_candidates"):
                        stack.enter_context(patch.object(build, name, return_value=[]))
                    stack.enter_context(patch.object(pipeline, "extract_game"))
                    stack.enter_context(patch.object(pipeline.game_icons, "main", return_value=0))
                    stack.enter_context(patch.object(pipeline.game_icons, "build_windows"))
                    stack.enter_context(patch.object(build, "compile_sources",
                        side_effect=ValueError("injected compile failure") if fail else None))
                    stack.enter_context(patch.object(build, "link_executable", return_value=root / "BDSP.exe"))
                    stack.enter_context(patch.object(build, "package_game", side_effect=package))
                    stack.enter_context(patch.object(pipeline, "install_package",
                        side_effect=lambda *a: installed.append(a)))
                    if fail:
                        with self.assertRaisesRegex(ValueError, "compile failure"):
                            pipeline.build_game(args, emit)
                    else:
                        pipeline.build_game(args, emit)
                        self.assertIs(build.compile_runtime.call_args.kwargs["qt"], bundles["qt"])
                        self.assertEqual(build.link_executable.call_args.kwargs["icon"],
                                         root / "work/recomp" / selected["cache_key"] / "icons/windows")
                steps = [e["id"] for e in events if e["event"] == "step" and e["status"] == "started"]
                self.assertEqual(steps, ["extract", "exefs", "eh_gen", "clang"] +
                                 ([] if fail else ["images", "runtime", "link", "package"]))
                self.assertEqual(bool(installed), not fail)
                self.assertFalse(any(e["event"] == "result" for e in events))

    def test_failed_extraction_does_not_move_clean_build_outputs_or_selected_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            selected = windows.profile("x86_64")
            output = root / "work/recomp" / selected["cache_key"]
            output.mkdir(parents=True)
            previous = output / "previous.c"
            previous.write_bytes(b"old generated source")
            args = SimpleNamespace(root=root, work=root / "work", windows_catalog=root / "catalog",
                                   target="windows", base=root / "input", prod_keys=root / "selected.keys",
                                   update=None, clean_build=True)
            bundles = {name: root / name for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt")}
            with patch.object(pipeline, "prerequisites",
                    return_value=(selected, root / "cc.exe", root / "gen.exe", bundles)), \
                    patch.object(pipeline, "extract_game", side_effect=ValueError("injected extraction failure")):
                with self.assertRaisesRegex(ValueError, "extraction failure"):
                    pipeline.build_game(args, lambda *a, **k: None)
                self.assertEqual(previous.read_bytes(), b"old generated source")
                args.prod_keys = output / "must-not-move.keys"
                args.prod_keys.write_bytes(b"synthetic keys")
                with self.assertRaisesRegex(ValueError, "outside"):
                    pipeline.build_game(args, lambda *a, **k: None)
                self.assertTrue(args.prod_keys.exists())
            self.assertEqual(list(output.parent.glob("*-previous-*")), [])

    def test_driver_success_result_only_after_install_and_redacts_selected_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            keys = root / "private-selected.keys"
            args = SimpleNamespace(root=root, work=root / "work", target="windows",
                                   windows_catalog=root / "catalog", prod_keys=str(keys))
            def execute(args, emit):
                emit("log", level="diagnostic", message="Compiler path: " + str(keys))
                emit("artifact", kind="installed_application", path=str(root / "app/BDSP.exe"))
            with patch.object(driver, "windows_prerequisites", return_value=0) as check, \
                    patch.object(driver, "load_windows_pipeline", return_value=SimpleNamespace(build_game=execute)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(driver.build(args), 0)
            check.assert_called_once_with(args, emit_result=False)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([e["event"] for e in events], ["hello", "log", "artifact", "result"])
            self.assertNotIn(str(keys), output.getvalue())


if __name__ == "__main__":
    unittest.main()
