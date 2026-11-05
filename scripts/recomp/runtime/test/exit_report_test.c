#include "../exit_report.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static char *slurp(const char *path) {
    static char buf[8192];
    FILE *f = fopen(path, "rb");
    size_t n = f ? fread(buf, 1, sizeof buf - 1, f) : 0;
    if (f) fclose(f);
    buf[n] = 0;
    return buf;
}

static int count(const char *hay, const char *needle) {
    int n = 0;
    for (const char *p = hay; (p = strstr(p, needle)); p += strlen(needle)) n++;
    return n;
}

int main(int argc, char **argv) {
    char line[512];
    (void)argc;
    (void)argv;
#ifdef _WIN32
    _putenv("BDSP_NO_EXIT_DIALOG=1");
    _putenv("BDSP_LOG_DIR=");
#else
    setenv("BDSP_NO_EXIT_DIALOG", "1", 1);
    unsetenv("BDSP_LOG_DIR");
#endif
    bdsp_exit_format(line, sizeof line, "guest memory window is not free.\n");
    CHECK(!strcmp(line, "[exit] game stopped at launch: guest memory window is not free. Log: the console output (stderr). "
                        "Send this file with your bug report."));
    bdsp_exit_log_path("some/dir/BDSP-log.txt");
    bdsp_exit_format(line, sizeof line, NULL);
    CHECK(strstr(line, "unknown reason. Log: some/dir/BDSP-log.txt. Send this file"));

    const char *capture = "exit_report_test.out";
    CHECK(freopen(capture, "w", stderr) != NULL);
    bdsp_exit_report("first reason\n");
    bdsp_exit_report("second reason");
    bdsp_exit_report_logged("third reason");
    bdsp_exit_fatalf("fourth %d", 4);
    fflush(stderr);
    char *out = slurp(capture);
    CHECK(count(out, "[exit] game stopped at launch:") == 1);
    CHECK(strstr(out, "launch: first reason. Log: some/dir/BDSP-log.txt."));
    CHECK(strstr(out, "FATAL: fourth 4"));
    remove(capture);
    if (fails) return 1;
    printf("exit_report_test passed\n");
    return 0;
}
