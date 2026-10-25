#!/usr/bin/env python3
"""Build/cache the standalone C tool; Python never processes module instructions.

The compile command is an argv list, including paths with spaces and apostrophes.
No CMake, pkg-config, pip, or network access is required for this milestone.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def build(output, compiler=None, sanitize=False):
    compiler = compiler or os.environ.get("CC") or ("clang" if shutil.which("clang") else "cc")
    resolved = shutil.which(compiler)
    if not resolved:
        raise ValueError("C compiler is missing: " + compiler)
    identity = subprocess.run([resolved, "--version"], check=True, capture_output=True).stdout
    vendor = HERE / "vendor/lz4"
    provenance = json.loads((vendor / "source.json").read_text())
    for name, expected in provenance["files"].items():
        if Path(name).name != name or hashlib.sha256((vendor / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Vendored LZ4 source checksum mismatch: " + name)
    sources = sorted((HERE / "src").glob("*.c")) + [HERE / "vendor/lz4/lz4.c"]
    inputs = sorted((HERE / "src").glob("*.h")) + sources + sorted((HERE / "vendor/lz4").glob("*.h"))
    fingerprint = hashlib.sha256()
    for path in [Path(__file__).resolve(), vendor / "source.json", *inputs]:
        fingerprint.update(path.relative_to(HERE).as_posix().encode() + b"\0" + path.read_bytes())
    fingerprint.update(identity)
    fingerprint.update(str(sanitize).encode())
    digest = fingerprint.hexdigest()
    output = output.resolve()
    metadata = output.with_suffix(output.suffix + ".json")
    if output.is_file() and metadata.is_file():
        record = json.loads(metadata.read_text())
        if record.get("source_hash") == digest and record.get("binary_sha256") == hashlib.sha256(output.read_bytes()).hexdigest():
            return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codegen-build-", dir=output.parent) as temporary:
        candidate = Path(temporary) / output.name
        flags = ["-std=c17", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-Wconversion",
                 "-Wno-sign-conversion", f"-ffile-prefix-map={ROOT}=.", "-I", str(HERE / "src"), "-I", str(HERE / "vendor/lz4"),
                 f'-DBDSP_CODEGEN_SOURCE_HASH="{digest}"']
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        if sys.platform == "win32":
            flags += ["-municode"]
        subprocess.run([resolved, *flags, *(str(p) for p in sources), "-o", str(candidate)], check=True)
        record = {"schema": 1, "source_hash": digest,
                  "binary_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
        os.replace(candidate, output)
        marker = Path(temporary) / "build.json"
        marker.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        os.replace(marker, metadata)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work/native-generator/bdsp_codegen")
    parser.add_argument("--cc")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    try:
        print(build(args.output, args.cc, args.sanitize))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Native generator build failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
