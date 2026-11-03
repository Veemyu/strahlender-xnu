"""Windows MAX_PATH planning for the native build. Standard library only.

Windows refuses any path of 260 characters or more (the limit counts the terminating NUL) to a program that is not long path
aware, and the native generator is not (no longPathAware manifest, no wide-character paths): it reports the failure as "cannot
create output file (No such file or directory)" in the middle of a build, also when Windows long paths are enabled. The pipeline
knows the shape of every path it creates below the work folder, so the longest one can be computed before any work starts:
the work folder is one fixed prefix, the generated names add a known tail.

The tails are planned worst cases (module names, five hex digits of window, four digits of chunk number, six digits of
process id for temporary files, eight random characters in temporary folders), not measurements of a finished build.
"""
import os
import sys

LIMIT = 260
MODULES = ("rtld", "main", "sdk", "subsdk0", "subsdk1")
RANDOM = "x" * 8
PID = "123456"
# Fixed folder names shared by the pipeline and the planner. The package folder sits directly below work, the game data
# is by far the deepest content (107 characters relative to romfs in the retail game) and every level above it counts.
PACKAGES = "pkg"
STAGE_PREFIX = "."          # package_game builds below pkg/.<8 random>/ and renames it
HOLDER_PREFIX = "t-"        # small helper files (qt.conf, mod.txt) live in pkg/t-<8 random>/
INSTALL_PREFIX = "i-"       # install_package stages below <install parent>/i-<8 random>/app
GENERATE_PREFIX = "g-"
COMPILE_PREFIX = "c-"
# Longest object name of the runtime sources (checked against the repository by the tests) and of the Vulkan overlay.
RUNTIME_OBJECT = "runtime_services_applet.o"
RUNTIME_DIR = "rt"
OVERLAY_FILE = RUNTIME_DIR + "/nvn-src-vk/nvn/maxwell/translate.c"
# ui_aspect_patch writes its overlay below romfs-patch with the same relative names, only for these folders of the game data.
PATCH_ROOTS = ("Data/StreamingAssets/AssetAssistant/UIs", "Data/StreamingAssets/AssetAssistant/FureaiHiroba/demo",
               "Data/StreamingAssets/AssetAssistant/Dpr/scenes/title")
# Before the first extraction the game data is unknown: plan the deepest RomFS file of the game (108 characters) so the check
# stops at the start with the same verdict as after the extraction (before: OK at the start, then 270 of 260 at the ExeFS step, #49).
ASSUMED_ROMFS = ("x" * 108,)
MOD_CODE_KEY = "x" * 20     # recomp/mods/<20 hex>/ holds the build of a mod with ExeFS code


def package_folder(mod=None):
    """Folder of the finished package below work/pkg: short, because the game data below it is deep."""
    return "m-" + mod["identity"][:8] if mod else "BDSP"


def installed_folder(mod=None):
    """Folder name of the installed app (a mod app keeps its readable name; it lives outside the work folder)."""
    return "BDSP-" + mod["slug"] + "-" + mod["identity"] if mod else "BDSP"


def _patched(relative):
    return relative.startswith(PATCH_ROOTS)


def _game_data(prefix, romfs, label):
    found = []
    for relative in romfs:
        found.append((label, prefix + "romfs/" + relative))
        if _patched(relative):
            found.append((label + " (UI overlay)", prefix + "romfs-patch/" + relative))
    return found


def _clean(romfs):
    return [relative.replace("\\", "/").strip("/") for relative in romfs]


def planned_paths(cache_key, modules=MODULES, romfs=(), mod=None, package=()):
    """(label, path) pairs of the longest paths below the work folder, with / as separator and no leading separator.

    `romfs` are paths below work/romfs (the game's data, only known after the extraction), `package` other paths
    below the package root (notices of the bundles). `mod` is the selected mod (a code mod builds in a deeper folder)."""
    module = max(modules, key=len)
    chunk = module + "_00000_0000"
    romfs = _clean(romfs)
    builds = ["recomp/" + cache_key]
    if mod:
        builds += ["recomp/mods/" + MOD_CODE_KEY + "/" + cache_key, "recomp/mod-apps/" + mod["identity"] + "/" + cache_key]
    paths = []
    for build in builds:
        paths += [
            ("generated source", build + "/" + GENERATE_PREFIX + RANDOM + "/" + module + "/" + chunk + ".c." + PID + ".tmp"),
            ("object file", build + "/objects/" + COMPILE_PREFIX + RANDOM + "/" + module + "_" + chunk + ".o"),
            ("object receipt", build + "/objects/" + module + "_" + chunk + ".o.json" + RANDOM + ".tmp"),
            ("runtime object", build + "/" + RUNTIME_DIR + "/" + COMPILE_PREFIX + RANDOM + "/" + RUNTIME_OBJECT + ".json" + RANDOM + ".tmp"),
            ("Vulkan sources", build + "/" + OVERLAY_FILE),
            ("application icons", build + "/icons/windows/" + "x" * 24),
        ]
    stage = PACKAGES + "/" + STAGE_PREFIX + RANDOM + "/"
    final = PACKAGES + "/" + package_folder(mod) + "/"
    paths += [("extracted game data", ".stage/romfs/" + relative) for relative in romfs]
    paths += _game_data("", romfs, "game data")
    for prefix in (stage, final):
        paths += _game_data(prefix, romfs, "packaged game data")
        paths += [("packaged file", prefix + relative.replace("\\", "/").strip("/")) for relative in package]
    return paths


