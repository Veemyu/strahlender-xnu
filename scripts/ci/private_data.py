#!/usr/bin/env python3
"""Fetches, verifies and decrypts the private CI game data on a runner, and wipes it again. Standard library plus `cryptography`.

The inputs are served as five encrypted blobs (see the private data repository's docs). Secrets arrive only through the
environment: CI_DATA_URL, CI_DATA_EDGE_KEY, CI_DATA_BEARER, CI_DATA_KEY, CI_DATA_MANIFEST. Nothing here prints a URL, a blob
name, a hash, a header or any decrypted byte; the only output is the role of a blob and pass or fail.

  mask           print ::add-mask:: commands for every secret and every part of it (run first, in the same step env)
  fetch DIR      download, verify, decrypt into DIR (game.xci, update.nsp, firmware.zip, mod.zip, prod.keys)
  mod DIR MODS   unpack DIR/mod.zip into MODS/ci-mod (a single top folder is flattened) and delete the zip
  wipe PATH...   remove folders (always safe to repeat)
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROLES = ("game.xci", "update.nsp", "firmware.zip", "mod.zip", "prod.keys")
MAGIC = {"game.xci": (256, b"HEAD"), "update.nsp": (0, b"PFS0"), "firmware.zip": (0, b"PK"), "mod.zip": (0, b"PK")}
SECRETS = ("CI_DATA_URL", "CI_DATA_EDGE_KEY", "CI_DATA_BEARER", "CI_DATA_KEY", "CI_DATA_MANIFEST")
MOD_NAME = "ci-mod"
SALTED = b"Salted__"
ITERATIONS = 600000
CHUNK = 8 << 20


class DataError(Exception):
    """Carries a message that is safe to print."""


def mask_lines(environ):
    """Workflow commands that hide every secret and every part of it (manifest lines, hashes, names, host) in later output."""
    parts = []
    for name in SECRETS:
        value = environ.get(name, "")
        for part in [value] + value.splitlines() + value.split():
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
    host = environ.get("CI_DATA_URL", "").split("://")[-1].split("/")[0]
    if host and host not in parts:
        parts.append(host)
    return ["::add-mask::" + part.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A") for part in parts]


def parse_manifest(text):
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        digest = fields[0].lower() if fields else ""
        if len(fields) != 2 or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise DataError("The manifest has an invalid line.")
        name = fields[1].lstrip("*")
        if "/" in name or "\\" in name or name in (".", ".."):
            raise DataError("The manifest has an invalid blob name.")
        entries.append((digest, name))
    if len(entries) != len(ROLES):
        raise DataError("The manifest must have %d lines, it has %d." % (len(ROLES), len(entries)))
    return entries


def curl_config(url, headers, output):
    """curl reads this from stdin, so no secret is ever on a command line (visible in process lists)."""
    def quote(value):
        if any(c in value for c in "\r\n\0"):
            raise DataError("A secret contains a line break.")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = ["url = " + quote(url), "output = " + quote(str(output))]
    lines += ["header = " + quote(name + ": " + value) for name, value in headers]
    return "\n".join(lines) + "\n"


def download(url, headers, target, run=subprocess.run):
    # No redirect following: a redirect must never carry the credentials to another host. No -v, so no headers are printed.
    command = ["curl", "--fail", "--silent", "--show-error", "--retry", "3", "--retry-delay", "5",
               "--connect-timeout", "30", "--max-time", "5400", "-C", "-", "--config", "-"]
    result = run(command, input=curl_config(url, headers, target), text=True, capture_output=True, check=False)
    if result.returncode:
        raise DataError("Download failed (curl exit %d)." % result.returncode)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def decrypt(source, target, key):
    """Same as `openssl enc -d -aes-256-ctr -pbkdf2 -iter 600000` (SHA-256 PBKDF2, 32 byte key then 16 byte counter block)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    with open(source, "rb") as handle:
        header = handle.read(16)
        if len(header) != 16 or header[:8] != SALTED:
            raise DataError("A blob has no salt header.")
        derived = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), header[8:], ITERATIONS, 48)
        cipher = Cipher(algorithms.AES(derived[:32]), modes.CTR(derived[32:])).decryptor()
        with open(target, "wb") as out:
            while chunk := handle.read(CHUNK):
                out.write(cipher.update(chunk))
            out.write(cipher.finalize())


