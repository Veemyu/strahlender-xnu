import json
import subprocess
import unittest
from unittest import mock

from scripts.install import diagnostics as diag

HOME_POSIX = "/Users/someone"
HOME_WIN = "C:\\Users\\someone"
USER = "someone"
HOST = "Someones-Laptop.local"
SERIAL = "F5K9ZZ12QW"
MAC = "aa:bb:cc:dd:ee:ff"

OS_RELEASE = '''NAME="SteamOS"
PRETTY_NAME="SteamOS Holo"
ID=steamos
VERSION_ID=3.5
VARIANT_ID=steamdeck
# comment
'''

CPUINFO_X86 = '''processor\t: 0
model name\t: AMD Ryzen 7 5800X 8-Core Processor
model\t\t: 33
processor\t: 1
model name\t: AMD Ryzen 7 5800X 8-Core Processor
'''

CPUINFO_ARM = '''processor\t: 0
BogoMIPS\t: 50.00
CPU implementer\t: 0x61
CPU part\t: 0x024
processor\t: 1
CPU implementer\t: 0x61
Hardware\t: Apple M1
Serial\t\t: 000000001234
'''

MEMINFO = '''MemTotal:       16318024 kB
MemFree:         1048576 kB
MemAvailable:    8388608 kB
'''

SW_VERS = "ProductName:\t\tmacOS\nProductVersion:\t\t14.4.1\nBuildVersion:\t\t23E224\n"

SP_APPLE = '''Graphics/Displays:

    Apple M2 Pro:

      Chipset Model: Apple M2 Pro
      Type: GPU
      Bus: Built-In
      Total Number of Cores: 19
      Vendor: Apple (0x106b)
      Metal Support: Metal 3
      Displays:
        Color LCD:
          Display Type: Built-in Liquid Retina XDR Display
          Resolution: 3456 x 2234 Retina
          Main Display: Yes
          Connection Type: Internal
        LG UltraFine:
          Resolution: 3840 x 2160 (2160p/4K UHD 1 - Ultra High Definition)
          Display Serial Number: 123ABCDEF
'''

SP_INTEL_AMD = '''Graphics/Displays:

    Intel UHD Graphics 630:

      Chipset Model: Intel UHD Graphics 630
      Type: GPU
      Bus: Built-In
      VRAM (Dynamic, Max): 1536 MB
      Vendor: Intel
      Metal Family: Supported, Metal GPUFamily macOS 2
      Displays:
        Color LCD:
          Resolution: 3072 x 1920 Retina

    AMD Radeon Pro 5500M:

      Chipset Model: AMD Radeon Pro 5500M
      Type: GPU
      Bus: PCIe
      VRAM (Total): 8 GB
      Vendor: AMD (0x1002)
      Metal Family: Supported, Metal GPUFamily macOS 2
'''

LSPCI = '''00:00.0 Host bridge [0600]: Advanced Micro Devices, Inc. [AMD] Root Complex [1022:1630]
\tSubsystem: Advanced Micro Devices, Inc. [AMD] Root Complex [1022:1630]
05:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA106 [GeForce RTX 3060] [10de:2503] (rev a1)
\tSubsystem: Gigabyte Technology Co., Ltd Device [1458:4074]
\tKernel driver in use: nvidia
\tKernel modules: nouveau, nvidia_drm, nvidia
06:00.0 Display controller [0380]: Advanced Micro Devices, Inc. [AMD/ATI] Cezanne [1002:1638] (rev c8)
\tKernel driver in use: amdgpu
\tKernel modules: amdgpu
07:00.0 Ethernet controller [0200]: Realtek RTL8111 [10ec:8168]
\tKernel driver in use: r8169
'''

VULKAN = '''==========
VULKANINFO
==========

Vulkan Instance Version: 1.3.280

Devices:
========
GPU0:
\tapiVersion         = 1.3.274
\tdriverVersion      = 24.0.3
\tvendorID           = 0x1002
\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
\tdeviceName         = AMD Radeon Graphics (RADV REMBRANDT)
\tdriverID           = DRIVER_ID_MESA_RADV
\tdriverName         = radv
\tdriverInfo         = Mesa 24.0.3-1ubuntu1
\tconformanceVersion = 1.3.0.0
\tdeviceUUID         = 00000000-1234-5678-9abc-def012345678
'''

GLX = '''name of display: :0
OpenGL vendor string: AMD
OpenGL renderer string: AMD Radeon Graphics (radeonsi, rembrandt, LLVM 17.0.6, DRM 3.57)
OpenGL version string: 4.6 (Compatibility Profile) Mesa 24.0.3-1ubuntu1
'''

DF = '''Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/disk3s5 482797652 300000000 150000000 67% /System/Volumes/Data
'''

MOUNT_MAC = '''/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, protect, sealed)
'''

MOUNT_LINUX = '''/dev/sda1 on /home type ext4 (rw,relatime)
tmpfs on /run type tmpfs (rw,nosuid)
'''

