#include "save_snapshot.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#ifdef BDSP_SAVE_FAULT_TESTS
static int fail_at(const char *point) {
    const char *selected = getenv("BDSP_SAVE_FAIL_AT");
    if (selected && !strcmp(selected, point)) { errno = ENOSPC; return 1; }
    return 0;
}
#else
#define fail_at(point) 0
#endif

static int path_join(char *out, size_t size, const char *parent, const char *name) {
    if (snprintf(out, size, "%s/%s", parent, name) >= (int)size) { errno = ENAMETOOLONG; return -1; }
    return 0;
}
static int flush_dir(const char *path) {
    int fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (fd < 0) return -1;
    int result = fsync(fd), saved = errno;
    close(fd); errno = saved; return result;
}
int bdsp_save_flush_directory(const char *directory) { return flush_dir(directory); }
static int flush_tree(const char *source, unsigned depth) {
    if (depth > 16) { errno = ELOOP; return -1; }
    struct stat st;
    if (lstat(source, &st)) return -1;
    if (S_ISREG(st.st_mode)) {
        int fd = open(source, O_RDONLY | O_NOFOLLOW);
        if (fd < 0) return -1;
        int result = fsync(fd), saved = errno; close(fd); errno = saved; return result;
    }
    if (!S_ISDIR(st.st_mode)) { errno = EINVAL; return -1; }
    DIR *dir = opendir(source);
    if (!dir) return -1;
    int result = 0;
    for (;;) {
        errno = 0; struct dirent *entry = readdir(dir);
        if (!entry) { if (errno) result = -1; break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char path[4096];
        if (path_join(path, sizeof path, source, entry->d_name) || flush_tree(path, depth + 1)) { result = -1; break; }
    }
    int saved = errno; closedir(dir); errno = saved;
    return result ? result : flush_dir(source);
}
int bdsp_save_flush(const char *source) { return flush_tree(source, 0); }
static int copy_verified(const char *source, const char *target) {
    int in = open(source, O_RDONLY | O_NOFOLLOW);
    if (in < 0) return -1;
    struct stat initial, final;
    if (fstat(in, &initial) || !S_ISREG(initial.st_mode)) { close(in); errno = EINVAL; return -1; }
    if (fsync(in)) { int saved = errno; close(in); errno = saved; return -1; }
    int out = open(target, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (out < 0) { close(in); return -1; }
    char a[65536], b[65536];
    ssize_t n; int result = -1;
    while ((n = read(in, a, sizeof a)) > 0) {
        if (fail_at("write")) goto done;
        ssize_t offset = 0;
        while (offset < n) {
            ssize_t wrote = write(out, a + offset, (size_t)(n - offset));
            if (wrote < 0 && errno == EINTR) continue;
            if (wrote <= 0) goto done;
            offset += wrote;
        }
    }
    if (n < 0 || fail_at("flush") || fsync(out) || fstat(in, &final) || initial.st_size != final.st_size ||
        lseek(in, 0, SEEK_SET) < 0 || lseek(out, 0, SEEK_SET) < 0) goto done;
    while ((n = read(in, a, sizeof a)) > 0) {
        ssize_t offset = 0;
        while (offset < n) {
            ssize_t got = read(out, b + offset, (size_t)(n - offset));
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) goto done;
            offset += got;
        }
        if (memcmp(a, b, (size_t)n)) { errno = EIO; goto done; }
    }
    if (n == 0 && read(out, b, 1) == 0) result = 0;
done: {
    int saved = errno;
    if (close(out) && result == 0) { result = -1; saved = errno; }
    close(in); errno = saved; return result;
} }

static int copy_tree(const char *source, const char *target, unsigned depth) {
    if (depth > 16) { errno = ELOOP; return -1; }
    struct stat st;
    if (lstat(source, &st) || !S_ISDIR(st.st_mode)) { errno = EINVAL; return -1; }
    if (mkdir(target, 0700)) return -1;
    DIR *dir = opendir(source);
    if (!dir) return -1;
    int result = 0;
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(dir);
        if (!entry) { if (errno) result = -1; break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char src[4096], dst[4096];
        if (path_join(src, sizeof src, source, entry->d_name) || path_join(dst, sizeof dst, target, entry->d_name) || lstat(src, &st)) { result = -1; break; }
        if (S_ISDIR(st.st_mode)) result = copy_tree(src, dst, depth + 1);
        else if (S_ISREG(st.st_mode)) result = copy_verified(src, dst);
        else { errno = EINVAL; result = -1; }
        if (result) break;
    }
    int saved = errno; closedir(dir); errno = saved;
    return result ? result : flush_dir(target);
}

static void remove_staging(const char *path) {
    DIR *dir = opendir(path);
    if (!dir) { unlink(path); return; }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char child[4096]; struct stat st;
        if (!path_join(child, sizeof child, path, entry->d_name) && !lstat(child, &st)) {
            if (S_ISDIR(st.st_mode)) remove_staging(child); else unlink(child);
        }
    }
    closedir(dir); rmdir(path);
}

int bdsp_save_snapshot(const char *source, const char *directory, char *published, size_t capacity) {
    char stage[4096], target[4096];
    struct timespec now;
    if (!source || !directory || !published || !capacity) { errno = EINVAL; return -1; }
    published[0] = 0;
    if (mkdir(directory, 0700) && errno != EEXIST) return -1;
    struct stat st;
    if (lstat(directory, &st) || !S_ISDIR(st.st_mode)) { errno = EINVAL; return -1; }
    if (path_join(stage, sizeof stage, directory, ".pending-XXXXXX") || !mkdtemp(stage)) return -1;
    // mkdtemp reserves the unique parent; copy_tree creates its payload.
    char payload[4096];
    if (path_join(payload, sizeof payload, stage, "save") || copy_tree(source, payload, 0)) goto failed;
    if (clock_gettime(CLOCK_REALTIME, &now)) goto failed;
    if (snprintf(target, sizeof target, "%s/%020lld-%09ld-%s", directory, (long long)now.tv_sec,
            now.tv_nsec, strrchr(stage, '/') + 1 + strlen(".pending-")) >= (int)sizeof target || strlen(target) >= capacity) {
        errno = ENAMETOOLONG; goto failed;
    }
    if (flush_dir(stage) || fail_at("publish") || rename(stage, target) || flush_dir(directory)) goto failed;
    strcpy(published, target);
    return 0;
failed: {
    int saved = errno; remove_staging(stage); errno = saved ? saved : EIO; return -1;
}
}
