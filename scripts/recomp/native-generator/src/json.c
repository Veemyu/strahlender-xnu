/* SPDX-License-Identifier: MIT
 * The metadata contract is an ordered object of UTF-8 symbol names and uint64
 * addresses, not a general-purpose JSON DOM. Matches Python json.dumps defaults. */
#include "codegen.h"
#include <ctype.h>
#include <inttypes.h>
#include <string.h>

static uint32_t utf8(const unsigned char **cursor) {
    const unsigned char *p = *cursor;
    unsigned char a = *p++; uint32_t cp; unsigned length = 0;
    if (a < 0x80) { *cursor = p; return a; }
    if (a >= 0xc2 && a <= 0xdf) { cp = a & 31; length = 1; }
    else if (a >= 0xe0 && a <= 0xef) { cp = a & 15; length = 2; }
    else if (a >= 0xf0 && a <= 0xf4) { cp = a & 7; length = 3; }
    else { *cursor = p; return 0xfffd; }
    for (unsigned i = 0; i < length; i++) {
        if ((p[i] & 0xc0) != 0x80 || (!i && ((a == 0xe0 && p[i] < 0xa0) ||
            (a == 0xed && p[i] >= 0xa0) || (a == 0xf0 && p[i] < 0x90) || (a == 0xf4 && p[i] >= 0x90)))) {
            *cursor = p + i; return 0xfffd;
        }
        cp = cp << 6 | (p[i] & 63);
    }
    *cursor = p + length; return cp;
}
void cg_json_string(Buffer *b, const char *s) {
    cg_buffer(b, "\"", 1);
    const unsigned char *p = (const unsigned char *)s;
    while (*p) {
        uint32_t cp = utf8(&p);
        switch (cp) {
            case '"': cg_buffer(b, "\\\"", 2); break;
            case '\\': cg_buffer(b, "\\\\", 2); break;
            case '\b': cg_buffer(b, "\\b", 2); break;
            case '\f': cg_buffer(b, "\\f", 2); break;
            case '\n': cg_buffer(b, "\\n", 2); break;
            case '\r': cg_buffer(b, "\\r", 2); break;
            case '\t': cg_buffer(b, "\\t", 2); break;
            default:
                if (cp < 32 || (cp >= 127 && cp <= 0xffff)) cg_printf(b, "\\u%04x", (unsigned)cp);
                else if (cp > 0xffff) { cp -= 0x10000; cg_printf(b, "\\u%04x\\u%04x", (unsigned)(0xd800 + (cp >> 10)), (unsigned)(0xdc00 + (cp & 1023))); }
                else { unsigned char c = (unsigned char)cp; cg_buffer(b, &c, 1); }
        }
    }
    cg_buffer(b, "\"", 1);
}
void cg_json_bindings(Buffer *b, const Bindings *bindings) {
    cg_buffer(b, "{", 1);
    for (size_t i = 0; i < bindings->size; i++) {
        if (i) cg_buffer(b, ", ", 2);
        cg_json_string(b, bindings->items[i].key); cg_printf(b, ": %" PRIu64, bindings->items[i].value);
    }
    cg_buffer(b, "}", 1);
}
static void whitespace(const unsigned char **p) { while (**p == ' ' || **p == '\t' || **p == '\n' || **p == '\r') ++*p; }
static uint32_t hex4(const unsigned char **p) {
    uint32_t n = 0;
    for (unsigned i = 0; i < 4; i++) {
        unsigned char c = **p; if (!c) cg_fail(4, "truncated JSON escape"); ++*p;
        unsigned v;
        if (c >= '0' && c <= '9') v = c - '0'; else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10; else cg_fail(4, "invalid JSON escape");
        n = n * 16 + v;
    }
    return n;
}
static void encode_utf8(Buffer *b, uint32_t cp) {
    unsigned char c[4]; size_t n;
    if (!cp) cg_fail(4, "NUL is not valid in a symbol name");
    if (cp < 0x80) { c[0] = (unsigned char)cp; n = 1; }
    else if (cp < 0x800) { c[0] = (unsigned char)(0xc0 | cp >> 6); c[1] = (unsigned char)(0x80 | (cp & 63)); n = 2; }
    else if (cp < 0x10000) { c[0] = (unsigned char)(0xe0 | cp >> 12); c[1] = (unsigned char)(0x80 | (cp >> 6 & 63)); c[2] = (unsigned char)(0x80 | (cp & 63)); n = 3; }
    else { c[0] = (unsigned char)(0xf0 | cp >> 18); c[1] = (unsigned char)(0x80 | (cp >> 12 & 63)); c[2] = (unsigned char)(0x80 | (cp >> 6 & 63)); c[3] = (unsigned char)(0x80 | (cp & 63)); n = 4; }
    cg_buffer(b, c, n);
}
char *cg_utf8_normalize(const char *s) {
    const unsigned char *p = (const unsigned char *)s;
    Buffer b = {0};
    while (*p) encode_utf8(&b, utf8(&p));
    if (!b.data) cg_buffer(&b, "", 0);
    return (char *)b.data;
}
static char *string(const unsigned char **p) {
    if (**p != '"') cg_fail(4, "expected a JSON symbol name");
    ++*p; Buffer b = {0};
    while (**p && **p != '"') {
        unsigned char c = *(*p)++;
        if (c < 32) cg_fail(4, "control character in JSON string");
        if (c != '\\') { cg_buffer(&b, &c, 1); continue; }
        c = *(*p)++; if (!c) cg_fail(4, "truncated JSON string");
        switch (c) {
            case '"': case '\\': case '/': cg_buffer(&b, &c, 1); break;
            case 'b': cg_buffer(&b, "\b", 1); break; case 'f': cg_buffer(&b, "\f", 1); break;
            case 'n': cg_buffer(&b, "\n", 1); break; case 'r': cg_buffer(&b, "\r", 1); break; case 't': cg_buffer(&b, "\t", 1); break;
            case 'u': {
                uint32_t cp = hex4(p);
                if (cp >= 0xd800 && cp <= 0xdbff) {
                    if ((*p)[0] != '\\' || (*p)[1] != 'u') cg_fail(4, "unpaired JSON surrogate");
                    *p += 2; uint32_t lo = hex4(p);
                    if (lo < 0xdc00 || lo > 0xdfff) cg_fail(4, "unpaired JSON surrogate");
                    cp = 0x10000 + ((cp - 0xd800) << 10) + lo - 0xdc00;
                } else if (cp >= 0xdc00 && cp <= 0xdfff) cg_fail(4, "unpaired JSON surrogate");
                encode_utf8(&b, cp); break;
            }
            default: cg_fail(4, "unknown JSON escape");
        }
    }
    if (**p != '"') cg_fail(4, "unterminated JSON string");
    ++*p; if (!b.data) cg_buffer(&b, "", 0); return (char *)b.data;
}
void cg_read_bindings(Bindings *bindings, const char *path) {
    Buffer data = cg_read(path); const unsigned char *p = data.data;
    if (memchr(data.data, 0, data.size)) cg_fail(4, "NUL byte in JSON metadata");
    whitespace(&p); if (*p++ != '{') cg_fail(4, "expected a JSON symbol object"); whitespace(&p);
    if (*p != '}') for (;;) {
        char *key = string(&p); whitespace(&p); if (*p++ != ':') cg_fail(4, "expected a JSON colon"); whitespace(&p);
        uint64_t value = 0;
        if (*p < '0' || *p > '9') cg_fail(4, "symbol address must be an unsigned integer");
        if (*p == '0' && p[1] >= '0' && p[1] <= '9') cg_fail(4, "leading zero in JSON address");
        do { unsigned d = *p++ - '0'; if (value > (UINT64_MAX - d) / 10) cg_fail(4, "symbol address overflow"); value = value * 10 + d; } while (*p >= '0' && *p <= '9');
        cg_set(bindings, key, value); whitespace(&p);
        if (*p != ',') break;
        p++; whitespace(&p);
    }
    if (*p++ != '}') cg_fail(4, "expected the end of the JSON symbol object");
    whitespace(&p); if (*p) cg_fail(4, "trailing data in JSON symbol object");
}
