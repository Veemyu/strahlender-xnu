#!/usr/bin/env python3
"""Mini linker for the exception spike: ELF64 relocatable (aarch64) -> synthetic NSO + flat memory image.

Own code, only for synthetic test programs (no game code). There is no aarch64 linker (no lld)
on the Mac; this linker places all sections with SHF_ALLOC one after another, applies the relocations,
generates `.eh_frame_hdr` including the search table (like `ld --eh-frame-hdr`) and writes:

  <out>.nso   NSO0 file (uncompressed, MOD0 with eh_frame_hdr), readable by scripts/recomp/upstream/generator/nso.py
  <out>.img   flat memory image (module base 0), with the relocations already applied
  <out>.json  symbols (name -> offset), sections, header/hdr location

External symbols are resolved against --syms (JSON {name: absolute address}), e.g. against the exports of the
SDK module at its guest base.

Usage: mini_link.py <object.o> <output-prefix> --base 0x7008000000 --syms syms.json
"""
import argparse
import json
import struct
import sys
from pathlib import Path

SHF_WRITE, SHF_ALLOC, SHF_EXEC = 1, 2, 4
SHT_SYMTAB, SHT_RELA, SHT_NOBITS = 2, 4, 8
PAGE = 0x1000


def align(v, a):
    return (v + a - 1) & ~(a - 1)


