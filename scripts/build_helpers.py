#!/usr/bin/env python3
"""Helper logic for scripts/build_all.sh (pure functions, standard library only).

Never prints key material into logs. The titlekey goes only to stdout of the
`titlekey` subcommand and is kept by the caller in a shell variable.

Subcommands (usage: build_helpers.py <command> ...):
  nca-info --path P          reads `hactool -i` from stdin, prints a TSV line with the safe fields
  pick --tsv F --type T [--title-id X]   picks the largest matching NCA, prints the path
  titlekey --rights-id R --tik-dir D [--title-keys F]   prints the titlekey (hex)
  cnmt-version DIR           title version from the .cnmt under DIR (decimal)
  nacp-version DIR           display version from control.nacp under DIR
  write-manifest ...         writes <work>/manifest.json
  check-manifest ...         exit 0 if manifest.json matches the work folder
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import time

# Exit codes (must match build_all.sh)
EX_KEYS = 6
EX_NOTFOUND = 7

# Ticket signature types: type -> (signature length, padding)
TIK_SIG_SIZES = {
    0x010000: (0x200, 0x3C), 0x010001: (0x100, 0x3C), 0x010002: (0x3C, 0x40),
    0x010003: (0x200, 0x3C), 0x010004: (0x100, 0x3C), 0x010005: (0x3C, 0x40),
}
ZERO_RIGHTS = "0" * 32
MANIFEST_SCHEMA = 1


class TikError(Exception):
    pass


def parse_tik(data):
    """Reads a ticket and returns rights ID, titlekey type and (for common tickets) the titlekey."""
    if len(data) < 4:
        raise TikError("ticket too short")
    sig_type = struct.unpack_from("<I", data, 0)[0]
    if sig_type not in TIK_SIG_SIZES:
        sig_type = struct.unpack_from(">I", data, 0)[0]
        if sig_type not in TIK_SIG_SIZES:
            raise TikError("unknown signature type")
    sig_len, pad = TIK_SIG_SIZES[sig_type]
    body = 4 + sig_len + pad
    if len(data) < body + 0x170:
        raise TikError("ticket truncated")
    title_key_type = data[body + 0x141]
    rights_id = data[body + 0x160:body + 0x170].hex()
    key_block = data[body + 0x40:body + 0x140]
    # Common ticket (type 0): the first 16 bytes are the encrypted titlekey
    key = key_block[:16].hex() if title_key_type == 0 else None
    return {"rights_id": rights_id, "key_type": title_key_type, "title_key": key}


def parse_title_keys(text):
    """title.keys format: lines `rightsid=key` (32 hex characters each), comments start with ; or #."""
    keys = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in ";#" or "=" not in line:
            continue
        rid, key = (p.strip().lower() for p in line.split("=", 1))
        if re.fullmatch(r"[0-9a-f]{32}", rid) and re.fullmatch(r"[0-9a-f]{32}", key):
            keys[rid] = key
    return keys


def find_title_key(rights_id, tik_dir=None, title_keys_text=None):
    """Looks up the titlekey: first a common ticket in the folder, then title.keys. Returns (key, source)."""
    rid = rights_id.lower()
    personalized = False
    if tik_dir and os.path.isdir(tik_dir):
        for name in sorted(os.listdir(tik_dir)):
            if not name.lower().endswith(".tik"):
                continue
            with open(os.path.join(tik_dir, name), "rb") as f:
                try:
                    tik = parse_tik(f.read())
                except TikError:
                    continue
            if tik["rights_id"] != rid:
                continue
            if tik["title_key"]:
                return tik["title_key"], "tik"
            personalized = True
    if title_keys_text:
        key = parse_title_keys(title_keys_text).get(rid)
        if key:
            return key, "title.keys"
    if personalized:
        raise KeyError("personalized ticket (cannot be decrypted) and no entry in title.keys")
    raise KeyError("no ticket and no entry in title.keys for the rights ID")


def parse_nca_info(text, path=""):
    """Extracts only non-critical fields from the `hactool -i` output (never key lines)."""
    fields = {}
    wanted = {
        "Title ID": "title_id", "Content Type": "content_type",
        "Master Key Revision": "master_key_rev", "Encryption Type": "encryption",
        "Rights ID": "rights_id", "Content Size": "size",
    }
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z ]*?):\s+(\S.*)$", line)
        if not m or m.group(1) not in wanted:
            continue
        fields.setdefault(wanted[m.group(1)], m.group(2).strip())
    if "title_id" not in fields or "content_type" not in fields:
        raise ValueError("no NCA info (keys missing or not an NCA)")
    rights = fields.get("rights_id", ZERO_RIGHTS).lower()
    return {
        "path": path,
        "title_id": fields["title_id"].lower(),
        "content_type": fields["content_type"],
        "master_key_rev": fields.get("master_key_rev", "").split(" ")[0],
        "encryption": fields.get("encryption", "Titlekey crypto" if rights != ZERO_RIGHTS else ""),
        "rights_id": "" if rights == ZERO_RIGHTS else rights,
        "size": int(fields["size"], 16) if "size" in fields else 0,
    }


