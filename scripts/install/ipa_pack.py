#!/usr/bin/env python3
"""Embeds the user's own game data in an iPhone/iPad app bundle and writes the IPA (ZIP64 where needed).

The data stay local: the project distributes no game data, and an IPA written here contains the data of the
user's own dump, so it is for their own use only. Pure standard library, so the tests run on every platform.
"""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

EMBED_DIR = "res/EmbeddedData"
MOD_FOLDERS = ("romfs", "exefs")
CHUNK = 1 << 20


def clear_embedded(app):
    """Removes data of an earlier export; an app folder is reused between builds."""
    shutil.rmtree(Path(app) / EMBED_DIR, ignore_errors=True)


def _checked_relative(value):
    path = Path(value)
    if not value or path.is_absolute() or PurePosixPath(value).is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Invalid embedded data path: " + str(value))
    return path


def _link_tree(source, destination):
    """APFS clone where possible (no extra space, one process), else hard links, else copies."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("Embedded data destination already exists: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        result = subprocess.run(["/bin/cp", "-cR", str(source), str(destination)],
                                capture_output=True, check=False)
        if result.returncode == 0:
            return "clone"
        shutil.rmtree(destination, ignore_errors=True)
    mode = "link"
    for parent, directories, files in os.walk(source):
        directories.sort()
        target = destination / Path(parent).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            origin = Path(parent) / name
            if origin.is_symlink():
                raise ValueError("Symbolic links in game data are not supported: " + str(origin))
            try:
                os.link(origin, target / name)
            except OSError:
                shutil.copy2(origin, target / name)
                mode = "copy"
    return mode


def embed_data(app, romfs, romfs_destination, mod=None, mod_destination=None):
    """Places the RomFS (and the romfs/exefs folders of a mod) below res/EmbeddedData of the app."""
    app, romfs = Path(app), Path(romfs).resolve(strict=True)
    if not (romfs / "Data").is_dir():
        raise ValueError("The RomFS has no Data folder; nothing was embedded.")
    clear_embedded(app)
    base = app / EMBED_DIR
    modes = [_link_tree(romfs, base / _checked_relative(romfs_destination))]
    if mod:
        mod = Path(mod).resolve(strict=True)
        target = base / _checked_relative(mod_destination)
        found = False
        for child in sorted(mod.iterdir()):
            if child.name.lower() in MOD_FOLDERS and child.is_dir() and not child.is_symlink():
                modes.append(_link_tree(child, target / child.name))
                found = True
        if not found:
            raise ValueError("The mod has no romfs or exefs folder; nothing was embedded.")
    return modes


def _entries(app):
    """Directories, links and files of the app in a stable order: (path, archive name, lstat)."""
    app = Path(app)
    root = "Payload/" + app.name
    items = [(app, root, os.lstat(app))]
    for parent, directories, files in os.walk(app):
        directories.sort()
        for name in directories + sorted(files):
            path = Path(parent) / name
            items.append((path, root + "/" + path.relative_to(app).as_posix(), os.lstat(path)))
    return items


def _date_time(status):
    value = time.localtime(max(status.st_mtime, 315532800))   # ZIP cannot hold dates before 1980
    return value[:6]


def pack_ipa(app, output, progress=None):
    """Writes Payload/<app> to a ZIP at output. Embedded data are stored, everything else deflated.

    progress(bytes_done, bytes_total, files_done, files_total) is called about once per MiB.
    Returns {"files", "bytes", "size", "zip64"}.
    """
    app, output = Path(app), Path(output)
    if not app.is_dir() or app.suffix != ".app":
        raise ValueError("The application folder is missing.")
    items = _entries(app)
    files = [item for item in items if not stat.S_ISDIR(item[2].st_mode)]   # files and links, as listed in the archive
    total = sum(item[2].st_size for item in files if stat.S_ISREG(item[2].st_mode))
    done_bytes = done_files = 0
    last_report = 0
    embedded_prefix = "Payload/" + app.name + "/" + EMBED_DIR + "/"
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        payload = zipfile.ZipInfo("Payload/", date_time=_date_time(items[0][2]))
        payload.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
        payload.create_system = 3
        archive.writestr(payload, b"")
        for path, name, status in items:
            info = zipfile.ZipInfo(name, date_time=_date_time(status))
            info.external_attr = (status.st_mode & 0xFFFF) << 16
            info.create_system = 3
            embedded = name.startswith(embedded_prefix)
            if stat.S_ISDIR(status.st_mode):
                info.filename = name + "/"
                info.external_attr |= 0x10
                archive.writestr(info, b"")
            elif stat.S_ISLNK(status.st_mode):
                archive.writestr(info, os.readlink(path))
                done_files += 1
            elif stat.S_ISREG(status.st_mode):
                info.file_size = status.st_size   # known up front, so ZIP64 is chosen per file
                info.compress_type = zipfile.ZIP_STORED if embedded else zipfile.ZIP_DEFLATED
                with open(path, "rb") as source, archive.open(info, "w") as target:
                    while True:
                        block = source.read(CHUNK)
                        if not block:
                            break
                        target.write(block)
                        done_bytes += len(block)
                        if progress and done_bytes - last_report >= CHUNK:
                            progress(done_bytes, total, done_files, len(files))
                            last_report = done_bytes
                done_files += 1
            else:
                raise ValueError("The app contains a file that cannot be packed: " + str(path))
    if progress:
        progress(done_bytes, total, done_files, len(files))
    return {"files": len(files), "bytes": total, "size": output.stat().st_size, "zip64": uses_zip64(output)}


def uses_zip64(path):
    """True when the archive ends with a ZIP64 end-of-central-directory locator."""
    with open(path, "rb") as file:
        file.seek(0, os.SEEK_END)
        length = file.tell()
        file.seek(max(0, length - 70000))
        return b"PK\x06\x07" in file.read()


def sha256_file(path, progress=None):
    digest = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(CHUNK), b""):
            digest.update(block)
            done += len(block)
            if progress and done % (64 * CHUNK) < CHUNK:
                progress(done, total)
    if progress:
        progress(total, total)
    return digest.hexdigest()


def check_archive(path, app_name, expected_files):
    """Cheap structure check (central directory only; the contents were just written from checked files)."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        regular = [item for item in archive.infolist() if not item.is_dir()]
    if "Payload/" + app_name + "/Info.plist" not in names or len(regular) != expected_files:
        raise ValueError("The written IPA does not list the expected files.")


