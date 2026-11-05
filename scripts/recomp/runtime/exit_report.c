#include "exit_report.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#ifdef _WIN32
#include <windows.h>
#include "win32_host.h"
#else
#include <unistd.h>
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;
#ifdef __APPLE__
#include <TargetConditionals.h>
#endif
#endif

static char g_log_path[1024];
static volatile int g_reported;

void bdsp_exit_log_path(const char *path) {
    if (path) snprintf(g_log_path, sizeof g_log_path, "%s", path);
}

static const char *log_location(char *buf, size_t size) {
    if (g_log_path[0]) return g_log_path;
    const char *dir = getenv("BDSP_LOG_DIR");
    if (!dir || !*dir) return "the console output (stderr)";
#ifdef _WIN32
    snprintf(buf, size, "%s\\crash.log", dir);
#else
    snprintf(buf, size, "%s/bdsp.log", dir);
#endif
    return buf;
}

int bdsp_exit_format(char *out, unsigned size, const char *reason) {
    char loc[1100], why[512];
    snprintf(why, sizeof why, "%s", reason && *reason ? reason : "unknown reason");
    size_t n = strlen(why);
    while (n && (why[n - 1] == '\n' || why[n - 1] == '\r' || why[n - 1] == ' ' || why[n - 1] == '.')) why[--n] = 0;
    return snprintf(out, size, "[exit] game stopped at launch: %s. Log: %s. Send this file with your bug report.",
                    why, log_location(loc, sizeof loc));
}

static void show_dialog(const char *line) {
    if (getenv("BDSP_NO_EXIT_DIALOG")) return;
    const char *text = line + sizeof "[exit] " - 1;
    (void)text;
#ifdef _WIN32
    MessageBoxA(NULL, text, "BDSP", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
#elif defined(__APPLE__)
#if !TARGET_OS_IPHONE   // iOS shows its own alert from the app shell
    char script[1400], *q = script;
    q += snprintf(q, sizeof script, "display alert \"BDSP\" message \"");
    for (const char *p = text; *p && q < script + sizeof script - 8; p++) {
        if (*p == '"' || *p == '\\') *q++ = '\\';
        *q++ = *p == '\n' ? ' ' : *p;
    }
    snprintf(q, (size_t)(script + sizeof script - q), "\"");
    char *args[] = {"osascript", "-e", script, NULL};
    pid_t pid;
    if (!posix_spawnp(&pid, "osascript", NULL, NULL, args, environ)) { int st; waitpid(pid, &st, 0); }
#endif
#elif defined(__linux__)
    if (!getenv("DISPLAY") && !getenv("WAYLAND_DISPLAY")) return;
    char *args[] = {"zenity", "--error", "--title=BDSP", "--no-markup", "--text", (char *)text, NULL};
    pid_t pid;
    if (!posix_spawnp(&pid, "zenity", NULL, NULL, args, environ)) { int st; waitpid(pid, &st, 0); }
#endif
}

static void report(const char *reason, int dialog) {
    if (__atomic_exchange_n(&g_reported, 1, __ATOMIC_SEQ_CST)) return;
    char line[1800];
    int n = bdsp_exit_format(line, sizeof line - 3, reason);
    if (n < 0) return;
    fprintf(stderr, "\n%s\n", line);
    fflush(stderr);
#ifdef _WIN32
    OutputDebugStringA(line);
    line[n] = '\r'; line[n + 1] = '\n';
    bdsp_win32_crash_write(line, (DWORD)n + 2);
    line[n] = 0;
#endif
    if (dialog) show_dialog(line);
}

void bdsp_exit_report(const char *reason) { report(reason, 1); }
void bdsp_exit_report_logged(const char *reason) { report(reason, 0); }

void bdsp_exit_fatalf(const char *fmt, ...) {
    char msg[512];
    va_list ap; va_start(ap, fmt); vsnprintf(msg, sizeof msg, fmt, ap); va_end(ap);
    fprintf(stderr, "FATAL: %s\n", msg);
    bdsp_exit_report(msg);
}
