/* SPDX-License-Identifier: MIT. Native equivalent of this project's mkimg.py. */
#include "codegen.h"
#include <ctype.h>
#include <inttypes.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

static void lines(Strings *result, const char *path, bool strip) {
    Buffer data = cg_read(path); char *p = (char *)data.data;
    for (;;) {
        char *end = strchr(p, '\n'); if (end) *end = 0;
        size_t length = strlen(p);
        if (length && p[length - 1] == '\r') p[--length] = 0;
        bool comment = *p == '#';
        if (strip) { while (*p && isspace((unsigned char)*p)) p++; length = strlen(p); while (length && isspace((unsigned char)p[length - 1])) p[--length] = 0; }
        if (*p && (!strip || !comment)) cg_push(result, cg_string(p, strlen(p)));
        if (!end) break;
        p = end + 1;
    }
}
static uint64_t add(uint64_t base, int64_t offset) {
    if (offset >= 0) { if (base > UINT64_MAX - (uint64_t)offset) cg_fail(4, "relocated address overflow"); return base + (uint64_t)offset; }
    uint64_t magnitude = (uint64_t)(-(offset + 1)) + 1;
    if (base < magnitude) cg_fail(4, "relocated address underflow");
    return base - magnitude;
}
static uint64_t plus(uint64_t base, uint64_t value) {
    if (base > UINT64_MAX - value) cg_fail(4, "module address overflow");
    return base + value;
}
static uint64_t slot(Strings *hle, Bindings *indices, const char *name, uint64_t base) {
    uint64_t index;
    if (!cg_get(indices, name, &index)) {
        index = hle->size; cg_push(hle, cg_string(name, strlen(name))); cg_set(indices, name, index);
    }
    if (index > UINT64_MAX / 16) cg_fail(4, "HLE slot overflow");
    return plus(base, index * 16);
}
static bool interposed(const char *name) {
    return !strncmp(name, "_Znw", 4) || !strncmp(name, "_Zna", 4) ||
           !strncmp(name, "_Zdl", 4) || !strncmp(name, "_Zda", 4) ||
           !strncmp(name, "_ZTI", 4) || !strncmp(name, "_ZTS", 4);
}
int cg_image(int argc, char **argv) {
    if (argc < 2) cg_fail(2, "image requires an NSO and module name");
    const char *nso_path = argv[0], *name = argv[1], *out = NULL, *hle_list = NULL;
    const char *interpose_path = NULL, *regex = "^(_Zn[wa]|_Zd[la]|_ZT[IS])";
    uint64_t base = 0, hle_base = UINT64_C(0x7080000000); bool have_base = false;
    Strings link_paths = {0}; cg_module = name;
    if (!*name || strchr(name, '/') || strchr(name, '\\') || !strcmp(name, ".") || !strcmp(name, "..")) cg_fail(2, "invalid module name");
    for (int i = 2; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--events=jsonl")) { cg_events = true; continue; }
        if (i + 1 >= argc) cg_fail(2, "missing value for image option");
        const char *value = argv[++i];
        if (!strcmp(arg, "--base")) { base = cg_number(value); have_base = true; }
        else if (!strcmp(arg, "--out")) out = value;
        else if (!strcmp(arg, "--hle-base")) hle_base = cg_number(value);
        else if (!strcmp(arg, "--link")) cg_push(&link_paths, cg_string(value, strlen(value)));
        else if (!strcmp(arg, "--hle-list")) hle_list = value;
        else if (!strcmp(arg, "--interpose-from")) interpose_path = value;
        else if (!strcmp(arg, "--interpose-regex")) regex = value;
        else cg_fail(2, "unknown image option");
    }
    if (!have_base || !out || !*out) cg_fail(2, "image requires --base and --out");
    if (strcmp(regex, "^(_Zn[wa]|_Zd[la]|_ZT[IS])")) cg_fail(2, "custom interposition regex is not supported by this generator");
    Nso n = cg_nso(nso_path); cg_phase = "images";
    Bindings linked = {0}, interpose = {0}, forced = {0}, exports = {0}, indices = {0};
    Strings hle = {0};
    if (hle_list) {
        Strings names = {0}; lines(&names, hle_list, true);
        for (size_t i = 0; i < names.size; i++) cg_set(&forced, names.items[i], 1);
    }
    if (interpose_path) cg_read_bindings(&interpose, interpose_path);
    for (size_t i = 0; i < link_paths.size; i++) cg_read_bindings(&linked, link_paths.items[i]);
    char *hle_path = cg_join(out, "hle.txt");
    /* An absent HLE file is expected in pass one; unreadable existing files
       must remain errors. Probe without creating anything. */
#ifdef _WIN32
    /* cg_read handles wide paths; existence is checked via Win32 below. */
    int wlen = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, hle_path, -1, NULL, 0);
    wchar_t *wpath = cg_alloc((size_t)wlen, sizeof(*wpath));
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, hle_path, -1, wpath, wlen);
    bool exists = GetFileAttributesW(wpath) != INVALID_FILE_ATTRIBUTES;
