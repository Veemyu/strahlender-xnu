#!/usr/bin/env python3
"""Headless JSONL entry point shared by the desktop installer and CLI wrappers."""
import argparse
import hashlib
import importlib.util
import json
import os
import plistlib
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path

PROTOCOL_VERSION = 2


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def load_build_stages(root):
    path = os.path.join(root, "scripts", "build_stages.py")
    spec = importlib.util.spec_from_file_location("strahlender_build_stages", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Build prerequisite checker is missing.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_detail(item):
    name = item["name"]
    detail = item.get("detail", "")
    if name.startswith("python3 >="):
        match = re.search(r"\d+\.\d+(?:\.\d+)?", detail)
        return match.group(0) if match else ""
    if name.startswith("Disk space"):
        match = re.search(r"([\d.]+)\s+GB\s+free", detail)
        return (match.group(1) + " GB free") if match else ""
    return ""


def prerequisite_exception(error, args):
    # Keep the traceback in the expandable protocol, not in the user dialog.
    for line in traceback.format_exc().splitlines():
        emit("log", level="diagnostic", message=_safe_line(line, args))
    emit("error", message=("Prerequisite checker internal error: " + type(error).__name__
                           + ": " + _safe_line(str(error), args)), code=1)


def preflight(args):
    emit("hello", protocol=PROTOCOL_VERSION, capabilities=["preflight", "build"])
    emit("step", id="prerequisites", status="started")
    try:
        stages = load_build_stages(args.root)
        items = stages.preflight(
            ["tools", "extract", "recomp"],
            args.target,
            args.root,
            args.work,
            args.tools_dir,
            min_free_gb=args.min_free_gb,
        )
        _, missing, disk_missing = stages.format_preflight(items)
        missing_names = {item["name"] for item in missing}
        for item in items:
            ok = item["ok"]
            level = "ok" if ok else ("note" if item["level"] == "note" else "warning")
            message = ("OK" if ok else ("NOTE" if level == "note" else "MISSING")) + "  " + item["name"]
            detail = safe_detail(item)
            if detail:
                message += " (" + detail + ")"
            emit("log", level=level, message=message)
            if item["name"] in missing_names and item.get("hint"):
                emit("log", level="hint", message="Next step: " + item["hint"])
        ok = not missing
        if ok:
            emit("step", id="prerequisites", status="complete")
        else:
            emit("step", id="prerequisites", status="needs attention")
        code = 0 if ok else (stages.EX_DISK if disk_missing and all(
            item["name"].startswith("Disk space") for item in missing) else stages.EX_TOOLS)
        emit("result", ok=ok, code=code)
        return code
    except Exception as error:
        prerequisite_exception(error, args)
        return 1


def _safe_line(line, args):
    for value in (getattr(args, "prod_keys", None), getattr(args, "base", None),
                  getattr(args, "update", None), getattr(args, "mod_root", None)):
        if value:
            line = line.replace(str(value), "<private input>")
    # Resolve relative roots before redaction. Replacing a literal "." corrupts
    # every decimal point in diagnostics and version strings.
    project_root = str(Path(args.root).resolve())
    return line.replace(project_root, "<project>").replace(str(Path.home()), "~").rstrip()


def _run_command(command, args, stage, progress=None, phase_from_line=None, extra_env=None, emit_steps=True):
    args.command_failure_hint = None
    active = stage
    # A long-running bash script must not keep reading a file being edited by a
    # parallel development session. Preserve $0 and argv while freezing its text.
    script = Path(command[0])
    if script.is_file():
        with script.open("rb") as file:
            prefix = file.read(128)
            if prefix.startswith((b"#!/bin/bash\n", b"#!/usr/bin/env bash\n")):
                source = prefix + file.read()
                command = ["bash", "-c", source.decode("utf-8"), str(script), *command[1:]]
    if emit_steps:
        emit("step", id=active, status="started")
    output = queue.Queue()
    environment = dict(os.environ)
    for variable in ("BDSP_EXEFS_DIR", "RECOMP_DIR", "BDSP_MOD_NAME", "BDSP_MOD_ROOT",
                     "BDSP_MOD_BUNDLE_ID", "BDSP_MOD_DISPLAY_NAME", "BDSP_ICON_SOURCE",
                     "BDSP_IOS_BUILD_DIR", "BDSP_IOS_UDID", "BDSP_IOS_BUNDLE_ID"):
        environment.pop(variable, None)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **(extra_env or {})})
    proc = subprocess.Popen(command, cwd=args.root, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            env=environment)

    def reader():
        for line in proc.stdout:
            output.put(line)
        output.put(None)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    done = False
    last_progress = None
    generated_modules = set()
    first_failure = None
    module_total = 4 + int((Path(environment.get("BDSP_EXEFS_DIR", Path(args.root) / "work/exefs")) / "subsdk1").is_file())
    try:
        while not done or proc.poll() is None:
            try:
                line = output.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                done = True
            elif line:
                message = _safe_line(line, args)
                if message:
                    emit("log", level="diagnostic", message=message)
                    if first_failure is None and re.search(
                            r"fatal error:|error:|undefined reference|ModuleNotFoundError:|ImportError:", message):
                        first_failure = message.strip()
                    if "maximum number of installed apps using a free developer profile" in message:
                        args.command_failure_hint = ("Apple's free signing limit is full on this device. Remove an unused development-signed app "
                                                     "to make room for the separate mod app. The installer does not replace your original game.")
                    if phase_from_line:
                        next_phase = phase_from_line(message)
                        if next_phase and next_phase != active:
                            emit("step", id=active, status="complete")
                            active = next_phase
                            emit("step", id=active, status="started")
                    if active == "eh_gen":
                        module_done = re.match(r"^([A-Za-z_][A-Za-z_0-9]*): wrote ", message)
                        module_marker = re.match(r"^module=([A-Za-z_][A-Za-z_0-9]*)\b", message)
                        completed_module = module_done or module_marker
                        if completed_module and completed_module[1] not in generated_modules:
                            generated_modules.add(completed_module[1])
                            emit("progress", id="eh_gen", completed=min(len(generated_modules), module_total), total=module_total)
            if progress:
                current = progress(active)
                if current and current != last_progress:
                    emit("progress", id=active, completed=current[0], total=current[1])
                    last_progress = current
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        raise
    finally:
        reader_thread.join(timeout=5)
        proc.stdout.close()
    if emit_steps:
        emit("step", id=active, status="complete" if code == 0 else "failed")
    if code:
        cause = args.command_failure_hint or first_failure or ("Command exited with code " + str(code))
        emit("error", message="Build step failed: " + active + "\n" + cause, code=code)
    return code


