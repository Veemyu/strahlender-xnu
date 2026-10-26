import json
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.install import driver


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
DRIVER = os.path.join(ROOT, "scripts", "install", "driver.py")


class InstallerDriverTests(unittest.TestCase):
    def test_linux_build_check_uses_real_formatter_for_extra_requirements(self):
        stages = driver.load_build_stages(ROOT)
        args = SimpleNamespace(root=ROOT, work="/unused", target="linux", mod_root=None)
        for missing in ([], ["Capstone"]):
            with self.subTest(missing=missing), \
                    patch.object(driver, "load_build_stages", return_value=stages), \
                    patch.object(stages, "preflight", return_value=[]), \
                    patch.object(driver, "required_free_gb", return_value=40), \
                    patch.object(driver, "missing_generator_modules", return_value=missing), \
                    patch.object(driver.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                code = driver.check_build_dependencies(args)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(code, stages.EX_TOOLS if missing else 0)
            self.assertFalse(any(event["event"] == "error" for event in events))
            self.assertTrue(any("Vulkan and Qt" in event.get("message", "") for event in events))

    def test_prerequisite_exception_has_type_traceback_and_redacted_paths(self):
        args = SimpleNamespace(root=ROOT, work="/unused", target="linux", mod_root=None)
        with patch.object(driver, "load_build_stages", side_effect=KeyError("detail")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver.check_build_dependencies(args), 1)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn("KeyError: 'detail'", events[-1]["message"])
        self.assertTrue(any("Traceback" in event.get("message", "") for event in events))
        self.assertNotIn(ROOT, output.getvalue())

    def test_preflight_formatter_accepts_requirements_without_optional_detail(self):
        stages = driver.load_build_stages(ROOT)
        item = {"name": "Vulkan", "ok": False, "level": "missing", "hint": "Install Vulkan"}
        lines, missing, disk = stages.format_preflight([item])
        self.assertIn("Vulkan", lines[0])
        self.assertEqual(missing, [item])
        self.assertFalse(disk)

    def test_missing_generator_modules_names_each_failed_import(self):
        def run(command, **kwargs):
            module = command[-1].removeprefix("import ")
            return SimpleNamespace(returncode=0 if module == "PIL.Image" else 1)

        self.assertEqual(driver.missing_generator_modules(run), ["Unicorn 2.1.4 native engine and headers", "LZ4"])

    def test_relative_project_root_redaction_preserves_dotted_values(self):
        args = SimpleNamespace(root=".")
        self.assertEqual(driver._safe_line("Python 3.14.3; 44.8 GB free", args),
                         "Python 3.14.3; 44.8 GB free")

    def test_desktop_compile_progress_ignores_an_incomplete_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for target, name in (("macos", "obj4"), ("linux", "obj4-c")):
                obj = work / "recomp" / name
                obj.mkdir(parents=True)
                (obj / "list_O0.txt").write_text("")
                (obj / "list_O1.txt").write_text("first.c\n")
                self.assertIsNone(driver._compile_count(work, target))
                (obj / ".compile-total").write_text("2\n")
                self.assertIsNone(driver._compile_count(work, target))
                (obj / "list_O1.txt").write_text("first.c\nsecond.c\n")
                (obj / "first.o").touch()
                self.assertEqual(driver._compile_count(work, target), (1, 2))

    def test_previous_run_objects_cannot_finish_a_new_compile_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for target, name in (("macos", "obj4"), ("linux", "obj4-c")):
                obj = work / "recomp" / name
                obj.mkdir(parents=True)
                (obj / "list_O0.txt").write_text("")
                (obj / "list_O1.txt").write_text("first.c\nsecond.c\n")
                marker = obj / ".compile-total"
                marker.write_text("2\n")
                for file in ("first.o", "second.o"):
                    (obj / file).touch()
                epoch = marker.stat().st_mtime_ns + 100
                self.assertIsNone(driver._compile_count(work, target, not_before_ns=epoch))
                for file in obj.glob("*.o"):
                    file.unlink()
                os.utime(marker, ns=(epoch + 1, epoch + 1))
                self.assertEqual(driver._compile_count(work, target, not_before_ns=epoch), (0, 2))
                (obj / "first.o").touch()
                self.assertEqual(driver._compile_count(work, target, not_before_ns=epoch), (1, 2))

    def test_mac_phase_does_not_publish_old_completion_before_inventory_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            obj = work / "recomp/obj4"
            obj.mkdir(parents=True)
            (obj / "list_O0.txt").write_text("")
            (obj / "list_O1.txt").write_text("first.c\nsecond.c\n")
            (obj / ".compile-total").write_text("2\n")
            for name in ("first.o", "second.o"):
                (obj / name).touch()
            args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
            code = ("from pathlib import Path; import time; p=Path(" + repr(str(obj)) + "); "
                    "print('2/6 compile: fixture',flush=True); time.sleep(.1); "
                    "[f.unlink() for f in p.glob('*.o')]; (p/'.compile-total').write_text(str(2)); "
                    "time.sleep(.35); (p/'first.o').touch(); print('compile checkpoint',flush=True)")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = driver._run_command([sys.executable, "-c", code], args, "eh_gen",
                    progress=lambda phase: driver._compile_count(work, "macos", not_before_ns=args.compile_epoch_ns)
                    if phase == "clang" else None, phase_from_line=driver._mac_phase)
            self.assertEqual(result, 0, output.getvalue())
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            counts = [e["completed"] for e in events if e["event"] == "progress" and e["id"] == "clang"]
            self.assertTrue(counts)
            self.assertNotIn(2, counts)
            self.assertEqual(counts[-1], 1)

    def test_development_home_isolation_does_not_expose_the_login_home(self):
        args = SimpleNamespace(root="/isolated/project")
        with patch.object(driver, "_login_home", return_value="/Users/example"):
            self.assertEqual(driver._safe_line("hactool (/Users/example/Work/tools/hactool)", args),
                             "hactool (~/Work/tools/hactool)")

    def test_ios_compile_progress_waits_for_the_complete_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            objects = build / "obj"
            objects.mkdir()
            generated = build / "gen/main"
            generated.mkdir(parents=True)
            first, second = generated / "first.c", generated / "second.c"
            first.write_text("first"); second.write_text("second")
            (objects / "list_O0.txt").write_text(str(first) + "\n")
            (objects / "list_O1.txt").write_text(str(second) + "\n")
            self.assertIsNone(driver._ios_compile_count(build))
            (objects / ".compile-total").write_text("2\n")
            compiled = objects / "main_first.o"
            compiled.write_bytes(b"object")
            self.assertEqual(driver._ios_compile_count(build), (1, 2))
            newer = compiled.stat().st_mtime_ns + 1
            os.utime(first, ns=(newer, newer))
            self.assertEqual(driver._ios_compile_count(build), (0, 2))

    @unittest.skipIf(os.name == "nt", "bash build phase")
    def test_ios_image_phase_returns_success_after_both_link_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / "python3"
            tool.write_text('#!/bin/sh\nprintf \'%s\\n\' "$CODEGEN_TEST_NATIVE"\n')
            tool.chmod(0o755)
            native = root / "native-generator"
            native.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CODEGEN_TEST_CALLS"\n')
            native.chmod(0o755)
            calls = root / "calls"
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get("PATH", ""),
                               IMG=str(root / "images"), BDSP_EXEFS_DIR=str(root / "exefs"),
                               CODEGEN_TEST_NATIVE=str(native), CODEGEN_TEST_CALLS=str(calls))
            result = subprocess.run(["bash", str(Path(ROOT) / "scripts/recomp/ios/gen32.sh"), "img"],
                                    env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = calls.read_text().splitlines()
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row.startswith("image ") for row in rows))
            self.assertTrue(all("--interpose-from" not in row for row in rows[:3]))
            self.assertTrue(all("--interpose-from" in row for row in rows[3:]))

    def test_native_generator_error_keeps_the_exact_phase_and_cause(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        message = "bdsp_codegen [analyze/subsdk1]: error: cross-module entry outside module text"
        command = [sys.executable, "-c", "import sys; print(" + repr(message) + "); sys.exit(4)"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(driver._run_command(command, args, "eh_gen"), 4)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        error = next(e for e in events if e["event"] == "error")
        self.assertIn(message, error["message"])

    def test_generator_live_logs_do_not_count_a_module_twice(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        text = "main: progress 1024/2000 files 8\nmain: wrote 16 chunks\nmodule=main generated\nsdk: wrote 2 chunks\n"
        command = [sys.executable, "-c", "print(" + repr(text) + ")"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(driver._run_command(command, args, "eh_gen"), 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([e["completed"] for e in events if e["event"] == "progress" and "module" not in e], [1, 2])
        self.assertFalse(any("1024/2000" in e.get("message", "") for e in events))
        self.assertTrue(any(e.get("module") == "main" and e["completed"] == 1024 for e in events))

    def test_filesystem_failure_keeps_its_actual_cause(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        message = "rm: generated output: Directory not empty"
        command = [sys.executable, "-c", "print(" + repr(message) + "); raise SystemExit(1)"]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver._run_command(command, args, "eh_gen"), 1)
        errors = [json.loads(line) for line in output.getvalue().splitlines() if json.loads(line)["event"] == "error"]
        self.assertIn(message, errors[-1]["message"])

    def test_stage_durations_are_reported_independently(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        command = [sys.executable, "-c", "print('2/6 compile: fixture',flush=True)"]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver._run_command(command, args, "eh_gen", phase_from_line=driver._mac_phase), 0)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        timed = [e for e in events if "elapsed_seconds" in e]
        self.assertEqual([e["id"] for e in timed], ["eh_gen", "clang"])
        self.assertTrue(all(e["elapsed_seconds"] >= 0 for e in timed))
        self.assertTrue(any("clang:" in e.get("message", "") for e in events))

    def test_native_function_progress_preserves_analysis_and_mod_module_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "subsdk1").touch()
            args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
            text = "main: analyzing module\nmain: progress 0/2000 files 0\nmain: progress 1024/2000 files 8\nmain: wrote 16 chunks\nsdk: analyzing module\n"
            command = [sys.executable, "-c", "print(" + repr(text) + ")"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = driver._run_command(command, args, "eh_gen", extra_env={"BDSP_EXEFS_DIR": folder})
            self.assertEqual(code, 0)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            progress = [e for e in events if e.get("module")]
            self.assertEqual([e["phase"] for e in progress], ["analyze", "emit", "emit", "analyze"])
            self.assertEqual([e["completed"] for e in progress], [0, 0, 1024, 0])
            self.assertTrue(all(e["modules_total"] == 5 for e in progress))
            self.assertEqual(progress[-1]["modules_completed"], 1)
            self.assertEqual(progress[-1]["total"], 0)

    def test_build_commands_do_not_inherit_a_previous_mod_build_source(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        command = [sys.executable, "-c", "import os; print('SOURCE=' + str(os.getenv('BDSP_EXEFS_DIR')))"]
        with patch.dict(os.environ, BDSP_EXEFS_DIR="previous-mod"), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver._run_command(command, args, "eh_gen"), 0)
        self.assertIn("SOURCE=None", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver._run_command(command, args, "eh_gen", extra_env={"BDSP_EXEFS_DIR": "selected-mod"}), 0)
        self.assertIn("SOURCE=selected-mod", output.getvalue())

    def test_free_apple_signing_limit_has_an_actionable_diagnostic(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        command = [sys.executable, "-c", "print('maximum number of installed apps using a free developer profile'); raise SystemExit(1)"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver._run_command(command, args, "install"), 1)
        self.assertIn("Remove an unused development-signed app", args.command_failure_hint)
        self.assertIn("does not replace your original game", args.command_failure_hint)

    def test_failed_compiler_emits_stage_and_first_error_as_a_protocol_error(self):
        args = SimpleNamespace(root=ROOT, base=None, prod_keys=None, update=None)
        command = [sys.executable, "-c",
                   "print(\"kernel.c:12:10: fatal error: 'sys/sysctl.h' file not found\"); "
                   "print('1 error generated.'); raise SystemExit(1)"]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver._run_command(command, args, "runtime"), 1)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        failure = events[-1]
        self.assertEqual(failure["event"], "error")
        self.assertTrue(failure["message"].startswith("Build step failed: runtime\n"))
        self.assertIn("sys/sysctl.h", failure["message"])
        self.assertNotIn("1 error generated", failure["message"])

    def test_ios_metadata_and_copy_commands_use_versioned_data_paths_without_saves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            (work / "romfs/Data").mkdir(parents=True)
            (work / "romfs/Data/game.bin").write_bytes(b"base")
            mod = root / "mod"
            (mod / "romfs").mkdir(parents=True)
            (mod / "romfs/game.bin").write_bytes(b"override")
            build_dir = work / "recomp/code/ios"
            prepared = {"build_dir": build_dir, "staged": work / "staged", "bundle_id": "dev.test.mod"}
            args = SimpleNamespace(root=root, work=work, mod_root=mod, mod_name="Example", ios_bundle_id=None)
            device = {"id": "connected-device", "udid": "device-udid", "name": "Test iPad"}
            with contextlib.redirect_stdout(io.StringIO()):
                environment = driver._prepare_ios(args, prepared, device)
            metadata = driver.plistlib.loads((build_dir / "res/install-data.plist").read_bytes())
            self.assertTrue(metadata["RomFSDirectory"].startswith("GameData/"))
            self.assertTrue(metadata["ModDirectory"].startswith("Mods/"))
            self.assertTrue(metadata["CompiledExeFS"])
            self.assertEqual(environment["BDSP_IOS_BUNDLE_ID"], "dev.test.mod")
            artifact = build_dir / "BDSP.app"
            (artifact / "res").mkdir(parents=True)
            (artifact / "Info.plist").write_bytes(driver.plistlib.dumps({"CFBundleIdentifier": "dev.test.mod"}))
            (artifact / "res/install-data.plist").write_bytes(driver.plistlib.dumps(metadata))
            with patch.object(driver, "_run_command", return_value=0) as run, contextlib.redirect_stdout(io.StringIO()):
                driver._install_ios(args, artifact)
            copies = [call.args[0] for call in run.call_args_list[1:]]
            self.assertEqual(len(copies), 2)
            for command in copies:
                self.assertNotIn("--remove-existing-content", command)
                destination = command[command.index("--destination") + 1]
                self.assertTrue(destination.startswith(("Documents/GameData/", "Documents/Mods/")))
                self.assertNotIn("Saves", destination)
            before = metadata["ModDirectory"]
            (mod / "romfs/game.bin").write_bytes(b"new mod version")
            with contextlib.redirect_stdout(io.StringIO()):
                driver._prepare_ios(args, prepared, device)
            self.assertNotEqual(before, args.ios_install["metadata"]["ModDirectory"])
            with patch.object(driver, "_run_command") as run:
                with self.assertRaisesRegex(ValueError, "does not match"):
                    driver._install_ios(args, artifact)
                run.assert_not_called()
            args.ios_bundle_id = "dev.local.xnubdsp"
            with self.assertRaisesRegex(ValueError, "original game's bundle identifier"), contextlib.redirect_stdout(io.StringIO()):
                driver._prepare_ios(args, prepared, device)

    def test_ios_device_selection_prefers_one_connected_ipad_and_requires_unambiguous_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(work=temporary, ios_device=None)
            def discover(command, **_kwargs):
                devices = [{"identifier": identifier, "hardwareProperties": {"platform": "iOS", "productType": model, "udid": identifier},
                            "connectionProperties": {"tunnelState": state}, "deviceProperties": {"name": model}}
                           for identifier, model, state in (("phone", "iPhone", "connected"), ("ipad", "iPad", "connected"), ("sim", "iPad", "disconnected"))]
                Path(command[-1]).write_text(json.dumps({"result": {"devices": devices}}))
                return SimpleNamespace(returncode=0)
            with patch.object(driver.subprocess, "run", side_effect=discover):
                self.assertEqual(driver._ios_device(args)["id"], "ipad")
                args.ios_device = "phone"
                self.assertEqual(driver._ios_device(args)["id"], "phone")
                args.ios_device = "missing"
                with self.assertRaises(ValueError):
                    driver._ios_device(args)

    @unittest.skipUnless(sys.platform == "darwin", "macOS bundle installation")
    def test_separate_mod_app_has_its_own_installation_and_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(root=root, work=root, target="macos", install_root=root / "Applications")
            for name in ("BDSP.app", "BDSP-mod-example.app"):
                bundle = root / "build" / name
                (bundle / "Contents/MacOS").mkdir(parents=True)
                (bundle / "Contents/MacOS/BDSP").write_bytes(name.encode())
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.install_artifact(args, bundle)
            for name in ("BDSP", "BDSP-mod-example"):
                self.assertTrue((args.install_root / (name + ".app/Contents/MacOS/BDSP")).is_file())
                self.assertTrue((args.install_root / ("." + name + ".installer-receipt.json")).is_file())

    def test_selected_mod_exefs_is_found_case_insensitively_and_staged_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "work"
            base = work / "exefs"
            base.mkdir(parents=True)
            for module in ("rtld", "main", "sdk", "subsdk0"):
                (base / module).write_bytes(module.encode("ascii"))
            mod = Path(temporary) / "mods/Luminescent"
            exefs = mod / "ExeFS"
            exefs.mkdir(parents=True)
            (exefs / "0123.IPS").write_bytes(b"PATCH EOF")
            helper = Path(temporary) / "ips_patch"
            helper.write_text("#!/bin/sh\nmkdir -p \"$4\"\ncp \"$2/main\" \"$4/main\"\n")
            helper.chmod(0o755)
            args = SimpleNamespace(target="macos", mod_root=mod, mod_name="Luminescent",
                                   mods_dir=mod.parent, ips_helper=helper, root=temporary,
                                   base="base.xci", prod_keys="prod.keys", update=None)
            with contextlib.redirect_stdout(io.StringIO()):
                prepared = driver._prepare_code_mod(args, work)
            self.assertTrue((prepared["staged"] / "main").is_file())
            self.assertTrue(prepared["app_name"].startswith("BDSP-luminescent-"))
            self.assertEqual(prepared["name"], "Luminescent")
            self.assertEqual((base / "main").read_bytes(), b"main")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                again = driver._prepare_code_mod(args, work)
            self.assertEqual(prepared["staged"], again["staged"])
            self.assertIn('"status": "skipped"', output.getvalue())

    @unittest.skipUnless(sys.platform == "darwin", "native Mac mod build")
    def test_mod_build_routes_staged_code_icons_and_identity_to_the_separate_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            mod = root / "mods/Example"
            (mod / "exefs").mkdir(parents=True)
            (mod / "exefs/0123.ips").write_bytes(b"PATCHEOF")
            for name in ("base.xci", "prod.keys", "ips_patch"):
                (root / name).write_bytes(b"fixture")
            prepared = {"staged": work / "mod/exefs", "build_dir": work / "mod",
                        "app_name": "BDSP-example.app", "bundle_id": "dev.local.xnubdsp.mod.example",
                        "name": "Example", "mods_dir": mod.parent, "root": mod}
            artifact = work / "builds/macos-recomp/BDSP-example.app"
            artifact.mkdir(parents=True)
            args = SimpleNamespace(root=root, work=work, target="macos", base=root / "base.xci",
                                   prod_keys=root / "prod.keys", update=None, mod_root=mod,
                                   mod_name="Example", mods_dir=mod.parent, ips_helper=root / "ips_patch")
            with patch.object(driver, "check_build_dependencies", return_value=0), \
                 patch.object(driver, "_prepare_code_mod", return_value=prepared), \
                 patch.object(driver, "_run_command", return_value=0) as run, \
                 patch.object(driver, "install_artifact") as install, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(driver.build(args), 0)
            command = run.call_args_list[-1]
            self.assertIn(str(artifact), command.args[0])
            env = command.kwargs["extra_env"]
            self.assertEqual(env["BDSP_EXEFS_DIR"], str(prepared["staged"]))
            self.assertEqual(env["BDSP_MOD_ROOT"], str(mod))
            self.assertEqual(env["BDSP_MOD_BUNDLE_ID"], prepared["bundle_id"])
            self.assertEqual(env["BDSP_ICON_SOURCE"], str(work / "recomp/icons/source"))
            install.assert_called_once_with(args, artifact)

    @unittest.skipUnless(sys.platform == "darwin", "macOS app bundle smoke test")
    def test_build_protocol_runs_stubbed_steps_and_installs_to_test_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = os.path.join(temporary, "repo")
            scripts = os.path.join(root, "scripts")
            os.makedirs(os.path.join(scripts, "recomp/app"))
            os.makedirs(os.path.join(root, "work"))
            with open(os.path.join(scripts, "build_stages.py"), "w") as file:
                file.write("EX_DISK=8\nEX_TOOLS=4\ndef preflight(*args, **kwargs): return []\ndef format_preflight(items): return ([], [], False)\n")
            with open(os.path.join(scripts, "build_all.sh"), "w") as file:
                file.write("#!/bin/sh\necho 'extract fixture'\n")
            os.chmod(os.path.join(scripts, "build_all.sh"), 0o755)
            recomp = os.path.join(scripts, "recomp/app/recomp_build.sh")
            with open(recomp, "w") as file:
                file.write("#!/usr/bin/env python3\nfrom pathlib import Path\n"
                           "root=Path(__file__).resolve().parents[3]\n"
                           "app=root/'work/builds/macos-recomp/BDSP.app/Contents/MacOS'\n"
                           "app.mkdir(parents=True)\n(app/'BDSP').write_bytes(b'fixture')\n"
                           "print('1/6 generator: fixture',flush=True)\n"
                           "print('2/6 compile: fixture',flush=True)\n"
                           "print('3/6 module images',flush=True)\n"
                           "print('4/6 building runtime',flush=True)\n"
                           "print('5/6 assembling',flush=True)\n")
            os.chmod(recomp, 0o755)
            base = os.path.join(temporary, "base.xci")
            keys = os.path.join(temporary, "prod.keys")
            for path in (base, keys):
                with open(path, "wb") as file:
                    file.write(b"fixture")
            applications = os.path.join(temporary, "Applications")
            result = subprocess.run([sys.executable, "-B", DRIVER, "build", "--root", root,
                                     "--work", os.path.join(root, "work"), "--target", "macos",
                                     "--base", base, "--prod-keys", keys,
                                     "--install-root", applications],
                                    cwd=root, capture_output=True, text=True, check=False)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(events[-1], {"event": "result", "ok": True, "code": 0})
            self.assertTrue(any(event.get("id") == "install" and event.get("status") == "complete"
                                for event in events))
            self.assertTrue(os.path.isfile(os.path.join(applications, "BDSP.app/Contents/MacOS/BDSP")))

    def test_free_space_estimate_uses_source_sizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = os.path.join(temporary, "base.xci")
            update = os.path.join(temporary, "update.nsp")
            with open(base, "wb") as file:
                file.truncate(2 * 1024 ** 3)
            with open(update, "wb") as file:
                file.truncate(1024 ** 3)
            args = SimpleNamespace(base=base, update=update)
            self.assertEqual(driver.required_free_gb(args), 40)

            with open(base, "wb") as file:
                file.truncate(20 * 1024 ** 3)
            self.assertEqual(driver.required_free_gb(args), 71)

    @unittest.skipUnless(sys.platform == "darwin", "ditto is a macOS system tool")
    def test_macos_install_copies_bundle_without_replacing_existing_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = os.path.join(temporary, "build/BDSP.app")
            os.makedirs(os.path.join(artifact, "Contents/MacOS"))
            with open(os.path.join(artifact, "Contents/MacOS/BDSP"), "wb") as file:
                file.write(b"binary")
            applications = os.path.join(temporary, "Test installs")
            args = SimpleNamespace(root=temporary, work=temporary, target="macos",
                                   install_root=applications)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                destination = driver.install_artifact(args, artifact)
            self.assertIn(driver._safe_line(applications, args), output.getvalue())
            self.assertNotIn("Copying the signed app bundle to Applications", output.getvalue())
            self.assertEqual(destination.parent, Path(applications))
            self.assertTrue((destination / "Contents/MacOS/BDSP").is_file())
            with contextlib.redirect_stdout(io.StringIO()):
                driver.install_artifact(args, artifact)
            with open(destination / "Contents/MacOS/BDSP", "wb") as file:
                file.write(b"foreign change")
            with self.assertRaises(FileExistsError):
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.install_artifact(args, artifact)

    @unittest.skipUnless(sys.platform == "darwin", "ditto is a macOS system tool")
    def test_macos_missing_app_can_be_reinstalled_with_a_stale_receipt(self):
        for old_receipt in ('{"path": "old", "binary_sha256": "old"}', "invalid old receipt"):
            with self.subTest(receipt=old_receipt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                artifact = root / "build/BDSP.app"
                (artifact / "Contents/MacOS").mkdir(parents=True)
                (artifact / "Contents/MacOS/BDSP").write_bytes(b"new binary")
                applications = root / "Applications"
                applications.mkdir()
                receipt = applications / ".BDSP.installer-receipt.json"
                receipt.write_text(old_receipt)
                args = SimpleNamespace(root=root, work=root, target="macos", install_root=applications)
                # A failed copy must preserve the old receipt and leave no app.
                with patch.object(driver.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ditto")), \
                        contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(subprocess.CalledProcessError):
                        driver.install_artifact(args, artifact)
                self.assertEqual(receipt.read_text(), old_receipt)
                self.assertFalse((applications / "BDSP.app").exists())
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    destination = driver.install_artifact(args, artifact)
                self.assertEqual((destination / "Contents/MacOS/BDSP").read_bytes(), b"new binary")
                self.assertEqual(json.loads(receipt.read_text())["path"], str(destination))
                self.assertIn("renewing its installation receipt", output.getvalue())
                self.assertFalse(list(applications.glob("*.app-staging-*")))

    def test_clean_build_removes_generated_outputs_but_keeps_game_data_and_unknown_files(self):
        for target, generated in (("macos", ("gen4", "obj4", "rt-bdsp-app", "img_app")),
                                  ("linux", ("gen4-c", "obj4-c", "rt-bdsp-vk", "img_gfx")),
                                  ("ios", ("gen", "obj", "rt", "derived"))):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                work = root / "work"
                directory = work / "recomp"
                for name in (*generated, "icons", "mods", "unknown"):
                    (directory / name).mkdir(parents=True)
                    (directory / name / "sentinel").write_text(name)
                for name in ("exefs", "romfs", "saves"):
                    (work / name).mkdir()
                    (work / name / "sentinel").write_text(name)
                keys = root / "prod.keys"
                keys.write_text("keys")
                args = SimpleNamespace(root=root, work=work, target=target, base=root / "game.xci", prod_keys=keys)
                with contextlib.redirect_stdout(io.StringIO()):
                    driver._clean_game_build(args, directory)
                for name in generated:
                    self.assertFalse((directory / name).exists())
                for name in ("icons", "mods", "unknown"):
                    self.assertEqual((directory / name / "sentinel").read_text(), name)
                for name in ("exefs", "romfs", "saves"):
                    self.assertEqual((work / name / "sentinel").read_text(), name)
                self.assertEqual(keys.read_text(), "keys")

    def test_clean_build_rejects_external_directories_and_selected_inputs_before_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            directory = work / "recomp"
            (directory / "gen4").mkdir(parents=True)
            (directory / "obj4").mkdir()
            key = directory / "obj4/prod.keys"
            key.write_text("private key")
            args = SimpleNamespace(root=root, work=work, target="macos", base=root / "game.xci", prod_keys=key)
            with self.assertRaises(ValueError):
                driver._clean_game_build(args, directory)
            self.assertTrue((directory / "gen4").is_dir())
            self.assertEqual(key.read_text(), "private key")
            with self.assertRaises(ValueError):
                driver._clean_game_build(args, root / "external")
            with self.assertRaises(ValueError):
                driver._clean_game_build(args, work)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symbolic links are unavailable")
    def test_clean_build_refuses_a_recomp_link_outside_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            work.mkdir()
            outside = root / "originals"
            (outside / "gen4").mkdir(parents=True)
            (outside / "gen4/save").write_text("untouched")
            (work / "recomp").symlink_to(outside, target_is_directory=True)
            args = SimpleNamespace(root=root, work=work, target="macos", base=root / "game.xci", prod_keys=root / "prod.keys")
            with self.assertRaises(ValueError):
                driver._clean_game_build(args, work / "recomp")
            self.assertEqual((outside / "gen4/save").read_text(), "untouched")

    def test_ios_failed_extraction_never_resets_build_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(root=root, work=root / "work", target="ios", clean_build=True)
            with patch.object(driver, "_ios_device", return_value={"name": "test device"}), \
                    patch.object(driver, "required_free_gb", return_value=40), \
                    patch.object(driver, "_run_command", return_value=4), \
                    patch.object(driver, "_clean_game_build") as clean, \
                    contextlib.redirect_stdout(io.StringIO()):
                code, _ = driver._build_ios(args, [])
            self.assertEqual(code, 4)
            clean.assert_not_called()

    def test_linux_install_isolated_package_keeps_saves_and_refuses_foreign_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = os.path.join(temporary, "repo")
            work = os.path.join(root, "work")
            for directory in ("romfs/Data", "recomp/img_gfx", "recomp/icons/linux", "exefs"):
                os.makedirs(os.path.join(work, directory), exist_ok=True)
            os.makedirs(os.path.join(root, "scripts/recomp/rt-bdsp/app/linux/lproj/en.lproj"))
            for relative in ("romfs/Data/game.bin", "recomp/img_gfx/main.img", "exefs/main.npdm",
                             "recomp/icons/linux/icon.png"):
                with open(os.path.join(work, relative), "wb") as file:
                    file.write(b"fixture")
            with open(os.path.join(root, "scripts/recomp/rt-bdsp/app/linux/lproj/en.lproj/Localizable.strings"), "w") as file:
                file.write("fixture")
            manifest = {"default": "en-US", "variants": [{"id": "en-US", "image": "icon.png"}]}
            with open(os.path.join(work, "recomp/icons/linux/icons.json"), "w") as file:
                json.dump(manifest, file)
            artifact = os.path.join(work, "recomp/bdsp_boot_vk_qt")
            with open(artifact, "wb") as file:
                file.write(b'#!/bin/sh\nprintf "%s|%s|%s\\n" "$BDSP_IMG" "$BDSP_SAVE" "$BDSP_MOD"\n')
            os.chmod(artifact, 0o755)
            install_root = os.path.join(temporary, "install")
            mods = os.path.join(temporary, "my mods")
            args = SimpleNamespace(root=root, work=work, target="linux", install_root=install_root)
            with patch.dict(os.environ, {"BDSP_MODS_DIR": mods, "BDSP_MOD": "Example Mod"}), \
                 contextlib.redirect_stdout(io.StringIO()):
                installed = driver.install_artifact(args, artifact)
            self.assertTrue((installed / "romfs/Data/game.bin").is_file())
            self.assertTrue((installed / "img/main.img").is_file())
            self.assertTrue((installed / "lproj/en.lproj/Localizable.strings").is_file())
            launcher = os.path.join(install_root, "bin/strahlender-xnu")
            with open(launcher) as file:
                text = file.read()
            self.assertIn("Example Mod", text)
            self.assertIn(mods, text)
            with patch.dict(os.environ, {"BDSP_MOD": ""}):
                launched = subprocess.run([launcher], capture_output=True, text=True, check=True)
            self.assertEqual(launched.stdout.strip(),
                             str(installed / "img") + "|" +
                             os.path.join(install_root, "share/strahlender-xnu/saves") +
                             "|Example Mod")
            save = os.path.join(install_root, "share/strahlender-xnu/saves/untouched.bin")
            with open(save, "wb") as file:
                file.write(b"save")
            with patch.dict(os.environ, {"BDSP_MODS_DIR": mods, "BDSP_MOD": "none"}), \
                 contextlib.redirect_stdout(io.StringIO()):
                driver.install_artifact(args, artifact)
            with open(save, "rb") as file:
                self.assertEqual(file.read(), b"save")
            os.remove(installed / ".installer-owned")
            with self.assertRaises(FileExistsError):
                with contextlib.redirect_stdout(io.StringIO()):
                    driver.install_artifact(args, artifact)

    def test_disk_only_failure_has_disk_exit_code(self):
        item = {"name": "Disk space >= 40 GB free", "ok": False,
                "detail": "53 GB free", "hint": "Free up space", "level": "missing"}
        stages = SimpleNamespace(
            preflight=lambda *args, **kwargs: [item],
            format_preflight=lambda items: (["missing"], items, True),
            EX_DISK=8, EX_TOOLS=4,
        )
        args = SimpleNamespace(root=ROOT, work="/missing/work", tools_dir="/missing/tools",
                               target="macos", min_free_gb=40)
        output = io.StringIO()
        with patch.object(driver, "load_build_stages", return_value=stages), contextlib.redirect_stdout(output):
            code = driver.preflight(args)
        self.assertEqual(code, 8)
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1]),
                         {"event": "result", "ok": False, "code": 8})

    def test_preflight_emits_versioned_events_without_creating_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = os.path.join(temporary, "not-created", "work")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    DRIVER,
                    "preflight",
                    "--root",
                    ROOT,
                    "--work",
                    work,
                    "--tools-dir",
                    os.path.join(ROOT, "tools"),
                    "--target",
                    "macos",
                    "--min-free-gb",
                    "0",
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                check=False,
            )

            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(events[0], {"event": "hello", "protocol": 2, "capabilities": ["preflight", "build"]})
            self.assertTrue(any(event["event"] == "step" for event in events))
            self.assertTrue(any(event["event"] == "log" for event in events))
            self.assertEqual(events[-1]["event"], "result")
            self.assertNotIn(ROOT, result.stdout)
            self.assertFalse(os.path.exists(work))
            self.assertEqual(result.stderr, "")

    def test_build_rejects_unknown_game_format_before_running_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = os.path.join(temporary, "base.zip")
            keys = os.path.join(temporary, "prod.keys")
            for path in (base, keys):
                with open(path, "wb") as file:
                    file.write(b"fixture")
            args = SimpleNamespace(root=temporary, work=os.path.join(temporary, "work"), target="macos" if sys.platform == "darwin" else "linux",
                                   base=base, prod_keys=keys, update=None)
            output = io.StringIO()
            with patch.object(driver, "_run_command") as run, contextlib.redirect_stdout(output):
                code = driver.build(args)
            self.assertEqual(code, 2)
            run.assert_not_called()
            self.assertIn("base XCI, base NSP or NCA folder", output.getvalue())

    def test_build_passes_each_base_format_to_extractor(self):
        target = "macos" if sys.platform == "darwin" else "linux"
        with tempfile.TemporaryDirectory() as temporary:
            root = os.path.join(temporary, "repo")
            work = os.path.join(root, "work")
            os.makedirs(os.path.join(root, "scripts"))
            artifact = os.path.join(work, "builds/macos-recomp/BDSP.app" if target == "macos" else "recomp/bdsp_boot_vk_qt")
            os.makedirs(os.path.dirname(artifact))
            if target == "macos":
                os.makedirs(artifact)
            else:
                with open(artifact, "wb") as file:
                    file.write(b"fixture")
            keys = os.path.join(temporary, "prod.keys")
            with open(keys, "wb") as file:
                file.write(b"fixture")
            for name, expected in (("base.xci", "--xci"), ("base.nsp", "--base-nsp"),
                                   ("nca", "--base-nca-dir")):
                base = os.path.join(temporary, name)
                if name == "nca":
                    os.mkdir(base)
                else:
                    with open(base, "wb") as file:
                        file.write(b"fixture")
                args = SimpleNamespace(root=root, work=work, target=target, base=base,
                                       prod_keys=keys, update=None)
                with patch.object(driver, "check_build_dependencies", return_value=0), \
                     patch.object(driver, "install_artifact"), \
                     patch.object(driver, "_run_command", return_value=0) as run, \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(driver.build(args), 0)
                command = run.call_args_list[0].args[0]
                self.assertIn(expected, command)
                self.assertEqual(command[command.index(expected) + 1], base)

    def test_build_emits_artifact_only_after_existing_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = os.path.join(temporary, "repo")
            work = os.path.join(root, "work")
            os.makedirs(os.path.join(root, "scripts"))
            base = os.path.join(temporary, "base.xci")
            keys = os.path.join(temporary, "prod.keys")
            for path in (base, keys):
                with open(path, "wb") as file:
                    file.write(b"fixture")
            target = "macos" if sys.platform == "darwin" else "linux"
            artifact = os.path.join(work, "builds/macos-recomp/BDSP.app" if target == "macos" else "recomp/bdsp_boot_vk_qt")
            os.makedirs(os.path.dirname(artifact))
            if target == "macos":
                os.makedirs(artifact)
            else:
                with open(artifact, "wb") as file:
                    file.write(b"fixture")
            args = SimpleNamespace(root=root, work=work, target=target, base=base, prod_keys=keys, update=None)
            output = io.StringIO()
            with patch.object(driver, "check_build_dependencies", return_value=0), \
                 patch.object(driver, "install_artifact"), \
                 patch.object(driver, "_run_command", return_value=0) as run, \
                 contextlib.redirect_stdout(output):
                code = driver.build(args)
            self.assertEqual(code, 0)
            self.assertGreater(run.call_count, 0)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(events[-2]["event"], "artifact")
            self.assertEqual(events[-1], {"event": "result", "ok": True, "code": 0})


if __name__ == "__main__":
    unittest.main()
