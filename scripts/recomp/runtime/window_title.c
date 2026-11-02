// Window title of the game window, see window_title.h. Portable C, no SDL; the test (test/window_title_test.c) runs it on every platform.
#include "window_title.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#elif defined(_WIN32)
#include <windows.h>
#endif

static size_t utf8_cut(const char *s, size_t max) {
    size_t n = strlen(s);
    if (n <= max) return n;
    while (max > 0 && ((unsigned char)s[max] & 0xC0) == 0x80) max--;
    return max;
}

static void append(char *out, size_t capacity, size_t *used, const char *text, size_t limit) {
    size_t room = capacity - 1 - *used;
    size_t n = utf8_cut(text, limit < room ? limit : room);
    memcpy(out + *used, text, n);
    *used += n;
    out[*used] = 0;
}

void bdsp_build_window_title(char *out, size_t capacity, const char *game_name, const char *mod_name, const char *tag) {
    if (!out || !capacity) return;
    size_t used = 0;
    out[0] = 0;
    append(out, capacity, &used, game_name && *game_name ? game_name : BDSP_TITLE_FALLBACK, 255);
    if (mod_name && *mod_name) {
        append(out, capacity, &used, " - ", 3);
        append(out, capacity, &used, mod_name, 100);
    }
    if (tag && *tag) {
        append(out, capacity, &used, " [", 2);
        append(out, capacity, &used, tag, 100);
        append(out, capacity, &used, "]", 1);
    }
}

typedef struct { const char *p, *end; } json_cursor;

static void skip_space(json_cursor *c) {
    while (c->p < c->end && (*c->p == ' ' || *c->p == '\t' || *c->p == '\n' || *c->p == '\r')) c->p++;
}

static int hex4(json_cursor *c, unsigned *value) {
    if (c->end - c->p < 4) return 0;
    unsigned v = 0;
    for (int i = 0; i < 4; i++) {
        char h = *c->p++;
        v <<= 4;
        if (h >= '0' && h <= '9') v |= (unsigned)(h - '0');
        else if (h >= 'a' && h <= 'f') v |= (unsigned)(h - 'a' + 10);
        else if (h >= 'A' && h <= 'F') v |= (unsigned)(h - 'A' + 10);
        else return 0;
    }
    *value = v;
    return 1;
}

static size_t put_utf8(char *out, unsigned cp) {
    if (cp < 0x80) { out[0] = (char)cp; return 1; }
    if (cp < 0x800) { out[0] = (char)(0xC0 | cp >> 6); out[1] = (char)(0x80 | (cp & 0x3F)); return 2; }
    if (cp < 0x10000) {
        out[0] = (char)(0xE0 | cp >> 12); out[1] = (char)(0x80 | (cp >> 6 & 0x3F)); out[2] = (char)(0x80 | (cp & 0x3F));
        return 3;
    }
    out[0] = (char)(0xF0 | cp >> 18); out[1] = (char)(0x80 | (cp >> 12 & 0x3F));
    out[2] = (char)(0x80 | (cp >> 6 & 0x3F)); out[3] = (char)(0x80 | (cp & 0x3F));
    return 4;
}

// Decodes a JSON string into out (NUL terminated, cut at capacity); out may be NULL to skip it. 0 on a syntax error.
static int parse_string(json_cursor *c, char *out, size_t capacity) {
    if (c->p >= c->end || *c->p != '"') return 0;
    c->p++;
    size_t used = 0;
    while (c->p < c->end && *c->p != '"') {
        char buf[4];
        size_t n = 1;
        unsigned char ch = (unsigned char)*c->p++;
        if (ch < 0x20) return 0;
        buf[0] = (char)ch;
        if (ch == '\\') {
            if (c->p >= c->end) return 0;
            char e = *c->p++;
            switch (e) {
            case '"': case '\\': case '/': buf[0] = e; break;
            case 'b': buf[0] = '\b'; break;
            case 'f': buf[0] = '\f'; break;
            case 'n': buf[0] = '\n'; break;
            case 'r': buf[0] = '\r'; break;
            case 't': buf[0] = '\t'; break;
            case 'u': {
                unsigned cp;
                if (!hex4(c, &cp)) return 0;
                if (cp >= 0xD800 && cp < 0xDC00) {
                    unsigned low;
                    if (c->end - c->p < 2 || c->p[0] != '\\' || c->p[1] != 'u') return 0;
                    c->p += 2;
                    if (!hex4(c, &low) || low < 0xDC00 || low > 0xDFFF) return 0;
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                } else if (cp >= 0xDC00 && cp <= 0xDFFF) return 0;
                n = put_utf8(buf, cp);
                break;
            }
            default: return 0;
            }
        }
        if (out && used + n < capacity) { memcpy(out + used, buf, n); used += n; }
    }
    if (c->p >= c->end) return 0;
    c->p++;
    if (out && capacity) out[used] = 0;
    return 1;
}