def _compile_count(work, target, recomp_dir=None):
    obj = Path(recomp_dir) if recomp_dir else Path(work) / "recomp"
    obj = obj / ("obj4" if target == "macos" else "obj4-c")
    lists = [obj / "list_O0.txt", obj / "list_O1.txt"]
    if not all(path.is_file() for path in lists):
        return None
    try:
        total = int((obj / ".compile-total").read_text().strip())
        inventory = sum(len(path.read_text().splitlines()) for path in lists)
    except (OSError, ValueError):
        return None
    if total <= 0 or total != inventory:
        return None
    return min(sum(1 for _ in obj.glob("*.o")), total), total


def _mac_phase(line):
    for marker, stage in (("1/6 generator:", "eh_gen"), ("2/6 compile:", "clang"),
                          ("3/6 module images", "images"), ("4/6 building runtime", "runtime"),
                          ("5/6 assembling", "package")):
        if marker in line:
            return stage
    return None


def required_free_gb(args):
    base = Path(args.base)
    if base.is_dir():
        base_bytes = sum(path.stat().st_size for path in base.iterdir()
                         if path.is_file() and path.suffix.lower() == ".nca")
    else:
        base_bytes = base.stat().st_size
    update_bytes = Path(args.update).stat().st_size if args.update else 0
    gb = 1_000_000_000
    return max(40, 25 + (2 * base_bytes + update_bytes + gb - 1) // gb + 1)


def missing_generator_modules(run=subprocess.run):
    checker = Path(__file__).resolve().parents[1] / "recomp/native-generator/build.py"
    missing = []
    if run([sys.executable, "-I", str(checker), "--check-unicorn"],
           capture_output=True, check=False).returncode:
        missing.append("Unicorn 2.1.4 native engine and headers")
    for module, label in (("lz4.block", "LZ4"), ("PIL.Image", "Pillow")):
        if run([sys.executable, "-I", "-c", "import " + module], capture_output=True, check=False).returncode:
            missing.append(label)
    return missing


def check_build_dependencies(args):
    emit("step", id="prerequisites", status="started")
    try:
        stages = load_build_stages(args.root)
        mac = args.target == "macos"
        items = stages.preflight(
            ["tools", "extract", "recomp"] if mac else ["tools", "extract"],
            "macos" if mac else "ios", args.root, args.work,
            os.path.join(args.root, "tools"), min_free_gb=required_free_gb(args),
        )
        if not mac:
            missing_modules = missing_generator_modules()
            items.append({"name": ("Build runtime components missing: " + ", ".join(missing_modules)
                                    if missing_modules else "Native Unicorn engine, LZ4 and Pillow"),
                          "ok": not missing_modules, "level": "missing", "detail": "",
                          "hint": "This development environment needs the native engine and asset packages. The packaged installer includes its private Python runtime."})
        if getattr(args, "mod_root", None):
            artwork = subprocess.run([sys.executable, str(Path(args.root) / "scripts/recomp/app/game_icons.py"),
                                      "check-mod-artwork", "--mod-root", str(args.mod_root)],
                                     cwd=args.root, capture_output=True, text=True, check=False)
            items.append({"name": "Mod artwork reader", "ok": artwork.returncode == 0, "level": "missing", "detail": "",
                          "hint": "Prepare the existing UnityPy shader profile in the build runtime for embedded mod title logos."})
        if args.target == "linux":
            packages = subprocess.run(
                ["bash", "-c", "source scripts/recomp/linux/deps.sh && linux_require_runtime && linux_require_qt"],
                cwd=args.root, capture_output=True, text=True, check=False,
            )
            items.append({"name": "Vulkan and Qt development packages",
                          "ok": packages.returncode == 0, "level": "missing", "detail": "",
                          "hint": "Install the distribution packages listed in docs/BUILD.md, section 6."})
            if packages.returncode:
                for line in (packages.stdout + "\n" + packages.stderr).splitlines():
                    if line.strip():
                        emit("log", level="diagnostic", message=_safe_line(line, args))
        if args.target == "ios":
            sdk = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], capture_output=True, check=False)
            items.append({"name": "Xcode iPhoneOS SDK", "ok": sdk.returncode == 0, "level": "missing", "detail": "",
                          "hint": "Install and open Xcode once, then select its developer directory."})
            libraries = Path(args.root) / "work/ios/ffmpeg-ios/lib"
            items.append({"name": "iPhoneOS FFmpeg static libraries",
                          "ok": all((libraries / ("lib" + name + ".a")).is_file() for name in ("avformat", "avcodec", "avutil")),
                          "level": "missing", "detail": "", "hint": "Prepare scripts/recomp/ios/build_ffmpeg_ios.sh as documented in docs/recomp-ios.md."})
        _, missing, disk_missing = stages.format_preflight(items)
        for item in items:
            ok = item["ok"]
            emit("log", level="ok" if ok else "warning",
                 message=("OK  " if ok else "MISSING  ") + item["name"]
                 + (" (" + safe_detail(item) + ")" if safe_detail(item) else ""))
            if not ok and item.get("hint"):
                emit("log", level="hint", message="Next step: " + item["hint"])
        emit("step", id="prerequisites", status="complete" if not missing else "needs attention")
        if not missing:
            return 0
        return stages.EX_DISK if disk_missing and all(
            item["name"].startswith("Disk space") for item in missing) else stages.EX_TOOLS
    except Exception as error:
        prerequisite_exception(error, args)
        return 1


