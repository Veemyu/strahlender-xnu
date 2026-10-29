// Host test of plat.c (POSIX build): cc plat_test.c ../plat.c -I.. && ./a.out <scratch-directory>
#include "plat.h"
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "FAILED line %d: %s\n", __LINE__, #condition); return 1; } } while (0)

static int read_file(const char *path, char *out, size_t capacity) {
    FILE *file = fopen(path, "rb");
    if (!file) return -1;
    size_t n = fread(out, 1, capacity - 1, file);
    fclose(file);
    out[n] = 0;
    return (int)n;
}

int main(int argc, char **argv) {
    CHECK(argc == 2);
    char a[32] = {0}, b[32] = {0}, path[4096], text[64];
    CHECK(plat_random(a, sizeof a) && plat_random(b, sizeof b));
    CHECK(memcmp(a, b, sizeof a) != 0);

    CHECK(plat_setenv("BDSP_PLAT_TEST", "first", true));
    CHECK(plat_setenv("BDSP_PLAT_TEST", "second", false) && !strcmp(getenv("BDSP_PLAT_TEST"), "first"));
    CHECK(plat_setenv("BDSP_PLAT_TEST", "third", true) && !strcmp(getenv("BDSP_PLAT_TEST"), "third"));

    snprintf(path, sizeof path, "%s/dir", argv[1]);
    CHECK(plat_ensure_directory(path) && plat_ensure_directory(path));
    snprintf(path, sizeof path, "%s/dir/file", argv[1]);
    CHECK(plat_write_file_atomic(path, "one", 3));
    CHECK(read_file(path, text, sizeof text) == 3 && !strcmp(text, "one"));
    CHECK(plat_ensure_directory(path) == false);  // a file is not a directory
    CHECK(plat_write_file_atomic(path, "second version", 14));
    CHECK(read_file(path, text, sizeof text) == 14 && !strcmp(text, "second version"));
    CHECK(plat_write_file_atomic(path, "", 0) && read_file(path, text, sizeof text) == 0);

    snprintf(path, sizeof path, "%s/dir", argv[1]);
    DIR *directory = opendir(path);
    int entries = 0;
    for (struct dirent *e; directory && (e = readdir(directory));) entries += strcmp(e->d_name, ".") && strcmp(e->d_name, "..");
    if (directory) closedir(directory);
    CHECK(entries == 1);  // no temporary file is left behind

    snprintf(path, sizeof path, "%s/missing/file", argv[1]);
    CHECK(!plat_write_file_atomic(path, "x", 1));
    uint64_t t0 = plat_now_ns();
    plat_sleep_until_ns(t0 + 20000000ull);
    uint64_t t1 = plat_now_ns();
    CHECK(t1 >= t0 + 20000000ull && t1 < t0 + 2000000000ull);
    plat_sleep_until_ns(0);  // a target in the past returns at once

    size_t ps = (size_t)sysconf(_SC_PAGESIZE);
    unsigned char *page = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    CHECK(page != MAP_FAILED && plat_memory_commit(page, 65536) && plat_memory_prepare_write(page, 65536));
    memset(page, 0xAB, 65536);
    CHECK(plat_memory_discard(page + ps, 2 * ps) && plat_memory_discard(page, 0));
    CHECK(page[0] == 0xAB && page[ps] == 0 && page[3 * ps - 1] == 0 && page[3 * ps] == 0xAB);
    puts("plat ok");
    return 0;
}