static int skip_value(json_cursor *c, int depth);

static int skip_container(json_cursor *c, char close, int depth) {
    c->p++;
    skip_space(c);
    if (c->p < c->end && *c->p == close) { c->p++; return 1; }
    for (;;) {
        skip_space(c);
        if (close == '}') {
            if (!parse_string(c, NULL, 0)) return 0;
            skip_space(c);
            if (c->p >= c->end || *c->p++ != ':') return 0;
        }
        if (!skip_value(c, depth + 1)) return 0;
        skip_space(c);
        if (c->p >= c->end) return 0;
        if (*c->p == ',') { c->p++; continue; }
        if (*c->p == close) { c->p++; return 1; }
        return 0;
    }
}

static int skip_value(json_cursor *c, int depth) {
    skip_space(c);
    if (c->p >= c->end || depth > 16) return 0;
    if (*c->p == '"') return parse_string(c, NULL, 0);
    if (*c->p == '{') return skip_container(c, '}', depth);
    if (*c->p == '[') return skip_container(c, ']', depth);
    const char *start = c->p;
    while (c->p < c->end && (isalnum((unsigned char)*c->p) || *c->p == '-' || *c->p == '+' || *c->p == '.')) c->p++;
    return c->p > start;
}

static int parse_titles(json_cursor *c, bdsp_title_set *set) {
    c->p++;
    skip_space(c);
    if (c->p < c->end && *c->p == '}') { c->p++; return 1; }
    for (;;) {
        char key[64], name[256];
        skip_space(c);
        if (!parse_string(c, key, sizeof key)) return 0;
        skip_space(c);
        if (c->p >= c->end || *c->p++ != ':') return 0;
        skip_space(c);
        if (c->p < c->end && *c->p == '"') {
            if (!parse_string(c, name, sizeof name)) return 0;
            if (strlen(key) < sizeof set->entry[0].id && *name && set->count < BDSP_TITLE_LOCALES) {
                strcpy(set->entry[set->count].id, key);
                strcpy(set->entry[set->count].name, name);
                set->count++;
            }
        } else if (!skip_value(c, 2)) return 0;
        skip_space(c);
        if (c->p >= c->end) return 0;
        if (*c->p == ',') { c->p++; continue; }
        if (*c->p == '}') { c->p++; return 1; }
        return 0;
    }
}

bool bdsp_title_set_parse(const char *json, size_t length, bdsp_title_set *set) {
    memset(set, 0, sizeof *set);
    json_cursor c = {json, json + length};
    if (length >= 3 && (unsigned char)json[0] == 0xEF && (unsigned char)json[1] == 0xBB && (unsigned char)json[2] == 0xBF) c.p += 3;
    skip_space(&c);
    if (c.p >= c.end || *c.p != '{') return false;
    c.p++;
    skip_space(&c);
    if (c.p < c.end && *c.p == '}') return true;
    for (;;) {
        char key[32];
        skip_space(&c);
        if (!parse_string(&c, key, sizeof key)) return false;
        skip_space(&c);
        if (c.p >= c.end || *c.p++ != ':') return false;
        skip_space(&c);
        if (!strcmp(key, "mod") && c.p < c.end && *c.p == '"') {
            if (!parse_string(&c, set->mod, sizeof set->mod)) return false;
        } else if (!strcmp(key, "titles") && c.p < c.end && *c.p == '{') {
            if (!parse_titles(&c, set)) return false;
        } else if (!skip_value(&c, 1)) return false;
        skip_space(&c);
        if (c.p >= c.end) return false;
        if (*c.p == ',') { c.p++; continue; }
        return *c.p == '}';
    }
}

