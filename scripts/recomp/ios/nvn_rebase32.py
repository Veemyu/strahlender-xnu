#!/usr/bin/env python3
"""Speichermodell B (--rebase32) für die kopierten NVN-Quellen (work/recomp/nvn-src, von prepare.sh erzeugt).

Der Klon (LASRecomp) rechnet Gastadressen mit (uintptr_t) in Hostzeiger um (Gastadresse == Hostadresse, Variante A). In Variante B
liegt der Gastspeicher bei g_base + 32-Bit-Offset: jede solche Stelle muss durch G2H() gehen (rt-bdsp/guestmem.h). Dieses Skript schreibt
die Kopie nach OUT um (Eingabe bleibt unverändert, nichts davon liegt im Repo). Jede Regel muss mindestens einmal treffen, sonst bricht
das Skript ab (die Quellen haben sich geändert und die Liste braucht eine Durchsicht).

Hostzeiger, die als uint64_t in Befehlssätzen oder Gastobjekten stehen (NvnTexture*, NvnProgram*, NvnDescPool*, bridged Objective-C-
Objekte), bleiben unberührt: nur Ausdrücke, die Gastadressen sind, werden von (uintptr_t)X zu GA(X) (= (uintptr_t)G2H(X)).

Aufruf: nvn_rebase32.py <nvn-src> <out>
"""
import os
import re
import shutil
import sys

src, out = sys.argv[1], sys.argv[2]
if os.path.exists(out):
    shutil.rmtree(out)
shutil.copytree(src, out)

# Ausdrücke, die Gastadressen sind (Argument von (uintptr_t))
GUEST = {
    "nvn/cmdbuf.c": [r"at", r"s\.x\[(?:arg|2|3|4|5)\]", r"views\[i\]", r"view", r"region", r"fp", r"\(fp \+ 8\)"],
    "nvn/objects.c": [r"event_addr\(A\(0\)\)", r"\(b \+ 0x28\)", r"t->addr", r"\* \(uint64_t \*\)\(data \+ i \* stride \+ 8\)",
                      r"\(code \+ 0x30\)", r"code", r"G\(uint64_t, A\([01]\), 0x18\)"],
    "nvn/renderer.m": [r"p->stages\[s\]\.code_addr", r"addr", r"dbg_addr", r"dbg_vs", r"p->stages\[0\]\.code_addr", r"p->stages\[1\]\.code_addr",
                       r"e->tex->addr", r"\(ss->code_addr \+ ss->const_offset\)", r"r\.addr", r"ss->code_addr", r"st\.ubuf\[[^\]]*\]\[[^\]]*\]\.addr",
                       r"st\.sbuf\[[^\]]*\]\[[^\]]*\]\.addr", r"st\.vbuf\[[^\]]*\]\.addr", r"\(fs \+ 0x30\)", r"st\.program->stages\[0\]\.code_addr",
                       r"iaddr", r"\(src \+ \(uint64_t\)z \* img\)", r"st_->addr", r"p", r"cs", r"st\.program->stages\[5\]\.code_addr",
                       r"\(r->x\[0\] \+ r->x\[2\]\)", r"r->x\[1\]", r"r->x\[0\]", r"t->addr"],
    "nvn/metal.m": [r"t->addr"],
}
# Ausnahmen innerhalb dieser Dateien: Ausdrücke, die Hostzeiger tragen, obwohl sie wie die obigen aussehen
KEEP = {"nvn/renderer.m": [r"\(NvnProgram \*\)\(uintptr_t\)r->x\[0\]"]}


def rewrite(path, exprs):
    p = os.path.join(out, path)
    s = open(p, encoding="utf-8").read()
    total = 0
    for e in exprs:
        # (uintptr_t)AUSDRUCK, danach kein Bezeichnerzeichen; nicht, wenn davor schon GA( steht
        pat = re.compile(r"\(uintptr_t\)\s*(" + e + r")(?![\w\[\]>.])")
        s, n = pat.subn(lambda m: "GA(" + m.group(1) + ")", s)
        total += n
    open(p, "w", encoding="utf-8").write(s)
    return total


counts = {f: rewrite(f, ex) for f, ex in GUEST.items()}

# renderer.m: Stellen, an denen derselbe Ausdruck einen Hostzeiger meint, zurücknehmen (Befehlssatz-Felder: Programm, Pools, Texturen)
p = os.path.join(out, "nvn/renderer.m")
s = open(p, encoding="utf-8").read()
for pat in (r"\(NvnProgram \*\)GA\(r->x\[0\]\)",):
    s, n = re.subn(pat, "(NvnProgram *)(uintptr_t)r->x[0]", s)
    counts["renderer.m:programm"] = n
# Zeile 2519/2520: tpool/spool sind Hostzeiger
s, n = re.subn(r"\(NvnDescPool \*\)GA\(r->x\[0\]\)", "(NvnDescPool *)(uintptr_t)r->x[0]", s)
open(p, "w", encoding="utf-8").write(s)

