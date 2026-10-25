#!/usr/bin/env python3
"""Generator extension for C++ exceptions and setjmp/longjmp (phase 2 spike, docs/architecture.md).

Own code. The generator from scripts/recomp/upstream/generator (MIT, vendored unchanged)
is not modified, but extended here at run time:

* `EhModule` is a subclass of `gen.Module`. Every generated guest function that contains a re-entry point
  (landing pad from an LSDA or the spot behind a `bl setjmp`) gets, at the start, a
  frame entry (`EhRec` on the host stack, chained through `Cpu`) and a `__builtin_setjmp`. The entry is
  unhooked again whenever the function is left (return, tail call, dispatch).
* `rt_dispatch` gets the path `rt_nle_enter` for addresses in the middle of a function (not a function start):
  search the matching frame entry and jump back there via `__builtin_longjmp`; the
  function then dispatches to the label of the landing pad (`switch (c->pc)`).
* `ret` after `mov sp, xN` (libunwind `jumpto`) and `ret xN` with N != 30 become an indirect
  jump to the register target (the standard lifter turns them into a `return`).

Usage like `gen.py`:  eh_gen.py gen <name> <nso> <base> <output folder> [--chunk-bytes N] [--simd asm|c] [--limit N]
Additionally: --las-dir <folder with gen.py> (default scripts/recomp/upstream/generator).
"""
import atexit
from array import array
import bisect
import os
import re
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
if os.environ.get("BDSP_INSTALLER_PRIVATE_RUNTIME") != "1":
    sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

SETJMP_NAMES = {"setjmp", "_setjmp", "sigsetjmp", "__sigsetjmp"}
EXTRA_SETJMP = []
STATS = Counter()
TAIL = re.compile(r"__attribute__\(\(musttail\)\) return ([^;]+);")


def excl_pair(w):
    """C for LDXP/LDAXP (bit 22 = 1) and STXP/STLXP: helper functions from rt/cpu.h (address via GPTR)."""
    from lifter import X, XS, set_reg
    sz64 = (w >> 30) & 1
    load = (w >> 22) & 1
    rs, rt2, rn, rt = (w >> 16) & 31, (w >> 10) & 31, (w >> 5) & 31, w & 31
    n = 64 if sz64 else 32
    if load:
        return (f"{{ uint64_t ea = {XS(rn)}; uint64_t lo, hi; ldxp{n}(c, ea, GPTR(ea), &lo, &hi); "
                f"{set_reg(sz64, rt, 'lo')} {set_reg(sz64, rt2, 'hi')} }}")
    return (f"{{ uint64_t ea = {XS(rn)}; uint32_t st = stxp{n}(c, ea, GPTR(ea), {X(rt)}, {X(rt2)}); "
            f"{set_reg(0, rs, 'st')} }}")


