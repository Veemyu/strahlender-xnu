"""Opt-in native LLVM-MinGW/Unicorn checks on synthetic NSOs, without a Git oracle."""
import hashlib
import json
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.install import windows_pipeline
from scripts.recomp import portable_build as build
from scripts.recomp import windows_support as windows
from scripts.tests.test_native_codegen import synthetic_nso, synthetic_eh_nso

ROOT = Path(__file__).resolve().parents[2]


def container(files):
    """Minimal PFS0 (NSP) image for driver tests."""
    names, table, payload = bytearray(), bytearray(), bytearray()
    for name, contents in files:
        table.extend(struct.pack("<QQII", len(payload), len(contents), len(names), 0))
        names.extend(name.encode("utf-8") + b"\0")
        payload.extend(contents)
    return b"PFS0" + struct.pack("<III", len(files), len(names), 0) + table + names + payload


@unittest.skipUnless(os.name == "nt" and os.environ.get("BDSP_WINDOWS_NATIVE_BINARY"),
                     "Set BDSP_WINDOWS_NATIVE_BINARY and BDSP_WINDOWS_NATIVE_CC for native checks")


class WindowsNativeGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "O'Brien 日本語"
        self.root.mkdir()
        self.binary = Path(os.environ["BDSP_WINDOWS_NATIVE_BINARY"]).resolve()
        self.compiler = os.environ["BDSP_WINDOWS_NATIVE_CC"]

    def tearDown(self):
        self.temporary.cleanup()

    def run_native(self, *arguments):
        result = subprocess.run([str(self.binary), *map(str, arguments)], capture_output=True,
                                text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def run_sdl_probe(self, executable, sdl):
        closure = windows.dll_closure(executable, [sdl / "bin/SDL3.dll"], "x86_64")
        for dependency in closure:
            if dependency != executable:
                shutil.copyfile(dependency, executable.parent / dependency.name)
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() != "PATH" and not key.upper().startswith(("BDSP_", "SDL_"))}
        environment["BDSP_DATA_DIR"] = str(self.root / "user data")
        result = subprocess.run([str(executable)], env=environment, cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_native_version_unicode_relocation_and_dll_closure(self):
        version = json.loads(self.run_native("--version", "--json").stdout)
        self.assertEqual(version["host"], "windows-x86_64")
        self.assertEqual(version["unicorn"], "2.1.4")
        self.assertIn("gen", version["capabilities"])
        closure = windows.dll_closure(self.binary, self.binary.parent.glob("*.dll"),
                                      "x86_64", allow_build_tools=True)
        names = {p.name.lower() for p in closure}
        self.assertIn("libunicorn.dll", names)
        self.assertFalse(names & windows.VC_RUNTIME_DLLS, "the generator must not depend on Microsoft's Visual C++ runtime")
        relocated = self.root / "moved tools"
        relocated.mkdir()
        for path in closure:
            shutil.copyfile(path, relocated / path.name)
        result = subprocess.run([str(relocated / self.binary.name), "--version", "--json"],
                                env={key: value for key, value in os.environ.items()
                                     if key.upper() != "PATH"},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["unicorn"], "2.1.4")

    def test_image_relocations_hle_unicode_and_repeatability(self):
        source = synthetic_nso(self.root / "synthetic.nso")
        links = self.root / "links.json"
        links.write_text(json.dumps({"linked": 0x123456789, "日本語🧩": 0x987654321}))
        hle = self.root / "forced.txt"
        hle.write_text("forced\n")
        output = self.root / "images"
        self.run_native("image", source, "main", "--base", "0x7000000000", "--out", output,
                        "--link", links, "--hle-list", hle)
        image = (output / "main.img").read_bytes()
        self.assertEqual(struct.unpack_from("<Q", image, 0x2000)[0], 0x7000000020)
        self.assertEqual(struct.unpack_from("<Q", image, 0x2008)[0], 0x7000000087)
        self.assertEqual(struct.unpack_from("<Q", image, 0x2010)[0], 0x123456785)
        self.assertIn("forced", (output / "hle.txt").read_text().splitlines())
        symbols = json.loads((output / "main.syms.json").read_text(encoding="utf-8"))
        self.assertIn("日本語🧩", symbols)
        hashes = {p.name: windows.sha256(p) for p in output.iterdir()}
        self.run_native("image", source, "main", "--base", "0x7000000000", "--out", output,
                        "--link", links, "--hle-list", hle)
        self.assertEqual(hashes, {p.name: windows.sha256(p) for p in output.iterdir()})

    def test_native_unicorn_generation_is_deterministic_and_compiles_amd64(self):
        source = synthetic_eh_nso(self.root / "synthetic.nso")
        folders = [self.root / "one/main", self.root / "two/main"]
        for folder in folders:
            self.run_native("gen", "main", source, "0x7000000000", folder, "--simd", "c")
        def inventory(folder):
            return {p.name: windows.sha256(p) for p in folder.glob("*.c")}
        self.assertTrue(inventory(folders[0]))
        self.assertEqual(inventory(folders[0]), inventory(folders[1]))
        commands = build.Commands()
        try:
            result = build.compile_sources(folders[0].parent, self.root / "objects", self.compiler,
                                           windows.profile("x86_64", "x86_64"), commands, jobs=2)
            self.assertTrue(result)
            self.assertTrue(all(int.from_bytes(path.read_bytes()[:2], "little") == 0x8664 for path in result))
        finally:
            commands.close()

    def test_windows_eh_header_setjmp_compiles(self):
        source = self.root / "eh.c"
        source.write_text('''#include "bdsp.h"
__attribute__((noinline)) static void jump_out(EhRec *record) { EH_LONGJMP(record->jb, 7); }
static int test(Cpu *c) {
    EH_ENTER(0, 4);
    int value = EH_SETJMP();
    if (!value) jump_out(&eh);
    EH_POP();
    return value;
}
int main(void) { Cpu c = {0}; return test(&c) != 7 || EH_TOP(&c) != 0; }
''')
        executable = self.root / "eh.exe"
        result = subprocess.run([self.compiler, "-std=gnu17", "-mcx16",
                                 "-D__USE_MINGW_SETJMP_NON_SEH", "-Werror=macro-redefined",
                                 "-I", str(ROOT / "scripts/recomp/rt-bdsp"),
                                 "-I", str(ROOT / "scripts/recomp/rt"),
                                 "-I", str(ROOT / "scripts/recomp/upstream/runtime"),
                                 str(source), "-o", str(executable)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_controller_lifecycle_with_stub_devices(self):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        executable = self.root / "pad_sdl_win_test.exe"
        result = subprocess.run([
            self.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
            "-I", str(runtime / "test/sdl_stub"),
            str(runtime / "test/pad_sdl_win_test.c"), "-o", str(executable)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_SDL_ROOT"), "Set the private SDL bundle root")
    def test_real_sdl_entry_virtual_controller_and_dummy_audio_without_path(self):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        sdl = Path(os.environ["BDSP_WINDOWS_SDL_ROOT"]).resolve()
        executable = self.root / "sdl_runtime_test.exe"
        result = subprocess.run([
            self.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror", "-municode",
            "-D_WIN32_WINNT=0x0A00", "-I", str(sdl / "include"),
            "-I", str(runtime), str(runtime / "test/sdl_runtime_test.c"),
            *(str(runtime / (name + ".c")) for name in
              ("win32_entry", "win32_files", "win32_host", "plat", "audio_output", "pad_sdl")),
            str(sdl / "lib/libSDL3.dll.a"), "-lpsapi", "-lbcrypt", "-lwinmm", "-lshell32", "-lole32", "-luuid",
            "-Wl,-Bstatic,-lwinpthread,-Bdynamic", "-o", str(executable)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_sdl_probe(executable, sdl)
        self.assertIn("Real SDL: virtual hotplug/buttons/stick/focus and dummy audio passed.", result.stdout)
        self.assertIn("virtual single Joy-Con L/R normalized controls and reconnect passed.", result.stdout)
        self.assertIn("[audio-output] SDL PCM16 48000 Hz 2 channels", result.stderr)
        self.assertNotIn("failed", result.stderr)
        expected = "[pad] controller reinitialization blocked by another SDL joystick owner\n"
        self.assertEqual(result.stderr.count(expected), 1)
        self.assertNotIn("[pad]", result.stderr.replace(expected, ""))

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_QT_ROOT") and os.environ.get("BDSP_WINDOWS_VULKAN_ROOT"),
                         "Explicit verified Qt and Vulkan bundles required")
    def test_real_qt_controller_menu_with_synthetic_backend(self):
        self.run_qt_fixture(False)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_QT_ROOT") and os.environ.get("BDSP_WINDOWS_VULKAN_ROOT"),
                         "Explicit verified Qt and Vulkan bundles required")
    def test_real_qt_keyboard_to_guest_hid(self):
        self.run_qt_fixture(True)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_QT_ROOT") and os.environ.get("BDSP_WINDOWS_VULKAN_ROOT"),
                         "Explicit verified Qt and Vulkan bundles required")
    def test_real_qt_close_drains_keepalive(self):
        self.run_qt_fixture(False, lifecycle=True)

    def run_qt_fixture(self, keyboard, lifecycle=False):
        qt = build.qt_development(os.environ["BDSP_WINDOWS_QT_ROOT"], self.compiler,
                                  windows.profile("x86_64"))
        sdl = Path(os.environ["BDSP_WINDOWS_SDL_ROOT"]).resolve()
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        compiler = Path(self.compiler).with_name("x86_64-w64-mingw32-clang++.exe")
        executable = self.root / ("qt_keyboard_test.exe" if keyboard else "qt_controller_menu_test.exe")
        includes = [sdl / "include", qt / "include",
                    Path(os.environ["BDSP_WINDOWS_VULKAN_ROOT"]) / "include",
                    *(qt / "include" / name for name in ("QtCore", "QtGui", "QtWidgets"))]
        objects = []
        if lifecycle:
            for name in ("swkbd_keepalive", "host_shutdown"):
                obj = self.root / f"qt-{name}.o"
                result = subprocess.run([
                    self.compiler, "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", runtime,
                    "-c", runtime / f"{name}.c", "-o", obj],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                objects.append(obj)
        if keyboard:
            c_includes = [sdl / "include", runtime / "nvn/vulkan/src", runtime / "nvn/src",
                          runtime / "nvn/src/nvn", ROOT / "scripts/recomp/rt",
                          ROOT / "scripts/recomp/upstream/runtime", runtime]
            for index, source in enumerate(("test/nvn_glue_win_test.c", "nvn/nvn_glue.c",
                                            "nvn/vulkan/vk_glue.c", "input.c",
                                            "win32_files.c", "win32_host.c", "plat.c")):
                obj = self.root / f"qt-input-{index}.o"
                result = subprocess.run([
                    self.compiler, "-std=gnu17", "-O2", "-DQT_INPUT_PROBE", "-D_WIN32_WINNT=0x0A00",
                    "-Dg_debug_frame=bdsp_glue_debug_frame", "-ffunction-sections", "-fdata-sections",
                    *(arg for path in c_includes for arg in ("-I", str(path))),
                    "-c", runtime / source, "-o", obj],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                objects.append(obj)
        result = subprocess.run([
            compiler, "-std=c++17", "-DQT_NO_DEBUG", "-O2",
            *(["-DQT_INPUT_PROBE"] if keyboard else []),
            *(["-DQT_LIFECYCLE_PROBE"] if lifecycle else []),
            *(arg for path in includes for arg in ("-I", str(path))),
            runtime / "test/qt_controller_menu_test.cpp",
            *objects,
            *(qt / f"lib/libQt6{name}.a" for name in ("Widgets", "Gui", "Core")),
            sdl / "lib/libSDL3.dll.a", "-lpsapi", "-lbcrypt", "-lwinmm",
            "-Wl,--gc-sections,-Bstatic,-lwinpthread,-Bdynamic", "-o", executable],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = windows.profile("x86_64")
        providers = build.runtime_dll_candidates(self.compiler, selected, [qt, sdl])
        plugin = qt / "plugins/platforms/qoffscreen.dll"
        plugin_closure = windows.dll_closure(plugin, providers, "x86_64")
        dynamic = [path.name for path in plugin_closure if path != plugin]
        for path in windows.dll_closure(executable, providers, "x86_64", dynamic):
            if path != executable:
                shutil.copyfile(path, self.root / path.name)
        plugins = self.root / "plugins/platforms"
        plugins.mkdir(parents=True)
        shutil.copyfile(plugin, plugins / plugin.name)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("QT_", "BDSP_"))}
        environment.update(QT_QPA_PLATFORM="offscreen", QT_PLUGIN_PATH=str(self.root / "plugins"),
                           BDSP_LPROJ=str(runtime / "app/linux/lproj"),
                           PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
        result = subprocess.run([executable], env=environment, cwd=self.root,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = ("Lifecycle shutdown passed: drained, joined, no future wake, idempotent before surface destruction."
                    if lifecycle else "Real Qt KeyForwarder -> SDL -> input mixer -> registered guest HID passed."
                    if keyboard else "persistence rollback and override gates passed")
        self.assertIn(expected, result.stdout)
        if lifecycle:
            self.assertEqual(result.stderr.count("surface stopped: keepalive joined, CPU drained, GPU idle"), 1)
            environment["BDSP_SHUTDOWN_SURFACE_ONLY"] = "1"
            result = subprocess.run([executable], env=environment, cwd=self.root,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertEqual(result.stderr.count("surface stopped: keepalive joined, CPU drained, GPU idle"), 1)
            del environment["BDSP_SHUTDOWN_SURFACE_ONLY"]
            for stage in ("keepalive", "drain", "gpu"):
                environment["BDSP_SHUTDOWN_NEGATIVE"] = stage
                result = subprocess.run([executable], env=environment, cwd=self.root,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("timeout", result.stderr)
                self.assertIn("FATAL: host shutdown failed; terminating before surface destruction", result.stderr)
                self.assertNotIn("Lifecycle shutdown passed", result.stdout)
                self.assertNotIn("surface stopped:", result.stderr)

    def test_real_swkbd_applet_submit_cancel(self):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        executable = self.root / "swkbd_applet_test.exe"
        result = subprocess.run([
            self.compiler, "-std=gnu17", "-O2", "-D_WIN32_WINNT=0x0A00",
            "-ffunction-sections", "-fdata-sections",
            *(arg for path in (runtime, ROOT / "scripts/recomp/rt",
                              ROOT / "scripts/recomp/upstream/runtime")
              for arg in ("-I", str(path))),
            *(runtime / source for source in (
                "test/swkbd_applet_win_test.c", "services_applet.c", "swkbd_ui.c",
                "swkbd_ime.c", "swkbd_snd.c", "lyt.c", "lyt_tex.c", "lyt_scene.c")),
            "-Wl,--gc-sections,-Bstatic,-lwinpthread,-Bdynamic", "-o", executable],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("BDSP_")}
        environment.update(BDSP_SWKBD_SIMPLE="1", BDSP_SWKBD_SOUND="0")
        result = subprocess.run([executable], env=environment, cwd=self.root,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("UTF-8/UTF-16 submit, cancel and interactive verdict passed", result.stdout)

    def build_nvn_probe(self, compiler, sdl, target):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        fixture = runtime / "test/nvn_glue_win_test.c"
        executable = self.root / ("nvn_glue_test-" + target + ".exe")
        second = self.root / ("second-" + target + ".o")
        flags = [compiler, "-std=gnu17", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-parameter", "-Wno-sign-compare", "-Wno-unused-function",
                 *windows.profile(target, "x86_64")["cpu_flags"], "-ffunction-sections", "-fdata-sections",
                 "-D_WIN32_WINNT=0x0A00", "-Dg_debug_frame=bdsp_glue_debug_frame",
                 *(part for directory in (sdl / "include", runtime / "nvn/vulkan/src", runtime / "nvn/src",
                                          runtime / "nvn/src/nvn", ROOT / "scripts/recomp/rt",
                                          ROOT / "scripts/recomp/upstream/runtime", runtime)
                   for part in ("-I", str(directory)))]
        result = subprocess.run([*flags, "-DHLE_SECOND_OBJECT", "-c", str(fixture), "-o", str(second)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([
            *flags, str(fixture), str(second), str(runtime / "nvn/nvn_glue.c"),
            str(runtime / "nvn/vulkan/vk_glue.c"),
            str(runtime / "win32_files.c"), str(runtime / "win32_host.c"), str(runtime / "plat.c"),
            str(sdl / "lib/libSDL3.dll.a"), "-lpsapi", "-lbcrypt", "-lwinmm",
            "-Wl,--gc-sections,-Bstatic,-lwinpthread,-Bdynamic", "-o", str(executable)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        windows.dll_closure(executable, [sdl / "bin/SDL3.dll"], target)
        return executable

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_SDL_ROOT"), "Set the private SDL bundle root")
    def test_nvn_coff_hle_registration_focus_reset_and_text(self):
        sdl = Path(os.environ["BDSP_WINDOWS_SDL_ROOT"]).resolve()
        executable = self.build_nvn_probe(self.compiler, sdl, "x86_64")
        result = self.run_sdl_probe(executable, sdl)
        self.assertIn("NVN glue: multi-object COFF HLE, keyboard focus reset and UTF-8 text passed.",
                      result.stdout)
        self.assertIn("SDL text: native preedit isolation, main-thread lifecycle and focus ownership passed.",
                      result.stdout)
        self.assertIn("text input requires a window on the SDL main thread", result.stderr)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_SDL_ARM64_ROOT") and
                         os.environ.get("BDSP_WINDOWS_ARM64_CC"), "Set the separate ARM64 SDL bundle/compiler")
    def test_arm64_nvn_coff_and_real_sdl_cross_link_without_execution(self):
        sdl = Path(os.environ["BDSP_WINDOWS_SDL_ARM64_ROOT"]).resolve()
        executable = self.build_nvn_probe(os.environ["BDSP_WINDOWS_ARM64_CC"], sdl, "aarch64")
        self.assertEqual(windows.PE(executable).machine, 0xaa64)

    def test_windows_unicode_files_and_app_entry(self):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        for name in ("files", "entry", "entry_paths"):
            is_entry = name != "files"
            executable = self.root / ("win32_" + name + ".exe")
            arguments = [self.compiler, "-std=gnu17", "-Wall", "-Wextra", "-Werror",
                         "-D_WIN32_WINNT=0x0A00", "-I", str(runtime),
                         str(runtime / ("test/win32_" + ("entry" if is_entry else "files") + "_test.c")),
                         str(runtime / "win32_files.c"), str(runtime / "win32_host.c"), str(runtime / "plat.c"),
                         "-lpsapi", "-lbcrypt", "-lwinmm", "-o", str(executable)]
            if is_entry:
                arguments += ([str(runtime / "win32_entry.c")] if name == "entry" else ["-DBDSP_ENTRY_PATH_TEST"])
                arguments += [str(runtime / "runtime_paths.c"),
                              "-I", str(ROOT / "scripts/recomp/rt"),
                              "-I", str(ROOT / "scripts/recomp/upstream/runtime"), "-mcx16",
                              "-DBDSP_NVN_NONE", "-municode", "-lshell32", "-lole32", "-luuid"]
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            environment = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith("BDSP_")}
            environment.update(BDSP_DATA_DIR=str(self.root / "user data 日本語"),
                               BDSP_ENTRY_PROBE="environment-日本語")
            (self.root / "exefs").mkdir(exist_ok=True)
            (self.root / "exefs/main.npdm").write_bytes(b"*")
            command = [str(executable)] + (["argument-日本語"] if is_entry else [])
            if name == "entry_paths":
                local, roaming = self.root / "Local 日本語", self.root / "Roaming 日本語"
                local.mkdir()
                roaming.mkdir()
                environment.update(TEST_LOCAL_ROOT=str(local), TEST_ROAMING_ROOT=str(roaming))
                for mode in ("default", "data_override", "save_override", "roaming_failure"):
                    env = dict(environment)
                    env.pop("BDSP_DATA_DIR")
                    env["TEST_EXPECT_DATA"] = str(local / "StrahlenderXnu")
                    env["TEST_EXPECT_SAVE"] = str(roaming / "StrahlenderXnu/save")
                    if mode == "data_override":
                        env["BDSP_DATA_DIR"] = environment["BDSP_DATA_DIR"]
                        env["TEST_EXPECT_DATA"] = env["BDSP_DATA_DIR"]
                        env["TEST_EXPECT_SAVE"] = str(Path(env["BDSP_DATA_DIR"]) / "save")
                    elif mode == "save_override":
                        save = self.root / "explicit save 日本語"
                        save.mkdir()
                        env.update(BDSP_SAVE=str(save), TEST_EXPECT_SAVE=str(save))
                    elif mode == "roaming_failure":
                        env["TEST_ROAMING_FAIL"] = "1"
                    result = subprocess.run(command, cwd=self.root, env=env,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 1 if mode == "roaming_failure" else 0,
                                     result.stderr)
                    if mode == "roaming_failure":
                        self.assertIn("FATAL: Windows roaming save folder lookup failed", result.stderr)
                continue
            result = subprocess.run(command, cwd=self.root, env=environment,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            if name == "entry":
                # The package remains read-only in practice: data is outside its tree.
                other = self.root / "unrelated cwd"
                other.mkdir()
                result = subprocess.run(command, cwd=other, env=environment,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_kernel_windows_suspend_context_and_resume(self):
        source = synthetic_nso(self.root / "gc-roots.nso")
        raw = bytearray(source.read_bytes())
        # LDR q0..q31,[sp,#16*n]; STLR ready; EOR root; ADD progress;
        # LDAR stop; CBZ back to EOR; RET. No private guest image is used.
        words = [0x3dc003e0 | (r << 10) | r for r in range(32)]
        words += [0xc89fff5b, 0xca170273, 0x91000694, 0xc8dfff16,
                  0xb4ffffb6, 0xd65f03c0]
        struct.pack_into("<" + "I" * len(words), raw, 0x120, *words)
        source.write_bytes(raw)
        guest = self.root / "gc-guest.c"
        guest.write_text('#include "cpu.h"\n#include "simd.h"\n' + self.run_native(
            "emit-function", source, "--base", hex(0x7000000000),
            "--entry", hex(0x7000000020), "--end", hex(0x7000000020 + 4 * len(words)),
            "--label", hex(0x7000000020 + 33 * 4), "--simd", "c").stdout)
        for optimization in ("-O1", "-O2", "-O3"):
            with self.subTest(optimization=optimization):
                result = self.run_kernel_probe(guest, optimization)
                self.assertIn("128 suspends, 128 resumes", result.stdout)
                self.assertIn("all guest GPR/SIMD roots and guest stacks", result.stdout)

    def test_optimized_sole_root_is_missing_from_guest_context(self):
        source = synthetic_nso(self.root / "sole-root.nso")
        raw = bytearray(source.read_bytes())
        # Load a hidden pointer, erase its source, reveal it in x19, then keep
        # it live in a finite dependency loop before storing it for validation.
        # This characterizes the unfixed export gap, not an actual collector.
        words = [0xf9400333, 0xf900033f, 0xca170273, 0x8b130294,
                 0xd341fe94, 0xd10006b5, 0xb5ffff95, 0xf9000333, 0xd65f03c0]
        struct.pack_into("<9I", raw, 0x120, *words)
        source.write_bytes(raw)
        guest = self.root / "sole-root.c"
        guest.write_text('#include "cpu.h"\n' + self.run_native(
            "emit-function", source, "--base", hex(0x7000000000),
            "--entry", hex(0x7000000020), "--end", hex(0x7000000020 + 4 * len(words)),
            "--label", hex(0x7000000028), "--simd", "c").stdout)
        for optimization in ("-O1", "-O2"):
            with self.subTest(optimization=optimization):
                result = self.run_kernel_probe(guest, optimization, extra=("-DSOLE_ROOT_PROBE",))
                self.assertIn("24 live host-context roots absent from exported guest contexts", result.stdout)

    def run_kernel_probe(self, guest, optimization, extra=()):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        executable = self.root / (guest.stem + optimization + ".exe")
        result = subprocess.run([
            self.compiler, "-std=gnu17", optimization, "-Wall", "-Wextra", "-Werror",
            "-Wno-unused-parameter", "-Wno-unused-label", "-Wno-sign-compare",
            "-mcx16", "-D_WIN32_WINNT=0x0A00", *extra,
            "-I", str(ROOT / "scripts/recomp/rt"),
            "-I", str(ROOT / "scripts/recomp/upstream/runtime"), "-I", str(runtime),
            str(runtime / "test/kernel_win_test.c"), str(guest), str(runtime / "kernel.c"),
            str(runtime / "win32_host.c"), str(runtime / "win32_files.c"), str(runtime / "plat.c"),
            "-Wl,-Bstatic,-lwinpthread,-Bdynamic", "-lbcrypt", "-lwinmm", "-lpsapi", "-o", str(executable)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    @unittest.skipUnless(all(os.environ.get("BDSP_WINDOWS_" + name + "_ROOT") for name in ("VULKAN", "FFMPEG", "SDL", "QT")),
                         "Explicit SDL, Vulkan, FFmpeg and Qt bundles required")
    def test_full_graphical_runtime_link_boot_and_host_crash(self):
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        selected = windows.profile("x86_64", "x86_64")
        generated = self.root / "synthetic tables"
        (generated / "main").mkdir(parents=True)
        shutil.copyfile(runtime / "test/runtime_win_test.c", generated / "main/tables.c")
        commands = build.Commands()
        bundles = {name: Path(os.environ["BDSP_WINDOWS_" + name.upper() + "_ROOT"]).resolve()
                   for name in ("sdl", "vulkan", "ffmpeg", "qt")}
        try:
            objects = build.compile_sources(
                generated, self.root / "guest objects", self.compiler, selected, commands,
                jobs=2, extra=("-I", str(runtime), "-DBDSP_HAS_SUBSDK1=0"))
            host = build.compile_runtime(self.root / "host objects", self.compiler, selected,
                                         commands, jobs=2, **bundles)
            executable = self.root / "relocated package 日本語/BDSP.exe"
            build.link_executable(objects[0].parent / "compile.json", host,
                                  build.graphical_libraries(self.compiler, selected, **bundles), executable,
                                  self.compiler, selected, commands)
        finally:
            commands.close()
        providers = build.runtime_dll_candidates(self.compiler, selected, bundles.values())
        for path in windows.dll_closure(executable, providers, "x86_64"):
            if path != executable:
                shutil.copyfile(path, executable.parent / path.name)
        images = executable.parent / "img"
        images.mkdir()
        (images / "hle.txt").write_bytes(b"")
        for name in ("main", "sdk", "subsdk0"):
            base = build.BASES[name]
            (images / (name + ".mod")).write_text(
                name + " " + " ".join(f"{value:x}" for value in
                                     (base, 0, 0x1000, 0x1000, 0x2000, 0x2000,
                                      0x3000, 0x3000, 0, 0, 0)) + "\n")
            (images / (name + ".img")).write_bytes(b"\0" * 0x3000)
            (images / (name + ".syms.json")).write_text(json.dumps(
                {"_ZN2nn4init5StartEmmPFvvES2_S2_": base} if name == "main" else {}))
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() != "PATH" and not key.upper().startswith("BDSP_")}
        environment.update(BDSP_DATA_DIR=str(self.root / "runtime data 日本語"),
                           BDSP_MOD="none", BDSP_TIMEOUT="10")
        for crash in (False, True):
            if crash:
                environment["BDSP_TEST_HOST_EXCEPTION"] = "1"
            result = subprocess.run([str(executable), "--no-window"], cwd=self.root,
                                    env=environment, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0xe0424242 if crash else 23,
                             result.stderr.decode("utf-8", errors="replace"))
            self.assertIn(b"[boot] main thread:", result.stderr)
            if crash:
                self.assertIn(b"unhandled Windows exception 0xe0424242", result.stderr)
                log = self.root / "runtime data 日本語/logs/crash.log"
                self.assertIn(b"unhandled Windows exception 0xe0424242", log.read_bytes())

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_VULKAN_ROOT") and os.environ.get("BDSP_WINDOWS_FFMPEG_ROOT"),
                         "Explicit Vulkan and FFmpeg development bundles required")
    def test_real_shaderc_and_ffmpeg_abi_codecs_license_and_relocation(self):
        selected = windows.profile("x86_64", "x86_64")
        vulkan, ffmpeg = (build.verified_bundle(os.environ["BDSP_WINDOWS_" + name + "_ROOT"], selected)
                          for name in ("VULKAN", "FFMPEG"))
        executable = self.root / "dependency_probe.exe"
        result = subprocess.run([
            self.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
            "-I", str(vulkan / "include"), "-I", str(ffmpeg / "include"),
            str(ROOT / "scripts/recomp/rt-bdsp/test/dependency_probe.c"),
            str(vulkan / "lib/libshaderc_shared.dll.a"),
            *(str(ffmpeg / f"lib/lib{name}.dll.a") for name in ("avformat", "avcodec", "avutil")),
            "-o", str(executable)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        providers = [path for bundle in (vulkan, ffmpeg) for path in (bundle / "bin").glob("*.dll")]
        for path in windows.dll_closure(executable, providers, "x86_64"):
            if path != executable:
                shutil.copyfile(path, executable.parent / path.name)
        environment = {key: value for key, value in os.environ.items() if key.upper() != "PATH"}
        result = subprocess.run([str(executable)], cwd=self.root, env=environment,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("movie=vp8-roundtrip;decoders=vp8,vp9,h264", result.stdout)
        self.assertIn("shaderc=valid-spirv-and-invalid-diagnostics", result.stdout)
        if os.environ.get("BDSP_WINDOWS_DEPENDENCY_REPORT"):
            build.atomic_json(os.environ["BDSP_WINDOWS_DEPENDENCY_REPORT"], {
                "schema": 1, "profile": selected, "stdout": result.stdout, "stderr": result.stderr,
                "probe_sha256": windows.sha256(ROOT / "scripts/recomp/rt-bdsp/test/dependency_probe.c"),
                "compiler": build.compiler_identity(self.compiler, selected),
                "bundles": {name: windows.sha256(path / "build.json")
                            for name, path in (("vulkan", vulkan), ("ffmpeg", ffmpeg))},
                "runtime": {path.name: windows.sha256(path) for path in
                            windows.dll_closure(executable, providers, "x86_64")},
                "qualified": False,
            })

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_HACTOOL_ROOT"), "Explicit native hactool bundle required")
    def test_native_hactool_unicode_pfs0_extraction_without_private_keys(self):
        selected = windows.profile("x86_64", "x86_64")
        bundle = build.verified_bundle(os.environ["BDSP_WINDOWS_HACTOOL_ROOT"], selected)
        executable = self.root / "hactool.exe"
        shutil.copyfile(bundle / "hactool.exe", executable)
        self.assertEqual(windows.dll_closure(executable, (), "x86_64"), [executable])
        filename = "sample-\u65e5\u672c\u8a9e.bin"
        content = b"synthetic extraction fixture\0\xff\r\n"
        name = filename.encode("utf-8") + b"\0"
        archive = self.root / "input-\u65e5\u672c\u8a9e.nsp"
        archive.write_bytes(b"PFS0" + struct.pack("<III", 1, len(name), 0) +
                            struct.pack("<QQII", 0, len(content), 0, 0) + name + content)
        destination = self.root / "output-\u65e5\u672c\u8a9e"
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() not in ("PATH", "HOME", "USERPROFILE", "XDG_CONFIG_HOME")}
        environment.update(HOME=str(self.root), USERPROFILE=str(self.root), XDG_CONFIG_HOME=str(self.root))
        result = subprocess.run([str(executable), "-t", "pfs0", "-x", "--disablekeywarns",
                                 "--suppresskeys", "--outdir=" + str(destination), str(archive)],
                                cwd=self.root, env=environment, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, "Synthetic hactool extraction failed")
        self.assertEqual((destination / filename).read_bytes(), content)
        for unsafe in ("../escape", "NUL", "a" * 1000):
            name = unsafe.encode("utf-8") + b"\0"
            archive.write_bytes(b"PFS0" + struct.pack("<III", 1, len(name), 0) +
                                struct.pack("<QQII", 0, len(content), 0, 0) + name + content)
            result = subprocess.run([str(executable), "-t", "pfs0", "-x", "--disablekeywarns",
                                     "--suppresskeys", "--outdir=" + str(destination), str(archive)],
                                    cwd=self.root, env=environment, capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, "Unsafe native extraction path was accepted")
        self.assertFalse((self.root / "escape").exists())
        archive.write_bytes(b"invalid archive")
        result = subprocess.run([str(executable), "-t", "pfs0", "-x", str(archive)],
                                cwd=self.root, env=environment, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_PRIVATE_CATALOG"),
                         "Explicit verified private offline catalog required")
    def test_native_pipeline_synthetic_extraction_to_relocated_installation(self):
        args = SimpleNamespace(root=ROOT, work=self.root / "work",
                               windows_catalog=Path(os.environ["BDSP_WINDOWS_PRIVATE_CATALOG"]),
                               target="windows", base=self.root / "synthetic input",
                               prod_keys=self.root / "synthetic.keys", update=None,
                               install_root=self.root / "installed", clean_build=False)
        def extracted(*arguments, **options):
            exefs = args.work / "exefs"
            exefs.mkdir(parents=True, exist_ok=True)
            for name in ("rtld", "main", "sdk", "subsdk0"):
                synthetic_eh_nso(exefs / name)
            (exefs / "main.npdm").write_bytes(b"synthetic npdm")
            (args.work / "romfs").mkdir(exist_ok=True)
            (args.work / "romfs/synthetic.bin").write_bytes(b"synthetic game data")
            from PIL import Image
            icons = args.work / "recomp/icons/source"
            icons.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            Image.new("RGB", (256, 256), "red").save(buffer, "PNG")
            digest = hashlib.sha256(buffer.getvalue()).hexdigest()
            (icons / (digest + ".png")).write_bytes(buffer.getvalue())
            (icons / "icons.json").write_text(json.dumps({
                "schema": 1, "title_id": "0", "default": "en-US", "titles": {}, "display_version": "",
                "variants": [{"id": "en-US", "label": "English (US)", "image": digest + ".png", "sha256": digest,
                              "icon": "BDSP_" + digest[:24]}]}))
        events = []
        with patch.object(windows_pipeline, "extract_game", side_effect=extracted), \
                patch.object(windows_pipeline.game_icons, "ROOT", self.root):
            executable = windows_pipeline.build_game(args, lambda event, **fields:
                                                     events.append({"event": event, **fields}))
            windows_pipeline.build_game(args, lambda event, **fields:
                                        events.append({"event": event, **fields}))
        record = windows_pipeline.package_record(executable.parent)
        self.assertNotIn("controller-mode.txt", record["files"])
        self.assertIn("notices/mingw-runtime/COPYING.winpthreads.txt", record["files"])
        self.assertIn("notices/mingw-runtime/COPYING.MinGW-w64-runtime.txt", record["files"])
        catalog_path = Path(args.windows_catalog)
        catalog = json.loads(catalog_path.read_text())
        for component in ("sdl", "vulkan", "ffmpeg"):
            bundle = catalog_path.parent / catalog["bundles"][component]
            dependency = json.loads((bundle / "build.json").read_text())
            for name, digest in dependency["files"].items():
                if name.startswith("notices/"):
                    packaged_name = "notices/" + component + "/" + name[len("notices/"):]
                    self.assertEqual(record["files"][packaged_name], digest)
        self.assertEqual(windows.PE(executable).machine, 0x8664)
        self.assertTrue(any(event["event"] == "progress" and event["id"] == "eh_gen" for event in events))
        self.assertTrue(any(name.endswith(".dll") for name in record["files"]))
        self.assertEqual((executable.parent / "romfs/synthetic.bin").read_bytes(), b"synthetic game data")
        self.assertTrue((executable.parent / "img/main.img").is_file())
        self.assertFalse(any("unicorn" in name.lower() or "python" in name.lower()
                             or name.lower().endswith((".a", ".o")) for name in record["files"]))
        moved = self.root / "relocated installation \u65e5\u672c\u8a9e"
        executable.parent.rename(moved)
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() != "PATH" and not key.upper().startswith("BDSP_")}
        environment.update(BDSP_DATA_DIR=str(self.root / "synthetic user data"), BDSP_TIMEOUT="10")
        result = subprocess.run([str(moved / "BDSP.exe"), "--no-window"], cwd=self.root,
                                env=environment, capture_output=True, timeout=20)
        # This fixture deliberately has no game entrypoint; it must reach that precise diagnostic.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"nn::init::Start not found", result.stderr)

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_PRIVATE_CATALOG"),
                         "Explicit verified private offline catalog required")
    def test_isolated_gui_driver_reports_native_extraction_failure_without_private_output(self):
        source, keys = self.root / "synthetic.nsp", self.root / "selected.keys"
        source.write_bytes(container([("synthetic.nca", b"invalid synthetic NCA")]))
        keys.write_text("SYNTHETIC KEY MATERIAL MUST NOT APPEAR IN LOGS\n")
        result = subprocess.run(
            [os.sys.executable, "-I", "-B", ROOT / "scripts/install/driver.py",
             "build", "--root", ROOT, "--work", self.root / "work", "--target", "windows",
             "--base", source, "--prod-keys", keys, "--windows-catalog",
             os.environ["BDSP_WINDOWS_PRIVATE_CATALOG"]],
            cwd=self.root, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 4)
        events = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
        self.assertEqual(events[-1], {"event": "result", "ok": False, "code": 4})
        self.assertEqual(sum(event["event"] == "result" for event in events), 1)
        self.assertIn({"event": "step", "id": "extract", "status": "failed"}, events)
        self.assertTrue(any("NCA" in event.get("message", "") or "unpacked" in event.get("message", "") for event in events))
        self.assertNotIn(b"SYNTHETIC KEY MATERIAL", result.stdout + result.stderr)
        self.assertFalse(any(event["event"] == "artifact" for event in events))

    def test_runtime_memory_faults_clock_and_unicode_image_loading(self):
        executable = self.root / "win32_host.exe"
        runtime = ROOT / "scripts/recomp/rt-bdsp"
        result = subprocess.run([
            self.compiler, "-std=gnu17", "-Wall", "-Wextra", "-Werror", "-mcx16",
            "-D_WIN32_WINNT=0x0A00", "-DBDSP_HAS_SUBSDK1=0", "-municode",
            "-I", str(ROOT / "scripts/recomp/rt"),
            "-I", str(ROOT / "scripts/recomp/upstream/runtime"), "-I", str(runtime),
            str(runtime / "test/win32_host_test.c"), str(runtime / "win32_host.c"),
            str(runtime / "win32_files.c"), str(runtime / "plat.c"),
            str(runtime / "loader.c"), "-lpsapi", "-lbcrypt", "-lwinmm", "-o", str(executable)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for mode in ("--memory", "--gpu-memory", "--guard-fault", "--readonly-fault", "--noaccess-fault", "--execute-fault"):
            result = subprocess.run([str(executable), mode], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0 if mode in ("--memory", "--gpu-memory") else 0xc0000005,
                             result.stderr.decode("utf-8", errors="replace"))
        images = self.root / "images 日本語"
        images.mkdir()
        (images / "hle.txt").write_bytes(b"synthetic_hle\r\n")
        for i, name in enumerate(("main", "sdk", "subsdk0")):
            base = build.BASES[name]
            (images / (name + ".mod")).write_text(
                name + " " + " ".join(f"{value:x}" for value in
                                     (base, 0, 0x1000, 0x1000, 0x2000, 0x2000,
                                      0x3000, 0x3000, 0, 0, 0)) + "\n")
            (images / (name + ".img")).write_bytes(bytes([0x41 + i]) * 0x3000)
            (images / (name + ".syms.json")).write_text(
                json.dumps({"synthetic_symbol": base} if name == "main" else {}))
        result = subprocess.run([str(executable), str(images)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

    @unittest.skipUnless(os.environ.get("BDSP_WINDOWS_ARM64_CC"), "Explicit ARM64 cross compiler required")
    def test_arm64_generated_c_compile_is_separate_from_native_execution(self):
        source = synthetic_nso(self.root / "synthetic.nso")
        folder = self.root / "gen/main"
        self.run_native("gen", "main", source, "0x7000000000", folder, "--simd", "c")
        commands = build.Commands()
        try:
            result = build.compile_sources(folder.parent, self.root / "objects",
                                           os.environ["BDSP_WINDOWS_ARM64_CC"],
                                           windows.profile("aarch64", "x86_64"), commands, jobs=2)
            self.assertTrue(result)
            self.assertTrue(all(int.from_bytes(path.read_bytes()[:2], "little") == 0xaa64 for path in result))
        finally:
            commands.close()


if __name__ == "__main__":
    unittest.main()
