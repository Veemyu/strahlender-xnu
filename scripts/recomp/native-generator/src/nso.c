/* SPDX-License-Identifier: MIT
 * NSO layout and relocation semantics adapted from LASRecomp's MIT nso.py.
 * Copyright notices remain in THIRD_PARTY_NOTICES.md and upstream/LICENSE. */
#include "codegen.h"
#include "lz4.h"
#include <inttypes.h>
#include <limits.h>
#include <string.h>

typedef struct { uint64_t tag, value; } Dynamic;
typedef struct { Dynamic *items; size_t size; } Dynamics;
static uint64_t tag(const Dynamics *d, uint64_t key) {
    for (size_t i = 0; i < d->size; i++) if (d->items[i].tag == key) return d->items[i].value;
    return 0;
}
static bool has_tag(const Dynamics *d, uint64_t key) {
    for (size_t i = 0; i < d->size; i++) if (d->items[i].tag == key) return true;
    return false;
}
static uint64_t relative(const Nso *n, uint32_t mod, unsigned offset) {
    int64_t value = (int64_t)mod + (int32_t)cg_u32(n->image + mod + offset);
    if (value < 0 || (uint64_t)value > n->size) cg_fail(4, "MOD0 relative offset is outside the module");
    return (uint64_t)value;
}
static char *symbol_string(const Nso *n, uint64_t table, uint64_t length, uint32_t offset) {
    if (offset >= length) cg_fail(4, "symbol name is outside the string table");
    cg_range(n->size, table, length, "string table");
    const unsigned char *start = n->image + table + offset;
    const unsigned char *end = memchr(start, 0, (size_t)(length - offset));
    if (!end) cg_fail(4, "unterminated symbol name");
    return cg_utf8_normalize(cg_string((const char *)start, (size_t)(end - start)));
}
Nso cg_nso(const char *path) {
    cg_phase = "nso";
    Buffer raw = cg_read(path); cg_range(raw.size, 0, 0x100, "NSO header");
    if (memcmp(raw.data, "NSO0", 4)) cg_fail(4, "invalid NSO0 signature");
    Nso n = {0}; uint32_t flags = cg_u32(raw.data + 0xc);
    uint32_t file_offsets[3], packed_sizes[3];
    for (unsigned i = 0; i < 3; i++) {
        const unsigned char *p = raw.data + 0x10 + i * 0x10;
        file_offsets[i] = cg_u32(p); n.segments[i].offset = cg_u32(p + 4); n.segments[i].size = cg_u32(p + 8);
        packed_sizes[i] = cg_u32(raw.data + 0x60 + i * 4);
        cg_range(raw.size, file_offsets[i], packed_sizes[i], "NSO segment");
        if (!(flags & (1u << i)) && packed_sizes[i] != n.segments[i].size) cg_fail(4, "uncompressed NSO segment size mismatch");
        if (n.segments[i].size > INT_MAX || packed_sizes[i] > INT_MAX) cg_fail(4, "NSO segment exceeds the LZ4 size limit");
    }
    n.bss_size = cg_u32(raw.data + 0x3c);
    uint64_t end = (uint64_t)n.segments[2].offset + n.segments[2].size + n.bss_size;
    end = (end + 0xfff) & ~UINT64_C(0xfff);
    if (end > SIZE_MAX || end > UINT32_MAX) cg_fail(4, "NSO mapped image is too large");
    n.size = (size_t)end;
    for (unsigned i = 0; i < 3; i++) {
        Segment s = n.segments[i]; cg_range(n.size, s.offset, s.size, "mapped segment");
        if (i && (uint64_t)n.segments[i - 1].offset + n.segments[i - 1].size > s.offset) cg_fail(4, "overlapping or unordered NSO segments");
    }
    n.image = cg_alloc(n.size, 1); memcpy(n.build_id, raw.data + 0x40, 32);
    for (unsigned i = 0; i < 3; i++) {
        Segment s = n.segments[i]; const unsigned char *source = raw.data + file_offsets[i];
        if (flags & (1u << i)) {
            int written = LZ4_decompress_safe((const char *)source, (char *)n.image + s.offset, (int)packed_sizes[i], (int)s.size);
            if (written < 0 || (uint32_t)written != s.size) cg_fail(4, "invalid LZ4 segment");
        } else if (s.size) memcpy(n.image + s.offset, source, s.size);
    }
    cg_range(n.size, 4, 4, "MOD0 pointer"); uint32_t mod = cg_u32(n.image + 4);
    cg_range(n.size, mod, 28, "MOD0 header");
    if (memcmp(n.image + mod, "MOD0", 4)) cg_fail(4, "invalid MOD0 signature");
    uint64_t dyn_offset = relative(&n, mod, 4);
    n.eh_start = (uint32_t)relative(&n, mod, 16); n.eh_end = (uint32_t)relative(&n, mod, 20);
    if (n.eh_start > n.eh_end) cg_fail(4, "reversed exception frame range");
    (void)relative(&n, mod, 8); (void)relative(&n, mod, 12); (void)relative(&n, mod, 24);
    /* First count the terminated dynamic array, then store the first value per
       tag as Python dict.setdefault does. Duplicate relocation tags stay stable. */
    size_t count = 0;
    for (uint64_t off = dyn_offset; ; off += 16) {
        cg_range(n.size, off, 16, "dynamic entry");
        if (!cg_u64(n.image + off)) break;
        count++;
    }
    Dynamics d = {cg_alloc(count, sizeof(Dynamic)), 0};
    for (size_t i = 0; i < count; i++) {
        const unsigned char *p = n.image + dyn_offset + i * 16;
        uint64_t key = cg_u64(p);
        if (!has_tag(&d, key)) d.items[d.size++] = (Dynamic){key, cg_u64(p + 8)};
    }
    n.init = tag(&d, 12); n.init_array = tag(&d, 25); n.init_array_size = tag(&d, 27);
    if (has_tag(&d, 4) && has_tag(&d, 6)) {
        uint64_t hash = tag(&d, 4), symtab = tag(&d, 6), strtab = tag(&d, 5);
        cg_range(n.size, hash, 8, "ELF hash header");
        n.symbol_count = cg_u32(n.image + hash + 4);
        cg_range(n.size, symtab, (uint64_t)n.symbol_count * 24, "dynamic symbol table");
        n.symbols = cg_alloc(n.symbol_count, sizeof(Symbol));
        uint64_t string_size = has_tag(&d, 10) ? tag(&d, 10) : n.size - strtab;
        cg_range(n.size, strtab, string_size, "string table");
        for (size_t i = 0; i < n.symbol_count; i++) {
            const unsigned char *p = n.image + symtab + i * 24;
            n.symbols[i] = (Symbol){symbol_string(&n, strtab, string_size, cg_u32(p)), p[4], cg_u16(p + 6), cg_u64(p + 8), cg_u64(p + 16)};
        }
    }
    const uint64_t bases[] = {7, 23}, sizes[] = {8, 2};
    for (unsigned pass = 0; pass < 2; pass++) {
        if (!has_tag(&d, bases[pass])) continue;
        uint64_t off = tag(&d, bases[pass]), bytes = tag(&d, sizes[pass]);
        if (bytes % 24) cg_fail(4, "relocation table size is not a multiple of 24");
        cg_range(n.size, off, bytes, "relocation table");
        n.relocation_count += (size_t)(bytes / 24);
    }
    n.relocations = cg_alloc(n.relocation_count, sizeof(Relocation)); size_t index = 0;
    for (unsigned pass = 0; pass < 2; pass++) {
        if (!has_tag(&d, bases[pass])) continue;
        uint64_t off = tag(&d, bases[pass]), bytes = tag(&d, sizes[pass]);
        for (uint64_t i = 0; i < bytes; i += 24) {
            const unsigned char *p = n.image + off + i; uint64_t info = cg_u64(p + 8);
            Relocation r = {cg_u64(p), info >> 32, (uint32_t)info, (int64_t)cg_u64(p + 16)};
            if (r.type == 1027 || r.type == 257 || r.type == 1025 || r.type == 1026) {
                cg_range(n.size, r.offset, 8, "relocation target");
                if (r.type != 1027 && r.symbol >= n.symbol_count) cg_fail(4, "relocation symbol is outside the symbol table");
            }
            n.relocations[index++] = r;
        }
    }
    return n;
}