class Elf:
    def __init__(self, path):
        d = self.d = Path(path).read_bytes()
        assert d[:4] == b"\x7fELF" and d[4] == 2 and struct.unpack_from("<H", d, 0x12)[0] == 183, "not an aarch64 ELF64"
        shoff = struct.unpack_from("<Q", d, 0x28)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", d, 0x3A)
        self.sec = []
        for i in range(shnum):
            name, typ, flags, addr, off, size, link, info, al, ent = struct.unpack_from("<IIQQQQIIQQ", d, shoff + i * shentsize)
            self.sec.append(dict(name=name, type=typ, flags=flags, off=off, size=size, link=link, info=info, align=max(al, 1), ent=ent, idx=i))
        stro = self.sec[shstrndx]["off"]
        for s in self.sec:
            s["name"] = self.cstr(stro + s["name"])
        for s in self.sec:
            if s["type"] == SHT_SYMTAB:
                self.symtab = s
        self.strtab = self.sec[self.symtab["link"]]["off"]
        self.syms = []
        for i in range(self.symtab["size"] // 24):
            nm, info, other, shndx, val, size = struct.unpack_from("<IBBHQQ", d, self.symtab["off"] + i * 24)
            self.syms.append(dict(name=self.cstr(self.strtab + nm), info=info, shndx=shndx, value=val, size=size))

    def cstr(self, o):
        e = self.d.index(b"\0", o)
        return self.d[o:e].decode()

    def data(self, s):
        return bytearray(self.d[s["off"]:s["off"] + s["size"]]) if s["type"] != SHT_NOBITS else bytearray(s["size"])


def link(obj, base, ext):
    e = Elf(obj)
    alloc = [s for s in e.sec if s["flags"] & SHF_ALLOC and s["size"] and not s["name"].startswith(".rela")]
    text = [s for s in alloc if s["flags"] & SHF_EXEC]
    other = [s for s in alloc if not s["flags"] & SHF_EXEC]
    pos = 0x10  # Kopf: 4 Byte Nop, 4 Byte MOD0-Offset
    for s in text:
        pos = align(pos, s["align"])
        s["addr"] = pos
        pos += s["size"]
    text_end = pos
    pos = align(pos, PAGE)
    ro_start = pos
    other.sort(key=lambda s: s["name"] == ".eh_frame")  # eh_frame zuletzt, hdr direkt dahinter
    for s in other:
        pos = align(pos, s["align"])
        s["addr"] = pos
        pos += s["size"]
    eh = next((s for s in other if s["name"] == ".eh_frame"), None)
    image = bytearray(align(pos + 0x2000, PAGE))
    for s in alloc:
        image[s["addr"]:s["addr"] + s["size"]] = e.data(s)

    def sym_addr(i):
        sy = e.syms[i]
        if sy["shndx"] == 0:
            if sy["name"] not in ext:
                raise SystemExit(f"unresolved symbol {sy['name']}")
            return ext[sy["name"]] - base  # relative to the module base
        if sy["shndx"] >= 0xFF00:
            raise SystemExit("Common/ABS symbols not supported")
        s = e.sec[sy["shndx"]]
        return s["addr"] + sy["value"]

    for rs in e.sec:
        if rs["type"] != SHT_RELA:
            continue
        tgt = e.sec[rs["info"]]
        if "addr" not in tgt:
            continue
        for k in range(rs["size"] // 24):
            off, info, add = struct.unpack_from("<QQq", e.d, rs["off"] + k * 24)
            typ, si = info & 0xFFFFFFFF, info >> 32
            P = tgt["addr"] + off
            S = sym_addr(si) + add
            w = struct.unpack_from("<I", image, P)[0] if typ not in (257, 260) else 0
            if typ == 257:
                struct.pack_into("<Q", image, P, (S + base) & (2**64 - 1))
            elif typ == 261:
                struct.pack_into("<i", image, P, S - P)
            elif typ == 260:
                struct.pack_into("<q", image, P, S - P)
            elif typ in (282, 283):
                v = (S - P) >> 2
                assert -(1 << 25) <= v < (1 << 25), "Sprungweite"
                struct.pack_into("<I", image, P, (w & 0xFC000000) | (v & 0x3FFFFFF))
            elif typ in (275, 276):
                v = (S >> 12) - (P >> 12)
                assert -(1 << 20) <= v < (1 << 20), "ADRP-Weite"
                struct.pack_into("<I", image, P, (w & 0x9F00001F) | ((v & 3) << 29) | (((v >> 2) & 0x7FFFF) << 5))
            elif typ == 274:
                v = S - P
                struct.pack_into("<I", image, P, (w & 0x9F00001F) | ((v & 3) << 29) | (((v >> 2) & 0x7FFFF) << 5))
            elif typ == 277:
                struct.pack_into("<I", image, P, (w & 0xFFC003FF) | ((S & 0xFFF) << 10))
            elif typ in (278, 284, 285, 286, 299):
                sh = {278: 0, 284: 1, 285: 2, 286: 3, 299: 4}[typ]
                struct.pack_into("<I", image, P, (w & 0xFFC003FF) | (((S & 0xFFF) >> sh) << 10))
            elif typ in (280, 273):
                v = (S - P) >> 2
                struct.pack_into("<I", image, P, (w & 0xFF00001F) | ((v & 0x7FFFF) << 5))
            elif typ == 279:
                v = (S - P) >> 2
                struct.pack_into("<I", image, P, (w & 0xFFF8001F) | ((v & 0x3FFF) << 5))
            else:
                raise SystemExit(f"relocation type {typ} not supported")

    fdes = []
    hdr_addr = pos
    hdr_end = pos
    if eh:
        a, end = eh["addr"], eh["addr"] + eh["size"]
        while a < end:
            ln = struct.unpack_from("<I", image, a)[0]
            if ln == 0:
                break
            cid = struct.unpack_from("<I", image, a + 4)[0]
            if cid != 0:
                pcrel = struct.unpack_from("<i", image, a + 8)[0]
                fdes.append((a + 8 + pcrel, a))
            a += 4 + ln
        fdes.sort()
        hdr_addr = align(end + 4, 8)  # 4 Byte Nullterminator hinter .eh_frame
        hdr = struct.pack("<BBBB", 1, 0x1B, 0x03, 0x3B)
        hdr += struct.pack("<i", eh["addr"] - (hdr_addr + 4))
        hdr += struct.pack("<I", len(fdes))
        for start, fa in fdes:
            hdr += struct.pack("<ii", start - hdr_addr, fa - hdr_addr)
        image[hdr_addr:hdr_addr + len(hdr)] = hdr
        hdr_end = hdr_addr + len(hdr)
    mod0 = align(hdr_end, 8)
    dyn = mod0 + 0x40
    struct.pack_into("<4siiiiii", image, mod0, b"MOD0", dyn - mod0, 0, 0, hdr_addr - mod0, hdr_end - mod0, 0)
    struct.pack_into("<I", image, 4, mod0)
    struct.pack_into("<I", image, 0, 0xD503201F)
    ro_end = align(dyn + 16, PAGE)
    syms = {sy["name"]: sym_addr(i) for i, sy in enumerate(e.syms)
            if sy["shndx"] and sy["shndx"] < 0xFF00 and sy["name"] and (sy["info"] & 0xF) in (0, 1, 2)
            and "addr" in e.sec[sy["shndx"]]}
    return dict(image=image[:ro_end + 0x1000], text=(0, align(text_end, PAGE)), ro=(ro_start, ro_end - ro_start),
                mod0=mod0, hdr=(hdr_addr, hdr_end - hdr_addr), syms=syms, fdes=len(fdes))


def write_nso(path, r):
    img = r["image"]
    t_end = r["text"][1]
    ro_off, ro_len = r["ro"]
    segs = [(0, img[0:t_end]), (ro_off, img[ro_off:ro_off + ro_len]), (ro_off + ro_len, img[ro_off + ro_len:ro_off + ro_len + 0x1000])]
    hdr = bytearray(0x100)
    struct.pack_into("<4sIII", hdr, 0, b"NSO0", 0, 0, 0)  # flags = 0: unkomprimiert
    f = 0x100
    for i, (mem, data) in enumerate(segs):
        struct.pack_into("<IIII", hdr, 0x10 + 16 * i, f, mem, len(data), 0)
        struct.pack_into("<I", hdr, 0x60 + 4 * i, len(data))
        f += len(data)
    struct.pack_into("<I", hdr, 0x3C, 0x1000)
    Path(path).write_bytes(bytes(hdr) + b"".join(bytes(d) for _, d in segs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj")
    ap.add_argument("out")
    ap.add_argument("--base", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--syms", required=True)
    a = ap.parse_args()
    ext = json.loads(Path(a.syms).read_text())
    r = link(a.obj, a.base, ext)
    write_nso(a.out + ".nso", r)
    Path(a.out + ".img").write_bytes(bytes(r["image"]))
    meta = {k: v for k, v in r.items() if k != "image"}
    Path(a.out + ".json").write_text(json.dumps(meta, indent=1))
    print(f"{a.out}: image {len(r['image'])} bytes, text {r['text']}, FDEs {r['fdes']}, symbols {len(r['syms'])}")


if __name__ == "__main__":
    sys.exit(main() or 0)
