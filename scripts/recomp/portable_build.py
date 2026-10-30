#!/usr/bin/env python3
"""Direct native C pipeline for Windows preparation; no shell or build framework.

This developer entry point can link diagnostic and Vulkan/movie runtimes, not
extract games or claim a playable Windows release. Dependency recipes are maintainer-only; the
graphical installer gates game builds on qualification and end-to-end acceptance.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASES = {"rtld": 0x7008000000, "main": 0x7000000000, "sdk": 0x7006000000,
         "subsdk0": 0x7007000000, "subsdk1": 0x7005708000}


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Missing build helper: " + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows = load_helper("bdsp_windows", HERE / "windows_support.py")
parallel = load_helper("bdsp_jobs", HERE / "parallel_jobs.py")
filesystem = load_helper("bdsp_filesystem", ROOT / "scripts/install/filesystem.py")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


class Commands:
    """Own only this run's processes; failure/interrupt cancels the shared queue."""
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.children = set()
        self.job = (load_helper("bdsp_windows_process", HERE / "windows_process.py").Job()
                    if sys.platform == "win32" else None)

    def run(self, arguments):
        return self._run(arguments)

    def capture(self, arguments, *, env=None, cwd=None, limit=1024 * 1024, on_line=None):
        """Bounded private capture of a tool's output."""
        read_fd, write_fd = os.pipe()
        chunks, overflow, callbacks = [], threading.Event(), []
        def drain(stream):
            total = 0
            pending = b""
            with stream:
                for chunk in iter(lambda: stream.read1(65536), b""):
                    total += len(chunk)
                    if total <= limit:
                        chunks.append(chunk)
                        if on_line and not callbacks:
                            pending += chunk
                            lines = pending.split(b"\n")
                            pending = lines.pop()
                            for line in lines:
                                try:
                                    on_line(line.decode("utf-8", errors="replace").rstrip("\r"))
                                except Exception as error:
                                    callbacks.append(error)
                                    self.cancel()
                                    break
                    else:
                        if not overflow.is_set():
                            overflow.set()
                            self.cancel()
                if pending and on_line and not callbacks and not overflow.is_set():
                    try:
                        on_line(pending.decode("utf-8", errors="replace"))
                    except Exception as error:
                        callbacks.append(error)
                        self.cancel()
        reader = threading.Thread(target=drain, args=(os.fdopen(read_fd, "rb"),))
        reader.start()
        failure = None
        try:
            with os.fdopen(write_fd, "wb") as stream:
                self._run(arguments, stdout=stream, stderr=stream, env=env, cwd=cwd)
        except subprocess.CalledProcessError as error:
            failure = error
        finally:
            reader.join()
        if overflow.is_set():
            raise ValueError("Tool output exceeded the private capture limit")
        if callbacks:
            raise callbacks[0]
        if failure is not None:
            failure.output = b"".join(chunks)
            raise failure
        return b"".join(chunks)

    def _run(self, arguments, *, stdout=None, stderr=None, env=None, cwd=None):
        with self.lock:
            if self.cancelled.is_set():
                raise InterruptedError("Build cancelled")
            child = (self.job.spawn(arguments, stdout=stdout, stderr=stderr, env=env, cwd=cwd) if self.job else
                     subprocess.Popen([str(arg) for arg in arguments], stdout=stdout, stderr=stderr,
                                      env=env, cwd=cwd))
            self.children.add(child)
        try:
            code = child.wait()
            if code:
                raise subprocess.CalledProcessError(code, arguments)
        except BaseException:
            self.cancel()
            raise
        finally:
            with self.lock:
                self.children.discard(child)
                if self.job:
                    child.close()

    def cancel(self):
        with self.lock:
            self.cancelled.set()
            children = list(self.children)
            if self.job:
                self.job.cancel()
                return
            else:
                for child in children:
                    if child.poll() is None:
                        child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def close(self):
        if self.job:
            self.job.close()


compiler_identity = windows.compiler_identity


def response_file(path, arguments):
    arguments = [str(argument) for argument in arguments]
    if any(any(char in argument for char in "\r\n\0") for argument in arguments):
        raise ValueError("Response-file argument contains a newline or NUL")
    Path(path).write_text(subprocess.list2cmdline(arguments) + "\n", encoding="utf-8")


