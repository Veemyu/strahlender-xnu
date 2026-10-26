#!/usr/bin/env python3
"""Picks real LSDA functions from `main` for the throw test (docs/architecture.md, section exceptions).

Own code. Reads the local dump (work/exefs/main, relocated image work/recomp/spike2/main.img from the native image command)
and writes only to work/recomp/spike2/:
  real_only.txt   function starts (hex, relative to the module base) for `codegen.sh gen ... --only`
  real_spec.txt   check job per function for the test run: start, type info for the throw, call sites with landing pad

Selection: small to medium functions (24 to 400 instructions) with at least one landing pad and one call,
the same number per kind (cleanup only / typed catch / catch(...)), reproducible (seed).
"""
import argparse
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import eh_lsda  # noqa: E402

OUT = eh_lsda.OUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x7040000000)
    ap.add_argument("--img", default=str(OUT / "main.img"))
    ap.add_argument("--per-kind", type=int, default=15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--module", default="main")
    a = ap.parse_args()
    n, nimg, hdr = eh_lsda.load_module(a.module)
    img = bytearray(Path(a.img).read_bytes())
    fdes = eh_lsda.parse_module(nimg, hdr)
    text_lo, text_len = n.seg["text"]
    words = struct.unpack(f"<{text_len // 4}I", bytes(nimg[text_lo:text_lo + text_len]))
    cand = {"cleanup": [], "catch_typed": [], "catch_all": []}
    for f in fdes:
        if not f["lsda"] or not 24 * 4 <= f["size"] <= 400 * 4 or not any(lp for _, _, lp, _ in f["sites"]):
            continue
        first = (f["start"] - text_lo) // 4
        ins = words[first:first + f["size"] // 4]
        if not any((w & 0xFC000000) == 0x94000000 or (w & 0xFFFFFC1F) == 0xD63F0000 for w in ins):
            continue
        k = eh_lsda.classify(nimg, f)
        if k.get("catch_typed"):
            cand["catch_typed"].append(f)
        elif k.get("catch_all"):
            cand["catch_all"].append(f)
        elif k.get("cleanup"):
            cand["cleanup"].append(f)
    rnd = random.Random(a.seed)
    picked = []
    for kind, lst in cand.items():
        rnd.shuffle(lst)
        picked += [(kind, f) for f in lst[:a.per_kind]]
    lines, only = [], []
    for kind, f in picked:
        info = f["lsda_info"]
        zti = 0
        if kind == "catch_typed":
            for (_, _, lp, act) in info["sites"]:
                if act:
                    chain = eh_lsda.action_chain(nimg, info, act)
                    t = next((x for x in chain if x > 0), 0)
                    if t:
                        enc = info["tt_enc"]
                        ea = info["tt_end"] - t * 4
                        raw = struct.unpack_from("<i", nimg, ea)[0]
                        if raw:
                            ref = ea + raw if enc & 0x10 else raw
                            zti = struct.unpack_from("<Q", img, ref)[0] if enc & 0x80 else a.base + ref
                    break
        sites = [(a.base + s, ln, (a.base + lp) if lp else 0) for (s, ln, lp, act) in f["sites"] if lp]
        lines.append(" ".join([kind, hex(a.base + f["start"]), hex(zti), str(len(sites))] +
                              [f"{s:#x} {s + ln:#x} {lp:#x}" for s, ln, lp in sites]))
        only.append(f"{f['start']:x}")
    (OUT / "real_spec.txt").write_text("\n".join(lines) + "\n")
    (OUT / "real_only.txt").write_text("\n".join(only) + "\n")
    print(f"{len(picked)} functions picked:", {k: min(len(v), a.per_kind) for k, v in cand.items()},
          "Kandidaten:", {k: len(v) for k, v in cand.items()})


if __name__ == "__main__":
    main()
