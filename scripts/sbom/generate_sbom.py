#!/usr/bin/env python3
"""Generates the software bill of materials (SBOM) of the repository.

Outputs (default: sbom/):
  sbom-strahlender-xnu.spdx.json   SPDX 2.3, JSON
  sbom-strahlender-xnu.spdx        SPDX 2.3, tag-value
  sbom-strahlender-xnu.cdx.json    CycloneDX 1.6, JSON
  sbom-strahlender-xnu.csv         flat inventory for review and spreadsheets

Sources:
  installer/Cargo.lock        Rust crates with SHA-256 checksums. Licences and dependency edges come from
                              `cargo metadata --locked --offline` (without cargo or the registry cache: no licence data).
  installer/runtime/*.json    private Python runtime: CPython archive hashes, pinned wheels per platform.
  tools/pydeps/*.dist-info    locally installed Python packages (git-ignored); skipped when absent.
  CATALOG below               everything else: vendored code, assets, pinned build inputs, system packages.
                              Each entry names its evidence files, so a reviewer can check it against the repository.

Standard library only (Python 3.11+ for tomllib). Run from anywhere:
  python3 scripts/sbom/generate_sbom.py [--out DIR]
"""
import argparse
import csv
import datetime
import json
import re
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = "strahlender-xnu-sbom (scripts/sbom/generate_sbom.py)"

# Distribution classes: where the component ends up.
SHIPPED = "shipped"          # in the installer, the app bundle or the release archive
BUILD = "build-tool"         # needed to build, not part of the output
DEV = "dev-test"             # tests and development helpers only
USER = "user-installed"      # installed by the user from the system package manager
LOCAL = "local-tool"         # present in tools/ (git-ignored), used by the build
OPTIONAL = "optional"        # profile or tool not yet shipped / not always used

# Repository state.
TRACKED = "tracked"
IGNORED = "git-ignored (tools/)"
EXTERNAL = "external"

LICENSE_REFS = {
    "LicenseRef-Apple-SDK": (
        "Apple Xcode and SDK Agreement",
        "Xcode, Command Line Tools and the Apple SDK frameworks (Metal, AppKit, UIKit, ...). Use only under Apple's terms.",
    ),
    "LicenseRef-FMOD": (
        "FMOD (Firelight Technologies) runtime",
        "Proprietary FMOD runtime library (libfmod) inside fmod_toolkit. Redistribution only under the FMOD license terms. Not evaluated here.",
    ),
}


# Decided by the project owner (2026-10-30): Unicorn is distributed under GPL-2.0-only, despite the wheel's BSD classifier.
CONCLUDED = {"unicorn": "GPL-2.0-only"}

def C(cid, name, version, purl, license_expr, distribution, tracked, evidence, *, download=None,
      copyright_text=None, category="library", sha256=None, notes=""):
    """One catalogue entry. `license_expr` is an SPDX expression; LicenseRef-* ids need LICENSE_REFS."""
    return {
        "id": cid, "name": name, "version": version, "purl": purl, "license": license_expr,
        "distribution": distribution, "tracked": tracked, "evidence": list(evidence),
        "download": download, "copyright": copyright_text, "category": category,
        "sha256": sha256, "notes": notes, "depends_on": [],
    }


