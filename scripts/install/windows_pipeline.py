"""Private offline Windows pipeline; public release qualification stays separate."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from scripts.extract_game import extract_game
from scripts.recomp import portable_build as build
from scripts.recomp.app import game_icons
from scripts.install.progress import GeneratorProgress


def toolchain_files(root):
    build.filesystem.reject_link(root)
    files = []
    for parent, directories, names in os.walk(root):
        for name in [*directories, *names]:
            build.filesystem.reject_link(Path(parent) / name)
        files.extend(Path(parent) / name for name in sorted(names))
    return files


def write_catalog(output, compiler, generator, selected, **bundles):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Refusing to replace an existing private dependency catalog")
    compiler = Path(build.compiler_identity(compiler, selected)["path"])
    generator = Path(generator).resolve()
    paths = {name: build.verified_bundle(path, selected) for name, path in bundles.items()}
    if set(paths) not in ({"sdl", "vulkan", "ffmpeg", "hactool"},
                         {"sdl", "vulkan", "ffmpeg", "hactool", "qt"}):
        raise ValueError("SDL, Vulkan, FFmpeg and hactool bundles, plus optional verified Qt, are required")
    if "qt" in paths:
        build.qt_development(paths["qt"], compiler, selected)
    closure = build.windows.dll_closure(generator, generator.parent.glob("*.dll"),
                                        selected["host"], allow_build_tools=True)
    if build.windows.PE(generator).machine != build.windows.profile(selected["host"])["machine"]:
        raise ValueError("The generator architecture does not match the host")
    toolchain = compiler.parent.parent
    files = [*toolchain_files(toolchain), *closure, *(path / "build.json" for path in paths.values())]
    build.atomic_json(output, {
        "schema": 1, "private_only": True, "profile": selected,
        "compiler": os.path.relpath(compiler, output.parent),
        "toolchain": os.path.relpath(toolchain, output.parent),
        "generator": os.path.relpath(generator, output.parent),
        "bundles": {name: os.path.relpath(path, output.parent) for name, path in paths.items()},
        "frontend": "qt" if "qt" in paths else "sdl-diagnostic",
        "files": {os.path.relpath(path, output.parent): build.windows.sha256(path) for path in files},
        "release_qualified": False,
    })
    return output


def read_catalog(path, target):
    path = Path(path).resolve()
    record = json.loads(path.read_text(encoding="utf-8"))
    selected = build.windows.profile(target)
    if (record.get("schema") != 1 or record.get("private_only") is not True or
            record.get("release_qualified") is not False or
            record.get("profile") != selected or not record.get("files")):
        raise ValueError("The private Windows catalog does not match the host/target profile")
    if target != "x86_64" or selected["host"] != "x86_64":
        raise ValueError("The full native pipeline currently has only amd64 development dependencies")
    for name, digest in record["files"].items():
        if build.windows.sha256(path.parent / name) != digest:
            raise ValueError("A private Windows catalog file changed; prepare a new catalog")
    bundles = {name: build.verified_bundle(path.parent / relative, selected)
               for name, relative in record["bundles"].items()}
    if set(bundles) not in ({"sdl", "vulkan", "ffmpeg", "hactool"},
                           {"sdl", "vulkan", "ffmpeg", "hactool", "qt"}):
        raise ValueError("The private dependency catalog is incomplete")
    compiler = (path.parent / record["compiler"]).resolve()
    if record.get("frontend", "sdl-diagnostic") != ("qt" if "qt" in bundles else "sdl-diagnostic"):
        raise ValueError("The private catalog frontend does not match its bundles")
    if "qt" in bundles:
        build.qt_development(bundles["qt"], compiler, selected)
    generator = (path.parent / record["generator"]).resolve()
    toolchain = (path.parent / record["toolchain"]).resolve()
    if compiler.parent.parent != toolchain:
        raise ValueError("The private compiler is outside its inventoried toolchain")
    closure = build.windows.dll_closure(generator, generator.parent.glob("*.dll"),
                                        selected["host"], allow_build_tools=True)
    for file in (*toolchain_files(toolchain), *closure, *(bundle / "build.json" for bundle in bundles.values())):
        if os.path.relpath(file, path.parent) not in record["files"]:
            raise ValueError("The private dependency catalog has an untracked input")
    build.compiler_identity(compiler, selected)
    return selected, compiler, generator, bundles


def prerequisites(catalog, target, work, minimum_free_gb=40):
    if sys.platform != "win32":
        raise ValueError("The Windows pipeline requires a native Windows host")
    version = sys.getwindowsversion()
    if version.major < 10 or version.build < 19045:
        raise ValueError("Windows 10 22H2 (19045) or Windows 11 is required")
    result = read_catalog(catalog, target)
    destination = Path(work).resolve()
    while not destination.exists():
        destination = destination.parent
    if shutil.disk_usage(destination).free < minimum_free_gb * 10**9:
        raise ValueError("Not enough free space for the native Windows build")
    return result


def publish_package(candidate, destination):
    """Replace only the installer's unchanged binary; preserve a failed rollback."""
    candidate, destination = Path(candidate), Path(destination)
    package_record(candidate)
    if destination.exists():
        try:
            package_record(destination)
            owned = True
        except (OSError, ValueError, KeyError, TypeError):
            owned = False
        if not owned:
            raise FileExistsError("The existing application is not this installer's unchanged Windows package")
    return build.filesystem.publish_tree(candidate, destination)


