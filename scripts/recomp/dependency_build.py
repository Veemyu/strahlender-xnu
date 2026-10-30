#!/usr/bin/env python3
"""Offline maintainer dependency recipes, separate from the direct game build."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from . import portable_build as build
else:
    import portable_build as build

ROOT = build.ROOT
LOCK = Path(os.environ.get("BDSP_WINDOWS_SOURCES") or ROOT / "installer/assets/windows-sources.json")
VULKAN_SOURCES = ("vulkan-headers", "vma", "shaderc", "glslang", "spirv-headers", "spirv-tools")


def import_ffmpeg(archive, destination, selected, archives=None, license_dir=None):
    """Import an FFmpeg development ZIP (BtbN lgpl-shared); never install tools or rebuild FFmpeg.

    The caller verified the download against the digest GitHub publishes. A lock file that pins this archive
    (size, hash, root) is checked as well when present.
    """
    component = next((item for item in build.windows.contract()["components"] if item["id"] == "ffmpeg"), {})
    archive, destination = Path(archive), Path(destination).resolve()
    pinned = [item for item in component.get("artifacts", []) if item["target"] == selected["target"]]
    if pinned:
        artifact = pinned[0]
        if archive.stat().st_size != artifact["size_bytes"] or build.windows.sha256(archive) != artifact["sha256"]:
            raise ValueError("FFmpeg archive checksum/size mismatch")
    else:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
        roots = {item.filename.split("/")[0] for item in entries}
        if len(roots) != 1:
            raise ValueError("Expected one FFmpeg archive root")
        artifact = {"target": selected["target"], "archive_root": roots.pop(), "size_bytes": archive.stat().st_size,
                    "sha256": build.windows.sha256(archive),
                    "expanded_size_bytes": sum(item.file_size for item in entries)}
    if destination.exists():
        raise ValueError("Refusing to replace an existing FFmpeg bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-import-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if sum(item.file_size for item in entries) != artifact["expanded_size_bytes"]:
                raise ValueError("FFmpeg archive expanded size mismatch")
            names = set()
            for item in entries:
                parts = item.filename.rstrip("/").split("/")
                if (parts[0] != artifact["archive_root"] or
                        any(part in ("", ".", "..") or re.search(r'[\\:<>"|?*\x00-\x1f]', part)
                            or part.endswith((".", " ")) for part in parts) or
                        item.filename.lower() in names or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Unsafe FFmpeg archive path: " + item.filename)
                names.add(item.filename.lower())
            source.extractall(stage / "archive")
        source = stage / "archive" / artifact["archive_root"]
        package = stage / "package"
        for directory in ("include", "lib", "doc"):
            shutil.copytree(source / directory, package / directory)
        notices = package / "notices/ffmpeg"
        notices.mkdir(parents=True)
        shutil.copyfile(source / "LICENSE.txt", notices / "LICENSE.txt")
        license_texts = None
        if license_dir is not None:
            for name in ("COPYING.GPLv3", "COPYING.LGPLv3"):
                shutil.copyfile(Path(license_dir) / name, notices / name)
            license_texts = {"source": "prepared licence texts", "scope": "Generic GPLv3/LGPLv3 texts only."}
        elif archives is not None:
            license_lock = source_lock()
            license_source = extract_source(archives, "ffmpeg", stage / "license-texts", license_lock)
            for name in ("COPYING.GPLv3", "COPYING.LGPLv3"):
                text = license_source / name
                build.filesystem.reject_link(text)
                shutil.copyfile(text, notices / name)
            license_texts = {
                "source": license_lock["ffmpeg"],
                "scope": "Generic GPLv3/LGPLv3 texts only; this older source is NOT corresponding source for the binary.",
            }
        providers = list((source / "bin").glob("*.dll"))
        closure = {}
        for name, major in (("avcodec", 62), ("avformat", 62), ("avutil", 60)):
            for relative in (f"include/lib{name}/{name}.h", f"lib/lib{name}.dll.a"):
                if not (package / relative).is_file():
                    raise ValueError("Missing FFmpeg development file: " + relative)
            for path in build.windows.dll_closure(source / f"bin/{name}-{major}.dll", providers,
                                                  selected["target"]):
                closure[path.name] = path
        (package / "bin").mkdir()
        for name, path in closure.items():
            shutil.copyfile(path, package / "bin" / name)
        build.atomic_json(package / "build.json", {
            "schema": 1, "profile": selected, "version": component.get("version") or artifact["archive_root"], "artifact": artifact,
            "recipe_sha256": build.windows.sha256(__file__),
            "support_sha256": build.windows.sha256(build.windows.__file__),
            "license_review": component.get("qualification", ""),
            "license_texts": license_texts,
            "files": {path.relative_to(package).as_posix(): build.windows.sha256(path)
                      for path in sorted(package.rglob("*")) if path.is_file()},
            "qualified": False,
        })
        package.rename(destination)
    return destination


def source_lock():
    return json.loads(LOCK.read_text(encoding="utf-8"))["sources"]


def extract_source(archives, name, destination, lock):
    item = lock[name]
    archive = Path(archives) / (name + "-" + item["revision"] + ".tar.gz")
    if archive.stat().st_size != item["size_bytes"] or build.windows.sha256(archive) != item["sha256"]:
        raise ValueError("Source archive checksum/size mismatch: " + name)
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as source:
        source.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError("Expected one source archive root: " + name)
    return children[0]


def pin_build_description(path, revision):
    """Bypass upstream VCS probing before any build script can invoke Git."""
    before = build.windows.sha256(path)
    text = path.read_text(encoding="utf-8")
    pattern = r"(?m)^(def describe\((?:directory|repo_path)\):\n)"
    text, count = re.subn(pattern, lambda match: match[1] + "    return " + repr(revision) + "\n", text)
    if count != 1:
        raise ValueError("Upstream version script changed: " + str(path))
    path.write_text(text, encoding="utf-8", newline="\n")
    return {"before": before, "after": build.windows.sha256(path),
            "change": "Use pinned source revision instead of invoking Git."}


def collect_notices(source, destination, component=None):
    build.filesystem.copy_notices(source, destination)
    if component == "hactool":
        # hactool embeds these distinct notices in the compiled upstream sources.
        embedded = destination / "embedded-source"
        embedded.mkdir(parents=True, exist_ok=True)
        for name in ("cJSON.c", "ConvertUTF.c", "ConvertUTF.h", "lz4.c", "lz4.h"):
            shutil.copyfile(source / name, embedded / name)


def bundle_receipt(package, selected, identity, sources, tools, **extra):
    build.atomic_json(package / "build.json", {
        "schema": 1, "profile": selected, "sources": sources,
        "recipe_sha256": build.windows.sha256(__file__),
        "driver_sha256": build.windows.sha256(build.__file__),
        "compiler": {key: value for key, value in identity.items() if key != "path"},
        "tools": {name: build.windows.sha256(path) for name, path in tools.items()},
        **extra,
        "files": {path.relative_to(package).as_posix(): build.windows.sha256(path)
                  for path in sorted(package.rglob("*")) if path.is_file()},
        "qualified": False,
    })


def build_hactool(archives, destination, compiler, selected, commands, jobs=None):
    """Direct C build from the approved archive, including its bundled mbedTLS."""
    identity = build.compiler_identity(compiler, selected)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Refusing to replace an existing hactool bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = source_lock()
    with tempfile.TemporaryDirectory(prefix="hactool-build-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        source = extract_source(archives, "hactool", stage / "source", lock)
        patches = patch_hactool_paths(source)
        makefile = (source / "Makefile").read_text(encoding="utf-8")
        match = re.search(r"(?m)^hactool\$\(EXEEXT\): ([^\n]+)$", makefile)
        if not match or not re.fullmatch(r"(?:[A-Za-z0-9_]+\.o ?)+", match[1]):
            raise ValueError("Upstream hactool source inventory changed")
        sources = [source / (name[:-2] + ".c") for name in match[1].split()]
        crypto = (source / "mbedtls/library/Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
        match = re.search(r"(?m)^OBJS_CRYPTO=(.+)$", crypto)
        if not match:
            raise ValueError("Upstream mbedTLS crypto inventory changed")
        names = match[1].split()
        if not all(re.fullmatch(r"[a-z0-9_]+\.o", name) for name in names):
            raise ValueError("Invalid mbedTLS crypto inventory")
        sources += [source / "mbedtls/library" / (name[:-2] + ".c") for name in names]
        boundary = Path(__file__).with_name("hactool_windows.c")
        header = boundary.with_suffix(".h")
        sources.append(boundary)
        per_source = {source / "main.c": ("-Dmain=hactool_main", "-Dfopen=bdsp_tool_fopen",
                                          "-include", str(header)),
                      source / "filepath.c": ("-include", str(header))}
        objects = build.compile_sources(
            source, stage / "objects", identity["path"], selected, commands, jobs=jobs,
            extra=("-I", str(source), "-I", str(source / "mbedtls/include"),
                   "-D_BSD_SOURCE", "-D_DEFAULT_SOURCE", "-D_FILE_OFFSET_BITS=64",
                   "-D__USE_MINGW_ANSI_STDIO=1"),
            source_paths=sources, dependency_headers=[header, *sorted(source.rglob("*.h"))],
            source_flags=per_source)
        package = stage / "package"
        package.mkdir()
        response = stage / "link.rsp"
        executable = package / "hactool.exe"
        build.response_file(response, [
            "-fuse-ld=lld", "-municode", *selected["cpu_flags"], *objects,
            "-ladvapi32", "-lws2_32", "-Wl,--nxcompat,--dynamicbase,--high-entropy-va",
            "-o", executable])
        commands.run([identity["path"], "--rsp-quoting=windows", "@" + str(response)])
        build.windows.dll_closure(executable, (), selected["target"], allow_build_tools=True)
        collect_notices(source, package / "notices/hactool", "hactool")
        bundle_receipt(package, selected, identity, {"hactool": lock["hactool"]}, {},
                       boundary={path.name: build.windows.sha256(path) for path in (boundary, header)},
                       source_inventory=[path.relative_to(source).as_posix()
                                         for path in sources if path != boundary],
                       adaptations={"main.c": list(per_source[source / "main.c"])}, patches=patches)
        package.rename(destination)
    return destination


LICENSE_NAME = re.compile(r"(?i)^(license|licence|copying|notice|qt_attribution)[^/]*$")


def qt_notices(source_archive, destination):
    """Licence texts of qtbase and of the third-party code inside it (src/3rdparty/*), from the qtbase source archive."""
    destination = Path(destination)
    destination.mkdir(parents=True)
    with tarfile.open(source_archive, "r:xz") as source:
        for member in source.getmembers():
            parts = member.name.split("/")
            relative = parts[1:]
            wanted = (len(relative) >= 2 and relative[0] == "LICENSES") or (len(relative) == 1 and LICENSE_NAME.match(relative[0])) \
                or (len(relative) >= 4 and relative[:2] == ["src", "3rdparty"] and LICENSE_NAME.match(relative[-1]))
            if member.isfile() and wanted and ".." not in relative:
                target = destination.joinpath(*relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.extractfile(member).read())
    if not any(destination.iterdir()):
        raise ValueError("The Qt source archive has no licence texts")
    return destination


def build_qt(qt_root, notices_dir, destination, compiler, selected, version):
    """Bundle the shared Qt6 that Qt publishes for LLVM-MinGW UCRT/libc++ (the C++ ABI of our compiler), plus its licence texts.

    `notices_dir` holds the licence texts of the matching qtbase source (see qt_notices); the compiler is the one Qt pairs with the kit.
    """
    qt_root, destination = Path(qt_root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Refusing to replace an existing Qt bundle")
    if not re.fullmatch(r"6\.\d+\.\d+", version):
        raise ValueError("Unexpected Qt version: " + version)
    identity = build.compiler_identity(compiler, selected)
    cxx = build.compiler_identity(Path(identity["path"]).with_name(selected["target"] + "-w64-mingw32-clang++.exe"), selected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wanted = [("include", ("QtCore", "QtGui", "QtWidgets")), ("lib", ()), ("bin", ()), ("plugins", ("platforms", "styles", "imageformats"))]
    with tempfile.TemporaryDirectory(prefix="qt-bundle-", dir=destination.parent) as temporary:
        package = Path(temporary) / "package"
        for folder, names in wanted:
            source = qt_root / folder
            if not source.is_dir():
                raise ValueError("Qt installation lacks " + folder)
            if names:
                for name in names:
                    if (source / name).is_dir():
                        build.filesystem.copy_tree(source / name, package / folder / name)
            else:
                (package / folder).mkdir(parents=True)
                for module in ("Core", "Gui", "Widgets"):
                    for pattern in (f"libQt6{module}.a", f"Qt6{module}.dll"):
                        for path in source.glob(pattern):
                            shutil.copyfile(path, package / folder / path.name)
        build.filesystem.copy_tree(Path(notices_dir), package / "notices/qt")
        if not any((package / "notices/qt").iterdir()):
            raise ValueError("No Qt licence texts")
        bundle_receipt(package, selected, identity, {"qtbase": {"version": version}}, {},
                       qt={"linkage": "shared", "cxx_runtime": "libc++", "version": version,
                           "minimum_windows_build": build.windows.contract()["minimum_windows_build"],
                           "cxx_compiler_sha256": cxx["sha256"]})
        package.rename(destination)
    return destination


def patch_hactool_paths(source):
    """Bound upstream fixed-size path construction before opening any output."""
    patches = {}
    edits = {
        "filepath.c": [
            ("    strcat(fpath->char_path, OS_PATH_SEPARATOR);\n    strcat(fpath->char_path, tmppath);",
             "    bdsp_tool_component(tmppath);\n"
             "    if (strlen(fpath->char_path) + strlen(tmppath) + 2 > MAX_PATH) {\n"
             '        fputs("Extracted path is too long\\n", stderr); exit(EXIT_FAILURE);\n    }\n'
             "    strcat(fpath->char_path, OS_PATH_SEPARATOR);\n    strcat(fpath->char_path, tmppath);"),
            ("    strcat(fpath->char_path, OS_PATH_SEPARATOR);\n    strncat(fpath->char_path, tmppath, n);",
             "    if (n >= sizeof(tmppath)) n = sizeof(tmppath) - 1;\n"
             "    tmppath[n] = 0;\n    bdsp_tool_component(tmppath);\n"
             "    if (strlen(fpath->char_path) + strlen(tmppath) + 2 > MAX_PATH) {\n"
             '        fputs("Extracted path is too long\\n", stderr); exit(EXIT_FAILURE);\n    }\n'
             "    strcat(fpath->char_path, OS_PATH_SEPARATOR);\n    strcat(fpath->char_path, tmppath);"),
            ("        fpath->valid = VALIDITY_INVALID;\n",
             '        fputs("Tool path is too long\\n", stderr); exit(EXIT_FAILURE);\n'),
        ],
        "main.c": [
            ("        strncpy(input_name, argv[optind], sizeof(input_name) - 1);",
             "        if (strlen(argv[optind]) >= sizeof(input_name)) {\n"
             '            fputs("Input path is too long\\n", stderr); return EXIT_FAILURE;\n        }\n'
             "        strncpy(input_name, argv[optind], sizeof(input_name) - 1);"),
        ],
    }
    for name, replacements in edits.items():
        path = source / name
        before = build.windows.sha256(path)
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if text.count(old) != 1:
                raise ValueError("Upstream hactool path implementation changed: " + name)
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8", newline="\n")
        patches[name] = {"before": before, "after": build.windows.sha256(path)}
    return patches


def vulkan_import_library(registry, output, compiler, selected, commands):
    # Import libraries contain symbol references only, never a redistributed loader.
    tree = ET.parse(registry)
    names = {node.findtext("proto/name") or node.get("name")
             for node in tree.findall("./commands/command") if node.get("api") != "vulkansc"}
    if None in names or not {"vkCreateInstance", "vkGetInstanceProcAddr"}.issubset(names):
        raise ValueError("Invalid Vulkan command registry")
    definition = output.with_suffix(".def")
    definition.write_text("LIBRARY vulkan-1.dll\nEXPORTS\n" + "\n".join(sorted(names)) + "\n",
                          encoding="ascii")
    commands.run([Path(compiler).with_name(selected["target"] + "-w64-mingw32-dlltool.exe"),
                  "-d", definition, "-l", output])


def build_vulkan(archives, destination, compiler, selected, cmake, ninja, commands, jobs=None):
    identity = build.compiler_identity(compiler, selected)
    compiler = Path(identity["path"])
    cmake, ninja, destination = Path(cmake).resolve(), Path(ninja).resolve(), Path(destination).resolve()
    if not cmake.is_file() or not ninja.is_file():
        raise ValueError("Explicit existing maintainer CMake and Ninja executables are required")
    if destination.exists():
        raise ValueError("Refusing to replace an existing Vulkan bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = source_lock()
    with tempfile.TemporaryDirectory(prefix="vulkan-build-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        sources = {name: extract_source(archives, name, stage / name, lock) for name in VULKAN_SOURCES}
        patches = {}
        for name, relative in (("shaderc", "utils/update_build_version.py"),
                               ("spirv-tools", "utils/update_build_version.py")):
            patches[name + "/" + relative] = pin_build_description(
                sources[name] / relative, lock[name]["revision"])
        package = stage / "package"
        definitions = {
            **build.cmake_target_definitions(compiler, selected, ninja, stage, package),
            "SHADERC_SKIP_TESTS": "ON", "SHADERC_SKIP_EXAMPLES": "ON",
            "SHADERC_SKIP_EXECUTABLES": "ON", "SHADERC_SKIP_COPYRIGHT_CHECK": "ON",
            "SHADERC_ENABLE_WERROR_COMPILE": "OFF", "SHADERC_ENABLE_HLSL": "OFF",
            "SHADERC_ENABLE_WGSL_OUTPUT": "OFF", "BUILD_SHARED_LIBS": "OFF",
            "SPIRV_SKIP_TESTS": "ON", "SPIRV_SKIP_EXECUTABLES": "ON",
            "ENABLE_GLSLANG_BINARIES": "OFF", "GLSLANG_TESTS": "OFF",
            "ENABLE_PCH": "OFF", "CMAKE_DISABLE_FIND_PACKAGE_Git": "TRUE",
            "FETCHCONTENT_FULLY_DISCONNECTED": "ON",
            "Python_EXECUTABLE:FILEPATH": sys.executable,
            "Python3_EXECUTABLE:FILEPATH": sys.executable,
            **{"SHADERC_" + name.upper().replace("-", "_") + "_DIR:PATH": str(sources[name])
               for name in ("glslang", "spirv-headers", "spirv-tools")},
        }
        commands.run([cmake, "-S", sources["shaderc"], "-B", stage / "build", "-G", "Ninja",
                      *(f"-D{name}={value}" for name, value in sorted(definitions.items()))])
        commands.run([cmake, "--build", stage / "build", "--parallel",
                      str(jobs or build.parallel.choose_jobs(build.parallel.cpu_count(),
                                                            build.parallel.memory_bytes()))])
        commands.run([cmake, "--install", stage / "build"])
        shutil.copytree(sources["vulkan-headers"] / "include", package / "include", dirs_exist_ok=True)
        shutil.copyfile(sources["vma"] / "include/vk_mem_alloc.h", package / "include/vk_mem_alloc.h")
        vulkan_import_library(sources["vulkan-headers"] / "registry/vk.xml",
                              package / "lib/libvulkan-1.a", compiler, selected, commands)
        # Shaderc owns allocation/free across its C API; copy only its measured C++ DLL closure.
        library = package / "bin/libshaderc_shared.dll"
        providers = list((compiler.parent.parent / (selected["target"] + "-w64-mingw32") / "bin").glob("*.dll"))
        providers += [path for path in (package / "bin").glob("*.dll") if path != library]
        for path in build.windows.dll_closure(library, providers, selected["target"]):
            if path.parent != package / "bin":
                shutil.copyfile(path, package / "bin" / path.name)
        for name, source in sources.items():
            collect_notices(source, package / "notices" / name, name)
        bundle_receipt(package, selected, identity, {name: lock[name] for name in VULKAN_SOURCES},
                       {"cmake": cmake, "ninja": ninja, "python": sys.executable},
                       patches=patches, definitions=definitions)
        package.rename(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("vulkan", "ffmpeg", "hactool", "qt", "qt-notices"))
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--qt-root", type=Path, help="Qt installation for LLVM-MinGW (contains bin, lib, include, plugins)")
    parser.add_argument("--qt-source", type=Path, help="Matching qtbase-everywhere-src .tar.xz (licence texts)")
    parser.add_argument("--qt-notices", type=Path, help="Licence texts prepared by the qt-notices step")
    parser.add_argument("--license-dir", type=Path, help="Folder with COPYING.GPLv3 and COPYING.LGPLv3 for FFmpeg")
    parser.add_argument("--qt-version")
    parser.add_argument("--archive", type=Path, help="Already downloaded pinned FFmpeg development ZIP")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--cc")
    parser.add_argument("--cmake", type=Path)
    parser.add_argument("--ninja", type=Path)
    parser.add_argument("--target", choices=("x86_64", "aarch64"), default=build.windows.architecture())
    parser.add_argument("--jobs", type=int)
    args = parser.parse_args(argv)
    if args.component == "ffmpeg" and not args.archive:
        parser.error("ffmpeg requires --archive")
    if args.component == "vulkan" and not all((args.archives, args.cc, args.cmake, args.ninja)):
        parser.error("vulkan requires --archives, --cc, --cmake and --ninja")
    if args.component == "hactool" and not all((args.archives, args.cc)):
        parser.error("hactool requires --archives and --cc")
    if args.component == "qt" and not all((args.qt_root, args.qt_notices, args.qt_version, args.cc)):
        parser.error("qt requires --qt-root, --qt-notices, --qt-version and --cc")
    if args.component == "qt-notices" and not args.qt_source:
        parser.error("qt-notices requires --qt-source")
    commands = build.Commands()
    try:
        if args.component == "qt-notices":
            qt_notices(args.qt_source, args.prefix)
        elif args.component == "qt":
            build_qt(args.qt_root, args.qt_notices, args.prefix, args.cc, build.windows.profile(args.target), args.qt_version)
        elif args.component == "ffmpeg":
            import_ffmpeg(args.archive, args.prefix, build.windows.profile(args.target), args.archives, args.license_dir)
        elif args.component == "hactool":
            build_hactool(args.archives, args.prefix, args.cc, build.windows.profile(args.target),
                          commands, args.jobs)
        else:
            build_vulkan(args.archives, args.prefix, args.cc, build.windows.profile(args.target),
                         args.cmake, args.ninja, commands, args.jobs)
    except KeyboardInterrupt:
        commands.cancel()
        return 130
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        commands.cancel()
        print("Dependency preparation failed: " + str(error), file=sys.stderr)
        return 4
    finally:
        commands.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