# ---------------------------------------------------------------- catalogue
CATALOG = [
    # Vendored source code (tracked). LASRecomp is MIT, see THIRD_PARTY_NOTICES.md.
    C("lasrecomp", "LASRecomp (vendored parts: shader_translator, scripts/recomp/upstream, scripts/recomp/runtime)",
      "09f8e5e", "pkg:github/peiikai/LASRecomp@09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5", "MIT", SHIPPED, TRACKED,
      ["THIRD_PARTY_NOTICES.md", "shader_translator/NOTICE.md", "scripts/recomp/runtime/NOTICE.md",
       "scripts/recomp/upstream/LICENSE", "scripts/recomp/native-generator/NOTICE.md"],
      download="https://github.com/peiikai/LASRecomp", copyright_text="Copyright (c) 2026 Peiikai", category="vendored-source",
      notes="Verbatim portions in scripts/recomp/runtime (see NOTICE.md). Upstream license excludes Nintendo property and "
            "third_party/ (imgui, smaa, fonts, LAS randomizer), none of which is included. "
            "The native generator adapts the analysis/lifter/emitter algorithms and preserves attribution."),

    C("stb-truetype", "stb_truetype (as shipped by Dear ImGui; on-screen keyboard text)", "1.26",
      "pkg:github/nothings/stb@stb_truetype-1.26", "MIT OR Unlicense", SHIPPED, TRACKED,
      ["scripts/recomp/runtime/third_party/stb_truetype.h", "scripts/recomp/runtime/NOTICE.md", "scripts/recomp/runtime/NOTICE.de.md"],
      download="https://github.com/nothings/stb", copyright_text="Copyright (c) 2017 Sean Barrett", category="vendored-source",
      notes="Single header, MIT or public domain at the user's choice. Rasterizes the user's own firmware fonts for the on-screen keyboard; "
            "not meant for untrusted font files."),

    C("lz4-native-codegen", "LZ4 (native generator)", "1.9.4",
      "pkg:github/lz4/lz4@v1.9.4", "BSD-2-Clause", BUILD, EXTERNAL,
      ["scripts/recomp/native-generator/vendor/lz4/LICENSE", "scripts/recomp/native-generator/vendor/lz4/source.json"],
      download="https://github.com/lz4/lz4/tree/v1.9.4", category="library",
      notes="Unchanged LZ4 C block decoder source, downloaded at build time into work/ and compiled into the standalone native generator. Only the license and the pinned per-file SHA-256 values (source.json) are tracked."),


    # Assets bundled into the installer (uncommitted installer/ directory).
    C("octicons-mark-github-16", "GitHub Octicons: mark-github-16", "unversioned (retrieved 2026-10-23)",
      "pkg:generic/octicons-mark-github-16", "MIT", SHIPPED, TRACKED,
      ["installer/assets/OCTICONS-LICENSE", "installer/assets/README.md", "installer/assets/github.svg"],
      download="https://github.com/primer/octicons", category="asset"),
    C("lucide-icons", "Lucide icons (sun, moon, monitor, laptop, tablet, smartphone)", "c32d98db",
      "pkg:generic/lucide-icons@c32d98db9b8e11ac5aa7db58d70d17b662679461", "ISC AND MIT", SHIPPED, TRACKED,
      ["installer/assets/lucide/LICENSE", "installer/assets/README.md"],
      download="https://github.com/lucide-icons/lucide", copyright_text="Copyright (c) 2026 Lucide Icons and Contributors",
      category="asset", notes="ISC for Lucide, MIT for the Feather parts (see lucide/LICENSE)."),
    C("fira-sans", "Fira Sans Regular (embedded by iced feature fira-sans)", "unversioned",
      "pkg:generic/fira-sans", "OFL-1.1", SHIPPED, TRACKED,
      ["installer/assets/FIRA-LICENSE", "installer/assets/README.md", "installer/Cargo.toml"],
      download="https://github.com/mozilla/Fira", copyright_text="Digitized data copyright (c) 2012-2015, The Mozilla Foundation and Telefonica S.A.",
      category="font", notes="Font bytes are embedded in the installer binary via the iced crate."),

    # Private Python runtime of the installer (pinned in installer/runtime/).
    C("cpython", "CPython (python-build-standalone install_only)", "3.13.15",
      "pkg:generic/cpython@3.13.15", "PSF-2.0", SHIPPED, TRACKED, ["installer/runtime/manifest.json"],
      download="https://github.com/astral-sh/python-build-standalone/releases/tag/20260901", category="runtime",
      notes="Archive SHA-256 per host: see properties. Build 20260901."),

    # Pinned build inputs (scripts). Versions are fixed in the named script lines.
    C("ffmpeg-source", "FFmpeg (pinned source build for iOS)", "9.0.2", "pkg:generic/ffmpeg@9.0.2",
      "LGPL-2.1-or-later", SHIPPED, TRACKED,
      ["scripts/recomp/ios/build_ffmpeg_ios.sh"],
      download="https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz",
      notes="Built from the pinned source by scripts/recomp/ios/build_ffmpeg_ios.sh and bundled into the iOS app; verify the "
            "configure flags for the LGPL claim. The macOS app bundles the host's FFmpeg libraries through "
            "scripts/recomp/app/bundle_dylibs.py (make_app.sh); Linux uses distribution packages."),
    C("vma", "Vulkan Memory Allocator (Linux build input)", "3.3.0", "pkg:github/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator@v3.3.0",
      "MIT", BUILD, TRACKED, ["scripts/recomp/runtime/nvn/vulkan/src/nvn/vulkan/vma.cpp"],
      download="https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator"),
    C("ghidra", "Ghidra (optional headless analysis)", "unpinned", "pkg:generic/ghidra", "Apache-2.0", OPTIONAL, TRACKED,
      ["scripts/ghidra/run_headless.sh"], download="https://github.com/NationalSecurityAgency/ghidra", notes="Not installed by the project."),

    # Local tools in tools/ (git-ignored). Used by the build, not distributed.
    C("hactool", "hactool", "1d64a83 (2023-10-10)", "pkg:github/SciresM/hactool@1d64a83450e025622f3468c28fc4164dad2c5ef6",
      "ISC", LOCAL, IGNORED, ["tools/hactool/LICENSE", "scripts/build_all.sh"],
      download="https://github.com/SciresM/hactool", copyright_text="Copyright (c) 2018, SciresM",
      notes="Cloned by scripts/build_all.sh when missing (git clone --recursive)."),
    C("mbedtls", "mbed TLS (vendored in hactool)", "2.6.1", "pkg:generic/mbedtls@2.6.1", "Apache-2.0 OR GPL-2.0-or-later",
      LOCAL, IGNORED, ["tools/hactool/mbedtls/LICENSE", "tools/hactool/config.mk"],
      download="https://github.com/Mbed-TLS/mbedtls", notes="Linked into the local hactool binary; not distributed."),
    C("cjson", "cJSON (vendored in hactool)", "unknown", "pkg:generic/cjson", "MIT", LOCAL, IGNORED,
      ["tools/hactool/cJSON.c", "tools/hactool/cJSON.h"], download="https://github.com/DaveGamble/cJSON"),
    C("lz4-c", "LZ4 C library (vendored in hactool and nx2elf)", "unknown", "pkg:generic/lz4-c", "BSD-2-Clause", LOCAL, IGNORED,
      ["tools/hactool/lz4.c", "tools/nx2elf/lz4.c"], download="https://github.com/lz4/lz4"),
    C("il2cppdumper", "Il2CppDumper", "4741d46 (2024-07-06)", "pkg:github/Perfare/Il2CppDumper@4741d46ba9cd6159c5d853eb9d6fc48b4bfa2b1a",
      "MIT", LOCAL, IGNORED, ["tools/Il2CppDumper/LICENSE", "tools/il2cppdumper-bin"],
      download="https://github.com/Perfare/Il2CppDumper", copyright_text="Copyright (c) 2016 Perfare",
      notes="Binary in tools/il2cppdumper-bin (Mach-O arm64) is built from this source."),
    C("nx2elf", "nx2elf", "unknown", "pkg:generic/nx2elf", "NOASSERTION", LOCAL, IGNORED, ["tools/nx2elf/README.md"],
      notes="No LICENSE file in the working tree. Licence unknown: needs clarification before any distribution."),
    C("vgmstream", "vgmstream", "unknown", "pkg:generic/vgmstream", "ISC", LOCAL, IGNORED, ["tools/vgmstream/src/COPYING"],
      copyright_text="Copyright (c) 2008-2025 Adam Gashlin, Fastelbja, Ronny Elfert, bnnm and others",
      notes="Bundles libogg and libvorbis (below)."),
    C("libogg", "libogg (vendored in vgmstream)", "1.3.5", "pkg:generic/libogg@1.3.5", "BSD-3-Clause", LOCAL, IGNORED,
      ["tools/vgmstream/deps/libogg-1.3.5"], download="https://xiph.org/ogg/"),
    C("libvorbis", "libvorbis (vendored in vgmstream)", "1.3.7", "pkg:generic/libvorbis@1.3.7", "BSD-3-Clause", LOCAL, IGNORED,
      ["tools/vgmstream/deps/libvorbis-1.3.7"], download="https://xiph.org/vorbis/"),
    C("fmod-libfmod", "FMOD runtime library (libfmod in fmod_toolkit)", "unknown", "pkg:generic/fmod", "LicenseRef-FMOD",
      OPTIONAL, IGNORED, ["tools/pydeps/fmod_toolkit"], copyright_text="Firelight Technologies Pty Ltd",
      notes="Binary library inside a Python wheel. Only in the shader profile (UnityPy). Proprietary license."),

    # System packages the user installs (scripts/install, docs/BUILD.md). The project does not pin their versions.
    C("xcode", "Xcode (Apple developer tools)", "26 or newer", "pkg:generic/xcode", "LicenseRef-Apple-SDK", USER, EXTERNAL,
      ["docs/BUILD.md", "install.command"], category="system-package", download="https://developer.apple.com/xcode/"),
    C("apple-frameworks", "Apple SDK frameworks used by the macOS/iOS app", "from the installed SDK",
      "pkg:generic/apple-sdk-frameworks", "LicenseRef-Apple-SDK", SHIPPED, EXTERNAL,
      ["scripts/recomp/ios/app/BDSP.xcodeproj/project.pbxproj", "scripts/recomp/app/make_app.sh"], category="system-package",
      notes="Linked, system-provided: Metal, MetalFX, AppKit, UIKit, QuartzCore, CoreText, CoreGraphics, CoreServices, ImageIO, "
            "AudioToolbox, AVFAudio, GameController, Foundation, UniformTypeIdentifiers."),
    C("homebrew", "Homebrew", "unpinned (install script)", "pkg:generic/homebrew", "BSD-2-Clause", USER, EXTERNAL,
      ["install.command"], category="system-package", download="https://brew.sh"),
    C("brew-llvm", "llvm (Homebrew)", "unpinned", "pkg:generic/llvm", "Apache-2.0 WITH LLVM-exception", USER, EXTERNAL,
      ["docs/BUILD.md", "install.command"], category="system-package", notes="The recompiler needs Homebrew clang first in PATH."),
    C("brew-sdl3", "sdl3 (Homebrew)", "unpinned", "pkg:generic/sdl3", "Zlib", USER, EXTERNAL,
      ["docs/BUILD.md", "install.command"], category="system-package", notes="Copied into the macOS app by bundle_dylibs.py."),
    C("brew-ffmpeg", "ffmpeg (Homebrew)", "unpinned", "pkg:generic/ffmpeg", "LGPL-2.1-or-later OR GPL-2.0-or-later", USER, EXTERNAL,
      ["docs/BUILD.md", "install.command"], category="system-package",
      notes="Build-dependent licence (GPL options in the Homebrew formula are common). Copied into the macOS app by bundle_dylibs.py."),
    C("pkg-config", "pkg-config (Homebrew; pkgconf on Linux)", "unpinned", "pkg:generic/pkg-config", "GPL-2.0-or-later", USER,
      EXTERNAL, ["docs/BUILD.md", "install.command", "scripts/recomp/linux/deps.sh"], category="system-package",
      notes="Linux packages it as pkgconf, licence GPL-2.0-or-later."),
    C("brew-python", "Python 3 (Homebrew)", "unpinned", "pkg:generic/python3", "PSF-2.0", USER, EXTERNAL,
      ["install.command", "scripts/build_stages.py"], category="system-package"),
    C("linux-clang", "clang / LLVM (apt clang, dnf clang, pacman clang)", "unpinned", "pkg:generic/clang", "Apache-2.0 WITH LLVM-exception",
      USER, EXTERNAL, ["install-linux.sh", "scripts/recomp/runtime/app/linux/deps.txt"], category="system-package"),
    C("linux-gcc", "GCC / g++ and build-essential (apt build-essential, dnf gcc-c++, pacman base-devel)", "unpinned", "pkg:generic/gcc",
      "GPL-3.0-or-later WITH GCC-exception-3.1", USER, EXTERNAL, ["install-linux.sh", "scripts/recomp/runtime/app/linux/deps.txt"],
      category="system-package"),
    C("linux-make", "GNU make", "unpinned", "pkg:generic/make", "GPL-3.0-or-later", USER, EXTERNAL, ["install-linux.sh"],
      category="system-package"),
    C("linux-git", "git", "unpinned", "pkg:generic/git", "GPL-2.0-only", USER, EXTERNAL, ["install-linux.sh"], category="system-package"),
    C("linux-cmake", "CMake", "unpinned", "pkg:generic/cmake", "BSD-3-Clause", USER, EXTERNAL,
      ["scripts/recomp/runtime/app/linux/deps.txt"], category="system-package"),
    C("linux-time", "GNU time (/usr/bin/time)", "unpinned", "pkg:generic/time", "GPL-3.0-or-later", USER, EXTERNAL,
      ["install-linux.sh"], category="system-package"),
    C("linux-qt6", "Qt 6 Widgets (qt6-base)", "unpinned", "pkg:generic/qt6-base", "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
      USER, EXTERNAL, ["scripts/recomp/runtime/app/linux/deps.txt", "scripts/recomp/runtime/app/linux/CMakeLists.txt"],
      category="system-package", download="https://www.qt.io",
      notes="Qt is offered under the LGPL/GPL or a commercial license. The choice is the distributor's."),
    C("linux-qt6-wayland", "Qt 6 Wayland platform plugin (qt6-wayland)", "unpinned", "pkg:generic/qt6-wayland",
      "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", USER, EXTERNAL, ["install-linux.sh"], category="system-package"),
    C("linux-vulkan", "Vulkan headers and loader (libvulkan-dev, vulkan-headers, vulkan-icd-loader)", "unpinned",
      "pkg:generic/vulkan", "Apache-2.0", USER, EXTERNAL, ["docs/BUILD.md", "scripts/recomp/linux/deps.sh"], category="system-package",
      notes="Headers are Apache-2.0 OR MIT; the loader is Apache-2.0."),
    C("linux-sdl3", "SDL3 development package (libsdl3-dev, SDL3-devel, sdl3)", "unpinned", "pkg:generic/sdl3-dev", "Zlib", USER,
      EXTERNAL, ["docs/BUILD.md"], category="system-package"),
    C("linux-shaderc", "shaderc development package", "unpinned", "pkg:generic/shaderc-dev", "Apache-2.0", USER, EXTERNAL,
      ["docs/BUILD.md"], category="system-package"),
    C("linux-vma", "Vulkan Memory Allocator headers (libvulkan-memory-allocator-dev, VulkanMemoryAllocator-devel; AUR on Arch)",
      "unpinned", "pkg:generic/vulkan-memory-allocator", "MIT", USER, EXTERNAL, ["docs/BUILD.md"], category="system-package"),
    C("linux-ffmpeg", "FFmpeg development packages (libavcodec, libavformat, libavutil)", "unpinned", "pkg:generic/ffmpeg-dev",
      "LGPL-2.1-or-later OR GPL-2.0-or-later", USER, EXTERNAL, ["docs/BUILD.md", "scripts/recomp/linux/deps.sh"],
      category="system-package", notes="Build-dependent licence."),
    C("linux-python", "Python 3 and venv (python3, python3-venv)", "unpinned", "pkg:generic/python3-linux", "PSF-2.0", USER, EXTERNAL,
      ["install-linux.sh"], category="system-package"),
    C("linux-pillow", "Pillow (python3-pil, python3-pillow, python-pillow)", "unpinned", "pkg:generic/python3-pil", "MIT-CMU", USER,
      EXTERNAL, ["install-linux.sh", "docs/BUILD.md"], category="system-package"),
]

