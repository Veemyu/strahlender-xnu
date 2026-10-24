#!/usr/bin/env python3
"""Looks in the modules for signs of pointer tags / 39-bit assumptions (memory model B, docs/architecture.md).

Own code. Reads only the local dump (work/exefs) and writes to work/recomp/spike2/ptr_scan.json; only counters
are printed. Heuristic over 64-bit instructions (counting only, no statement about semantics):
  and_ptrmask   AND (imm) with mask 2^k-1, 39 <= k <= 63 (truncate the pointer width)
  and_lowmask   AND (imm) with mask 2^k-1, 32 <= k <= 38 (truncate to 32-39 bits)
  or_hightag    ORR (imm) with a bit >= 40 set (set a tag), eor_hightag: EOR (imm) likewise
  eor_allones   EOR (imm) with mask 0xFFFF...F (Boehm: GC_HIDE_POINTER and similar obfuscations)
  shift_high    LSR/ASR/UBFX/SBFX from bit >= 40 (read tag/high bits)
  lsl_high      LSL by >= 40
  movk_high     MOVK/MOVZ/MOVN with halfword 2 or 3 and value != 0/0xFFFF (high constants, e.g. tags)
  ldr_sxtw      LDRSW (hint at 32-bit values that are extended to 64 bits)
"""
import json
import os
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") != "1":
    sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.path.insert(0, str(ROOT / "research" / "LASRecomp" / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.dont_write_bytecode = True
from lifter import decode_bit_masks  # noqa: E402
import recomp_survey as rs  # noqa: E402

OUT = ROOT / "work" / "recomp" / "spike2"


def scan(name):
    n = rs.Nso(rs.EXEFS / name)
    code = n.text_bytes()
    words = struct.unpack(f"<{len(code) // 4}I", code)
    c = Counter()
    cache = {}
    for w in words:
        top = w & 0xFF800000
        if top in (0x92000000, 0xB2000000, 0xD2000000):  # AND/ORR/EOR (imm), sf=1
            nbit, immr, imms = (w >> 22) & 1, (w >> 16) & 63, (w >> 10) & 63
            key = (nbit, imms, immr)
            if key not in cache:
                try:
                    cache[key] = decode_bit_masks(nbit, imms, immr, 64, True)[0]
                except Exception:
                    cache[key] = None
            m = cache[key]
            if m is None:
                continue
            if top == 0x92000000:
                if m & (m + 1) == 0 and m != 0:
                    k = m.bit_length()
                    if 39 <= k < 64:
                        c["and_ptrmask"] += 1
                    elif 32 <= k <= 38:
                        c["and_lowmask"] += 1
            elif m >> 40:
                c["or_hightag" if top == 0xB2000000 else "eor_hightag"] += 1
            if top == 0xD2000000 and m == 0xFFFFFFFFFFFFFFFF:
                c["eor_allones"] += 1
        elif (w & 0xFF800000) in (0xD3000000, 0x93000000) and (w >> 22) & 1:  # UBFM/SBFM 64-bit
            immr, imms = (w >> 16) & 63, (w >> 10) & 63
            if imms >= immr and immr >= 40:
                c["shift_high"] += 1
            elif imms != 63 and imms + 1 == immr and 64 - immr >= 40:
                c["lsl_high"] += 1
        elif (w & 0x7F800000) in (0x72800000, 0x52800000, 0x12800000) and (w >> 31):  # MOVK/MOVZ/MOVN 64-bit
            hw = (w >> 21) & 3
            imm = (w >> 5) & 0xFFFF
            if hw >= 2 and imm not in (0, 0xFFFF):
                c["movk_high"] += 1
        elif (w & 0xFFC00000) == 0xB9800000 or (w & 0xFFE00C00) == 0xB8A00800:  # LDRSW (imm, reg)
            c["ldr_sxtw"] += 1
    return {"instructions": len(words), **dict(c)}


def main():
    res = {m: scan(m) for m in (sys.argv[1:] or ("main", "sdk", "subsdk0"))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ptr_scan.json").write_text(json.dumps(res, indent=1))
    for m, r in res.items():
        print(m, r)


if __name__ == "__main__":
    main()
