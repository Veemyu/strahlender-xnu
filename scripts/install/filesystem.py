"""Shared installation file operations; never follow links into user data."""
import hashlib
import os
from pathlib import Path
import shutil
import stat
import re
import tempfile


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_link(path):
    info = Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("A symbolic link or reparse point in installation data needs manual review.")


def reject_existing_link(path):
    try:
        reject_link(path)
    except FileNotFoundError:
        pass


def walk_error(error):
    raise error


def copy_notices(source, destination):
    """Keep upstream license-directory contents as well as named notice files."""
    source, destination = Path(source), Path(destination)
    reject_link(source)
    if not source.is_dir():
        raise FileNotFoundError("Notice sources are missing: " + str(source))
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("The notice destination must remain outside its source tree.")
    for parent, directories, files in os.walk(source, onerror=walk_error):
        for name in directories:
            reject_link(Path(parent) / name)
        for name in files:
            path = Path(parent) / name
            reject_link(path)
            relative = path.relative_to(source)
            if (any(part.lower() in ("license", "licenses", "licences", "copying", "notices")
                    for part in relative.parts[:-1]) or
                    any(word in name.lower() for word in ("license", "copying", "notice")) or
                    name.lower().split(".")[0] in ("authors", "copyright")):
                output = destination / relative
                for ancestor in (output, *output.parents):
                    if ancestor == destination.parent:
                        break
                    reject_existing_link(ancestor)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, output)


def copy_tree(source, destination, progress=None):
    source, destination = Path(source), Path(destination)
    reject_link(source)
    if not source.is_dir():
        raise FileNotFoundError("Build data is missing: " + str(source))
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("The copy destination must remain outside its source tree.")
    reject_existing_link(destination)
    for parent, directories, files in os.walk(source, onerror=walk_error):
        directories.sort()
        for name in directories:
            reject_link(Path(parent) / name)
        target = destination / Path(parent).relative_to(source)
        reject_existing_link(target)
        target.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            origin = Path(parent) / name
            reject_link(origin)
            reject_existing_link(target / name)
            shutil.copy2(origin, target / name)
            if progress:
                progress()


def verify_inventory(source, files, ignored=()):
    """Reject changed, extra or linked files before replacing an owned package."""
    source = Path(source)
    reject_link(source)
    if not isinstance(files, dict) or not files:
        raise ValueError("The package file inventory is empty or invalid")
    for name, digest in files.items():
        if (not isinstance(name, str) or "\\" in name or ":" in name or
                any(part in ("", ".", "..") for part in name.split("/")) or
                not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("Invalid package file inventory")
    actual = set()
    for parent, directories, names in os.walk(source, onerror=walk_error):
        for name in directories:
            reject_link(Path(parent) / name)
        for name in names:
            path = Path(parent) / name
            reject_link(path)
            relative = path.relative_to(source).as_posix()
            if relative in ignored:
                continue
            if relative not in files or sha256(path) != files[relative]:
                raise ValueError("A packaged file was added or changed: " + relative)
            actual.add(relative)
    if actual != set(files):
        raise ValueError("A packaged file is missing")


def publish_tree(candidate, destination):
    """Same-volume replacement, preserving the backup if rollback itself fails."""
    candidate, destination = Path(candidate), Path(destination)
    reject_link(candidate)
    reject_existing_link(destination)
    if (candidate.resolve().is_relative_to(destination.resolve()) or
            destination.resolve().is_relative_to(candidate.resolve())):
        raise ValueError("Replacement trees must be separate, non-nested directories.")
    backup_root = Path(tempfile.mkdtemp(prefix=".app-backup-", dir=destination.parent))
    backup = backup_root / "app"
    moved = False
    try:
        if destination.exists():
            destination.rename(backup)
            moved = True
        candidate.rename(destination)
    except BaseException:
        if moved:
            try:
                backup.rename(destination)
            except OSError:
                raise OSError("Installation rollback failed; prior files remain in " + str(backup)) from None
        backup_root.rmdir()
        raise
    shutil.rmtree(backup_root)
    return destination