# Known licence corrections for Python packages (the METADATA of some wheels is inconsistent).
PY_LICENSE = {
    "unicorn": "GPL-2.0-only",   # upstream README: "Distributed under free software license GPLv2"; the PyPI classifier says BSD.
    "capstone": "BSD-3-Clause",
    "lz4": "BSD-3-Clause",
    "pillow": "MIT-CMU",
    "unitypy": "MIT",
    "attrs": "MIT",
    "brotli": "MIT",
    "archspec": "Apache-2.0 OR MIT",
    "astc-encoder-py": "MIT",
    "etcpak": "MIT",
    "fmod-toolkit": "MIT",
    "pyfmodex": "MIT",
    "texture2ddecoder": "MIT",
    "tpk-ar": "MIT",
    "fsspec": "BSD-3-Clause",
}


# ---------------------------------------------------------------- helpers
def git(*args):
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.rstrip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def normalize_license(expr):
    """Turns Cargo's informal 'MIT/Apache-2.0' into the SPDX expression 'MIT OR Apache-2.0'."""
    if not expr:
        return "NOASSERTION"
    return re.sub(r"(?<=[A-Za-z0-9.+-])/(?=[A-Za-z0-9.+-])", " OR ", expr.strip())


def purl_name(name):
    return re.sub(r"[_.]", "-", name).lower()