def check_magic(role, path):
    """A wrong key does not fail in openssl, it writes noise; this is the only check after decrypting."""
    with open(path, "rb") as handle:
        if role == "prod.keys":
            head = handle.read(4096)
            return bool(head) and all(b in (9, 10, 13) or 32 <= b < 127 for b in head)
        offset, expected = MAGIC[role]
        handle.seek(offset)
        return handle.read(len(expected)) == expected


def restrict(path):
    if os.name != "nt":
        os.chmod(path, stat.S_IRWXU if Path(path).is_dir() else stat.S_IRUSR | stat.S_IWUSR)


def fetch(directory, environ=os.environ, run=subprocess.run):
    missing = [name for name in SECRETS if not environ.get(name)]
    if missing:
        raise DataError("Missing secrets: " + ", ".join(missing))
    base = environ["CI_DATA_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise DataError("CI_DATA_URL must start with https://")
    entries = parse_manifest(environ["CI_DATA_MANIFEST"])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    restrict(directory)
    headers = [("X-CI-Edge", environ["CI_DATA_EDGE_KEY"]), ("Authorization", "Bearer " + environ["CI_DATA_BEARER"])]
    for role, (digest, name) in zip(ROLES, entries):
        blob = directory / (role + ".bin")
        plain = directory / role
        try:
            download(base + "/" + name, headers, blob, run)
            if sha256_file(blob) != digest:
                raise DataError("Hash mismatch for " + role + "; nothing was decrypted.")
            decrypt(blob, plain, environ["CI_DATA_KEY"])
        finally:
            blob.unlink(missing_ok=True)
        restrict(plain)
        if not check_magic(role, plain):
            plain.unlink(missing_ok=True)
            raise DataError("Sanity check failed for " + role + " (wrong key or wrong blob).")
        print("ok " + role, flush=True)


def prepare_mod(directory, mods):
    archive = Path(directory) / "mod.zip"
    root = (Path(mods) / MOD_NAME).resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            destination = (root / info.filename).resolve()
            if destination != root and root not in destination.parents:
                raise DataError("The mod archive contains an unsafe path.")
        zipped.extractall(root)
    archive.unlink()
    entries = [path for path in root.iterdir() if path.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir() and entries[0].name.lower() not in ("romfs", "exefs"):
        inner = entries[0]
        for item in list(inner.iterdir()):
            shutil.move(str(item), str(root / item.name))
        inner.rmdir()
    print("ok mod", flush=True)


def _writable(function, path, _error):
    for target in (os.path.dirname(path), path):
        if os.path.lexists(target) and not os.path.islink(target):
            os.chmod(target, stat.S_IRWXU)
    function(path)


def _remove_tree(path):
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable)
    else:
        shutil.rmtree(path, onerror=_writable)


def wipe(paths):
    for path in paths:
        if path and os.path.lexists(path):
            if os.path.isdir(path) and not os.path.islink(path):
                _remove_tree(path)
            else:
                os.unlink(path)


def main(argv):
    try:
        if len(argv) == 3 and argv[1] == "fetch":
            fetch(argv[2])
        elif len(argv) == 4 and argv[1] == "mod":
            prepare_mod(argv[2], argv[3])
        elif len(argv) >= 3 and argv[1] == "wipe":
            wipe(argv[2:])
        elif len(argv) == 2 and argv[1] == "mask":
            print("\n".join(mask_lines(os.environ)))
        else:
            print(__doc__)
            return 2
    except DataError as error:
        print("error: " + str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