def package_record(package):
    package = Path(package)
    build.filesystem.reject_link(package)
    build.filesystem.reject_link(package / "package.json")
    record = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema") != 1 or
            record.get("target") != build.windows.profile("x86_64") or
            not isinstance(record.get("files"), dict) or "BDSP.exe" not in record["files"]):
        raise ValueError("The Windows package receipt is incomplete or has the wrong target")
    build.filesystem.verify_inventory(package, record["files"], ignored=("package.json",))
    return record


def install_package(package, destination, emit):
    package, destination = Path(package), Path(destination)
    package_record(package)
    emit("step", id="install", status="started")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="windows-install-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "app"
        build.filesystem.copy_tree(package, staged)
        publish_package(staged, destination)
    emit("step", id="install", status="complete")
    executable = destination / "BDSP.exe"
    emit("artifact", kind="installed_application", path=str(executable))
    return executable


def build_game(args, emit):
    selected, compiler, generator, bundles = prerequisites(
        args.windows_catalog, "aarch64" if args.target == "windows-arm64" else "x86_64", args.work)
    if getattr(args, "mod_root", None):
        raise ValueError("Mod installation is not wired to the native Windows package yet; no mod was ignored")
    root, work = Path(args.root).resolve(), Path(args.work).resolve()
    output = work / "recomp" / selected["cache_key"]
    if output.resolve() != output:
        raise ValueError("The native build cache must not pass through a symbolic link or reparse point")
    for name in ("base", "prod_keys", "title_keys", "update", "mod_root", "windows_catalog"):
        value = getattr(args, name, None)
        if value and Path(value).resolve().is_relative_to(output):
            raise ValueError("Selected inputs must remain outside the replaceable native build cache")
    icons = work / "recomp/icons/source"  # outside the replaceable build cache, like the other pipelines
    generator_progress = GeneratorProgress(4 + int((work / "exefs/subsdk1").is_file()))
    def tool_line(line):
        progress = generator_progress.feed(line)
        if progress:
            emit("progress", **progress)
        else:
            emit("log", level="diagnostic", message=line)
    class InstallerCommands(build.Commands):
        def run(self, arguments):
            try:
                self.capture(arguments, on_line=tool_line)
            except subprocess.CalledProcessError:
                raise ValueError("Native compilation or generation failed; see the technical log.") from None
    commands = InstallerCommands()
    def stage(name, function):
        emit("step", id=name, status="started")
        try:
            result = function()
        except BaseException:
            emit("step", id=name, status="failed")
            raise
        emit("step", id=name, status="complete")
        return result
    try:
        stage("extract", lambda: extract_game(
            args.base, args.prod_keys, work, bundles["hactool"] / "hactool.exe", commands,
            update=args.update, title_keys=getattr(args, "title_keys", None),
            progress=lambda text: emit("log", level="diagnostic", message=text), icons=icons))
        def verify_exefs():
            names = build.modules(work / "exefs")
            if not (work / "exefs/main.npdm").is_file():
                raise ValueError("The native extractor produced no exefs/main.npdm")
            generator_progress.total = len(names)
        stage("exefs", verify_exefs)
        def prepare_icons():
            return game_icons.build_windows(icons, output / "icons/windows")
        if getattr(args, "clean_build", False) and output.exists():
            # Keep all old outputs recoverable while building a fresh target cache.
            previous = output.with_name(output.name + "-previous-" + uuid.uuid4().hex)
            output.rename(previous)
            emit("log", level="diagnostic", message="Previous native build outputs were preserved in " + str(previous))
        stage("eh_gen", lambda: build.generate(generator, work / "exefs", output / "gen", commands))
        stage("clang", lambda: build.compile_sources(
            output / "gen", output / "objects", compiler, selected, commands,
            source_paths=build.generated_inventory(output / "gen"),
            progress=lambda completed, total: emit("progress", id="clang", completed=completed, total=total)))
        def prepare_images():
            build.images(generator, work / "exefs", output / "images",
                         root / "scripts/recomp/rt-bdsp/hle_nvn.txt", commands)
            prepare_icons()
        stage("images", prepare_images)
        frontend = "qt" if "qt" in bundles else "sdl"
        runtime = stage("runtime", lambda: build.compile_runtime(
            output / "runtime-vulkan", compiler, selected, commands, backend="vulkan",
            has_subsdk1=(work / "exefs/subsdk1").is_file(), root=root,
            frontend=frontend, qt=bundles.get("qt"),
            **{name: bundles[name] for name in ("sdl", "vulkan", "ffmpeg")}))
        executable = stage("link", lambda: build.link_executable(
            output / "objects" / selected["cache_key"] / "compile.json", runtime,
            build.graphical_libraries(compiler, selected, *(bundles[name] for name in ("sdl", "vulkan", "ffmpeg")),
                                      frontend=frontend, qt=bundles.get("qt")),
            output / "BDSP.exe", compiler, selected, commands, icon=output / "icons/windows"))
        destination = work / "builds/windows-amd64/BDSP"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="windows-package-", dir=destination.parent) as temporary:
            def package():
                dependencies = [bundles[name] for name in ("sdl", "vulkan", "ffmpeg")]
                toolchain = Path(compiler).parent.parent
                toolchain_license = toolchain / "LICENSE.TXT"
                notices = {name: bundles[name] / "notices" for name in ("sdl", "vulkan", "ffmpeg")}
                notices["mingw-runtime"] = toolchain / (selected["target"] + "-w64-mingw32") / "share/mingw32"
                data = {"img": output / "images", "romfs": work / "romfs",
                        "exefs/main.npdm": work / "exefs/main.npdm",
                        "icons/windows": output / "icons/windows"}
                dynamic = []
                if "qt" in bundles:
                    dependencies.append(bundles["qt"])
                    notices["qt"] = bundles["qt"] / "notices"
                    plugin = bundles["qt"] / "plugins/platforms/qwindows.dll"
                    providers = build.runtime_dll_candidates(compiler, selected, dependencies)
                    dynamic = [path.name for path in build.windows.dll_closure(
                        plugin, providers, selected["target"]) if path != plugin]
                    data["plugins/platforms/qwindows.dll"] = plugin
                    qt_conf = Path(temporary) / "qt.conf"
                    qt_conf.write_text("[Paths]\nPrefix=.\nPlugins=plugins\n", encoding="utf-8")
                    data["qt.conf"] = qt_conf
                    data["lproj"] = root / "scripts/recomp/rt-bdsp/app/linux/lproj"
                packaged = build.package_game(
                    executable, build.runtime_dll_candidates(compiler, selected, dependencies),
                    selected["target"], Path(temporary) / "BDSP",
                    {"runtime.md": root / "scripts/recomp/rt-bdsp/NOTICE.md",
                     "vulkan.md": root / "scripts/recomp/rt-bdsp/nvn/vulkan/NOTICE.md",
                     "toolchain.txt": toolchain_license},
                    dynamic=dynamic, notice_trees=notices, data=data)
                return publish_package(packaged, destination)
            stage("package", package)
        override = getattr(args, "install_root", None)
        if override:
            install = Path(override) / "BDSP"
        else:
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise ValueError("The Windows per-user application data directory is unavailable")
            install = Path(local) / "StrahlenderXnu/app"
        return install_package(destination, install, emit)
    except BaseException:
        commands.cancel()
        raise
    finally:
        commands.close()


def main():
    parser = argparse.ArgumentParser(description="Register verified private offline bundles; never downloads.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--generator", type=Path, required=True)
    for name in ("sdl", "vulkan", "ffmpeg", "hactool"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--qt", type=Path, help="Verified shared Qt6 LLVM-MinGW UCRT/libc++ bundle")
    args = parser.parse_args()
    write_catalog(args.output, args.cc, args.generator, build.windows.profile("x86_64"),
                  **{name: getattr(args, name) for name in ("sdl", "vulkan", "ffmpeg", "hactool")},
                  **({"qt": args.qt} if args.qt else {}))


if __name__ == "__main__":
    main()