#else
    bool exists = access(hle_path, F_OK) == 0;
#endif
    if (exists) lines(&hle, hle_path, false);
    for (size_t i = 0; i < hle.size; i++) cg_set(&indices, hle.items[i], i);
    for (size_t i = 0; i < n.symbol_count; i++) {
        Symbol s = n.symbols[i]; if (*s.name && s.section) cg_set(&exports, s.name, plus(base, s.value));
    }
    uint64_t relative = 0, bound = 0, linked_count = 0, hle_count = 0, weak = 0, interposed_count = 0;
    for (size_t i = 0; i < n.relocation_count; i++) {
        Relocation r = n.relocations[i]; uint64_t value, unused;
        if (r.type == 1027) { value = add(base, r.addend); relative++; }
        else if (r.type == 257 || r.type == 1025 || r.type == 1026) {
            Symbol s = n.symbols[r.symbol]; int64_t increment = r.type == 257 ? r.addend : 0;
            if (cg_get(&forced, s.name, &unused)) { value = add(slot(&hle, &indices, s.name, hle_base), increment); hle_count++; }
            else if (strcmp(name, "main") && interposed(s.name) && cg_get(&interpose, s.name, &value)) { value = add(value, increment); interposed_count++; }
            else if (s.section) { value = add(plus(base, s.value), increment); bound++; }
            else if (cg_get(&linked, s.name, &value)) { value = add(value, increment); linked_count++; }
            else if ((s.info >> 4) == 2) { value = 0; weak++; }
            else { value = slot(&hle, &indices, s.name, hle_base); hle_count++; }
        } else continue;
        cg_put64(n.image + r.offset, value);
    }
    Buffer mod = {0}, json = {0}, hle_text = {0}, file = {0};
    cg_printf(&mod, "%s 0x%" PRIx64 " 0x%x 0x%" PRIx64 " 0x%x 0x%" PRIx64 " 0x%x 0x%" PRIx64 " 0x%zx 0x%" PRIx64 " 0x%" PRIx64 " 0x%" PRIx64 "\n",
              name, base, n.segments[0].offset, (uint64_t)n.segments[0].offset + n.segments[0].size,
              n.segments[1].offset, (uint64_t)n.segments[1].offset + n.segments[1].size,
              n.segments[2].offset, (uint64_t)n.segments[2].offset + n.segments[2].size,
              n.size, n.init, n.init_array, n.init_array_size);
    cg_json_bindings(&json, &exports);
    for (size_t i = 0; i < hle.size; i++) cg_printf(&hle_text, "%s\n", hle.items[i]);
    if (!hle.size) cg_buffer(&hle_text, "\n", 1);
    cg_mkdirs(out);
    cg_printf(&file, "%s.img", name); cg_write(cg_join(out, (char *)file.data), n.image, n.size);
    file.size = 0; cg_printf(&file, "%s.mod", name); cg_write(cg_join(out, (char *)file.data), mod.data, mod.size);
    file.size = 0; cg_printf(&file, "%s.syms.json", name); cg_write(cg_join(out, (char *)file.data), json.data, json.size);
    cg_write(hle_path, hle_text.data, hle_text.size);
    if (cg_events) {
        printf("{\"event\":\"progress\",\"phase\":\"images\",\"completed\":1,\"total\":1}\n");
    } else printf("%s image %zu relocations relative=%" PRIu64 " bound=%" PRIu64 " linked=%" PRIu64 " hle=%" PRIu64 " weak0=%" PRIu64 " interposed=%" PRIu64 " HLE slots total %zu\n",
                  name, n.size, relative, bound, linked_count, hle_count, weak, interposed_count, hle.size);
    return 0;
}
