#!/usr/bin/env python3
"""Compare the native image pipeline against a frozen Git reference.

Only user-specified inputs are read; all snapshots, logs and results go to --out.
The reference is extracted from Git, never fetched or silently updated.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCE = "a26bc12e4188fb69d6cd96f3271a07bfc9e475ab"


def snapshot(output, revision=REFERENCE):
    paths = ("scripts/recomp/mkimg.py", "scripts/recomp/eh_gen.py", "scripts/recomp/eh_lsda.py",
             *("scripts/recomp/upstream/generator/" + name for name in
               ("nso.py", "gen.py", "lifter.py", "simd_c.py", "analyze.py", "patches.py")))
    source = output / "reference-source"
    for name in paths:
        data = subprocess.run(["git", "show", revision + ":" + name], cwd=ROOT,
                              check=True, capture_output=True).stdout
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return source


def tree(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def compare_images(exefs, output, binary, layout="macos", reference=REFERENCE):
    exefs, output, binary = exefs.resolve(), output.resolve(), binary.resolve()
    if output.exists():
        raise ValueError("Comparison output must be a new directory; existing data is preserved")
    # Never put comparison output within the input tree.
    if output == exefs or exefs in output.parents:
        raise ValueError("Comparison output must be separate from the ExeFS input")
    offsets = {"main": 0, "sdk": 0x6000000, "subsdk0": 0x7000000, "subsdk1": 0x5708000}
    origin = 0x7000000000
    if layout in ("compact", "compact-a"):
        offsets = {"main": 0x1000000, "sdk": 0x7000000, "subsdk0": 0x8000000, "subsdk1": 0x6708000}
        origin = 0x800000000 if layout == "compact-a" else 0
    modules = ["main", "sdk", "subsdk0"]
    if (exefs / "subsdk1").is_file():
        modules.append("subsdk1")
    for name in modules:
        if not (exefs / name).is_file():
            raise ValueError("Missing ExeFS module: " + name)
    output.mkdir(parents=True)
    source = snapshot(output, reference)
    env = dict(os.environ)
    if os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") != "1":
        env["PYTHONPATH"] = str(ROOT / "tools/pydeps") + os.pathsep + env.get("PYTHONPATH", "")
    results = {}
    for mode in ("reference", "native"):
        target = output / mode
        target.mkdir()
        links = [value for name in modules for value in ("--link", str(target / (name + ".syms.json")))]
        prefix = [str(binary), "image"] if mode == "native" else [sys.executable, str(source / "scripts/recomp/mkimg.py")]
        start = time.perf_counter()
        with (output / (mode + ".log")).open("w") as log:
            for phase in range(2):
                (target / "hle.txt").unlink(missing_ok=True)
                for name in modules:
                    command = [*prefix, str(exefs / name), name, "--base", hex(origin + offsets[name]), "--out", str(target)]
                    if layout != "macos":
                        command += ["--hle-base", hex(origin + 0xa000000)]
                    if phase:
                        command += [*links, "--interpose-from", str(target / "main.syms.json")]
                        command += ["--hle-list", str(ROOT / "scripts/recomp/rt-bdsp/hle_nvn.txt")]
                    subprocess.run(command, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
        results[mode] = {"seconds": round(time.perf_counter() - start, 3), "files": tree(target)}
    left, right = results["reference"]["files"], results["native"]["files"]
    different = sorted(name for name in left.keys() | right.keys() if left.get(name) != right.get(name))
    record = {"schema": 1, "reference_revision": reference, "layout": layout,
              "modules": modules, "equal": not different, "different": different, "results": results}
    (output / "comparison.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if different:
        raise ValueError("Native/reference outputs differ: " + ", ".join(different))
    return record


def compare_analysis(exefs, output, binary, layout="macos", reference=REFERENCE):
    exefs, output, binary = exefs.resolve(), output.resolve(), binary.resolve()
    if output.exists() or output == exefs or exefs in output.parents:
        raise ValueError("Analysis output must be a new directory separate from ExeFS")
    output.mkdir(parents=True)
    source = snapshot(output, reference)
    offsets = {"main": 0, "sdk": 0x6000000, "subsdk0": 0x7000000, "rtld": 0x8000000, "subsdk1": 0x5708000}
    origin = 0x7000000000
    if layout != "macos":
        offsets = {"main": 0x1000000, "sdk": 0x7000000, "subsdk0": 0x8000000, "rtld": 0x9000000, "subsdk1": 0x6708000}
        origin = 0x800000000 if layout == "compact-a" else 0
    record = {"schema": 1, "reference_revision": reference, "layout": layout, "equal": True, "modules": {}}
    for name in ("rtld", "main", "sdk", "subsdk0", "subsdk1"):
        if not (exefs / name).is_file():
            if name == "subsdk1":
                continue
            raise ValueError("Missing ExeFS module: " + name)
        common = [str(exefs / name), name, "--base", hex(origin + offsets[name])]
        if (exefs / (name + ".entries")).is_file():
            common += ["--entry-offsets", str(exefs / (name + ".entries"))]
        commands = {"native": [str(binary), "inspect", *common],
                    "reference": [sys.executable, str(HERE / "reference_analysis.py"), "--reference", str(source), *common]}
        values = {}
        for mode, command in commands.items():
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            (output / (name + "-" + mode + ".json")).write_text(result.stdout)
            (output / (name + "-" + mode + ".log")).write_text(result.stderr)
            values[mode] = json.loads(result.stdout)
        equal = values["native"] == values["reference"]
        record["modules"][name] = {"equal": equal, "counts": {key: len(value) if isinstance(value, list) else value for key, value in values["native"].items()}}
        record["equal"] &= equal
    (output / "comparison.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not record["equal"]:
        raise ValueError("Initial native/reference analysis differs; see comparison JSON")
    return record


def compare_generation(exefs, output, binary, layout="macos", reference=REFERENCE, simd="asm", jobs="auto"):
    exefs, output, binary = exefs.resolve(), output.resolve(), binary.resolve()
    if output.exists() or output == exefs or exefs in output.parents:
        raise ValueError("Generation output must be a new directory separate from ExeFS")
    modules = ["rtld", "main", "sdk", "subsdk0"]
    if (exefs / "subsdk1").is_file():
        modules.append("subsdk1")
    for module in modules:
        if not (exefs / module).is_file():
            raise ValueError("Missing ExeFS module: " + module)
    offsets = dict(main=0, sdk=0x6000000, subsdk0=0x7000000, rtld=0x8000000, subsdk1=0x5708000)
    origin = 0x7000000000
    if layout != "macos":
        offsets = dict(main=0x1000000, sdk=0x7000000, subsdk0=0x8000000, rtld=0x9000000, subsdk1=0x6708000)
        origin = 0x800000000 if layout == "compact-a" else 0
    output.mkdir(parents=True)
    source = snapshot(output, reference)
    record = dict(schema=1, reference_revision=reference, layout=layout, simd=simd, jobs=jobs, equal=True, modules={})
    for module in modules:
        values = {}
        for mode in ("reference", "native"):
            target = output / mode / module
            prefix = [str(binary)] if mode == "native" else [sys.executable, str(source / "scripts/recomp/eh_gen.py"),
                      "--las-dir", str(source / "scripts/recomp/upstream/generator")]
            command = [*prefix, "gen", module, str(exefs / module), hex(origin + offsets[module]), str(target), "--simd", simd]
            if (exefs / (module + ".entries")).is_file():
                command += ["--entry-offsets", str(exefs / (module + ".entries"))]
            if mode == "native":
                command += ["--jobs", jobs]
            start = time.perf_counter()
            with (output / (module + "-" + mode + ".log")).open("w") as log:
                subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
            elapsed = round(time.perf_counter() - start, 3)
            values[mode] = dict(seconds=elapsed, files=tree(target))
        left, right = values["reference"]["files"], values["native"]["files"]
        different = sorted(name for name in left.keys() | right.keys() if left.get(name) != right.get(name))
        record["modules"][module] = dict(equal=not different, different=different, results=values)
        record["equal"] &= not different
        (output / "comparison.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(json.dumps(dict(module=module, equal=not different, files=len(left),
                              reference_seconds=values["reference"]["seconds"], native_seconds=values["native"]["seconds"])), flush=True)
        if different:
            raise ValueError("Native/reference generation differs for " + module + ": " + ", ".join(different[:10]))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exefs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--layout", choices=("macos", "compact", "compact-a"), default="macos")
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--stage", choices=("images", "analysis", "generate"), default="images")
    parser.add_argument("--simd", choices=("asm", "c"), default="asm")
    parser.add_argument("--jobs", default="auto")
    args = parser.parse_args()
    try:
        function = {"images": compare_images, "analysis": compare_analysis, "generate": compare_generation}[args.stage]
        extra = (args.simd, args.jobs) if args.stage == "generate" else ()
        record = function(args.exefs, args.out, args.native, args.layout, args.reference, *extra)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Image comparison failed: " + str(error) + "\n")
    if args.stage in ("analysis", "generate"):
        print(json.dumps({"equal": record["equal"], "modules": list(record["modules"])}))
        return
    print(json.dumps({"equal": record["equal"], "modules": record["modules"],
                      "reference_seconds": record["results"]["reference"]["seconds"],
                      "native_seconds": record["results"]["native"]["seconds"]}))


if __name__ == "__main__":
    main()