def install(las_dir):
    sys.path.insert(0, str(Path(las_dir).resolve()))
    import gen
    from lifter import Insn
    import eh_lsda

    class EhModule(gen.Module):
        def __init__(self, name, path, base, simd="asm"):
            super().__init__(name, path, base, simd)
            # Compact instruction storage matters when spawn workers each load a module.
            self.words = array("I", self.words)
            n = self.nso
            img = n.image
            # Homebrew NSOs can have an empty unwind range whose relative
            # offsets both resolve to MOD0, rather than an .eh_frame_hdr.
            if n.eh_start == n.eh_end:
                n.eh_start = n.eh_end = 0
            self.no_unwind = not n.eh_start
            self.wide_tables = {}
            mod0 = struct.unpack_from("<I", img, 4)[0]
            hdr = mod0 + struct.unpack_from("<i", img, mod0 + 16)[0]
            fdes = eh_lsda.parse_module(img, hdr) if n.eh_start else []
            lps = set()
            for f in fdes:
                for (_, _, lp, _) in f["sites"]:
                    if lp:
                        lps.add(base + lp)
            self.lp_set = lps
            self.setjmp_set = self._find_setjmp_returns()
            self.nle = sorted(lps | self.setjmp_set)
            STATS["landing_pads"] += len(lps)
            STATS["setjmp_returns"] += len(self.setjmp_set)

        def _find_setjmp_returns(self):
            """Addresses behind `bl setjmp` (re-entry on longjmp): direct exports or PLT stubs to imports."""
            n, base = self.nso, self.base
            target_fns = {base + s[3] for s in n.syms if s[0] in SETJMP_NAMES and s[2]} | {base + o for o in EXTRA_SETJMP}
            slots = {}
            for off, typ, sym, add in n.relocs:
                if typ in (1025, 1026, 257) and sym and n.syms[sym][0] in SETJMP_NAMES:
                    slots[base + off] = n.syms[sym][0]
            stubs = set()
            if slots:
                words, lo = self.words, self.lo
                for i in range(len(words) - 2):
                    w = words[i]
                    if (w & 0x9F000000) == 0x90000000 and (words[i + 1] & 0xFFC00000) == 0xF9400000:
                        imm = ((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3)
                        if imm & (1 << 20):
                            imm -= 1 << 21
                        pc = lo + i * 4
                        slot = ((pc & ~0xFFF) + (imm << 12)) + ((words[i + 1] >> 10) & 0xFFF) * 8
                        if slot in slots:
                            stubs.add(pc)
            targets = target_fns | stubs
            res = set()
            if not targets:
                return res
            for i, w in enumerate(self.words):
                if (w & 0xFC000000) == 0x94000000:
                    t = self.lo + i * 4 + gen.sext26(w) * 4
                    if t in targets:
                        res.add(self.lo + i * 4 + 4)
            return res

        def lift(self, a):
            w0 = self.word(a)
            if (w0 & 0xBFA00000) == 0x88200000:  # LDXP/LDAXP/STXP/STLXP (standard lifter: not supported)
                STATS["excl_pair"] += 1
                return Insn("op", excl_pair(w0))
            ins = super().lift(a)
            if ins.kind == "ret":
                w = self.word(a)
                rn = (w >> 5) & 31
                if rn != 30:
                    STATS["ret_xN"] += 1
                    return Insn("br", target=f"c->x[{rn}]")
                if a - 4 >= self.lo and (self.word(a - 4) & 0xFFFFFC1F) == 0x9100001F:  # mov sp, xN ; ret
                    STATS["ret_after_mov_sp"] += 1
                    return Insn("br", target="c->x[30]")
            return ins

        def jump_table(self, br_pc, entry, end):
            targets = super().jump_table(br_pc, entry, end)
            if targets is None:
                # Tables can span partitions inferred from ADR targets. Keep
                # guard discovery bounded, but admit targets in other text blocks.
                if br_pc not in self.wide_tables:
                    context = max(self.lo, br_pc - 0x1000)
                    wide = self._jump_table_fallthrough(br_pc, context, self.hi)
                    if wide is None and self.no_unwind:
                        wide = super().jump_table(br_pc, context, self.hi)
                    self.wide_tables[br_pc] = wide
                targets = self.wide_tables[br_pc]
            return targets

        def scan(self, entry, end):
            labels, external, tables = super().scan(entry, end)
            for pc, targets in list(tables.items()):
                if targets == "all":
                    continue
                external.update(target for target in targets if not entry <= target < end)
                # Other partitions have their own dispatch entries. A local
                # switch must never emit a goto into another generated C function.
                tables[pc] = [target for target in targets if entry <= target < end] or "all"
            return {target for target in labels if entry <= target < end}, external, tables

        def emit_function(self, entry, end, labels, tables, hle):
            lo = bisect.bisect_left(self.nle, entry)
            hi = bisect.bisect_left(self.nle, end)
            pads = self.nle[lo:hi]
            if not pads or entry in hle:
                return super().emit_function(entry, end, labels, tables, hle)
            labels = set(labels) | set(pads)
            lines = super().emit_function(entry, end, labels, tables, hle)
            STATS["eh_functions"] += 1
            out, done = [], False
            for ln in lines:
                if not done and "FN_ENTER" in ln:
                    out.append(ln)
                    out.append(f"    EH_ENTER({gen.hx(entry)}, {gen.hx(end)});")
                    cases = " ".join(f"case {gen.hx(p)}: goto L_{p:x};" for p in pads)
                    out.append(f"    if (EH_SETJMP()) {{ switch (c->pc) {{ {cases} default: rt_nle_fatal(c); }} }}")
                    done = True
                    continue
                if ln.strip() == "return;":
                    ln = "    { EH_POP(); return; }"
                elif "musttail" in ln:
                    ln = TAIL.sub(lambda m: f"do {{ EH_POP(); __attribute__((musttail)) return {m.group(1)}; }} while (0);", ln)
                out.append(ln)
            return out

    gen.Module = EhModule
    gen.PATCHES.clear()
    gen.RANDO_CODE.clear()
    return gen


def is_jumptable_base_adr(words, i):
    """`adr xD, T` followed (<= 24 words) by `add xD, xD, xM, lsl n` and `br xD`: T is the base of a relative
    jump table (or the first case of a byte offset table, window 24 because of constant loads in between)
    within the same function, not a function start (the standard generator would otherwise cut the function at T)."""
    w = words[i]
    d = w & 31
    seen_add = False
    for k in range(i + 1, min(i + 25, len(words))):
        x = words[k]
        if (x & 0xFF200000) == 0x8B000000 and (x & 31) == d and ((x >> 5) & 31) == d:
            seen_add = True
        if x == (0xD61F0000 | (d << 5)):
            return seen_add
    return False


def generate(gen, args):
    """Discover EH-aware function boundaries, then scan and emit stable C chunks.

    ADR jump-table bases stay within their function. Independent work uses spawn
    processes; stateful jump-table emulation retains the serial reference order.
    """
    import time
    t0 = time.time()
    m = gen.Module(args.name, args.nso, args.base, args.simd)
    starts = m.boundaries()
    hle = {}
    if args.hle and os.path.exists(args.hle):
        want = {l.strip() for l in open(args.hle) if l.strip() and not l.startswith("#")}
        for name, info, shndx, value, size in m.nso.syms:
            if shndx and name in want:
                hle[args.base + value] = name
    start_set = set(starts)
    if args.entry_offsets:
        for offset in Path(args.entry_offsets).read_text().split():
            target = args.base + int(offset, 16)
            if target & 3 or not m.in_text(target):
                raise ValueError(f"Cross-module entry outside {args.name} text: {target:#x}")
            start_set.add(target)
    for i, w in enumerate(m.words):
        if (w & 0xFC000000) == 0x94000000:
            t = m.lo + i * 4 + gen.sext26(w) * 4
            if m.in_text(t):
                start_set.add(t)
    adrp_regs = {}
    for i, w in enumerate(m.words):
        pc = m.lo + i * 4
        if (w & 0x9F000000) == 0x10000000:  # ADR
            imm = ((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            if m.in_text(pc + imm):
                if is_jumptable_base_adr(m.words, i):
                    STATS["adr_jumptable_base_kept_inside"] += 1
                else:
                    start_set.add(pc + imm)
        elif (w & 0x9F000000) == 0x90000000:  # ADRP
            imm = ((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            adrp_regs[w & 31] = ((pc & ~0xFFF) + (imm << 12), i)
        elif (w & 0xFFC00000) == 0x91000000:  # ADD (imm)
            rn = (w >> 5) & 31
            if rn in adrp_regs and i - adrp_regs[rn][1] <= 8:
                t = adrp_regs[rn][0] + ((w >> 10) & 0xFFF)
                if m.in_text(t):
                    start_set.add(t)
    if args.jobs != "auto":
        jobs = int(args.jobs)
    else:
        from parallel_jobs import choose_jobs, cpu_count, memory_bytes
        jobs = choose_jobs(cpu_count(), memory_bytes())
    # Tiny modules do not amortize process startup. Modules stay sequential;
    # the CPU budget belongs to the currently active module.
    if args.jobs == "auto":
        jobs = min(jobs, max(1, (m.hi - m.lo) // 0x80000))
    workers = None
    print(f"{args.name}: generator workers {jobs}", file=sys.stderr, flush=True)
    if jobs > 1:
        from eh_parallel import Workers
        workers = Workers(jobs, args.las_dir, args, hle)
    try:
        return generate_functions(gen, args, m, starts, start_set, hle, workers, t0)
    finally:
        if workers:
            workers.close()


def generate_functions(gen, args, m, starts, start_set, hle, workers, t0):
    import io
    import time
    scanned, rounds = {}, 0
    while True:
        rounds += 1
        order = sorted(start_set)
        new = set()
        ranges = [(a, order[i + 1] if i + 1 < len(order) else m.hi)
                  for i, a in enumerate(order)]
        missing = [key for key in ranges if key not in scanned]
        done = 0
        if workers:
            for result, stats, eh_stats in workers.map("scan", missing):
                m.stats.update(stats)
                STATS.update(eh_stats)
                for a, end, scanned_range in result:
                    scanned[(a, end)] = m.scan(a, end) if scanned_range is None else scanned_range
                done += len(result)
                print(f"{args.name}: scan round {rounds} progress {done}/{len(missing)}",
                      file=sys.stderr, flush=True)
        else:
            for a, end in missing:
                scanned[(a, end)] = m.scan(a, end)
        for key in ranges:
            new |= scanned[key][1] - start_set
        if not new:
            break
        start_set |= new
    entries = {}
    for i, a in enumerate(order):
        end = order[i + 1] if i + 1 < len(order) else m.hi
        labels, ext, tables = scanned[(a, end)]
        entries[a] = (end, labels, tables)
    print(f"{args.name}: {len(starts)} boundaries, {len(entries)} functions, {rounds} rounds, {dict(m.stats)}, "
          f"{time.time() - t0:.0f}s", file=sys.stderr)
    os.makedirs(args.outdir, exist_ok=True)
    order = sorted(entries)
    if args.limit:
        order = order[:args.limit]
    if args.only:  # file with function starts (hex, relative to the module base), generate only these (partial build for tests)
        want = {args.base + int(x, 16) for x in open(args.only).read().split()}
        order = [a for a in order if a in want]
        missing = want - set(order)
        if missing:
            print(f"{args.name}: --only: {len(missing)} starts are not function starts", file=sys.stderr)

    def emitted_functions():
        if workers:
            items = ((a, *entries[a]) for a in order)
            for result, stats, eh_stats in workers.map("emit", items):
                STATS.update(eh_stats)
                yield from result
        else:
            for a in order:
                end, labels, tables = entries[a]
                m._refs = set()
                lines = m.emit_function(a, end, labels, tables, hle)
                yield a, lines, m._refs
                m._refs = set()

    emitted = iter(emitted_functions())
    nchunks, ci, pending = 0, 0, None
    all_refs = set()
    written, last_win, sub = set(), None, 0
    win_of = lambda a: (a - m.lo) // args.window if args.window else 0  # fixed address windows: chunks stay stable under local changes
    while ci < len(order) or pending:
        body, refs, size, fns = [], set(), 0, []
        while (pending or ci < len(order)) and len(fns) < args.chunk and size < args.chunk_bytes:
            if not pending and fns and win_of(order[ci]) != win_of(fns[0]):
                break
            if pending:
                a, lines, r = pending
                pending = None
            else:
                a, lines, r = next(emitted)
                ci += 1
            n = sum(len(l) + 1 for l in lines)
            if n > args.big_fn and fns:
                pending = (a, lines, r)
                break
            body += lines
            size += n
            fns.append(a)
            refs |= r
            if n > args.big_fn:
                break
        win = win_of(fns[0])
        sub = sub + 1 if win == last_win else 0
        last_win = win
        fname_ = f"{args.name}_{win:05x}_{sub}.c"
        written.add(fname_)
        path = os.path.join(args.outdir, fname_)
        text = ['#include "cpu.h"\n' + ('#include "simd.h"\n' if m.lifter.sc else "")]
        text += [f"void {gen.fname(r)}(Cpu *c);\n" for r in sorted(refs)]
        text += [f"void {gen.sanitize(hle[a])}(Cpu *c);\n" for a in sorted(set(hle) & set(fns))]
        text += ["\n".join(body), "\n"]
        gen.write_if_changed(path, "".join(text))
        all_refs |= refs
        nchunks += 1
        print(f"{args.name}: progress {ci}/{len(order)} files {nchunks}", file=sys.stderr, flush=True)
    for fn in os.listdir(args.outdir):  # chunks of earlier runs (other windows or old numbering)
        if re.fullmatch(re.escape(args.name) + r"_(\d{3}|[0-9a-f]{5}_\d+)\.c", fn) and fn not in written:
            os.remove(os.path.join(args.outdir, fn))
    with io.StringIO() as f:
        f.write('#include "cpu.h"\n')
        for a in order:
            f.write(f"void {gen.fname(a)}(Cpu *c);\n")
        f.write(f"const uint64_t {args.name}_fn_addrs[] = {{\n" + ",\n".join(gen.hx(a) for a in order) + "};\n")
        f.write(f"const GuestFn {args.name}_fn_ptrs[] = {{\n" + ",\n".join(gen.fname(a) for a in order) + "};\n")
        f.write(f"const uint64_t {args.name}_fn_count = {len(order)};\n")
        gen.write_if_changed(os.path.join(args.outdir, f"{args.name}_table.c"), f.getvalue())
    print(f"{args.name}: wrote {nchunks} chunks, {time.time() - t0:.0f}s total", file=sys.stderr)
    if args.only:  # partial build: direct calls to non-generated functions go through the dispatch (test stubs)
        missing_refs = sorted(all_refs - set(order))
        stub = ['#include "cpu.h"\n'] + [
            f"void {gen.fname(a)}(Cpu *c) {{ c->pc = {gen.hx(a)}; rt_dispatch(c); }}\n" for a in missing_refs]
        gen.write_if_changed(os.path.join(args.outdir, f"{args.name}_stubs.c"), "".join(stub))
    STATS["functions"] = len(order)
    STATS["chunks"] = nchunks
    STATS["br_all_labels"] = m.stats.get("br_all_labels", 0)
    STATS["br_dispatch"] = m.stats.get("br_dispatch", 0)
    STATS["jumptables"] = m.stats.get("jumptables", 0)


def main():
    import argparse
    import platform
    argv = sys.argv[1:]
    las = ROOT / "scripts" / "recomp" / "upstream" / "generator"
    if "--las-dir" in argv:
        i = argv.index("--las-dir")
        las = Path(argv[i + 1])
        del argv[i:i + 2]
    if not argv or argv[0] != "gen":
        print(__doc__)
        return 2
    gen = install(las)
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("name")
    ap.add_argument("nso")
    ap.add_argument("base", type=lambda s: int(s, 0))
    ap.add_argument("outdir")
    ap.add_argument("--hle")
    ap.add_argument("--chunk", type=int, default=1500)
    ap.add_argument("--chunk-bytes", type=int, default=1500000)
    ap.add_argument("--big-fn", type=int, default=100000)
    ap.add_argument("--window", type=lambda x: int(x, 0), default=0x8000, help="chunk boundary every N bytes of guest code (0 = by size only)")
    ap.add_argument("--setjmp-at", action="append", type=lambda x: int(x, 0), default=[],
                    help="additional setjmp function (offset to the module base) for modules without dynamic symbols (test module)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only")
    ap.add_argument("--entry-offsets", help="module-relative cross-module branch targets from native ExeFS staging")
    ap.add_argument("--simd", choices=("asm", "c"), default="asm" if platform.machine().lower() in ("arm64", "aarch64") else "c")
    ap.add_argument("--jobs", default=os.environ.get("BDSP_GEN_JOBS", "auto"),
                    help="generator processes (default: CPU/RAM-based auto; 1 = serial)")
    args = ap.parse_args(argv)
    if args.jobs != "auto" and (not args.jobs.isdecimal() or int(args.jobs) < 1):
        ap.error("--jobs must be auto or a positive integer")
    args.las_dir = las
    EXTRA_SETJMP.extend(args.setjmp_at)
    atexit.register(lambda: print("eh_gen:", dict(STATS), file=sys.stderr))
    generate(gen, args)


if __name__ == "__main__":
    sys.exit(main() or 0)