def installed_paths(romfs=(), package=()):
    """Paths below the install folder of the app (the finished app runs from there), with / and no leading separator."""
    romfs = _clean(romfs)
    return _game_data("", romfs, "installed game data") + [("installed file", relative) for relative in package]


def longest_relative(cache_key, modules=MODULES, romfs=(), mod=None, package=()):
    """(length, label) of the longest planned path below the work folder, counting the separator in front of it."""
    label, path = max(planned_paths(cache_key, modules, romfs, mod, package), key=lambda item: len(item[1]))
    return len(path) + 1, label


def romfs_relative(work):
    """Paths below work/romfs of an earlier extraction (empty before the first one)."""
    top = os.path.join(str(work), "romfs")
    found = []
    for folder, _directories, names in os.walk(top):
        prefix = os.path.relpath(folder, top)
        found.extend(name if prefix == "." else prefix.replace(os.sep, "/") + "/" + name for name in names)
    return found


def long_paths_enabled():
    """True or False from HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem; None where it cannot be read."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except (OSError, ImportError):
        return None


class PathCheck(object):
    def __init__(self, root, longest, label, long_paths, installed=0, installed_label=""):
        self.root, self.longest, self.label, self.long_paths = root, longest, label, long_paths
        self.total = root + longest
        self.installed, self.installed_label = installed, installed_label

    @property
    def too_long(self):
        return self.total >= LIMIT

    @property
    def installed_too_long(self):
        return self.installed >= LIMIT

    @property
    def risk(self):
        """Too long: the generator would stop in the middle, whatever the Windows long path setting says."""
        return self.too_long or self.installed_too_long

    def line(self):
        state = {True: "yes", False: "no"}.get(self.long_paths, "unknown")
        installed = ", installed app %d chars" % self.installed if self.installed else ""
        return ("Path length check: root %d chars, longest generated path %d chars (%s), limit %d%s, LongPathsEnabled=%s, "
                "result %s" % (self.root, self.longest, self.label, LIMIT, installed, state, "RISK" if self.risk else "OK"))

    def failure(self):
        if self.installed_too_long and not self.too_long:
            return ("The folder for the installed app is too deep for Windows (%d of %d characters, %s). Windows programs that "
                    "are not long path aware could not open it." % (self.installed, LIMIT, self.installed_label))
        return ("The install folder is too deep for Windows (%d of %d characters). The build tools cannot create paths this long, "
                "even when Windows long paths are enabled. Set the environment variable BDSP_INSTALLER_DATA_DIR to a short folder such as C:\\bdsp and start the installer again." % (self.total, LIMIT))


def check(work, cache_key, modules=MODULES, romfs=(), long_paths=None, mod=None, package=(), install=None):
    """The path check of a work folder; `long_paths` is True, False or None (unknown).

    `install` is the folder the app will be installed to (its parent holds the temporary staging folder)."""
    romfs = romfs or ASSUMED_ROMFS
    length, label = longest_relative(cache_key, modules, romfs, mod, package)
    installed, installed_label = 0, ""
    if install is not None:
        install = str(install).rstrip("\\/")
        parent = len(install.replace("\\", "/").rsplit("/", 1)[0])
        staged = parent + 1 + len(INSTALL_PREFIX) + len(RANDOM) + len("/app")
        for found_label, path in installed_paths(romfs, package):
            for base in (len(install), staged):
                if base + 1 + len(path) > installed:
                    installed, installed_label = base + 1 + len(path), found_label
    return PathCheck(len(str(work)), length, label, long_paths, installed, installed_label)
