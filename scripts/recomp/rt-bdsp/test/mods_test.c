// Synthetic test of the mod support (mods.c, and the overlay in services_fs.c): invented folders and files only, no game content.
// Finds mods in several folder layouts, gives the active mod its own save folder (and leaves the game's save folder alone), merges the
// mod's RomFS over the game's (replace, add, ignore files next to Data/, match names ignoring case) and resolves host paths.
// Build and run: scripts/recomp/rt-bdsp/test/run_mods_test.sh
#include <sys/stat.h>
#include <unistd.h>

#include "../services_fs.c"  // static functions (romfs_build_index, romfs_read, rom) used directly

void guest_log(const char *line) { (void)line; }
void ipc_note(const char *svc, uint32_t cmd, int unhandled) { (void)svc; (void)cmd; (void)unhandled; }
Service *service_new(const char *name, ServiceHandler h, void *state) { (void)name; (void)h; (void)state; return NULL; }
void ipc_return_object(IpcResp *resp, Service *s) { (void)resp; (void)s; }
void rt_fatal(const char *fmt, ...) { fprintf(stderr, "FATAL: %s", fmt); exit(3); }
void kernel_report(FILE *f) { (void)f; }
KThread *kernel_current_thread(void) { return NULL; }
uint64_t rt_now_ns(void) { return 0; }
void user_id_load(const char *save_dir) { (void)save_dir; }

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static void put(const char *path, size_t size, uint8_t seed) {
    FILE *f = fopen(path, "wb");
    if (!f) { printf("setup failed: cannot write %s\n", path); exit(2); }
    for (size_t i = 0; i < size; i++) fputc((int)((i * 31 + seed) & 0xFF), f);
    fclose(f);
}
static int pattern_ok(const uint8_t *d, size_t size, uint8_t seed) {
    for (size_t i = 0; i < size; i++) if (d[i] != (uint8_t)((i * 31 + seed) & 0xFF)) return 0;
    return 1;
}
static void sh(const char *fmt, const char *a) {
    char cmd[1024];
    snprintf(cmd, sizeof cmd, fmt, a, a, a, a);
    if (system(cmd)) { printf("setup failed: %s\n", cmd); exit(2); }
}
static int exists(const char *p) { struct stat st; return stat(p, &st) == 0; }

