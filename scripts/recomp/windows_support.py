"""Windows target contract and PE dependency inspection. Standard library only."""
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "installer" / "assets" / "windows-dependencies.json"


def architecture(value=None):
    value = (value or platform.machine()).lower()
    if value in ("amd64", "x86_64"):
        return "x86_64"
    if value in ("arm64", "aarch64"):
        return "aarch64"
    raise ValueError("Windows requires an amd64 or ARM64 host/target")


def contract(path=CONTRACT):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("abi") != "llvm-mingw-ucrt":
        raise ValueError("Unsupported Windows dependency contract")
    return data


def profile(target=None, host=None):
    data = contract()
    host, target = architecture(host), architecture(target)
    selected = data["profiles"][target]
    return {**selected, "host": host, "target": target, "abi": data["abi"],
            "simd": data["simd"],
            "cache_key": f"windows-{host}-to-{target}-{data['abi']}-simd-c"}


def prerequisite_items(root, work, target=None):
    """Fail closed until every release input is pinned and acceptance is recorded."""
    data = contract(Path(root) / "installer" / "assets" / "windows-dependencies.json")
    items = []
    if sys.platform != "win32":
        items.append({"name": "Native Windows host", "ok": False, "level": "missing",
                      "hint": "Build the Windows target on Windows; no Linux fallback is used."})
    else:
        version = sys.getwindowsversion()
        items.append({"name": "Windows 10 22H2 (19045) or Windows 11",
                      "ok": version.major >= 10 and version.build >= data["minimum_windows_build"],
                      "level": "missing", "hint": "Windows builds older than 19045 are not supported."})
    selected = data["profiles"][architecture(target)]
    items.append({"name": "Windows target acceptance", "ok": selected["accepted"],
                  "level": "missing", "hint": "This target is not yet qualified for a playable release."})
    for component in data["components"]:
        # Empty arrays are deliberately not downloadable plans.
        items.append({"name": component["id"] + " locked Windows package", "ok": False,
                      "level": "missing", "hint": component["qualification"]})
    for blocker in data["release_blockers"]:
        items.append({"name": blocker, "ok": False, "level": "missing", "hint": ""})
    destination = Path(work).resolve()
    while not destination.exists():
        destination = destination.parent
    free = shutil.disk_usage(destination).free
    minimum = data["minimum_free_gb"]
    items.append({"name": f"Disk space >= {minimum} GB", "ok": free >= minimum * 10**9,
                  "level": "missing", "detail": f"{free / 10**9:.1f} GB free",
                  "hint": "Select a local build volume with enough space."})
    return items


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PE:
    """Bounded PE32+ reader for normal and delay-load DLL import names."""
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if self.data[:2] != b"MZ":
            raise ValueError("Expected PE executable: " + self.path.name)
        pe = self.unpack("<I", 0x3c)[0]
        if self.slice(pe, 4) != b"PE\0\0":
            raise ValueError("Invalid PE signature: " + self.path.name)
        self.machine, count = self.unpack("<HH", pe + 4)
        optional_size = self.unpack("<H", pe + 20)[0]
        optional = pe + 24
        if optional_size < 112 or self.unpack("<H", optional)[0] != 0x20b:
            raise ValueError("Expected 64-bit PE optional header: " + self.path.name)
        self.slice(optional, optional_size)
        self.header_size = self.unpack("<I", optional + 60)[0]
        self.image_base = self.unpack("<Q", optional + 24)[0]
        directory_count = self.unpack("<I", optional + 108)[0]
        if directory_count > (optional_size - 112) // 8:
            raise ValueError("Invalid PE directory count")
        self.directories = [self.unpack("<II", optional + 112 + i * 8)
                            for i in range(directory_count)]
        self.sections = []
        for i in range(count):
            section = optional + optional_size + i * 40
            self.slice(section, 40)
            virtual_size, rva, raw_size, offset = self.unpack("<IIII", section + 8)
            self.slice(offset, raw_size)
            self.sections.append((rva, raw_size, offset))

    def slice(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.data) - size:
            raise ValueError("Truncated PE: " + self.path.name)
        return self.data[offset:offset + size]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.slice(offset, struct.calcsize(fmt)))

    def location(self, rva, size):
        if rva < self.header_size and rva + size <= self.header_size:
            self.slice(rva, size)
            return rva
        for start, length, offset in self.sections:
            if start <= rva and rva + size <= start + length:
                return offset + rva - start
        raise ValueError("Unmapped PE RVA: " + self.path.name)

    def dll_name(self, rva):
        name = bytearray()
        for i in range(256):
            byte = self.slice(self.location(rva + i, 1), 1)[0]
            if not byte:
                text = name.decode("ascii")
                if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.dll", text, re.I):
                    raise ValueError("Invalid PE DLL name")
                return text.lower()
            name.append(byte)
        raise ValueError("Unterminated PE DLL name")

    def imports(self):
        result = set()
        for index, width, name_index in ((1, 20, 3), (13, 32, 1)):
            if index >= len(self.directories):
                continue
            rva, size = self.directories[index]
            if not rva and not size:
                continue
            terminated = False
            for offset in range(0, size - width + 1, width):
                entry = self.unpack("<" + "I" * (width // 4), self.location(rva + offset, width))
                if not any(entry):
                    terminated = True
                    break
                name_rva = entry[name_index]
                if index == 13 and not (entry[0] & 1):
                    name_rva -= self.image_base
                result.add(self.dll_name(name_rva))
            if not terminated:
                raise ValueError("Unterminated PE import directory")
        return result


SYSTEM_DLLS = frozenset("""
advapi32.dll authz.dll avrt.dll bcrypt.dll bcryptprimitives.dll cfgmgr32.dll combase.dll comctl32.dll
comdlg32.dll crypt32.dll d3d9.dll d3d11.dll d3d12.dll dbghelp.dll dinput8.dll
dsound.dll dwmapi.dll dxgi.dll d2d1.dll dnsapi.dll dwrite.dll gdi32.dll hid.dll imm32.dll iphlpapi.dll
kernel32.dll kernelbase.dll mpr.dll mscms.dll msimg32.dll msvcrt.dll ncrypt.dll netapi32.dll ntdll.dll ole32.dll oleaut32.dll
powrprof.dll propsys.dll rpcrt4.dll secur32.dll setupapi.dll shell32.dll
shcore.dll shlwapi.dll user32.dll userenv.dll usp10.dll uxtheme.dll ucrtbase.dll version.dll winhttp.dll
winmm.dll wintrust.dll ws2_32.dll wtsapi32.dll xinput1_4.dll
""".split())


def dll_closure(executable, candidates, target, dynamic=(), allow_build_tools=False):
    """Resolve only explicitly inventoried files; never search PATH or copy a tool bin tree."""
    expected = profile(target)["machine"]
    providers = {}
    for path in map(Path, candidates):
        name = path.name.lower()
        if name in providers:
            raise ValueError("Ambiguous DLL provider: " + name)
        providers[name] = path
    pending = [Path(executable)]
    for name in dynamic:
        if name.lower() not in providers:
            raise ValueError("Missing dynamically loaded DLL: " + name)
        pending.append(providers[name.lower()])
    selected = {}
    while pending:
        path = pending.pop()
        name = path.name.lower()
        if name in selected:
            continue
        if not allow_build_tools and any(word in name for word in ("unicorn", "python", "clang", "lld.exe")):
            raise ValueError("Build-only dependency in game package: " + name)
        image = PE(path)
        if image.machine != expected:
            raise ValueError("Wrong PE architecture: " + name)
        selected[name] = path
        for dependency in sorted(image.imports()):
            if dependency in SYSTEM_DLLS or re.fullmatch(r"(api|ext)-ms-win-[a-z0-9-]+\.dll", dependency):
                continue
            if dependency == "vulkan-1.dll":
                continue  # GPU-vendor loader; the renderer must diagnose its absence.
            if dependency not in providers:
                raise ValueError(f"Missing DLL: {dependency} (required by {name})")
            pending.append(providers[dependency])
    return [selected[name] for name in sorted(selected)]


def compiler_identity(compiler, selected, run=subprocess.run):
    resolved = shutil.which(str(compiler))
    if not resolved:
        raise ValueError("LLVM-MinGW C compiler is missing: " + str(compiler))
    resolved = str(Path(resolved).resolve())
    def query(*arguments, **kwargs):
        return run([resolved, *arguments], check=True, capture_output=True,
                   text=True, **kwargs).stdout.strip()
    triple = query("-dumpmachine")
    expected = selected["target"]
    if not triple.startswith(expected + "-") or not ("mingw" in triple or "windows-gnu" in triple):
        raise ValueError("Expected LLVM-MinGW compiler for " + selected["triple"] + ", got " + triple)
    macros = query("-dM", "-E", "-x", "c", "-", input="#include <_mingw.h>\n")
    if not re.search(r"^#define __MINGW32__\b", macros, re.M) or not re.search(
            r"^#define _UCRT\b", macros, re.M):
        raise ValueError("Windows compiler must use MinGW UCRT, not MSVC or MSVCRT")
    return {"path": resolved, "sha256": sha256(resolved),
            "version": query("--version"), "triple": triple,
            "macros_sha256": hashlib.sha256(macros.encode()).hexdigest()}