def cargo_components(project):
    """Rust crates of one Cargo project (its Cargo.lock). Licences and dependency edges come from `cargo metadata` when it works offline."""
    lock_path = (project / "Cargo.lock").relative_to(ROOT).as_posix()
    manifest = (project / "Cargo.toml").relative_to(ROOT).as_posix()
    lock = tomllib.loads((project / "Cargo.lock").read_text(encoding="utf-8"))
    checksums = {(p["name"], p["version"]): p.get("checksum") for p in lock.get("package", []) if "source" in p}
    try:
        meta = json.loads(subprocess.run(
            ["cargo", "metadata", "--locked", "--offline", "--format-version", "1",
             "--manifest-path", str(project / "Cargo.toml")],
            capture_output=True, text=True, check=True).stdout)
    except (OSError, subprocess.CalledProcessError):
        meta = None
        print("warning: cargo metadata unavailable; Rust licences are NOASSERTION", file=sys.stderr)

    if meta is None:
        crates = [C(f"crate-{name}-{version}", name, version, f"pkg:cargo/{name}@{version}", "NOASSERTION", SHIPPED,
                    TRACKED, [lock_path], download=f"https://crates.io/crates/{name}/{version}",
                    category="rust-crate", sha256=checksum)
                  for (name, version), checksum in checksums.items()]
        return crates, {}, None

    root_pkg = next(p for p in meta["packages"] if Path(p["manifest_path"]) == project / "Cargo.toml")
    purl_of = {p["id"]: f"pkg:cargo/{p['name']}@{p['version']}" for p in meta["packages"] if p["id"] != root_pkg["id"]}
    crates = []
    for pkg in meta["packages"]:
        if pkg["id"] == root_pkg["id"]:
            continue
        vendored = pkg["source"] is None
        location = Path(pkg["manifest_path"]).parent.relative_to(ROOT).as_posix() if vendored else lock_path
        crates.append(C(f"crate-{pkg['name']}-{pkg['version']}", pkg["name"], pkg["version"], purl_of[pkg["id"]],
                        normalize_license(pkg.get("license")), SHIPPED, TRACKED, [location],
                        download=f"https://crates.io/crates/{pkg['name']}/{pkg['version']}", category="rust-crate",
                        sha256=checksums.get((pkg["name"], pkg["version"])),
                        notes=(f"Repository: {pkg['repository']}" if pkg.get("repository") else "")
                        + ("; locally patched source; see PATCHES.md in the component directory." if vendored else "")))
    edges = {}
    for node in meta["resolve"]["nodes"]:
        if node["id"] in purl_of:
            edges[purl_of[node["id"]]] = [purl_of[d] for d in node["dependencies"] if d in purl_of]
    root = C("installer" if project.name == "installer" else project.name, root_pkg["name"], root_pkg["version"],
             f"pkg:cargo/{root_pkg['name']}@{root_pkg['version']}", normalize_license(root_pkg.get("license")) or "MIT",
             SHIPPED, TRACKED, [manifest, lock_path], category="application",
             notes=root_pkg.get("description") or "")
    root["depends_on"] = [purl_of[d] for d in next(n for n in meta["resolve"]["nodes"]
                                                    if n["id"] == root_pkg["id"])["dependencies"] if d in purl_of]
    return crates, edges, root