PROC_MOUNTS = '''/dev/nvme0n1p2 / btrfs rw 0 0
/dev/sda1 /home ext4 rw 0 0
/dev/sdb1 /mnt/with\\040space ntfs3 rw 0 0
'''

WIN_DATA = {
    "os": {"Caption": "Microsoft Windows 11 Pro", "Version": "10.0.22631",
           "BuildNumber": "22631", "OSArchitecture": "64-bit",
           "FreePhysicalMemory": 8388608, "TotalVisibleMemorySize": 16777216},
    "cpu": [{"Name": "AMD Ryzen 5 5600X", "NumberOfCores": 6, "NumberOfLogicalProcessors": 12}],
    "gpu": [{"Name": "NVIDIA GeForce RTX 3060", "DriverVersion": "31.0.15.5186",
             "DriverDate": "2024-05-01", "AdapterRAM": 4293918720,
             "VideoProcessor": "NVIDIA GeForce RTX 3060"},
            {"Name": "AMD Radeon(TM) Graphics", "DriverVersion": "31.0.21001.1005",
             "DriverDate": "2023-10-10", "AdapterRAM": 536870912,
             "VideoProcessor": "AMD Radeon Graphics Processor (0x1638)"}],
    "cs": {"Manufacturer": "ASUS", "Model": "ROG STRIX", "TotalPhysicalMemory": 17179869184},
    "defender": {"AMServiceEnabled": True, "RealTimeProtectionEnabled": True,
                 "AntivirusEnabled": True},
    "exclusions": {"paths": 3, "processes": 1, "extensions": 0},
    "av": [{"displayName": "Windows Defender"}],
    "reg": {"LongPathsEnabled": 0, "NtfsDisable8dot3NameCreation": 2, "DeveloperMode": 1},
}


ACTOOL = '''<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>com.apple.actool.version</key><dict>
<key>bundle-version</key><string>22685</string><key>short-bundle-version</key><string>15.3</string>
</dict></dict></plist>
'''

DEVICES = {"result": {"devices": [
    {"identifier": "11111111-2222-3333-4444-555555555555",
     "hardwareProperties": {"platform": "iOS", "udid": "00008103-001A2B3C4D5E001E", "marketingName": "iPad Pro 11-inch (3rd generation)",
                            "productType": "iPad13,4", "reality": "physical"},
     "deviceProperties": {"name": "Someones iPad", "osVersionNumber": "17.4.1"},
     "connectionProperties": {"tunnelState": "connected"}},
    {"hardwareProperties": {"platform": "iOS", "udid": "x", "productType": "iPhone15,2", "reality": "physical"},
     "deviceProperties": {"osVersionNumber": "18.0"}, "connectionProperties": {"tunnelState": "disconnected"}},
    {"hardwareProperties": {"platform": "iOS", "reality": "simulated", "productType": "iPhone99,9"}},
    {"hardwareProperties": {"platform": "watchOS", "productType": "Watch7,1"}},
]}}


class FakeResult(object):
    def __init__(self, out="", code=0, err=""):
        self.stdout = out
        self.stderr = err
        self.returncode = code


