"""Prebuilt SPIR-V shaders for the Vulkan targets (Windows, Linux), prepared on the user's own computer.

The renderer turns every Maxwell shader of the game into GLSL and compiles it with shaderc while the game runs; its disk cache
(`spirv/<hash of stage + GLSL>.spv`) only helps from the second run on. This stage does that work at build time: the game's own
shader programs are translated to GLSL with the same translator and the same ShaderKey the renderer uses for draws, compiled with the
renderer's own compile step (`spirv_warm`, sharing spv_cache.h with the renderer) and left in a read-only folder that the installed
application reads next to its own cache (`BDSP_PACKAGED_CACHE_DIR`). A GLSL text the renderer produces is looked up under the same
hash, so a translator change makes the old files unreachable and the stamp below rebuilds them.

Only the user's data on the user's machine is used; nothing is downloaded or uploaded. Every problem here ends in a skipped stage:
the game then compiles its shaders while it runs, as before. Own code."""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = 1
TARGETS = ("windows", "windows-arm64", "linux")
# The renderer asks for the fragment shader with the varyings its vertex shader writes. The pairs are not known offline, and a
# fragment shader reads only inputs the vertex shader provides, so "everything provided" yields the text of nearly every real pair.
VS_OUT_MASK = "0xffffffff"
TRANSLATOR_SOURCES = ("main.c", "translate.c", "container.c", "container.h", "shader.h")
WARM_SOURCES = ("scripts/recomp/runtime/nvn/vulkan/spirv_warm.c", "scripts/recomp/runtime/nvn/vulkan/src/nvn/vulkan/spv_cache.h")
SCRIPT_SOURCES = ("scripts/shader_extract_blobs.py", "scripts/install/vk_shaders.py")
BUNDLES = ("romfs/Data/StreamingAssets/AssetAssistant/Dpr/shaders",
           "romfs/Data/StreamingAssets/AssetAssistant/Effects/fxparticle",
           "romfs/Data/resources.assets",
           "romfs/Data/StreamingAssets/AssetAssistant/Dpr/tmpshader")
PROGRESS = re.compile(r"^warm: progress (\d+) of (\d+)$")
DONE = re.compile(r"^warm: done compiled (\d+) present (\d+) failed (\d+)$")


class Missing(Exception):
    """A prerequisite is not there: the stage is skipped."""


def applies(target):
    return target in TARGETS


def folders(work):
    base = Path(work) / "shaders" / "vulkan"
    return {"base": base, "tools": base / "tools", "glsl": base / "glsl", "stage": base / "prebuilt.new",
            "prebuilt": base / "prebuilt", "stamp": base / "stamp", "blobs": Path(work) / "shaders" / "blobs"}


