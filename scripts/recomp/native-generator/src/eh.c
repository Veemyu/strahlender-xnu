/* SPDX-License-Identifier: MIT
 * Native counterpart of eh_lsda.py and the EH-table part of LASRecomp analyze.py.
 * Parse metadata only; exception execution remains in the existing game runtime. */
#include "codegen.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

typedef struct { const Nso *n; uint64_t p, end; } Reader;
typedef struct { uint64_t offset; unsigned fde, lsda; } Cie;

void cg_address(Addresses *a, uint64_t value) {
    if (a->size == a->capacity) {
        size_t capacity = a->capacity ? a->capacity * 2 : 128;
        uint64_t *p = cg_alloc(capacity, sizeof(*p));
        if (a->size) memcpy(p, a->items, a->size * sizeof(*p));
        a->items = p; a->capacity = capacity;
    }
    a->items[a->size++] = value;
}
static int compare(const void *left, const void *right) {
    uint64_t a = *(const uint64_t *)left, b = *(const uint64_t *)right;
    return (a > b) - (a < b);
}
void cg_unique(Addresses *a) {
    if (!a->size) return;
    qsort(a->items, a->size, sizeof(*a->items), compare);
    size_t count = 1;
    for (size_t i = 1; i < a->size; i++) if (a->items[i] != a->items[count - 1]) a->items[count++] = a->items[i];
    a->size = count;
}
static uint64_t take(Reader *r, unsigned bytes) {
    cg_range((size_t)r->end, r->p, bytes, "exception metadata");
    const unsigned char *p = r->n->image + r->p; r->p += bytes;
    switch (bytes) { case 1: return *p; case 2: return cg_u16(p); case 4: return cg_u32(p); default: return cg_u64(p); }
}
static int64_t leb(Reader *r, bool sign) {
    uint64_t value = 0; unsigned shift = 0;
    for (unsigned i = 0; i < 10; i++) {
        unsigned byte = (unsigned)take(r, 1);
        if (i == 9 && ((sign && byte != 0 && byte != 0x7f) || (!sign && byte > 1))) cg_fail(4, "LEB128 overflow");
        value |= (uint64_t)(byte & 0x7f) << shift;
        shift += 7;
        if (!(byte & 0x80)) {
            if (sign && (byte & 0x40) && shift < 64) value |= UINT64_MAX << shift;
            if (!sign && value > INT64_MAX) cg_fail(4, "exception count exceeds supported range");
            return (int64_t)value;
        }
    }
    cg_fail(4, "unterminated LEB128 value");
}
static int64_t encoded(Reader *r, unsigned enc) {
    uint64_t at = r->p; int64_t value;
    switch (enc & 15) {
        case 0: value = (int64_t)take(r, 8); break;
        case 1: value = leb(r, false); break;
        case 2: value = (int64_t)take(r, 2); break;
        case 3: value = (int64_t)take(r, 4); break;
        case 4: value = (int64_t)take(r, 8); break;
        case 9: value = leb(r, true); break;
        case 10: value = (int16_t)take(r, 2); break;
        case 11: value = (int32_t)take(r, 4); break;
        case 12: value = (int64_t)take(r, 8); break;
        default: cg_fail(4, "unsupported DWARF pointer encoding");
    }
    if ((enc & 0x70) == 0x10) {
        if (value > INT64_MAX - (int64_t)at) cg_fail(4, "DWARF pointer overflow");
        value += (int64_t)at;
    }
    return value;
}
static uint64_t location(int64_t value, const Nso *n, const char *what) {
    if (value < 0 || (uint64_t)value >= n->size) cg_fail(4, "%s is outside the module", what);
    return (uint64_t)value;
}
static uint64_t address(uint64_t base, uint64_t offset) {
    if (offset > UINT64_MAX - base) cg_fail(4, "guest exception address overflow");
    return base + offset;
}
static Cie cie(const Nso *n, uint64_t offset) {
    cg_range(n->size, offset, 8, "CIE header");
    uint32_t length = cg_u32(n->image + offset);
    cg_range(n->size, offset + 4, length, "CIE body");
    Reader r = {n, offset + 9, offset + 4 + length};
    uint64_t augmentation = r.p;
    while (take(&r, 1)) { /* bounded NUL-terminated augmentation */ }
    (void)leb(&r, false); (void)leb(&r, true); (void)take(&r, 1);
    Cie c = {offset, 0, 0xff};
    if (n->image[augmentation] == 'z') {
        int64_t bytes = leb(&r, false);
        cg_range((size_t)r.end, r.p, (uint64_t)bytes, "CIE augmentation");
        r.end = r.p + (uint64_t)bytes;
        const unsigned char *p = n->image + augmentation + 1;
        while (*p) {
            switch (*p++) {
                case 'R': c.fde = (unsigned)take(&r, 1); break;
                case 'L': c.lsda = (unsigned)take(&r, 1); break;
                case 'P': { unsigned enc = (unsigned)take(&r, 1); (void)encoded(&r, enc & 0x7f); break; }
                case 'S': break;
                default: cg_fail(4, "unsupported CIE augmentation");
            }
        }
    }
    return c;
}
static void lsda(const Nso *n, uint64_t pointer, uint64_t start, uint64_t base, Addresses *landing_pads) {
    Reader r = {n, pointer, n->size}; unsigned lp_enc = (unsigned)take(&r, 1);
    uint64_t lp_start = start;
    if (lp_enc != 0xff) lp_start = location(encoded(&r, lp_enc), n, "LSDA landing-pad base");
    unsigned type_enc = (unsigned)take(&r, 1);
    if (type_enc != 0xff) (void)leb(&r, false);
    unsigned site_enc = (unsigned)take(&r, 1); uint64_t bytes = (uint64_t)leb(&r, false);
    cg_range(n->size, r.p, bytes, "LSDA call-site table"); r.end = r.p + bytes;
    while (r.p < r.end) {
        (void)encoded(&r, site_enc); (void)encoded(&r, site_enc);
        int64_t lp = encoded(&r, site_enc); (void)leb(&r, false);
        if (lp) {
            uint64_t target;
            if (lp >= 0) {
                if ((uint64_t)lp > UINT64_MAX - lp_start) cg_fail(4, "invalid landing pad");
                target = lp_start + (uint64_t)lp;
            } else {
                uint64_t magnitude = (uint64_t)(-(lp + 1)) + 1;
                if (magnitude > lp_start) cg_fail(4, "invalid landing pad");
                target = lp_start - magnitude;
            }
            cg_range(n->size, target, 4, "landing pad"); cg_address(landing_pads, address(base, target));
        }
    }
}
void cg_exception_addresses(const Nso *n, uint64_t base, Addresses *boundaries, Addresses *landing_pads) {
    if (!n->eh_start || n->eh_start == n->eh_end) return;
    cg_phase = "exceptions";
    uint64_t hdr = n->eh_start;
    Reader r = {n, hdr, n->size};
    unsigned version = (unsigned)take(&r, 1), pointer_enc = (unsigned)take(&r, 1);
    unsigned count_enc = (unsigned)take(&r, 1), table_enc = (unsigned)take(&r, 1);
    if (version != 1) cg_fail(4, "unsupported exception header version");
    (void)encoded(&r, pointer_enc); int64_t count = encoded(&r, count_enc);
    if (count < 0 || (uint64_t)count > n->size / 2) cg_fail(4, "invalid exception table count");
    Cie *cies = cg_alloc((size_t)count, sizeof(*cies)); size_t cie_count = 0;
    for (int64_t i = 0; i < count; i++) {
        int64_t loc = encoded(&r, table_enc & 15), fde = encoded(&r, table_enc & 15);
        if ((table_enc & 0x70) == 0x30) {
            if (loc > INT64_MAX - (int64_t)hdr || fde > INT64_MAX - (int64_t)hdr) cg_fail(4, "exception table pointer overflow");
            loc += (int64_t)hdr; fde += (int64_t)hdr;
        }
        uint64_t entry = location(loc, n, "EH function");
        cg_address(boundaries, address(base, entry));
        uint64_t off = location(fde, n, "FDE"); cg_range(n->size, off, 8, "FDE header");
        uint32_t length = cg_u32(n->image + off), cid = cg_u32(n->image + off + 4);
        cg_range(n->size, off + 4, length, "FDE body");
        if ((uint64_t)cid > off + 4) cg_fail(4, "CIE pointer underflow");
        uint64_t cie_offset = off + 4 - cid; size_t index = 0;
        while (index < cie_count && cies[index].offset != cie_offset) index++;
        if (index == cie_count) cies[cie_count++] = cie(n, cie_offset);
        Cie c = cies[index]; Reader q = {n, off + 8, off + 4 + length};
        uint64_t start = location(encoded(&q, c.fde), n, "FDE function");
        (void)encoded(&q, c.fde & 15); uint64_t augmentation_size = (uint64_t)leb(&q, false);
        cg_range((size_t)q.end, q.p, augmentation_size, "FDE augmentation");
        q.end = q.p + augmentation_size;
        if (c.lsda != 0xff && augmentation_size) {
            int64_t pointer = encoded(&q, c.lsda);
            if (pointer) lsda(n, location(pointer, n, "LSDA"), start, base, landing_pads);
        }
    }
    cg_unique(boundaries); cg_unique(landing_pads);
}
