#ifndef BDSP_EXIT_REPORT_H
#define BDSP_EXIT_REPORT_H

/* The one place that announces "the game stopped" before the process ends (rt_fatal, fatal signals, the Windows
   exception filter, the NVN layer through bdsp_fatal_report, launch failures in main). Writes one greppable line
   "[exit] game stopped at launch: <reason>. Log: <path>. Send this file with your bug report." to stderr (and the
   Windows crash log) and shows a short message where the platform has a UI. Only the first call acts. */
void bdsp_exit_report(const char *reason);
/* Same line, no dialog: for callers that already showed their own message. */
void bdsp_exit_report_logged(const char *reason);
/* The file the log goes to when the shell redirected it (macOS app, iOS). Default: $BDSP_LOG_DIR/crash.log on
   Windows, $BDSP_LOG_DIR/bdsp.log elsewhere, else the console. */
void bdsp_exit_log_path(const char *path);
/* printf-style: prints "FATAL: <message>" to stderr, then bdsp_exit_report with the same text. For startup code before rt_fatal is usable. */
void bdsp_exit_fatalf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
/* Formats the line into out (no newline); returns the length. Exposed for tests. */
int bdsp_exit_format(char *out, unsigned size, const char *reason);

#endif
