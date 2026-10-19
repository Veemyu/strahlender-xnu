#!/usr/bin/env python3
"""Generator-Erweiterung für C++-Exceptions und setjmp/longjmp (Phase-2-Spike, docs/recomp-spike-2.md).

Eigener Code. Der Generator aus research/LASRecomp/tools (MIT, nur zur Laufzeit importiert, nichts kopiert)
wird nicht verändert, sondern hier zur Laufzeit erweitert:

* `EhModule` ist eine Unterklasse von `gen.Module`. Jede erzeugte Gastfunktion, die einen Wiedereinstiegspunkt
  enthält (Landing-Pad aus einer LSDA oder die Stelle hinter einem `bl setjmp`), bekommt am Anfang einen
  Rahmeneintrag (`EhRec` auf dem Host-Stack, verkettet über `Cpu`) und ein `__builtin_setjmp`. Der Eintrag wird
  bei jedem Verlassen der Funktion (Return, Tail-Call, Dispatch) wieder ausgehängt.
* `rt_dispatch` bekommt für Adressen mitten in einer Funktion (kein Funktionsanfang) den Pfad
  `rt_nle_enter`: passenden Rahmeneintrag suchen und per `__builtin_longjmp` dorthin zurückspringen; die
  Funktion verteilt dann auf das Label des Landing-Pads (`switch (c->pc)`).
* `ret` nach `mov sp, xN` (libunwind-`jumpto`) und `ret xN` mit N != 30 werden zu einem indirekten
  Sprung auf das Registerziel (der Standard-Lifter macht daraus ein `return`).

Aufruf wie `gen.py`:  eh_gen.py gen <name> <nso> <basis> <ausgabeordner> [--chunk-bytes N] [--simd asm|c] [--limit N]
Zusätzlich: --las-dir <Ordner mit gen.py> (Standard research/LASRecomp/tools).
"""
import atexit
import bisect
import re
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools" / "pydeps"))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

SETJMP_NAMES = {"setjmp", "_setjmp", "sigsetjmp", "__sigsetjmp"}
STATS = Counter()
TAIL = re.compile(r"__attribute__\(\(musttail\)\) return ([^;]+);")


def install(las_dir):
    sys.path.insert(0, str(Path(las_dir).resolve()))
    import gen
    from lifter import Insn
    import eh_lsda

    class EhModule(gen.Module):
        def __init__(self, name, path, base, simd="asm"):
            super().__init__(name, path, base, simd)
            n = self.nso
            img = n.image
            mod0 = struct.unpack_from("<I", img, 4)[0]
            hdr = mod0 + struct.unpack_from("<i", img, mod0 + 16)[0]
            fdes = eh_lsda.parse_module(img, hdr)
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
            """Adressen hinter `bl setjmp` (Wiedereinstieg bei longjmp): direkte Exporte oder PLT-Stubs auf Importe."""
            n, base = self.nso, self.base
            target_fns = {base + s[3] for s in n.syms if s[0] in SETJMP_NAMES and s[2]}
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
    """`adr xD, T` gefolgt (<= 8 Wörter) von `add xD, xD, xM, lsl n` und `br xD`: T ist die Basis einer relativen
    Sprungtabelle innerhalb derselben Funktion, kein Funktionsanfang (der Standard-Generator zerschneidet sonst
    die Funktion an T)."""
    w = words[i]
    d = w & 31
    seen_add = False
    for k in range(i + 1, min(i + 9, len(words))):
        x = words[k]
        if (x & 0xFF200000) == 0x8B000000 and (x & 31) == d and ((x >> 5) & 31) == d:
            seen_add = True
        if x == (0xD61F0000 | (d << 5)):
            return seen_add
    return False


def generate(gen, args):
    """Wie gen.main (LASRecomp, MIT), mit einer Änderung: ADR-Ziele, die Sprungtabellenbasen sind, werden keine
    Funktionsanfänge. Ausgabe: Chunks `<name>_NNN.c` und `<name>_table.c`."""
    import io
    import os
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
    scanned, rounds = {}, 0
    while True:
        rounds += 1
        order = sorted(start_set)
        new = set()
        for i, a in enumerate(order):
            end = order[i + 1] if i + 1 < len(order) else m.hi
            key = (a, end)
            if key not in scanned:
                scanned[key] = m.scan(a, end)
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
    if args.only:  # Datei mit Funktionsanfängen (hex, relativ zur Modulbasis), nur diese erzeugen (Teilbau für Tests)
        want = {args.base + int(x, 16) for x in open(args.only).read().split()}
        order = [a for a in order if a in want]
        missing = want - set(order)
        if missing:
            print(f"{args.name}: --only: {len(missing)} Anfänge sind keine Funktionsanfänge", file=sys.stderr)
    nchunks, ci, pending = 0, 0, None
    all_refs = set()
    while ci < len(order) or pending:
        body, refs, size, fns = [], set(), 0, []
        while (pending or ci < len(order)) and len(fns) < args.chunk and size < args.chunk_bytes:
            if pending:
                a, lines, r = pending
                pending = None
            else:
                a = order[ci]
                ci += 1
                end, labels, tables = entries[a]
                lines = m.emit_function(a, end, labels, tables, hle)
                r = getattr(m, "_refs", set())
                m._refs = set()
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
        path = os.path.join(args.outdir, f"{args.name}_{nchunks:03d}.c")
        text = ['#include "cpu.h"\n' + ('#include "simd.h"\n' if m.lifter.sc else "")]
        text += [f"void {gen.fname(r)}(Cpu *c);\n" for r in sorted(refs)]
        text += [f"void {gen.sanitize(hle[a])}(Cpu *c);\n" for a in sorted(set(hle) & set(fns))]
        text += ["\n".join(body), "\n"]
        gen.write_if_changed(path, "".join(text))
        all_refs |= refs
        nchunks += 1
        print(f"{args.name}: progress {ci}/{len(order)} files {nchunks}", file=sys.stderr, flush=True)
    for fn in os.listdir(args.outdir):
        mm = re.fullmatch(re.escape(args.name) + r"_(\d{3})\.c", fn)
        if mm and int(mm.group(1)) >= nchunks:
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
    if args.only:  # Teilbau: direkte Aufrufe auf nicht erzeugte Funktionen laufen über den Dispatch (Test-Stubs)
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
    las = ROOT / "research" / "LASRecomp" / "tools"
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
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only")
    ap.add_argument("--simd", choices=("asm", "c"), default="asm" if platform.machine().lower() in ("arm64", "aarch64") else "c")
    args = ap.parse_args(argv)
    atexit.register(lambda: print("eh_gen:", dict(STATS), file=sys.stderr))
    generate(gen, args)


if __name__ == "__main__":
    sys.exit(main() or 0)