def info_row(info):
    cols = ["path", "title_id", "content_type", "master_key_rev", "encryption", "rights_id", "size"]
    return "\t".join(str(info[c]) for c in cols)


def pick_nca(rows, content_type, title_id=None):
    """Picks the largest NCA with the content type (and title ID) from TSV lines; None if none matches."""
    best = None
    for row in rows:
        cols = row.rstrip("\n").split("\t")
        if len(cols) < 7:
            continue
        path, tid, ctype, size = cols[0], cols[1], cols[2], int(cols[6] or 0)
        if ctype.lower() != content_type.lower():
            continue
        if title_id and tid != title_id.lower():
            continue
        if best is None or size > best[0]:
            best = (size, path)
    return best[1] if best else None


def pick_related_nca(rows, content_type, title_id):
    """Associate unambiguous Control/Meta content with a Program's title family."""
    matches = []
    for row in rows:
        fields = row.rstrip("\n").split("\t")
        if (len(fields) >= 7 and fields[2].lower() == content_type.lower() and
                (int(fields[1], 16) & ~0xFFF) == (int(title_id, 16) & ~0xFFF)):
            matches.append(fields[0])
    if len(matches) > 1:
        raise ValueError("Multiple matching " + content_type + " NCAs; title association is ambiguous")
    return matches[0] if matches else ""


def cnmt_version(data):
    """Title version (u32 LE at offset 8) and title ID from a PackagedContentMeta."""
    if len(data) < 0x10:
        raise ValueError("cnmt too short")
    title_id, version = struct.unpack_from("<QI", data, 0)
    return {"title_id": "%016x" % title_id, "version": version}


def nacp_display_version(data):
    """Anzeigeversion aus control.nacp (Offset 0x3060, 16 Byte)."""
    if len(data) < 0x3070:
        raise ValueError("nacp too short")
    return data[0x3060:0x3070].split(b"\0", 1)[0].decode("utf-8", "replace")


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def romfs_stats(romfs):
    count = total = 0
    for p in _walk_files(romfs):
        if os.path.basename(p) == ".DS_Store":
            continue
        count += 1
        total += os.path.getsize(p)
    return count, total


def file_hashes(path):
    sha256, sha1 = hashlib.sha256(), hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha256.update(chunk)
            sha1.update(chunk)
    return sha256.hexdigest(), sha1.hexdigest()