// The data of a file as the game reads it through the virtual image
static uint8_t *read_through_image(const char *host_path, uint64_t *size) {
    for (int i = 0; i < rom.nfiles; i++) {
        RFile *f = rom.sorted[i];
        if (strcmp(f->path, host_path)) continue;
        uint8_t *b = malloc(f->size ? f->size : 1);
        romfs_read(b, f->size, f->data_off);
        *size = f->size;
        return b;
    }
    return NULL;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    const char *t = "work/recomp/test/mods_syn";
    sh("rm -rf %s && mkdir -p %s/base/Data/Sub %s/base/Data/Movie %s/saves", t);
    char p[600];
#define PATH(...) (snprintf(p, sizeof p, __VA_ARGS__), p)
    put(PATH("%s/base/Data/a.bin", t), 100, 1);
    put(PATH("%s/base/Data/Sub/b.bin", t), 200, 2);
    put(PATH("%s/base/Data/Sub/keep.bin", t), 64, 3);
    put(PATH("%s/base/Data/Movie/m.webm", t), 300, 4);
    put(PATH("%s/saves/user_id.hex", t), 32, 0);

    // Mods in four layouts
    sh("mkdir -p %s/mods/Alpha/romfs/Data/New %s/mods/Alpha/romfs/Data/Movie %s/mods/Alpha/exefs", t);
    put(PATH("%s/mods/Alpha/romfs/Data/a.bin", t), 50, 11);              // replaces
    put(PATH("%s/mods/Alpha/romfs/Data/New/n.bin", t), 20, 12);          // new
    put(PATH("%s/mods/Alpha/romfs/Data/Movie/m.webm", t), 10, 14);       // replaces (folder only exists in the game)
    put(PATH("%s/mods/Alpha/romfs/README.md", t), 7, 13);                // next to Data/: not part of the RomFS
    put(PATH("%s/mods/Alpha/romfs/Data/.DS_Store", t), 7, 15);           // hidden
    sh("mkdir -p %s/mods/Wrapper/Inner/romfs/data/SUB", t);              // wrapper folder, other case
    put(PATH("%s/mods/Wrapper/Inner/romfs/data/SUB/B.BIN", t), 30, 21);
    sh("mkdir -p %s/mods/Wrapper2/contents/0100/Beta/ROMFS/Data", t);    // Ryujinx layout, upper-case ROMFS
    put(PATH("%s/mods/Wrapper2/contents/0100/Beta/ROMFS/Data/z.bin", t), 5, 31);
    sh("mkdir -p %s/mods/Zeta/Alpha/romfs/Data", t);                     // same name as the first
    put(PATH("%s/mods/Zeta/Alpha/romfs/Data/q.bin", t), 5, 41);
    sh("mkdir -p %s/mods/Empty %s/mods/.hidden/romfs", t);               // not mods
    put(PATH("%s/mods/Empty/readme.txt", t), 5, 51);

    ModInfo list[MODS_MAX];
    int n = mods_scan(PATH("%s/mods", t), list, MODS_MAX);
    CHECK(n == 4);
    CHECK(n == 4 && !strcmp(list[0].name, "Alpha") && list[0].romfs[0] && list[0].exefs[0]);
    CHECK(n == 4 && !strcmp(list[1].name, "Inner") && list[1].romfs[0] && !list[1].exefs[0]);
    CHECK(n == 4 && !strcmp(list[2].name, "Beta") && list[2].romfs[0]);
    CHECK(n == 4 && !strcmp(list[3].name, "Alpha (2)"));
    CHECK(mods_scan(PATH("%s/nonexistent", t), list, MODS_MAX) == 0);
    CHECK(mods_active() == NULL && !*mods_active_save());

    // Without a mod: the game's tree alone
    static char romfs_path[600];
    snprintf(romfs_path, sizeof romfs_path, "%s/base", t);
    g_romfs_dir = romfs_path;
    char saves[600];
    snprintf(saves, sizeof saves, "%s/saves", t);
    n = mods_scan(PATH("%s/mods", t), list, MODS_MAX);
    char host[1200];

    // Activate "Alpha": own save folder, user_id.hex copied, the game's folder untouched
    CHECK(mods_activate(&list[0], saves) == 0);
    CHECK(mods_active() && !strcmp(mods_active()->name, "Alpha"));
    CHECK(!strcmp(mods_active_save(), PATH("%s/saves/mods/Alpha", t)));
    CHECK(exists(PATH("%s/saves/mods/Alpha/user_id.hex", t)));
    CHECK(!exists(PATH("%s/saves/save_1", t)) && !exists(PATH("%s/saves/_safety", t)));
    put(PATH("%s/saves/mods/Alpha/user_id.hex", t), 32, 99);             // an existing id of the mod is never overwritten
    CHECK(mods_activate(&list[0], saves) == 0);
    {
        FILE *f = fopen(PATH("%s/saves/mods/Alpha/user_id.hex", t), "rb");
        int c0 = fgetc(f);
        fclose(f);
        CHECK(c0 == 99);
    }

    // Exported app identity survives a display-name change without migrating saves.
    CHECK(mods_activate_profile(&list[0], saves, "0123456789abcdef0123") == 0);
    put(PATH("%s/saves/mods/0123456789abcdef0123/sentinel", t), 4, 77);
    ModInfo renamed = list[0];
    snprintf(renamed.name, sizeof renamed.name, "Renamed mod");
    CHECK(mods_activate_profile(&renamed, saves, "0123456789abcdef0123") == 0);
    CHECK(exists(PATH("%s/saves/mods/0123456789abcdef0123/sentinel", t)));
    CHECK(!strcmp(mods_active()->name, "Renamed mod"));
    CHECK(mods_activate_profile(&renamed, saves, "../bad") != 0);
    CHECK(mods_activate(&list[0], saves) == 0);

    // The merged RomFS
    romfs_build_index();
    CHECK(rom.nfiles == 5);   // the game's 4 files, 2 of them replaced, plus New/n.bin
    CHECK(fs_resolve_rom_path("Data/a.bin", host, sizeof host) && strstr(host, "mods/Alpha/romfs/Data/a.bin"));
    CHECK(fs_resolve_rom_path("Data/Sub/b.bin", host, sizeof host) && strstr(host, "base/Data/Sub/b.bin"));
    CHECK(fs_resolve_rom_path("data/SUB/KEEP.BIN", host, sizeof host) && strstr(host, "base/Data/Sub/keep.bin"));   // case-insensitive
    CHECK(fs_resolve_rom_path("Data/Movie/m.webm", host, sizeof host) && strstr(host, "mods/Alpha/romfs/Data/Movie/m.webm"));
    CHECK(fs_resolve_rom_path("Data/New/n.bin", host, sizeof host) && strstr(host, "mods/Alpha/romfs/Data/New/n.bin"));
    CHECK(!fs_resolve_rom_path("README.md", host, sizeof host));         // files next to Data/ are ignored
    CHECK(!fs_resolve_rom_path("Data/.DS_Store", host, sizeof host));
    CHECK(!fs_resolve_rom_path("Data/missing.bin", host, sizeof host));
    CHECK(!fs_resolve_rom_path("Data/Sub", host, sizeof host));          // a folder is not a file
    uint64_t size = 0;
    uint8_t *d = read_through_image(PATH("%s/mods/Alpha/romfs/Data/a.bin", t), &size);
    CHECK(d && size == 50 && pattern_ok(d, size, 11));                   // the game reads the mod's bytes
    free(d);
    d = read_through_image(PATH("%s/base/Data/Sub/keep.bin", t), &size);
    CHECK(d && size == 64 && pattern_ok(d, size, 3));
    free(d);
    d = read_through_image(PATH("%s/base/Data/a.bin", t), &size);
    CHECK(d == NULL);                                                    // the replaced original is no longer in the image

    printf(fails ? "mods test: %d errors\n" : "mods test: passed (4 folder layouts found, own save folder, game save untouched, RomFS merge: replace, add, ignore root files, case-insensitive)\n", fails);
    return fails != 0;
}
