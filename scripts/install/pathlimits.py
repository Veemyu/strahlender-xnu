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


def planned_paths(cache_key, modules=MODULES, romfs=()):
    """(label, path) pairs of the longest paths below the work folder, with / as separator and no leading separator.

    `romfs` are paths below work/romfs (the game's data, only known after the extraction)."""
    module = max(modules, key=len)
    chunk = module + "_00000_0000"
    build = "recomp/" + cache_key
    paths = [
        ("generated source", build + "/generate-" + RANDOM + "/" + module + "/" + chunk + ".c." + PID + ".tmp"),
        ("object file", build + "/objects/" + cache_key + "/compile-" + RANDOM + "/" + module + "_" + chunk + ".o"),
        ("object receipt", build + "/objects/" + cache_key + "/" + module + "_" + chunk + ".o.json" + RANDOM + ".tmp"),
    ]
    for relative in romfs:
        relative = relative.replace("\\", "/").strip("/")
        paths += [
            ("extracted game data", ".stage/romfs/" + relative),
            ("packaged game data", "builds/windows-amd64/windows-package-" + RANDOM + "/BDSP/romfs/" + relative),
        ]
    return paths


def longest_relative(cache_key, modules=MODULES, romfs=()):
    """(length, label) of the longest planned path below the work folder, counting the separator in front of it."""
    label, path = max(planned_paths(cache_key, modules, romfs), key=lambda item: len(item[1]))
    return len(path) + 1, label


def romfs_relative(work):
    """Paths below work/romfs of an earlier extraction (empty before the first one)."""
    top = os.path.join(str(work), "romfs")
    found = []
    for folder, _directories, names in os.walk(top):
        prefix = os.path.relpath(folder, top)
        found.extend(name if prefix == "." else prefix + "/" + name for name in names)
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
    def __init__(self, root, longest, label, long_paths):
        self.root, self.longest, self.label, self.long_paths = root, longest, label, long_paths
        self.total = root + longest

    @property
    def too_long(self):
        return self.total >= LIMIT

    @property
    def risk(self):
        """Too long: the generator would stop in the middle, whatever the Windows long path setting says."""
        return self.too_long

    def line(self):
        state = {True: "yes", False: "no"}.get(self.long_paths, "unknown")
        return ("Path length check: root %d chars, longest generated path %d chars, limit %d, LongPathsEnabled=%s, "
                "result %s" % (self.root, self.longest, LIMIT, state, "RISK" if self.risk else "OK"))

    def failure(self):
        return ("The install folder is too deep for Windows (%d of %d characters). The build tools cannot create paths this long, "
                "even when Windows long paths are enabled. Choose a shorter folder, for example C:\\bdsp." % (self.total, LIMIT))


def check(work, cache_key, modules=MODULES, romfs=(), long_paths=None):
    """The path check of a work folder; `long_paths` is True, False or None (unknown)."""
    length, label = longest_relative(cache_key, modules, romfs)
    return PathCheck(len(str(work)), length, label, long_paths)
