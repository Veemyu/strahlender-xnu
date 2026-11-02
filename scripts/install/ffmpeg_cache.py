#!/usr/bin/env python3
"""Where the iPhoneOS FFmpeg static libraries live and when they may be reused.

The installer keeps them in its data directory (BDSP_IOS_FFMPEG_DIR) so a new build workspace does not build FFmpeg again;
a development checkout uses work/ios/ffmpeg-ios. A folder counts as complete only with a stamp that matches the current
FFmpeg source checksum, SDK, compiler and build script, and the stamp is written last.

Usage: ffmpeg_cache.py dir
       ffmpeg_cache.py stamp SHA256 SDK_PATH SDK_VERSION COMPILER_ID SCRIPT
       ffmpeg_cache.py current DIR STAMP      (exit 0 when DIR is complete and built for STAMP)
"""
import hashlib
import os
import sys
from pathlib import Path

ENV = "BDSP_IOS_FFMPEG_DIR"
STAMP_FILE = ".bdsp-stamp"
LIBRARIES = ("libavformat.a", "libavcodec.a", "libavutil.a")


def ffmpeg_dir(root=None, environ=None):
    environ = os.environ if environ is None else environ
    configured = environ.get(ENV)
    if configured:
        return Path(configured).expanduser().absolute()
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    return root / "work/ios/ffmpeg-ios"


def stamp(source_sha256, sdk_path, sdk_version, compiler_id, script_file):
    digest = hashlib.sha256()
    for part in (source_sha256, sdk_path, sdk_version, compiler_id, hashlib.sha256(Path(script_file).read_bytes()).hexdigest()):
        digest.update(part.encode() + b"\n")
    return digest.hexdigest()


def is_current(folder, expected):
    folder = Path(folder)
    try:
        if (folder / STAMP_FILE).read_text().strip() != expected:
            return False
    except OSError:
        return False
    return all((folder / "lib" / name).is_file() for name in LIBRARIES) and (folder / "include").is_dir()


def main(argv):
    if argv[:1] == ["dir"] and len(argv) == 1:
        print(ffmpeg_dir())
    elif argv[:1] == ["stamp"] and len(argv) == 6:
        print(stamp(*argv[1:]))
    elif argv[:1] == ["current"] and len(argv) == 3:
        return 0 if is_current(argv[1], argv[2]) else 1
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
