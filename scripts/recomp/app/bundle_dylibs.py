#!/usr/bin/env python3
"""Bundles the third-party libraries (SDL3, FFmpeg with all dependencies) of a Mach-O file into <App>/Contents/Frameworks.

Copies every library that is not part of the system (/usr/lib, /System) to <frameworks>, sets its ID to @rpath/<name>,
repoints all references to it and adds @executable_path/../Frameworks as an rpath of the main binary. The signatures of the
modified files become invalid; the caller re-signs afterwards (make_app.sh). Standard library only.
Usage: bundle_dylibs.py <main-binary> <frameworks-folder>
"""
import os
import shutil
import subprocess
import sys

SYSTEM = ("/usr/lib/", "/System/")


def deps(path):
    out = subprocess.run(["otool", "-L", path], capture_output=True, text=True, check=True).stdout.splitlines()[1:]
    return [line.split()[0] for line in out if line.strip()]


def is_foreign(dep):
    return not dep.startswith(SYSTEM) and not dep.startswith("@")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    main_bin, fw = sys.argv[1], sys.argv[2]
    os.makedirs(fw, exist_ok=True)
    done = {}   # name -> path in fw
    queue = [main_bin]
    while queue:
        cur = queue.pop()
        for dep in deps(cur):
            if not is_foreign(dep):
                continue
            real = os.path.realpath(dep)
            name = os.path.basename(dep)
            if name not in done:
                dst = os.path.join(fw, name)
                shutil.copyfile(real, dst)
                os.chmod(dst, 0o755)
                subprocess.run(["install_name_tool", "-id", "@rpath/" + name, dst], check=True, capture_output=True)
                done[name] = dst
                queue.append(dst)
            if os.path.basename(cur) != name:   # its own entry (ID) is already rewritten
                subprocess.run(["install_name_tool", "-change", dep, "@rpath/" + name, cur], check=True, capture_output=True)
    rp = subprocess.run(["otool", "-l", main_bin], capture_output=True, text=True, check=True).stdout
    if "@executable_path/../Frameworks" not in rp:
        subprocess.run(["install_name_tool", "-add_rpath", "@executable_path/../Frameworks", main_bin], check=True, capture_output=True)
    left = [d for f in [main_bin] + list(done.values()) for d in deps(f) if is_foreign(d)]
    if left:
        print("ERROR: references not repointed: %s" % sorted(set(left)))
        return 1
    total = sum(os.path.getsize(p) for p in done.values())
    print("bundled: %d libraries, %.1f MB" % (len(done), total / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
