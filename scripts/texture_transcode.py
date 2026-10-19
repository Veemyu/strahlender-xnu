#!/usr/bin/env python3
"""Wandelt BCn-Texturen (BC1/BC3/BC4/BC5/BC7, DXT1/DXT5, Crunch) in UnityFS-Bundles nach ASTC um (für iOS/iPadOS).

Hintergrund: Die Bundles des Spiels stammen von der Switch und enthalten DXT/BC-Texturen. Apple-GPUs (iOS/iPadOS)
unterstützen BCn nicht, Unity meldet je Textur "format is not supported, decompressing texture" und danach
"Failed to decompress" (docs/player-build-1.md, Abschnitt 6). Dieses Skript dekodiert jede Mip-Stufe der Textur
nach RGBA, kodiert sie mit astcenc (Python-Modul astc_encoder) als ASTC und schreibt das Bundle neu.

Erhalten bleiben: Objektnamen, PathIDs, Breite/Höhe, Mip-Anzahl (jede Stufe wird einzeln umgewandelt, keine neue
Mip-Kette), ColorSpace, Wrap-/Filter-Einstellungen, Streaming über die .resS-Datei des Bundles (Offsets/Größen werden
neu gesetzt). Der sRGB-Flag der Textur bestimmt das astcenc-Profil (LDR_SRGB bzw. LDR).
Nicht angefasst: Texturen, die iOS schon kann (ASTC, RGBA32, Alpha8, ...), HDR (BC6H), Cubemaps und Texture2DArray
(werden gezählt und gemeldet).
Keine Spieldaten im Repo: gearbeitet wird nur auf lokalen, gitignorierten Ordnern.

Zielformat (--block): 6x6 (Standard; 3,56 Bit/Pixel, gleiche Wahl wie die Originaltexturen der Figuren/UI),
4x4 (8 Bit/Pixel, beste Qualität), 8x8 (2 Bit/Pixel). BC4/BC5 (Normal-/Einkanalmaps) nutzen immer mindestens 4x4,
weil dort Blockartefakte sofort sichtbar sind (--block-data, Standard 4x4).
Die Unity-Formatkennungen sind ASTC_4x4=48, 5x5=49, 6x6=50, 8x8=51 (wie die Original-ASTC-Texturen im Spiel).

Aufruf (PYTHONPATH=tools/pydeps):
  texture_transcode.py info    BUNDLE                       Texturformate und Größen
  texture_transcode.py bundle  QUELLE ZIEL [--block 6x6] [--quality medium]
  texture_transcode.py tree    ORDNER [--list DATEI] [--block 6x6] [--jobs N] [--dry-run]
      ändert die Bundles im ORDNER (schreibt neue Datei, benennt über die alte; ein APFS-Klon des Originals bleibt unberührt).
      --list: nur die dort aufgeführten Pfade (relativ zum ORDNER, Zeilen mit # sind Kommentare).
  texture_transcode.py psnr    QUELLE ZIEL [--samples 50]   PSNR je Textur gegen die dekodierte BC-Quelle (nur Zahlen)
Idempotent: ein Bundle ohne umzuwandelnde Texturen bleibt unverändert; ein zweiter Lauf ändert nichts.
Exit-Codes: 0 ok, 2 Aufruf, 3 Datei fehlt, 4 Fehler bei mindestens einem Bundle.
"""
import argparse
import math
import os
import sys
import time

ASTC_IDS = {(4, 4): 48, (5, 5): 49, (6, 6): 50, (8, 8): 51, (10, 10): 52, (12, 12): 53}
ASTC_ID_SET = set(range(48, 60)) | set(range(66, 72))     # inklusive RGBA-Kennungen und HDR
# Unity-TextureFormat -> (Name, Bytes je 4x4-Block, Daten-Textur?)
BC_FORMATS = {10: ("DXT1", 8, False), 12: ("DXT5", 16, False), 25: ("BC7", 16, False),
              26: ("BC4", 8, True), 27: ("BC5", 16, True)}
CRUNCHED = {28: "DXT1Crunched", 29: "DXT5Crunched"}
MAGIC = b"UnityFS\x00"
STREAM_TYPES = ("Mesh", "AudioClip", "VideoClip", "Texture3D", "Cubemap", "Texture2DArray", "CubemapArray")
QUALITIES = {"fastest": 0.0, "fast": 10.0, "medium": 60.0, "thorough": 98.0}


