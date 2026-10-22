#!/usr/bin/env python3
"""Histogram of the FP/SIMD instructions in the text of the NSO modules (docs/recomp-diff.md, section 1).

Own code. Reads work/exefs/{main,sdk,subsdk0,rtld} (local, none of it in the repo), decodes every
32-bit word of the text segment with Capstone and counts mnemonics per module. Additionally: MRS/MSR on FPCR/FPSR
(words directly by mask) and the FPCR write values, as far as they appear as a `mov` constant before.
Output: work/recomp/diff/hist.json (mnemonic -> counter per module) and a text summary.

Usage: hist.py [--exefs work/exefs] [--out work/recomp/diff/hist.json]
"""
import argparse
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.path.insert(0, str(ROOT / "research" / "LASRecomp" / "tools"))
sys.dont_write_bytecode = True
import capstone  # noqa: E402
from nso import Nso  # noqa: E402

# MSR/MRS (register) with o0=1 op1=3 CRn=4: FPCR = CRm 4 op2 0, FPSR = CRm 4 op2 1
MRS_FPCR, MRS_FPSR = 0xD53B4400, 0xD53B4420
MSR_FPCR, MSR_FPSR = 0xD51B4400, 0xD51B4420


REG = re.compile(r"\b([vqdshbwx])(\d+)\b")
IMM = re.compile(r"#-?(0x[0-9a-f]+|\d+(\.\d+)?|[0-9.e+-]+)")


def shape(mn, ops):
    """Mnemonic + operands without register numbers and constants (arrangement/width stays)."""
    return mn + " " + IMM.sub("#", REG.sub(lambda m: m.group(1) + "N", ops))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exefs", default=str(ROOT / "work" / "exefs"))
    ap.add_argument("--out", default=str(ROOT / "work" / "recomp" / "diff" / "hist.json"))
    a = ap.parse_args()
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = False
    res, sysregs, total, shapes = {}, {}, {}, {}
    for mod in ("main", "sdk", "subsdk0", "rtld"):
        n = Nso(Path(a.exefs) / mod)
        off, size = n.text
        text = bytes(n.image[off:off + size])
        words = struct.unpack("<%dI" % (size // 4), text)
        total[mod] = len(words)
        cnt = Counter()
        shp = Counter()
        sr = Counter()
        for i, w in enumerate(words):
            m = w & 0xFFFFFFE0
            if m == MRS_FPCR:
                sr["mrs fpcr"] += 1
            elif m == MRS_FPSR:
                sr["mrs fpsr"] += 1
            elif m == MSR_FPCR:
                sr["msr fpcr"] += 1
            elif m == MSR_FPSR:
                sr["msr fpsr"] += 1
        pos = 0
        undec = 0
        while pos < size:  # disasm_lite stops at the first invalid encoding
            chunk = text[pos:pos + (1 << 20)]
            k = 0
            for ins in md.disasm_lite(chunk, pos):
                cnt[ins[2]] += 1
                ww = words[ins[0] >> 2]
                # FP/SIMD data processing (bits 27:25 = 111) or FP/SIMD load/store (V=1, bit 27 = 1, bit 25 = 0)
                if (ww >> 25) & 7 == 7 or ((ww >> 26) & 1 and (ww >> 27) & 1 and not (ww >> 25) & 1):
                    shp[shape(ins[2], ins[3])] += 1
                k += 1
            pos += k * 4
            if pos < size and k * 4 < len(chunk):
                undec += 1
                pos += 4
        cnt["<undecoded>"] = undec
        res[mod] = cnt
        shapes[mod] = shp
        sysregs[mod] = sr
        print(mod, len(words), "words,", len(cnt), "mnemonics", dict(sr), file=sys.stderr, flush=True)
    out = {"words": total, "mnemonics": {m: dict(c) for m, c in res.items()}, "sysregs": {m: dict(c) for m, c in sysregs.items()},
           "shapes": {m: dict(c) for m, c in shapes.items()}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, sort_keys=True))
    print("total", sum(total.values()), "words ->", a.out)


if __name__ == "__main__":
    main()
