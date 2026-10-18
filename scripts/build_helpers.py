#!/usr/bin/env python3
"""Hilfslogik für scripts/build_all.sh (reine Funktionen, nur Standardbibliothek).

Gibt nie Schlüsselmaterial in Logs aus. Der Titlekey geht ausschließlich auf stdout des
Unterbefehls `titlekey` und wird vom Aufrufer in einer Shell-Variable gehalten.

Unterbefehle (Aufruf: build_helpers.py <befehl> ...):
  nca-info --path P          liest `hactool -i` von stdin, gibt eine TSV-Zeile mit Sicherem aus
  pick --tsv F --type T [--title-id X]   wählt die größte passende NCA, gibt den Pfad aus
  titlekey --rights-id R --tik-dir D [--title-keys F]   gibt den Titlekey (Hex) aus
  cnmt-version DIR           Titelversion aus der .cnmt unter DIR (Dezimal)
  nacp-version DIR           Anzeigeversion aus control.nacp unter DIR
  write-manifest ...         schreibt <work>/manifest.json
  check-manifest ...         Exit 0, wenn manifest.json zum Arbeitsordner passt
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import time

# Exit-Codes (müssen zu build_all.sh passen)
EX_KEYS = 6
EX_NOTFOUND = 7

# Ticket-Signaturtypen: Typ -> (Signaturlänge, Padding)
TIK_SIG_SIZES = {
    0x010000: (0x200, 0x3C), 0x010001: (0x100, 0x3C), 0x010002: (0x3C, 0x40),
    0x010003: (0x200, 0x3C), 0x010004: (0x100, 0x3C), 0x010005: (0x3C, 0x40),
}
ZERO_RIGHTS = "0" * 32
MANIFEST_SCHEMA = 1


class TikError(Exception):
    pass


def parse_tik(data):
    """Liest ein Ticket und gibt Rights-ID, Titlekey-Typ und (bei Common-Tickets) den Titlekey zurück."""
    if len(data) < 4:
        raise TikError("Ticket zu kurz")
    sig_type = struct.unpack_from("<I", data, 0)[0]
    if sig_type not in TIK_SIG_SIZES:
        sig_type = struct.unpack_from(">I", data, 0)[0]
        if sig_type not in TIK_SIG_SIZES:
            raise TikError("unbekannter Signaturtyp")
    sig_len, pad = TIK_SIG_SIZES[sig_type]
    body = 4 + sig_len + pad
    if len(data) < body + 0x170:
        raise TikError("Ticket abgeschnitten")
    title_key_type = data[body + 0x141]
    rights_id = data[body + 0x160:body + 0x170].hex()
    key_block = data[body + 0x40:body + 0x140]
    # Common-Ticket (Typ 0): die ersten 16 Byte sind der verschlüsselte Titlekey
    key = key_block[:16].hex() if title_key_type == 0 else None
    return {"rights_id": rights_id, "key_type": title_key_type, "title_key": key}


def parse_title_keys(text):
    """title.keys-Format: Zeilen `rightsid=key` (je 32 Hex-Zeichen), Kommentare mit ; oder #."""
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
    """Sucht den Titlekey: zuerst Common-Ticket im Ordner, dann title.keys. Gibt (key, quelle) zurück."""
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
        raise KeyError("personalisiertes Ticket (nicht entschlüsselbar) und kein Eintrag in title.keys")
    raise KeyError("kein Ticket und kein Eintrag in title.keys für die Rights-ID")


def parse_nca_info(text, path=""):
    """Zieht nur unkritische Felder aus der `hactool -i`-Ausgabe (nie Schlüsselzeilen)."""
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
        raise ValueError("keine NCA-Info (Schlüssel fehlen oder keine NCA)")
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
    """Wählt aus TSV-Zeilen die größte NCA mit Content-Typ (und Titel-ID); None, wenn keine passt."""
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


def cnmt_version(data):
    """Titelversion (u32 LE bei Offset 8) und Titel-ID aus einer PackagedContentMeta."""
    if len(data) < 0x10:
        raise ValueError("cnmt zu kurz")
    title_id, version = struct.unpack_from("<QI", data, 0)
    return {"title_id": "%016x" % title_id, "version": version}


def nacp_display_version(data):
    """Anzeigeversion aus control.nacp (Offset 0x3060, 16 Byte)."""
    if len(data) < 0x3070:
        raise ValueError("nacp zu kurz")
    return data[0x3060:0x3070].split(b"\0", 1)[0].decode("utf-8", "replace")


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def romfs_stats(romfs):
    count = total = 0
    for p in _walk_files(romfs):
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


def build_manifest(work, title_id, title_version, display_version, update_applied, xci_size, nsp_size):
    """Nur Hashes, Titel-ID, Version und Größen – kein Schlüsselmaterial."""
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
        "inputs": {"xci_size": xci_size, "nsp_size": nsp_size},
        "exefs": {"main": {"sha256": main_sha256, "sha1": main_sha1}, "files_sha256": exefs_files},
        "romfs": {"files": count, "bytes": total},
    }


def manifest_matches(work, xci_size, nsp_size):
    """True, wenn manifest.json zu Eingaben und vorhandenen Ergebnissen passt."""
    try:
        with open(os.path.join(work, "manifest.json")) as f:
            m = json.load(f)
        if m.get("schema") != MANIFEST_SCHEMA or m.get("stage") != "extract":
            return False
        if m["inputs"]["xci_size"] != xci_size or m["inputs"]["nsp_size"] != nsp_size:
            return False
        main = os.path.join(work, "exefs", "main")
        if file_hashes(main)[0] != m["exefs"]["main"]["sha256"]:
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
        print("Titlekey-Quelle: " + source, file=sys.stderr)
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
                           a.update_applied, a.xci_size, a.nsp_size)
        tmp = os.path.join(a.work, "manifest.json.tmp")
        with open(tmp, "w") as f:
            json.dump(m, f, indent=2)
            f.write("\n")
        os.replace(tmp, os.path.join(a.work, "manifest.json"))
        return 0
    if a.cmd == "check-manifest":
        return 0 if manifest_matches(a.work, a.xci_size, a.nsp_size) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