def parse_block(text):
    try:
        x, y = text.lower().split("x")
        b = (int(x), int(y))
    except ValueError:
        raise SystemExit("Ungültiger Blockwert: %s (z. B. 4x4, 6x6, 8x8)" % text)
    if b not in ASTC_IDS:
        raise SystemExit("Blockgröße %s nicht unterstützt (%s)" % (text, ", ".join("%dx%d" % k for k in ASTC_IDS)))
    return b


def mip_dims(width, height, mips):
    out = []
    w, h = width, height
    for _ in range(max(1, mips)):
        out.append((w, h))
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def bc_size(w, h, block_bytes):
    return ((w + 3) // 4) * ((h + 3) // 4) * block_bytes


def astc_size(w, h, block):
    return ((w + block[0] - 1) // block[0]) * ((h + block[1] - 1) // block[1]) * 16


def decode_bc(fmt, data, w, h):
    """BC-Daten einer Mip-Stufe nach BGRA (texture2ddecoder liefert BGRA, Daten als 4 Byte je Pixel)."""
    import texture2ddecoder as t
    fn = {10: t.decode_bc1, 12: t.decode_bc3, 25: t.decode_bc7, 26: t.decode_bc4, 27: t.decode_bc5}[fmt]
    return fn(data, w, h)


_CONTEXTS = {}


def astc_context(block, srgb, quality):
    import astc_encoder as a
    key = (block, srgb, quality)
    if key not in _CONTEXTS:
        profile = a.ASTCProfile.LDR_SRGB if srgb else a.ASTCProfile.LDR
        cfg = a.ASTCConfig(profile, block[0], block[1], 1, QUALITIES[quality], a.ASTCConfigFlags.USE_DECODE_UNORM8)
        _CONTEXTS[key] = a.ASTCContext(cfg)
    return _CONTEXTS[key]


def encode_astc(bgra, w, h, block, srgb, quality):
    import astc_encoder as a
    img = a.ASTCImage(a.ASTCType.U8, w, h, 1, bytes(bgra))
    return bytes(astc_context(block, srgb, quality).compress(img, a.ASTCSwizzle.from_str("BGRA")))


def decode_astc_bgra(data, w, h, block, srgb):
    """ASTC-Daten einer Mip-Stufe nach BGRA (für PSNR und Roundtrip-Tests)."""
    import astc_encoder as a
    img = a.ASTCImage(a.ASTCType.U8, w, h, 1)
    astc_context(block, srgb, "medium").decompress(data[:astc_size(w, h, block)], img, a.ASTCSwizzle.from_str("BGRA"))
    return bytes(img.data)


def target_block(fmt, block, block_data):
    if BC_FORMATS[fmt][2]:
        return block_data if block_data[0] < block[0] else block
    return block


def transcode_levels(fmt, data, width, height, mips, block, srgb, quality):
    """Alle Mip-Stufen BC -> ASTC. Gibt (neue Daten, [(Offset, Größe)] je Stufe) zurück."""
    bb = BC_FORMATS[fmt][1]
    out = bytearray()
    off = 0
    for w, h in mip_dims(width, height, mips):
        size = bc_size(w, h, bb)
        if off + size > len(data):
            raise ValueError("Texturdaten kürzer als die Mip-Kette (%d < %d)" % (len(data), off + size))
        bgra = decode_bc(fmt, data[off:off + size], w, h)
        out += encode_astc(bgra, w, h, block, srgb, quality)
        off += size
    return bytes(out)


def crunched_to_astc(tex, block, srgb, quality):
    """Crunch-Texturen sind selten und winzig; nur die Hauptstufe wird dekodiert, die Mips entstehen per Box-Filter."""
    from PIL import Image
    img = tex.image.convert("RGBA")
    out = bytearray()
    cur = img
    for w, h in mip_dims(tex.m_Width, tex.m_Height, tex.m_MipCount):
        if cur.size != (w, h):
            cur = img.resize((w, h), Image.BOX)
        r, g, b, al = cur.split()
        bgra = Image.merge("RGBA", (b, g, r, al)).tobytes()
        out += encode_astc(bgra, w, h, block, srgb, quality)
    return bytes(out)


def is_unityfs(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _textures(env):
    for o in env.objects:
        if o.type.name == "Texture2D":
            yield o


def inspect_bundle(path):
    """Zählt Texturen je Format: {Name: (Anzahl, Bytes)} plus nicht behandelte Typen."""
    import UnityPy
    from UnityPy.enums import TextureFormat as TF
    env = UnityPy.load(path)
    counts, other = {}, {}
    for o in env.objects:
        n = o.type.name
        if n == "Texture2D":
            t = o.read()
            name = TF(t.m_TextureFormat).name if t.m_TextureFormat in TF._value2member_map_ else str(t.m_TextureFormat)
            c = counts.setdefault(name, [0, 0])
            c[0] += 1
            c[1] += t.m_CompleteImageSize
        elif n in ("Cubemap", "Texture2DArray", "CubemapArray", "Texture3D"):
            other[n] = other.get(n, 0) + 1
    return counts, other


def needs_transcode(fmt):
    return fmt in BC_FORMATS or fmt in CRUNCHED


def transcode_bundle(src, dst, block=(6, 6), block_data=(4, 4), quality="medium"):
    """Schreibt das Bundle mit ASTC-Texturen nach dst (auch dst == src). Gibt Statistik-Dict zurück oder None (nichts zu tun)."""
    import UnityPy
    from UnityPy.streams import EndianBinaryWriter
    from UnityPy.files import BundleFile
    from UnityPy.helpers.ResourceReader import get_resource_data
    t0 = time.time()
    env = UnityPy.load(src)
    bundle = env.file
    if not isinstance(bundle, BundleFile):
        raise ValueError("kein UnityFS-Bundle")
    work = []
    all_tex = []
    shared = set()
    skipped = {}
    for o in env.objects:
        n = o.type.name
        if n == "Texture2D":
            tex = o.read()
            all_tex.append(tex)
            fmt = int(tex.m_TextureFormat)
            if needs_transcode(fmt):
                if tex.m_TextureDimension != 2:
                    skipped["Texture2D-Dimension %d" % tex.m_TextureDimension] = skipped.get("Texture2D-Dimension %d" % tex.m_TextureDimension, 0) + 1
                    continue
                work.append(tex)
        elif n in STREAM_TYPES:
            if n in ("Cubemap", "Texture2DArray", "CubemapArray", "Texture3D"):
                skipped[n] = skipped.get(n, 0) + 1
            try:
                sd = o.read().m_StreamData
                if sd is not None and sd.size:
                    shared.add(sd.path)
            except Exception:
                shared.add("*")
    if not work:
        return None
    stats = {"texturen": len(work), "formate": {}, "bytes_vorher": 0, "bytes_nachher": 0, "uebersprungen": skipped}
    by_path = {}                       # resS-Pfad -> Liste der Texturen in der Datei
    for t in all_tex:
        if t.m_StreamData is not None and t.m_StreamData.size:
            by_path.setdefault(t.m_StreamData.path, []).append(t)
    new_data = {}                      # id(tex) -> neue Bytes
    work_ids = {id(t) for t in work}
    for tex in work:
        fmt = int(tex.m_TextureFormat)
        raw = tex.get_image_data()
        srgb = int(getattr(tex, "m_ColorSpace", 1)) == 1
        blk = target_block(fmt, block, block_data) if fmt in BC_FORMATS else block
        if fmt in BC_FORMATS:
            data = transcode_levels(fmt, bytes(raw), tex.m_Width, tex.m_Height, tex.m_MipCount, blk, srgb, quality)
        else:
            data = crunched_to_astc(tex, blk, srgb, quality)
        new_data[id(tex)] = (data, ASTC_IDS[blk])
        name = (BC_FORMATS.get(fmt) or (CRUNCHED[fmt],))[0]
        stats["formate"][name] = stats["formate"].get(name, 0) + 1
        stats["bytes_vorher"] += tex.m_CompleteImageSize
        stats["bytes_nachher"] += len(data)

    # resS neu aufbauen: nur wenn kein anderes Objekt die Datei mitbenutzt, sonst anhängen (alter Bereich bleibt Totraum)
    files = bundle.files
    resave = []
    for path, texes in by_path.items():
        node = path.split("/")[-1]
        resfile = files[node]
        old = bytes(resfile.bytes if hasattr(resfile, "bytes") else resfile.read_bytes())
        if not any(id(t) in work_ids for t in texes):
            continue
        compact = path not in shared and "*" not in shared
        buf = bytearray() if compact else bytearray(old)
        for t in sorted(texes, key=lambda x: x.m_StreamData.offset):
            sd = t.m_StreamData
            if id(t) in new_data:
                data = new_data[id(t)][0]
            elif compact:
                data = old[sd.offset:sd.offset + sd.size]
            else:
                continue
            if id(t) in new_data or compact:
                sd.offset = len(buf)
                sd.size = len(data)
                buf += data
                if id(t) not in work_ids:
                    resave.append(t)       # unveränderte Textur mit verschobenem Offset: Objekt muss neu geschrieben werden
        w = EndianBinaryWriter()
        w.write_bytes(bytes(buf))
        w.flags = resfile.flags
        files[node] = w
    for tex in work:
        data, tid = new_data[id(tex)]
        tex.m_TextureFormat = tid
        tex.m_CompleteImageSize = len(data)
        if tex.m_StreamData is not None and tex.m_StreamData.size:
            tex.m_StreamData.size = len(data)
            tex.image_data = b""
        else:
            tex.image_data = data
        tex.save()
    for tex in resave:
        tex.save()
    out = bundle.save(packer=(0x43, 3))
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, dst)
    stats["sekunden"] = round(time.time() - t0, 2)
    stats["bundle_bytes_nachher"] = len(out)
    return stats


def _worker(job):
    path, block, block_data, quality, dry = job
    try:
        if dry:
            counts, _ = inspect_bundle(path)
            bc = [c for k, c in counts.items() if k in ("DXT1", "DXT5", "BC7", "BC4", "BC5", "DXT1Crunched", "DXT5Crunched")]
            return path, ("dry", sum(c[0] for c in bc), sum(c[1] for c in bc)), None
        size_before = os.path.getsize(path)
        st = transcode_bundle(path, path, block, block_data, quality)
        if st is None:
            return path, None, None
        st["bundle_bytes_vorher"] = size_before
        return path, st, None
    except Exception as e:      # noqa: BLE001 - je Bundle melden, Lauf geht weiter
        return path, None, "%s: %s" % (type(e).__name__, e)


def cmd_tree(root, listfile, block, block_data, quality, jobs, dry):
    if listfile:
        with open(listfile) as f:
            paths = [os.path.join(root, l.strip()) for l in f if l.strip() and not l.startswith("#")]
    else:
        paths = [os.path.join(d, n) for d, _, fs in os.walk(root) for n in fs]
    paths = sorted(p for p in paths if is_unityfs(p))
    t0 = time.time()
    results = []
    todo = [(p, block, block_data, quality, dry) for p in paths]
    if jobs > 1 and len(todo) > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(jobs) as pool:
            for r in pool.imap_unordered(_worker, todo):
                results.append(r)
    else:
        results = [_worker(j) for j in todo]
    changed = same = failed = 0
    tex = before = after = tex_before = tex_after = 0
    for p, st, err in sorted(results):
        rel = os.path.relpath(p, root)
        if err:
            failed += 1
            print("FEHLER %s: %s" % (rel, err), file=sys.stderr)
        elif st is None or (isinstance(st, tuple) and st[1] == 0):
            same += 1
        elif isinstance(st, tuple):
            changed += 1
            tex += st[1]
            tex_before += st[2]
        else:
            changed += 1
            tex += st["texturen"]
            before += st["bundle_bytes_vorher"]
            after += st["bundle_bytes_nachher"]
            tex_before += st["bytes_vorher"]
            tex_after += st["bytes_nachher"]
            print("  %s: %d Texturen, %s, %.1f s, Bundle %d -> %d Byte" % (
                rel, st["texturen"], " ".join("%s=%d" % kv for kv in sorted(st["formate"].items())),
                st["sekunden"], st["bundle_bytes_vorher"], st["bundle_bytes_nachher"]))
    print("texturen: Bundles umgewandelt %d, ohne BC-Texturen %d, Fehler %d, Texturen %d, Texturbytes %d -> %s, "
          "Bundle-Bytes %d -> %d, %.1f s%s"
          % (changed, same, failed, tex, tex_before, tex_after if tex_after else "?", before, after,
             time.time() - t0, " (Probelauf)" if dry else ""))
    return 4 if failed else 0


def _psnr(a, b):
    se = 0
    n = len(a)
    # nur RGB-Kanäle und A gemeinsam; effizient über memoryview-Differenzen
    import array
    da = array.array("B", a)
    db = array.array("B", b)
    se = sum((x - y) * (x - y) for x, y in zip(da, db))
    if se == 0:
        return 99.0
    return 10 * math.log10(255.0 * 255.0 * n / se)


def cmd_psnr(src, dst, samples):
    """PSNR (Hauptstufe) je Textur: dekodierte BC-Quelle gegen dekodiertes ASTC des Ziels. Nur Zahlen."""
    import UnityPy
    es, ed = UnityPy.load(src), UnityPy.load(dst)
    b_src = {o.path_id: o for o in es.objects if o.type.name == "Texture2D"}
    pairs = []
    for o in ed.objects:
        if o.type.name == "Texture2D" and o.path_id in b_src:
            ts = b_src[o.path_id].read()
            if needs_transcode(int(ts.m_TextureFormat)) and int(ts.m_TextureFormat) in BC_FORMATS:
                pairs.append((ts, o.read()))
    pairs.sort(key=lambda p: p[0].object_reader.path_id)
    step = max(1, len(pairs) // samples)
    pairs = pairs[::step][:samples]
    rows = []
    for ts, td in pairs:
        fmt = int(ts.m_TextureFormat)
        w, h = ts.m_Width, ts.m_Height
        raw = bytes(ts.get_image_data())
        ref = decode_bc(fmt, raw[:bc_size(w, h, BC_FORMATS[fmt][1])], w, h)
        tid = int(td.m_TextureFormat)
        blk = next(k for k, v in ASTC_IDS.items() if v == tid)
        got = decode_astc_bgra(bytes(td.get_image_data()), w, h, blk, int(ts.m_ColorSpace) == 1)
        # ungenutzte Kanäle (BC4/BC5: B/A fest) zählen nicht
        p = _psnr(ref, got)
        rows.append((BC_FORMATS[fmt][0], "%dx%d" % (w, h), "%dx%d" % blk, p))
    for r in rows:
        print("%-5s %-9s ASTC %-5s PSNR %.2f dB" % r)
    if rows:
        ps = sorted(r[3] for r in rows)
        print("psnr: %d Texturen, Minimum %.2f, Median %.2f, Mittel %.2f, Maximum %.2f dB"
              % (len(ps), ps[0], ps[len(ps) // 2], sum(ps) / len(ps), ps[-1]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("info"); a.add_argument("file")
    for name in ("bundle", "tree", "psnr"):
        p = sub.add_parser(name)
        if name == "tree":
            p.add_argument("root"); p.add_argument("--list"); p.add_argument("--dry-run", action="store_true")
            p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
        else:
            p.add_argument("src"); p.add_argument("dst")
        if name == "psnr":
            p.add_argument("--samples", type=int, default=50)
        else:
            p.add_argument("--block", default="6x6"); p.add_argument("--block-data", default="4x4")
            p.add_argument("--quality", choices=sorted(QUALITIES), default="medium")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "info":
            if not os.path.isfile(args.file):
                return 3
            counts, other = inspect_bundle(args.file)
            for k, (n, b) in sorted(counts.items()):
                print("%-14s %5d Texturen %10d Byte" % (k, n, b))
            for k, n in other.items():
                print("%-14s %5d (nicht behandelt)" % (k, n))
            return 0
        if args.cmd == "psnr":
            return cmd_psnr(args.src, args.dst, args.samples)
        block, bd = parse_block(args.block), parse_block(args.block_data)
        if args.cmd == "bundle":
            if not os.path.isfile(args.src):
                return 3
            st = transcode_bundle(args.src, args.dst, block, bd, args.quality)
            if st is None:
                import shutil
                shutil.copyfile(args.src, args.dst)
                print("keine umzuwandelnden Texturen, kopiert")
            else:
                print(st)
            return 0
        if not os.path.isdir(args.root):
            return 3
        return cmd_tree(args.root, args.list, block, bd, args.quality, args.jobs, args.dry_run)
    except FileNotFoundError as e:
        print("FEHLER: %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