class FakeRunner(object):
    """Maps the first argument (and optionally more) of a command to a canned result."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        for size in (5, 4, 3, 2, 1):
            key = " ".join(args[:size])
            if key in self.table:
                value = self.table[key]
                if isinstance(value, BaseException):
                    raise value
                if isinstance(value, tuple):
                    return FakeResult(value[1], value[0])
                return FakeResult(value)
        raise FileNotFoundError(args[0])


class FakeFs(object):
    def __init__(self, files=None, links=None, present=(), which=(), euid=1000):
        self.files = files or {}
        self.links = links or {}
        self.present = set(present)
        self.which_names = set(which)
        self.euid = euid

    def read(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def exists(self, path):
        return path in self.files or path in self.present

    def readlink(self, path):
        if path not in self.links:
            raise FileNotFoundError(path)
        return self.links[path]

    def which(self, name):
        return "/usr/bin/" + name if name in self.which_names else None

    def geteuid(self):
        return self.euid


def collect(system, runner, fs=None, work="/Users/someone/Work/build", **kw):
    env = kw.pop("env", {"HOME": HOME_POSIX, "USER": USER, "LANG": "en_US.UTF-8",
                         "BDSP_FOO": "1", "BDSP_TOKEN": "secretvalue"})
    return diag.collect(work=work, runner=runner, env=env, system=system, home=HOME_POSIX,
                        user=USER, host=HOST, fs=fs or FakeFs(), **kw)


def joined(lines):
    return "\n".join(lines)


class RedactTests(unittest.TestCase):
    def test_home_variants(self):
        home = "C:\\Users\\someone"
        for text in ("C:\\Users\\someone\\AppData", "C:/Users/someone/AppData",
                     "C:\\\\Users\\\\someone\\\\AppData", "c:\\users\\SOMEONE\\AppData"):
            out = diag.redact(text, home=home)
            self.assertTrue(out.startswith("<home>"), out)
            self.assertNotIn("omeone", out.lower().replace("someone", "") + "")
            self.assertNotIn("someone", out.lower())
        self.assertEqual(diag.redact("/Users/someone/Work", home="/Users/someone"), "<home>/Work")

    def test_other_profiles_are_redacted_without_home(self):
        self.assertEqual(diag.redact("D:\\Users\\bob\\x"), "<home>\\x")
        self.assertEqual(diag.redact("/home/alice/src"), "<home>/src")
        self.assertEqual(diag.redact("/Users/Shared/x"), "/Users/Shared/x")

    def test_user_as_whole_word_only(self):
        out = diag.redact("login someone ok; someone_else_tool; Someone-pc", user="someone")
        self.assertEqual(out, "login <user> ok; someone_else_tool; <user>-pc")

    def test_generic_user_names_are_left_alone(self):
        self.assertEqual(diag.redact("root 12 chars", user="root"), "root 12 chars")

    def test_host(self):
        out = diag.redact("host Someones-Laptop.local and Someones-Laptop", host=HOST)
        self.assertEqual(out, "host <host> and <host>")

    def test_placeholder_not_corrupted_by_short_names(self):
        out = diag.redact("addr aa:bb:cc:dd:ee:ff", user="mac")
        self.assertEqual(out, "addr <mac>")

    def test_identifiers(self):
        self.assertEqual(diag.redact("mac aa:bb:cc:dd:ee:ff and AA-BB-CC-DD-EE-FF"),
                         "mac <mac> and <mac>")
        self.assertEqual(diag.redact("uuid 12345678-90ab-cdef-1234-567890abcdef."),
                         "uuid <uuid>.")
        self.assertEqual(diag.redact("from 192.168.1.20 now"), "from <ip> now")
        self.assertEqual(diag.redact("v6 2001:db8::8a2e:370:7334 and fe80::1%en0 and ::1"),
                         "v6 <ip> and <ip> and <ip>")
        self.assertEqual(diag.redact("2001:0db8:0000:0000:0000:ff00:0042:8329"), "<ip>")
        self.assertEqual(diag.redact("key " + "ab12" * 8), "key <key>")
        self.assertEqual(diag.redact("Serial Number (system): C02XYZ123"),
                         "Serial Number (system): <serial>")
        self.assertEqual(diag.redact('"SerialNumber":"ABC123",'), '"SerialNumber":"<serial>",')

    def test_versions_and_similar_text_survive(self):
        text = ("10.0.22631 3.9.6 Python 3.14.3 conformanceVersion = 1.3.0.0 "
                "driver 31.0.15.5186 time 12:30:45 std::string Mesa 24.0.3-1ubuntu1 "
                "build 23E224 clang-1500.3.9.4")
        self.assertEqual(diag.redact(text), text)


class ParserTests(unittest.TestCase):
    def test_os_release(self):
        info = diag.parse_os_release(OS_RELEASE)
        self.assertEqual(info["PRETTY_NAME"], "SteamOS Holo")
        self.assertEqual(info["VARIANT_ID"], "steamdeck")
        self.assertNotIn("# comment", info)

    def test_cpuinfo(self):
        x86 = diag.parse_cpuinfo(CPUINFO_X86)
        self.assertEqual(x86["model"], "AMD Ryzen 7 5800X 8-Core Processor")
        self.assertEqual(x86["processors"], 2)
        self.assertEqual(x86["hardware"], "")
        arm = diag.parse_cpuinfo(CPUINFO_ARM)
        self.assertEqual((arm["model"], arm["implementer"], arm["part"], arm["hardware"]),
                         ("", "0x61", "0x024", "Apple M1"))

    def test_meminfo(self):
        self.assertEqual(diag.parse_meminfo(MEMINFO),
                         {"MemTotal": 16318024, "MemFree": 1048576, "MemAvailable": 8388608})

    def test_sw_vers(self):
        info = diag.parse_sw_vers(SW_VERS)
        self.assertEqual(info["ProductVersion"], "14.4.1")
        self.assertEqual(info["BuildVersion"], "23E224")

    def test_system_profiler_apple_silicon(self):
        info = diag.parse_system_profiler_displays(SP_APPLE)
        self.assertEqual(len(info["gpus"]), 1)
        gpu = info["gpus"][0]
        self.assertEqual((gpu["chipset"], gpu["cores"], gpu["metal"]),
                         ("Apple M2 Pro", "19", "Metal 3"))
        self.assertEqual(info["displays"], 2)

    def test_system_profiler_intel_amd(self):
        info = diag.parse_system_profiler_displays(SP_INTEL_AMD)
        self.assertEqual([g["chipset"] for g in info["gpus"]],
                         ["Intel UHD Graphics 630", "AMD Radeon Pro 5500M"])
        self.assertEqual(info["gpus"][0]["vram"], "1536 MB")
        self.assertEqual(info["gpus"][1]["vram"], "8 GB")
        self.assertIn("Metal GPUFamily", info["gpus"][1]["metal"])

    def test_lspci_keeps_only_display_blocks(self):
        devices = diag.parse_lspci_display(LSPCI)
        self.assertEqual(len(devices), 2)
        self.assertIn("[10de:2503]", devices[0]["name"])
        self.assertEqual(devices[0]["driver"], "nvidia")
        self.assertEqual(devices[0]["modules"], "nouveau, nvidia_drm, nvidia")
        self.assertEqual(devices[1]["class"], "Display controller")
        self.assertEqual(devices[1]["driver"], "amdgpu")

    def test_vulkaninfo_summary(self):
        info = diag.parse_vulkaninfo_summary(VULKAN)
        self.assertEqual(info["instance"], "1.3.280")
        dev = info["devices"][0]
        self.assertEqual((dev["name"], dev["api"], dev["driver"], dev["type"]),
                         ("AMD Radeon Graphics (RADV REMBRANDT)", "1.3.274", "radv",
                          "integrated_gpu"))
        self.assertEqual(diag.mesa_version(dev["driver_info"]), "24.0.3-1ubuntu1")

    def test_glxinfo(self):
        info = diag.parse_glxinfo_b(GLX)
        self.assertIn("radeonsi", info["renderer"])
        self.assertEqual(info["mesa"], "24.0.3-1ubuntu1")

    def test_windows_json_single_object_list_and_bom(self):
        single = dict(WIN_DATA, gpu={"Name": "Only GPU"}, av={"displayName": "X"})
        parsed = diag.parse_windows_json("\ufeff" + json.dumps(single))
        self.assertEqual([g["Name"] for g in parsed["gpu"]], ["Only GPU"])
        self.assertEqual(parsed["av"][0]["displayName"], "X")
        parsed = diag.parse_windows_json("noise\n" + json.dumps(WIN_DATA) + "\n")
        self.assertEqual(len(parsed["gpu"]), 2)
        self.assertEqual(parsed["cpu"][0]["NumberOfCores"], 6)
        self.assertEqual(parsed["defender"], WIN_DATA["defender"])
        with self.assertRaises(ValueError):
            diag.parse_windows_json("nothing here")

    def test_df_and_mount(self):
        device, mount = diag.parse_df(DF)
        self.assertEqual((device, mount), ("/dev/disk3s5", "/System/Volumes/Data"))
        self.assertEqual(diag.parse_mount(MOUNT_MAC, mount, device), "apfs")
        self.assertEqual(diag.parse_mount(MOUNT_LINUX, "/home"), "ext4")
        self.assertIsNone(diag.parse_mount(MOUNT_LINUX, "/nowhere"))
        with self.assertRaises(ValueError):
            diag.parse_df("Filesystem\n")

    def test_proc_mounts_longest_match(self):
        self.assertEqual(diag.parse_proc_mounts(PROC_MOUNTS, "/home/x/work"), "ext4")
        self.assertEqual(diag.parse_proc_mounts(PROC_MOUNTS, "/homework"), "btrfs")
        self.assertEqual(diag.parse_proc_mounts(PROC_MOUNTS, "/mnt/with space/a"), "ntfs3")

    def test_version_first_line(self):
        self.assertEqual(diag.version_first_line("\n\ngit version 2.43.0\nmore"),
                         "git version 2.43.0")
        self.assertEqual(diag.version_first_line(""), "")

    def test_vm_stat(self):
        text = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free: 10.\nPages inactive: 5.\nPages speculative: 1.\n")
        self.assertEqual(diag.parse_vm_stat(text), 16 * 16384)


class RunTests(unittest.TestCase):
    def test_success_failure_and_exceptions(self):
        self.assertEqual(diag.run(["a"], runner=lambda a, **k: FakeResult("out\n")),
                         (True, "out\n"))
        self.assertEqual(diag.run(["a"], runner=lambda a, **k: FakeResult(b"\xff", 0)),
                         (True, "\ufffd"))
        self.assertEqual(diag.run(["a"], runner=lambda a, **k: FakeResult("o", 3)),
                         (False, "exit code 3"))

        def boom(exc):
            def runner(args, **kwargs):
                raise exc
            return runner

        self.assertEqual(diag.run(["a"], runner=boom(FileNotFoundError())), (False, "not found"))
        self.assertEqual(diag.run(["a"], runner=boom(subprocess.TimeoutExpired("a", 8))),
                         (False, "timeout"))
        self.assertEqual(diag.run(["a"], runner=boom(PermissionError())),
                         (False, "permission denied"))

    def test_runner_arguments(self):
        seen = {}

        def runner(args, **kwargs):
            seen.update(kwargs)
            return FakeResult("x")

        diag.run(["a", "b"], timeout=5, runner=runner)
        self.assertIs(seen["shell"], False)
        self.assertEqual(seen["stdin"], subprocess.DEVNULL)
        self.assertEqual(seen["timeout"], 5)


class ItemTests(unittest.TestCase):
    def test_failure_does_not_stop_following_items(self):
        lines = []

        def bad():
            raise ValueError("broken thing")

        self.assertFalse(diag._item(lines, "First", bad))
        self.assertTrue(diag._item(lines, "Second", lambda: ["a", "b"]))
        self.assertEqual(lines[0], "[Diagnostics] First: unavailable (ValueError: broken thing)")
        self.assertEqual(lines[1:], ["[Diagnostics] a", "[Diagnostics] b"])

    def test_timeout_and_unavailable_reasons(self):
        lines = []

        def slow():
            raise subprocess.TimeoutExpired("x", 8)

        def missing():
            raise diag._Unavailable("not found")

        diag._item(lines, "Slow", slow)
        diag._item(lines, "Gone", missing)
        self.assertEqual(lines, ["[Diagnostics] Slow: unavailable (timeout)",
                                 "[Diagnostics] Gone: unavailable (not found)"])


class PathCheckTests(unittest.TestCase):
    def test_length_only(self):
        self.assertEqual(diag.path_check_lines("C:\\Work\\x"),
                         ["[Diagnostics] Work folder path length: 9 chars"])

    def test_risk_ok_and_not_applicable(self):
        work = "C" * 100
        risk = diag.path_check_lines(work, 160, False, system="windows")
        self.assertEqual(risk, ["[Diagnostics] Path length check: root 100 chars, longest "
                                "generated path 160 chars, limit 260, LongPathsEnabled=no, "
                                "result RISK"])
        self.assertIn("LongPathsEnabled=unknown, result RISK",
                      diag.path_check_lines(work, 160, None, system="windows")[0])
        self.assertIn("LongPathsEnabled=yes, result OK",
                      diag.path_check_lines(work, 160, True, system="windows")[0])
        self.assertIn("result OK", diag.path_check_lines(work, 159, False, system="windows")[0])
        self.assertIn("not applicable on this platform",
                      diag.path_check_lines(work, 400, None, system="linux")[0])


class CollectTests(unittest.TestCase):
    def assert_private(self, lines):
        text = joined(lines)
        for secret in (USER, HOME_POSIX, HOME_WIN, SERIAL, MAC, "Someones", "secretvalue"):
            self.assertNotIn(secret.lower(), text.lower())
        for line in lines:
            self.assertTrue(line.startswith("[Diagnostics] "), line)
            self.assertNotIn("\u2013", line)
            self.assertNotIn("\u2014", line)

    def test_darwin(self):
        runner = FakeRunner({
            "sw_vers": SW_VERS + "Serial Number: %s\n" % SERIAL,
            "sysctl -n machdep.cpu.brand_string": "Apple M2 Pro\n",
            "sysctl -n hw.logicalcpu": "12\n",
            "sysctl -n hw.memsize": "34359738368\n",
            "sysctl -n hw.model": "Mac14,9\n",
            "sysctl -n sysctl.proc_translated": "1\n",
            "system_profiler SPDisplaysDataType": SP_APPLE + "Serial Number: %s\n" % SERIAL,
            "xcode-select -p": "/Users/someone/Xcode/Developer\n",
            "xcodebuild -version": "Xcode 15.3\nBuild version 15E204a\n",
            "xcrun --sdk macosx --show-sdk-path": "/Users/someone/SDKs/MacOSX.sdk\n",
            "xcrun --sdk macosx --show-sdk-version": "14.4\n",
            "xcrun --sdk iphoneos --show-sdk-path": "/Users/someone/SDKs/iPhoneOS.sdk\n",
            "xcrun --sdk iphoneos --show-sdk-version": "17.4\n",
            "xcrun actool --version": ACTOOL,
            "xcrun -sdk macosx": "Apple metal version 32023.100 (metalfe-32023.100.1)\nTarget: air64-apple-darwin23.4.0\n",
            "xcrun -sdk iphoneos": ("1", "error: sdk \"iphoneos\" cannot be located"),
            "pkgutil --pkg-info=com.apple.pkg.CLTools_Executables": "package-id: com.apple.pkg.CLTools_Executables\nversion: 15.3.0.0.1.1708646388\n",
            "/usr/bin/clang --version": "Apple clang version 15.0.0 (clang-1500.3.9.4)\nTarget: arm64-apple-darwin23.4.0\n",
            "pkg-config --modversion sdl3": "3.2.8\n",
            "pkg-config --modversion libavcodec": "61.3.100\n",
            "csrutil status": "System Integrity Protection status: enabled.\n",
            "df -P": DF,
            "mount": MOUNT_MAC + "en0 aa:bb:cc:dd:ee:ff\n",
            "vm_stat": "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                       "Pages free: 100.\nPages inactive: 100.\nPages speculative: 0.\n",
            "git --version": "git version 2.39.3 (Apple Git-146)\n",
        })
        lines = collect("darwin", runner)
        text = joined(lines)
        self.assertIn("[Diagnostics] macOS: macOS 14.4.1 (build 23E224)", text)
        self.assertIn("CPU: Apple M2 Pro, 12 logical cores", text)
        self.assertIn("Python process translated (Rosetta 2)", text)
        self.assertIn("RAM: total 32.0 GiB", text)
        self.assertIn("GPU 1: Apple M2 Pro, 19 cores, Metal: Metal 3", text)
        self.assertIn("Developer directory (xcode-select -p): <home>/Xcode/Developer", text)
        self.assertIn("xcodebuild: Xcode 15.3; Build version 15E204a", text)
        self.assertIn("SDK macosx: version 14.4, path <home>/SDKs/MacOSX.sdk", text)
        self.assertIn("SDK iphoneos: version 17.4, path <home>/SDKs/iPhoneOS.sdk", text)
        self.assertIn("Command Line Tools package: version 15.3.0.0.1.1708646388", text)
        self.assertIn("actool: version 15.3 (Icon Composer icons need 26 or newer)", text)
        self.assertIn("Metal compiler (macosx): Apple metal version 32023.100 (metalfe-32023.100.1)", text)
        self.assertIn("Metal compiler (iphoneos): unavailable (exit code 1)", text)
        self.assertIn("Apple clang (/usr/bin/clang): Apple clang version 15.0.0 (clang-1500.3.9.4)", text)
        self.assertIn("Homebrew LLVM clang (Apple silicon): not installed", text)
        self.assertIn("Libraries (pkg-config): sdl3 3.2.8, libavcodec 61.3.100, libavformat not found, libavutil not found", text)
        self.assertIn("DEVELOPER_DIR: unset", text)
        self.assertNotIn("Apple devices", text)
        self.assertEqual(lines[0], "[Diagnostics] This report stays on this computer. It only leaves it if you share this log.")
        self.assertIn("System Integrity Protection: enabled", text)
        self.assertIn("Work folder file system: apfs", text)
        self.assertIn("Tool git: git version 2.39.3 (Apple Git-146)", text)
        self.assertIn("Tool cmake: not found", text)
        self.assertIn("Environment BDSP_* variables: BDSP_FOO=1, BDSP_TOKEN", text)
        self.assert_private(lines)

    def test_darwin_ios_target_lists_connected_devices_without_names_or_ids(self):
        def runner(args, **kwargs):
            if args[:4] == ["xcrun", "devicectl", "list", "devices"]:
                with open(args[args.index("--json-output") + 1], "w") as stream:
                    json.dump(DEVICES, stream)
                return FakeResult("")
            if args[:2] == ["xcode-select", "-p"]:
                return FakeResult("/Applications/Xcode.app/Contents/Developer\n")
            raise FileNotFoundError(args[0])
        lines = diag.collect(work="/Users/someone/Work/build", runner=runner, env={"HOME": HOME_POSIX, "USER": USER}, system="darwin",
                             home=HOME_POSIX, user=USER, host=HOST, fs=FakeFs(), target="ios")
        text = joined(lines)
        self.assertIn("Apple device 1: iPad Pro 11-inch (3rd generation) (iPad13,4), iOS 17.4.1, connected", text)
        self.assertIn("Apple device 2: iPhone15,2, iOS 18.0, disconnected", text)
        self.assertNotIn("iPhone99,9", text)
        self.assertNotIn("Watch7", text)
        for private in ("Someones", "00008103", "11111111"):
            self.assertNotIn(private, text)
        def empty(args, **kwargs):
            if args[:3] == ["xcrun", "devicectl", "list"]:
                with open(args[args.index("--json-output") + 1], "w") as stream:
                    json.dump({"result": {"devices": []}}, stream)
            return FakeResult("/Applications/Xcode.app/Contents/Developer\n")
        none = diag.collect(work=None, runner=empty, env={}, system="darwin", home=HOME_POSIX, user=USER, host=HOST,
                            fs=FakeFs(), target="ios")
        self.assertIn("Apple devices for the iOS target: none found", joined(none))

    def test_darwin_without_developer_tools_skips_shims(self):
        runner = FakeRunner({"xcode-select -p": ("2", "")})
        runner.table["xcode-select -p"] = (2, "")
        lines = collect("darwin", runner)
        text = joined(lines)
        self.assertIn("Tool git: not checked (developer tools not installed)", text)
        self.assertNotIn("git", [c[0][0] for c in runner.calls])
        self.assertIn("Developer directory: unavailable (exit code 2)", text)
        self.assertIn("Apple clang (/usr/bin/clang): not checked (developer tools not installed)", text)
        self.assertIn("actool: unavailable (not checked, developer tools not installed)", text)

    def test_linux(self):
        runner = FakeRunner({
            "uname -srm": "Linux 6.1.52-valve16-1-neptune-61 x86_64\n",
            "lscpu": "Model name: AMD Custom APU 0405\n",
            "lspci -nnk": LSPCI + "\tSerial number: %s\n" % SERIAL,
            "vulkaninfo --summary": VULKAN,
            "glxinfo -B": GLX,
            "git --version": "git version 2.43.0\n",
            "stat": "unused\n",
        })
        fs = FakeFs(files={
            "/etc/os-release": OS_RELEASE,
            "/proc/cpuinfo": CPUINFO_X86,
            "/proc/meminfo": MEMINFO,
            "/proc/mounts": PROC_MOUNTS,
        }, present=["/.dockerenv", "/home", "/"], which=["apt", "nix-env"])
        env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE",
               "WAYLAND_DISPLAY": "wayland-0", "WSL_DISTRO_NAME": "Ubuntu",
               "LANG": "de_DE.UTF-8"}
        lines = collect("linux", runner, fs, work="/home/someone/Work", env=env)
        text = joined(lines)
        self.assertIn("Linux distribution: SteamOS Holo (ID=steamos, VERSION_ID=3.5, "
                      "VARIANT_ID=steamdeck)", text)
        self.assertIn("Kernel: Linux 6.1.52-valve16-1-neptune-61 x86_64", text)
        self.assertIn("CPU: AMD Ryzen 7 5800X 8-Core Processor (lscpu: AMD Custom APU 0405)", text)
        self.assertIn("RAM: total 15.6 GiB, available 8.0 GiB", text)
        self.assertIn("[10de:2503]", text)
        self.assertIn("driver in use: amdgpu; modules: amdgpu", text)
        self.assertIn("Vulkan instance version: 1.3.280", text)
        self.assertIn("OpenGL: renderer AMD Radeon Graphics (radeonsi", text)
        self.assertIn("Mesa version: 24.0.3-1ubuntu1", text)
        self.assertIn("XDG_SESSION_TYPE=wayland, XDG_CURRENT_DESKTOP=KDE, WAYLAND_DISPLAY set, "
                      "DISPLAY unset", text)
        self.assertIn("Package managers: apt, nix-env", text)
        self.assertIn("SteamOS=yes, Asahi=no, WSL=yes, Flatpak=no, AppImage=no, container=yes",
                      text)
        self.assertIn("Work folder file system: ext4", text)
        self.assertIn("Environment BDSP_* variables: none", text)
        self.assertIn("Tool git: git version 2.43.0", text)
        self.assertIn("Locale: ", text)
        self.assertIn("LANG=de_DE.UTF-8", text)
        self.assert_private(lines)

    def test_linux_drm_fallback_and_missing_files(self):
        runner = FakeRunner({"uname -srm": ("1", "")})
        runner.table["uname -srm"] = (1, "")
        fs = FakeFs(files={"/sys/class/drm/card0/device/vendor": "0x1002\n",
                           "/sys/class/drm/card0/device/device": "0x1638\n"},
                    links={"/sys/class/drm/card0/device/driver": "../../../bus/pci/drivers/amdgpu"})
        text = joined(collect("linux", runner, fs))
        self.assertIn("GPU (sysfs card0): vendor 0x1002, device 0x1638, driver amdgpu", text)
        self.assertIn("Linux distribution: unavailable (os-release not found)", text)
        self.assertIn("Kernel: unavailable (exit code 1)", text)
        self.assertIn("CPU: unavailable (", text)
        self.assertIn("Vulkan: unavailable (not found)", text)

    def test_linux_platform_gpu_without_pci_ids_is_named_by_the_device_tree(self):
        runner = FakeRunner({"lspci -nnk": "00:00.0 Host bridge [0600]: Example Bridge [1234:0001]\n"})
        fs = FakeFs(files={"/sys/class/drm/card1/device/uevent":
                           "DRIVER=asahi\nOF_NAME=gpu\nOF_COMPATIBLE_0=apple,agx-t8112\nOF_COMPATIBLE_1=apple,agx-g14g\n"},
                    links={"/sys/class/drm/card1/device/driver": "../../../../bus/platform/drivers/asahi"})
        text = joined(collect("linux", runner, fs))
        self.assertIn("GPU (sysfs card1): platform device apple,agx-t8112, driver asahi", text)
        self.assertNotIn("GPU: unavailable", text)

    def test_windows(self):
        ps = json.dumps(WIN_DATA)
        runner = FakeRunner({
            "powershell.exe": "\ufeff" + ps + "\n",
            "vulkaninfo --summary": VULKAN,
            "git --version": "git version 2.45.1.windows.1\n",
            "ffmpeg -version": "ffmpeg version 7.0 Copyright (c) 2000-2024\n",
        })
        fs = FakeFs(present=["C:\\Windows\\System32\\vulkan-1.dll"])
        env = {"USERPROFILE": HOME_WIN, "USERNAME": USER, "WINDIR": "C:\\Windows",
               "BDSP_DEBUG": "true", "PROCESSOR_ARCHITEW6432": "ARM64"}
        with mock.patch.object(diag, "_win_fs_type", return_value="NTFS"), \
                mock.patch.object(diag, "_win_is_admin", return_value=False), \
                mock.patch.object(diag, "_win_reg_dword", side_effect=diag._Unavailable("test")), \
                mock.patch("platform.machine", return_value="AMD64"):
            lines = collect("windows", runner, fs, work="C:\\Users\\someone\\Work\\" + "d" * 80,
                            env=env, longest_generated=200)
        text = joined(lines)
        self.assertEqual(sum(1 for c in runner.calls if c[0][0] == "powershell.exe"), 1)
        ps_call = [c for c in runner.calls if c[0][0] == "powershell.exe"][0]
        self.assertEqual(ps_call[0][1:6], ["-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                           "Bypass", "-Command"])
        self.assertEqual(len(ps_call[0]), 7)
        self.assertNotIn("wmic", joined(ps_call[0]).lower())
        self.assertIn("Windows: Microsoft Windows 11 Pro, version 10.0.22631, build 22631, "
                      "64-bit", text)
        self.assertIn("CPU 1: AMD Ryzen 5 5600X, 6 cores, 12 logical processors", text)
        self.assertIn("RAM: total 16.0 GiB, free 8.0 GiB", text)
        self.assertIn("GPU 1: NVIDIA GeForce RTX 3060, driver 31.0.15.5186 dated 2024-05-01", text)
        self.assertIn("GPU 2: AMD Radeon(TM) Graphics, driver 31.0.21001.1005", text)
        self.assertIn("System: ASUS ROG STRIX", text)
        self.assertIn("Work folder file system: NTFS", text)
        self.assertIn("LongPathsEnabled: no", text)
        self.assertIn("8.3 short names (NtfsDisable8dot3NameCreation=2): set per volume", text)
        self.assertIn("Developer Mode: yes", text)
        self.assertIn("Microsoft Defender: service true, real-time protection true, "
                      "antivirus true", text)
        self.assertIn("exclusions (counts only): paths 3, processes 1, extensions 0", text)
        self.assertIn("Antivirus products: Windows Defender", text)
        self.assertIn("Vulkan runtime (vulkan-1.dll in System32): present", text)
        self.assertIn("VC++ runtime (vcruntime140.dll in System32): missing", text)
        self.assertIn("Vulkan device 1: AMD Radeon Graphics (RADV REMBRANDT)", text)
        self.assertIn("Elevated: no", text)
        self.assertIn("Python process emulated or WOW64 (host architecture ARM64)", text)
        self.assertIn("root 102 chars, longest generated path 200 chars, limit 260, "
                      "LongPathsEnabled=no, result RISK", text)
        self.assertIn("Tool ffmpeg: ffmpeg version 7.0", text)
        self.assertIn("Environment BDSP_* variables: BDSP_DEBUG=true", text)
        self.assertIn("cloud-synced folder (OneDrive, Dropbox, iCloud): no", text)
        self.assert_private(lines)

    def test_windows_powershell_failure_and_registry_fallback(self):
        runner = FakeRunner({"powershell.exe": subprocess.TimeoutExpired("powershell.exe", 20)})
        with mock.patch.object(diag, "_win_reg_dword", side_effect=[1, None, None]), \
                mock.patch.object(diag, "_win_fs_type", side_effect=OSError("denied")):
            lines = collect("windows", runner, work="C:\\Users\\someone\\OneDrive\\x")
        text = joined(lines)
        self.assertIn("Windows: unavailable (timeout)", text)
        self.assertIn("CPU: unavailable (timeout)", text)
        self.assertIn("Microsoft Defender: unavailable (timeout)", text)
        self.assertEqual(sum(1 for c in runner.calls if c[0][0] == "powershell.exe"), 1)
        self.assertIn("LongPathsEnabled: yes", text)
        self.assertIn("8.3 short names (NtfsDisable8dot3NameCreation=0): enabled on all volumes",
                      text)
        self.assertIn("Developer Mode: no", text)
        self.assertIn("Work folder file system: unavailable (OSError: denied)", text)
        self.assertIn("cloud-synced folder (OneDrive, Dropbox, iCloud): yes", text)
        self.assertNotIn("OneDrive\\x", text)
        self.assert_private(lines)

    def test_every_command_timeout_never_raises(self):
        runner = FakeRunner({name: subprocess.TimeoutExpired(name, 8) for name in (
            "sw_vers", "sysctl", "system_profiler", "xcode-select", "xcodebuild", "xcrun",
            "csrutil", "df", "mount", "vm_stat")})
        lines = collect("darwin", runner)
        text = joined(lines)
        self.assertIn("macOS: unavailable (timeout)", text)
        self.assertIn("GPU: unavailable (timeout)", text)
        self.assertIn("Diagnostics script version", text)
        self.assertIn("Environment BDSP_* variables", text)

    def test_main_prints_report_and_returns_zero(self):
        printed = []
        with mock.patch.object(diag, "report", return_value=["[Diagnostics] x"]), \
                mock.patch.object(diag, "_write_line", printed.append):
            self.assertEqual(diag.main(["--work", "."]), 0)
        self.assertEqual(printed, ["[Diagnostics] x"])
        printed[:] = []
        with mock.patch.object(diag, "report", side_effect=RuntimeError("x")), \
                mock.patch.object(diag, "_write_line", printed.append):
            self.assertEqual(diag.main([]), 0)
        self.assertEqual(printed, ["[Diagnostics] report: unavailable (RuntimeError)"])


if __name__ == "__main__":
    unittest.main()
