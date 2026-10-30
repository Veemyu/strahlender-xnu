"""Windows build contracts and synthetic PE/C fixtures; never reads game inputs."""
import os
import contextlib
import ctypes
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.install import driver
from scripts.recomp import portable_build as build
from scripts.recomp import windows_support as windows
from scripts.recomp import windows_process

ROOT = Path(__file__).resolve().parents[2]


def pe(path, imports=(), delayed=(), machine=0x8664):
    """One-section PE fixture, with bounded normal and delay import tables."""
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, machine, 1)
    struct.pack_into("<H", data, 0x94, 240)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20b)
    struct.pack_into("<Q", data, optional + 24, 0x140000000)
    struct.pack_into("<I", data, optional + 60, 0x200)
    struct.pack_into("<I", data, optional + 108, 16)
    struct.pack_into("<IIII", data, optional + 240 + 8, 0x1000, 0x1000, 0x1000, 0x200)
    for names, index, width, rva, raw in ((imports, 1, 20, 0x1000, 0x200),
                                          (delayed, 13, 32, 0x1200, 0x400)):
        if not names:
            continue
        struct.pack_into("<II", data, optional + 112 + index * 8, rva, (len(names) + 1) * width)
        name_raw = raw + 0x100
        for i, name in enumerate(names):
            offset = raw + i * width
            struct.pack_into("<I", data, offset + (12 if index == 1 else 4), rva + name_raw - raw)
            if index == 13:
                struct.pack_into("<I", data, offset, 1)
            encoded = name.encode("ascii") + b"\0"
            data[name_raw:name_raw + len(encoded)] = encoded
            name_raw += len(encoded)
    path = Path(path)
    path.write_bytes(data)
    return path


