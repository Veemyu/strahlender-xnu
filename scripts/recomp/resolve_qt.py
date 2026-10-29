#!/usr/bin/env python3
"""Picks the newest Qt 6 that Qt publishes for LLVM-MinGW (UCRT, libc++) and the toolchain Qt pairs with it.

Uses aqtinstall's listing commands, so nothing is pinned in the repository. Prints one JSON object:
{"qt": "6.12.0", "arch": "win64_llvm_mingw", "tool": "tools_llvm_mingw2217", "variant": "qt.tools.win64_llvm_mingw2217"}
"""
import json
import re
import subprocess
import sys

ARCH = "win64_llvm_mingw"


def version_key(text):
    return tuple(int(part) for part in re.findall(r"\d+", text))


def pick(qt_listing, arch_listing_for, tool_listing):
    """qt_listing/tool_listing: aqt output; arch_listing_for(version): aqt output for that Qt version."""
    versions = sorted((v for v in re.findall(r"\b6\.\d+\.\d+\b", qt_listing)), key=version_key, reverse=True)
    for version in versions:
        if ARCH in arch_listing_for(version).split():
            tools = sorted(set(re.findall(r"\btools_llvm_mingw\d+\b", tool_listing)), key=version_key)
            if not tools:
                raise ValueError("aqt lists no LLVM-MinGW tool")
            tool = tools[-1]
            return {"qt": version, "arch": ARCH, "tool": tool, "variant": "qt.tools.win64_" + tool.removeprefix("tools_")}
    raise ValueError("No Qt 6 release offers " + ARCH)


def aqt(*arguments):
    return subprocess.run([sys.executable, "-m", "aqt", *arguments], check=True, capture_output=True, text=True).stdout


def main():
    result = pick(aqt("list-qt", "windows", "desktop"),
                  lambda version: aqt("list-qt", "windows", "desktop", "--arch", version),
                  aqt("list-tool", "windows", "desktop"))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