def sha256_of(parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def stamp(root, work, toolchain="", shaderc=""):
    """Everything the output depends on: the translator and warm tool sources, this script and the extractor, the game's shader
    bundles (by size), the compiler that builds the tools and the shaderc that compiles."""
    root, work = Path(root), Path(work)
    parts = [VERSION, VS_OUT_MASK, toolchain, shaderc]
    parts += [(root / "shader_translator" / name).read_bytes() for name in TRANSLATOR_SOURCES]
    parts += [(root / name).read_bytes() for name in WARM_SOURCES + SCRIPT_SOURCES]
    for bundle in BUNDLES:
        path = work / bundle
        parts.append("%s:%s" % (bundle, path.stat().st_size if path.is_file() else "none"))
    return sha256_of(parts)


def parse_progress(line):
    """(completed, total) from a 'warm: progress N of M' line of spirv_warm, else None."""
    found = PROGRESS.match(line.strip())
    return (int(found.group(1)), int(found.group(2))) if found else None


def prebuilt_count(prebuilt):
    spirv = Path(prebuilt) / "spirv"
    return sum(1 for _ in spirv.glob("*.spv")) if spirv.is_dir() else 0


def tool_commands(root, directory, tools):
    """Compiler command lines for the two helpers. tools: {'cc': [...], 'cflags': [...], 'libs': [...], 'suffix': '.exe' or ''}."""
    root, directory = Path(root), Path(directory)
    suffix = tools.get("suffix", "")
    translator = directory / ("maxwell2msl" + suffix)
    warm = directory / ("spirv_warm" + suffix)
    sources = [str(root / "shader_translator" / name) for name in ("main.c", "translate.c", "container.c")]
    vulkan = root / "scripts/recomp/runtime/nvn/vulkan"
    return {
        "translator": (translator, [*tools["cc"], "-O2", "-std=gnu11", "-w", "-o", str(translator), *sources, "-lm", "-lpthread"]),
        "warm": (warm, [*tools["cc"], "-O2", "-std=gnu11", "-w", *tools.get("cflags", []), "-o", str(warm),
                        str(vulkan / "spirv_warm.c"), *tools.get("libs", []), "-lpthread"]),
    }


def translation_list(blobs, listing):
    """Writes the batch list (every vertex and fragment program of the game) and returns how many programs it names."""
    index = json.loads((Path(blobs) / "index.json").read_text(encoding="utf-8"))["blobs"]
    lines = ["%s %s\n" % (entry["stage"], Path(blobs) / (entry["hash"] + ".bin")) for entry in index if entry["stage"] in ("vs", "fs")]
    Path(listing).write_text("".join(lines), encoding="utf-8")
    return len(lines)


def run_streaming(command, env=None, cwd=None, on_line=None):
    """Runs a command, hands every output line to on_line, returns the exit status."""
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    for line in process.stdout:
        if on_line:
            on_line(line.rstrip("\r\n"))
    return process.wait()


def linux_tools(run=subprocess.run):
    """The compiler and shaderc of this Linux computer (the same development packages the runtime build needs)."""
    compiler = os.environ.get("CC") or "clang"
    try:
        version = run([compiler, "--version"], capture_output=True, text=True, check=True).stdout
        for module in ("shaderc_shared", "shaderc"):
            found = run(["pkg-config", "--cflags", "--libs", module], capture_output=True, text=True)
            if found.returncode == 0:
                modversion = run(["pkg-config", "--modversion", module], capture_output=True, text=True).stdout.strip()
                return {"cc": [compiler], "suffix": "", "cflags": shlex.split(found.stdout), "libs": [], "toolchain": version.strip(),
                        "shaderc": module + " " + modversion}
    except (OSError, subprocess.SubprocessError) as error:
        raise Missing("the C compiler or pkg-config is missing (%s)" % error) from error
    raise Missing("the shaderc development package is missing")


def prepare(root, work, tools, log, progress=None, python=None, run=run_streaming, force=False, jobs=None):
    """Fills <work>/shaders/vulkan/prebuilt/spirv. Returns (status, detail): 'complete', 'reused' or 'skipped'. Never raises.

    tools: {'cc': [...], 'cflags': [...], 'libs': [...], 'suffix': '' or '.exe', 'env': {...}, 'toolchain': text, 'shaderc': text}
    or a function returning it (called inside the guard). log(message) receives the 'shaders: ...' progress lines;
    progress(done, total) the SPIR-V compile count; run(command, env, cwd, on_line) -> status is replaceable for tests."""
    try:
        return _prepare(Path(root), Path(work), tools() if callable(tools) else tools, log, progress, python or sys.executable, run,
                        force, jobs)
    except Missing as error:
        log("shaders: skipped: %s" % error)
        return "skipped", str(error)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        log("shaders: failed: %s" % error)
        return "skipped", str(error)


def _prepare(root, work, tools, log, progress, python, run, force, jobs):
    place = folders(work)
    wanted = stamp(root, work, tools.get("toolchain", ""), tools.get("shaderc", ""))
    if not (work / BUNDLES[0]).is_file():
        raise Missing("the game's shader bundle is missing")
    if (not force and place["stamp"].is_file() and place["stamp"].read_text(encoding="utf-8").strip() == wanted
            and prebuilt_count(place["prebuilt"])):
        count = prebuilt_count(place["prebuilt"])
        log("shaders: reusing the SPIR-V shaders prepared earlier (%d)" % count)
        return "reused", str(count)
    environment = dict(os.environ)
    environment.update(tools.get("env", {}))

    def checked(command, what, cwd=None, on_line=None, env=None):
        tail = []

        def keep(line):
            tail.append(line)
            del tail[:-6]
            if on_line:
                on_line(line)
        if run(command, env or environment, cwd, keep):
            raise RuntimeError("%s failed: %s" % (what, " ".join(tail)[-300:]))

    log("shaders: reading the shader programs of the game")
    place["base"].mkdir(parents=True, exist_ok=True)
    checked([python, str(root / "scripts/shader_extract_blobs.py"), "--out", str(place["blobs"]), "--romfs", str(work / "romfs"),
             "--extra"], "the shader extraction", cwd=str(root), env={**environment, "PYTHONDONTWRITEBYTECODE": "1"})
    log("shaders: building the translator")
    place["tools"].mkdir(parents=True, exist_ok=True)
    commands = tool_commands(root, place["tools"], tools)
    for name in ("translator", "warm"):
        binary, command = commands[name]
        binary.unlink(missing_ok=True)
        checked(command, "building the %s" % name)
        if not binary.is_file():
            raise RuntimeError("building the %s produced no program" % name)
    log("shaders: translating")
    shutil.rmtree(place["glsl"], ignore_errors=True)
    place["glsl"].mkdir(parents=True)
    listing = place["base"] / "translate-list.txt"
    programs = translation_list(place["blobs"], listing)
    checked([str(commands["translator"][0]), "--batch", str(listing), "--emit-cache", str(place["glsl"]), "-o",
             str(place["base"] / "translate-log.jsonl"), "--glsl", "--vs-out-mask", VS_OUT_MASK], "the translation")
    texts = sum(1 for _ in place["glsl"].glob("*.glsl"))
    if not texts:
        raise RuntimeError("the translation produced no shader")
    log("shaders: %d distinct shaders from %d programs" % (texts, programs))
    log("shaders: compiling the SPIR-V shaders")
    shutil.rmtree(place["stage"], ignore_errors=True)
    result = {}

    def follow(line):
        counted = parse_progress(line)
        if counted and progress:
            progress(*counted)
        done = DONE.match(line.strip())
        if done:
            result["compiled"], result["present"], result["failed"] = (int(value) for value in done.groups())
    command = [str(commands["warm"][0]), "--glsl", str(place["glsl"]), "--out", str(place["stage"]),
               "--jobs", str(jobs or max(1, min(16, (os.cpu_count() or 2) - 1)))]
    status = run(command, environment, None, follow)
    ready = prebuilt_count(place["stage"])
    if status not in (0, 1) or not ready or ready < texts // 2:
        shutil.rmtree(place["stage"], ignore_errors=True)
        raise RuntimeError("the SPIR-V compilation failed (status %s, %d of %d files)" % (status, ready, texts))
    shutil.rmtree(place["prebuilt"], ignore_errors=True)
    os.replace(place["stage"], place["prebuilt"])
    shutil.rmtree(place["glsl"], ignore_errors=True)
    place["stamp"].write_text(wanted + "\n", encoding="utf-8")
    failed = result.get("failed", 0)
    log("shaders: %d SPIR-V shaders ready%s" % (ready, " (%d did not compile and are built while the game runs)" % failed if failed else ""))
    return "complete", str(ready)
