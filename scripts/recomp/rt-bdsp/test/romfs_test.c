// Synthetic test of the virtual RomFS image (services_fs.c): builds a small directory of invented files, lets
// the image be built and looks up every file by path in it like the game does through hash tables (directory and file hash, meta tables);
// content and size are checked against the directory, as is reading across file boundaries. No game content.
// Build and run: scripts/recomp/rt-bdsp/test/run_romfs_test.sh
#include <sys/stat.h>
#include <unistd.h>

#include "../services_fs.c"  // static Funktionen (romfs_build_index, romfs_read) direkt nutzen

void guest_log(const char *line) { (void)line; }
void ipc_note(const char *svc, uint32_t cmd, int unhandled) { (void)svc; (void)cmd; (void)unhandled; }
Service *service_new(const char *name, ServiceHandler h, void *state) {
    Service *s = calloc(1, sizeof *s);
    s->name = name; s->handler = h; s->state = state;
    return s;
}
void ipc_return_object(IpcResp *resp, Service *s) { resp->objects[resp->nobjects++] = s; }
void rt_fatal(const char *fmt, ...) { fprintf(stderr, "FATAL: %s", fmt); exit(3); }
void kernel_report(FILE *f) { (void)f; }
KThread *kernel_current_thread(void) { return NULL; }

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static void put(const char *path, size_t size, uint8_t seed) {
    FILE *f = fopen(path, "wb");
    for (size_t i = 0; i < size; i++) fputc((int)((i * 31 + seed) & 0xFF), f);
    fclose(f);
}

static uint8_t *img(uint64_t off, uint64_t size) {
    uint8_t *b = malloc(size ? size : 1);
    romfs_read(b, size, off);
    return b;
}

// Lookup like the game's RomFS tables: directory via hash(parent, name), file via hash(parent dir, name)
static int64_t find_entry(const uint64_t *hdr, const uint8_t *htab, uint32_t hcount, const uint8_t *meta, uint32_t parent, const char *name, size_t nl, int is_dir) {
    uint32_t h = romfs_hash(parent, name, (uint32_t)nl) % hcount, off;
    memcpy(&off, htab + 4 * h, 4);
    while (off != EMPTY) {
        const uint8_t *e = meta + off;
        uint32_t p, len, next;
        memcpy(&p, e, 4);
        memcpy(&next, e + (is_dir ? 16 : 24), 4);
        memcpy(&len, e + (is_dir ? 20 : 28), 4);
        if (p == parent && len == nl && !memcmp(e + (is_dir ? 24 : 32), name, nl)) return off;
        off = next;
    }
    (void)hdr;
    return -1;
}

static int lookup_file(const uint64_t *hdr, const char *path, uint64_t *data_off, uint64_t *size) {
    uint8_t *dh = img(hdr[1], hdr[2]), *dm = img(hdr[3], hdr[4]), *fh = img(hdr[5], hdr[6]), *fm = img(hdr[7], hdr[8]);
    uint32_t dir = 0;
    char buf[512];
    snprintf(buf, sizeof buf, "%s", path);
    int ok = 0;
    for (char *tok = buf, *next; tok && *tok; tok = next) {
        next = strchr(tok, '/');
        if (next) *next++ = 0;
        if (next) {
            int64_t d = find_entry(hdr, dh, (uint32_t)(hdr[2] / 4), dm, dir, tok, strlen(tok), 1);
            if (d < 0) goto out;
            dir = (uint32_t)d;
        } else {
            int64_t f = find_entry(hdr, fh, (uint32_t)(hdr[6] / 4), fm, dir, tok, strlen(tok), 0);
            if (f < 0) goto out;
            memcpy(data_off, fm + f + 8, 8);
            memcpy(size, fm + f + 16, 8);
            *data_off += hdr[9];
            ok = 1;
        }
    }
out:
    free(dh); free(dm); free(fh); free(fm);
    return ok;
}