# Windows components: what the CI archive contains, read from the lock files the CI resolved on the day.
def windows_components(folder):
    """Components of the Windows components from the resolved lock files (windows-dependencies.json,
    windows-sources.json, qt.json) in `folder`."""
    folder = Path(folder)
    contract = json.loads((folder / "windows-dependencies.json").read_text(encoding="utf-8"))
    sources = json.loads((folder / "windows-sources.json").read_text(encoding="utf-8"))
    qt = json.loads((folder / "qt.json").read_text(encoding="utf-8")) if (folder / "qt.json").is_file() else {}
    versions = {"qt": qt.get("qt"), "llvm-mingw": qt.get("toolchain_version")}
    note = "Windows components archive (windows-components.yml)."
    result = []

    def register(expr, text):
        for ref in re.findall(r"LicenseRef-[A-Za-z0-9.-]+", expr):
            LICENSE_REFS.setdefault(ref, (ref.removeprefix("LicenseRef-").replace("-", " "), text))

    for item in contract["components"]:
        version = item.get("version") or versions.get(item["id"]) or "rolling"
        register(item["license"], item.get("qualification", ""))
        artifacts = item.get("artifacts") or []
        sha = (artifacts[0].get("sha256") if artifacts else None) or item.get("source_archive", {}).get("sha256")
        result.append(C(f"win-{item['id']}", item["id"], version, f"pkg:generic/windows-{item['id']}@{version}",
                        item["license"], SHIPPED, EXTERNAL, ["installer/assets/windows-dependencies.json"],
                        download=item.get("source"), category="build-environment", sha256=sha, notes=note))
    for name, entry in sources["sources"].items():
        expr = entry.get("license", "NOASSERTION")
        register(expr, f"Licence of the {name} sources as shipped in the build environment.")
        revision = entry.get("revision") or "unknown"
        result.append(C(f"win-src-{name}", name, entry.get("version") or revision, f"pkg:github/{entry['repository']}@{revision}",
                        expr, SHIPPED, EXTERNAL, ["installer/assets/windows-sources.json"],
                        download="https://github.com/" + entry["repository"], category="build-environment",
                        sha256=entry.get("sha256"), notes=note + " Built from source."))
    return result


