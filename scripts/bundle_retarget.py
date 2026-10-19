#!/usr/bin/env python3
"""Setzt in UnityFS-Bundles die Zielplattform (m_TargetPlatform der Serialized Files) um.

Hintergrund: Die Bundles des Spiels sind für die Switch gebaut (Zielplattform 38). Der Editor lädt sie trotzdem, ein
Player lehnt sie ab ("created for another build target that is not compatible with this platform"). Dieses Skript
ändert nur die vier Bytes der Plattformkennung; Inhalt, Texturformate und Shader bleiben unverändert.

Vorgehen je Bundle: Blockinfo lesen, den Block mit der Plattformkennung entpacken, patchen und mit LZ4HC neu packen
(nur dieser eine Block, höchstens 128 KiB; lässt er sich nicht verkleinern, bleibt er unkomprimiert), Blockinfo neu
schreiben (unkomprimiert), alle übrigen Blöcke unverändert kopieren.
Keine Spieldaten im Repo: gearbeitet wird nur auf lokalen, gitignorierten Ordnern.

Aufruf:
  scripts/bundle_retarget.py info  DATEI
  scripts/bundle_retarget.py patch QUELLE ZIEL --platform macos|ios|<Zahl>
  scripts/bundle_retarget.py tree  ORDNER --platform macos|ios|<Zahl> [--list DATEI] [--dry-run]
      tree ändert Bundles im ORDNER (schreibt neue Datei, benennt über die alte; ein APFS-Klon des Originals bleibt unberührt).
      --list: nur die dort aufgeführten Pfade (relativ zum ORDNER, eine je Zeile).
  scripts/bundle_retarget.py subset QUELLE ZIEL --list DATEI --platform macos|ios|<Zahl>
      kopiert nur die gelisteten Bundles (Zeilen mit # sind Kommentare) und alle Nicht-Bundle-Dateien (Katalog) und setzt die Plattform.
Voraussetzung: Python-Modul lz4 (tools/pydeps, PYTHONPATH=tools/pydeps).
Exit-Codes: 0 ok, 2 Aufruf, 3 Datei fehlt/kein UnityFS, 4 Format nicht unterstützt.
"""
import argparse
import os
import struct
import sys

PLATFORMS = {"macos": 2, "ios": 9, "windows": 5, "android": 13, "switch": 38}
MAGIC = b"UnityFS\x00"
COMP_MASK = 0x3F


class Unsupported(Exception):
    pass


def _lz4_compress(data):
    import lz4.block
    return lz4.block.compress(data, mode="high_compression", store_size=False)


def _lz4_decompress(data, size):
    import lz4.block
    return lz4.block.decompress(data, uncompressed_size=size)


def _cstr(buf, off):
    end = buf.index(b"\0", off)
    return buf[off:end].decode("utf-8", "replace"), end + 1


def parse(path):
    """Liest Kopf, Blockinfo und Knoten. Gibt ein Dict zurück oder wirft Unsupported/ValueError."""
    with open(path, "rb") as f:
        head = f.read(512)
        if not head.startswith(MAGIC):
            raise ValueError("kein UnityFS")
        off = len(MAGIC)
        version = struct.unpack_from(">I", head, off)[0]; off += 4
        player, off = _cstr(head, off)
        engine, off = _cstr(head, off)
        size, cinfo, uinfo, flags = struct.unpack_from(">QIII", head, off); off += 20
        header_end = off
        if version < 6:
            raise Unsupported("UnityFS-Version %d" % version)
        if flags & 0x80:
            raise Unsupported("Blockinfo am Dateiende")
        info_start = (header_end + 15) // 16 * 16 if version >= 7 else header_end
        f.seek(info_start)
        raw = f.read(cinfo)
    comp = flags & COMP_MASK
    if comp == 0:
        info = raw
    elif comp in (2, 3):
        info = _lz4_decompress(raw, uinfo)
    else:
        raise Unsupported("Blockinfo-Kompression %d" % comp)
    if len(info) != uinfo:
        raise ValueError("Blockinfo-Größe stimmt nicht")
    guid = info[:16]
    (nblocks,) = struct.unpack_from(">i", info, 16)
    p = 20
    blocks = []
    for _ in range(nblocks):
        u, c, fl = struct.unpack_from(">IIH", info, p); p += 10
        blocks.append([u, c, fl])
    (nnodes,) = struct.unpack_from(">i", info, p); p += 4
    nodes = []
    for _ in range(nnodes):
        o, s, fl = struct.unpack_from(">QQI", info, p); p += 20
        name, p = _cstr(info, p)
        nodes.append((o, s, fl, name))
    return {
        "version": version, "player": player, "engine": engine, "size": size, "flags": flags,
        "header_end": header_end, "info_start": info_start, "info_len": cinfo,
        "guid": guid, "blocks": blocks, "nodes": nodes, "data_start": info_start + cinfo,
    }


