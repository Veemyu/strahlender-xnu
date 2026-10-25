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
    from lifter import Insn, Lifter, Unsupported, hx, X, XS, set_reg
    import ast
    # Execute the frozen EH override verbatim rather than duplicating its algorithm.
    tree = ast.parse((args.reference / "scripts/recomp/eh_gen.py").read_text())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "excl_pair")
    scope = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "frozen-excl-pair", "exec"), scope)
    excl_pair = scope["excl_pair"]
    lifter = Lifter(0, args.simd)
    for line in sys.stdin:
        if not line.strip():
            continue
        word = int(line, 16)
        try:
            ins = Insn("op", excl_pair(word)) if word & 0xbfa00000 == 0x88200000 else lifter.lift(word, args.pc)
        except Unsupported as error:
            ins = Insn("trap", f"rt_udf(c, {hx(args.pc)}); /* {error} */")
        if ins.kind == "ret":
            rn = word >> 5 & 31
            if rn != 30:
                ins = Insn("br", target=f"c->x[{rn}]")
            elif args.previous_word is not None and args.previous_word & 0xfffffc1f == 0x9100001f:
                ins = Insn("br", target="c->x[30]")
        record = {"handled": True, "kind": ins.kind, "code": ins.code, "target": ins.target, "cond": ins.cond}
        if ins.asm is not None:
            a = ins.asm
            record["asm"] = {"word": a.word, "vregs": sorted(a.vregs), "gprs": a.gprs,
                             "flags": a.flags, "consts": a.consts}
        print(json.dumps(record))


if __name__ == "__main__":
    main()
