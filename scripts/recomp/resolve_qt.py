#!/usr/bin/env python3
"""Downloads the newest Qt 6 that Qt publishes for LLVM-MinGW (UCRT, libc++) and the LLVM-MinGW toolchain Qt pairs with it.

Reads Qt's own online repository (download.qt.io) directly, so nothing is pinned in the repository; every archive is
checked against the .sha1 file Qt publishes next to it. Also fetches the matching qtbase sources for the licence texts.
Writes <out>/qt.json with the file names and the Qt version.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/"
SOURCES = "https://download.qt.io/official_releases/qt/%s/%s/submodules/qtbase-everywhere-src-%s.tar.xz"


def text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "strahlender-xnu-ci"}), timeout=120) as response:
        return response.read().decode("utf-8")


def package(updates, name):
    """(version, archives) of one package in a repository's Updates.xml."""
    for item in ET.fromstring(updates).iter("PackageUpdate"):
        if item.findtext("Name") == name:
            return item.findtext("Version"), [a.strip() for a in (item.findtext("DownloadableArchives") or "").split(",") if a.strip()]
    raise ValueError("Package not found: " + name)


def resolve(get=text):
    listing = get(BASE)
    toolchain = None
    for number in sorted({int(n) for n in re.findall(r'href="qt6_(\d+)/"', listing)}, reverse=True):
        try:
            version, archives = package(get("%sqt6_%d/qt6_%d_llvm_mingw/Updates.xml" % (BASE, number, number)),
                                        "qt.qt6.%d.win64_llvm_mingw" % number)
        except (OSError, ValueError, ET.ParseError):
            continue  # releases without an LLVM-MinGW kit are skipped
        qtbase = next((a for a in archives if a.startswith("qtbase-")), None)
        if qtbase:
            qt = {"qt": version.split("-")[0], "url": "%sqt6_%d/qt6_%d_llvm_mingw/qt.qt6.%d.win64_llvm_mingw/%s%s" % (BASE, number, number, number, version, qtbase)}
            break
    else:
        raise ValueError("No Qt 6 release offers the LLVM-MinGW kit")
    for number in sorted({int(n) for n in re.findall(r'href="tools_llvm_mingw(\d+)/"', listing)}, reverse=True):
        tool_version, tool_archives = package(get("%stools_llvm_mingw%d/Updates.xml" % (BASE, number)), "qt.tools.win64_llvm_mingw%d" % number)
        toolchain = "%stools_llvm_mingw%d/qt.tools.win64_llvm_mingw%d/%s%s" % (BASE, number, number, tool_version, tool_archives[0])
        break
    if not toolchain:
        raise ValueError("No LLVM-MinGW tool in the Qt repository")
    minor = ".".join(qt["qt"].split(".")[:2])
    return {"qt": qt["qt"], "qtbase": qt["url"], "toolchain": toolchain, "toolchain_version": tool_version.split("-")[0], "source": SOURCES % (minor, qt["qt"], qt["qt"])}


def download(url, destination, expected_sha1=None):
    digest = hashlib.sha1()
    with urllib.request.urlopen(url, timeout=600) as response, open(destination, "wb") as output:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
            output.write(chunk)
    if expected_sha1 and digest.hexdigest() != expected_sha1:
        Path(destination).unlink(missing_ok=True)
        raise ValueError("SHA-1 mismatch: " + url)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        found = resolve()
        files = {}
        for role, extension in (("qtbase", "7z"), ("toolchain", "7z"), ("source", "tar.xz")):
            target = args.out / ("%s.%s" % (role, extension))
            sha1 = text(found[role] + ".sha1").split()[0] if role != "source" else None
            download(found[role], target, sha1)
            files[role] = target.name
    except (OSError, ValueError, ET.ParseError) as error:
        print("Resolving Qt failed: " + str(error), file=sys.stderr)
        return 4
    (args.out / "qt.json").write_text(json.dumps({"qt": found["qt"], "toolchain_version": found["toolchain_version"], "files": files}) + "\n", encoding="utf-8")
    print(json.dumps({"qt": found["qt"], **files}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