def modules(exefs, include_rtld=True):
    names = ["rtld", "main", "sdk", "subsdk0"] if include_rtld else ["main", "sdk", "subsdk0"]
    if (Path(exefs) / "subsdk1").is_file():
        names.append("subsdk1")
    for name in names:
        if not (Path(exefs) / name).is_file():
            raise ValueError("Extracted module is missing: " + name)
    return names


def verify_build_output(output, marker):
    if output.exists():
        filesystem.reject_link(output)
        filesystem.reject_link(output / marker)
        record = json.loads((output / marker).read_text(encoding="utf-8"))
        if record.get("schema") != 1:
            raise ValueError("Unrecognized native build output; use a fresh target cache")
        filesystem.verify_inventory(output, record.get("outputs", record["files"]), ignored=(marker,))


def generate(generator, exefs, output, commands):
    names = modules(exefs)
    output = Path(output)
    verify_build_output(output, ".generation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="generate-", dir=output.parent) as temporary:
        stage = Path(temporary)
        inventory = {}
        for name in names:
            destination = stage / name
            destination.mkdir()
            command = [generator, "gen", name, Path(exefs) / name, hex(BASES[name]),
                       destination, "--simd", "c"]
            entries = Path(exefs) / (name + ".entries")
            if entries.is_file():
                command += ["--entry-offsets", entries]
            commands.run(command)
            files = sorted(destination.glob("*.c"))
            if not files:
                raise ValueError("Generator produced no C sources for " + name)
            inventory.update({path.relative_to(stage).as_posix(): windows.sha256(path) for path in files})
        outputs = {path.relative_to(stage).as_posix(): windows.sha256(path)
                   for path in stage.rglob("*") if path.is_file()}
        atomic_json(stage / ".generation.json", {
            "schema": 1, "simd": "c", "modules": names, "generator": windows.sha256(generator),
            "files": inventory, "outputs": outputs})
        filesystem.publish_tree(stage, output)


def generated_inventory(output):
    output = Path(output)
    record = json.loads((output / ".generation.json").read_text(encoding="utf-8"))
    if record.get("schema") != 1 or record.get("simd") != "c" or not record.get("files"):
        raise ValueError("Missing completed portable C generation inventory")
    sources = []
    for name, digest in sorted(record["files"].items()):
        if not re.fullmatch(r"(rtld|main|sdk|subsdk0|subsdk1)/[^/\\]+\.c", name):
            raise ValueError("Invalid generated source inventory")
        path = output / name
        if windows.sha256(path) != digest:
            raise ValueError("Generated source changed; regenerate before compiling")
        sources.append(path)
    return sources


def images(generator, exefs, output, hle_list, commands):
    names = modules(exefs, include_rtld=False)
    output = Path(output)
    if not Path(hle_list).is_file():
        raise ValueError("NVN HLE list is required")
    verify_build_output(output, "images.json")
    # Two passes share one fresh directory; stale exports or HLE slots cannot leak in.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="images-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for name in names:
            commands.run([generator, "image", Path(exefs) / name, name, "--base",
                          hex(BASES[name]), "--out", stage])
        (stage / "hle.txt").unlink(missing_ok=True)
        links = [item for name in names for item in ("--link", stage / (name + ".syms.json"))]
        for name in names:
            commands.run([generator, "image", Path(exefs) / name, name, "--base",
                          hex(BASES[name]), "--out", stage, *links,
                          "--interpose-from", stage / "main.syms.json",
                          "--hle-list", hle_list])
        files = sorted(path for path in stage.iterdir() if path.is_file())
        if not files or not (stage / "hle.txt").is_file():
            raise ValueError("Image generator did not produce the HLE table")
        inventory = {path.name: windows.sha256(path) for path in files}
        atomic_json(stage / "images.json", {"schema": 1, "modules": names, "files": inventory})
        filesystem.publish_tree(stage, output)


def optimization(source, threshold, hot):
    text = Path(source).read_text(encoding="utf-8")
    functions = re.findall(r"^void (f_[A-Za-z0-9_]+)\([^;\n]*\) \{$", text, re.M)
    if hot.intersection(functions):
        return "-O2"
    return "-O0" if len(functions) == 1 and Path(source).stat().st_size > threshold else "-O1"


def prepare_vulkan(root, destination):
    root, destination = Path(root), Path(destination)
    base = root / "scripts/recomp/runtime/nvn"
    sources = {}
    for source_tree in (base / "src", base / "vulkan/src"):
        if not source_tree.is_dir():
            raise ValueError("Missing Vulkan source tree")
        for source in sorted(source_tree.rglob("*")):
            if source.is_file() and source.name != ".DS_Store":
                sources[source.relative_to(source_tree).as_posix()] = source
    for name in ("translate.c", "shader.h"):
        sources["nvn/maxwell/" + name] = root / "shader_translator" / name
    inventory = {name: windows.sha256(source) for name, source in sources.items()}
    metadata = {"schema": 1, "driver": windows.sha256(__file__), "files": inventory}
    if destination.exists():
        marker = destination / ".portable-overlay.json"
        if not marker.is_file():
            raise ValueError("Refusing to replace an unmanaged Vulkan overlay")
        previous = json.loads(marker.read_text(encoding="utf-8"))
        actual = {path.relative_to(destination).as_posix(): windows.sha256(path)
                  for path in destination.rglob("*") if path.is_file() and path != marker}
        if previous.get("files") != actual:
            raise ValueError("Vulkan overlay was edited; preserve those changes before rebuilding")
        if previous == metadata:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vulkan-overlay-", dir=destination.parent) as temporary:
        stage, backup = Path(temporary) / "sources", Path(temporary) / "previous"
        stage.mkdir()
        for name, source in sources.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        atomic_json(stage / ".portable-overlay.json", metadata)
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
    return destination


def compile_sources(generated, objects, compiler, selected, commands, jobs=None,
                    extra=(), threshold=300000, root=ROOT, progress=None, source_paths=None,
                    dependency_headers=(), source_flags=None):
    identity = compiler_identity(compiler, selected)
    root, generated = Path(root).resolve(), Path(generated).resolve()
    objects = Path(objects) / selected["cache_key"]
    objects.mkdir(parents=True, exist_ok=True)
    marker = objects / "compile.json"
    marker.unlink(missing_ok=True)
    headers = [root / "scripts/recomp/rt/cpu.h", *sorted(
        (root / "scripts/recomp/upstream/runtime").glob("*.h")), *dependency_headers]
    hot_path = root / "scripts/recomp/hot_o2.txt"
    hot = {line.strip() for line in hot_path.read_text(encoding="utf-8").splitlines()
           if line.strip() and not line.lstrip().startswith("#")}
    sources = sorted(source_paths if source_paths is not None else generated.glob("*/*.c"),
                     key=lambda path: (-path.stat().st_size, str(path)))
    if not sources:
        raise ValueError("No generated C sources")
    names = [source.parent.name + "_" + source.stem + ".o" for source in sources]
    if len(set(names)) != len(names):
        raise ValueError("Compile sources have colliding object names")
    cxx_identity = None
    if any(source.suffix == ".cpp" for source in sources):
        cxx_identity = compiler_identity(Path(identity["path"]).with_name(
            selected["target"] + "-w64-mingw32-clang++.exe"), selected)
    source_flags = source_flags or {}
    flags = ["-fno-strict-aliasing", "-w", *selected["cpu_flags"],
             "-D_WIN32_WINNT=0x0A00", "-DWINVER=0x0A00",
             *extra,
             "-I", str(root / "scripts/recomp/rt"),
             "-I", str(root / "scripts/recomp/upstream/runtime")]
    signature = fingerprint({"schema": 1, "driver": windows.sha256(__file__),
                             "support": windows.sha256(HERE / "windows_support.py"),
                             "compiler": identity, "cxx_compiler": cxx_identity,
                             "profile": selected, "flags": flags,
                             "source_flags": {str(path): list(value) for path, value in source_flags.items()},
                             "headers": {str(h.resolve()): windows.sha256(h) for h in headers},
                             "hot": windows.sha256(hot_path), "threshold": threshold,
                             "generated": str(generated)})
    jobs = jobs if jobs is not None else parallel.choose_jobs(parallel.cpu_count(), parallel.memory_bytes())
    if jobs < 1:
        raise ValueError("Compile jobs must be positive")
    jobs = min(jobs, parallel.choose_jobs(parallel.cpu_count(), parallel.memory_bytes()))

    def compile_one(source):
        name = source.parent.name + "_" + source.stem + ".o"
        output = objects / name
        record = output.with_suffix(".o.json")
        opt = optimization(source, threshold, hot)
        wanted = {"signature": signature, "source": windows.sha256(source), "opt": opt}
        if output.is_file() and record.is_file():
            try:
                cached = json.loads(record.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                cached = None
            if cached == {**wanted, "object": windows.sha256(output)}:
                return output
        with tempfile.TemporaryDirectory(prefix="compile-", dir=objects) as temporary:
            candidate = Path(temporary) / name
            response = Path(temporary) / "compile.rsp"
            language = "-std=c++17" if source.suffix == ".cpp" else "-std=gnu17"
            driver = cxx_identity if source.suffix == ".cpp" else identity
            response_file(response, [language, *flags, *source_flags.get(source, ()),
                                     opt, "-c", source, "-o", candidate])
            commands.run([driver["path"], "--rsp-quoting=windows", "@" + str(response)])
            wanted["object"] = windows.sha256(candidate)
            os.replace(candidate, output)
            atomic_json(record, wanted)
        return output

    results = []
    pool = ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = [pool.submit(compile_one, source) for source in sources]
        for future in as_completed(futures):
            results.append(future.result())
            if progress:
                progress(len(results), len(sources))
    except BaseException:
        commands.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    # Linking consumes this exact inventory, never an object-directory wildcard.
    atomic_json(marker, {"schema": 1, "signature": signature, "profile": selected,
                         "objects": {path.name: windows.sha256(path) for path in sorted(results)}})
    return sorted(results)


def compile_runtime(objects, compiler, selected, commands, *, has_subsdk1=False,
                    jobs=None, root=ROOT, sdl=None, vulkan=None, ffmpeg=None, qt=None):
    """Compile the Windows runtime: Vulkan renderer and the shared Qt game host."""
    qt_bundle = qt_development(qt, compiler, selected)
    root = Path(root).resolve()
    runtime = root / "scripts/recomp/runtime"
    # Snapshot publication uses the iOS durability contract, not a Windows shim.
    sources = [path for path in sorted(runtime.glob("*.c")) if path.name != "save_snapshot.c"]
    extra = ["-I", str(runtime), f"-DBDSP_HAS_SUBSDK1={int(has_subsdk1)}"]
    headers = sorted(runtime.rglob("*.h"))
    per_source = {}
    bundles = [verified_bundle(path, selected) for path in (sdl, vulkan, ffmpeg)]
    overlay = prepare_vulkan(root, Path(objects) / "nvn-src-vk")
    nvn = runtime / "nvn"
    sources += [overlay / f"nvn/{name}.c" for name in ("objects", "cmdbuf", "formats", "tegra", "astc")]
    sources += [overlay / "nvn/maxwell/translate.c"]
    sources += [overlay / f"nvn/vulkan/{name}.c" for name in ("device", "exec", "shaders", "textures")]
    sources += [overlay / "nvn/vulkan/vma.cpp", nvn / "nvn_glue.c",
                nvn / "vulkan/vk_glue.c", nvn / "vulkan/swkbd_overlay_vk.c", nvn / "movie_glue.c"]
    per_source[nvn / "nvn_glue.c"] = ("-Dg_debug_frame=bdsp_glue_debug_frame",)
    for directory in (overlay, overlay / "nvn", *(path / "include" for path in bundles)):
        extra += ["-I", str(directory)]
        headers += sorted(directory.rglob("*.h"))
    host = runtime / "app/linux"
    sources.append(host / "qt_ui.cpp")
    extra += ["-DBDSP_QT", "-DQT_NO_DEBUG"]
    for directory in (host, qt_bundle / "include",
                      *(qt_bundle / "include" / name for name in ("QtCore", "QtGui", "QtWidgets"))):
        extra += ["-I", str(directory)]
        headers += sorted(directory.rglob("*.h"))
    return compile_sources(
        runtime, objects, compiler, selected, commands, jobs,
        extra=extra, root=root, source_paths=sources, dependency_headers=headers, source_flags=per_source)


def verified_bundle(path, selected):
    """Private development bundles remain distinct from public release qualification."""
    if path is None:
        raise ValueError("Explicit SDL3, Vulkan and FFmpeg development bundle paths are required")
    path = Path(path)
    filesystem.reject_link(path)
    path = path.resolve()
    record = json.loads((path / "build.json").read_text(encoding="utf-8"))
    if record.get("schema") != 1 or record.get("profile") != selected or not record.get("files"):
        raise ValueError("Development bundle profile/inventory mismatch: " + str(path))
    filesystem.verify_inventory(path, record["files"], ignored=("build.json",))
    return path


def qt_development(path, compiler, selected):
    """Qt crosses a C++ ABI boundary: a generic MSVC/GCC SDK is not interchangeable."""
    if path is None or not (Path(path) / "build.json").is_file():
        raise ValueError("Qt development bundle missing: supply --qt-prefix with a verified shared Qt6 "
                         "LLVM-MinGW UCRT/libc++ target build; MSVC or GCC Qt packages are not compatible")
    bundle = verified_bundle(path, selected)
    record = json.loads((bundle / "build.json").read_text(encoding="utf-8"))
    qt = record.get("qt", {})
    if (qt.get("linkage") != "shared" or qt.get("cxx_runtime") != "libc++" or
            not isinstance(qt.get("version"), str) or not re.fullmatch(r"6\.\d+\.\d+", qt["version"]) or
            type(qt.get("minimum_windows_build")) is not int or
            not 0 < qt["minimum_windows_build"] <= windows.contract()["minimum_windows_build"]):
        raise ValueError("Qt bundle must declare shared Qt6, libc++ and the supported Windows baseline")
    compiler = Path(compiler_identity(compiler, selected)["path"])
    cxx = compiler.with_name(selected["target"] + "-w64-mingw32-clang++.exe")
    identity = compiler_identity(cxx, selected)
    if qt.get("cxx_compiler_sha256") != identity["sha256"]:
        raise ValueError("Qt C++ toolchain identity differs; do not mix MSVC/GCC/LLVM C++ ABIs")
    required = ("include/QtCore/qglobal.h", "include/QtGui/QVulkanInstance",
                "include/QtWidgets/QApplication", "plugins/platforms/qwindows.dll",
                *(f"lib/libQt6{name}.a" for name in ("Core", "Gui", "Widgets")),
                *(f"bin/Qt6{name}.dll" for name in ("Core", "Gui", "Widgets")))
    for name in required:
        if not (bundle / name).is_file():
            raise ValueError("Qt development/runtime file missing: " + name)
    if not any(name.startswith("notices/") for name in record["files"]):
        raise ValueError("Qt license/notices inventory missing; private use is not release qualification")
    candidates = [*bundle.joinpath("bin").glob("*.dll"),
                  *runtime_dll_candidates(compiler, selected)]
    for name in ("bin/Qt6Widgets.dll", "plugins/platforms/qwindows.dll"):
        windows.dll_closure(bundle / name, candidates, selected["target"])
    return bundle


def graphical_libraries(compiler, selected, sdl, vulkan, ffmpeg, *, qt=None):
    qt_bundle = qt_development(qt, compiler, selected)
    sdl, vulkan, ffmpeg = (verified_bundle(path, selected) for path in (sdl, vulkan, ffmpeg))
    identity = compiler_identity(compiler, selected)
    prefix = Path(identity["path"]).parent.parent / (selected["target"] + "-w64-mingw32")
    libraries = [sdl / "lib/libSDL3.dll.a", vulkan / "lib/libshaderc_shared.dll.a",
                 vulkan / "lib/libvulkan-1.a",
                 *(ffmpeg / f"lib/lib{name}.dll.a" for name in ("avformat", "avcodec", "avutil")),
                 prefix / "lib/libc++.dll.a", *runtime_libraries(compiler, selected),
                 *(qt_bundle / f"lib/libQt6{name}.a" for name in ("Widgets", "Gui", "Core"))]
    for path in libraries:
        if not path.is_file():
            raise ValueError("Missing graphical runtime library: " + str(path))
    return libraries


def runtime_dll_candidates(compiler, selected, bundles=()):
    identity = compiler_identity(compiler, selected)
    target_bin = Path(identity["path"]).parent.parent / (selected["target"] + "-w64-mingw32") / "bin"
    return [*target_bin.glob("*.dll"),
            *(path for bundle in bundles for path in (Path(bundle) / "bin").glob("*.dll"))]


def runtime_libraries(compiler, selected):
    identity = compiler_identity(compiler, selected)
    prefix = Path(identity["path"]).parent.parent
    directory = prefix / (selected["target"] + "-w64-mingw32") / "lib"
    libraries = [directory / ("lib" + name + ".a")
                 for name in ("winpthread", "bcrypt", "psapi", "shell32", "ole32", "uuid", "winmm")]
    for path in libraries:
        if not path.is_file():
            raise ValueError("Missing LLVM-MinGW runtime library: " + str(path))
    return libraries


def cmake_target_definitions(compiler, selected, ninja, stage, package):
    """Explicit UCRT tools shared by offline maintainer dependency recipes."""
    compiler = Path(compiler)
    flags = subprocess.list2cmdline(
        [*selected["cpu_flags"], "-D_WIN32_WINNT=0x0A00",
         "-DWINVER=0x0A00", f"-ffile-prefix-map={Path(stage).as_posix()}=."])
    # Typed cache paths let CMake normalize backslashes in generated compiler files.
    return {
        "CMAKE_SYSTEM_NAME": "Windows", "CMAKE_SYSTEM_PROCESSOR": selected["target"],
        "CMAKE_BUILD_TYPE": "Release", "CMAKE_MAKE_PROGRAM:FILEPATH": str(ninja),
        "CMAKE_C_COMPILER:FILEPATH": str(compiler),
        "CMAKE_CXX_COMPILER:FILEPATH": str(compiler.with_name(
            selected["target"] + "-w64-mingw32-clang++.exe")),
        "CMAKE_RC_COMPILER:FILEPATH": str(compiler.with_name(compiler.name.replace("clang", "windres"))),
        "CMAKE_AR:FILEPATH": str(compiler.with_name("llvm-ar.exe")),
        "CMAKE_RANLIB:FILEPATH": str(compiler.with_name("llvm-ranlib.exe")),
        "CMAKE_C_FLAGS": flags, "CMAKE_CXX_FLAGS": flags,
        "CMAKE_INSTALL_PREFIX:PATH": str(package),
        "CMAKE_DISABLE_FIND_PACKAGE_PkgConfig": "TRUE",
    }


def import_sdl(devel, destination, selected):
    """Bundle the official SDL3 MinGW development package (libsdl-org publishes it with every release).

    `devel` is the unpacked SDL3-devel-*-mingw archive root; its <arch>-w64-mingw32 folder holds include/, lib/ and bin/.
    """
    devel, destination = Path(devel).resolve(), Path(destination).resolve()
    source = devel / (selected["target"] + "-w64-mingw32")
    if destination.exists():
        raise ValueError("Refusing to replace an existing SDL bundle")
    for relative in ("include/SDL3/SDL.h", "lib/libSDL3.dll.a", "bin/SDL3.dll"):
        if not (source / relative).is_file():
            raise ValueError("Missing SDL development file: " + relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sdl-import-", dir=destination.parent) as temporary:
        package = Path(temporary) / "package"
        filesystem.copy_tree(source / "include", package / "include")
        (package / "lib").mkdir(parents=True)
        shutil.copyfile(source / "lib/libSDL3.dll.a", package / "lib/libSDL3.dll.a")
        (package / "bin").mkdir()
        shutil.copyfile(source / "bin/SDL3.dll", package / "bin/SDL3.dll")
        windows.dll_closure(package / "bin/SDL3.dll", (), selected["target"])
        notices = package / "notices/SDL3"
        notices.mkdir(parents=True)
        for name in ("LICENSE.txt", "README.md"):
            if (devel / name).is_file():
                shutil.copyfile(devel / name, notices / name)
        if not (notices / "LICENSE.txt").is_file():
            raise ValueError("The SDL package has no LICENSE.txt")
        atomic_json(package / "build.json", {
            "schema": 1, "profile": selected, "recipe_sha256": windows.sha256(__file__), "origin": "libsdl-org SDL3-devel mingw package",
            "files": {path.relative_to(package).as_posix(): windows.sha256(path)
                      for path in sorted(package.rglob("*")) if path.is_file()},
            "qualified": False,
        })
        package.rename(destination)
    return destination


def compiled_inventory(compile_marker, selected):
    marker = Path(compile_marker)
    record = json.loads(marker.read_text(encoding="utf-8"))
    if record.get("schema") != 1 or record.get("profile") != selected or not record.get("objects"):
        raise ValueError("Compile inventory does not match the Windows target")
    objects = []
    for name, digest in sorted(record["objects"].items()):
        if Path(name).name != name or not name.endswith(".o"):
            raise ValueError("Invalid compile inventory object")
        path = marker.parent / name
        if windows.sha256(path) != digest:
            raise ValueError("Compiled object changed: " + name)
        objects.append(path)
    return objects


def link_executable(compile_marker, runtime_objects, libraries, output, compiler, selected, commands, *, icon=None):
    """Link an explicit inventory after the platform runtime has been compiled."""
    identity = compiler_identity(compiler, selected)
    generated = compiled_inventory(compile_marker, selected)
    runtime_objects, libraries = list(map(Path, runtime_objects)), list(map(Path, libraries))
    if not runtime_objects:
        raise ValueError("The Win32 platform runtime objects are required")
    for path in [*generated, *runtime_objects]:
        with path.open("rb") as stream:
            header = stream.read(2)
        if len(header) != 2 or int.from_bytes(header, "little") != selected["machine"]:
            raise ValueError("Wrong Windows COFF object architecture: " + path.name)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    resource_inputs = []
    if icon is not None:
        icon = Path(icon).resolve()
        resource_compiler = Path(identity["path"]).with_name(
            Path(identity["path"]).name.replace("clang", "windres"))
        if not resource_compiler.is_file():
            raise ValueError("The paired Windows resource compiler is missing")
        resource_inputs = [icon / "app.rc", icon / "app.ico"]
        resource = output.with_suffix(".icon.o")
        commands.run([resource_compiler, "-I", icon, "-i", icon / "app.rc",
                      "-O", "coff", "-o", resource])
        runtime_objects.append(resource)
    with tempfile.TemporaryDirectory(prefix="link-", dir=output.parent) as temporary:
        candidate = Path(temporary) / output.name
        response = Path(temporary) / "link.rsp"
        response_file(response, ["-fuse-ld=lld", "-municode",
                                "-Wl,--nxcompat,--dynamicbase,--high-entropy-va", *selected["cpu_flags"],
                                *generated, *runtime_objects, *libraries, "-o", candidate])
        commands.run([identity["path"], "--rsp-quoting=windows", "@" + str(response)])
        if windows.PE(candidate).machine != selected["machine"]:
            raise ValueError("Linked executable has the wrong Windows architecture")
        receipt = {"schema": 1, "profile": selected, "compiler": identity,
                   "binary": windows.sha256(candidate),
                   "inputs": {str(path): windows.sha256(path) for path in
                              [*generated, *runtime_objects, *libraries, *resource_inputs]}}
        output.with_suffix(output.suffix + ".json").unlink(missing_ok=True)
        os.replace(candidate, output)
        atomic_json(output.with_suffix(output.suffix + ".json"), receipt)
    return output


def package_game(executable, candidates, target, destination, notices, dynamic=(), *,
                 notice_trees=None, data=None):
    """Build a new local binary package; data/paths and GUI installation are separate."""
    closure = windows.dll_closure(executable, candidates, target, dynamic)
    if not notices:
        raise ValueError("Runtime dependency notices are required before packaging")
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Refusing to replace an existing game package")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="game-package-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        for path in closure:
            shutil.copyfile(path, stage / path.name)
        notice_dir = stage / "notices"
        notice_dir.mkdir()
        for name, path in notices.items():
            if Path(name).name != name or Path(name).suffix.lower() not in (".txt", ".md"):
                raise ValueError("Invalid dependency notice filename")
            shutil.copyfile(path, notice_dir / name)
        for name, path in (notice_trees or {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError("Invalid dependency notice directory")
            filesystem.copy_tree(path, notice_dir / name)
        for name, path in (data or {}).items():
            relative = Path(name)
            if relative.is_absolute() or any(part in ("", ".", "..") for part in re.split(r"[/\\]", name)):
                raise ValueError("Invalid game data destination")
            output = stage / relative
            if not output.resolve().is_relative_to(stage) or output.exists():
                raise ValueError("Game data conflicts with a packaged file")
            filesystem.reject_link(path)
            if Path(path).is_dir():
                filesystem.copy_tree(path, output)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, output)
        atomic_json(stage / "package.json", {"schema": 1, "target": windows.profile(target),
                    "files": {path.relative_to(stage).as_posix(): windows.sha256(path)
                              for path in sorted(stage.rglob("*")) if path.is_file()}})
        stage.rename(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("generate", "images", "compile", "generator", "overlay", "runtime", "link"))
    parser.add_argument("--target", choices=("x86_64", "aarch64"), default=windows.architecture())
    parser.add_argument("--host", choices=("x86_64", "aarch64"), default=windows.architecture())
    parser.add_argument("--cc", help="Explicit LLVM-MinGW target compiler")
    parser.add_argument("--host-cc", help="LLVM-MinGW compiler for the generator host, not the game target")
    parser.add_argument("--unicorn-root", type=Path)
    parser.add_argument("--work", type=Path, default=ROOT / "work")
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--with-subsdk1", action="store_true")
    parser.add_argument("--sdl-prefix", type=Path, help="New private SDL development-bundle directory")
    parser.add_argument("--vulkan-prefix", type=Path, help="Verified private Vulkan development bundle")
    parser.add_argument("--ffmpeg-prefix", type=Path, help="Verified private FFmpeg development bundle")
    parser.add_argument("--qt-prefix", type=Path, help="Verified shared Qt6 LLVM-MinGW UCRT/libc++ target bundle")
    args = parser.parse_args(argv)
    selected = windows.profile(args.target, args.host)
    if args.stage == "overlay":
        try:
            prepare_vulkan(ROOT, args.work / "recomp" / selected["cache_key"] / "nvn-src-vk")
            return 0
        except (ValueError, OSError) as error:
            print("Vulkan overlay failed: " + str(error), file=sys.stderr)
            return 4
    if sys.platform != "win32":
        parser.error("Native Windows stages require Windows; no Unix fallback")
    if args.host != windows.architecture():
        parser.error("The generator host must match the running Python architecture")
    commands = None
    work = args.work / "recomp" / selected["cache_key"]
    generator = args.work / "native-generator" / ("windows-" + args.host) / "bdsp_codegen.exe"
    try:
        commands = Commands()
        if args.stage in ("generator", "generate", "images"):
            builder = load_helper("bdsp_codegen_build", HERE / "native-generator/build.py")
            host_profile = windows.profile(args.host, args.host)
            compiler_identity(args.host_cc or args.cc or "", host_profile)
            generator = builder.build(generator, args.host_cc or args.cc,
                                      unicorn_root=args.unicorn_root, require_unicorn=True,
                                      command_runner=commands.run)
        if args.stage == "generate":
            generate(generator, args.work / "exefs", work / "gen", commands)
        elif args.stage == "images":
            images(generator, args.work / "exefs", work / "images",
                   HERE / "runtime/hle_nvn.txt", commands)
        elif args.stage == "compile":
            compile_sources(work / "gen", work / "objects", args.cc or "", selected, commands, args.jobs,
                            source_paths=generated_inventory(work / "gen"))
        elif args.stage == "runtime":
            compile_runtime(work / "runtime-vulkan", args.cc or "", selected, commands,
                            has_subsdk1=args.with_subsdk1, jobs=args.jobs,
                            sdl=args.sdl_prefix, vulkan=args.vulkan_prefix, ffmpeg=args.ffmpeg_prefix, qt=args.qt_prefix)
        elif args.stage == "link":
            host = compiled_inventory(work / "runtime-vulkan" / selected["cache_key"] / "compile.json", selected)
            libraries = graphical_libraries(args.cc or "", selected, args.sdl_prefix, args.vulkan_prefix,
                                            args.ffmpeg_prefix, qt=args.qt_prefix)
            link_executable(work / "objects" / selected["cache_key"] / "compile.json", host,
                            libraries, work / "BDSP.exe", args.cc or "", selected, commands)
        return 0
    except KeyboardInterrupt:
        if commands:
            commands.cancel()
        print("Windows build cancelled", file=sys.stderr)
        return 130
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if commands:
            commands.cancel()
        print("Windows build failed: " + str(error), file=sys.stderr)
        return 4
    finally:
        if commands:
            commands.close()


if __name__ == "__main__":
    raise SystemExit(main())