def python_runtime_wheels(installer, filename="wheels.lock.json"):
    """Pinned wheels of the private runtime (installer/runtime/wheels.lock.json)."""
    lock = json.loads((installer / "runtime" / filename).read_text(encoding="utf-8"))
    found = {}
    for target, pins in lock["targets"].items():
        for spec, info in pins.items():
            name, version = spec.split("==")
            found.setdefault((name, version), {})[target] = info["sha256"]
    return found


def pydeps_metadata(pyd):
    """Name, version and runtime requirements from tools/pydeps/*.dist-info/METADATA."""
    result = []
    for dist in sorted(pyd.glob("*.dist-info")):
        fields = {"requires": []}
        for line in (dist / "METADATA").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name: ") and "name" not in fields:
                fields["name"] = line[6:].strip()
            elif line.startswith("Version: ") and "version" not in fields:
                fields["version"] = line[9:].strip()
            elif line.startswith("Requires-Dist: ") and "extra ==" not in line:
                fields["requires"].append(re.split(r"[ ;<>=!~\[(]", line[15:].strip())[0])
            elif line == "":
                break
        result.append(fields)
    return result


def merge_notes(*parts):
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------- assemble
def build_components(windows_inputs=None):
    purls = [c["purl"] for c in CATALOG]
    duplicates = sorted({p for p in purls if purls.count(p) > 1})
    if duplicates:
        raise SystemExit("duplicate purl in CATALOG: " + ", ".join(duplicates))
    components = {c["purl"]: c for c in CATALOG}

    for project in (ROOT / "installer", ROOT / "installer" / "extract"):
        crates, crate_edges, root = cargo_components(project)
        for c in crates:
            components.setdefault(c["purl"], c)
        for purl, deps in crate_edges.items():
            components[purl]["depends_on"] = sorted(set(components[purl]["depends_on"]) | set(deps))
        if root is not None:
            components[root["purl"]] = root
    if windows_inputs:
        for c in windows_components(windows_inputs):
            components[c["purl"]] = c

    # Pinned wheels of the installer's private runtime (shipped).
    for (name, version), per_target in python_runtime_wheels(ROOT / "installer").items():
        key = purl_name(name)
        purl = f"pkg:pypi/{key}@{version}"
        hashes = "; ".join(f"wheel sha256 {t}: {h}" for t, h in sorted(per_target.items()))
        if purl in components:
            comp = components[purl]
            comp["distribution"], comp["tracked"] = SHIPPED, TRACKED
            comp["evidence"] = sorted(set(comp["evidence"]) | {"installer/runtime/wheels.lock.json"})
            comp["notes"] = merge_notes(comp["notes"], "Installer runtime (base profile).", hashes)
        else:
            components[purl] = C(f"py-{key}", name, version, purl, PY_LICENSE.get(key, "NOASSERTION"), SHIPPED, TRACKED,
                                 ["installer/runtime/wheels.lock.json"], download=f"https://pypi.org/project/{name}/{version}/",
                                 category="python-package", notes=merge_notes("Installer runtime (base profile).", hashes))

    # Locally installed packages (git-ignored tools/pydeps); skipped when absent.
    pyd = ROOT / "tools" / "pydeps"
    if pyd.is_dir():
        for fields in pydeps_metadata(pyd):
            key = purl_name(fields["name"])
            purl = f"pkg:pypi/{key}@{fields['version']}"
            note = "Local build environment (tools/pydeps, git-ignored). The shader profile uses UnityPy."
            if purl in components:
                comp = components[purl]
                comp["notes"] = merge_notes(comp["notes"], note)
                comp["evidence"] = sorted(set(comp["evidence"]) | {"tools/pydeps"})
            else:
                components[purl] = C(f"py-{key}", fields["name"], fields["version"], purl, PY_LICENSE.get(key, "NOASSERTION"),
                                     BUILD, IGNORED, ["tools/pydeps"], category="python-package", notes=note)
            components[purl]["requires"] = fields["requires"]

    py_by_name = {purl_name(c["name"]): c["purl"] for c in components.values() if c["category"] == "python-package"}
    for comp in components.values():
        for dep in comp.get("requires", []):
            target = py_by_name.get(purl_name(dep))
            if target and target not in comp["depends_on"]:
                comp["depends_on"].append(target)

    if "pkg:pypi/unicorn@2.1.4" in components:
        comp = components["pkg:pypi/unicorn@2.1.4"]
        comp["notes"] = merge_notes(comp["notes"], "Retained production payload is the Unicorn 2.1.4 C shared library and headers. "
                                                   "The native generator links this library directly; Python bindings are removed during runtime assembly. "
                                                   "GPL-2.0-only follows upstream's GPLv2 declaration despite the wheel's BSD classifier.")
        comp["evidence"] = sorted(set(comp["evidence"]) | {"installer/scripts/assemble_runtime.py", "scripts/recomp/native-generator/NOTICE.md"})
    return components


