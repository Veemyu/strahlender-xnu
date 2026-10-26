#!/usr/bin/env python3
"""Stage logic for scripts/build_all.sh (selection, markers with input hashes, preflight).

Standard library only. Never prints key material, team IDs or game content; markers and logs
contain only hashes, sizes and counts.

Subcommands (usage: build_stages.py <command> ...):
  stages [--stage S ...] [--from S] [--to S] [--only S ...]   selected stages in fixed order
  stage-hash --stage S --root R --work W [--target T]   input hash of a stage
  marker-check --work W --stage S --hash H       exit 0 if the marker matches the hash
  marker-write --work W --stage S --hash H [--note K=V ...]
  marker-clear --work W --stage S
  preflight --stages "a b" --target T --root R --work W [--min-free-gb N] [--tools-dir D] ...
  env-get --file F --key K                       value from a KEY=value file (e.g. work/local.env)
  tree-size --path P                             "<files> <bytes>" of a folder
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

# Exit codes (must match build_all.sh)
EX_USAGE = 2
EX_TOOLS = 4
EX_DISK = 8

STAGES = ["tools", "extract", "recomp", "shaders"]
ALIASES = {"shader": "shaders", "macapp": "recomp"}
MARKER_SCHEMA = 1
MIN_FREE_GB = 40
RECOMP_MIN_FREE_GB = 25   # generator C, objects, binary, app, intermediate copies (measured about 3 GB; the rest is reserve for the compiler and swapping)
HEAVY_STAGES = {"extract", "shaders"}
TARGETS = ("macos", "ios", "all")


def normalize_stage(name):
    name = name.strip().lower()
    name = ALIASES.get(name, name)
    if name not in STAGES:
        raise ValueError("Unknown stage: %s (known: %s)" % (name, " ".join(STAGES)))
    return name


def _names(values):
    out = []
    for v in values or []:
        out.extend(p for p in re.split(r"[,\s]+", v) if p)
    return out


def select_stages(requested=(), from_stage=None, to_stage=None, only=()):
    """Selects stages in canonical order. `all` or no argument = all."""
    only_names = _names(only)
    if only_names:
        if from_stage or to_stage:
            raise ValueError("--only cannot be combined with --from/--to")
        chosen = {normalize_stage(n) for n in only_names}
        return [s for s in STAGES if s in chosen]
    req = _names(requested)
    if not req or "all" in req:
        chosen = set(STAGES)
    else:
        chosen = {normalize_stage(n) for n in req}
    lo = STAGES.index(normalize_stage(from_stage)) if from_stage else 0
    hi = STAGES.index(normalize_stage(to_stage)) if to_stage else len(STAGES) - 1
    if lo > hi:
        raise ValueError("--from (%s) is after --to (%s)" % (from_stage, to_stage))
    result = [s for i, s in enumerate(STAGES) if lo <= i <= hi and s in chosen]
    if not result:
        raise ValueError("No stage in the selected range")
    return result


# ---------- Hashes and markers ----------
# NOTE: the placeholder tokens below ("missing", "no-marker", "no-prepare", "no-manifest", "none") are part of the stage
# hashes, but only in cases where an input is absent. Renaming them from their old German forms changed the hash of the
# shaders stage once (SHADER_USED unset gave "keine"), so that stage re-runs a single time.

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def hash_file(path):
    if not os.path.isfile(path):
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name == ".DS_Store":
                continue
            yield os.path.join(dirpath, name)


def hash_tree_content(root, suffixes=None, skip_dirs=("Library", "Temp", "Logs", "obj", "UserSettings")):
    """Hash over relative paths and contents (for small source folders)."""
    if not os.path.isdir(root):
        return "missing"
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for name in sorted(filenames):
            if name == ".DS_Store" or (suffixes and not name.lower().endswith(tuple(suffixes))):
                continue
            p = os.path.join(dirpath, name)
            h.update(os.path.relpath(p, root).encode() + b"\0" + hash_file(p).encode() + b"\n")
    return h.hexdigest()


def extract_core(work):
    """Input core from manifest.json (stage extract): title, version, main hash, RomFS counts."""
    try:
        with open(os.path.join(work, "manifest.json")) as f:
            m = json.load(f)
        return {"title_id": m["title_id"], "title_version": m["title_version"],
                "main_sha256": m["exefs"]["main"]["sha256"], "romfs": m["romfs"]}
    except (OSError, KeyError, ValueError, TypeError):
        return None


def marker_path(work, stage):
    return os.path.join(work, ".stages", stage + ".json")


def read_marker(work, stage):
    try:
        with open(marker_path(work, stage)) as f:
            m = json.load(f)
        return m if m.get("schema") == MARKER_SCHEMA and m.get("stage") == stage else None
    except (OSError, ValueError):
        return None


def marker_matches(work, stage, digest):
    m = read_marker(work, stage)
    return bool(m) and m.get("hash") == digest


def write_marker(work, stage, digest, notes=None):
    path = marker_path(work, stage)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"schema": MARKER_SCHEMA, "stage": stage, "hash": digest,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "notes": notes or {}}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def clear_marker(work, stage):
    try:
        os.remove(marker_path(work, stage))
    except OSError:
        pass


def _marker_hash(work, stage):
    m = read_marker(work, stage)
    return m["hash"] if m else "no-marker"


def read_env_value(path, key):
    """Value from a file with KEY=value lines (optional `export`, quotes, #-comments)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    value = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            value = v
    return value or None


def nvn_source_stamp(rec):
    """Source hash of the NVN layer (nvn/src, translate.c, shader.h, prepare.sh); the only definition is in prepare.sh."""
    script = os.path.join(rec, "rt-bdsp", "nvn", "prepare.sh")
    if not os.path.isfile(script):
        return "no-prepare"
    r = subprocess.run(["bash", script, "--print"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("prepare.sh --print failed: " + r.stderr.strip())
    return r.stdout.strip()


def stage_hash(stage, root, work, target="all", env=None):
    """Hash of a stage's inputs; if it changes, the stage runs again. Returns (hash, parts)."""
    env = os.environ if env is None else env
    scripts = os.path.join(root, "scripts")
    core = extract_core(work)
    parts = {"stage": stage, "extract": core if core else "no-manifest"}

    def files(*names):
        return {n: hash_file(os.path.join(scripts, n)) for n in names}

    if stage in ("recomp-gen", "recomp"):
        # Generator inputs and native source/tool dependency contracts.
        rec = os.path.join(scripts, "recomp")
        parts["modules"] = {m: hash_file(os.path.join(work, "exefs", m)) for m in ("main", "sdk", "subsdk0", "rtld")}
        parts["generator"] = {n: hash_file(os.path.join(rec, n)) for n in
                              ("native-generator/build.py", "parallel_jobs.py", "gen_all.sh", "c_exact/fp_env.h", "rt/cpu.h")}
        parts["native_codegen"] = hash_tree_content(os.path.join(rec, "native-generator"), (".c", ".h", ".json"), skip_dirs=("__pycache__",))
        parts["native_dependencies"] = hash_file(os.path.join(root, "installer/runtime/wheels.lock.json"))
        if stage == "recomp":
            # runtime, NVN layer (vendored + patches), translator, app shell; the partial markers cover generator and objects
            skip = ("test", "vulkan", "__pycache__")
            parts["gen"] = _marker_hash(work, "recomp-gen")
            parts["obj"] = _marker_hash(work, "recomp-obj")
            parts["runtime"] = hash_tree_content(os.path.join(rec, "rt-bdsp"), (".c", ".h", ".m", ".sh", ".patch", ".txt"), skip_dirs=skip)
            parts["nvn_stamp"] = nvn_source_stamp(rec)
            parts["app"] = hash_tree_content(os.path.join(rec, "app"), (".sh", ".py", ".h", ".in", ".entitlements"), skip_dirs=("__pycache__",))
            parts["build_scripts"] = files("recomp/build_all.sh", "recomp/test/compile_chunk.sh")
            parts["npdm"] = hash_file(os.path.join(work, "exefs", "main.npdm"))
            parts["icons"] = hash_tree_content(env.get("BDSP_ICON_SOURCE", os.path.join(work, "recomp/icons/source")), (".json", ".png"))
            parts["options"] = env.get("XNU_RECOMP_OPTS", "")
    elif stage == "shaders":
        parts["scripts"] = files("shader_build.sh", "shader_extract_blobs.py", "shader_inventory.py",
                                 "shader_fidelity.py", "shader_wrap_all.py", "shader_wrap.py")
        tr = os.path.join(root, "shader_translator")
        parts["translator"] = hash_tree_content(tr, (".c", ".h", "makefile"), skip_dirs=("build", "__pycache__"))
        used = env.get("SHADER_USED", "")
        parts["used"] = hash_file(used) if used else "none"
    digest = _sha(json.dumps(parts, sort_keys=True).encode())
    return digest, parts


# ---------- Preflight ----------

def tree_size(path):
    count = total = 0
    for p in _walk(path):
        count += 1
        total += os.path.getsize(p)
    return count, total


def free_gb(path):
    probe = path
    while not os.path.exists(probe):
        probe = os.path.dirname(probe) or "."
    # Display and thresholds use decimal GB (1 GB = 1,000,000,000 bytes),
    # matching macOS System Settings and APFS capacity reporting.
    return shutil.disk_usage(probe).free / 1_000_000_000


def _run_ok(cmd, env=None, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return False, ""


def preflight(stages, target, root, work, tools_dir=None, min_free_gb=MIN_FREE_GB,
              which=shutil.which, run=_run_ok, free=free_gb):
    """Checks only what the selected stages need; nothing is installed. Entry: dict(name, ok, detail, hint, level)."""
    tools_dir = tools_dir or os.path.join(root, "tools")
    s = set(stages)
    want_mac = target in ("macos", "all")
    items = []

    def add(name, ok, detail="", hint="", level="missing"):
        items.append({"name": name, "ok": bool(ok), "detail": detail, "hint": hint, "level": level})

    def python_imports(modules, pydeps=None, command=None):
        """Use the same import paths as the build, including an existing CLI venv."""
        private_runtime = os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") == "1"
        candidates = ([sys.executable] if private_runtime else [
            os.path.join(work, "venv", "Scripts", "python.exe") if os.name == "nt"
            else os.path.join(work, "venv", "bin", "python3"), sys.executable])
        env = os.environ.copy()
        if pydeps and not private_runtime:
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (pydeps, env.get("PYTHONPATH"))))
        code = "; ".join("import " + module for module in modules)
        for python in candidates:
            if python != sys.executable and not os.access(python, os.X_OK):
                continue
            ok, _ = run([python, "-I" if private_runtime else "-B", *(command or ["-c", code])], env=env)
            if ok:
                return True
        return False

    major = sys.version_info
    add("python3 >= 3.9", major >= (3, 9), "%d.%d.%d" % major[:3], "brew install python")
    if s & HEAVY_STAGES:
        gb = free(work)
        add("Disk space >= %d GB free" % min_free_gb, gb >= min_free_gb, "%.1f GB free under %s" % (gb, work),
            "Free up disk space before continuing. This run requires at least %d GB for input copies, "
            "extracted data and build output. Lowering the check can make the build run out of disk space."
            % min_free_gb)

    hactool = os.path.join(tools_dir, "hactool", "hactool")
    if "tools" in s:
        for c in ("git", "make", "cc"):
            executable = os.environ.get("BDSP_GIT", "git") if c == "git" else c
            add(c + " (for hactool)", which(executable), executable if c == "git" else "",
                "xcode-select --install (Command Line Tools)")
    elif "extract" in s:
        add("hactool", os.access(hactool, os.X_OK), hactool,
            "scripts/build_all.sh tools (clones and builds hactool locally, without sudo)")
    if "extract" in s and "tools" in s and not os.access(hactool, os.X_OK):
        add("hactool", True, "built by stage tools", level="note")

    if "shaders" in s:
        pyd = os.path.join(tools_dir, "pydeps")
        add("Python packages (UnityPy, lz4) for shaders", python_imports(("UnityPy", "lz4.block"), pyd),
            "", "python3 -m pip install --target tools/pydeps UnityPy lz4")
        for c in ("make", "cc"):
            add(c + " (for shader_translator)", which(c), "", "xcode-select --install (Command Line Tools)")

    if "recomp" in s and want_mac:
        if not (s & HEAVY_STAGES):   # otherwise the general space check (stricter) already covers it
            need = min(RECOMP_MIN_FREE_GB, min_free_gb)
            gb = free(work)
            add("Disk space >= %d GB free (stage recomp)" % need, gb >= need, "%.1f GB free under %s" % (gb, work),
                "Free up space (delete old work/recomp subfolders such as img*, gen, obj*, spike2) or deliberately ask for less: --min-free-gb N")
        add("clang (Homebrew LLVM in PATH)", which("clang"), which("clang") or "", "brew install llvm and put /opt/homebrew/opt/llvm/bin before /usr/bin in the PATH")
        ok, _ = run(["/usr/bin/xcrun", "--find", "clang"])
        add("Apple clang (Objective-C, Command Line Tools)", ok, "", "xcode-select --install")
        for c, hint in (("pkg-config", "brew install pkg-config"), ("rsync", "rsync is part of macOS"), ("strip", "xcode-select --install"), ("codesign", "xcode-select --install"),
                        ("install_name_tool", "xcode-select --install"), ("otool", "xcode-select --install"),
                        ("iconutil", "xcode-select --install"), ("plutil", "plutil is part of macOS")):
            add(c + " (for the app)", which(c), "", hint)
        pc = which("pkg-config")
        ok, _ = run([pc, "--exists", "sdl3", "libavcodec", "libavformat", "libavutil"]) if pc else (False, "")
        add("SDL3 and FFmpeg libraries (pkg-config)", ok, "", "brew install sdl3 ffmpeg")
        add("Pillow (app icons)", python_imports(("PIL.Image",)), "", "python3 -m pip install Pillow")
        pyd = os.path.join(tools_dir, "pydeps")
        native = os.path.join(root, "scripts", "recomp", "native-generator")
        add("Unicorn 2.1.4 C engine and headers (native generator)",
            python_imports((), pyd, [os.path.join(native, "build.py"), "--check-unicorn"]), "",
            "Use the installer runtime, or install unicorn==2.1.4 in the CLI environment; BDSP_UNICORN_ROOT can provide include/ and lib/ directly")
        up = os.path.join(root, "scripts", "recomp", "upstream")
        add("Native generator sources and runtime headers",
            os.path.isfile(os.path.join(native, "src", "generator.c")) and os.path.isfile(os.path.join(up, "runtime", "cpu.h")), "",
            "git checkout -- scripts/recomp/native-generator scripts/recomp/upstream/runtime")

    return items


def format_preflight(items):
    """Lines for the output plus install list; returns (lines, missing, disk_missing)."""
    lines, missing, disk = [], [], False
    for it in items:
        if it["ok"]:
            tag = "OK    " if it["level"] != "note" else "NOTE   "
        else:
            tag = "MISSING " if it["level"] == "missing" else "NOTE   "
        detail = it.get("detail", "")
        lines.append("  %s %s%s" % (tag, it["name"], " (%s)" % detail if detail else ""))
        if not it["ok"] and it["level"] == "missing":
            missing.append(it)
            if it["name"].startswith("Disk space"):
                disk = True
    return lines, missing, disk


def install_list(missing):
    out = ["Install list (nothing is run with administrator rights; please run these yourself):"]
    for i, it in enumerate(m for m in missing if not m["name"].startswith("Disk space")):
        out.append("  %d. %s: %s" % (i + 1, it["name"], it["hint"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stages")
    p.add_argument("--stage", action="append", default=[])
    p.add_argument("--from", dest="from_stage")
    p.add_argument("--to", dest="to_stage")
    p.add_argument("--only", action="append", default=[])
    p = sub.add_parser("stage-hash")
    p.add_argument("--stage", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--target", default="all")
    p.add_argument("--parts", action="store_true")
    for name in ("marker-check", "marker-write"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
        p.add_argument("--stage", required=True)
        p.add_argument("--hash", required=True)
        if name == "marker-write":
            p.add_argument("--note", action="append", default=[])
    p = sub.add_parser("marker-clear")
    p.add_argument("--work", required=True)
    p.add_argument("--stage", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--stages", required=True)
    p.add_argument("--target", default="all", choices=TARGETS)
    p.add_argument("--root", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--tools-dir")
    p.add_argument("--min-free-gb", type=int, default=MIN_FREE_GB)
    p = sub.add_parser("env-get")
    p.add_argument("--file", required=True)
    p.add_argument("--key", required=True)
    p = sub.add_parser("tree-size")
    p.add_argument("--path", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "stages":
        try:
            print(" ".join(select_stages(a.stage, a.from_stage, a.to_stage, a.only)))
        except ValueError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return EX_USAGE
        return 0
    if a.cmd == "stage-hash":
        digest, parts = stage_hash(a.stage, a.root, a.work, a.target)
        if a.parts:
            print(json.dumps(parts, indent=2, sort_keys=True))
        print(digest)
        return 0
    if a.cmd == "marker-check":
        return 0 if marker_matches(a.work, a.stage, a.hash) else 1
    if a.cmd == "marker-write":
        notes = dict(n.split("=", 1) for n in a.note if "=" in n)
        write_marker(a.work, a.stage, a.hash, notes)
        return 0
    if a.cmd == "marker-clear":
        clear_marker(a.work, a.stage)
        return 0
    if a.cmd == "preflight":
        items = preflight(a.stages.split(), a.target, a.root, a.work, a.tools_dir, min_free_gb=a.min_free_gb)
        lines, missing, disk = format_preflight(items)
        print("\n".join(lines))
        for m in missing:
            if m["name"].startswith("Disk space"):
                print("Space: " + m["hint"])
        if any(not m["name"].startswith("Disk space") for m in missing):
            print("\n".join(install_list(missing)))
        if disk:
            return EX_DISK if all(m["name"].startswith("Disk space") for m in missing) else EX_TOOLS
        return EX_TOOLS if missing else 0
    if a.cmd == "env-get":
        v = read_env_value(a.file, a.key)
        if v is None:
            return 1
        print(v)
        return 0
    if a.cmd == "tree-size":
        count, total = tree_size(a.path)
        print(count, total)
        return 0
    return EX_USAGE


if __name__ == "__main__":
    sys.exit(main())