def _copy_tree(source, destination, stage_id, state):
    source = Path(source)
    if not source.is_dir():
        raise FileNotFoundError("Build data is missing: " + str(source))
    for parent, dirs, files in os.walk(source):
        dirs.sort()
        files.sort()
        for name in dirs:
            if (Path(parent) / name).is_symlink():
                raise ValueError("A symbolic link in game data needs manual review.")
        target = destination / Path(parent).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            origin = Path(parent) / name
            if origin.is_symlink():
                raise ValueError("A symbolic link in game data needs manual review: " + str(origin))
            shutil.copy2(origin, target / name)
            state[0] += 1
            if state[0] % 25 == 0 or state[0] == state[1]:
                emit("progress", id=stage_id, completed=state[0], total=state[1])


def _file_count(source):
    return sum(len(files) for _, _, files in os.walk(source))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mod_exefs(root):
    if not root:
        return None
    root = Path(root)
    if not root.is_dir():
        raise ValueError("The selected mod folder no longer exists.")
    matches = [path for path in root.iterdir() if path.name.lower() == "exefs" and path.is_dir()]
    if len(matches) > 1:
        raise ValueError("The selected mod has multiple ExeFS folders.")
    if not matches:
        return None
    files = [path for path in matches[0].iterdir()
             if path.name.lower() not in ("license", "notice", ".ds_store")]
    return matches[0] if files else None


def _validate_mod_name(name):
    if not isinstance(name, str) or not name.strip() or name in (".", "..") or any(character in name for character in "/\\\r\n"):
        raise ValueError("Choose a mod name without path separators or newlines.")
    if len(name.encode("utf-8")) > 254:
        raise ValueError("The mod name is too long for this runtime.")


