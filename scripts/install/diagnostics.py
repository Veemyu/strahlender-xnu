#!/usr/bin/env python3
"""System and hardware report for the installer log.

Every line has the form ``[Diagnostics] <text>`` and states one fact, so that
bug reports (for example a Windows "cannot create output file" error) come
with the relevant platform data.

Run it standalone with::

    python3 scripts/install/diagnostics.py [--work FOLDER] [--root FOLDER]

The report goes to stdout and the exit code is always 0, even when every item
is unavailable. ``--root`` is accepted as an alias of ``--work``.

Privacy
-------
* No telemetry and no network access. Nothing is sent anywhere; the report
  only leaves the machine if the user copies the log and shares it.
* Every emitted line and every raw command output is passed through
  ``redact`` first. It replaces the home directory (all slash, backslash and
  doubled-backslash variants) and any other user profile path such as
  ``C:\\Users\\name`` with ``<home>``, the login name as a whole word with
  ``<user>`` (a word ends at any character other than a letter, a digit or an
  underscore), the machine name with ``<host>``, serial numbers, MAC
  addresses, hardware UUIDs, IPv4 and IPv6 addresses, and any run of 32 or
  more hex digits (key material). Dotted numbers that follow words such as
  "version" or "driver" are kept, because they are versions and not addresses.
* Environment variables: only the NAMES of BDSP_* variables are listed. A
  value is shown only when it is one of 0, 1, true or false. A few other
  variables (LANG, LC_ALL, XDG_SESSION_TYPE, XDG_CURRENT_DESKTOP) and the
  presence of WAYLAND_DISPLAY and DISPLAY are reported as listed in the code.
* Microsoft Defender exclusions are reported as counts only, never as values.
* The work folder is reported as a length and a yes/no cloud-sync flag, never
  as a path.

Each item is isolated: a failure produces
``[Diagnostics] <item>: unavailable (<reason>)`` and never raises.
"""

import argparse
import json
import locale
import ntpath
import os
import platform
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tempfile

DIAGNOSTICS_VERSION = 1
PREFIX = "[Diagnostics] "
WINDOWS_PATH_LIMIT = 260
SHORT_TIMEOUT = 8
LONG_TIMEOUT = 20

_TOOLS = (
    "git", "make", "cc", "clang", "gcc", "cmake", "ffmpeg", "pkg-config",
    "python3", "python",
)
# On macOS these are shims that pop up an install dialog without developer tools.
_MAC_SHIM_TOOLS = ("git", "make", "cc", "clang", "gcc", "python3")
_PACKAGE_MANAGERS = (
    "apt", "dnf", "pacman", "zypper", "apk", "rpm-ostree", "nix-env",
)
_TOGGLE_VALUES = ("0", "1", "true", "false")
_CLOUD_WORDS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud",
                "clouddocs", "box sync")

# Private-use characters stand in for placeholders while redacting, so a user
# or host name such as "mac" cannot corrupt an already inserted placeholder.
_PLACEHOLDERS = {
    "\ue000": "<home>",
    "\ue001": "<user>",
    "\ue002": "<host>",
    "\ue003": "<serial>",
    "\ue004": "<uuid>",
    "\ue005": "<mac>",
    "\ue006": "<ip>",
    "\ue007": "<key>",
}
_P_HOME, _P_USER, _P_HOST, _P_SERIAL, _P_UUID, _P_MAC, _P_IP, _P_KEY = sorted(
    _PLACEHOLDERS)

_WIN_PROFILE_RE = re.compile(
    r"[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+[^\\/\s\"'<>|?*]+",
    re.IGNORECASE)
_POSIX_PROFILE_RE = re.compile(r"(?<![\w.])/(?:Users/(?!Shared\b)|home/)[^/\s\"']+")
_SERIAL_RE = re.compile(
    r"(serial[\w ()]*?[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)", re.IGNORECASE)
_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])")
_HEX_RUN_RE = re.compile(r"[0-9A-Fa-f]{32,}")
_MAC_RE = re.compile(
    r"(?<![0-9A-Za-z])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Za-z])")
_H = r"[0-9A-Fa-f]{1,4}"
_IPV6_RE = re.compile(
    r"(?<![\w:.])(?:"
    r"(?:%(h)s:){7}%(h)s"
    r"|(?:%(h)s:){1,7}:(?:%(h)s(?::%(h)s){0,6})?"
    r"|::%(h)s(?::%(h)s){0,6}"
    r")(?:%%[0-9A-Za-z]+)?(?![\w:])" % {"h": _H})
_IPV4_RE = re.compile(
    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")
_VERSION_CONTEXT_RE = re.compile(
    r"(version|conformance|driver|build|api|revision|bios|firmware)[^\n]{0,30}$",
    re.IGNORECASE)
_GENERIC_NAMES = ("root", "system", "user", "admin", "administrator", "localhost")


class _Unavailable(Exception):
    """An item cannot be reported; ``reason`` is the short text for the log."""

    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [item for item in value if item]


def _home_variants(home):
    home = home.strip().rstrip("\\/")
    if len(home) < 3:
        return []
    back = home.replace("/", "\\")
    variants = set([home, home.replace("\\", "/"), back, back.replace("\\", "\\\\")])
    return sorted(variants, key=len, reverse=True)


def _name_re(names):
    names = sorted(set(n for n in names if len(n) >= 3 and n.lower() not in _GENERIC_NAMES),
                   key=len, reverse=True)
    if not names:
        return None
    body = "|".join(re.escape(n) for n in names)
    return re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])" % body, re.IGNORECASE)


def _ipv4_sub(match):
    text = match.string
    before = text[max(0, match.start() - 40):match.start()]
    if _VERSION_CONTEXT_RE.search(before):
        return match.group(0)
    return _P_IP


def redact(text, home=None, user=None, host=None):
    """Return ``text`` with personal and hardware identifiers replaced.

    ``home``, ``user`` and ``host`` may each be a string or a list of strings.
    """
    if not text:
        return text
    result = text
    variants = []
    for item in _as_list(home):
        variants.extend(_home_variants(item))
    if variants:
        variants = sorted(set(variants), key=len, reverse=True)
        result = re.sub("|".join(re.escape(v) for v in variants), _P_HOME,
                        result, flags=re.IGNORECASE)
    result = _WIN_PROFILE_RE.sub(_P_HOME, result)
    result = _POSIX_PROFILE_RE.sub(_P_HOME, result)
    result = _SERIAL_RE.sub(lambda m: m.group(1) + _P_SERIAL, result)
    result = _UUID_RE.sub(_P_UUID, result)
    result = _HEX_RUN_RE.sub(_P_KEY, result)
    result = _MAC_RE.sub(_P_MAC, result)
    result = _IPV6_RE.sub(_P_IP, result)
    result = _IPV4_RE.sub(_ipv4_sub, result)
    pattern = _name_re(_as_list(user))
    if pattern:
        result = pattern.sub(_P_USER, result)
    hosts = []
    for item in _as_list(host):
        hosts.append(item)
        if "." in item:
            hosts.append(item.split(".", 1)[0])
    pattern = _name_re(hosts)
    if pattern:
        result = pattern.sub(_P_HOST, result)
    for char, label in _PLACEHOLDERS.items():
        result = result.replace(char, label)
    return result


