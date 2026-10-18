#!/usr/bin/env python3
"""Inventar von work/romfs/Data/StreamingAssets (nur lesend, nur Header).

Gibt einen Textbericht auf stdout aus: Ordnerstatistik, UnityFS-Header,
Wwise-Bank-Versionen, WebM-Codecs. Nur Standardbibliothek.
Aufruf: scripts/data_inventory.py [--root PFAD]
"""
import argparse
import collections
import lzma
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "work/romfs/Data/StreamingAssets"
KOMPRESSION = {0: "keine", 1: "LZMA", 2: "LZ4", 3: "LZ4HC"}
GROESSEN = [(1 << 10, "<1 KiB"), (1 << 12, "1-4 KiB"), (1 << 14, "4-16 KiB"),
            (1 << 16, "16-64 KiB"), (1 << 18, "64-256 KiB"), (1 << 20, "256 KiB-1 MiB"),
            (1 << 22, "1-4 MiB"), (1 << 24, "4-16 MiB"), (1 << 26, "16-64 MiB"),
            (1 << 62, ">=64 MiB")]


def mib(n):
    return f"{n / 1048576:.1f} MiB"


def alle_dateien(basis):
    for r, _, fs in os.walk(basis):
        for n in sorted(fs):
            if n != ".DS_Store":
                yield Path(r) / n


def dateityp(p):
    return p.suffix.lower().lstrip(".") or "(ohne)"


