/* SPDX-License-Identifier: MIT
 * Native BDSP generator. Container semantics follow the MIT LASRecomp NSO
 * loader and this project's mkimg.py; see THIRD_PARTY_NOTICES.md. */
#ifndef BDSP_CODEGEN_H
#define BDSP_CODEGEN_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

typedef struct { unsigned char *data; size_t size, capacity; } Buffer;
typedef struct { char *key; uint64_t value; } Binding;
typedef struct { Binding *items; size_t size, capacity; size_t *index, index_capacity; } Bindings;
typedef struct { char **items; size_t size, capacity; } Strings;
typedef struct { uint32_t offset, size; } Segment;
typedef struct { char *name; uint8_t info; uint16_t section; uint64_t value, size; } Symbol;
typedef struct { uint64_t offset, symbol; uint32_t type; int64_t addend; } Relocation;
typedef struct {
    unsigned char *image;
    size_t size;
    Segment segments[3];
    uint32_t bss_size, eh_start, eh_end;
    unsigned char build_id[32];
    uint64_t init, init_array, init_array_size;
    Symbol *symbols; size_t symbol_count;
    Relocation *relocations; size_t relocation_count;
} Nso;

extern _Thread_local const char *cg_phase, *cg_module;
extern _Thread_local bool cg_events;
_Noreturn void cg_fail(int code, const char *format, ...);
void *cg_alloc(size_t count, size_t size);
char *cg_string(const char *source, size_t size);
char *cg_format(const char *format, ...);
void *cg_mark(void);
void cg_rewind(void *mark);
void cg_thread_finish(void);
void cg_buffer(Buffer *buffer, const void *data, size_t size);
void cg_printf(Buffer *buffer, const char *format, ...);
void cg_json_string(Buffer *buffer, const char *string);
char *cg_utf8_normalize(const char *string);
void cg_json_bindings(Buffer *buffer, const Bindings *bindings);
void cg_read_bindings(Bindings *bindings, const char *path);
void cg_set(Bindings *bindings, const char *key, uint64_t value);
bool cg_get(const Bindings *bindings, const char *key, uint64_t *value);
void cg_push(Strings *strings, char *string);
Buffer cg_read(const char *path);
char *cg_join(const char *folder, const char *name);
void cg_mkdirs(const char *path);
void cg_write(const char *path, const void *data, size_t size);
uint64_t cg_number(const char *text);
uint16_t cg_u16(const unsigned char *p);
uint32_t cg_u32(const unsigned char *p);
uint64_t cg_u64(const unsigned char *p);
void cg_put64(unsigned char *p, uint64_t value);
void cg_range(size_t size, uint64_t offset, uint64_t length, const char *what);
Nso cg_nso(const char *path);
int cg_generate(int argc, char **argv);
void cg_prune_chunks(const char *directory, const char *module, const Strings *written);
int cg_image(int argc, char **argv);
typedef struct { uint64_t *items; size_t size, capacity; } Addresses;
void cg_address(Addresses *a, uint64_t value);
void cg_unique(Addresses *a);
void cg_exception_addresses(const Nso *n, uint64_t base, Addresses *boundaries, Addresses *landing_pads);
int cg_inspect(int argc, char **argv);
#endif
