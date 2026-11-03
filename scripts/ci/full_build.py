#!/usr/bin/env python3
"""Runs the installer driver build headlessly on the private CI data and reports only what is safe to show.

The driver's JSON event stream goes to a file inside the (wiped) base folder, never to the Actions log. What is printed and
written to the summary: step names with their status, the result code, and error messages with every known path and every
long hex run replaced. Standard library only.

Usage: full_build.py --target T --root SRC --base BASE [--python PY] [--mod] [--windows-catalog F] [--ips-helper F]
       [--firmware-helper F] [--extract F --extract-prefix P] [--summary FILE] [--installed-out FILE]
BASE holds data/ (decrypted inputs from private_data.py), mods/, work/, install/ and logs/.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TARGETS = ("macos", "linux", "windows")
HEX_RUN = re.compile(r"[0-9a-fA-F]{24,}")


def redact(text, known, limit=300):
    forms = []
    for value in known:
        if value:
            forms += [str(value), str(value).replace("\\", "/"), str(value).replace("\\", "\\\\")]
    for form in sorted(set(forms), key=len, reverse=True):
        text = text.replace(form, "<path>")
    return HEX_RUN.sub("<hex>", text)[:limit]


def build_command(args, python=None):
    base = Path(args.base)
    data = base / "data"
    # The mac and linux pipeline refuses any work folder except the checkout's work/ (driver.py); Windows uses its own.
    work = base / "work" if args.target == "windows" else Path(args.root) / "work"
    command = [python or args.python or sys.executable]
    command += ["-I", "-B"] if args.target == "windows" else ["-B"]
    command += [str(Path(args.root) / "scripts/install/driver.py"), "build", "--root", str(args.root),
                "--work", str(work), "--target", args.target,
                "--base", str(data / "game.xci"), "--prod-keys", str(data / "prod.keys"),
                "--update", str(data / "update.nsp"), "--firmware", str(data / "firmware.zip"),
                "--install-root", str(base / "install")]
    for option, value in (("--windows-catalog", args.windows_catalog), ("--ips-helper", args.ips_helper),
                          ("--firmware-helper", args.firmware_helper)):
        if value:
            command += [option, str(value)]
    if args.mod:
        command += ["--mod-root", str(base / "mods/ci-mod"), "--mod-name", "ci-mod", "--mods-dir", str(base / "mods")]
    return command


def link_work(args):
    """The checkout's work/ points at the big disk (BASE), so the disk space check and the build use BASE."""
    if args.target == "windows":
        return
    link = Path(args.root) / "work"
    if link.exists() or link.is_symlink():
        return
    target = Path(args.base) / "work"
    target.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def build_environment(args, environ=os.environ):
    base = Path(args.base)
    env = dict(environ)
    env.update({"BDSP_SHADER_CACHE_DIR": str(base / "shader-cache"), "BDSP_MOD": "ci-mod" if args.mod else "none",
                "BDSP_NO_DIAGNOSTICS": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    if args.mod:
        env["BDSP_MODS_DIR"] = str(base / "mods")
    if args.extract:
        env["BDSP_EXTRACT"] = str(args.extract)
        if args.extract_prefix:
            env["BDSP_EXTRACT_PREFIX"] = args.extract_prefix
    if args.target == "windows":
        env["BDSP_INSTALLER_PRIVATE_RUNTIME"] = "1"
        for name in ("PYTHONPATH", "PYTHONHOME", "BDSP_CPU_TARGET"):
            env.pop(name, None)
    return env


def summarize(lines, known):
    steps, errors, missing, result, installed = {}, [], [], None, None
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("event")
        if kind == "step" and "id" in event:
            steps[str(event["id"])] = str(event.get("status", ""))
        elif kind == "error":
            errors.append({"code": event.get("code"), "message": redact(str(event.get("message", "")), known)})
        elif kind == "log" and str(event.get("message", "")).startswith("MISSING"):
            missing.append(redact(str(event["message"]), known))
        elif kind == "result":
            result = {"ok": bool(event.get("ok")), "code": event.get("code")}
        elif kind == "artifact" and event.get("kind") == "installed_application":
            installed = event.get("path")
    summary = {"steps": steps, "errors": errors[-5:], "result": result}
    if missing:
        summary["missing"] = missing[:20]
    return summary, installed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--python")
    parser.add_argument("--mod", action="store_true")
    parser.add_argument("--windows-catalog")
    parser.add_argument("--ips-helper")
    parser.add_argument("--firmware-helper")
    parser.add_argument("--extract")
    parser.add_argument("--extract-prefix")
    parser.add_argument("--summary")
    parser.add_argument("--installed-out")
    args = parser.parse_args(argv)
    base = Path(args.base)
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    link_work(args)
    print("free GB before the build: %d under the base folder, %d under the checkout work folder" % (
        shutil.disk_usage(base).free // 2**30, shutil.disk_usage(Path(args.root) if os.name == "nt" else Path(args.root) / "work").free // 2**30), flush=True)
    with open(logs / "driver-events.jsonl", "w", encoding="utf-8") as events, \
            open(logs / "driver-stderr.log", "w", encoding="utf-8") as stderr:
        code = subprocess.run(build_command(args), cwd=args.root, env=build_environment(args), stdout=events,
                              stderr=stderr, stdin=subprocess.DEVNULL, check=False).returncode
    known = [args.base, args.root, os.environ.get("RUNNER_TEMP"), str(Path.home())]
    lines = (logs / "driver-events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    summary, installed = summarize(lines, known)
    summary.update({"target": args.target, "mod": args.mod, "exit": code, "seconds": int(time.monotonic() - started)})
    ok = code == 0 and bool(summary["result"] and summary["result"]["ok"])
    print(json.dumps(summary, indent=2))
    if not ok:
        reasons = {8: "not enough disk space", 4: "a tool or component is missing"}
        print("FAILED: exit %s (%s). Missing items: %s. Last error: %s" % (
            code, reasons.get(code, "see the steps above"), "; ".join(summary.get("missing", [])) or "none reported",
            summary["errors"][-1]["message"].splitlines()[0] if summary["errors"] else "none"), flush=True)
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.installed_out and installed and ok:
        Path(args.installed_out).write_text(str(installed), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