def _clean_line(text):
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- running

def _decode(data):
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def run(args, timeout=SHORT_TIMEOUT, runner=None):
    """Run a command without a shell. Returns (ok, text_or_reason)."""
    runner = runner or subprocess.run
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
        "shell": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = runner(list(args), **kwargs)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "not found"
    except PermissionError:
        return False, "permission denied"
    except OSError as exc:
        return False, "error: %s" % exc.__class__.__name__
    code = getattr(proc, "returncode", 0)
    if code != 0:
        return False, "exit code %s" % code
    out = _decode(getattr(proc, "stdout", ""))
    if out.strip():
        return True, out
    return True, _decode(getattr(proc, "stderr", ""))


# ---------------------------------------------------------------- parsers

def version_first_line(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def parse_os_release(text):
    result = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


def parse_cpuinfo(text):
    info = {"model": "", "implementer": "", "part": "", "hardware": "", "processors": 0}
    for raw in (text or "").splitlines():
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "processor":
            info["processors"] += 1
        elif key == "model name" and not info["model"]:
            info["model"] = value
        elif key == "cpu implementer" and not info["implementer"]:
            info["implementer"] = value
        elif key == "cpu part" and not info["part"]:
            info["part"] = value
        elif key == "hardware" and not info["hardware"]:
            info["hardware"] = value
        elif key == "model" and not info["hardware"] and not value.isdigit():
            info["hardware"] = value
    return info


def parse_lscpu_model(text):
    for raw in (text or "").splitlines():
        key, sep, value = raw.partition(":")
        if sep and key.strip().lower() == "model name":
            return value.strip()
    return ""


def parse_meminfo(text):
    """Return the values of MemTotal, MemFree and MemAvailable in kB."""
    result = {}
    for raw in (text or "").splitlines():
        match = re.match(r"\s*(MemTotal|MemFree|MemAvailable):\s*(\d+)", raw)
        if match:
            result[match.group(1)] = int(match.group(2))
    return result


def parse_sw_vers(text):
    result = {}
    for raw in (text or "").splitlines():
        key, sep, value = raw.partition(":")
        if sep:
            result[key.strip()] = value.strip()
    return result


def parse_actool_version(text):
    """Short version from ``actool --version`` (a property list), for example 27.1."""
    match = re.search(r"<key>short-bundle-version</key>\s*<string>([^<]+)</string>", text or "")
    if not match:
        raise _Unavailable("version not found in the output")
    return match.group(1).strip()


def parse_pkg_version(text):
    """The ``version:`` row of ``pkgutil --pkg-info``."""
    return parse_sw_vers(text).get("version", "")


def parse_devicectl(text):
    """Connected-device facts from ``devicectl list devices`` JSON: model, iOS version and state only, never a name or an ID."""
    try:
        devices = json.loads(text).get("result", {}).get("devices", [])
    except (ValueError, AttributeError) as exc:
        raise _Unavailable("unparsable output: %s" % exc.__class__.__name__)
    found = []
    for device in devices if isinstance(devices, list) else []:
        hardware = device.get("hardwareProperties") or {}
        if hardware.get("platform") != "iOS" or hardware.get("reality") == "simulated":
            continue
        model = hardware.get("marketingName") or hardware.get("productType") or "unknown model"
        if hardware.get("productType") and hardware.get("productType") not in model:
            model += " (%s)" % hardware["productType"]
        found.append({
            "model": model,
            "os": (device.get("deviceProperties") or {}).get("osVersionNumber") or "unknown",
            "state": (device.get("connectionProperties") or {}).get("tunnelState") or "unknown",
        })
    return found


def parse_vm_stat(text):
    """Return approximate reclaimable memory in bytes (free + inactive + speculative)."""
    match = re.search(r"page size of (\d+) bytes", text or "")
    size = int(match.group(1)) if match else 4096
    pages = 0
    for name in ("free", "inactive", "speculative"):
        found = re.search(r"Pages %s:\s*(\d+)" % name, text or "")
        if found:
            pages += int(found.group(1))
    return pages * size


def parse_system_profiler_displays(text):
    """Parse ``system_profiler SPDisplaysDataType`` into GPUs and a display count."""
    gpus = []
    displays = 0
    current = None
    in_displays = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "Chipset Model":
            current = {"chipset": value, "cores": "", "metal": "", "vram": "",
                       "vendor": "", "bus": ""}
            gpus.append(current)
            in_displays = False
            continue
        if key == "Displays":
            in_displays = True
            continue
        if key == "Resolution":
            displays += 1
        if current is None or in_displays:
            continue
        if key == "Total Number of Cores":
            current["cores"] = value
        elif key in ("Metal Support", "Metal Family", "Metal"):
            current["metal"] = value
        elif key.startswith("VRAM"):
            current["vram"] = value
        elif key == "Vendor":
            current["vendor"] = value
        elif key == "Bus":
            current["bus"] = value
    return {"gpus": gpus, "displays": displays}


_DISPLAY_CLASS_RE = re.compile(
    r"(VGA compatible controller|3D controller|Display controller)", re.IGNORECASE)


def parse_lspci_display(text):
    """Parse ``lspci -nnk`` and keep only VGA, 3D and display controller blocks."""
    devices = []
    current = None
    for raw in (text or "").splitlines():
        if not raw.strip():
            current = None
            continue
        if not raw[0].isspace():
            current = None
            match = re.match(r"\S+\s+(.*?):\s+(.*)$", raw)
            if match and _DISPLAY_CLASS_RE.search(match.group(1)):
                current = {"class": re.sub(r"\s*\[[0-9a-fA-F]{4}\]$", "", match.group(1)),
                           "name": match.group(2).strip(), "driver": "", "modules": ""}
                devices.append(current)
            continue
        if current is None:
            continue
        key, _, value = raw.strip().partition(":")
        if key == "Kernel driver in use":
            current["driver"] = value.strip()
        elif key == "Kernel modules":
            current["modules"] = value.strip()
    return devices


def mesa_version(text):
    match = re.search(r"Mesa\s+(\d+(?:\.\d+)+[^\s,)]*)", text or "")
    return match.group(1) if match else ""


def parse_vulkaninfo_summary(text):
    """Keep the instance version and per-device name, type, API and driver lines."""
    result = {"instance": "", "devices": []}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        match = re.match(r"Vulkan Instance Version:\s*(\S+)", line)
        if match:
            result["instance"] = match.group(1)
            continue
        if re.match(r"GPU\d+:$", line):
            current = {"name": "", "api": "", "driver": "", "driver_info": "", "type": ""}
            result["devices"].append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "deviceName":
            current["name"] = value
        elif key == "apiVersion":
            current["api"] = value
        elif key == "driverName":
            current["driver"] = value
        elif key == "driverInfo":
            current["driver_info"] = value
        elif key == "deviceType":
            current["type"] = value.replace("PHYSICAL_DEVICE_TYPE_", "").lower()
    return result


def parse_glxinfo_b(text):
    result = {"renderer": "", "version": "", "vendor": "", "mesa": ""}
    for raw in (text or "").splitlines():
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "OpenGL renderer string":
            result["renderer"] = value
        elif key == "OpenGL version string":
            result["version"] = value
            result["mesa"] = mesa_version(value)
        elif key == "OpenGL vendor string":
            result["vendor"] = value
    return result


def parse_df(text):
    """Return (device, mount point) from ``df -P`` output."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("no df data line")
    fields = lines[-1].split()
    if len(fields) < 6:
        raise ValueError("short df line")
    return fields[0], " ".join(fields[5:])


_MOUNT_LINE_RE = re.compile(
    r"^(?P<dev>.+?) on (?P<mnt>.+?) (?:type (?P<type>\S+) )?\((?P<opts>[^)]*)\)\s*$")


def parse_mount(text, mount_point, device=None):
    """Find the file system type of a mount point in ``mount`` output (macOS or Linux)."""
    for raw in (text or "").splitlines():
        match = _MOUNT_LINE_RE.match(raw.strip())
        if not match:
            continue
        if match.group("mnt") != mount_point and (device is None or match.group("dev") != device):
            continue
        if match.group("type"):
            return match.group("type")
        return match.group("opts").split(",")[0].strip()
    return None


def parse_proc_mounts(text, path):
    """Return the file system type of the longest mount point containing ``path``."""
    best = None
    best_len = -1
    for raw in (text or "").splitlines():
        fields = raw.split()
        if len(fields) < 3:
            continue
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[1])
        base = mount.rstrip("/")
        if path == mount or path.startswith(base + "/") or mount == "/":
            if len(mount) >= best_len:
                best, best_len = fields[2], len(mount)
    return best


def _first_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _dict_list(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def parse_windows_json(text):
    """Parse the PowerShell JSON; one object and a list of objects are both fine."""
    text = (text or "").lstrip("\ufeff").replace("\ufeff", "")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON in output")
    data = json.loads(text[start:end + 1])
    result = {}
    for key in ("os", "cs", "defender", "exclusions", "reg"):
        result[key] = _first_dict(data.get(key))
    for key in ("cpu", "gpu", "av"):
        result[key] = _dict_list(data.get(key))
    return result


# ------------------------------------------------------- Windows-only APIs

def _win_is_admin():
    if sys.platform != "win32":
        raise _Unavailable("not windows")
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _win_reg_dword(subkey, name):
    """Read a HKLM value. Returns None when the value is missing."""
    if sys.platform != "win32":
        raise _Unavailable("winreg not available")
    import winreg
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, access) as key:
            return int(winreg.QueryValueEx(key, name)[0])
    except FileNotFoundError:
        return None


def _win_fs_type(path):
    if sys.platform != "win32":
        raise _Unavailable("not windows")
    import ctypes
    root = ntpath.splitdrive(os.path.abspath(path))[0] + "\\"
    buffer = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        root, None, 0, None, None, None, buffer, 261)
    if not ok:
        raise _Unavailable("GetVolumeInformationW failed")
    return buffer.value


# ---------------------------------------------------------------- context

class _SystemAccess(object):
    """Local file and PATH access, replaceable in tests."""

    def read(self, path):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def exists(self, path):
        return os.path.exists(path)

    def readlink(self, path):
        return os.readlink(path)

    def which(self, name):
        return shutil.which(name)

    def geteuid(self):
        func = getattr(os, "geteuid", None)
        return func() if func else None


def _detect_system():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _gib(nbytes):
    return "%.1f GiB" % (float(nbytes) / (1024.0 ** 3))


def _yes_no(value):
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _nearest_existing(path, exists=os.path.exists):
    current = path
    while current:
        if exists(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


class _Context(object):
    def __init__(self, work, runner, env, system, home, user, host, fs):
        self.work = work
        self.runner = runner
        self.env = env
        self.system = system
        self.fs = fs
        self.cache = {}
        self.redactor = lambda text: redact(text, home, user, host)
        self._win = None

    def try_cmd(self, args, timeout=SHORT_TIMEOUT):
        ok, text = run(args, timeout=timeout, runner=self.runner)
        if ok:
            text = self.redactor(text)
        return ok, text

    def cmd(self, args, timeout=SHORT_TIMEOUT):
        ok, text = self.try_cmd(args, timeout)
        if not ok:
            raise _Unavailable(text)
        return text

    def read(self, path):
        return self.redactor(self.fs.read(path))

    def win(self):
        """Run the single PowerShell query once and cache data or failure."""
        if self._win is None:
            try:
                text = self.cmd(_powershell_args(), timeout=LONG_TIMEOUT)
                self._win = ("ok", parse_windows_json(text))
            except _Unavailable as exc:
                self._win = ("fail", exc)
            except ValueError as exc:
                self._win = ("fail", _Unavailable("unparsable output: %s" % exc))
        if self._win[0] == "fail":
            raise self._win[1]
        return self._win[1]

    def work_exists_parent(self):
        if not self.work:
            raise _Unavailable("no work folder given")
        return _nearest_existing(self.work)


_PS_SCRIPT = "; ".join([
    "$ErrorActionPreference='SilentlyContinue'",
    "function Cnt($x){ if(-not $x){0} elseif((@($x) -join '') -match 'administrator'){-1} else {@($x).Count} }",
    "function Reg($p,$n){ $v=(Get-ItemProperty -Path $p -Name $n).$n; $v }",
    "$r=[ordered]@{}",
    "$r.os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,FreePhysicalMemory,TotalVisibleMemorySize",
    "$r.cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)",
    "$r.gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,@{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}},AdapterRAM,VideoProcessor)",
    "$r.cs=Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory",
    "$r.defender=Get-MpComputerStatus | Select-Object AMServiceEnabled,RealTimeProtectionEnabled,AntivirusEnabled",
    "$p=Get-MpPreference",
    "$r.exclusions=[ordered]@{paths=(Cnt $p.ExclusionPath);processes=(Cnt $p.ExclusionProcess);extensions=(Cnt $p.ExclusionExtension)}",
    "$r.av=@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct | Select-Object displayName)",
    "$r.reg=[ordered]@{LongPathsEnabled=(Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' 'LongPathsEnabled');NtfsDisable8dot3NameCreation=(Reg 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' 'NtfsDisable8dot3NameCreation');DeveloperMode=(Reg 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\AppModelUnlock' 'AllowDevelopmentWithoutDevLicense')}",
    "ConvertTo-Json -Compress -Depth 4 -InputObject $r",
])


def _powershell_args():
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-Command", _PS_SCRIPT]


# ------------------------------------------------------------------ items

def _item(lines, label, function):
    """Run one report item; a failure becomes an 'unavailable' line, never an exception."""
    try:
        result = function()
    except subprocess.TimeoutExpired:
        reason = "timeout"
    except _Unavailable as exc:
        reason = exc.reason
    except Exception as exc:
        reason = ("%s: %s" % (exc.__class__.__name__, exc)).strip(": ")[:80]
    else:
        if result is None:
            return True
        if isinstance(result, str):
            result = [result]
        for text in result:
            lines.append(PREFIX + text)
        return True
    lines.append(PREFIX + "%s: unavailable (%s)" % (label, _clean_line(reason)))
    return False


def _python_info(ctx):
    bits = struct.calcsize("P") * 8
    venv = "yes" if getattr(sys, "base_prefix", sys.prefix) != sys.prefix else "no"
    return "Python: %s (%d-bit), %s, virtualenv %s" % (
        platform.python_version(), bits, platform.python_implementation(), venv)


def _os_python_info(ctx):
    return "OS (Python): %s %s, %s" % (
        platform.system(), platform.release(), platform.platform())


def _arch_info(ctx):
    machine = platform.machine() or "unknown"
    state = "unknown"
    if ctx.system == "darwin":
        ok, text = ctx.try_cmd(["sysctl", "-n", "sysctl.proc_translated"])
        if ok:
            state = "translated (Rosetta 2)" if text.strip() == "1" else "native"
        elif text.startswith("exit code"):
            state = "native"
        else:
            state = "unknown (%s)" % text
    elif ctx.system == "windows":
        host = (ctx.env.get("PROCESSOR_ARCHITEW6432") or "").upper()
        known = ("AMD64", "ARM64", "X86", "IA64")
        if host and host in known and host != machine.upper():
            state = "emulated or WOW64 (host architecture %s)" % host
        else:
            state = "native"
    else:
        state = "native"
    return "Architecture: %s, Python process %s" % (machine, state)


def _logical_cores(ctx):
    return "Logical cores (Python): %s" % (os.cpu_count() or "unknown")


def _disk_line(label, path):
    if not path:
        raise _Unavailable("folder not found")
    usage = shutil.disk_usage(path)
    return "Free disk space (%s): %s of %s" % (label, _gib(usage.free), _gib(usage.total))


def _work_disk(ctx):
    return _disk_line("work folder", ctx.work_exists_parent())


def _temp_disk(ctx):
    return _disk_line("temp folder", _nearest_existing(tempfile.gettempdir()))


def _is_cloud_path(path):
    lowered = (path or "").lower()
    return any(word in lowered for word in _CLOUD_WORDS)


def _cloud_line(ctx):
    if not ctx.work:
        raise _Unavailable("no work folder given")
    return "Work folder below a cloud-synced folder (OneDrive, Dropbox, iCloud): %s" % (
        "yes" if _is_cloud_path(ctx.work) else "no")


def _locale_info(ctx):
    try:
        current = locale.getlocale()
    except (ValueError, TypeError):
        current = ("unknown", "unknown")
    parts = ["Locale: %s, encoding %s" % (
        "%s %s" % (current[0], current[1]) if current[1] else current[0],
        locale.getpreferredencoding(False))]
    for name in ("LANG", "LC_ALL"):
        value = ctx.env.get(name)
        parts.append("%s=%s" % (name, value if value else "unset"))
    return ", ".join(parts)


def _elevated(ctx):
    if ctx.system == "windows":
        return "Elevated: %s" % _yes_no(_win_is_admin())
    euid = ctx.fs.geteuid()
    if euid is None:
        raise _Unavailable("not available")
    return "Elevated: %s" % _yes_no(euid == 0)


def _tool_lines(ctx):
    lines = []
    mac_ok = True
    if ctx.system == "darwin":
        mac_ok, _ = ctx.try_cmd(["xcode-select", "-p"])
    for tool in _TOOLS:
        if ctx.system == "darwin" and not mac_ok and tool in _MAC_SHIM_TOOLS:
            lines.append("Tool %s: not checked (developer tools not installed)" % tool)
            continue
        ok, text = ctx.try_cmd([tool, "-version" if tool == "ffmpeg" else "--version"])
        if ok:
            lines.append("Tool %s: %s" % (tool, version_first_line(text) or "present"))
        elif text == "not found":
            lines.append("Tool %s: not found" % tool)
        else:
            lines.append("Tool %s: unavailable (%s)" % (tool, text))
    return lines


def _env_lines(ctx):
    names = sorted(name for name in ctx.env if name.upper().startswith("BDSP_"))
    shown = []
    for name in names:
        value = str(ctx.env.get(name, ""))
        if value.lower() in _TOGGLE_VALUES:
            shown.append("%s=%s" % (name, value.lower()))
        else:
            shown.append(name)
    lines = ["Environment BDSP_* variables: %s" % (", ".join(shown) if shown else "none")]
    return lines


def _display_flags(ctx):
    def state(name):
        return "set" if ctx.env.get(name) else "unset"
    return ("Session: XDG_SESSION_TYPE=%s, XDG_CURRENT_DESKTOP=%s, WAYLAND_DISPLAY %s, "
            "DISPLAY %s" % (ctx.env.get("XDG_SESSION_TYPE") or "unset",
                            ctx.env.get("XDG_CURRENT_DESKTOP") or "unset",
                            state("WAYLAND_DISPLAY"), state("DISPLAY")))


# Vulkan and OpenGL (Linux and Windows)

def _vulkan_lines(ctx):
    text = ctx.cmd(["vulkaninfo", "--summary"])
    info = parse_vulkaninfo_summary(text)
    ctx.cache["mesa"] = ctx.cache.get("mesa") or next(
        (mesa_version(d["driver_info"]) for d in info["devices"]
         if mesa_version(d["driver_info"])), "")
    lines = []
    if info["instance"]:
        lines.append("Vulkan instance version: %s" % info["instance"])
    for index, dev in enumerate(info["devices"], 1):
        lines.append("Vulkan device %d: %s, type %s, API %s, driver %s %s" % (
            index, dev["name"] or "unknown", dev["type"] or "unknown",
            dev["api"] or "unknown", dev["driver"] or "unknown", dev["driver_info"]))
    if not lines:
        raise _Unavailable("no devices in output")
    return lines


def _glx_lines(ctx):
    info = parse_glxinfo_b(ctx.cmd(["glxinfo", "-B"]))
    if info["mesa"]:
        ctx.cache["mesa"] = ctx.cache.get("mesa") or info["mesa"]
    if not (info["renderer"] or info["version"]):
        raise _Unavailable("no OpenGL data in output")
    return "OpenGL: renderer %s, version %s" % (
        info["renderer"] or "unknown", info["version"] or "unknown")


def _mesa_line(ctx):
    if ctx.cache.get("mesa"):
        return "Mesa version: %s" % ctx.cache["mesa"]
    return None


# macOS

def _sysctl(ctx, name):
    return ctx.cmd(["sysctl", "-n", name]).strip()


def _mac_os(ctx):
    info = parse_sw_vers(ctx.cmd(["sw_vers"]))
    return "macOS: %s %s (build %s)" % (
        info.get("ProductName", "unknown"), info.get("ProductVersion", "unknown"),
        info.get("BuildVersion", "unknown"))


def _mac_cpu(ctx):
    model = _sysctl(ctx, "machdep.cpu.brand_string")
    try:
        cores = _sysctl(ctx, "hw.logicalcpu")
    except _Unavailable:
        cores = _sysctl(ctx, "hw.ncpu")
    return "CPU: %s, %s logical cores (sysctl)" % (model or "unknown", cores)


def _mac_model(ctx):
    return "Hardware model: %s" % _sysctl(ctx, "hw.model")


def _mac_ram(ctx):
    total = int(_sysctl(ctx, "hw.memsize"))
    text = "RAM: total %s" % _gib(total)
    ok, vm = ctx.try_cmd(["vm_stat"])
    if ok:
        text += ", free or reclaimable %s (free, inactive and speculative pages)" % _gib(
            parse_vm_stat(vm))
    return text


def _mac_gpu(ctx):
    info = parse_system_profiler_displays(
        ctx.cmd(["system_profiler", "SPDisplaysDataType"], timeout=LONG_TIMEOUT))
    lines = []
    for index, gpu in enumerate(info["gpus"], 1):
        parts = ["GPU %d: %s" % (index, gpu["chipset"] or "unknown")]
        if gpu["cores"]:
            parts.append("%s cores" % gpu["cores"])
        if gpu["metal"]:
            parts.append("Metal: %s" % gpu["metal"])
        if gpu["vram"]:
            parts.append("VRAM %s" % gpu["vram"])
        if gpu["bus"]:
            parts.append("bus %s" % gpu["bus"])
        lines.append(", ".join(parts))
    if not lines:
        raise _Unavailable("no GPU in output")
    lines.append("Displays connected: %d" % info["displays"])
    return lines


def _mac_xcode(ctx):
    lines = ["Developer directory (xcode-select -p): %s" % ctx.cmd(["xcode-select", "-p"]).strip()]
    return lines


def _mac_developer_dir(ctx):
    return "DEVELOPER_DIR: %s" % (ctx.env.get("DEVELOPER_DIR") or "unset")


def _has_dev_tools(ctx):
    """The developer tools are installed; xcrun, clang and git are shims that open an install dialog otherwise."""
    if "dev_tools" not in ctx.cache:
        ctx.cache["dev_tools"] = ctx.try_cmd(["xcode-select", "-p"])[0]
    return ctx.cache["dev_tools"]


def _mac_dev_tools(ctx):
    if not _has_dev_tools(ctx):
        raise _Unavailable("not checked, developer tools not installed")


def _mac_clt(ctx):
    ok, text = ctx.try_cmd(["pkgutil", "--pkg-info=com.apple.pkg.CLTools_Executables"])
    if ok:
        return "Command Line Tools package: version %s" % (parse_pkg_version(text) or "unknown")
    if text.startswith("exit code"):
        return "Command Line Tools package: not installed (Xcode only)"
    raise _Unavailable(text)


def _mac_xcodebuild(ctx):
    text = ctx.cmd(["xcodebuild", "-version"])
    rows = [r.strip() for r in text.splitlines() if r.strip()][:2]
    return "xcodebuild: %s" % "; ".join(rows)


def _mac_sdk(ctx, sdk):
    path = ctx.cmd(["xcrun", "--sdk", sdk, "--show-sdk-path"]).strip()
    version = ctx.cmd(["xcrun", "--sdk", sdk, "--show-sdk-version"]).strip()
    return "SDK %s: version %s, path %s" % (sdk, version, path)


def _mac_actool(ctx):
    _mac_dev_tools(ctx)
    return "actool: version %s (Icon Composer icons need 26 or newer)" % parse_actool_version(
        ctx.cmd(["xcrun", "actool", "--version"]))


def _mac_metal(ctx, sdk):
    _mac_dev_tools(ctx)
    return "Metal compiler (%s): %s" % (sdk, version_first_line(ctx.cmd(["xcrun", "-sdk", sdk, "metal", "--version"])) or "unknown")


_CLANGS = (("Apple clang (/usr/bin/clang)", "/usr/bin/clang"),
           ("Homebrew LLVM clang (Apple silicon)", "/opt/homebrew/opt/llvm/bin/clang"),
           ("Homebrew LLVM clang (Intel)", "/usr/local/opt/llvm/bin/clang"))


def _mac_clangs(ctx):
    lines = []
    for label, path in _CLANGS:
        if path != "/usr/bin/clang" and not ctx.fs.exists(path):
            lines.append("%s: not installed" % label)
            continue
        if path == "/usr/bin/clang" and not _has_dev_tools(ctx):
            lines.append("%s: not checked (developer tools not installed)" % label)
            continue
        ok, text = ctx.try_cmd([path, "--version"])
        lines.append("%s: %s" % (label, version_first_line(text) if ok else "unavailable (%s)" % text))
    return lines


def _mac_libraries(ctx):
    """pkg-config versions of the libraries the Mac build links (SDL3, FFmpeg)."""
    found = []
    for name in ("sdl3", "libavcodec", "libavformat", "libavutil"):
        ok, text = ctx.try_cmd(["pkg-config", "--modversion", name])
        found.append("%s %s" % (name, version_first_line(text) if ok else "not found" if text.startswith(("exit code", "not found")) else "unavailable (%s)" % text))
    return "Libraries (pkg-config): " + ", ".join(found)


def _mac_rosetta(ctx):
    if platform.machine().lower() not in ("arm64", "aarch64"):
        return None
    return "Rosetta 2 installed: %s" % _yes_no(ctx.fs.exists("/Library/Apple/usr/libexec/oah/libRosettaRuntime"))


def _mac_devices(ctx):
    """Connected iPhones and iPads for an iOS build: model, iOS version and connection state only."""
    _mac_dev_tools(ctx)
    handle, path = tempfile.mkstemp(prefix="devices-", suffix=".json")
    os.close(handle)
    try:
        ctx.cmd(["xcrun", "devicectl", "list", "devices", "--json-output", path], timeout=LONG_TIMEOUT)
        with open(path, "r", encoding="utf-8") as stream:
            devices = parse_devicectl(stream.read())
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if not devices:
        return "Apple devices for the iOS target: none found"
    return ["Apple device %d: %s, iOS %s, %s" % (index, item["model"], item["os"], item["state"])
            for index, item in enumerate(devices, 1)]


def _mac_sip(ctx):
    text = ctx.cmd(["csrutil", "status"]).lower()
    if "disabled" in text:
        state = "disabled"
    elif "enabled" in text:
        state = "enabled"
    else:
        state = "unknown"
    return "System Integrity Protection: %s" % state


def _mac_fs(ctx):
    path = ctx.work_exists_parent()
    device, mount = parse_df(ctx.cmd(["df", "-P", path]))
    fstype = parse_mount(ctx.cmd(["mount"]), mount, device)
    if not fstype:
        raise _Unavailable("mount point not found")
    return "Work folder file system: %s" % fstype


# Linux

def _linux_osrelease(ctx):
    if "osrelease" not in ctx.cache:
        text = ""
        for path in ("/etc/os-release", "/usr/lib/os-release"):
            try:
                text = ctx.read(path)
                break
            except (OSError, IOError):
                continue
        ctx.cache["osrelease"] = parse_os_release(text) if text else None
    if ctx.cache["osrelease"] is None:
        raise _Unavailable("os-release not found")
    return ctx.cache["osrelease"]


def _linux_os(ctx):
    info = _linux_osrelease(ctx)
    return "Linux distribution: %s (ID=%s, VERSION_ID=%s, VARIANT_ID=%s)" % (
        info.get("PRETTY_NAME", "unknown"), info.get("ID", "unknown"),
        info.get("VERSION_ID", "unknown"), info.get("VARIANT_ID", "none"))


def _linux_uname(ctx):
    text = ctx.cmd(["uname", "-srm"]).strip()
    ctx.cache["uname"] = text
    return "Kernel: %s" % text


def _linux_cpu(ctx):
    info = parse_cpuinfo(ctx.read("/proc/cpuinfo"))
    model = info["model"]
    if not model:
        parts = []
        if info["hardware"]:
            parts.append(info["hardware"])
        if info["implementer"] or info["part"]:
            parts.append("implementer %s part %s" % (
                info["implementer"] or "unknown", info["part"] or "unknown"))
        model = ", ".join(parts) or "unknown"
    ok, text = ctx.try_cmd(["lscpu"])
    extra = parse_lscpu_model(text) if ok else ""
    if extra and extra != model:
        model = "%s (lscpu: %s)" % (model, extra)
    return "CPU: %s, %d processors in /proc/cpuinfo" % (model, info["processors"])


def _linux_ram(ctx):
    mem = parse_meminfo(ctx.read("/proc/meminfo"))
    if "MemTotal" not in mem:
        raise _Unavailable("MemTotal missing")
    free = mem.get("MemAvailable", mem.get("MemFree"))
    text = "RAM: total %s" % _gib(mem["MemTotal"] * 1024)
    if free is not None:
        text += ", available %s" % _gib(free * 1024)
    return text


def _drm_fallback(ctx):
    lines = []
    for index in range(8):
        base = "/sys/class/drm/card%d/device/" % index
        try:
            driver = posixpath.basename(ctx.fs.readlink(base + "driver"))
        except (OSError, IOError):
            driver = "unknown"
        try:
            vendor = ctx.read(base + "vendor").strip()
        except (OSError, IOError):
            vendor = ""
        if not vendor:
            # No PCI ids: a platform GPU such as Apple's (Asahi) or an ARM SoC. The device tree names the hardware.
            try:
                uevent = parse_os_release(ctx.read(base + "uevent"))
            except (OSError, IOError):
                continue
            model = uevent.get("OF_COMPATIBLE_0")
            if model:
                lines.append("GPU (sysfs card%d): platform device %s, driver %s" % (index, model, driver))
            continue
        try:
            device = ctx.read(base + "device").strip()
        except (OSError, IOError):
            device = "unknown"
        lines.append("GPU (sysfs card%d): vendor %s, device %s, driver %s" % (
            index, vendor, device, driver))
    if not lines:
        raise _Unavailable("no GPU found in /sys/class/drm")
    return lines


def _linux_gpu(ctx):
    ok, text = ctx.try_cmd(["lspci", "-nnk"])
    if not ok and text != "not found":
        raise _Unavailable("lspci: %s" % text)
    devices = parse_lspci_display(text) if ok else []
    if not devices:
        return _drm_fallback(ctx)
    lines = []
    for index, dev in enumerate(devices, 1):
        lines.append("GPU %d: %s: %s; driver in use: %s; modules: %s" % (
            index, dev["class"], dev["name"], dev["driver"] or "none",
            dev["modules"] or "none"))
    return lines


def _linux_pkg(ctx):
    found = [name for name in _PACKAGE_MANAGERS if ctx.fs.which(name)]
    return "Package managers: %s" % (", ".join(found) if found else "none found")


def _linux_flags(ctx):
    info = ctx.cache.get("osrelease") or {}
    uname = (ctx.cache.get("uname") or "").lower()
    flat = " ".join(info.values()).lower()
    flags = [
        ("SteamOS", info.get("ID", "").lower() == "steamos"),
        ("Asahi", "asahi" in flat or "asahi" in uname),
        ("WSL", "microsoft" in uname or bool(ctx.env.get("WSL_DISTRO_NAME"))),
        ("Flatpak", ctx.fs.exists("/.flatpak-info")),
        ("AppImage", bool(ctx.env.get("APPIMAGE"))),
        ("container", ctx.fs.exists("/.dockerenv") or ctx.fs.exists("/run/.containerenv")
         or bool(ctx.env.get("container"))),
    ]
    return "Environment flags: %s" % ", ".join("%s=%s" % (n, _yes_no(v)) for n, v in flags)


def _linux_fs(ctx):
    if not ctx.work:
        raise _Unavailable("no work folder given")
    path = _nearest_existing(ctx.work, ctx.fs.exists) or "/"
    try:
        fstype = parse_proc_mounts(ctx.read("/proc/mounts"), path)
    except (OSError, IOError):
        fstype = None
    if not fstype:
        fstype = ctx.cmd(["stat", "-f", "-c", "%T", path]).strip()
    if not fstype:
        raise _Unavailable("not determined")
    return "Work folder file system: %s" % fstype


# Windows

_EIGHT_DOT_THREE = {
    0: "enabled on all volumes",
    1: "disabled on all volumes",
    2: "set per volume",
    3: "disabled on all volumes except the system volume",
}


def _win_os(ctx):
    info = ctx.win()["os"]
    if not info:
        raise _Unavailable("no data")
    return "Windows: %s, version %s, build %s, %s" % (
        str(info.get("Caption", "unknown")).strip(), info.get("Version", "unknown"),
        info.get("BuildNumber", "unknown"), info.get("OSArchitecture", "unknown"))


def _win_cpu(ctx):
    cpus = ctx.win()["cpu"]
    if not cpus:
        raise _Unavailable("no data")
    lines = []
    for index, cpu in enumerate(cpus, 1):
        lines.append("CPU %d: %s, %s cores, %s logical processors" % (
            index, str(cpu.get("Name", "unknown")).strip(), cpu.get("NumberOfCores", "unknown"),
            cpu.get("NumberOfLogicalProcessors", "unknown")))
    return lines


def _win_ram(ctx):
    data = ctx.win()
    os_info = data["os"]
    total_kb = os_info.get("TotalVisibleMemorySize")
    free_kb = os_info.get("FreePhysicalMemory")
    if total_kb is None:
        total_bytes = data["cs"].get("TotalPhysicalMemory")
        if total_bytes is None:
            raise _Unavailable("no data")
        text = "RAM: total %s" % _gib(float(total_bytes))
    else:
        text = "RAM: total %s" % _gib(float(total_kb) * 1024)
    if free_kb is not None:
        text += ", free %s" % _gib(float(free_kb) * 1024)
    return text


def _win_gpu(ctx):
    gpus = ctx.win()["gpu"]
    if not gpus:
        raise _Unavailable("no video controller found")
    lines = []
    for index, gpu in enumerate(gpus, 1):
        ram = gpu.get("AdapterRAM")
        ram_text = "%d MiB" % (float(ram) / (1024 * 1024)) if ram else "unknown"
        lines.append("GPU %d: %s, driver %s dated %s, AdapterRAM %s (32-bit field), processor %s" % (
            index, str(gpu.get("Name", "unknown")).strip(), gpu.get("DriverVersion", "unknown"),
            gpu.get("DriverDate", "unknown"), ram_text, gpu.get("VideoProcessor", "unknown")))
    return lines


def _win_system(ctx):
    cs = ctx.win()["cs"]
    if not cs:
        raise _Unavailable("no data")
    return "System: %s %s" % (cs.get("Manufacturer", "unknown"), cs.get("Model", "unknown"))


def _win_reg_value(ctx, subkey, name, ps_key):
    """Registry value through winreg, falling back to the PowerShell data."""
    try:
        value = _win_reg_dword(subkey, name)
        return 0 if value is None else value
    except (_Unavailable, OSError):
        value = ctx.win()["reg"].get(ps_key)
        return None if value is None else int(value)


_FS_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"


def _win_long_paths_value(ctx):
    value = _win_reg_value(ctx, _FS_KEY, "LongPathsEnabled", "LongPathsEnabled")
    return None if value is None else value == 1


def _win_long_paths(ctx):
    return "LongPathsEnabled: %s" % _yes_no(_win_long_paths_value(ctx))


def _win_8dot3(ctx):
    value = _win_reg_value(ctx, _FS_KEY, "NtfsDisable8dot3NameCreation",
                           "NtfsDisable8dot3NameCreation")
    if value is None:
        raise _Unavailable("value not readable")
    return "8.3 short names (NtfsDisable8dot3NameCreation=%d): %s" % (
        value, _EIGHT_DOT_THREE.get(value, "unknown setting"))


def _win_devmode(ctx):
    value = _win_reg_value(
        ctx, r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
        "AllowDevelopmentWithoutDevLicense", "DeveloperMode")
    return "Developer Mode: %s" % _yes_no(None if value is None else value == 1)


def _tri(value):
    if value is None:
        return "unknown"
    return str(value).lower()


def _win_defender(ctx):
    data = ctx.win()
    status = data["defender"]
    if not status:
        raise _Unavailable("Get-MpComputerStatus returned nothing")
    lines = ["Microsoft Defender: service %s, real-time protection %s, antivirus %s" % (
        _tri(status.get("AMServiceEnabled")), _tri(status.get("RealTimeProtectionEnabled")),
        _tri(status.get("AntivirusEnabled")))]
    counts = data["exclusions"]
    if counts:
        def count(key):
            value = counts.get(key)
            if value is None or value < 0:
                return "unknown (needs administrator)"
            return str(value)
        lines.append("Microsoft Defender exclusions (counts only): paths %s, processes %s, "
                     "extensions %s" % (count("paths"), count("processes"), count("extensions")))
    return lines


def _win_av(ctx):
    names = [str(p.get("displayName")) for p in ctx.win()["av"] if p.get("displayName")]
    return "Antivirus products: %s" % (", ".join(names) if names else "none reported")


def _win_dir(ctx):
    return ctx.env.get("WINDIR") or ctx.env.get("SystemRoot") or "C:\\Windows"


def _win_dll(ctx, label, dll):
    present = ctx.fs.exists(ntpath.join(_win_dir(ctx), "System32", dll))
    return "%s (%s in System32): %s" % (label, dll, "present" if present else "missing")


def _win_fs(ctx):
    path = ctx.work_exists_parent()
    return "Work folder file system: %s" % _win_fs_type(path)


# ----------------------------------------------------------- path length

def _long_paths_text(value):
    if isinstance(value, str):
        return value.lower() if value.lower() in ("yes", "no") else "unknown"
    return _yes_no(value)


def path_check_lines(work, longest_generated=None, long_paths=None, system=None):
    """Lines describing the work folder path length and the Windows MAX_PATH risk.

    ``longest_generated`` is the length of the longest path relative to the
    work folder that the build creates, including the separator.
    """
    system = system or _detect_system()
    if work is None:
        return [PREFIX + "Work folder path length: unavailable (no work folder given)"]
    root_len = len(str(work))
    if longest_generated is None:
        return [PREFIX + "Work folder path length: %d chars" % root_len]
    if system != "windows":
        return [PREFIX + "Path length check: root %d chars, longest generated path %d chars, "
                "not applicable on this platform" % (root_len, longest_generated)]
    state = _long_paths_text(long_paths)
    risk = root_len + longest_generated > WINDOWS_PATH_LIMIT - 1 and state != "yes"
    return [PREFIX + "Path length check: root %d chars, longest generated path %d chars, "
            "limit %d, LongPathsEnabled=%s, result %s" % (
                root_len, longest_generated, WINDOWS_PATH_LIMIT, state,
                "RISK" if risk else "OK")]


# ---------------------------------------------------------------- collect

def _default_names():
    home = os.path.expanduser("~")
    user = None
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = None
    try:
        import socket
        host = socket.gethostname()
    except Exception:
        host = None
    return home, user, host


def collect(work=None, runner=None, env=None, system=None, home=None, user=None,
            host=None, fs=None, longest_generated=None, target=None):
    """Return the already-redacted ``[Diagnostics] ...`` report lines."""
    env = os.environ if env is None else env
    system = system or _detect_system()
    fs = fs or _SystemAccess()
    if home is None and user is None and host is None:
        home, user, host = _default_names()
    homes = _as_list(home) + _as_list(env.get("USERPROFILE")) + _as_list(env.get("HOME"))
    users = _as_list(user) + _as_list(env.get("USERNAME")) + _as_list(env.get("USER"))
    hosts = _as_list(host) + _as_list(env.get("COMPUTERNAME")) + _as_list(env.get("HOSTNAME"))
    work = str(work) if work else None
    ctx = _Context(work, runner, env, system, homes, users, hosts, fs)
    lines = []

    def add(label, function):
        _item(lines, label, lambda: function(ctx))

    lines.append(PREFIX + "This report stays on this computer. It only leaves it if you share this log.")
    lines.append(PREFIX + "Diagnostics script version %d, target %s" % (
        DIAGNOSTICS_VERSION, system))
    add("OS (Python)", _os_python_info)
    if system == "windows":
        add("Windows", _win_os)
    elif system == "darwin":
        add("macOS", _mac_os)
        add("Hardware model", _mac_model)
    else:
        add("Linux distribution", _linux_os)
        add("Kernel", _linux_uname)
    add("Architecture", _arch_info)
    add("Python", _python_info)
    if system == "windows":
        add("CPU", _win_cpu)
    elif system == "darwin":
        add("CPU", _mac_cpu)
    else:
        add("CPU", _linux_cpu)
    add("Logical cores", _logical_cores)
    if system == "windows":
        add("RAM", _win_ram)
        add("System", _win_system)
    elif system == "darwin":
        add("RAM", _mac_ram)
    else:
        add("RAM", _linux_ram)
    add("Free disk space (work folder)", _work_disk)
    add("Free disk space (temp folder)", _temp_disk)
    if system == "windows":
        add("Work folder file system", _win_fs)
    elif system == "darwin":
        add("Work folder file system", _mac_fs)
    else:
        add("Work folder file system", _linux_fs)

    long_paths = []
    if system == "windows":
        def read_long_paths(_ctx):
            long_paths.append(_win_long_paths_value(_ctx))
            return "LongPathsEnabled: %s" % _yes_no(long_paths[0])
        add("LongPathsEnabled", read_long_paths)
    lines.extend(path_check_lines(work, longest_generated,
                                  long_paths[0] if long_paths else None, system))
    add("Cloud-synced folder", _cloud_line)
    add("Locale", _locale_info)
    add("Elevated", _elevated)

    if system == "windows":
        add("8.3 short names", _win_8dot3)
        add("Developer Mode", _win_devmode)
        add("GPU", _win_gpu)
        add("Microsoft Defender", _win_defender)
        add("Antivirus products", _win_av)
        add("Vulkan runtime", lambda c: _win_dll(c, "Vulkan runtime", "vulkan-1.dll"))
        add("Vulkan", _vulkan_lines)
        add("VC++ runtime", lambda c: _win_dll(c, "VC++ runtime", "vcruntime140.dll"))
    elif system == "darwin":
        add("Developer directory", _mac_xcode)
        add("DEVELOPER_DIR", _mac_developer_dir)
        add("xcodebuild", _mac_xcodebuild)
        add("Command Line Tools package", _mac_clt)
        add("SDK macosx", lambda c: _mac_sdk(c, "macosx"))
        add("SDK iphoneos", lambda c: _mac_sdk(c, "iphoneos"))
        add("actool", _mac_actool)
        add("Metal compiler (macosx)", lambda c: _mac_metal(c, "macosx"))
        add("Metal compiler (iphoneos)", lambda c: _mac_metal(c, "iphoneos"))
        add("clang", _mac_clangs)
        add("Libraries (pkg-config)", _mac_libraries)
        add("Rosetta 2", _mac_rosetta)
        add("System Integrity Protection", _mac_sip)
        add("GPU", _mac_gpu)
        if target == "ios":
            add("Apple devices", _mac_devices)
    else:
        add("GPU", _linux_gpu)
        add("Vulkan", _vulkan_lines)
        add("OpenGL", _glx_lines)
        add("Mesa version", _mesa_line)
        add("Session", _display_flags)
        add("Package managers", _linux_pkg)
        add("Environment flags", _linux_flags)

    add("Tools", _tool_lines)
    add("Environment", _env_lines)

    redactor = ctx.redactor
    return [_clean_line(redactor(line)) for line in lines]


def report(work=None, **kw):
    return collect(work=work, **kw)


# ------------------------------------------------------------------- main

def _write_line(text):
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, "replace").decode(encoding, "replace") + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print the installer system and hardware report. Nothing is sent anywhere.")
    parser.add_argument("--work", help="work folder to check (disk space, path length)")
    parser.add_argument("--root", help="alias of --work")
    args = parser.parse_args(argv)
    folder = args.work or args.root
    if folder:
        folder = os.path.abspath(folder)
    try:
        lines = report(work=folder)
    except Exception as exc:
        lines = [PREFIX + "report: unavailable (%s)" % exc.__class__.__name__]
    for line in lines:
        _write_line(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
