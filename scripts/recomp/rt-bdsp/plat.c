#include "plat.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include "win32_files.h"
#include <bcrypt.h>
#else
#include <unistd.h>
#if defined(__linux__)
#include <sys/random.h>
#endif
#endif

#ifndef O_BINARY
#define O_BINARY 0
#endif

bool plat_random(void *buffer, size_t size) {
#if defined(_WIN32)
    for (uint8_t *p = buffer; size;) {
        ULONG chunk = size > 0x10000000 ? 0x10000000 : (ULONG)size;
        if (BCryptGenRandom(NULL, p, chunk, BCRYPT_USE_SYSTEM_PREFERRED_RNG)) return false;
        p += chunk, size -= chunk;
    }
    return true;
#elif defined(__linux__)
    // getrandom exists since glibc 2.25, arc4random only since 2.36.
    for (uint8_t *p = buffer; size;) {
        ssize_t n = getrandom(p, size, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        p += n, size -= (size_t)n;
    }
    return true;
#else
    arc4random_buf(buffer, size);
    return true;
#endif
}

bool plat_setenv(const char *name, const char *value, bool overwrite) {
#ifdef _WIN32
    if (!overwrite && getenv(name)) return true;
    return _putenv_s(name, value) == 0;
#else
    return setenv(name, value, overwrite) == 0;
#endif
}

bool plat_ensure_directory(const char *path) {
    if (!mkdir(path, 0700)) return true;
#ifdef _WIN32
    BdspFileInfo info;
#else
    struct stat info;
#endif
    return errno == EEXIST && !stat(path, &info) && S_ISDIR(info.st_mode);
}

bool plat_write_file_atomic(const char *path, const void *data, size_t size) {
    static unsigned counter;
#ifdef _WIN32
    unsigned long process = GetCurrentProcessId();
#else
    unsigned long process = (unsigned long)getpid();
#endif
    size_t capacity = strlen(path) + 48;
    char *temporary = malloc(capacity);
    if (!temporary) { errno = ENOMEM; return false; }
    snprintf(temporary, capacity, "%s.%lu.%u.tmp", path, process, __atomic_fetch_add(&counter, 1, __ATOMIC_RELAXED));
    int fd = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_BINARY, 0600);
    if (fd < 0) { free(temporary); return false; }
    const char *bytes = data;
    bool ok = true;
    for (size_t done = 0; ok && done < size;) {
        ssize_t n = write(fd, bytes + done, (size - done) > 0x40000000 ? 0x40000000 : (unsigned)(size - done));
        if (n <= 0) ok = false; else done += (size_t)n;
    }
    int error = ok ? 0 : (errno ? errno : EIO);
    if (ok && fsync(fd)) { ok = false; error = errno; }
    if (close(fd) && ok) { ok = false; error = errno; }
    if (ok && rename(temporary, path)) { ok = false; error = errno; }
    if (!ok) unlink(temporary);
    free(temporary);
    errno = error;
    return ok;
}