def serialized_platform(buf):
    """(Offset der Plattformkennung, Wert, little-endian) am Anfang eines Serialized Files; None, wenn nicht erkennbar."""
    if len(buf) < 32:
        return None
    version = struct.unpack_from(">I", buf, 8)[0]
    if version < 7 or version > 100:
        return None
    pos = 48 if version >= 22 else 20     # ab 22 erweiterter Kopf mit 64-Bit-Feldern
    little = buf[40 if version >= 22 else 16] == 0
    try:
        _, pos = _cstr(buf, pos)
    except ValueError:
        return None
    if pos + 4 > len(buf):
        return None
    return pos, struct.unpack_from("<i" if little else ">i", buf, pos)[0], little


def _serialized_nodes(nodes):
    return [n for n in nodes if not n[3].endswith((".resS", ".resource", ".resourceFile"))]


def _block_of(info, offset):
    """(Blockindex, Start des Blocks im entpackten Strom, Größe) für einen Offset."""
    pos = 0
    for i, (u, c, fl) in enumerate(info["blocks"]):
        if pos <= offset < pos + u:
            return i, pos, u
        pos += u
    raise ValueError("Offset außerhalb der Blöcke")


def _read_block(f, info, index):
    pos = info["data_start"] + sum(b[1] for b in info["blocks"][:index])
    u, c, fl = info["blocks"][index]
    f.seek(pos)
    raw = f.read(c)
    comp = fl & COMP_MASK
    if comp == 0:
        return raw
    if comp in (2, 3):
        return _lz4_decompress(raw, u)
    raise Unsupported("Block-Kompression %d" % comp)


def read_platforms(path):
    """Plattformkennungen der Serialized Files eines Bundles: [(Name, Wert)]."""
    info = parse(path)
    out = []
    with open(path, "rb") as f:
        for off, size, fl, name in _serialized_nodes(info["nodes"]):
            bi, bstart, _ = _block_of(info, off)
            data = _read_block(f, info, bi)
            rel = off - bstart
            hit = serialized_platform(data[rel:rel + 128])
            out.append((name, hit[1] if hit else None))
    return out


def retarget(src, dst, platform):
    """Schreibt das Bundle mit geänderter Plattform nach dst (auch dst == src). (alt, neu) oder None, wenn nichts zu tun war."""
    info = parse(src)
    patches = {}   # Blockindex -> [(Offset im Block, little-endian)]
    old = None
    with open(src, "rb") as f:
        for off, size, fl, name in _serialized_nodes(info["nodes"]):
            bi, bstart, bsize = _block_of(info, off)
            data = _read_block(f, info, bi)
            rel = off - bstart
            hit = serialized_platform(data[rel:rel + 128])
            if hit is None:
                continue
            pos, value, little = hit
            if value == platform:
                continue
            if rel + pos + 4 > bsize:
                raise Unsupported("Plattformkennung über Blockgrenze")
            old = value
            patches.setdefault(bi, []).append((rel + pos, little))
    if not patches:
        return None

    blocks = [list(b) for b in info["blocks"]]
    new_blocks = {}
    with open(src, "rb") as f:
        for bi, plist in patches.items():
            data = bytearray(_read_block(f, info, bi))
            for pos, little in plist:
                struct.pack_into("<i" if little else ">i", data, pos, platform)
            raw = bytes(data)
            comp = _lz4_compress(raw) if blocks[bi][2] & COMP_MASK in (2, 3) else None
            if comp is not None and len(comp) < len(raw):
                new_blocks[bi] = comp
                blocks[bi] = [len(raw), len(comp), (blocks[bi][2] & ~COMP_MASK) | 3]
            else:
                new_blocks[bi] = raw
                blocks[bi] = [len(raw), len(raw), blocks[bi][2] & ~COMP_MASK]

    infob = bytearray(info["guid"])
    infob += struct.pack(">i", len(blocks))
    for u, c, fl in blocks:
        infob += struct.pack(">IIH", u, c, fl)
    infob += struct.pack(">i", len(info["nodes"]))
    for o, s, fl, name in info["nodes"]:
        infob += struct.pack(">QQI", o, s, fl) + name.encode() + b"\0"

    flags = info["flags"] & ~COMP_MASK        # Blockinfo unkomprimiert
    data_total = sum(b[1] for b in blocks)
    head = bytearray(MAGIC + struct.pack(">I", info["version"]))
    head += info["player"].encode() + b"\0" + info["engine"].encode() + b"\0"
    size_pos = len(head)
    head += struct.pack(">QIII", 0, len(infob), len(infob), flags)
    if info["version"] >= 7:
        head += b"\0" * ((-len(head)) % 16)
    struct.pack_into(">Q", head, size_pos, len(head) + len(infob) + data_total)

    tmp = dst + ".tmp"
    with open(src, "rb") as f, open(tmp, "wb") as out:
        out.write(head)
        out.write(infob)
        f.seek(info["data_start"])
        for i, (u, c, fl) in enumerate(info["blocks"]):
            if i in new_blocks:
                f.seek(c, 1)
                out.write(new_blocks[i])
            else:
                left = c
                while left:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk:
                        raise ValueError("Bundle abgeschnitten")
                    out.write(chunk)
                    left -= len(chunk)
    os.replace(tmp, dst)
    return old, platform