class WindowsBuildTests(unittest.TestCase):
    def test_qt_missing_sdk_stops_before_compiler_or_overlay_work(self):
        selected = windows.profile("x86_64", "x86_64")
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(build, "compiler_identity") as compiler, \
                patch.object(build, "prepare_vulkan") as overlay, \
                patch.object(build, "compile_sources") as compile_sources:
            for bundle in (None, Path(temporary) / "missing"):
                with self.assertRaisesRegex(ValueError, "Qt development bundle missing"):
                    build.compile_runtime(Path(temporary) / "objects", "unused", selected, None,
                                          qt=bundle)
            compiler.assert_not_called()
            overlay.assert_not_called()
            compile_sources.assert_not_called()
            self.assertFalse((Path(temporary) / "objects").exists())

    def test_qt_bundle_checks_cpp_abi_plugins_closure_and_shared_source_wiring(self):
        selected = windows.profile("x86_64", "x86_64")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            qt = root / "Qt"
            files = ("include/QtCore/qglobal.h", "include/QtGui/QVulkanInstance",
                     "include/QtWidgets/QApplication", "notices/Qt/LICENSE.txt",
                     *(f"lib/libQt6{name}.a" for name in ("Core", "Gui", "Widgets")))
            for name in files:
                path = qt / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic SDK")
            for name, imports in (("bin/Qt6Core.dll", ("kernel32.dll",)),
                                  ("bin/Qt6Gui.dll", ("Qt6Core.dll",)),
                                  ("bin/Qt6Widgets.dll", ("Qt6Gui.dll",)),
                                  ("plugins/platforms/qwindows.dll", ("Qt6Gui.dll",))):
                path = qt / name
                path.parent.mkdir(parents=True, exist_ok=True)
                pe(path, imports)
            compiler = root / "x86_64-w64-mingw32-clang.exe"
            identity = {"path": str(compiler), "sha256": "a" * 64}
            metadata = {"version": "6.8.0", "linkage": "shared", "cxx_runtime": "libc++",
                        "minimum_windows_build": 19045, "cxx_compiler_sha256": identity["sha256"]}
            def receipt():
                build.atomic_json(qt / "build.json", {
                    "schema": 1, "profile": selected, "qualified": False, "qt": metadata,
                    "files": {p.relative_to(qt).as_posix(): windows.sha256(p)
                              for p in qt.rglob("*") if p.is_file() and p.name != "build.json"},
                })
            receipt()
            with patch.object(build, "compiler_identity", return_value=identity), \
                    patch.object(build, "runtime_dll_candidates", return_value=[]):
                self.assertEqual(build.qt_development(qt, compiler, selected), qt)
                for module in ("Core", "Gui", "Widgets"):
                    library = qt / f"lib/libQt6{module}.a"
                    old_name = library.with_name(f"libQt6{module}.dll.a")
                    library.rename(old_name)
                    receipt()
                    with self.assertRaisesRegex(ValueError, rf"libQt6{module}\.a"):
                        build.qt_development(qt, compiler, selected)
                    old_name.rename(library)
                    receipt()
                for key, invalid in (("cxx_runtime", "libstdc++"), ("linkage", "static"),
                                     ("minimum_windows_build", 22000), ("minimum_windows_build", -1),
                                     ("minimum_windows_build", True), ("version", "latest"),
                                     ("cxx_compiler_sha256", "b" * 64)):
                    original = metadata[key]
                    metadata[key] = invalid
                    receipt()
                    with self.assertRaisesRegex(ValueError, "Qt"):
                        build.qt_development(qt, compiler, selected)
                    metadata[key] = original
                receipt()
                plugin = qt / "plugins/platforms/qwindows.dll"
                pe(plugin, ("MissingQtProvider.dll",))
                receipt()
                with self.assertRaisesRegex(ValueError, "Missing DLL"):
                    build.qt_development(qt, compiler, selected)
                pe(plugin, ("Qt6Gui.dll",), machine=0xaa64)
                receipt()
                with self.assertRaisesRegex(ValueError, "architecture"):
                    build.qt_development(qt, compiler, selected)
                plugin.unlink()
                receipt()
                with self.assertRaisesRegex(ValueError, "qwindows.dll"):
                    build.qt_development(qt, compiler, selected)
            # The existing host, not a second Windows UI source, joins the exact compile inventory.
            with patch.object(build, "qt_development", return_value=qt), \
                    patch.object(build, "verified_bundle", return_value=qt), \
                    patch.object(build, "prepare_vulkan", return_value=root / "overlay"), \
                    patch.object(build, "compile_sources", return_value=[]) as compile_sources:
                build.compile_runtime(root / "objects", compiler, selected, None,
                                      qt=qt, sdl=qt, vulkan=qt, ffmpeg=qt)
                options = compile_sources.call_args.kwargs
                self.assertIn(ROOT / "scripts/recomp/rt-bdsp/app/linux/qt_ui.cpp", options["source_paths"])
                self.assertIn("-DBDSP_QT", options["extra"])
                self.assertIn(str(qt / "include/QtWidgets"), options["extra"])

    def test_graphical_link_uses_official_qt_import_library_names(self):
        selected = windows.profile("x86_64", "x86_64")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = root / "llvm/bin/x86_64-w64-mingw32-clang.exe"
            qt = root / "qt"
            bundle = root / "graphics"
            relative = ("lib/libSDL3.dll.a", "lib/libshaderc_shared.dll.a",
                        "lib/libvulkan-1.a",
                        *(f"lib/lib{name}.dll.a" for name in ("avformat", "avcodec", "avutil")))
            paths = [*(bundle / name for name in relative),
                     compiler.parent.parent / "x86_64-w64-mingw32/lib/libc++.dll.a",
                     *(qt / f"lib/libQt6{name}.a" for name in ("Core", "Gui", "Widgets"))]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic import library")
            with patch.object(build, "qt_development", return_value=qt) as qt_check, \
                    patch.object(build, "verified_bundle", return_value=bundle), \
                    patch.object(build, "compiler_identity", return_value={"path": str(compiler)}), \
                    patch.object(build, "runtime_libraries", return_value=[]):
                libraries = build.graphical_libraries(
                    compiler, selected, bundle, bundle, bundle, qt=qt)
                self.assertEqual(libraries[-3:],
                                 [qt / f"lib/libQt6{name}.a" for name in ("Widgets", "Gui", "Core")])
                qt_check.assert_called_once_with(qt, compiler, selected)
                library = qt / "lib/libQt6Widgets.a"
                library.rename(library.with_name("libQt6Widgets.dll.a"))
                with self.assertRaisesRegex(ValueError, r"libQt6Widgets\.a"):
                    build.graphical_libraries(
                        compiler, selected, bundle, bundle, bundle, qt=qt)

    def test_sdl_offline_recipe_paths_target_inventory_and_atomic_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "tools with spaces"
            root.mkdir()
            archive, cmake, ninja = (root / name for name in ("SDL.tar.gz", "cmake.exe", "ninja.exe"))
            for path in (archive, cmake, ninja):
                path.write_bytes(b"synthetic")
            contract = windows.contract()
            component = next(item for item in contract["components"] if item["id"] == "SDL3")
            # The repository pins nothing; the CI job supplies the resolved version and hash.
            component["version"] = "3.4.18"
            component["source_archive"] = {"url": "https://example.invalid/SDL3.tar.gz", "sha256": "0" * 64, "size_bytes": 9}
            with patch.object(build, "compiler_identity") as identity, \
                    patch.object(build.windows, "contract", return_value=contract):
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    build.build_sdl(archive, root / "bad", "", {}, cmake, ninja, None)
                identity.assert_not_called()
            with tarfile.open(archive, "w:gz") as output:
                contents = b"Synthetic license"
                member = tarfile.TarInfo("SDL3-" + component["version"] + "/LICENSE.txt")
                member.size = len(contents)
                output.addfile(member, io.BytesIO(contents))
            component["source_archive"]["sha256"] = windows.sha256(archive)
            for architecture in ("x86_64", "aarch64"):
                with self.subTest(architecture=architecture):
                    selected = windows.profile(architecture, "x86_64")
                    compiler = root / (architecture + "-w64-mingw32-clang.exe")
                    destination = root / architecture
                    configuration = {}
                    fail_build = False
                    def run(command):
                        if "-S" in command:
                            configuration.update(arg[2:].split("=", 1) for arg in command
                                                 if isinstance(arg, str) and arg.startswith("-D"))
                            generated = Path(command[command.index("-B") + 1]) / "generated"
                            generated.mkdir(parents=True)
                            (generated / "SDL_build_config.h").write_text("synthetic config")
                        elif "--build" in command and fail_build:
                            raise RuntimeError("injected SDL build failure")
                        elif "--install" in command:
                            package = Path(configuration["CMAKE_INSTALL_PREFIX:PATH"])
                            for relative in ("include/SDL3/SDL.h", "lib/libSDL3.dll.a", "bin/SDL3.dll"):
                                target = package / relative
                                target.parent.mkdir(parents=True, exist_ok=True)
                                if target.suffix == ".dll":
                                    pe(target, ["kernel32.dll"], machine=selected["machine"])
                                else:
                                    target.write_bytes(b"synthetic development file")
                    with patch.object(build.windows, "contract", return_value=contract), \
                            patch.object(build, "compiler_identity",
                                         return_value={"path": str(compiler), "sha256": "synthetic"}):
                        build.build_sdl(archive, destination, compiler, selected, cmake, ninja,
                                        SimpleNamespace(run=run), jobs=1)
                        self.assertEqual(configuration["CMAKE_C_COMPILER:FILEPATH"], str(compiler))
                        self.assertEqual(configuration["CMAKE_CXX_COMPILER:FILEPATH"],
                                         str(compiler.with_name(architecture + "-w64-mingw32-clang++.exe")))
                        self.assertEqual(configuration["CMAKE_C_FLAGS"], configuration["CMAKE_CXX_FLAGS"])
                        self.assertEqual(configuration["CMAKE_SYSTEM_PROCESSOR"], architecture)
                        self.assertEqual(configuration["CMAKE_DISABLE_FIND_PACKAGE_Git"], "TRUE")
                        self.assertEqual(configuration["FETCHCONTENT_FULLY_DISCONNECTED"], "ON")
                        self.assertEqual(configuration["SDL_TEST_LIBRARY"], "OFF")
                        record = json.loads((destination / "build.json").read_text())
                        self.assertEqual(record["profile"], selected)
                        self.assertFalse(record["qualified"])
                        self.assertEqual(record["recipe_sha256"], windows.sha256(build.__file__))
                        self.assertIn("notices/SDL3/LICENSE.txt", record["files"])
                        for relative, digest in record["files"].items():
                            self.assertEqual(windows.sha256(destination / relative), digest)
                        with self.assertRaisesRegex(ValueError, "existing"):
                            build.build_sdl(archive, destination, compiler, selected, cmake, ninja, None)
                        fail_build = True
                        with self.assertRaisesRegex(RuntimeError, "injected"):
                            build.build_sdl(archive, root / "failed", compiler, selected, cmake, ninja,
                                            SimpleNamespace(run=run), jobs=1)
                        self.assertFalse((root / "failed").exists())
                        self.assertEqual(list(root.glob("sdl-build-*")), [])

    def test_failed_command_cancels_queue_and_rejects_later_work(self):
        commands = build.Commands()
        try:
            with self.assertRaises(subprocess.CalledProcessError):
                commands.run([sys.executable, "-I", "-c", "raise SystemExit(7)"])
            self.assertTrue(commands.cancelled.is_set())
            with self.assertRaises(InterruptedError):
                commands.run([sys.executable, "-I", "-c", "raise SystemExit(0)"])
        finally:
            commands.close()

    def test_link_inventory_and_tool_free_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            selected = windows.profile("x86_64", "x86_64")
            game, runtime = root / "main_chunk.o", root / "runtime.o"
            for path in (game, runtime):
                path.write_bytes(struct.pack("<H", selected["machine"]) + b"synthetic COFF")
            marker = root / "compile.json"
            build.atomic_json(marker, {"schema": 1, "profile": selected,
                                      "objects": {game.name: windows.sha256(game)}})
            records = {}
            def response(path, arguments):
                records[str(path)] = arguments
            def run(command):
                arguments = records[command[-1][1:]]
                self.assertIn("-fuse-ld=lld", arguments)
                self.assertIn(game, arguments)
                self.assertIn(runtime, arguments)
                pe(arguments[-1], ["SDL3.dll"])
            exe = root / "BDSP.exe"
            with patch.object(build, "compiler_identity", return_value={"path": "clang.exe"}), \
                    patch.object(build, "response_file", side_effect=response):
                build.link_executable(marker, [runtime], [], exe, "clang", selected, SimpleNamespace(run=run))
                game.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    build.link_executable(marker, [runtime], [], exe, "clang", selected, SimpleNamespace(run=run))
            sdl = pe(root / "SDL3.dll")
            compiler = pe(root / "clang.exe")
            notice = root / "SDL-notice.txt"
            notice.write_text("Synthetic license fixture")
            package = build.package_game(exe, [sdl, compiler], "x86_64", root / "package",
                                         {notice.name: notice})
            self.assertEqual({p.name for p in package.iterdir()},
                             {"BDSP.exe", "SDL3.dll", "notices", "package.json"})
            self.assertFalse((package / "clang.exe").exists())
            with self.assertRaisesRegex(ValueError, "existing"):
                build.package_game(exe, [sdl], "x86_64", package, {notice.name: notice})
            with self.assertRaisesRegex(ValueError, "notices"):
                build.package_game(exe, [sdl], "x86_64", root / "bad-package", {})

    @unittest.skipUnless(sys.platform == "win32", "Native Windows job lifecycle")
    def test_compiler_job_owns_descendants_and_cancels_without_orphans(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child.pid"
            grandchild = "import os,time; from pathlib import Path; Path(" + repr(str(marker)) + ").write_text(str(os.getpid())); time.sleep(60)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-I','-c'," + repr(grandchild) + "]); time.sleep(60)"
            job = windows_process.Job()
            process = job.spawn([sys.executable, "-I", "-c", parent])
            descendant = None
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.is_file(), "owned descendant failed to start")
                pid = int(marker.read_text())
                kernel = job.kernel
                kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
                kernel.OpenProcess.restype = ctypes.c_void_p
                descendant = kernel.OpenProcess(0x100000, False, pid)
                self.assertTrue(descendant)
                self.assertEqual(kernel.WaitForSingleObject(descendant, 0), 258)
                job.cancel()
                self.assertEqual(process.wait(timeout=5), 130)
                self.assertEqual(kernel.WaitForSingleObject(descendant, 5000), 0)
            finally:
                if descendant:
                    job.kernel.CloseHandle(descendant)
                job.close()
                process.close()

    @unittest.skipUnless(os.name == "nt", "Mocks sys.platform and needs executable-file semantics of Windows; runs on Windows only")
    def test_generator_windows_exe_and_compiler_identity_cache(self):
        builder = build.load_helper("windows_generator_test", ROOT / "scripts/recomp/native-generator/build.py")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = root / "clang.exe"
            compiler.write_bytes(b"synthetic")
            identity = {"path": str(compiler), "sha256": "compiler-one", "triple": "x86_64-w64-windows-gnu"}
            calls = []
            def compile(command):
                calls.append(command)
                pe(Path(command[-1]))
            with patch.object(builder.sys, "platform", "win32"), \
                    patch.object(builder, "unicorn_dependency", return_value=None), \
                    patch.object(windows, "compiler_identity", side_effect=lambda *args: identity.copy()), \
                    patch.object(builder, "windows_helper", return_value=windows):
                binary = builder.build(root / "bdsp_codegen", str(compiler), command_runner=compile)
                self.assertEqual(binary.name, "bdsp_codegen.exe")
                self.assertIn("-municode", calls[0])
                self.assertIn("-fuse-ld=lld", calls[0])
                builder.build(root / "bdsp_codegen", str(compiler), command_runner=compile)
                self.assertEqual(len(calls), 1)
                identity["sha256"] = "compiler-two"
                builder.build(root / "bdsp_codegen", str(compiler), command_runner=compile)
                self.assertEqual(len(calls), 2)

    def test_profiles_separate_host_target_crt_and_cache(self):
        native = windows.profile("x86_64", "x86_64")
        cross = windows.profile("aarch64", "x86_64")
        arm_host = windows.profile("aarch64", "aarch64")
        self.assertEqual(len({item["cache_key"] for item in (native, cross, arm_host)}), 3)
        self.assertEqual(cross["host"], "x86_64")
        self.assertEqual(cross["target"], "aarch64")
        self.assertEqual(cross["simd"], "c")
        self.assertNotIn("-march=native", native["cpu_flags"])
        self.assertEqual(windows.architecture("AMD64"), "x86_64")
        with self.assertRaises(ValueError):
            windows.architecture("i686")

    def test_contract_has_recipes_but_no_pinned_versions_or_downloads(self):
        data = windows.contract()
        self.assertEqual(data["minimum_windows_build"], 19045)
        runtime = json.loads((ROOT / data["private_runtime"]["manifest"]).read_text())
        wheels = json.loads((ROOT / data["private_runtime"]["wheels"]).read_text())
        self.assertIn("windows-x86_64", runtime["targets"])
        self.assertIn("unicorn==2.1.4", wheels["targets"]["windows-x86_64"])
        self.assertFalse(data["profiles"]["aarch64"]["accepted"])
        text = json.dumps(data)
        self.assertNotRegex(text, r'"sha256": "[0-9a-f]{64}"')  # hashes are measured per run (resolve_inputs.py)
        recipes = {item["id"]: item.get("build_recipe", {}) for item in data["components"]}
        self.assertEqual(recipes["SDL3"]["status"], "implemented-offline")
        self.assertEqual(recipes["ffmpeg"]["component"], "ffmpeg")
        self.assertFalse(recipes["ffmpeg"]["redistribution_qualified"])
        self.assertEqual(recipes["hactool"]["component"], "hactool")
        for item in data["components"]:
            self.assertTrue(item["qualification"])

    def test_pe_normal_delay_imports_and_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            exe = pe(root / "BDSP.exe", ["SDL3.dll", "KERNEL32.dll", "api-ms-win-core-file-l1-1-0.dll"],
                     delayed=["shaderc_shared.dll", "vulkan-1.dll"])
            sdl = pe(root / "SDL3.dll", ["winmm.dll", "libwinpthread-1.dll"])
            pthread = pe(root / "libwinpthread-1.dll", ["ucrtbase.dll"])
            shader = pe(root / "shaderc_shared.dll", ["kernel32.dll"])
            self.assertIn("shaderc_shared.dll", windows.PE(exe).imports())
            selected = windows.dll_closure(exe, [sdl, pthread, shader], "x86_64")
            self.assertEqual(set(selected), {exe, sdl, pthread, shader})
            with self.assertRaisesRegex(ValueError, "Missing DLL"):
                windows.dll_closure(exe, [sdl, shader], "x86_64")
            with self.assertRaisesRegex(ValueError, "dynamically"):
                windows.dll_closure(exe, [sdl, pthread, shader], "x86_64", ["codec.dll"])
            pe(shader, machine=0xaa64)
            with self.assertRaisesRegex(ValueError, "architecture"):
                windows.dll_closure(exe, [sdl, pthread, shader], "x86_64")

    def test_qt_platform_imports_resolve_to_baseline_windows_system_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            exe = pe(Path(temporary) / "qt-host.exe",
                     ["authz.dll", "mpr.dll", "netapi32.dll", "uxtheme.dll",
                      "d3d9.dll", "mscms.dll", "shcore.dll"])
            self.assertEqual(windows.dll_closure(exe, [], "x86_64"), [exe])
            pe(exe, ["not-a-windows-system-library.dll"])
            with self.assertRaisesRegex(ValueError, "Missing DLL"):
                windows.dll_closure(exe, [], "x86_64")

    def test_pe_rejects_truncation_unbounded_imports_and_build_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            exe = pe(root / "BDSP.exe", ["unicorn.dll"])
            engine = pe(root / "unicorn.dll")
            with self.assertRaisesRegex(ValueError, "Build-only"):
                windows.dll_closure(exe, [engine], "x86_64")
            self.assertEqual(len(windows.dll_closure(exe, [engine], "x86_64", allow_build_tools=True)), 2)
            with self.assertRaisesRegex(ValueError, "Ambiguous"):
                windows.dll_closure(exe, [engine, engine], "x86_64")
            exe.write_bytes(exe.read_bytes()[:100])
            with self.assertRaisesRegex(ValueError, "Truncated"):
                windows.PE(exe)
            pe(exe, ["SDL3.dll"])
            data = bytearray(exe.read_bytes())
            struct.pack_into("<I", data, 0x98 + 112 + 8 + 4, 20)
            exe.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "Unterminated"):
                windows.PE(exe).imports()

    @unittest.skipUnless(os.name == "nt", "Mocks sys.platform and needs executable-file semantics of Windows; runs on Windows only")
    def test_compiler_rejects_msvc_msvcrt_and_wrong_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "clang.exe"
            compiler.write_bytes(b"compiler")
            selected = windows.profile("x86_64", "x86_64")
            for triple, macros, valid in (
                ("x86_64-pc-windows-msvc", "", False),
                ("aarch64-w64-windows-gnu", "", False),
                ("x86_64-w64-windows-gnu", "#define __MINGW32__ 1\n", False),
                ("x86_64-w64-windows-gnu", "#define __MINGW32__ 1\n#define _UCRT 1\n", True),
            ):
                def query(command, **kwargs):
                    return SimpleNamespace(stdout=triple if "-dumpmachine" in command else
                                           macros if "-dM" in command else "clang version synthetic")
                if valid:
                    self.assertEqual(windows.compiler_identity(str(compiler), selected, query)["triple"], triple)
                else:
                    with self.assertRaises(ValueError):
                        windows.compiler_identity(str(compiler), selected, query)

    @unittest.skipUnless(sys.platform == "win32", "Native Windows command-line parser")
    def test_response_file_unicode_spaces_quotes_and_trailing_backslashes(self):
        arguments = ["clang", "C:\\O'Brien 日本語\\a b.c", 'a"b', "C:\\trailing slash\\", "", "@literal"]
        with tempfile.TemporaryDirectory() as temporary:
            response = Path(temporary) / "compile.rsp"
            build.response_file(response, arguments)
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            parse = shell.CommandLineToArgvW
            parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
            parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
            count = ctypes.c_int()
            result = parse(response.read_text(encoding="utf-8").rstrip("\n"), ctypes.byref(count))
            self.assertTrue(result)
            try:
                self.assertEqual([result[i] for i in range(count.value)], arguments)
            finally:
                kernel = ctypes.WinDLL("kernel32")
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree(ctypes.cast(result, ctypes.c_void_p))

    def test_response_rejects_newline_and_atomic_json_cleans_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "output"
            with self.assertRaises(ValueError):
                build.response_file(path, ["bad\nargument"])
            with self.assertRaises(TypeError):
                build.atomic_json(path, object())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_generation_order_entries_and_simd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name in build.BASES:
                (root / name).write_bytes(b"synthetic")
            (root / "subsdk1.entries").write_text("0x100\n")
            generator = root / "generator.exe"
            generator.write_bytes(b"synthetic generator")
            def run(command):
                commands.calls.append(command)
                (command[5] / "chunk.c").write_text("void f_synthetic(void) {\n}\n")
            commands = SimpleNamespace(calls=[], run=run)
            build.generate(generator, root, root / "gen", commands)
            self.assertEqual([c[2] for c in commands.calls], ["rtld", "main", "sdk", "subsdk0", "subsdk1"])
            self.assertTrue(all(c[6:8] == ["--simd", "c"] for c in commands.calls))
            self.assertEqual(commands.calls[-1][-2], "--entry-offsets")
            self.assertEqual(len(build.generated_inventory(root / "gen")), 5)
            (root / "subsdk1").unlink()
            build.generate(generator, root, root / "gen", commands)
            self.assertFalse((root / "gen/subsdk1").exists())
            self.assertEqual(len(build.generated_inventory(root / "gen")), 4)
            previous = (root / "gen/.generation.json").read_bytes()
            def failed(command):
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                build.generate(generator, root, root / "gen", SimpleNamespace(run=failed))
            self.assertEqual((root / "gen/.generation.json").read_bytes(), previous)
            (root / "gen/main/chunk.c").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                build.generated_inventory(root / "gen")

    def test_images_are_two_pass_with_explicit_hle_and_no_success_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            exefs = root / "exefs"
            exefs.mkdir()
            for name in ("main", "sdk", "subsdk0"):
                (exefs / name).write_bytes(b"synthetic")
            hle = root / "hle.txt"
            hle.write_text("nvnInit\n")
            calls = []
            def run(command):
                calls.append(command)
                output = Path(command[command.index("--out") + 1])
                (output / (command[3] + ".syms.json")).write_text("{}")
                (output / (command[3] + ".bin")).write_bytes(b"image")
                (output / "hle.txt").write_text("slot")
            build.images("generator.exe", exefs, root / "images", hle, SimpleNamespace(run=run))
            self.assertEqual(len(calls), 6)
            self.assertTrue(all("--link" not in c for c in calls[:3]))
            self.assertTrue(all("--hle-list" in c for c in calls[3:]))
            inventory = json.loads((root / "images/images.json").read_text())
            self.assertIn("main.bin", inventory["files"])
            (exefs / "subsdk1").write_bytes(b"synthetic optional module")
            build.images("generator.exe", exefs, root / "images", hle, SimpleNamespace(run=run))
            self.assertTrue((root / "images/subsdk1.bin").is_file())
            (exefs / "subsdk1").unlink()
            build.images("generator.exe", exefs, root / "images", hle, SimpleNamespace(run=run))
            self.assertFalse((root / "images/subsdk1.bin").exists())
            def failed(command):
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                build.images("generator.exe", exefs, root / "failed", hle, SimpleNamespace(run=failed))
            self.assertFalse((root / "failed/images.json").exists())
            previous = (root / "images/images.json").read_bytes()
            with self.assertRaises(subprocess.CalledProcessError):
                build.images("generator.exe", exefs, root / "images", hle, SimpleNamespace(run=failed))
            self.assertEqual((root / "images/images.json").read_bytes(), previous)

    def test_compile_cache_headers_flags_architecture_hot_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "O'Brien 日本語 build"
            generated = root / "gen/main"
            generated.mkdir(parents=True)
            (generated / "hot.c").write_text("void f_hot(Cpu *c) {\n}\n")
            (generated / "large.c").write_text("void f_large(Cpu *c) {\n}\n" + " " * 100)
            (generated / "small.c").write_text("void f_small(Cpu *c) {\n}\n")
            headers = root / "scripts/recomp/upstream/runtime"
            headers.mkdir(parents=True)
            (headers / "cpu.h").write_text("/* cpu */")
            local = root / "scripts/recomp/rt"
            local.mkdir()
            (local / "cpu.h").write_text("/* local */")
            (root / "scripts/recomp/hot_o2.txt").write_text("f_hot\n")
            selected = windows.profile("x86_64", "x86_64")
            records, calls = {}, []
            real_response = build.response_file
            def response(path, arguments):
                records[str(path)] = arguments
                real_response(path, arguments)
            def run(command):
                arguments = records[str(command[-1])[1:]]
                calls.append(arguments)
                Path(arguments[-1]).write_bytes(b"object")
            commands = SimpleNamespace(run=run, cancel=lambda: None)
            def compile(extra=(), target=selected):
                return build.compile_sources(generated.parent, root / "obj", "clang.exe",
                                             target, commands, jobs=2, extra=extra, threshold=80, root=root)
            with patch.object(build, "compiler_identity", return_value={"path": "clang.exe", "sha256": "synthetic"}), \
                    patch.object(build, "response_file", side_effect=response):
                result = compile()
                self.assertEqual(len(calls), 3)
                self.assertEqual({next(a for a in c if a.startswith("-O")) for c in calls}, {"-O0", "-O1", "-O2"})
                compile()
                self.assertEqual(len(calls), 3)
                result[0].write_bytes(b"corrupt")
                compile()
                self.assertEqual(len(calls), 4)
                (local / "cpu.h").write_text("/* modified */")
                compile()
                self.assertEqual(len(calls), 7)
                compile(["-DTEST=1"])
                self.assertEqual(len(calls), 10)
                compile(target=windows.profile("aarch64", "x86_64"))
                self.assertEqual(len(calls), 13)
                marker = root / "obj" / selected["cache_key"] / "compile.json"
                def fail(command):
                    raise subprocess.CalledProcessError(2, command)
                commands.run = fail
                (generated / "small.c").write_text("void f_changed(Cpu *c) {\n}\n")
                with self.assertRaises(subprocess.CalledProcessError):
                    compile()
                self.assertFalse(marker.exists())

    def test_mixed_c_cpp_uses_target_drivers_flags_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name in ("scripts/recomp/rt/cpu.h", "scripts/recomp/hot_o2.txt"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            source = root / "sources"
            source.mkdir()
            c, cpp = source / "glue.c", source / "vma.cpp"
            for path in (c, cpp):
                path.write_text("synthetic source")
            records, calls = {}, []
            def response(path, arguments):
                records[str(path)] = arguments
            def run(command):
                arguments = records[str(command[-1])[1:]]
                calls.append((command[0], arguments))
                Path(arguments[-1]).write_bytes(b"synthetic object")
            cxx_version = "v1"
            def identity(compiler, selected):
                return {"path": str(compiler), "version": cxx_version if "++" in str(compiler) else "c"}
            selected = windows.profile("aarch64", "x86_64")
            def compile():
                return build.compile_sources(
                    source, root / "objects", root / "aarch64-w64-mingw32-clang.exe",
                    selected, SimpleNamespace(run=run, cancel=lambda: None), jobs=1, root=root,
                    source_paths=[c, cpp], extra=("-I", "overlay"), source_flags={c: ("-DGLUE=1",)})
            with patch.object(build, "compiler_identity", side_effect=identity), \
                    patch.object(build, "response_file", side_effect=response):
                compile()
                self.assertEqual(len(calls), 2)
                for driver, arguments in calls:
                    cxx = "++" in driver
                    self.assertTrue(driver.endswith("aarch64-w64-mingw32-clang" + ("++" if cxx else "") + ".exe"))
                    self.assertIn("-std=c++17" if cxx else "-std=gnu17", arguments)
                    self.assertEqual("-DGLUE=1" in arguments, not cxx)
                    self.assertLess(arguments.index("overlay"), arguments.index(str(root / "scripts/recomp/upstream/runtime")))
                compile()
                self.assertEqual(len(calls), 2)
                cxx_version = "v2"
                compile()
                self.assertEqual(len(calls), 4)

    def test_overlay_is_deterministic_and_preserves_manual_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            base = root / "scripts/recomp/rt-bdsp/nvn"
            for folder, text in (("src/nvn", "base"), ("vulkan/src/nvn", "vulkan")):
                path = base / folder / "test.c"
                path.parent.mkdir(parents=True)
                path.write_text(text)
            translator = root / "shader_translator"
            translator.mkdir()
            for name in ("translate.c", "shader.h"):
                (translator / name).write_text(name)
            output = root / "overlay"
            build.prepare_vulkan(root, output)
            marker = output / ".portable-overlay.json"
            before = marker.stat().st_mtime_ns
            build.prepare_vulkan(root, output)
            self.assertEqual(marker.stat().st_mtime_ns, before)
            self.assertEqual((output / "nvn/test.c").read_text(), "vulkan")
            (output / "nvn/test.c").write_text("user edit")
            with self.assertRaisesRegex(ValueError, "edited"):
                build.prepare_vulkan(root, output)
            self.assertEqual((output / "nvn/test.c").read_text(), "user edit")

    def test_windows_gui_driver_never_dispatches_shell_or_reads_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = SimpleNamespace(root=ROOT, work=ROOT / "work", target="windows",
                                   base=Path(temporary) / "private.nsp",
                                   prod_keys=Path(temporary) / "prod.keys")
            with patch.object(driver, "_run_command", side_effect=AssertionError("No shell fallback")), \
                    patch.object(driver, "load_build_stages", side_effect=AssertionError("No Unix preflight")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(driver.build(args), 4)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(events[-1], {"event": "result", "ok": False, "code": 4})
            self.assertNotIn(str(args.prod_keys), output.getvalue())
            self.assertTrue(any("Windows components" in e.get("message", "") for e in events))


if __name__ == "__main__":
    unittest.main()