def input_fingerprint(path):
    """Content identity of one container or a folder of NCAs, without recording its path."""
    if not path:
        return ""
    if os.path.isfile(path):
        return file_hashes(path)[0]
    digest = hashlib.sha256()
    for parent, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            if not name.lower().endswith((".nca", ".tik")):
                continue
            full = os.path.join(parent, name)
            relative = os.path.relpath(full, path).replace(os.sep, "/")
            digest.update(relative.encode("utf-8", "surrogateescape"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(file_hashes(full)[0]))
    return digest.hexdigest()


def build_manifest(work, title_id, title_version, display_version, update_applied, xci_size, nsp_size,
                   base_kind=None, base_path=None, update_path=None):
    """Only hashes, title ID, version and sizes, no key material."""
    exefs_dir = os.path.join(work, "exefs")
    main_sha256, main_sha1 = file_hashes(os.path.join(exefs_dir, "main"))
    exefs_files = {}
    for name in sorted(os.listdir(exefs_dir)):
        p = os.path.join(exefs_dir, name)
        if os.path.isfile(p):
            exefs_files[name] = file_hashes(p)[0]
    count, total = romfs_stats(os.path.join(work, "romfs"))
    return {
        "schema": MANIFEST_SCHEMA,
        "stage": "extract",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title_id": title_id,
        "title_version": title_version,
        "display_version": display_version,
        "update_applied": bool(update_applied),
        "inputs": {"xci_size": xci_size, "nsp_size": nsp_size,
                   "base_kind": base_kind, "base_sha256": input_fingerprint(base_path),
                   "update_sha256": input_fingerprint(update_path)},
        "exefs": {"main": {"sha256": main_sha256, "sha1": main_sha1}, "files_sha256": exefs_files},
        "romfs": {"files": count, "bytes": total},
    }


def manifest_matches(work, xci_size, nsp_size, base_kind=None, base_path=None, update_path=None):
    """True if manifest.json matches the inputs and the existing results."""
    try:
        with open(os.path.join(work, "manifest.json")) as f:
            m = json.load(f)
        if m.get("schema") != MANIFEST_SCHEMA or m.get("stage") != "extract":
            return False
        if m["inputs"]["xci_size"] != xci_size or m["inputs"]["nsp_size"] != nsp_size:
            return False
        if base_path and (m["inputs"].get("base_kind") != base_kind or
                          m["inputs"].get("base_sha256") != input_fingerprint(base_path) or
                          m["inputs"].get("update_sha256") != input_fingerprint(update_path)):
            return False
        main = os.path.join(work, "exefs", "main")
        if file_hashes(main)[0] != m["exefs"]["main"]["sha256"]:
            return False
        for name, digest in m["exefs"].get("files_sha256", {}).items():
            if os.path.basename(name) != name or name in (".", ".."):
                return False
            if name != "main" and file_hashes(os.path.join(work, "exefs", name))[0] != digest:
                return False
        count, total = romfs_stats(os.path.join(work, "romfs"))
        return count > 0 and count == m["romfs"]["files"] and total == m["romfs"]["bytes"]
    except (OSError, KeyError, ValueError, TypeError):
        return False


def _find_first(root, suffix):
    for p in _walk_files(root):
        if p.lower().endswith(suffix):
            return p
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("nca-info")
    p.add_argument("--path", default="")
    p = sub.add_parser("pick")
    p.add_argument("--tsv", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--title-id")
    p = sub.add_parser("titlekey")
    p.add_argument("--rights-id", required=True)
    p.add_argument("--tik-dir")
    p.add_argument("--title-keys")
    p = sub.add_parser("cnmt-version")
    p.add_argument("dir")
    p = sub.add_parser("nacp-version")
    p.add_argument("dir")
    for name in ("write-manifest", "check-manifest"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
        p.add_argument("--xci-size", type=int, default=0)
        p.add_argument("--nsp-size", type=int, default=0)
        p.add_argument("--base-kind", choices=("xci", "nsp", "nca"))
        p.add_argument("--base-path")
        p.add_argument("--update-path")
        if name == "write-manifest":
            p.add_argument("--title-id", required=True)
            p.add_argument("--title-version", type=int, default=0)
            p.add_argument("--display-version", default="")
            p.add_argument("--update-applied", type=int, default=0)
    a = ap.parse_args(argv)

    if a.cmd == "nca-info":
        try:
            print(info_row(parse_nca_info(sys.stdin.read(), a.path)))
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if a.cmd == "pick":
        with open(a.tsv) as f:
            path = pick_nca(f.readlines(), a.type, a.title_id)
        if not path:
            return EX_NOTFOUND
        print(path)
        return 0
    if a.cmd == "titlekey":
        text = None
        if a.title_keys:
            with open(a.title_keys, errors="replace") as f:
                text = f.read()
        try:
            key, source = find_title_key(a.rights_id, a.tik_dir, text)
        except KeyError as e:
            print(e.args[0], file=sys.stderr)
            return EX_KEYS
        print("Titlekey source: " + source, file=sys.stderr)
        print(key)
        return 0
    if a.cmd == "cnmt-version":
        path = _find_first(a.dir, ".cnmt")
        if not path:
            return EX_NOTFOUND
        with open(path, "rb") as f:
            print(cnmt_version(f.read())["version"])
        return 0
    if a.cmd == "nacp-version":
        path = _find_first(a.dir, "control.nacp")
        if not path:
            return EX_NOTFOUND
        with open(path, "rb") as f:
            print(nacp_display_version(f.read()))
        return 0
    if a.cmd == "write-manifest":
        m = build_manifest(a.work, a.title_id, a.title_version, a.display_version,
                           a.update_applied, a.xci_size, a.nsp_size,
                           a.base_kind, a.base_path, a.update_path)
        tmp = os.path.join(a.work, "manifest.json.tmp")
        with open(tmp, "w") as f:
            json.dump(m, f, indent=2)
            f.write("\n")
        os.replace(tmp, os.path.join(a.work, "manifest.json"))
        return 0
    if a.cmd == "check-manifest":
        return 0 if manifest_matches(a.work, a.xci_size, a.nsp_size,
                                     a.base_kind, a.base_path, a.update_path) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
