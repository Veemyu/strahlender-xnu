/* SPDX-License-Identifier: MIT
 * Read-only analysis checkpoint used to validate native generator stages. */
#include "analysis.h"
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

static bool contains(const Addresses *a, uint64_t value) {
    size_t lo = 0, hi = a->size;
    while (lo < hi) { size_t mid = lo + (hi - lo) / 2; if (a->items[mid] < value) lo = mid + 1; else hi = mid; }
    return lo < a->size && a->items[lo] == value;
}
static bool in_text(const Nso *n, uint64_t base, uint64_t value) {
    return value >= base + n->segments[0].offset && value < base + n->segments[0].offset + n->segments[0].size && !(value & 3);
}
static uint32_t word(const Nso *n, size_t index) { return cg_u32(n->image + n->segments[0].offset + index * 4); }
static int64_t immediate(uint32_t w) {
    int64_t imm = (int64_t)(((w >> 5) & 0x7ffff) << 2 | (w >> 29 & 3));
    return imm & (1 << 20) ? imm - (1 << 21) : imm;
}
static uint64_t branch(uint64_t pc, uint32_t w) {
    int64_t delta = w & 0x3ffffff;
    if (delta & (1 << 25)) delta -= 1 << 26;
    return pc + (uint64_t)(delta * 4);
}
static bool jump_table_base(const Nso *n, size_t i, size_t count) {
    uint32_t d = word(n, i) & 31; bool seen = false;
    size_t end = i + 25 < count ? i + 25 : count;
    for (size_t k = i + 1; k < end; k++) {
        uint32_t w = word(n, k);
        if ((w & 0xff200000) == 0x8b000000 && (w & 31) == d && ((w >> 5) & 31) == d) seen = true;
        if (w == (0xd61f0000 | d << 5)) return seen;
    }
    return false;
}
static bool setjmp_name(const char *s) {
    return !strcmp(s, "setjmp") || !strcmp(s, "_setjmp") || !strcmp(s, "sigsetjmp") || !strcmp(s, "__sigsetjmp");
}
static void setjmp_returns(const Nso *n, uint64_t base, const Addresses *extra, Addresses *returns) {
    Addresses targets = {0}, slots = {0};
    for (size_t i = 0; i < n->symbol_count; i++) {
        Symbol s = n->symbols[i];
        if (s.section && setjmp_name(s.name)) {
            if (s.value > UINT64_MAX - base) cg_fail(4, "setjmp symbol address overflow");
            cg_address(&targets, base + s.value);
        }
    }
    for (size_t i = 0; i < extra->size; i++) {
        if (extra->items[i] > UINT64_MAX - base) cg_fail(4, "setjmp offset overflow");
        cg_address(&targets, base + extra->items[i]);
    }
    for (size_t i = 0; i < n->relocation_count; i++) {
        Relocation r = n->relocations[i];
        if (r.symbol && (r.type == 257 || r.type == 1025 || r.type == 1026) && setjmp_name(n->symbols[r.symbol].name)) cg_address(&slots, base + r.offset);
    }
    cg_unique(&slots);
    size_t count = n->segments[0].size / 4; uint64_t lo = base + n->segments[0].offset;
    if (slots.size) for (size_t i = 0; i + 2 < count; i++) {
        uint32_t w = word(n, i), next = word(n, i + 1);
        if ((w & 0x9f000000) == 0x90000000 && (next & 0xffc00000) == 0xf9400000) {
            uint64_t pc = lo + i * 4;
            uint64_t slot = (pc & ~UINT64_C(0xfff)) + (uint64_t)(immediate(w) * 4096) + ((next >> 10) & 0xfff) * 8;
            if (contains(&slots, slot)) cg_address(&targets, pc);
        }
    }
    cg_unique(&targets);
    if (!targets.size) return;
    for (size_t i = 0; i < count; i++) {
        uint32_t w = word(n, i); uint64_t pc = lo + i * 4;
        if ((w & 0xfc000000) == 0x94000000 && contains(&targets, branch(pc, w))) cg_address(returns, pc + 4);
    }
    cg_unique(returns);
}
static void address_json(Buffer *out, const char *key, const Addresses *a, bool comma) {
    if (comma) cg_buffer(out, ",", 1);
    cg_json_string(out, key); cg_buffer(out, ":[", 2);
    for (size_t i = 0; i < a->size; i++) cg_printf(out, "%s%" PRIu64, i ? "," : "", a->items[i]);
    cg_buffer(out, "]", 1);
}
InitialAnalysis cg_initial_analysis(const Nso *input, uint64_t base, const Addresses *extra, const char *entry_offsets) {
    Nso n = *input;
    if (base > UINT64_MAX - n.size) cg_fail(4, "module base address overflow");
    if (n.segments[0].size % 4) cg_fail(4, "unaligned AArch64 text length");
    Addresses boundaries = {0}, landing_pads = {0}, returns = {0}, entries = {0};
    cg_exception_addresses(&n, base, &boundaries, &landing_pads); cg_phase = "analyze";
    for (size_t i = 0; i < n.symbol_count; i++) {
        Symbol s = n.symbols[i];
        if (s.section && (s.info & 15) == 2 && s.value <= UINT64_MAX - base) cg_address(&boundaries, base + s.value);
    }
    for (size_t i = 0; i < n.relocation_count; i++) {
        Relocation r = n.relocations[i];
        if (r.type == 1027) cg_address(&boundaries, base + (uint64_t)r.addend);
    }
    size_t valid = 0;
    for (size_t i = 0; i < boundaries.size; i++) if (in_text(&n, base, boundaries.items[i])) boundaries.items[valid++] = boundaries.items[i];
    boundaries.size = valid; cg_unique(&boundaries);
    for (size_t i = 0; i < boundaries.size; i++) cg_address(&entries, boundaries.items[i]);
    if (entry_offsets) {
        Buffer file = cg_read(entry_offsets); char *p = (char *)file.data;
        while (*p) {
            while (isspace((unsigned char)*p)) p++;
            if (!*p) break;
            if (*p == '-' || *p == '+') cg_fail(4, "invalid cross-module entry offset");
            char *end; errno = 0; uintmax_t offset = strtoumax(p, &end, 16);
            if (p == end || errno || (*end && !isspace((unsigned char)*end)) || offset > UINT64_MAX - base || !in_text(&n, base, base + offset)) cg_fail(4, "cross-module entry outside module text");
            cg_address(&entries, base + offset); p = end;
        }
    }
    size_t count = n.segments[0].size / 4; uint64_t lo = base + n.segments[0].offset;
    for (size_t i = 0; i < count; i++) {
        uint32_t w = word(&n, i);
        if ((w & 0xfc000000) == 0x94000000) {
            uint64_t target = branch(lo + i * 4, w);
            if (in_text(&n, base, target)) cg_address(&entries, target);
        }
    }
    uint64_t pages[32] = {0}; size_t page_at[32] = {0}; bool page_valid[32] = {false};
    size_t kept = 0;
    for (size_t i = 0; i < count; i++) {
        uint32_t w = word(&n, i); uint64_t pc = lo + i * 4;
        if ((w & 0x9f000000) == 0x10000000) {
            uint64_t target = pc + (uint64_t)immediate(w);
            if (in_text(&n, base, target)) {
                if (jump_table_base(&n, i, count)) kept++; else cg_address(&entries, target);
            }
        } else if ((w & 0x9f000000) == 0x90000000) {
            unsigned reg = w & 31; pages[reg] = (pc & ~UINT64_C(0xfff)) + (uint64_t)(immediate(w) * 4096); page_at[reg] = i; page_valid[reg] = true;
        } else if ((w & 0xffc00000) == 0x91000000) {
            unsigned reg = w >> 5 & 31;
            if (page_valid[reg] && i - page_at[reg] <= 8) {
                uint64_t target = pages[reg] + (w >> 10 & 0xfff);
                if (in_text(&n, base, target)) cg_address(&entries, target);
            }
        }
    }
    cg_unique(&entries); setjmp_returns(&n, base, extra, &returns);
    return (InitialAnalysis){boundaries, entries, landing_pads, returns, kept};
}
int cg_inspect(int argc, char **argv) {
    if (argc < 2) cg_fail(2, "inspect requires an NSO and module name");
    const char *path = argv[0], *entry_offsets = NULL; cg_module = argv[1];
    uint64_t base = 0; bool have_base = false; Addresses extra = {0};
    for (int i = 2; i < argc; i++) {
        const char *option = argv[i];
        if (!strcmp(option, "--events=jsonl")) { cg_events = true; continue; }
        if (++i == argc) cg_fail(2, "missing inspect option value");
        if (!strcmp(option, "--base")) { base = cg_number(argv[i]); have_base = true; }
        else if (!strcmp(option, "--entry-offsets")) entry_offsets = argv[i];
        else if (!strcmp(option, "--setjmp-at")) cg_address(&extra, cg_number(argv[i]));
        else cg_fail(2, "unknown inspect option");
    }
    if (!have_base) cg_fail(2, "inspect requires --base");
    Nso n = cg_nso(path); cg_phase = "analyze";
    InitialAnalysis result = cg_initial_analysis(&n, base, &extra, entry_offsets);
    Buffer output = {0}; cg_buffer(&output, "{", 1);
    address_json(&output, "boundaries", &result.boundaries, false);
    address_json(&output, "initial_entries", &result.entries, true);
    address_json(&output, "landing_pads", &result.landing_pads, true);
    address_json(&output, "setjmp_returns", &result.returns, true);
    cg_printf(&output, ",\"adr_bases_kept_inside\":%zu}\n", result.adr_bases_kept);
    fwrite(output.data, 1, output.size, stdout); return 0;
}