def space_message(needed, free):
    """The refusal for too little space. There is deliberately no automatic switch to an export without game data."""
    return ("Not enough free space for the IPA with your game data: about %.1f GB are needed in the export folder, %.1f GB are free. "
            "Nothing was exported. Free at least %.1f GB and run the export again, or export without game data on purpose: "
            "--ios-export-no-embed on the command line, or \"Export without game data\" in the installer."
            % (needed / 1e9, free / 1e9, max(0.0, needed - free) / 1e9 + 0.5))


def free_bytes_needed(app):
    """Upper bound of the IPA size: the stored size of every file (embedded data compress poorly)."""
    return sum(item[2].st_size for item in _entries(app) if stat.S_ISREG(item[2].st_mode))


def publish_ipa(app, destination, bundle_id, progress=None, log=None, hash_progress=None):
    """Writes the IPA once into destination and names it after the hash of its bytes.

    Returns (path, stats). An existing file of that name is the same content; a different file is never replaced.
    """
    app, destination = Path(app), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    needed = free_bytes_needed(app)
    free = shutil.disk_usage(destination).free
    if free < needed + (512 << 20):
        raise ValueError(space_message(needed + (512 << 20), free))
    say = log or (lambda message: None)
    temporary = destination / (".ipa-" + uuid.uuid4().hex)
    try:
        say("Writing the IPA: zipping the app and the embedded game data (step 1 of 3).")
        stats = pack_ipa(app, temporary, progress)
        say("Checking the structure of the written IPA (step 2 of 3).")
        check_archive(temporary, app.name, stats["files"])
        say("Hashing the IPA once to name it after its content (step 3 of 3).")
        digest = sha256_file(temporary, hash_progress)
        final = destination / (bundle_id + "-" + digest[:20] + ".ipa")
        if final.exists():
            if sha256_file(final) != digest:
                raise ValueError("An existing IPA differs; it was not overwritten.")
            temporary.unlink()
        else:
            with open(temporary, "r+b") as file:   # Windows only syncs a file that is open for writing
                os.fsync(file.fileno())
            os.rename(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return final, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    embed = sub.add_parser("embed", help="place game data below res/EmbeddedData of an app folder")
    embed.add_argument("--app", required=True)
    embed.add_argument("--romfs", required=True)
    embed.add_argument("--romfs-dest", required=True)
    embed.add_argument("--mod")
    embed.add_argument("--mod-dest")
    clear = sub.add_parser("clear", help="remove embedded data of an earlier build")
    clear.add_argument("--app", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "clear":
            clear_embedded(args.app)
        else:
            modes = embed_data(args.app, args.romfs, args.romfs_dest, args.mod, args.mod_dest)
            print("Embedded game data (%s)." % ", ".join(modes))
    except (OSError, ValueError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
