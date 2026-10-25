/* SPDX-License-Identifier: MIT */
#include "codegen.h"
#include "lifter.h"
#include "emitter.h"
#include "lz4.h"
#include <string.h>
#ifndef BDSP_CODEGEN_SOURCE_HASH
#define BDSP_CODEGEN_SOURCE_HASH "development"
#endif
#if defined(__aarch64__) || defined(_M_ARM64)
#define CODEGEN_ARCH "aarch64"
#elif defined(__x86_64__) || defined(_M_X64)
#define CODEGEN_ARCH "x86_64"
#else
#error Unsupported generator host architecture
#endif
#if defined(_WIN32)
#define CODEGEN_OS "windows"
#elif defined(__APPLE__)
#define CODEGEN_OS "macos"
#else
#define CODEGEN_OS "linux"
#endif
_Static_assert(sizeof(void *) == 8, "The generator requires a 64-bit host");
static int run(int argc, char **argv) {
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "--events=jsonl")) cg_events = true;
    if (argc >= 2 && !strcmp(argv[1], "--version")) {
        printf("{\"tool\":\"bdsp_codegen\",\"version\":\"0.1.0\",\"interface\":1,\"host\":\"" CODEGEN_OS "-" CODEGEN_ARCH "\",\"source\":\"%s\",\"lz4\":\"%s\",\"capabilities\":[\"image\",\"inspect\",\"decode-basic\",\"emit-function\"]}\n", BDSP_CODEGEN_SOURCE_HASH, LZ4_versionString()); return 0;
    }
    if (argc >= 2 && !strcmp(argv[1], "emit-function")) return cg_emit_checkpoint(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "decode")) return cg_decode(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "inspect")) return cg_inspect(argc - 2, argv + 2);
    if (argc >= 2 && !strcmp(argv[1], "image")) return cg_image(argc - 2, argv + 2);
    cg_fail(2, "usage: bdsp_codegen image <nso> <module> --base N --out DIR [options] | --version --json");
}
#ifdef _WIN32
#include <windows.h>
int wmain(int argc, wchar_t **wide_argv) {
    char **argv = cg_alloc((size_t)argc + 1, sizeof(*argv));
    for (int i = 0; i < argc; i++) {
        int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, NULL, 0, NULL, NULL);
        if (!n) cg_fail(2, "invalid Unicode command line");
        argv[i] = cg_alloc((size_t)n, 1); WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, argv[i], n, NULL, NULL);
    }
    return run(argc, argv);
}
#else
int main(int argc, char **argv) { return run(argc, argv); }
#endif