# Makros in nvn.h
p = os.path.join(out, "nvn/nvn.h")
s = open(p, encoding="utf-8").read()
reps = [
    ('#include "tegra.h"', '#include "tegra.h"\n#include "guestmem.h"\n#define GA(a) ((uintptr_t)G2H(a))'),
    ("#define AP(i) ((void *)(uintptr_t)c->x[(i)])", "#define AP(i) ((void *)G2H(c->x[(i)]))"),
    ("#define HOST(T, guest) ((T *)(uintptr_t)(*(uint64_t *)(uintptr_t)(guest)))", "#define HOST(T, guest) ((T *)(uintptr_t)(*(uint64_t *)G2H(guest)))"),
    ("#define SET_HOST(guest, p) (*(uint64_t *)(uintptr_t)(guest) = (uint64_t)(uintptr_t)(p))", "#define SET_HOST(guest, p) (*(uint64_t *)G2H(guest) = (uint64_t)(uintptr_t)(p))"),
    ("#define G(T, base, off) (*(T *)((uint8_t *)(uintptr_t)(base) + (off)))", "#define G(T, base, off) (*(T *)((uint8_t *)G2H(base) + (off)))"),
]
for a, b in reps:
    if a not in s:
        sys.exit("nvn.h: Regel trifft nicht: " + a)
    s = s.replace(a, b)
open(p, "w", encoding="utf-8").write(s)

# metal.m: der Metal-Puffer umhüllt den Hostbereich des Gastspeichers
p = os.path.join(out, "nvn/metal.m")
s = open(p, encoding="utf-8").read()
s, n = re.subn(r"newBufferWithBytesNoCopy:\(void \*\)HEAP_BASE", "newBufferWithBytesNoCopy:G2H(HEAP_BASE)", s)
counts["metal.m:buffer"] = n
open(p, "w", encoding="utf-8").write(s)

bad = [k for k, v in counts.items() if v == 0]
print("Ersetzungen:", counts)
if bad:
    sys.exit("Regeln ohne Treffer: %s" % bad)

# movie_glue.c (Repo, nicht verändert) -> out/movie_glue32.c: Gastzeiger über G2H, Hostzeiger, die der Gast liest, in den Gastspeicher legen
mp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rt-bdsp", "nvn", "movie_glue.c")
s = open(mp, encoding="utf-8").read()
mreps = [
    (r"\(uintptr_t\)(c->x\[\d\])", r"GA(\1)"),
    (r"\(uintptr_t\)guest;", r"GA(guest);"),
    (r"#define BUF\(x\) \(\(MBuffer \*\)\(uintptr_t\)\(x\)\)", r"#define BUF(x) ((MBuffer *)GA(x))"),
    (r"return \(uint64_t\)\(uintptr_t\)t;", r"return H2G(t);"),
    (r"\(uint64_t\)\(uintptr_t\)(d->in_mem\[i\]|d->out_mem\[i\]);", r"H2G(\1);"),
    (r"\(void \*\)\(uintptr_t\)b->base", r"(void *)GA(b->base)"),
    (r"\(uint64_t\)\(uintptr_t\)e->sval;", r"gstr(e->sval);"),
    (r"static MediaData \*md\(uint64_t guest\) \{",
     "static uint64_t gstr(const char *v) { void *p = hle_alloc(strlen(v) + 1); strcpy(p, v); return H2G(p); }\n"
     "static MediaData *md(uint64_t guest) {"),
    (r'#include "hle.h"', '#include "hle.h"\n#include "guestmem.h"\n#define GA(a) ((uintptr_t)G2H(a))'),
]
for pat, rep in mreps:
    s, n = re.subn(pat, rep, s)
    if n == 0:
        sys.exit("movie_glue: Regel trifft nicht: " + pat)
open(os.path.join(out, "movie_glue32.c"), "w", encoding="utf-8").write(s)
rest = [l.strip() for l in s.splitlines() if "(uintptr_t)" in l and "GA(" not in l.replace("#define GA(a) ((uintptr_t)G2H(a))", "")]
print("movie_glue32.c: übrige (uintptr_t)-Stellen:", len(rest))
for l in rest:
    print("   ", l[:150])

# Zeiger-Reste: nach dem Umschreiben darf (uintptr_t) nur an den gelisteten Stellen stehen. Das sind Hostzeiger (Befehlsobjekte, Hashes,
# Hostobjekte, Makro-Definitionen, undurchsichtige Griffe der Filmwiedergabe, die nur der Host liest). Eine neue Stelle kann ein
# Gastzeiger sein, den keine Regel erreicht: dann bricht das Skript ab. Der Übersetzer (nvn/maxwell) ist Hostcode ohne Gastspeicher.
EXPECTED_CASTS = {"nvn/renderer.m": 16, "nvn/cmdbuf.c": 7, "nvn/metal.m": 4, "nvn/nvn.h": 4, "movie_glue32.c": 6}
found = {}
for dp, _, fn in os.walk(out):
    rel_dir = os.path.relpath(dp, out)
    if rel_dir.startswith("nvn/maxwell"):
        continue
    for f in fn:
        if not f.endswith((".c", ".h", ".m", ".inc")):
            continue
        p = os.path.join(dp, f)
        n = sum(1 for line in open(p, encoding="utf-8") if "(uintptr_t)" in line)
        if n:
            found[os.path.relpath(p, out)] = n
unexpected = {f: (found.get(f, 0), EXPECTED_CASTS.get(f, 0)) for f in set(found) | set(EXPECTED_CASTS)
              if found.get(f, 0) != EXPECTED_CASTS.get(f, 0)}
if unexpected:
    sys.exit("Zeiger-Reste (uintptr_t) weichen von der Liste ab (gefunden, erwartet): %s" % unexpected)
print("Zeiger-Reste wie erwartet:", found)
