#!/usr/bin/env python3
"""Development oracle for native instruction IR; loads the frozen Git snapshot."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--pc", required=True, type=lambda s: int(s, 0))
    parser.add_argument("--simd", choices=("asm", "c"), default="asm")
    parser.add_argument("--previous-word", type=lambda s: int(s, 0))
    args = parser.parse_args()
    sys.path.insert(0, str(args.reference / "scripts/recomp/upstream/generator"))
    from lifter import Insn, Lifter, Unsupported, hx
    lifter = Lifter(0, args.simd)
    for line in sys.stdin:
        if not line.strip():
            continue
        word = int(line, 16)
        try:
            ins = lifter.lift(word, args.pc)
        except Unsupported as error:
            ins = Insn("trap", f"rt_udf(c, {hx(args.pc)}); /* {error} */")
        if ins.kind == "ret":
            rn = word >> 5 & 31
            if rn != 30:
                ins = Insn("br", target=f"c->x[{rn}]")
            elif args.previous_word is not None and args.previous_word & 0xfffffc1f == 0x9100001f:
                ins = Insn("br", target="c->x[30]")
        print(json.dumps({"handled": True, "kind": ins.kind, "code": ins.code,
                          "target": ins.target, "cond": ins.cond}))


if __name__ == "__main__":
    main()