// ---- Save folder (IFileSystem/IFile/IDirectory through the service functions, without guest)
typedef struct { uint8_t raw[64]; } Raw;
static IpcResp call(Service *s, uint32_t cmd, const void *data, size_t dsz, const char *path, const char *path2, const void *abuf, size_t asz, void *bbuf, size_t bsz) {
    IpcReq req;
    memset(&req, 0, sizeof req);
    static uint8_t raw[64];
    memset(raw, 0, sizeof raw);
    if (data) memcpy(raw, data, dsz);
    req.cmd = cmd;
    req.data = raw;
    if (path) { req.x[req.nx].addr = H2G(path); req.x[req.nx++].size = strlen(path) + 1; }
    if (path2) { req.x[req.nx].addr = H2G(path2); req.x[req.nx++].size = strlen(path2) + 1; }
    if (abuf) { req.a[0].addr = H2G(abuf); req.a[0].size = asz; req.na = 1; }
    if (bbuf) { req.b[0].addr = H2G(bbuf); req.b[0].size = bsz; req.nb = 1; }
    IpcResp resp;
    memset(&resp, 0, sizeof resp);
    s->handler(s, &req, &resp);
    return resp;
}

static void test_save(void) {
    system("rm -rf work/recomp/test/save_syn");
    g_save_dir = "work/recomp/test/save_syn";
    Service *fs = open_host_fs("save_1");
    uint8_t cf[16] = {0};
    *(int64_t *)(cf + 8) = 0;
    IpcResp r = call(fs, 0, cf, sizeof cf, "/data.bin", NULL, NULL, 0, NULL, 0);  // CreateFile
    CHECK(r.result == 0);
    r = call(fs, 0, cf, sizeof cf, "/data.bin", NULL, NULL, 0, NULL, 0);
    CHECK(r.result == FS_PATH_EXISTS);
    r = call(fs, 2, NULL, 0, "/dir", NULL, NULL, 0, NULL, 0);  // CreateDirectory
    CHECK(r.result == 0);
    uint32_t mode = 2;
    r = call(fs, 8, &mode, 4, "/data.bin", NULL, NULL, 0, NULL, 0);  // OpenFile (Schreiben)
    CHECK(r.result == 0 && r.nobjects == 1);
    Service *f = r.objects[0];
    uint8_t wr[32];
    for (int i = 0; i < 32; i++) wr[i] = (uint8_t)(i * 7);
    uint8_t wargs[24] = {0};
    *(int64_t *)(wargs + 8) = 10;   // Offset
    *(int64_t *)(wargs + 16) = 32;  // size
    r = call(f, 1, wargs, sizeof wargs, NULL, NULL, wr, sizeof wr, NULL, 0);  // Write
    CHECK(r.result == 0);
    r = call(f, 4, NULL, 0, NULL, NULL, NULL, 0, NULL, 0);  // GetSize
    CHECK(r.result == 0 && *(int64_t *)r.data == 42);
    uint8_t rd[32] = {0};
    uint8_t rargs[24] = {0};
    *(int64_t *)(rargs + 8) = 10;
    *(int64_t *)(rargs + 16) = 32;
    r = call(f, 0, rargs, sizeof rargs, NULL, NULL, NULL, 0, rd, sizeof rd);  // Read
    CHECK(r.result == 0 && *(int64_t *)r.data == 32 && !memcmp(rd, wr, 32));
    uint8_t ss[8];
    *(int64_t *)ss = 100;
    r = call(f, 3, ss, 8, NULL, NULL, NULL, 0, NULL, 0);  // SetSize
    r = call(f, 4, NULL, 0, NULL, NULL, NULL, 0, NULL, 0);
    CHECK(*(int64_t *)r.data == 100);
    r = call(fs, 7, NULL, 0, "/data.bin", NULL, NULL, 0, NULL, 0);  // GetEntryType
    CHECK(r.result == 0 && *(uint32_t *)r.data == 1);
    r = call(fs, 7, NULL, 0, "/dir", NULL, NULL, 0, NULL, 0);
    CHECK(r.result == 0 && *(uint32_t *)r.data == 0);
    r = call(fs, 7, NULL, 0, "/missing", NULL, NULL, 0, NULL, 0);
    CHECK(r.result == FS_PATH_NOT_FOUND);
    r = call(fs, 5, NULL, 0, "/data.bin", "/renamed.bin", NULL, 0, NULL, 0);  // RenameFile
    CHECK(r.result == 0);
    uint32_t dm = 3;
    r = call(fs, 9, &dm, 4, "/", NULL, NULL, 0, NULL, 0);  // OpenDirectory (files and folders)
    CHECK(r.result == 0 && r.nobjects == 1);
    Service *d = r.objects[0];
    r = call(d, 1, NULL, 0, NULL, NULL, NULL, 0, NULL, 0);  // GetEntryCount
    CHECK(*(int64_t *)r.data == 2);
    static uint8_t ents[0x310 * 4];
    r = call(d, 0, NULL, 0, NULL, NULL, NULL, 0, ents, sizeof ents);  // Read
    CHECK(*(int64_t *)r.data == 2);
    r = call(fs, 1, NULL, 0, "/renamed.bin", NULL, NULL, 0, NULL, 0);  // DeleteFile
    CHECK(r.result == 0);
    r = call(fs, 7, NULL, 0, "/renamed.bin", NULL, NULL, 0, NULL, 0);
    CHECK(r.result == FS_PATH_NOT_FOUND);
    struct stat sb;
    CHECK(stat("work/recomp/test/save_syn/save_1/dir", &sb) == 0 && S_ISDIR(sb.st_mode));
}

