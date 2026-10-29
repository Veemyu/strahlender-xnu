#!/usr/bin/env python3
"""Build/cache the standalone C tool; Python never processes module instructions.

The compile command is an argv list, including paths with spaces and apostrophes.
No CMake, pkg-config or pip is required. The pinned LZ4 sources are downloaded once
into ignored work/ and checked against vendor/lz4/source.json (or taken from --lz4-root).
"""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def unicorn_dependency(explicit=None):
    location = explicit or os.environ.get("BDSP_UNICORN_ROOT")
    if not location:
        spec = importlib.util.find_spec("unicorn")
        if spec and spec.submodule_search_locations:
            location = next(iter(spec.submodule_search_locations))
    if not location:
        # The documented dev setup (docs/BUILD.md): pip install --target tools/pydeps unicorn==2.1.4, without PYTHONPATH.
        bundled = Path(os.environ.get("TOOLS_DIR") or ROOT / "tools") / "pydeps/unicorn"
        if (bundled / "include/unicorn/unicorn.h").is_file():
            location = str(bundled)
    if not location:
        return None
    root = Path(location).resolve()
    header = root / "include/unicorn/unicorn.h"
    if not header.is_file():
        raise ValueError("Unicorn C headers are missing")
    text = header.read_text()
    for name, value in (("MAJOR", 2), ("MINOR", 1), ("PATCH", 4)):
        if f"#define UC_API_{name} {value}" not in text:
            raise ValueError("Native generator requires Unicorn 2.1.4 headers")
    names = ["unicorn.dll", "libunicorn.dll"] if sys.platform == "win32" else ["libunicorn.2.dylib"] if sys.platform == "darwin" else ["libunicorn.so.2"]
    library = next((root / "lib" / n for n in names if (root / "lib" / n).is_file()), None)
    if not library:
        raise ValueError("Unicorn 2.1.4 shared library is missing for this host")
    digest = hashlib.sha256()
    for path in sorted((root / "include/unicorn").glob("*.h")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    sha = hashlib.sha256(library.read_bytes()).hexdigest()
    digest.update(sha.encode())
    return {"root": root, "library": library, "sha256": sha, "fingerprint": digest.hexdigest()}


def download(url):
    """Fetch bytes; python.org builds on macOS may lack CA certificates, so fall back to curl.

    The caller checks the pinned SHA-256, so the transport is never trusted for content.
    """
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except OSError as error:
        curl = shutil.which("curl")
        if not curl:
            raise ValueError("Cannot download " + url + ": " + str(error))
        return subprocess.run([curl, "-fsSL", "--max-time", "60", url], check=True, capture_output=True).stdout


def lz4_dependency(explicit=None):
    """Directory with the pinned lz4.c/lz4.h; only the pin and LICENSE live in the repo."""
    pin = HERE / "vendor/lz4/source.json"
    provenance = json.loads(pin.read_text())
    location = explicit or os.environ.get("BDSP_LZ4_ROOT")
    root = Path(location).resolve() if location else ROOT / "work/native-generator/deps" / ("lz4-" + provenance["version"])
    for name in ("lz4.c", "lz4.h"):
        expected = provenance["files"][name]
        path = root / name
        if not path.is_file():
            if location:
                raise ValueError("LZ4 source is missing: " + str(path))
            data = download(provenance["url"].format(name=name))
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Downloaded LZ4 source checksum mismatch: " + name)
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as handle:
                handle.write(data)
            os.replace(handle.name, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("LZ4 source checksum mismatch: " + str(path))
    return root


def build(output, compiler=None, sanitize=False, unicorn_root=None, require_unicorn=False, lz4_root=None):
    compiler = compiler or os.environ.get("CC") or ("clang" if shutil.which("clang") else "cc")
    resolved = shutil.which(compiler)
    if not resolved:
        raise ValueError("C compiler is missing: " + compiler)
    dependency = unicorn_dependency(unicorn_root)
    if require_unicorn and not dependency:
        raise ValueError("Unicorn 2.1.4 native library and C headers are required; use the private installer runtime or BDSP_UNICORN_ROOT")
    identity = subprocess.run([resolved, "--version"], check=True, capture_output=True).stdout
    lz4 = lz4_dependency(lz4_root)
    sources = sorted((HERE / "src").glob("*.c")) + [lz4 / "lz4.c"]
    inputs = sorted((HERE / "src").glob("*.h")) + sorted((HERE / "src").glob("*.c"))
    fingerprint = hashlib.sha256()
    for path in [Path(__file__).resolve(), HERE / "vendor/lz4/source.json", *inputs]:
        fingerprint.update(path.relative_to(HERE).as_posix().encode() + b"\0" + path.read_bytes())
    fingerprint.update((dependency["fingerprint"] if dependency else "without-unicorn").encode())
    fingerprint.update(identity)
    fingerprint.update(str(sanitize).encode())
    fingerprint.update(output.name.encode())
    digest = fingerprint.hexdigest()
    output = output.resolve()
    metadata = output.with_suffix(output.suffix + ".json")
    dep_target = (output.parent if sys.platform == "win32" else output.parent / (output.name + ".deps")) / dependency["library"].name if dependency else None
    dependency_valid = not dependency or (dep_target.is_file() and hashlib.sha256(dep_target.read_bytes()).hexdigest() == dependency["sha256"])
    if output.is_file() and metadata.is_file():
        try:
            record = json.loads(metadata.read_text())
        except (ValueError, OSError):
            record = {}
        if isinstance(record, dict) and dependency_valid and record.get("source_hash") == digest and record.get("binary_sha256") == hashlib.sha256(output.read_bytes()).hexdigest():
            return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codegen-build-", dir=output.parent) as temporary:
        candidate = Path(temporary) / output.name
        flags = ["-std=c17", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-Wconversion",
                 "-Wno-sign-conversion", f"-ffile-prefix-map={Path.home()}=/build", f"-ffile-prefix-map={ROOT}=.", "-I", str(HERE / "src"), "-I", str(lz4),
                 f'-DBDSP_CODEGEN_SOURCE_HASH="{digest}"']
        if sys.platform != "win32":
            flags += ["-pthread"]
        libraries = []
        if dependency:
            flags += ["-DBDSP_WITH_UNICORN=1", "-I", str(dependency["root"] / "include")]
            if sys.platform == "win32":
                windows_import = dependency["root"] / "lib/unicorn.lib"
                libraries = [str(windows_import if windows_import.is_file() else dependency["library"])]
            else:
                libraries = [str(dependency["library"])]
                prefix = "@loader_path" if sys.platform == "darwin" else "$ORIGIN"
                libraries += [f"-Wl,-rpath,{prefix}/{output.name}.deps"]
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        if sys.platform == "win32":
            flags += ["-municode"]
        subprocess.run([resolved, *flags, *(str(p) for p in sources), *libraries, "-o", str(candidate)], check=True)
        record = {"schema": 1, "source_hash": digest,
                  "binary_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
        if dependency:
            dep_target.parent.mkdir(parents=True, exist_ok=True)
            copy = Path(temporary) / dependency["library"].name
            shutil.copyfile(dependency["library"], copy)
            os.replace(copy, dep_target)
            record["unicorn"] = {"version": "2.1.4", "library": dep_target.relative_to(output.parent).as_posix(), "sha256": dependency["sha256"]}
        os.replace(candidate, output)
        marker = Path(temporary) / "build.json"
        marker.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        os.replace(marker, metadata)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work/native-generator/bdsp_codegen")
    parser.add_argument("--cc")
    parser.add_argument("--unicorn-root", type=Path, help="Pinned Unicorn package root containing include/ and lib/")
    parser.add_argument("--lz4-root", type=Path, help="Directory with the pinned lz4.c and lz4.h (default: download into work/)")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--require-unicorn", action="store_true", help="Require the native engine for the complete generator")
    parser.add_argument("--check-unicorn", action="store_true", help="Validate native engine assets without compiling or importing its Python binding")
    args = parser.parse_args()
    try:
        if args.check_unicorn:
            if not unicorn_dependency(args.unicorn_root):
                raise ValueError("Unicorn 2.1.4 C headers and shared library are missing")
            print('{"unicorn":"2.1.4","native_assets":true}')
            return
        print(build(args.output, args.cc, args.sanitize, args.unicorn_root, args.require_unicorn, args.lz4_root))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Native generator build failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