static int has_region(const char *region, const char *const *list) {
    for (; *list; list++) if (!strcmp(region, *list)) return 1;
    return 0;
}

int bdsp_title_candidates(const char *tag, char out[3][12]) {
    char lang[16] = "", script[8] = "", region[8] = "";
    size_t n = 0;
    char buf[40];
    for (; tag && tag[n] && tag[n] != '.' && tag[n] != '@' && n < sizeof buf - 1; n++) buf[n] = tag[n] == '_' ? '-' : tag[n];
    buf[n] = 0;
    int part = 0;
    for (char *s = strtok(buf, "-"); s; s = strtok(NULL, "-"), part++) {
        size_t len = strlen(s);
        if (part == 0) { if (len < sizeof lang) strcpy(lang, s); }
        else if (len == 4 && !script[0]) strcpy(script, s);
        else if ((len == 2 || len == 3) && !region[0]) strcpy(region, s);
    }
    for (char *s = lang; *s; s++) *s = (char)tolower((unsigned char)*s);
    for (char *s = script; *s; s++) *s = (char)tolower((unsigned char)*s);
    for (char *s = region; *s; s++) *s = (char)toupper((unsigned char)*s);
    const char *list[3] = {NULL, NULL, NULL};
    static const char *const british[] = {"GB", "AU", "NZ", "IE", "ZA", "IN", "SG", "HK", NULL};
    static const char *const traditional[] = {"TW", "HK", "MO", NULL};
    if (!strcmp(lang, "en")) { if (has_region(region, british)) { list[0] = "en-GB"; list[1] = "en-US"; } else { list[0] = "en-US"; list[1] = "en-GB"; } }
    else if (!strcmp(lang, "es")) { if (region[0] && strcmp(region, "ES")) { list[0] = "es-419"; list[1] = "es-ES"; } else { list[0] = "es-ES"; list[1] = "es-419"; } }
    else if (!strcmp(lang, "pt")) { if (!strcmp(region, "BR")) { list[0] = "pt-BR"; list[1] = "pt-PT"; } else { list[0] = "pt-PT"; list[1] = "pt-BR"; } }
    else if (!strcmp(lang, "fr")) { if (!strcmp(region, "CA")) { list[0] = "fr-CA"; list[1] = "fr"; } else { list[0] = "fr"; list[1] = "fr-CA"; } }
    else if (!strcmp(lang, "zh")) {
        int hant = script[0] ? !strcmp(script, "hant") : has_region(region, traditional);
        list[0] = hant ? "zh-Hant" : "zh-Hans"; list[1] = hant ? "zh-Hans" : "zh-Hant";
    }
    else if (!strcmp(lang, "de") || !strcmp(lang, "ja") || !strcmp(lang, "ko") || !strcmp(lang, "it") || !strcmp(lang, "nl") || !strcmp(lang, "ru")) list[0] = lang;
    int count = 0;
    for (int i = 0; i < 2 && list[i]; i++) { snprintf(out[count], 12, "%s", list[i]); count++; }
    return count;
}

static const char *find_name(const bdsp_title_set *set, const char *id) {
    for (int i = 0; i < set->count; i++) if (!strcmp(set->entry[i].id, id)) return set->entry[i].name;
    return NULL;
}

const char *bdsp_pick_game_name(const bdsp_title_set *set, const char *const *languages, int count) {
    char candidates[3][12];
    for (int i = 0; i < count; i++) {
        int found = bdsp_title_candidates(languages[i], candidates);
        for (int k = 0; k < found; k++) {
            const char *name = find_name(set, candidates[k]);
            if (name) return name;
        }
    }
    const char *name = find_name(set, "en-US");
    if (name) return name;
    return set->count ? set->entry[0].name : NULL;
}