def _prepare_code_mod(args, work, build_cache=None):
    exefs = _mod_exefs(getattr(args, "mod_root", None))
    if not exefs:
        emit("step", id="exefs", status="skipped")
        return None
    if args.target not in ("macos", "ios"):
        raise ValueError("ExeFS builds currently need a native Apple build host.")
    name = getattr(args, "mod_name", None)
    mods_dir = getattr(args, "mods_dir", None)
    helper = getattr(args, "ips_helper", None)
    if not name or not mods_dir or not helper or not Path(helper).is_file():
        raise ValueError("A code mod needs its name, mod library and native ips_patch helper.")
    _validate_mod_name(name)
    root = Path(args.mod_root).resolve()
    library = Path(mods_dir).resolve()
    if root == library or not root.is_relative_to(library):
        raise ValueError("The selected mod must be inside its mod library.")
    if any("\n" in value or "\r" in value for value in (name, str(library), str(root))):
        raise ValueError("Mod name and folder cannot contain newlines.")
    if len(name.encode("utf-8")) > 254 or any(len(str(path).encode("utf-8")) > 1098 for path in (library, root)):
        raise ValueError("The mod name or folder path is too long for this runtime.")
    digest = hashlib.sha256()
    for module in ("rtld", "main", "sdk", "subsdk0"):
        digest.update(_sha256(work / "exefs" / module).encode("ascii"))
    for file in sorted(exefs.iterdir()):
        digest.update(file.name.encode("utf-8"))
        if file.is_file() and not file.is_symlink():
            digest.update(_sha256(file).encode("ascii"))
    digest.update(_sha256(helper).encode("ascii"))
    key = digest.hexdigest()[:20]
    build_dir = (Path(build_cache) if build_cache else work / "recomp") / "mods" / key
    staged = build_dir / "exefs"
    if staged.exists():
        if not (staged / ".source-sha256").is_file() or (staged / ".source-sha256").read_text() != key:
            raise ValueError("The existing mod staging folder does not match this build. Inspect it before retrying.")
        emit("step", id="exefs", status="skipped")
    else:
        code = _run_command([str(helper), "stage", str(work / "exefs"), str(exefs), str(staged)],
                            args, "exefs")
        if code:
            raise ValueError("IPS staging failed. See the ExeFS details above.")
        (staged / ".source-sha256").write_text(key, encoding="ascii")
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "mod"
    app_name = "BDSP-" + slug + "-" + identity + ".app"
    return {"staged": staged, "build_dir": build_dir / "ios" if args.target == "ios" else build_dir, "app_name": app_name,
            "bundle_id": "dev.local.xnubdsp.mod." + identity,
            "name": name, "mods_dir": library, "root": root}


def _ios_device(args):
    output = Path(args.work) / "installer/ios-devices.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(["xcrun", "devicectl", "list", "devices", "--json-output", str(output)],
                                capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as error:
        raise ValueError("Apple device discovery timed out. Unlock and reconnect the device.") from error
    if result.returncode:
        raise ValueError("Could not query connected Apple devices. Open Xcode and pair the device first.")
    devices = json.loads(output.read_text()).get("result", {}).get("devices", [])
    connected = [device for device in devices
                 if device.get("connectionProperties", {}).get("tunnelState") == "connected"
                 and device.get("hardwareProperties", {}).get("platform") == "iOS"]
    selected = getattr(args, "ios_device", None)
    if selected:
        connected = [device for device in connected if selected in (
            device.get("identifier"), device.get("hardwareProperties", {}).get("udid"),
            device.get("deviceProperties", {}).get("name"))]
    else:
        ipads = [device for device in connected if device.get("hardwareProperties", {}).get("productType", "").startswith("iPad")]
        connected = ipads or connected
    if len(connected) != 1:
        raise ValueError("Connect and unlock one iPad/iPhone, or select it explicitly with --ios-device.")
    device = connected[0]
    return {"id": device["identifier"], "udid": device["hardwareProperties"]["udid"],
            "name": device.get("deviceProperties", {}).get("name", "iPad / iPhone")}


