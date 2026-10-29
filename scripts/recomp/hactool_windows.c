/* UTF-8 boundary for the pinned upstream tool; extraction logic stays upstream. */
#include "hactool_windows.h"
#include <errno.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

int hactool_main(int argc, char **argv);

void bdsp_tool_component(const char *name) {
    size_t size = strlen(name);
    bool invalid = !size || !strcmp(name, ".") || !strcmp(name, "..");
    for (size_t i = 0; i < size; i++)
        if ((unsigned char)name[i] < 32 || strchr("\\/:<>\"|?*", name[i])) invalid = true;
    if (size && (name[size - 1] == '.' || name[size - 1] == ' ')) invalid = true;
    size_t base = strcspn(name, ".");
    if ((base == 3 && (!_strnicmp(name, "CON", 3) || !_strnicmp(name, "PRN", 3) ||
                       !_strnicmp(name, "AUX", 3) || !_strnicmp(name, "NUL", 3))) ||
        (base == 4 && (!_strnicmp(name, "COM", 3) || !_strnicmp(name, "LPT", 3)) &&
         name[3] >= '1' && name[3] <= '9')) invalid = true;
    if (invalid) {
        fputs("Unsafe extracted path component\n", stderr);
        exit(EXIT_FAILURE);
    }
}

static wchar_t *wide(const char *text) {
    int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (!size) { errno = EILSEQ; return NULL; }
    wchar_t *out = calloc((size_t)size, sizeof(*out));
    if (!out) { errno = ENOMEM; return NULL; }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, out, size)) {
        free(out);
        errno = EILSEQ;
        return NULL;
    }
    return out;
}

FILE *bdsp_tool_fopen(const char *path, const char *mode) {
    wchar_t *wpath = wide(path), *wmode = wide(mode);
    FILE *file = wpath && wmode ? _wfopen(wpath, wmode) : NULL;
    int error = errno;
    free(wpath);
    free(wmode);
    errno = error;
    return file;
}

int wmain(int argc, wchar_t **arguments) {
    char **argv = calloc((size_t)argc + 1, sizeof(*argv));
    if (!argv) { fputs("Tool command-line allocation failed\n", stderr); return 2; }
    int code = 2;
    for (int i = 0; i < argc; i++) {
        int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, arguments[i], -1, NULL, 0, NULL, NULL);
        if (!size) { fputs("Invalid Unicode tool command line\n", stderr); goto done; }
        argv[i] = calloc((size_t)size, 1);
        if (!argv[i]) { fputs("Tool command-line allocation failed\n", stderr); goto done; }
        if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, arguments[i], -1, argv[i], size, NULL, NULL)) {
            fputs("Invalid Unicode tool command line\n", stderr);
            goto done;
        }
    }
    code = hactool_main(argc, argv);
done:
    for (int i = 0; i < argc; i++) free(argv[i]);
    free(argv);
    return code;
}
