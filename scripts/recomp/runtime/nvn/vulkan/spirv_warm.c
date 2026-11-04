// Install-time SPIR-V cache filler: compiles translated GLSL files (<stage letter>_<hash>.glsl, from maxwell2msl --glsl --emit-cache)
// with the renderer's own compile step and writes <out>/spirv/<cache key>.spv, the files the renderer looks up at run time.
// Usage: spirv_warm --glsl <dir> --out <dir> [--jobs N]
// Output (stdout, one line each): "warm: total N", "warm: progress DONE of N" every few files, "warm: done compiled C present P failed F".
// Exit status 0 when every file was compiled or present, 1 when some failed (the rest is still written), 2 on usage errors.
#include <dirent.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/stat.h>

#include "src/nvn/vulkan/spv_cache.h"

#ifdef _WIN32
#include <direct.h>
#define MKDIR(p) _mkdir(p)
#else
#define MKDIR(p) mkdir(p, 0777)
#endif

typedef struct { char *name; } Item;

static Item *items;
static size_t nitems;
static atomic_size_t next_item, done_items;
static atomic_uint compiled, present, failed;
static const char *glsl_dir, *out_dir;

static char *read_text(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *s = n >= 0 ? malloc((size_t)n + 1) : NULL;
    if (s && fread(s, 1, (size_t)n, f) != (size_t)n) { free(s); s = NULL; }
    if (s) s[n] = 0;
    fclose(f);
    return s;
}

static int exists(const char *path) {
    struct stat st;
    return stat(path, &st) == 0;
}

static int write_atomic(const char *path, const uint32_t *words, size_t nwords, size_t tag) {
    char tmp[4400];
    snprintf(tmp, sizeof tmp, "%s.tmp%zu", path, tag);
    FILE *f = fopen(tmp, "wb");
    if (!f) return 0;
    int ok = fwrite(words, 4, nwords, f) == nwords;
    ok = fclose(f) == 0 && ok;
    if (ok) {
#ifdef _WIN32
        remove(path);  // rename does not replace on Windows
#endif
        ok = rename(tmp, path) == 0;
    }
    if (!ok) remove(tmp);
    return ok;
}

static void *worker(void *arg) {
    size_t tag = (size_t)(uintptr_t)arg;
    shaderc_compiler_t comp = shaderc_compiler_initialize();
    for (size_t i; (i = atomic_fetch_add(&next_item, 1)) < nitems;) {
        char path[4400], target[4400], rel[64];
        const char *name = items[i].name;
        snprintf(path, sizeof path, "%s/%s", glsl_dir, name);
        char *src = comp ? read_text(path) : NULL;
        int stage = name[0] == 'v' ? SPIRV_VERTEX : name[0] == 'f' ? SPIRV_FRAGMENT : SPIRV_COMPUTE;
        if (!src) {
            atomic_fetch_add(&failed, 1);
        } else {
            spirv_file_name(rel, sizeof rel, spirv_key(src, stage));
            snprintf(target, sizeof target, "%s/%s", out_dir, rel);
            if (exists(target)) {
                atomic_fetch_add(&present, 1);
            } else {
                char err[512];
                size_t nwords = 0;
                uint32_t *spv = spirv_compile(comp, src, stage, name, &nwords, err, sizeof err);
                if (spv && write_atomic(target, spv, nwords, tag)) atomic_fetch_add(&compiled, 1);
                else atomic_fetch_add(&failed, 1);
                free(spv);
            }
            free(src);
        }
        size_t d = atomic_fetch_add(&done_items, 1) + 1;
        if (d % 50 == 0 || d == nitems) { printf("warm: progress %zu of %zu\n", d, nitems); fflush(stdout); }
    }
    if (comp) shaderc_compiler_release(comp);
    return NULL;
}

int main(int argc, char **argv) {
    int jobs = 4;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--glsl") && i + 1 < argc) glsl_dir = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) out_dir = argv[++i];
        else if (!strcmp(argv[i], "--jobs") && i + 1 < argc) jobs = atoi(argv[++i]);
        else { fprintf(stderr, "usage: spirv_warm --glsl <dir> --out <dir> [--jobs N]\n"); return 2; }
    }
    if (!glsl_dir || !out_dir) { fprintf(stderr, "usage: spirv_warm --glsl <dir> --out <dir> [--jobs N]\n"); return 2; }
    if (jobs < 1) jobs = 1;
    if (jobs > 64) jobs = 64;
    DIR *d = opendir(glsl_dir);
    if (!d) { fprintf(stderr, "spirv_warm: cannot read %s\n", glsl_dir); return 2; }
    size_t cap = 0;
    for (struct dirent *e; (e = readdir(d));) {
        size_t n = strlen(e->d_name);
        if (n < 6 || strcmp(e->d_name + n - 5, ".glsl")) continue;
        if (nitems == cap) items = realloc(items, (cap = cap ? cap * 2 : 1024) * sizeof *items);
        items[nitems++].name = strdup(e->d_name);
    }
    closedir(d);
    char dir[4400];
    MKDIR(out_dir);
    snprintf(dir, sizeof dir, "%s/spirv", out_dir);
    MKDIR(dir);
    printf("warm: total %zu\n", nitems);
    fflush(stdout);
    pthread_t threads[64];
    for (int i = 0; i < jobs; i++) pthread_create(&threads[i], NULL, worker, (void *)(uintptr_t)(i + 1));
    for (int i = 0; i < jobs; i++) pthread_join(threads[i], NULL);
    printf("warm: done compiled %u present %u failed %u\n", atomic_load(&compiled), atomic_load(&present), atomic_load(&failed));
    return atomic_load(&failed) ? 1 : 0;
}