int bdsp_system_languages(char languages[][32], int capacity) {
    int count = 0;
    const char *override = getenv("BDSP_UI_LANGUAGES");   // test switch: "de-DE:en-US" instead of the system's list
    if (override && *override) {
        while (*override && count < capacity) {
            size_t n = strcspn(override, ":,;");
            if (n && n < 32) {
                memcpy(languages[count], override, n);
                languages[count++][n] = 0;
            }
            override += n + (override[n] != 0);
        }
        return count;
    }
#ifdef __APPLE__
    CFArrayRef list = CFLocaleCopyPreferredLanguages();
    if (list) {
        for (CFIndex i = 0; i < CFArrayGetCount(list) && count < capacity; i++)
            if (CFStringGetCString(CFArrayGetValueAtIndex(list, i), languages[count], 32, kCFStringEncodingUTF8)) count++;
        CFRelease(list);
    }
#elif defined(_WIN32)
    ULONG number = 0, size = 0;
    if (GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, &number, NULL, &size) && size) {
        WCHAR *wide = malloc(size * sizeof *wide);
        if (wide && GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, &number, wide, &size)) {
            for (const WCHAR *w = wide; *w && count < capacity; w += wcslen(w) + 1) {
                int k = 0;
                for (; w[k] && k < 31; k++) languages[count][k] = w[k] < 128 ? (char)w[k] : '?';
                languages[count][k] = 0;
                count++;
            }
        }
        free(wide);
    }
#else
    const char *variables[] = {"LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"};
    for (size_t v = 0; v < sizeof variables / sizeof *variables && count < capacity; v++) {
        const char *value = getenv(variables[v]);
        while (value && *value && count < capacity) {
            size_t n = strcspn(value, ":");
            if (n && n < 32) {
                memcpy(languages[count], value, n);
                languages[count][n] = 0;
                if (strcmp(languages[count], "C") && strcmp(languages[count], "POSIX")) count++;
            }
            value += n + (value[n] == ':');
        }
    }
#endif
    return count;
}

static char *read_text(const char *path, size_t *length) {
#ifdef _WIN32
    wchar_t wide[1024];
    FILE *f = MultiByteToWideChar(CP_UTF8, 0, path, -1, wide, 1024) ? _wfopen(wide, L"rb") : NULL;
#else
    FILE *f = fopen(path, "rb");
#endif
    if (!f) return NULL;
    char *data = malloc(65537);
    size_t n = data ? fread(data, 1, 65536, f) : 0;
    fclose(f);
    if (!data || !n || n == 65536) { free(data); return NULL; }
    data[n] = 0;
    *length = n;
    return data;
}

static bool load_titles(const char *directory, bdsp_title_set *set) {
    char path[1100];
    if (snprintf(path, sizeof path, "%s/titles.json", directory) >= (int)sizeof path) return false;
    size_t length;
    char *text = read_text(path, &length);
    if (!text) return false;
    bool ok = bdsp_title_set_parse(text, length, set);
    free(text);
    return ok;
}

void bdsp_window_title(char *out, size_t capacity, const char *base_dir, const char *mod_override) {
    bdsp_title_set set;
    memset(&set, 0, sizeof set);
    char base[900] = "";
    if (base_dir) {
        snprintf(base, sizeof base, "%s", base_dir);
        size_t n = strlen(base);
        while (n > 1 && (base[n - 1] == '/' || base[n - 1] == '\\')) base[--n] = 0;
    }
    char dirs[5][1000];
    int count = 0;
    const char *environment = getenv("BDSP_ICON_DIR");
    if (environment && *environment) snprintf(dirs[count++], sizeof dirs[0], "%s", environment);
    if (*base) {
        static const char *const sub[] = {"icons/windows", "icons/linux", "../icons/linux", "AppIcons"};
        for (int i = 0; i < 4; i++) snprintf(dirs[count++], sizeof dirs[0], "%s/%s", base, sub[i]);
    }
    for (int i = 0; i < count; i++) {
        memset(&set, 0, sizeof set);
        if (load_titles(dirs[i], &set)) break;
        memset(&set, 0, sizeof set);
    }
    char languages[16][32];
    const char *pointers[16];
    int languageCount = bdsp_system_languages(languages, 16);
    for (int i = 0; i < languageCount; i++) pointers[i] = languages[i];
    const char *mod = mod_override && *mod_override ? mod_override : set.mod;
    bdsp_build_window_title(out, capacity, bdsp_pick_game_name(&set, pointers, languageCount), mod, getenv("BDSP_WINDOW_TAG"));
}
