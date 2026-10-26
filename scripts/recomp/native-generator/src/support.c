/* SPDX-License-Identifier: MIT */
#include "codegen.h"
#include "workers.h"
#include <stdatomic.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __APPLE__
#include <xlocale.h>
#endif
#ifdef _WIN32
#include <windows.h>
#include <direct.h>
#include <io.h>
#else
#include <unistd.h>
#endif

_Thread_local const char *cg_phase = "arguments", *cg_module = "";
_Thread_local bool cg_events = false;
/* Thread-local bump arena. Checkpoints reclaim temporary expressions without
 * sending every small allocation through the process-wide malloc allocator. */
typedef union Allocation Allocation;
union Allocation { struct { Allocation *previous; size_t used, capacity; } block; max_align_t alignment; };
typedef struct { Allocation *block; size_t used; } Checkpoint;
static _Thread_local Allocation *allocations;
static atomic_bool registered;
static _Thread_local bool allocation_ready;
static _Thread_local CgFailure *failure_target;
void cg_failure_target(CgFailure *target) { failure_target = target; }
#ifdef __APPLE__
static _Thread_local locale_t numeric_locale;
#endif
void cg_thread_finish(void) {
    cg_rewind(NULL);
#ifdef __APPLE__
    if(numeric_locale) {freelocale(numeric_locale);numeric_locale=NULL;}
#endif
}
static void release(void) { cg_thread_finish(); }
static int format_text(char *out,size_t size,const char *format,va_list arguments) {
#ifdef __APPLE__
    /* Darwin localeconv_l serializes the shared global locale even for integer
     * formats. Each worker owns its locale and never changes process locale. */
    if(!numeric_locale) {
        numeric_locale=duplocale(LC_GLOBAL_LOCALE);
        if(!numeric_locale)cg_fail(4,"cannot create native worker formatting locale");
    }
    return vsnprintf_l(out,size,numeric_locale,format,arguments);
#else
    return vsnprintf(out,size,format,arguments);
#endif
}
void *cg_alloc(size_t count, size_t size) {
    int saved_errno = errno;
    if (!allocation_ready) {
        if (!atomic_exchange(&registered, true)) { if (atexit(release)) cg_fail(4, "cannot register allocation cleanup"); }
        allocation_ready = true;
    }
    if (size && count > (SIZE_MAX - sizeof(Allocation)) / size) cg_fail(4, "allocation size overflow");
    size_t bytes=count*size,alignment=_Alignof(max_align_t);
    if(bytes>SIZE_MAX-(alignment-1))cg_fail(4,"allocation alignment overflow");
    size_t padded=(bytes+alignment-1)/alignment*alignment;
    if(!padded)padded=alignment;
    if(!allocations||padded>allocations->block.capacity-allocations->block.used) {
        size_t capacity=padded>65536?padded:65536;
        if(capacity>SIZE_MAX-sizeof(Allocation))cg_fail(4,"arena allocation overflow");
        Allocation *next=malloc(sizeof(*next)+capacity);
        if(!next)cg_fail(4,"not enough memory");
        next->block.previous=allocations;next->block.used=0;next->block.capacity=capacity;allocations=next;
    }
    unsigned char *data=(unsigned char*)(allocations+1)+allocations->block.used;
    allocations->block.used+=padded;memset(data,0,bytes);errno=saved_errno;return data;
}
void *cg_mark(void) {
    Allocation *block=allocations;size_t used=block?block->block.used:0;
    Checkpoint *mark=cg_alloc(1,sizeof(*mark));
    *mark=(Checkpoint){block?block:allocations,used};return mark;
}
void cg_rewind(void *mark) {
    Checkpoint target=mark?*(Checkpoint*)mark:(Checkpoint){0};
    while(allocations!=target.block) {
        if(!allocations)cg_fail(4,"invalid allocation checkpoint");
        Allocation *previous=allocations->block.previous;free(allocations);allocations=previous;
    }
    if(allocations)allocations->block.used=target.used;
}
char *cg_format(const char *format, ...) {
    va_list ap, copy; va_start(ap, format); va_copy(copy, ap);
    int n = format_text(NULL, 0, format, copy); va_end(copy);
    if (n < 0) cg_fail(4, "text formatting failed");
    char *s = cg_alloc((size_t)n + 1, 1); format_text(s, (size_t)n + 1, format, ap); va_end(ap);
    return s;
}
char *cg_string(const char *s, size_t n) {
    if (n == SIZE_MAX) cg_fail(4, "string size overflow");
    char *p = cg_alloc(n + 1, 1); memcpy(p, s, n); return p;
}
_Noreturn void cg_fail(int code, const char *format, ...) {
    if (failure_target) {
        va_list arguments; va_start(arguments, format);
        vsnprintf(failure_target->message, sizeof(failure_target->message), format, arguments); va_end(arguments);
        failure_target->code = code;
        snprintf(failure_target->phase, sizeof(failure_target->phase), "%s", cg_phase);
        snprintf(failure_target->module, sizeof(failure_target->module), "%s", cg_module);
        longjmp(failure_target->jump, 1);
    }
    static _Thread_local bool failing;
    if (failing) { fputs("bdsp_codegen: error reporting failed\n", stderr); exit(code); }
    failing = true;
    char message[1024]; va_list ap; va_start(ap, format); vsnprintf(message, sizeof(message), format, ap); va_end(ap);
    if (cg_events) {
        Buffer b = {0}; cg_printf(&b, "{\"event\":\"error\",\"phase\":"); cg_json_string(&b, cg_phase);
        cg_printf(&b, ",\"module\":"); cg_json_string(&b, cg_module);
        cg_printf(&b, ",\"message\":"); cg_json_string(&b, message);
        cg_printf(&b, ",\"code\":%d}\n", code); fwrite(b.data, 1, b.size, stdout); fflush(stdout);
    }
    fprintf(stderr, "bdsp_codegen [%s%s%s]: error: %s\n", cg_phase, *cg_module ? "/" : "", cg_module, message);
    exit(code);
}
void cg_buffer(Buffer *b, const void *data, size_t n) {
    if (n > SIZE_MAX - b->size - 1) cg_fail(4, "buffer size overflow");
    size_t need = b->size + n + 1;
    if (need > b->capacity) {
        size_t capacity = b->capacity ? b->capacity : 256;
        while (capacity < need) { if (capacity > SIZE_MAX / 2) { capacity = need; break; } capacity *= 2; }
        unsigned char *p = cg_alloc(capacity, 1);
        if (b->size) memcpy(p, b->data, b->size);
        b->data = p; b->capacity = capacity;
    }
    if (n) memcpy(b->data + b->size, data, n);
    b->size += n; b->data[b->size] = 0;
}
void cg_printf(Buffer *b, const char *format, ...) {
    va_list ap, copy; va_start(ap, format); va_copy(copy, ap);
    int n = format_text(NULL, 0, format, copy); va_end(copy);
    if (n < 0) cg_fail(4, "text formatting failed");
    char *s = cg_alloc((size_t)n + 1, 1); format_text(s, (size_t)n + 1, format, ap); va_end(ap);
    cg_buffer(b, s, (size_t)n);
}
uint16_t cg_u16(const unsigned char *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
uint32_t cg_u32(const unsigned char *p) { return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
uint64_t cg_u64(const unsigned char *p) { return cg_u32(p) | (uint64_t)cg_u32(p + 4) << 32; }
void cg_put64(unsigned char *p, uint64_t n) { for (unsigned i = 0; i < 8; i++) p[i] = (unsigned char)(n >> (8 * i)); }
void cg_range(size_t size, uint64_t off, uint64_t n, const char *what) {
    if (off > size || n > size - off) cg_fail(4, "%s is outside the module", what);
}
uint64_t cg_number(const char *s) {
    if (!*s || *s == '-' || *s == '+') cg_fail(2, "expected an unsigned integer");
    char *end; errno = 0; uintmax_t n = strtoumax(s, &end, 0);
    if (errno || *end || n > UINT64_MAX) cg_fail(2, "invalid unsigned integer");
    return (uint64_t)n;
}
#ifdef _WIN32
static wchar_t *wide(const char *s) {
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0);
    if (!n) cg_fail(5, "invalid UTF-8 path");
    wchar_t *p = cg_alloc((size_t)n, sizeof(*p)); MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, p, n); return p;
}
static FILE *open_file(const char *path, const char *mode) { return _wfopen(wide(path), wide(mode)); }
#else
static FILE *open_file(const char *path, const char *mode) { return fopen(path, mode); }
#endif
Buffer cg_read(const char *path) {
    FILE *f = open_file(path, "rb");
    if (!f) cg_fail(5, "cannot open input file (%s)", strerror(errno));
    if (fseek(f, 0, SEEK_END)) cg_fail(5, "cannot determine input size");
    long length = ftell(f);
    if (length < 0 || (uintmax_t)length >= SIZE_MAX) cg_fail(5, "invalid input size");
    if (fseek(f, 0, SEEK_SET)) cg_fail(5, "cannot rewind input file");
    Buffer b = {cg_alloc((size_t)length + 1, 1), (size_t)length, (size_t)length + 1};
    if (fread(b.data, 1, b.size, f) != b.size || ferror(f)) cg_fail(5, "cannot read input file");
    fclose(f); return b;
}
char *cg_join(const char *folder, const char *name) {
    Buffer b = {0}; cg_printf(&b, "%s/%s", folder, name); return (char *)b.data;
}
static bool separator(char c) {
#ifdef _WIN32
    return c == '/' || c == '\\';
#else
    return c == '/';
#endif
}
void cg_mkdirs(const char *path) {
    char *s = cg_string(path, strlen(path));
    size_t start = 1;
#ifdef _WIN32
    /* Drive and UNC share roots already exist; mkdir must start below them. */
    size_t length = strlen(s);
    if (length >= 3 && s[1] == ':' && separator(s[2])) {
        if (length == 3) return;
        start = 3;
    } else if (length >= 2 && separator(s[0]) && separator(s[1])) {
        start = 2;
        while (s[start] && !separator(s[start])) start++;
        if (!s[start]) return;
        start++;
        while (s[start] && !separator(s[start])) start++;
        if (!s[start]) return;
        start++;
    }
#endif
    for (size_t i = start; ; i++) {
        if (!s[i] || separator(s[i])) {
            char saved = s[i]; s[i] = 0;
#ifdef _WIN32
            int rc = _wmkdir(wide(s));
#else
            int rc = mkdir(s, 0755);
#endif
            if (rc && errno != EEXIST) cg_fail(5, "cannot create output directory (%s)", strerror(errno));
            s[i] = saved; if (!saved) break;
        }
    }
}
void cg_write(const char *path, const void *data, size_t size) {
    /* Only replace a completed file; preserve timestamps when content matches. */
    FILE *old = open_file(path, "rb");
    if (old) {
        unsigned char block[8192]; size_t offset = 0; bool same = true;
        while (offset < size) {
            size_t n = size - offset; if (n > sizeof(block)) n = sizeof(block);
            if (fread(block, 1, n, old) != n || memcmp(block, (const unsigned char *)data + offset, n)) { same = false; break; }
            offset += n;
        }
        if (same && fgetc(old) != EOF) same = false;
        if (ferror(old)) same = false;
        fclose(old); if (same) return;
    }
#ifdef _WIN32
    unsigned long process = GetCurrentProcessId();
#else
    unsigned long process = (unsigned long)getpid();
#endif
    Buffer name = {0}; cg_printf(&name, "%s.%lu.tmp", path, process);
    const char *temporary = (char *)name.data;
    FILE *f = open_file(temporary, "wbx");
    if (!f) cg_fail(5, "cannot create output file (%s)", strerror(errno));
    bool failed = fwrite(data, 1, size, f) != size;
    if (fclose(f)) failed = true;
    if (failed) {
#ifdef _WIN32
        _wremove(wide(temporary));
#else
        remove(temporary);
#endif
        cg_fail(5, "cannot finish output file");
    }
#ifdef _WIN32
    if (!MoveFileExW(wide(temporary), wide(path), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        _wremove(wide(temporary)); cg_fail(5, "cannot publish output file");
    }
#else
    if (rename(temporary, path)) {
        int failure = errno; remove(temporary);
        cg_fail(5, "cannot publish output file (%s)", strerror(failure));
    }
#endif
}
static uint64_t hash_key(const char *key) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (; *key; key++) { h ^= (unsigned char)*key; h *= UINT64_C(1099511628211); }
    return h;
}
static size_t binding_slot(const Bindings *b, const char *key) {
    size_t slot = (size_t)hash_key(key) & (b->index_capacity - 1);
    while (b->index[slot] && strcmp(b->items[b->index[slot] - 1].key, key)) slot = (slot + 1) & (b->index_capacity - 1);
    return slot;
}
void cg_set(Bindings *b, const char *key, uint64_t value) {
    if (!b->index_capacity || b->size >= b->index_capacity / 2) {
        b->index_capacity = b->index_capacity ? b->index_capacity * 2 : 64;
        b->index = cg_alloc(b->index_capacity, sizeof(*b->index));
        for (size_t i = 0; i < b->size; i++) b->index[binding_slot(b, b->items[i].key)] = i + 1;
    }
    size_t slot = binding_slot(b, key);
    if (b->index[slot]) { b->items[b->index[slot] - 1].value = value; return; }
    if (b->size == b->capacity) {
        size_t capacity = b->capacity ? b->capacity * 2 : 32;
        Binding *p = cg_alloc(capacity, sizeof(*p));
        if (b->size) memcpy(p, b->items, b->size * sizeof(*p));
        b->items = p; b->capacity = capacity;
    }
    b->items[b->size++] = (Binding){cg_string(key, strlen(key)), value};
    b->index[slot] = b->size;
}
bool cg_get(const Bindings *b, const char *key, uint64_t *value) {
    if (!b->index_capacity) return false;
    size_t i = b->index[binding_slot(b, key)];
    if (!i) return false;
    *value = b->items[i - 1].value; return true;
}
void cg_push(Strings *s, char *value) {
    if (s->size == s->capacity) {
        size_t capacity = s->capacity ? s->capacity * 2 : 32;
        char **p = cg_alloc(capacity, sizeof(*p));
        if (s->size) memcpy(p, s->items, s->size * sizeof(*p));
        s->items = p; s->capacity = capacity;
    }
    s->items[s->size++] = value;
}