def parse_platform(text):
    if text in PLATFORMS:
        return PLATFORMS[text]
    try:
        return int(text)
    except ValueError:
        raise SystemExit("Unbekannte Plattform: %s (macos, ios oder Zahl)" % text)


def is_unityfs(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def cmd_tree(root, platform, listfile, dry):
    if listfile:
        with open(listfile) as f:
            paths = [os.path.join(root, line.strip()) for line in f if line.strip()]
    else:
        paths = []
        for d, _, files in os.walk(root):
            paths += [os.path.join(d, n) for n in files]
    changed = same = skipped = failed = 0
    for p in sorted(paths):
        if not is_unityfs(p):
            skipped += 1
            continue
        try:
            if dry:
                differs = any(v != platform for _, v in read_platforms(p))
                changed += differs
                same += not differs
            elif retarget(p, p, platform) is None:
                same += 1
            else:
                changed += 1
        except (Unsupported, ValueError, OSError) as e:
            failed += 1
            print("FEHLER %s: %s" % (os.path.relpath(p, root), e), file=sys.stderr)
    print("tree: geändert %d, schon passend %d, kein Bundle %d, Fehler %d%s"
          % (changed, same, skipped, failed, " (Probelauf)" if dry else ""))
    return 4 if failed else 0


def cmd_subset(src, dst, listfile, platform):
    """Kopiert nur die gelisteten Bundles (plus alle Nicht-Bundle-Dateien wie den Katalog) und setzt die Plattform."""
    with open(listfile) as f:
        wanted = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    import shutil
    found = set()
    copied = size = 0
    for d, _, files in os.walk(src):
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, src)
            if is_unityfs(p) and rel not in wanted:
                continue
            found.add(rel)
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if is_unityfs(p):
                if retarget(p, out, platform) is None:
                    shutil.copyfile(p, out)
            else:
                shutil.copyfile(p, out)
            copied += 1
            size += os.path.getsize(out)
    missing = sorted(wanted - found)
    for m in missing:
        print("FEHLT in der Quelle: %s" % m, file=sys.stderr)
    print("subset: %d Dateien, %d Byte, %d gelistete Bundles fehlen" % (copied, size, len(missing)))
    return 3 if missing else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("info"); a.add_argument("file")
    b = sub.add_parser("patch"); b.add_argument("src"); b.add_argument("dst"); b.add_argument("--platform", required=True)
    c = sub.add_parser("tree"); c.add_argument("root"); c.add_argument("--platform", required=True)
    c.add_argument("--list"); c.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("subset"); s.add_argument("src"); s.add_argument("dst"); s.add_argument("--list", required=True)
    s.add_argument("--platform", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "subset":
            if not os.path.isdir(args.src) or not os.path.isfile(args.list):
                return 3
            return cmd_subset(args.src, args.dst, args.list, parse_platform(args.platform))
        if args.cmd == "info":
            if not os.path.isfile(args.file):
                return 3
            i = parse(args.file)
            print("UnityFS v%d, %s, %d Blöcke, %d Knoten" % (i["version"], i["engine"], len(i["blocks"]), len(i["nodes"])))
            for name, v in read_platforms(args.file):
                print("  %s: Plattform %s" % (name, v))
            return 0
        if args.cmd == "patch":
            r = retarget(args.src, args.dst, parse_platform(args.platform))
            if r is None:
                import shutil
                shutil.copyfile(args.src, args.dst)
                print("schon passend, kopiert")
            else:
                print("Plattform %d -> %d" % r)
            return 0
        if not os.path.isdir(args.root):
            return 3
        return cmd_tree(args.root, parse_platform(args.platform), args.list, args.dry_run)
    except (FileNotFoundError, ValueError) as e:
        print("FEHLER: %s" % e, file=sys.stderr)
        return 3
    except Unsupported as e:
        print("FEHLER (nicht unterstützt): %s" % e, file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