def lz4_block(data, out_size):
    """Minimaler LZ4-Blockdekoder (nur fuer die kleine Blockinfo-Tabelle)."""
    out = bytearray()
    i = 0
    while i < len(data):
        tok = data[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = data[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += data[i:i + lit]
        i += lit
        if i >= len(data):
            break
        off = data[i] | (data[i + 1] << 8)
        i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = data[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        for _ in range(ml):
            out.append(out[-off])
    return bytes(out[:out_size])


def cstr(f):
    b = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b"\0":
            return b.decode("ascii", "replace")
        b += c


def unityfs_header(path):
    """Liest Header und (kleine) Blockinfo-Tabelle. Gibt dict oder None."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if f.read(8) != b"UnityFS\0":
            return None
        ver = struct.unpack(">I", f.read(4))[0]
        plugin = cstr(f)
        rev = cstr(f)
        total, csz, usz, flags = struct.unpack(">QIII", f.read(20))
        h = dict(datei=size, version=ver, plugin=plugin, revision=rev,
                 total=total, flags=flags, info_komp=KOMPRESSION.get(flags & 0x3F, "?"))
        # Flag 0x80: Blockinfo am Dateiende; sonst direkt nach dem Header (ab v7 16-Byte-ausgerichtet)
        ende = bool(flags & 0x80)
        h["info_am_ende"] = ende
        if ende:
            f.seek(size - csz)
        else:
            if ver >= 7:
                f.seek((f.tell() + 15) // 16 * 16)
        raw = f.read(csz)
    kind = flags & 0x3F
    try:
        if kind == 0:
            info = raw
        elif kind == 1:
            props = raw[:5]
            dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[_lzma_filter(props)])
            info = dec.decompress(raw[5:], usz)
        else:
            info = lz4_block(raw, usz)
        n = struct.unpack(">i", info[16:20])[0]
        blocks = []
        p = 20
        for _ in range(n):
            u, c, fl = struct.unpack(">IIH", info[p:p + 10])
            blocks.append((u, c, fl))
            p += 10
        nn = struct.unpack(">i", info[p:p + 4])[0]
        h["bloecke"] = blocks
        h["knoten"] = nn
    except Exception as e:  # Blockinfo nicht lesbar
        h["fehler"] = repr(e)
    return h


def _lzma_filter(props):
    d = props[0]
    lc, rest = d % 9, d // 9
    lp, pb = rest % 5, rest // 5
    dict_size = struct.unpack("<I", props[1:5])[0]
    return {"id": lzma.FILTER_LZMA1, "dict_size": dict_size, "lc": lc, "lp": lp, "pb": pb}


def abschnitt(titel):
    print(f"\n## {titel}\n")


def ordner_statistik(root):
    abschnitt("1. Verzeichnisstruktur")
    for top in sorted(p for p in root.iterdir() if p.is_dir()):
        files = list(alle_dateien(top))
        typen = collections.Counter(dateityp(p) for p in files)
        print(f"{top.name}: {len(files)} Dateien, {mib(sum(p.stat().st_size for p in files))}, "
              f"Typen: {dict(typen.most_common())}")
        subs = sorted(p for p in top.iterdir() if p.is_dir())
        for s in subs:
            fs = list(alle_dateien(s))
            t = collections.Counter(dateityp(p) for p in fs)
            print(f"  {s.name}: {len(fs)} Dateien, {mib(sum(p.stat().st_size for p in fs))}, "
                  f"Typen: {dict(t.most_common())}")
        lose = [p for p in top.iterdir() if p.is_file() and p.name != ".DS_Store"]
        for p in lose:
            print(f"  (Datei direkt im Ordner) {p.name}: {p.stat().st_size} Bytes")


def bundles(root):
    abschnitt("2. UnityFS-Bundles")
    basis = root / "AssetAssistant"
    liste = []
    fremd = []
    for p in alle_dateien(basis):
        h = unityfs_header(p)
        if h:
            liste.append((p, h))
        else:
            fremd.append(p)
    print(f"Bundles: {len(liste)}, gesamt {mib(sum(h['datei'] for _, h in liste))}; "
          f"keine UnityFS-Dateien: {[str(p.relative_to(basis)) for p in fremd]}")
    print("Format-Version:", dict(collections.Counter(h["version"] for _, h in liste)))
    print("Unity-Version (Plugin):", dict(collections.Counter(h["plugin"] for _, h in liste)))
    print("Unity-Revision:", dict(collections.Counter(h["revision"] for _, h in liste)))
    print("Blockinfo-Kompression:", dict(collections.Counter(h["info_komp"] for _, h in liste)))
    print("Blockinfo am Ende:", dict(collections.Counter(h["info_am_ende"] for _, h in liste)))
    print("Flags:", {hex(k): v for k, v in collections.Counter(h["flags"] for _, h in liste).items()})
    print("Header-total == Dateigroesse:", sum(h["total"] == h["datei"] for _, h in liste), "von", len(liste))
    print("Blockinfo-Fehler:", sum("fehler" in h for _, h in liste))
    dk = collections.Counter()
    nb = collections.Counter()
    kn = collections.Counter()
    for _, h in liste:
        for u, c, fl in h.get("bloecke", []):
            dk[KOMPRESSION.get(fl & 0x3F, "?")] += 1
        nb[min(len(h.get("bloecke", [])), 10)] += 1
        kn[min(h.get("knoten", 0), 10)] += 1
    print("Datenblock-Kompression (Anzahl Bloecke):", dict(dk))
    print("Bloecke pro Bundle (10 = >=10):", dict(sorted(nb.items())))
    print("Knoten (Dateien) pro Bundle (10 = >=10):", dict(sorted(kn.items())))
    gv = collections.Counter()
    for _, h in liste:
        for lim, name in GROESSEN:
            if h["datei"] < lim:
                gv[name] += 1
                break
    print("\nGroessenverteilung:")
    for _, name in GROESSEN:
        print(f"  {name}: {gv[name]}")
    gs = sorted(h["datei"] for _, h in liste)
    print(f"Min {gs[0]} B, Median {gs[len(gs) // 2]} B, Max {mib(gs[-1])}")
    print("\nTop-Ordner (Bundles, Groesse):")
    pro = collections.defaultdict(lambda: [0, 0])
    for p, h in liste:
        k = p.relative_to(basis).parts[0]
        pro[k][0] += 1
        pro[k][1] += h["datei"]
    for k, (n, s) in sorted(pro.items(), key=lambda x: -x[1][1]):
        print(f"  {k}: {n} Bundles, {mib(s)}")
    print("\nStichprobe (Quantile 5 %, 15 %, 25 % der Groessenreihenfolge):")
    ordnung = sorted(liste, key=lambda x: (x[1]["datei"], str(x[0])))
    for q in (0.05, 0.15, 0.25):
        p, h = ordnung[int(len(ordnung) * q)]
        print(f"  {p.relative_to(basis)}: {h['datei']} B, Knoten {h.get('knoten')}, "
              f"Bloecke {[(u, c, KOMPRESSION.get(fl & 0x3F, '?')) for u, c, fl in h.get('bloecke', [])]}")
    print("\nBundles mit Stammdaten-Namen:")
    for p, h in liste:
        n = str(p.relative_to(basis)).lower()
        if any(k in n for k in ("master", "message", "msbt", "personal", "table")):
            print(f"  {p.relative_to(basis)}: {h['datei']} B")


def audio(root):
    abschnitt("4. Audio")
    a = root / "Audio"
    fs = list(alle_dateien(a))
    for ext in ("bnk", "wem"):
        sel = [p for p in fs if dateityp(p) == ext]
        print(f"{ext}: {len(sel)} Dateien, {mib(sum(p.stat().st_size for p in sel))}")
    sonst = [p.name for p in fs if dateityp(p) not in ("bnk", "wem")]
    print("Sonstige:", sonst)
    vers = collections.Counter()
    kein = 0
    for p in fs:
        if dateityp(p) != "bnk":
            continue
        with open(p, "rb") as f:
            d = f.read(16)
        if d[:4] == b"BKHD":
            vers[struct.unpack("<I", d[8:12])[0]] += 1
        else:
            kein += 1
    print("BKHD-Version (Anzahl Banks):", dict(vers), "ohne BKHD:", kein)
    codec = collections.Counter()
    for p in fs:
        if dateityp(p) != "wem":
            continue
        with open(p, "rb") as f:
            d = f.read(24)
        if d[:4] in (b"RIFF", b"RIFX") and d[8:12] == b"WAVE" and d[12:16] == b"fmt ":
            codec[hex(struct.unpack("<H", d[20:22])[0])] += 1
        else:
            codec["kein RIFF/WAVE"] += 1
    print("WEM fmt-Codec-Tag (0xffff=Vorbis, 0x3039=Opus, 0x2/0x11=ADPCM, 0xfffe=Extensible):", dict(codec))
    gs = sorted(p.stat().st_size for p in fs if dateityp(p) == "bnk")
    if gs:
        print(f"Bank-Groessen: Min {gs[0]} B, Median {gs[len(gs) // 2]} B, Max {mib(gs[-1])}")


def movie(root):
    abschnitt("5. Movie")
    for p in alle_dateien(root / "Movie"):
        with open(p, "rb") as f:
            d = f.read(1 << 16)
        ebml = d[:4] == b"\x1a\x45\xdf\xa3"
        marker = [m.decode() for m in (b"V_VP8", b"V_VP9", b"V_AV1", b"V_MPEG4", b"A_VORBIS", b"A_OPUS", b"A_AAC")
                  if m in d]
        doc = "webm" if b"webm" in d[:64] else ("matroska" if b"matroska" in d[:64] else "?")
        print(f"{p.relative_to(root / 'Movie')}: {p.stat().st_size} B, EBML={ebml}, DocType={doc}, Codecs={marker}")


def sprachen(root):
    abschnitt("6. Sprachen")
    m = root / "AssetAssistant/Message"
    print("Message-Eintraege:", sorted(p.name for p in m.iterdir() if p.name != ".DS_Store"))
    kuerzel = collections.Counter()
    for p in alle_dateien(root / "Movie"):
        parts = p.stem.split("_")
        if len(parts) > 2 and parts[2] not in ("op", "ed") and p.name.startswith("movie_dia_"):
            kuerzel[parts[2]] += 1
    print("Movie-Sprachkuerzel (Dateien):", dict(sorted(kuerzel.items())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args()
    ordner_statistik(a.root)
    bundles(a.root)
    audio(a.root)
    movie(a.root)
    sprachen(a.root)


if __name__ == "__main__":
    main()
