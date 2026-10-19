#!/usr/bin/env python3
"""Stufenlogik für scripts/build_all.sh (Auswahl, Marker mit Eingabe-Hashes, Preflight, Editor-Erkennung).

Nur Standardbibliothek. Gibt nie Schlüsselmaterial, Team-IDs oder Spielinhalte aus; Marker und Logs
enthalten nur Hashes, Größen und Zählwerte.

Unterbefehle (Aufruf: build_stages.py <befehl> ...):
  stages [--stage S ...] [--from S] [--to S] [--only S ...]   gewählte Stufen in fester Reihenfolge
  stage-hash --stage S --root R --work W [--target T] [--profile P]   Eingabe-Hash einer Stufe
  marker-check --work W --stage S --hash H       Exit 0, wenn der Marker zum Hash passt
  marker-write --work W --stage S --hash H [--note K=V ...]
  marker-clear --work W --stage S
  preflight --stages "a b" --target T --root R --work W [--min-free-gb N] [--tools-dir D] ...
  editor-open --project DIR                      Exit 0 und PID, wenn ein Editor das Projekt hält
  env-get --file F --key K                       Wert aus einer KEY=Wert-Datei (z. B. work/local.env)
  tree-size --path P                             "<Dateien> <Bytes>" eines Ordners
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

# Exit-Codes (müssen zu build_all.sh passen)
EX_USAGE = 2
EX_TOOLS = 4
EX_DISK = 8

STAGES = ["tools", "extract", "il2cpp", "recomp", "masterdata", "shaders", "video", "audio", "assets", "stubs", "unity-build", "deploy"]
ALIASES = {"unity": "unity-build", "xcode": "deploy", "shader": "shaders", "videos": "video", "macapp": "recomp"}
UNITY_VERSION = "6000.3.26f1"
MARKER_SCHEMA = 1
MIN_FREE_GB = 60
RECOMP_MIN_FREE_GB = 25   # Generator-C, Objekte, Binärdatei, App, Zwischenablagen (gemessen rund 3 GB; der Rest ist Reserve für Compiler und Auslagerung)
HEAVY_STAGES = {"extract", "il2cpp", "masterdata", "shaders", "video", "assets", "stubs", "unity-build", "deploy"}
TARGETS = ("macos", "ios", "all")


def normalize_stage(name):
    name = name.strip().lower()
    name = ALIASES.get(name, name)
    if name not in STAGES:
        raise ValueError("Unbekannte Stufe: %s (bekannt: %s)" % (name, " ".join(STAGES)))
    return name


def _names(values):
    out = []
    for v in values or []:
        out.extend(p for p in re.split(r"[,\s]+", v) if p)
    return out


def select_stages(requested=(), from_stage=None, to_stage=None, only=()):
    """Wählt Stufen in kanonischer Reihenfolge. `all` oder keine Angabe = alle."""
    only_names = _names(only)
    if only_names:
        if from_stage or to_stage:
            raise ValueError("--only lässt sich nicht mit --from/--to kombinieren")
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
        raise ValueError("--from (%s) liegt hinter --to (%s)" % (from_stage, to_stage))
    result = [s for i, s in enumerate(STAGES) if lo <= i <= hi and s in chosen]
    if not result:
        raise ValueError("Keine Stufe im gewählten Bereich")
    return result


# ---------- Hashes und Marker ----------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def hash_file(path):
    if not os.path.isfile(path):
        return "fehlt"
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


def hash_listing(root, suffixes=None):
    """Hash über relative Pfade und Größen (schnell, für große Ordner)."""
    if not os.path.isdir(root):
        return "fehlt"
    h = hashlib.sha256()
    for p in _walk(root):
        if suffixes and not p.lower().endswith(tuple(suffixes)):
            continue
        h.update(("%s\t%d\n" % (os.path.relpath(p, root), os.path.getsize(p))).encode())
    return h.hexdigest()


def hash_tree_content(root, suffixes=None, skip_dirs=("Library", "Temp", "Logs", "obj", "UserSettings")):
    """Hash über relative Pfade und Inhalte (für kleine Quellordner)."""
    if not os.path.isdir(root):
        return "fehlt"
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
    """Eingaben-Kern aus manifest.json (Stufe extract): Titel, Version, main-Hash, RomFS-Zahlen."""
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
    return m["hash"] if m else "kein-marker"


def read_env_value(path, key):
    """Wert aus einer Datei mit KEY=Wert-Zeilen (optional `export`, Anführungszeichen, #-Kommentare)."""
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


def stage_hash(stage, root, work, target="all", profile="h265-crf18", env=None):
    """Hash der Eingaben einer Stufe; ändert sich er, läuft die Stufe neu. Liefert (hash, teile)."""
    env = os.environ if env is None else env
    scripts = os.path.join(root, "scripts")
    core = extract_core(work)
    parts = {"stage": stage, "extract": core if core else "kein-manifest"}

    def files(*names):
        return {n: hash_file(os.path.join(scripts, n)) for n in names}

    if stage == "il2cpp":
        parts["metadata"] = hash_file(os.path.join(work, "romfs", "Data", "Managed", "Metadata", "global-metadata.dat"))
        parts["dumper"] = hash_file(os.path.join(root, "tools", "il2cppdumper-bin", "Il2CppDumper.dll"))
    elif stage == "masterdata":
        parts["scripts"] = files("masterdata_export.py")
    elif stage in ("recomp-gen", "recomp"):
        # Generator: Module des Dumps, eigene Generatorskripte und der Klon, dessen Werkzeuge er zur Laufzeit importiert
        rec = os.path.join(scripts, "recomp")
        parts["modules"] = {m: hash_file(os.path.join(work, "exefs", m)) for m in ("main", "sdk", "subsdk0", "rtld")}
        parts["generator"] = {n: hash_file(os.path.join(rec, n)) for n in
                              ("eh_gen.py", "eh_lsda.py", "eh_pick.py", "gen_all.sh", "c_exact/fp_env.h", "rt/cpu.h")}
        parts["las_tools"] = hash_tree_content(os.path.join(rec, "upstream", "generator"), (".py",), skip_dirs=("__pycache__",))
        if stage == "recomp":
            # Laufzeit, NVN-Schicht (vendort + Patches), Übersetzer, App-Hülle; die Teilmarker bilden Generator und Objekte ab
            skip = ("test", "vulkan", "__pycache__")
            parts["gen"] = _marker_hash(work, "recomp-gen")
            parts["obj"] = _marker_hash(work, "recomp-obj")
            parts["runtime"] = hash_tree_content(os.path.join(rec, "rt-bdsp"), (".c", ".h", ".m", ".sh", ".patch", ".txt"), skip_dirs=skip)
            parts["nvn_las"] = hash_tree_content(os.path.join(rec, "rt-bdsp", "nvn", "upstream", "nvn"), (".c", ".h", ".m"), skip_dirs=("vulkan",))
            parts["translator"] = hash_tree_content(os.path.join(root, "shader_translator"), (".c", ".h"), skip_dirs=("build", "__pycache__"))
            parts["app"] = hash_tree_content(os.path.join(rec, "app"), (".sh", ".py", ".in", ".entitlements"), skip_dirs=("__pycache__",))
            parts["build_scripts"] = files("recomp/build_all.sh", "recomp/test/compile_chunk.sh")
            parts["npdm"] = hash_file(os.path.join(work, "exefs", "main.npdm"))
            parts["options"] = env.get("XNU_RECOMP_OPTS", "")
    elif stage == "shaders":
        parts["scripts"] = files("shader_build.sh", "shader_extract_blobs.py", "shader_inventory.py",
                                 "shader_fidelity.py", "shader_wrap_all.py", "shader_wrap.py")
        tr = os.path.join(root, "shader_translator")
        parts["translator"] = hash_tree_content(tr, (".c", ".h", "makefile"), skip_dirs=("build", "__pycache__"))
        used = env.get("SHADER_USED", "")
        parts["used"] = hash_file(used) if used else "keine"
    elif stage == "video":
        parts["scripts"] = files("video_convert.sh")
        parts["profile"] = profile
        parts["movies"] = hash_listing(os.path.join(work, "romfs", "Data", "StreamingAssets", "Movie"), (".webm",))
    elif stage == "assets":
        parts["bundles"] = hash_listing(os.path.join(work, "romfs", "Data", "StreamingAssets", "AssetAssistant"))
        parts["retarget"] = files("bundle_retarget.py", "texture_transcode.py")
        parts["platform"] = env.get("XNU_BUNDLE_PLATFORM", "") or "auto"
        parts["texture_format"] = env.get("XNU_TEXTURE_FORMAT", "") or "auto"
        subset = env.get("XNU_BUNDLE_SUBSET", "")
        parts["subset"] = hash_file(subset) if subset else "alle"
        parts["materials"] = hash_listing(os.path.join(work, "materials"))
        parts["video"] = _marker_hash(work, "video")
        parts["masterdata"] = _marker_hash(work, "masterdata")
        parts["audio"] = _marker_hash(work, "audio")
    elif stage == "stubs":
        parts["scripts"] = files("stub_gen.py", "stub_dump.py")
        parts["il2cpp"] = _marker_hash(work, "il2cpp")
        parts["bundles"] = hash_listing(os.path.join(work, "romfs", "Data", "StreamingAssets", "AssetAssistant"))
    elif stage == "unity-build":
        unity = os.path.join(root, "unity")
        parts["assets"] = _marker_hash(work, "assets")
        parts["stubs"] = _marker_hash(work, "stubs")
        parts["shaders"] = _marker_hash(work, "shaders")
        parts["sources"] = {
            "Scripts": hash_tree_content(os.path.join(unity, "Assets", "Scripts"), (".cs", ".asmdef")),
            "Scenes": hash_tree_content(os.path.join(unity, "Assets", "Scenes"), (".unity",)),
            "ProjectSettings": hash_tree_content(os.path.join(unity, "ProjectSettings"), (".asset", ".txt")),
            "Packages": hash_file(os.path.join(unity, "Packages", "manifest.json")),
        }
        parts["target"] = target
        parts["editor"] = UNITY_VERSION
    elif stage == "deploy":
        parts["unity-build"] = _marker_hash(work, "unity-build")
        team = (env.get("TEAM_ID") or read_env_value(env.get("XNU_LOCAL_ENV") or os.path.join(root, "work", "local.env"), "TEAM_ID") or "")
        parts["team"] = _sha(team.encode())[:16] if team else "keine"  # nur ein Hash, nie die ID
        parts["target"] = target
    digest = _sha(json.dumps(parts, sort_keys=True).encode())
    return digest, parts


# ---------- Editor-Erkennung ----------

def find_editor_pid(ps_text, project_dir):
    """PID des Unity-Editors, der `project_dir` offen hat (nicht: Import-Worker, Shader-Compiler)."""
    want = os.path.realpath(project_dir)
    for line in ps_text.splitlines():
        line = line.strip()
        m = re.match(r"(\d+)\s+(.*)$", line)
        if not m:
            continue
        pid, cmd = m.groups()
        if "Unity.app/Contents/MacOS/Unity" not in cmd:
            continue
        if "AssetImportWorker" in cmd or "-adb2" in cmd:
            continue
        pm = re.search(r"-projectpath\s+(.+?)(?=\s+-[A-Za-z]|$)", cmd, re.IGNORECASE)
        if pm and os.path.realpath(pm.group(1).strip().strip('"')) == want:
            return int(pid)
    return None


def editor_open(project_dir):
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return find_editor_pid(out, project_dir)


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
    return shutil.disk_usage(probe).free / (1 << 30)


def _run_ok(cmd, env=None, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return False, ""


def preflight(stages, target, root, work, tools_dir=None, unity_root="/Applications/Unity/Hub/Editor",
              developer_dir="/Applications/Xcode.app/Contents/Developer", min_free_gb=MIN_FREE_GB,
              which=shutil.which, run=_run_ok, free=free_gb, home=None):
    """Prüft nur, was die gewählten Stufen brauchen; nichts wird installiert. Eintrag: dict(name, ok, detail, hint, level)."""
    tools_dir = tools_dir or os.path.join(root, "tools")
    home = home or os.path.expanduser("~")
    s = set(stages)
    want_mac = target in ("macos", "all")
    want_ios = target in ("ios", "all")
    items = []

    def add(name, ok, detail="", hint="", level="fehlt"):
        items.append({"name": name, "ok": bool(ok), "detail": detail, "hint": hint, "level": level})

    major = sys.version_info
    add("python3 >= 3.9", major >= (3, 9), "%d.%d.%d" % major[:3], "brew install python")
    if s & HEAVY_STAGES:
        gb = free(work)
        add("Plattenplatz >= %d GB frei" % min_free_gb, gb >= min_free_gb, "%.0f GB frei unter %s" % (gb, work),
            "Platz schaffen (Caches, alte work/-Unterordner) oder bewusst weniger verlangen: --min-free-gb N "
            "(Gesamtbedarf mit Bundles, Kopien und Builds grob 60 GB)")

    hactool = os.path.join(tools_dir, "hactool", "hactool")
    if "tools" in s:
        for c in ("git", "make", "cc"):
            add(c + " (für hactool)", which(c), "", "xcode-select --install (Command Line Tools)")
    elif "extract" in s:
        add("hactool", os.access(hactool, os.X_OK), hactool,
            "scripts/build_all.sh tools (klont und baut hactool lokal, ohne sudo)")
    if "extract" in s and "tools" in s and not os.access(hactool, os.X_OK):
        add("hactool", True, "wird von Stufe tools gebaut", level="hinweis")

    if "il2cpp" in s:
        ok, out = (False, "")
        dotnet = which("dotnet")
        if dotnet:
            ok, out = run([dotnet, "--version"])
        ver = out.strip().split("\n")[0] if ok else ""
        good = bool(ver) and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) >= 8
        add("dotnet >= 8", good, ver or "nicht gefunden",
            "brew install dotnet (Formel, ohne sudo; alternativ den Installer von dotnet.microsoft.com, der ein Admin-Passwort verlangt)")
        dumper = os.path.join(tools_dir, "il2cppdumper-bin", "Il2CppDumper.dll")
        add("Il2CppDumper (gebaut)", os.path.isfile(dumper), dumper,
            "git clone https://github.com/Perfare/Il2CppDumper tools/Il2CppDumper && "
            "dotnet build tools/Il2CppDumper/Il2CppDumper -c Release -f net8.0 -o tools/il2cppdumper-bin")

    if s & {"masterdata", "shaders", "stubs"}:
        add("Python-Pakete (UnityPy, lz4) in tools/pydeps", os.path.isdir(os.path.join(tools_dir, "pydeps", "UnityPy")),
            os.path.join(tools_dir, "pydeps"), "python3 -m pip install --target tools/pydeps UnityPy lz4")
    if "shaders" in s:
        for c in ("make", "cc"):
            add(c + " (für shader_translator)", which(c), "", "xcode-select --install (Command Line Tools)")

    if "recomp" in s and want_mac:
        if not (s & HEAVY_STAGES):   # sonst deckt der allgemeine Platz-Check (strenger) das schon ab
            need = min(RECOMP_MIN_FREE_GB, min_free_gb)
            gb = free(work)
            add("Plattenplatz >= %d GB frei (Stufe recomp)" % need, gb >= need, "%.0f GB frei unter %s" % (gb, work),
                "Platz schaffen (alte work/recomp-Unterordner wie img*, gen, obj*, spike2 löschen) oder bewusst weniger verlangen: --min-free-gb N")
        add("clang (Homebrew-LLVM im PATH)", which("clang"), which("clang") or "", "brew install llvm und /opt/homebrew/opt/llvm/bin vor /usr/bin in den PATH")
        ok, _ = run(["/usr/bin/xcrun", "--find", "clang"])
        add("Apple-clang (Objective-C, Command Line Tools)", ok, "", "xcode-select --install")
        for c, hint in (("pkg-config", "brew install pkg-config"), ("rsync", "rsync ist Teil von macOS"), ("codesign", "xcode-select --install"),
                        ("install_name_tool", "xcode-select --install"), ("otool", "xcode-select --install"),
                        ("iconutil", "xcode-select --install"), ("plutil", "plutil ist Teil von macOS")):
            add(c + " (für die App)", which(c), "", hint)
        pc = which("pkg-config")
        ok, _ = run([pc, "--exists", "sdl3", "libavcodec", "libavformat", "libavutil"]) if pc else (False, "")
        add("SDL3 und FFmpeg-Bibliotheken (pkg-config)", ok, "", "brew install sdl3 ffmpeg")
        pyd = os.path.join(tools_dir, "pydeps")
        add("Python-Pakete capstone, unicorn in tools/pydeps (Generator)",
            os.path.isdir(os.path.join(pyd, "capstone")) and os.path.isdir(os.path.join(pyd, "unicorn")), pyd,
            "python3 -m pip install --target tools/pydeps capstone unicorn")
        up = os.path.join(root, "scripts", "recomp", "upstream")
        add("Vendorte LASRecomp-Teile (Generator, Header; MIT)",
            os.path.isfile(os.path.join(up, "generator", "gen.py")) and os.path.isfile(os.path.join(up, "runtime", "cpu.h")), up,
            "git checkout -- scripts/recomp/upstream (Ordner fehlt im Arbeitsstand)")

    if "video" in s:
        ffmpeg = which("ffmpeg")
        ok, out = run([ffmpeg, "-hide_banner", "-encoders"]) if ffmpeg else (False, "")
        add("ffmpeg mit libx265", ok and "libx265" in out, ffmpeg or "nicht gefunden", "brew install ffmpeg")

    if s & {"unity-build", "deploy"}:
        editor = os.path.join(unity_root, UNITY_VERSION)
        have = os.path.isdir(os.path.join(editor, "Unity.app"))
        if "unity-build" in s:
            add("Unity Editor " + UNITY_VERSION, have, editor,
                "Unity Hub installieren (brew install --cask unity-hub, das fragt ggf. selbst nach Admin-Rechten) und dann: "
                "unity install %s -a arm64   bzw.   Unity Hub -- --headless install --version %s --architecture arm64" % (UNITY_VERSION, UNITY_VERSION))
            if want_mac:
                mac = os.path.join(editor, "Unity.app", "Contents", "PlaybackEngines", "MacStandaloneSupport",
                                   "Variations", "macos_arm64_player_nondevelopment_il2cpp")
                add("Unity-Modul Mac Build Support (IL2CPP)", os.path.isdir(mac), "",
                    "unity install-modules -e %s -a arm64 -m mac-il2cpp --non-interactive" % UNITY_VERSION)
            if want_ios:
                add("Unity-Modul iOS Build Support", os.path.isdir(os.path.join(editor, "PlaybackEngines", "iOSSupport")), "",
                    "unity install-modules -e %s -a arm64 -m ios --non-interactive" % UNITY_VERSION)
            cli = which("unity") or (os.path.join(home, ".unity", "bin", "unity")
                                     if os.access(os.path.join(home, ".unity", "bin", "unity"), os.X_OK) else None)
            add("unity CLI (optional)", cli, cli or "nicht gefunden; Rückfall: Editor direkt im Batchmodus",
                "Unity-CLI von unity.com installieren", level="hinweis" if not cli else "fehlt")
        xcode_ok = os.path.isdir(developer_dir)
        out = ""
        if xcode_ok:
            xcode_ok, out = run(["xcodebuild", "-version"], env=dict(os.environ, DEVELOPER_DIR=developer_dir))
        add("Xcode (DEVELOPER_DIR)", xcode_ok, (out.strip().replace("\n", " ") if xcode_ok else developer_dir),
            "Xcode aus dem App Store oder von developer.apple.com in /Applications installieren, Lizenz akzeptieren "
            "(xcodebuild -license, braucht Admin) und DEVELOPER_DIR=<Xcode>/Contents/Developer setzen; "
            "xcode-select -s wird absichtlich nicht benutzt")
    return items


def format_preflight(items):
    """Zeilen für die Ausgabe plus Installationsliste; gibt (zeilen, fehlend, disk_fehlt) zurück."""
    lines, missing, disk = [], [], False
    for it in items:
        if it["ok"]:
            tag = "OK    " if it["level"] != "hinweis" else "HINWEIS"
        else:
            tag = "FEHLT " if it["level"] == "fehlt" else "HINWEIS"
        lines.append("  %s %s%s" % (tag, it["name"], " (%s)" % it["detail"] if it["detail"] else ""))
        if not it["ok"] and it["level"] == "fehlt":
            missing.append(it)
            if it["name"].startswith("Plattenplatz"):
                disk = True
    return lines, missing, disk


def install_list(missing):
    out = ["Installationsliste (keine sudo-Befehle werden ausgeführt; bitte selbst ausführen):"]
    for i, it in enumerate(m for m in missing if not m["name"].startswith("Plattenplatz")):
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
    p.add_argument("--profile", default="h265-crf18")
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
    p.add_argument("--unity-root", default="/Applications/Unity/Hub/Editor")
    p.add_argument("--developer-dir", default="/Applications/Xcode.app/Contents/Developer")
    p.add_argument("--min-free-gb", type=int, default=MIN_FREE_GB)
    p = sub.add_parser("editor-open")
    p.add_argument("--project", required=True)
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
            print("FEHLER: %s" % e, file=sys.stderr)
            return EX_USAGE
        return 0
    if a.cmd == "stage-hash":
        digest, parts = stage_hash(a.stage, a.root, a.work, a.target, a.profile)
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
        items = preflight(a.stages.split(), a.target, a.root, a.work, a.tools_dir, a.unity_root,
                          a.developer_dir, a.min_free_gb)
        lines, missing, disk = format_preflight(items)
        print("\n".join(lines))
        for m in missing:
            if m["name"].startswith("Plattenplatz"):
                print("Platz: " + m["hint"])
        if any(not m["name"].startswith("Plattenplatz") for m in missing):
            print("\n".join(install_list(missing)))
        if disk:
            return EX_DISK if all(m["name"].startswith("Plattenplatz") for m in missing) else EX_TOOLS
        return EX_TOOLS if missing else 0
    if a.cmd == "editor-open":
        pid = editor_open(a.project)
        if pid:
            print(pid)
            return 0
        return 1
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