def _tree_digest(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("Device data folder is missing: " + str(folder))
    def fail(error):
        raise error
    digest = hashlib.sha256()
    for parent, directories, files in os.walk(folder, onerror=fail):
        directories.sort()
        for name in directories + sorted(files):
            path = Path(parent) / name
            if path.is_symlink():
                raise ValueError("Symbolic links in device data are not supported: " + str(path))
            if path.is_file() and name != ".DS_Store":
                digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
                digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()[:20]


def _prepare_ios(args, mod_build, device):
    work = Path(args.work)
    input_work = Path(getattr(args, "ios_input_work", work))
    build_dir = mod_build["build_dir"] if mod_build else work / "recomp/ios-installer/vanilla"
    resources = build_dir / "res"
    resources.mkdir(parents=True, exist_ok=True)
    emit("step", id="package", status="started")
    emit("log", level="diagnostic", message="Identifying game and mod data for the device container.")
    romfs = input_work / "romfs"
    if not (romfs / "Data").is_dir():
        raise ValueError("The extracted RomFS is missing its Data folder.")
    metadata = {"RomFSDirectory": "GameData/" + _tree_digest(romfs) + "/romfs"}
    mod_root = getattr(args, "mod_root", None)
    if mod_root:
        _validate_mod_name(args.mod_name)
        metadata.update({"ModDirectory": "Mods/" + _tree_digest(mod_root), "ModName": args.mod_name,
                         "CompiledExeFS": mod_build is not None})
    (resources / "install-data.plist").write_bytes(plistlib.dumps(metadata))
    bundle_id = getattr(args, "ios_bundle_id", None) or (mod_build["bundle_id"] if mod_build else "dev.local.xnubdsp.installer")
    if not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+", bundle_id):
        raise ValueError("The Apple bundle identifier is invalid.")
    if mod_build and bundle_id in ("dev.local.xnubdsp", "dev.local.xnubdsp.installer"):
        raise ValueError("A separate code-mod app cannot use the original game's bundle identifier.")
    args.ios_install = {"device": device, "bundle_id": bundle_id, "metadata": metadata,
                        "romfs": romfs, "mod_root": mod_root, "build_dir": build_dir}
    return {"BDSP_IOS_BUILD_DIR": str(build_dir), "BDSP_IOS_UDID": device["udid"],
            "BDSP_IOS_BUNDLE_ID": bundle_id,
            "BDSP_EXEFS_DIR": str(mod_build["staged"] if mod_build else input_work / "exefs"),
            "BDSP_ICON_SOURCE": str(input_work / "recomp/icons/source"),
            **({"BDSP_MOD_ROOT": str(mod_root), "BDSP_MOD_NAME": args.mod_name} if mod_build else {})}


def _install_ios(args, artifact):
    info = args.ios_install
    device, bundle = info["device"]["id"], info["bundle_id"]
    try:
        packaged = plistlib.loads((Path(artifact) / "Info.plist").read_bytes())
        metadata = plistlib.loads((Path(artifact) / "res/install-data.plist").read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise ValueError("The iOS app is missing valid installer metadata; installation was not started.") from error
    if packaged.get("CFBundleIdentifier") != bundle or metadata != info["metadata"]:
        raise ValueError("The packaged iOS app identity or mod selection does not match this build; installation was not started.")
    if metadata.get("CompiledExeFS") and bundle in ("dev.local.xnubdsp", "dev.local.xnubdsp.installer"):
        raise ValueError("Installing a separate code mod over the original game is not allowed.")
    emit("log", level="diagnostic", message="Installing the signed app on " + info["device"]["name"] + ".")
    code = _run_command(["xcrun", "devicectl", "device", "install", "app", "--device", device, str(artifact)],
                        args, "install", emit_steps=False)
    if code:
        raise ValueError(getattr(args, "command_failure_hint", None) or "Device app installation failed; see the device diagnostics above.")
    copies = [(info["romfs"], info["metadata"]["RomFSDirectory"])]
    if info["mod_root"]:
        copies.append((info["mod_root"], info["metadata"]["ModDirectory"]))
    for source, destination in copies:
        emit("log", level="diagnostic", message="Copying " + ("mod files" if destination.startswith("Mods/") else "game data") + " to the device.")
        code = _run_command(["xcrun", "devicectl", "device", "copy", "to", "--device", device,
                             "--domain-type", "appDataContainer", "--domain-identifier", bundle,
                             "--source", str(source), "--destination", "Documents/" + destination],
                            args, "install", emit_steps=False)
        if code:
            raise ValueError("Device data copy failed. Retry installation to resume copying; saves are not copied or removed.")
    emit("artifact", kind="ipa", path=str(info["build_dir"] / "BDSP.ipa"))
    return Path(artifact)


def _ios_compile_count(build_dir):
    obj = Path(build_dir) / "obj"
    try:
        total = int((obj / ".compile-total").read_text().strip())
        sources = [Path(line) for name in ("list_O0.txt", "list_O1.txt")
                   for line in (obj / name).read_text().splitlines()]
    except (OSError, ValueError):
        return None
    if total <= 0 or len(sources) != total:
        return None
    completed = 0
    for source in sources:
        output = obj / (source.parent.name + "_" + source.stem + ".o")
        try:
            completed += output.stat().st_mtime_ns >= source.stat().st_mtime_ns
        except OSError:
            pass
    return completed, total


def _build_ios(args, common):
    root, work = Path(args.root), Path(args.work)
    input_work = work / "installer-inputs/ios"
    args.ios_input_work = input_work
    device = _ios_device(args)
    emit("log", level="diagnostic", message="Apple device: " + device["name"])
    extract = [str(root / "scripts/build_all.sh"), "--only", "tools,extract", "--target", "ios",
               "--work", str(input_work), "--min-free-gb", str(required_free_gb(args)), *common]
    code = _run_command(extract, args, "extract")
    mod_build = _prepare_code_mod(args, input_work, build_cache=work / "recomp") if code == 0 else None
    build_dir = mod_build["build_dir"] if mod_build else work / "recomp/ios-installer/vanilla"
    environment = {"BDSP_IOS_BUILD_DIR": str(build_dir),
                   "BDSP_EXEFS_DIR": str(mod_build["staged"] if mod_build else input_work / "exefs")}
    builder = str(root / "scripts/recomp/ios/installer_build.sh")
    for stage, phase in (("eh_gen", "gen"), ("clang", "compile"), ("images", "images"), ("runtime", "runtime")):
        if code:
            break
        counter = (lambda _phase: _ios_compile_count(build_dir)) if stage == "clang" else None
        code = _run_command([builder, phase], args, stage, counter, extra_env=environment)
    if code == 0:
        environment.update(_prepare_ios(args, mod_build, device))
        code = _run_command([builder, "package"], args, "package", extra_env=environment)
    return code, build_dir / "derived/Build/Products/Release-iphoneos/BDSP.app"


def install_artifact(args, artifact):
    """Install only after a successful build; never replace an unowned application."""
    emit("step", id="install", status="started")
    root = Path(args.root)
    work = Path(args.work)
    override = getattr(args, "install_root", None)
    if args.target == "ios":
        destination = _install_ios(args, artifact)
    elif args.target == "macos":
        applications = Path(override) if override else Path("/Applications")
        app_name = Path(artifact).name
        if not app_name.endswith(".app") or "/" in app_name or "\\" in app_name:
            raise ValueError("Invalid application bundle name.")
        destination = applications / app_name
        stem = app_name[:-4]
        receipt = applications / ("." + stem + ".installer-receipt.json")
        if destination.exists():
            try:
                owned = json.loads(receipt.read_text(encoding="utf-8"))
                current_hash = _sha256(destination / "Contents/MacOS/BDSP")
            except (OSError, ValueError):
                owned = None
            if not owned or owned.get("path") != str(destination) or owned.get("binary_sha256") != current_hash:
                raise FileExistsError(app_name + " already exists in " + str(applications) + " and is not this installer's unchanged app.")
        elif receipt.exists():
            raise FileExistsError("An installer receipt exists without " + app_name + "; inspect it before reinstalling.")
        applications.mkdir(parents=True, exist_ok=True)
        staging = applications / ("." + stem + ".app-staging-" + str(os.getpid()))
        backup = applications / ("." + stem + ".app-backup-" + str(os.getpid()))
        receipt_tmp = applications / ("." + stem + ".installer-receipt-" + str(os.getpid()))
        if staging.exists():
            raise FileExistsError("An installation staging folder already exists: " + str(staging))
        if backup.exists():
            raise FileExistsError("An installation backup already exists: " + str(backup))
        emit("log", level="diagnostic", message="Copying the signed app bundle to Applications.")
        try:
            subprocess.run(["ditto", str(artifact), str(staging)], check=True)
            new_hash = _sha256(staging / "Contents/MacOS/BDSP")
            if destination.exists():
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
                receipt_tmp.write_text(json.dumps({"path": str(destination),
                                                   "binary_sha256": new_hash}), encoding="utf-8")
                os.replace(receipt_tmp, receipt)
            except OSError:
                if destination.exists():
                    os.replace(destination, staging)
                if backup.exists():
                    os.replace(backup, destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            if receipt_tmp.exists():
                receipt_tmp.unlink()
    else:
        if override:
            data_home = Path(override) / "share"
            bin_home = Path(override) / "bin"
        else:
            data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
            bin_home = Path.home() / ".local/bin"
        data = data_home / "strahlender-xnu"
        destination = data / "app"
        if destination.exists() and not (destination / ".installer-owned").is_file():
            raise FileExistsError("An existing application at " + str(destination) + " is not owned by this installer.")
        data.mkdir(parents=True, exist_ok=True)
        staging = data / (".app-staging-" + str(os.getpid()))
        if staging.exists():
            raise FileExistsError("An installation staging folder already exists: " + str(staging))
        source_trees = ((work / "romfs", staging / "romfs"),
                        (work / "recomp/img_gfx", staging / "img"),
                        (work / "recomp/icons/linux", staging / "icons/linux"),
                        (root / "scripts/recomp/rt-bdsp/app/linux/lproj", staging / "lproj"))
        total = sum(_file_count(source) for source, _ in source_trees) + 2
        state = [0, total]
        backup = data / (".app-backup-" + str(os.getpid()))
        mods_dir = Path(os.environ.get("BDSP_MODS_DIR") or data / "mods")
        selected_mod = os.environ.get("BDSP_MOD") or "none"
        launcher = bin_home / "strahlender-xnu"
        desktop_file = data_home / "applications/dev.local.xnubdsp.desktop"
        if not destination.exists() and (launcher.exists() or desktop_file.exists()):
            raise FileExistsError("A launcher or desktop entry already exists; it needs manual review before installation.")
        try:
            staging.mkdir()
            shutil.copy2(artifact, staging / "bdsp_boot_vk_qt")
            state[0] += 1
            npdm = work / "exefs/main.npdm"
            shutil.copy2(npdm, staging / "main.npdm")
            state[0] += 1
            emit("progress", id="install", completed=state[0], total=total)
            for source, target in source_trees:
                emit("log", level="diagnostic", message="Copying " + target.name + ".")
                _copy_tree(source, target, "install", state)
            _linux_desktop(launcher, staging)
            (staging / ".installer-owned").write_text("strahlender-xnu-installer v1\n", encoding="utf-8")
            if destination.exists():
                if backup.exists():
                    raise FileExistsError("An installation backup already exists: " + str(backup))
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
            except OSError:
                if backup.exists():
                    os.replace(backup, destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            (data / "saves").mkdir(exist_ok=True)
            mods_dir.mkdir(parents=True, exist_ok=True)
            bin_home.mkdir(parents=True, exist_ok=True)
            launcher.write_text(_linux_launcher(data, mods_dir, selected_mod), encoding="utf-8")
            launcher.chmod(0o755)
            applications = data_home / "applications"
            applications.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(_linux_desktop(launcher, destination), encoding="utf-8")
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    emit("step", id="install", status="complete")
    emit("artifact", kind="installed_application", path=str(destination))
    return destination


def _sh_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def _linux_launcher(data, mods_dir, selected_mod):
    app = data / "app"
    lines = ["#!/bin/sh", "set -eu"]
    for name, path in (("BDSP_IMG", app / "img"), ("BDSP_NPDM", app / "main.npdm"),
                       ("BDSP_ROMFS", app / "romfs"), ("BDSP_SAVE", data / "saves"),
                       ("BDSP_MODS_DIR", mods_dir), ("BDSP_ICON_DIR", app / "icons/linux"),
                       ("BDSP_LPROJ", app / "lproj")):
        lines.append("export " + name + "=" + _sh_quote(path))
    lines.append("export BDSP_MOD=${BDSP_MOD:-" + _sh_quote(selected_mod) + "}")
    lines.extend(["export SDL_AUDIODRIVER=dummy",
                  "exec " + _sh_quote(app / "bdsp_boot_vk_qt") + ' "$@"'])
    return "\n".join(lines) + "\n"


def _linux_desktop(launcher, app):
    metadata = json.loads((app / "icons/linux/icons.json").read_text(encoding="utf-8"))
    default = metadata.get("default")
    variant = next((item for item in metadata.get("variants", []) if item.get("id") == default), None)
    image = variant.get("image") if variant else None
    if not image or Path(image).name != image:
        raise ValueError("The generated game icon manifest has no valid default icon.")
    icon = app / "icons/linux" / image
    if not icon.is_file():
        raise FileNotFoundError("The generated default game icon is missing.")
    # Desktop Entry quoting uses double quotes, with backslash escapes.
    executable = str(launcher).replace("\\", "\\\\").replace('"', '\\"')
    return ("[Desktop Entry]\nType=Application\nName=BDSP\nExec=\"" + executable +
            "\"\nIcon=" + str(icon) +
            "\nTerminal=false\nCategories=Game;\nStartupWMClass=dev.local.xnubdsp\n")


def build(args):
    emit("hello", protocol=PROTOCOL_VERSION, capabilities=["preflight", "build"])
    root = Path(args.root)
    work = Path(args.work)
    if work.resolve() != (root / "work").resolve():
        emit("error", message="This build pipeline currently uses the checkout's work/ folder.", code=2)
        return 2
    if (sys.platform == "darwin" and args.target not in ("macos", "ios")) or (sys.platform != "darwin" and args.target != "linux"):
        emit("error", message="This target must be built on its native Mac or Linux host.", code=2)
        return 2
    if not Path(args.prod_keys).is_file() or not Path(args.base).exists():
        emit("error", message="Game input or prod.keys is missing.", code=3)
        return 3
    if args.update and not Path(args.update).is_file():
        emit("error", message="The selected update is missing.", code=3)
        return 3
    try:
        code_mod = _mod_exefs(getattr(args, "mod_root", None)) is not None
    except (OSError, ValueError) as error:
        emit("error", message="Mod folder: " + _safe_line(str(error), args), code=3)
        return 3
    if code_mod and (args.target not in ("macos", "ios") or not getattr(args, "ips_helper", None) or
                     not Path(args.ips_helper).is_file()):
        emit("error", message="ExeFS currently needs a Mac host and the packaged ips_patch helper.", code=3)
        return 3
    base = Path(args.base)
    if base.is_dir():
        base_option = "--base-nca-dir"
    elif base.suffix.lower() == ".xci":
        base_option = "--xci"
    elif base.suffix.lower() == ".nsp":
        base_option = "--base-nsp"
    else:
        emit("error", message="Choose a base XCI, base NSP or NCA folder.", code=2)
        return 2
    common = [base_option, args.base, "--prod-keys", args.prod_keys]
    if args.update:
        common += ["--nsp", args.update]
    code = check_build_dependencies(args)
    if code:
        emit("result", ok=False, code=code)
        return code
    if args.target == "macos":
        extract = [str(root / "scripts/build_all.sh"), "--only", "tools,extract",
                   "--target", "macos", "--min-free-gb", str(required_free_gb(args)), *common]
        code = _run_command(extract, args, "extract")
        if code == 0:
            try:
                mod_build = _prepare_code_mod(args, work)
            except (OSError, ValueError) as error:
                emit("error", message="ExeFS preparation failed: " + _safe_line(str(error), args), code=4)
                code = 4
        artifact = work / "builds/macos-recomp" / (mod_build["app_name"] if code == 0 and mod_build else "BDSP.app")
        if code == 0:
            environment = ({"BDSP_EXEFS_DIR": str(mod_build["staged"]),
                            "RECOMP_DIR": str(mod_build["build_dir"]),
                            "BDSP_MOD_NAME": mod_build["name"],
                            "BDSP_MOD_ROOT": str(mod_build["root"]),
                            "BDSP_MODS_DIR": str(mod_build["mods_dir"]),
                            "BDSP_MOD_BUNDLE_ID": mod_build["bundle_id"],
                            "BDSP_MOD_DISPLAY_NAME": mod_build["name"],
                            "BDSP_ICON_SOURCE": str(work / "recomp/icons/source")} if mod_build else {})
            command = [str(root / "scripts/recomp/app/recomp_build.sh")]
            if mod_build:
                command += ["--out", str(artifact)]
            code = _run_command(command, args, "eh_gen",
                                lambda phase: _compile_count(work, "macos", mod_build["build_dir"] if mod_build else None)
                                if phase == "clang" else None, _mac_phase, extra_env=environment)
    elif args.target == "ios":
        code, artifact = _build_ios(args, common)
    else:
        extract = [str(root / "scripts/build_all.sh"), "--only", "tools,extract",
                   "--min-free-gb", str(required_free_gb(args)), *common]
        stages = [
            ("extract", extract, None),
            ("eh_gen", ["bash", "scripts/recomp/linux/local/gen.sh", "c"], None),
            ("clang", ["bash", "scripts/recomp/linux/local/compile.sh", "c"],
             lambda _phase: _compile_count(work, "linux")),
            ("images", ["bash", "scripts/recomp/rt-bdsp/mkimages.sh"], None),
            ("runtime", ["bash", "scripts/recomp/linux/local/vk_build.sh", "--qt"], None),
        ]
        code = 0
        for stage, command, progress in stages:
            if stage == "eh_gen" and code == 0:
                emit("step", id="exefs", status="skipped")
            image_env = {"IMG": "work/recomp/img_gfx",
                         "HLE_LIST": "scripts/recomp/rt-bdsp/hle_nvn.txt"} if stage == "images" else None
            code = _run_command(command, args, stage, progress, extra_env=image_env)
            if code:
                break
        artifact = work / "recomp/bdsp_boot_vk_qt"
    if code == 0 and not artifact.exists():
        emit("error", message="Build reported success but the application was not produced.", code=4)
        return 4
    if code == 0:
        emit("artifact", kind="application", path=str(artifact))
        try:
            install_artifact(args, artifact)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            emit("step", id="install", status="failed")
            emit("error", message="Installation failed: " + _safe_line(str(error), args), code=5)
            code = 5
    emit("result", ok=code == 0, code=code)
    return code


def _interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    sys.dont_write_bytecode = True
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _interrupt)
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("preflight")
    check.add_argument("--root", required=True)
    check.add_argument("--work", required=True)
    check.add_argument("--tools-dir", required=True)
    check.add_argument("--target", choices=("macos", "linux", "ios"), required=True)
    check.add_argument("--min-free-gb", type=int, default=40)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--root", required=True)
    build_parser.add_argument("--work", required=True)
    build_parser.add_argument("--target", choices=("macos", "linux", "ios"), required=True)
    build_parser.add_argument("--base", required=True)
    build_parser.add_argument("--prod-keys", required=True)
    build_parser.add_argument("--update")
    build_parser.add_argument("--mod-root")
    build_parser.add_argument("--mod-name")
    build_parser.add_argument("--mods-dir")
    build_parser.add_argument("--ips-helper")
    build_parser.add_argument("--ios-device", help="Connected device identifier, UDID or name")
    build_parser.add_argument("--ios-bundle-id", help="Separate application identifier for device testing")
    build_parser.add_argument("--install-root", help="Override the installation root for local testing")
    args = parser.parse_args(argv)
    if args.command == "preflight":
        return preflight(args)
    try:
        return build(args)
    except (OSError, ValueError) as error:
        emit("error", message="Build could not continue: " + _safe_line(str(error), args), code=4)
        emit("result", ok=False, code=4)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
