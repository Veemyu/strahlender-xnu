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


def setUpModule():
    # The system report runs real commands; build tests must not depend on the machine they run on.
    patcher = patch.dict(os.environ, {"BDSP_NO_DIAGNOSTICS": "1"})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


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
            # The game data is hard-linked, so the edit is also visible in the package: reinstalling is refused either way, by the check of
            # the installed folder (FileExistsError) or by the check of the package (ValueError); the user's file stays as it is.
            with self.assertRaises((FileExistsError, ValueError)):
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
                                 ([] if fail else ["images", "ui_overlay", "runtime", "link", "package"]))
                self.assertEqual(bool(installed), not fail)
                self.assertFalse(any(e["event"] == "result" for e in events))

    def test_extract_lines_reach_the_installer_while_the_tool_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            script = root / "fake_extract.py"
            script.write_text("import sys\n"
                              "print('1/5 unpack the game containers', flush=True)\n"
                              "print('extract progress 120', flush=True)\n"
                              "sys.stdin.close()\n"
                              "print('ERROR: The game NCA cannot be extracted', file=sys.stderr, flush=True)\n"
                              "sys.exit(5)\n", encoding="utf-8")
            lines = []
            environment = {"BDSP_EXTRACT": sys.executable, "BDSP_EXTRACT_PREFIX": str(script)}
            with patch.dict(os.environ, environment), self.assertRaisesRegex(ValueError, "cannot be extracted"):
                pipeline.extract_game(root / "game.xci", root / "prod.keys", root / "work", root / "hactool",
                                      progress=lines.append)
            self.assertEqual(lines, ["1/5 unpack the game containers", "extract progress 120"])

    def test_the_permille_counter_of_the_extract_tool_becomes_progress_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            selected = windows.profile("x86_64")
            args = SimpleNamespace(root=root, work=root / "work", windows_catalog=root / "catalog",
                                   target="windows", base=root / "input", prod_keys=root / "selected.keys",
                                   update=None, clean_build=False)
            bundles = {name: root / name for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt")}
            events = []

            def extract(*_arguments, progress, **_options):
                progress("4/5 extract ExeFS and RomFS")
                progress("extract progress 420")
                raise ValueError("stop here")

            with patch.object(pipeline, "prerequisites", return_value=(selected, root / "cc.exe", root / "gen.exe", bundles)), \
                    patch.object(pipeline, "extract_game", side_effect=extract), self.assertRaisesRegex(ValueError, "stop here"):
                pipeline.build_game(args, lambda event, **fields: events.append({"event": event, **fields}))
            self.assertIn({"event": "progress", "id": "extract", "completed": 420, "total": 1000}, events)
            self.assertIn({"event": "log", "level": "diagnostic", "message": "4/5 extract ExeFS and RomFS"}, events)
            self.assertFalse(any(e.get("message") == "extract progress 420" for e in events))

    def test_too_deep_folder_stops_the_preflight_with_an_actionable_message(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            selected = windows.profile("x86_64")
            args = SimpleNamespace(root=root, work=root / ("d" * 120) / "work", windows_catalog=root / "catalog",
                                   target="windows", min_free_gb=1)
            for enabled, code in ((False, 4), (True, 4)):
                output = io.StringIO()
                with patch.object(driver, "load_windows_pipeline", return_value=pipeline), \
                        patch.object(pipeline, "prerequisites", return_value=(selected, None, None, {})), \
                        patch.object(pipeline.pathlimits, "long_paths_enabled", return_value=enabled), \
                        contextlib.redirect_stdout(output):
                    self.assertEqual(driver.windows_prerequisites(args, emit_result=False), code)
                events = [json.loads(line) for line in output.getvalue().splitlines()]
                errors = [event for event in events if event["event"] == "error"]
                if code:
                    self.assertEqual(len(errors), 1)
                    self.assertIn("too deep for Windows", errors[0]["message"])
                    self.assertIn("of 260 characters", errors[0]["message"])
                    self.assertEqual(events[-3], {"event": "step", "id": "prerequisites", "status": "needs attention"})
                    self.assertNotIn("LongPathsEnabled", errors[0]["message"])

    def test_a_deep_game_folder_stops_the_build_before_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            work = root / ("d" * 40) / "work"
            (work / "exefs").mkdir(parents=True)
            for name in ("rtld", "main", "sdk", "subsdk0", "main.npdm"):
                (work / "exefs" / name).write_bytes(b"synthetic")
            deep = work / "romfs" / ("e" * 100) / ("f" * 100)
            deep.mkdir(parents=True)
            (deep / "data.bin").write_bytes(b"synthetic")
            selected = windows.profile("x86_64")
            args = SimpleNamespace(root=root, work=work, windows_catalog=root / "catalog", target="windows",
                                   base=root / "input", prod_keys=root / "selected.keys", update=None, clean_build=False)
            bundles = {name: root / name for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt")}
            events = []
            with patch.object(pipeline, "prerequisites", return_value=(selected, root / "cc.exe", root / "gen.exe", bundles)), \
                    patch.object(pipeline, "extract_game"), \
                    patch.object(pipeline.pathlimits, "long_paths_enabled", return_value=False), \
                    patch.object(build, "generate") as generate, self.assertRaisesRegex(ValueError, "too deep"):
                pipeline.build_game(args, lambda event, **fields: events.append({"event": event, **fields}))
            generate.assert_not_called()
            self.assertIn({"event": "step", "id": "exefs", "status": "failed"}, events)
            self.assertTrue(any("Path length check" in e.get("message", "") and "RISK" in e["message"] for e in events))

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

    def run_mod_build(self, root, mod_root, staged=None, artwork_error=None, emit=None, icons=None, artwork=None, mod_name="Luminescent Platinum"):
        """Runs build_game with a validated mod selection; the native tools are replaced by recording fakes."""
        (root / "work/exefs").mkdir(parents=True)
        for name in ("rtld", "main", "sdk", "subsdk0", "main.npdm"):
            (root / "work/exefs" / name).write_bytes(b"synthetic")
        (root / "work/romfs").mkdir()
        args = SimpleNamespace(root=root, work=root / "work", windows_catalog=root / "catalog",
                               target="windows", base=root / "input", prod_keys=root / "selected.keys",
                               update=None, install_root=root / "install", clean_build=False,
                               mod_root=str(mod_root), mod_name=mod_name, mods_dir=str(mod_root.parent))
        mod = driver._selected_mod(args)
        selected = windows.profile("x86_64")
        bundles = {name: root / name for name in ("sdl", "vulkan", "ffmpeg", "hactool", "qt")}
        plugin = bundles["qt"] / "plugins/platforms/qwindows.dll"
        plugin.parent.mkdir(parents=True)
        pe(plugin, ("kernel32.dll",))
        record = {"events": [], "installed": [], "staging": []}
        def package(*arguments, **options):
            record["data"] = dict(options["data"])
            record["mod.txt"] = options["data"]["mod.txt"].read_text(encoding="utf-8")
            record["package"] = Path(arguments[3])
            return self.package(Path(arguments[3]))
        def stage_code_mod(work, cache):
            record["staging"].append((work, cache))
            return staged
        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, "prerequisites",
                return_value=(selected, root / "cc.exe", root / "gen.exe", bundles)))
            for name in ("generate", "generated_inventory", "images", "compile_runtime", "compile_sources",
                         "graphical_libraries", "runtime_dll_candidates"):
                record[name] = stack.enter_context(patch.object(build, name, return_value=[]))
            stack.enter_context(patch.object(pipeline, "extract_game"))
            record["icons"] = stack.enter_context(patch.object(pipeline.game_icons, "build_windows", side_effect=icons))
            stack.enter_context(patch.object(pipeline.game_icons, "check_mod_artwork", side_effect=artwork or artwork_error))
            record["link"] = stack.enter_context(patch.object(build, "link_executable", return_value=root / "BDSP.exe"))
            stack.enter_context(patch.object(build, "package_game", side_effect=package))
            stack.enter_context(patch.object(pipeline, "install_package",
                side_effect=lambda *a: record["installed"].append(a)))
            pipeline.build_game(args, emit or (lambda event, **fields: record["events"].append({"event": event, **fields})),
                                mod=mod, stage_code_mod=stage_code_mod)
        return mod, selected, record

    def test_mod_txt_names_the_mod_folder_whatever_display_name_was_given(self):
        # mods.c finds a mod by its folder name; the display name only reaches the title and the icons.
        for display in ("Luminescent Platinum", "Lumi (display name)"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                mod_root = root / "mods/Luminescent Platinum"
                (mod_root / "RomFS").mkdir(parents=True)
                mod, _, record = self.run_mod_build(root, mod_root, artwork_error=ValueError("x"), mod_name=display)
                self.assertEqual(record["mod.txt"], "Luminescent Platinum\n%s\nromfs\n" % mod_root.parent)
                self.assertEqual(mod["name"], display)
                self.assertEqual(record["icons"].call_args.args[3], display)

    def test_what_the_icon_code_prints_stays_a_protocol_line_or_becomes_a_log_event(self):
        # The installer rejects every non-JSON stdout line ("Invalid backend protocol event"); game_icons reports with print().
        def icons(*arguments, **options):
            print("Mod icons: 0 supplied variants, 3 base variants marked MOD")
            print("partial line without newline", end="")
        def artwork(*arguments, **options):
            print("Mod artwork: 3 language variants extracted from RomFS title-logo bundles")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mod_root = root / "mods/Luminescent Platinum"
            (mod_root / "RomFS").mkdir(parents=True)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.run_mod_build(root, mod_root, emit=driver.emit, icons=icons, artwork=artwork)
        events = [json.loads(line) for line in printed.getvalue().splitlines()]
        self.assertTrue(events and all("event" in event for event in events))
        messages = [event.get("message", "") for event in events if event["event"] == "log"]
        for expected in ("Mod icons: 0 supplied variants, 3 base variants marked MOD", "partial line without newline",
                         "Mod artwork: 3 language variants extracted from RomFS title-logo bundles"):
            self.assertIn(expected, messages)

    def test_romfs_mod_becomes_a_separate_app_on_the_game_code_with_its_own_launch_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mod_root = root / "mods/Luminescent Platinum"
            (mod_root / "RomFS").mkdir(parents=True)
            mod, selected, record = self.run_mod_build(root, mod_root, artwork_error=ValueError("no UnityPy"))
            work = root / "work"
            game = work / "recomp" / selected["cache_key"]
            app = work / "recomp/mod-apps" / mod["identity"] / selected["cache_key"]
            folder = "BDSP-luminescent-platinum-" + mod["identity"]
            self.assertEqual(len(record["staging"]), 1)
            self.assertEqual(record["generate"].call_args.args[1:3], (work / "exefs", game / "gen"))
            self.assertFalse(record["compile_runtime"].call_args.kwargs["has_subsdk1"])
            self.assertEqual(record["link"].call_args.args[3], app / "BDSP.exe")
            self.assertEqual(record["link"].call_args.kwargs["icon"], app / "icons/windows")
            icon_call = record["icons"].call_args
            self.assertEqual(icon_call.args[2:], (mod_root, "Luminescent Platinum"))
            self.assertFalse(icon_call.kwargs["embedded_logos"])
            self.assertTrue(any(e["event"] == "log" and "MOD badge" in e["message"] for e in record["events"]))
            self.assertEqual(record["mod.txt"], "Luminescent Platinum\n%s\nromfs\n" % mod_root.parent)
            self.assertEqual(record["data"]["exefs/main.npdm"], work / "exefs/main.npdm")
            self.assertEqual(record["installed"][0][0], work / "builds/windows-amd64" / folder)
            self.assertEqual(record["installed"][0][1], root / "install" / folder)

    def test_code_mod_builds_the_staged_modules_and_subsdk1_in_its_own_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mod_root = root / "mods/Luminescent Platinum"
            (mod_root / "exefs").mkdir(parents=True)
            (mod_root / "exefs/0123.ips").write_bytes(b"PATCHEOF")
            build_dir = root / "work/recomp/mods/0123456789abcdef0123"
            staged = build_dir / "exefs"
            staged.mkdir(parents=True)
            for name in ("rtld", "main", "sdk", "subsdk0", "subsdk1", "main.npdm", "main.entries"):
                (staged / name).write_bytes(b"patched")
            mod, selected, record = self.run_mod_build(
                root, mod_root, staged={"staged": staged, "build_dir": build_dir})
            output = build_dir / selected["cache_key"]
            self.assertEqual(record["generate"].call_args.args[1:3], (staged, output / "gen"))
            self.assertEqual(record["images"].call_args.args[1:3], (staged, output / "images"))
            self.assertTrue(record["compile_runtime"].call_args.kwargs["has_subsdk1"])
            self.assertEqual(record["link"].call_args.args[3], output / "BDSP.exe")
            self.assertTrue(record["icons"].call_args.kwargs["embedded_logos"])
            self.assertEqual(record["mod.txt"], "Luminescent Platinum\n%s\nexefs\n" % mod_root.parent)
            self.assertEqual(record["data"]["exefs/main.npdm"], staged / "main.npdm")
            self.assertEqual(record["data"]["img"], output / "images")
            # The game's own extraction stays the input of later game builds.
            self.assertEqual((root / "work/exefs/main").read_bytes(), b"synthetic")

    def test_code_mod_without_staging_and_unvalidated_mods_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mod_root = root / "mods/Code"
            (mod_root / "exefs").mkdir(parents=True)
            (mod_root / "exefs/0123.ips").write_bytes(b"PATCHEOF")
            with self.assertRaisesRegex(ValueError, "ExeFS code"):
                self.run_mod_build(root, mod_root, staged=None)
            args = SimpleNamespace(windows_catalog=root / "catalog", target="windows", work=root / "work",
                                   mod_root=str(mod_root))
            with patch.object(pipeline, "prerequisites", return_value=(windows.profile("x86_64"), None, None, {})), \
                    self.assertRaisesRegex(ValueError, "not validated"):
                pipeline.build_game(args, lambda *a, **k: None)

    def test_driver_passes_the_validated_mod_and_shared_staging_to_the_windows_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mod_root = root / "mods/Lumi"
            (mod_root / "exefs").mkdir(parents=True)
            (mod_root / "exefs/0123.ips").write_bytes(b"PATCHEOF")
            helper = root / "ips_patch.exe"
            args = SimpleNamespace(root=root, work=root / "work", target="windows", windows_catalog=root / "catalog",
                                   prod_keys=str(root / "keys"), mod_root=str(mod_root), mod_name="Lumi",
                                   mods_dir=str(mod_root.parent), ips_helper=str(helper))
            calls = []
            def execute(args, emit, mod=None, stage_code_mod=None):
                calls.append((mod, stage_code_mod))
            with patch.object(driver, "windows_prerequisites", return_value=0), \
                    patch.object(driver, "load_windows_pipeline", return_value=SimpleNamespace(build_game=execute)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(driver.build(args), 3)
                self.assertIn("ips_patch helper", output.getvalue())
                self.assertEqual(calls, [])
                helper.write_bytes(b"helper")
                self.assertEqual(driver.build(args), 0)
            mod, stage_code_mod = calls[0]
            self.assertEqual((mod["name"], mod["root"], mod["mods_dir"]), ("Lumi", mod_root, mod_root.parent))
            work = root / "work"
            for module in ("rtld", "main", "sdk", "subsdk0"):
                (work / "exefs").mkdir(parents=True, exist_ok=True)
                (work / "exefs" / module).write_bytes(module.encode())
            def staging(command, args, stage, emit_steps=True):
                self.assertEqual(command[:2], [str(helper), "stage"])
                self.assertFalse(emit_steps)
                Path(command[4]).mkdir(parents=True)
                return 0
            with patch.object(driver, "_run_command", side_effect=staging):
                staged = stage_code_mod(work, work / "recomp")
            self.assertTrue(staged["staged"].is_relative_to(work / "recomp/mods"))
            self.assertTrue((staged["staged"] / ".source-sha256").is_file())

    def test_driver_success_result_only_after_install_and_redacts_selected_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            keys = root / "private-selected.keys"
            args = SimpleNamespace(root=root, work=root / "work", target="windows",
                                   windows_catalog=root / "catalog", prod_keys=str(keys))
            def execute(args, emit, **_):
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