def root_component():
    short = git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = git("status", "--porcelain").splitlines()
    return {
        "name": "strahlender-xnu",
        "version": short + ("-dirty" if dirty else ""),
        "commit": git("rev-parse", "HEAD") or "unknown",
        "dirty": [line[3:] for line in dirty],
    }


PURPOSE = {"runtime": "APPLICATION", "application": "APPLICATION", "vendored-source": "SOURCE",
           "asset": "FILE", "font": "FILE"}
CDX_TYPE = {"runtime": "platform", "application": "application", "asset": "file", "font": "file"}


def write_outputs(out, components, root):
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc_uuid = uuid.uuid5(uuid.NAMESPACE_URL, "strahlender-xnu|" + root["commit"] + "|" + "|".join(root["dirty"]))
    state = ("Uncommitted files at generation: " + ", ".join(root["dirty"]) + ".") if root["dirty"] else \
        "Clean working tree at generation."
    comps = sorted(components.values(), key=lambda c: (c["category"], c["name"].lower()))
    ids = {c["purl"]: "SPDXRef-" + re.sub(r"[^A-Za-z0-9.-]+", "-", c["id"]).strip("-") for c in comps}
    root_id = "SPDXRef-" + root["name"]
    referenced = {d for c in comps for d in c["depends_on"]}
    top_level = [c["purl"] for c in comps if c["purl"] not in referenced]
    used_refs = sorted({ref for c in comps for ref in re.findall(r"LicenseRef-[A-Za-z0-9.-]+", c["license"])})

    # ---------------- SPDX 2.3 JSON
    packages = [{
        "SPDXID": root_id, "name": root["name"], "versionInfo": root["version"], "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False, "licenseConcluded": "NOASSERTION", "licenseDeclared": "MIT",
        "copyrightText": "Copyright (c) 2026 Veemyu", "primaryPackagePurpose": "APPLICATION",
        "comment": f"Repository commit {root['commit']}. {state}",
    }]
    for c in comps:
        pkg = {
            "SPDXID": ids[c["purl"]], "name": c["name"], "versionInfo": c["version"],
            "downloadLocation": c["download"] or "NOASSERTION", "filesAnalyzed": False,
            "licenseConcluded": CONCLUDED.get(c["name"].lower(), "NOASSERTION"), "licenseDeclared": c["license"],
            "copyrightText": c["copyright"] or "NOASSERTION",
            "primaryPackagePurpose": PURPOSE.get(c["category"], "LIBRARY"),
            "comment": merge_notes(f"Distribution: {c['distribution']}. Repository state: {c['tracked']}.",
                                   ("Evidence: " + ", ".join(c["evidence"]) + ".") if c["evidence"] else "", c["notes"]),
            "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": c["purl"]}],
        }
        if c.get("sha256"):
            pkg["checksums"] = [{"algorithm": "SHA256", "checksumValue": c["sha256"]}]
        packages.append(pkg)

    relationships = [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": root_id}]
    relationships += [{"spdxElementId": root_id, "relationshipType": "DEPENDS_ON", "relatedSpdxElement": ids[p]}
                      for p in top_level]
    for c in comps:
        relationships += [{"spdxElementId": ids[c["purl"]], "relationshipType": "DEPENDS_ON", "relatedSpdxElement": ids[d]}
                          for d in c["depends_on"]]

    spdx = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{root['name']} {root['version']} SBOM",
        "documentNamespace": f"https://spdx.org/spdxdocs/{root['name']}-{doc_uuid}",
        "creationInfo": {"created": now, "creators": ["Tool: " + TOOL]},
        "documentDescribes": [root_id], "packages": packages, "relationships": relationships,
    }
    if used_refs:
        spdx["hasExtractedLicensingInfos"] = [
            {"licenseId": ref, "name": LICENSE_REFS[ref][0], "extractedText": LICENSE_REFS[ref][1]} for ref in used_refs]
    (out / "sbom-strahlender-xnu.spdx.json").write_text(json.dumps(spdx, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---------------- SPDX 2.3 tag-value
    lines = ["SPDXVersion: SPDX-2.3", "DataLicense: CC0-1.0", "SPDXID: SPDXRef-DOCUMENT",
             f"DocumentName: {spdx['name']}", f"DocumentNamespace: {spdx['documentNamespace']}",
             f"Creator: Tool: {TOOL}", f"Created: {now}", ""]
    for ref in used_refs:
        lines += [f"LicenseID: {ref}", f"LicenseName: {LICENSE_REFS[ref][0]}",
                  f"ExtractedText: <text>{LICENSE_REFS[ref][1]}</text>", ""]
    for pkg in packages:
        lines += [f"PackageName: {pkg['name']}", f"SPDXID: {pkg['SPDXID']}", f"PackageVersion: {pkg['versionInfo']}",
                  f"PackageDownloadLocation: {pkg['downloadLocation']}", "FilesAnalyzed: false",
                  f"PackageLicenseConcluded: {pkg['licenseConcluded']}", f"PackageLicenseDeclared: {pkg['licenseDeclared']}",
                  f"PackageCopyrightText: <text>{pkg['copyrightText']}</text>",
                  f"PrimaryPackagePurpose: {pkg['primaryPackagePurpose']}"]
        lines += [f"ExternalRef: PACKAGE-MANAGER purl {ref['referenceLocator']}" for ref in pkg.get("externalRefs", [])]
        lines += [f"PackageChecksum: SHA256: {chk['checksumValue']}" for chk in pkg.get("checksums", [])]
        lines += [f"PackageComment: <text>{pkg['comment']}</text>", ""]
    lines += [f"Relationship: {rel['spdxElementId']} {rel['relationshipType']} {rel['relatedSpdxElement']}"
              for rel in relationships]
    (out / "sbom-strahlender-xnu.spdx").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------- CycloneDX 1.6 JSON
    cdx_components = []
    for c in comps:
        lic = c["license"]
        if lic == "NOASSERTION":
            licenses = []
        elif lic in LICENSE_REFS:
            licenses = [{"license": {"name": LICENSE_REFS[lic][0]}}]
        else:
            licenses = [{"expression": lic}]
        comp = {
            "type": CDX_TYPE.get(c["category"], "library"), "bom-ref": c["purl"], "name": c["name"],
            "version": c["version"], "purl": c["purl"],
            "scope": "required" if c["distribution"] == SHIPPED else "optional",
            "licenses": licenses,
            "properties": [
                {"name": "bdsp:category", "value": c["category"]},
                {"name": "bdsp:distribution", "value": c["distribution"]},
                {"name": "bdsp:repository-state", "value": c["tracked"]},
                {"name": "bdsp:evidence", "value": ", ".join(c["evidence"])},
            ],
        }
        if c["download"]:
            comp["externalReferences"] = [{"type": "distribution", "url": c["download"]}]
        if c["copyright"]:
            comp["copyright"] = c["copyright"]
        if c.get("sha256"):
            comp["hashes"] = [{"alg": "SHA-256", "content": c["sha256"]}]
        if c["notes"]:
            comp["description"] = c["notes"]
        cdx_components.append(comp)
    cdx_dependencies = [{"ref": "root", "dependsOn": top_level}]
    cdx_dependencies += [{"ref": c["purl"], "dependsOn": c["depends_on"]} for c in comps]
    cdx = {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": f"urn:uuid:{doc_uuid}", "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": {"components": [{"type": "application", "name": "generate_sbom.py"}]},
            "component": {"type": "application", "bom-ref": "root", "name": root["name"], "version": root["version"],
                          "licenses": [{"license": {"id": "MIT"}}],
                          "description": f"Repository commit {root['commit']}. {state}"},
        },
        "components": cdx_components, "dependencies": cdx_dependencies,
    }
    (out / "sbom-strahlender-xnu.cdx.json").write_text(json.dumps(cdx, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---------------- CSV
    with (out / "sbom-strahlender-xnu.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "name", "version", "category", "distribution", "repository_state", "license", "purl",
                         "download", "sha256", "evidence", "notes"])
        for c in comps:
            writer.writerow([c["id"], c["name"], c["version"], c["category"], c["distribution"], c["tracked"], c["license"],
                             c["purl"], c["download"] or "", c.get("sha256") or "", "; ".join(c["evidence"]), c["notes"]])
    return len(comps)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "sbom"), help="output directory (default: sbom/)")
    parser.add_argument("--windows-inputs", help="folder with the lock files the Windows build-environment CI resolved")
    args = parser.parse_args(argv)
    count = write_outputs(Path(args.out), build_components(args.windows_inputs), root_component())
    print(f"{count} components written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