int main(void) {
    const char *root = "work/recomp/test/romfs_syn";
    char cmd[256];
    snprintf(cmd, sizeof cmd, "rm -rf %s && mkdir -p %s/Data/Sub/Deep %s/Data/Other", root, root, root);
    if (system(cmd)) return 2;
    struct { const char *p; size_t sz; uint8_t seed; } files[] = {
        {"Data/a.bin", 100, 1}, {"Data/b.bin", 0, 2}, {"Data/Sub/c.dat", 70000, 3}, {"Data/Sub/Deep/d_long_name_with_many_characters.assets", 5, 4},
        {"Data/Other/e.txt", 16, 5}, {"Data/Other/f.txt", 17, 6}, {"top.cfg", 33, 7}, {"Data/Sub/Deep/g", 4096, 8},
    };
    char path[512];
    for (unsigned i = 0; i < sizeof files / sizeof *files; i++) {
        snprintf(path, sizeof path, "%s/%s", root, files[i].p);
        put(path, files[i].sz, files[i].seed);
    }
    snprintf(path, sizeof path, "%s/Data/.DS_Store", root);  // hidden files are not part of the image
    put(path, 10, 9);
    g_romfs_dir = root;
    romfs_build_index();
    CHECK(rom.nfiles == 8);
    uint64_t hdr[10];
    romfs_read((uint8_t *)hdr, sizeof hdr, 0);
    CHECK(hdr[0] == 0x50 && hdr[9] == 0x200);
    for (unsigned i = 0; i < sizeof files / sizeof *files; i++) {
        uint64_t off = 0, size = 0;
        CHECK(lookup_file(hdr, files[i].p, &off, &size));
        CHECK(size == files[i].sz);
        uint8_t *d = img(off, size);
        int same = 1;
        for (size_t k = 0; k < size; k++) if (d[k] != (uint8_t)((k * 31 + files[i].seed) & 0xFF)) { same = 0; break; }
        CHECK(same);
        free(d);
        CHECK(off % 16 == 0);
    }
    uint64_t o, s;
    CHECK(!lookup_file(hdr, "Data/missing.bin", &o, &s));
    CHECK(!lookup_file(hdr, "Data/.DS_Store", &o, &s));
    // Reading across file boundaries: the whole data region at once, then samples against single accesses
    uint8_t *all = img(0, rom.tables_off + rom.tables_size);
    uint64_t co, cs;
    CHECK(lookup_file(hdr, "Data/Sub/c.dat", &co, &cs));
    CHECK(!memcmp(all + co, img(co, cs), cs));
    test_save();
    printf(fails ? "RomFS/save test: %d errors\n" : "RomFS/save test: passed (8 files, hash lookup like in the game, reading across file boundaries, host folder: create, write, read, size, rename, list, delete)\n", fails);
    return fails != 0;
}
