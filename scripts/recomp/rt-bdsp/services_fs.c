// fsp-srv of the BDSP runtime: RomFS as a virtual memory image (tables in memory, file data from work/romfs via pread,
// no 5 GB image needed), saves and SD card as host folders (work/recomp/save, never in the repository).
// Own code; layout of the RomFS image (header, data from 0x200, then hash/meta tables) and the IFileSystem/IFile
// command set after LASRecomp runtime/romfs_build.c and services/fs.c (MIT, Copyright (c) 2026 Peiikai, see NOTICE.md).
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include "bdsp.h"

void ipc_note(const char *svc, uint32_t cmd, int unhandled);

#define FS_PATH_NOT_FOUND MAKE_RESULT(2, 1)
#define FS_PATH_EXISTS MAKE_RESULT(2, 2)
#define FS_NOT_EMPTY MAKE_RESULT(2, 8)
#define FS_UNEXPECTED MAKE_RESULT(2, 4000)

const char *g_romfs_dir = "work/romfs";
const char *g_save_dir = "work/recomp/save";
void fs_set_dirs(const char *romfs, const char *save) {
    if (romfs) g_romfs_dir = romfs;
    if (save) g_save_dir = save;
    user_id_load(g_save_dir);
}

// ------------------------------------------------------------------ RomFS-Abbild
#define EMPTY 0xFFFFFFFFu
#define DATA_START 0x200u
typedef struct RDir RDir;
typedef struct { char *name, *path; uint64_t size, data_off; uint32_t off; RDir *parent; } RFile;
struct RDir { char *name, *path; RDir *parent; RDir **dirs; RFile **files; int ndirs, nfiles; uint32_t off; };

typedef struct {
    uint8_t *tables;           // hash and meta tables (from tables_off in the image)
    uint64_t tables_off, tables_size, data_end;
    uint8_t header[0x50];
    RFile **sorted;            // by data offset
    int nfiles;
    uint64_t nreads, nbytes;
} RomImage;
static RomImage rom;
static pthread_mutex_t rom_lock = PTHREAD_MUTEX_INITIALIZER;

static int by_name_dir(const void *a, const void *b) { return strcmp((*(RDir *const *)a)->name, (*(RDir *const *)b)->name); }
static int by_name_file(const void *a, const void *b) { return strcmp((*(RFile *const *)a)->name, (*(RFile *const *)b)->name); }
static int by_off(const void *a, const void *b) {
    uint64_t x = (*(RFile *const *)a)->data_off, y = (*(RFile *const *)b)->data_off;
    return x < y ? -1 : x > y;
}

static RDir *scan(const char *path, const char *name, RDir *parent, int depth, int *total) {
    if (depth > 32) return NULL;
    DIR *d = opendir(path);
    if (!d) return NULL;
    RDir *dir = calloc(1, sizeof *dir);
    dir->name = strdup(name); dir->path = strdup(path); dir->parent = parent;
    int cd = 0, cf = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;  // ".", "..", .DS_Store are not part of the game
        size_t n = strlen(path) + strlen(e->d_name) + 2;
        char *p = malloc(n);
        snprintf(p, n, "%s/%s", path, e->d_name);
        struct stat st;
        if (stat(p, &st) != 0) { free(p); continue; }
        if (S_ISDIR(st.st_mode)) {
            RDir *c = scan(p, e->d_name, dir, depth + 1, total);
            free(p);
            if (!c) continue;
            if (dir->ndirs == cd) dir->dirs = realloc(dir->dirs, sizeof *dir->dirs * (cd = cd ? cd * 2 : 8));
            dir->dirs[dir->ndirs++] = c;
        } else if (S_ISREG(st.st_mode)) {
            RFile *f = calloc(1, sizeof *f);
            f->name = strdup(e->d_name); f->path = p; f->size = (uint64_t)st.st_size; f->parent = dir;
            if (dir->nfiles == cf) dir->files = realloc(dir->files, sizeof *dir->files * (cf = cf ? cf * 2 : 16));
            dir->files[dir->nfiles++] = f;
            (*total)++;
        } else free(p);
    }
    closedir(d);
    if (dir->ndirs) qsort(dir->dirs, dir->ndirs, sizeof *dir->dirs, by_name_dir);
    if (dir->nfiles) qsort(dir->files, dir->nfiles, sizeof *dir->files, by_name_file);
    return dir;
}

static uint32_t romfs_hash(uint32_t parent, const char *name, uint32_t len) {
    uint32_t h = parent ^ 123456789u;
    for (uint32_t i = 0; i < len; i++) { h = (h >> 5) | (h << 27); h ^= (uint8_t)name[i]; }
    return h;
}
static uint32_t hash_count(uint32_t n) {  // odd, coprime to the small primes (like the console's tools)
    if (n < 3) return 3;
    if (n < 19) return n | 1;
    uint32_t c = n | 1;
    for (;; c += 2) {
        int ok = 1;
        for (uint32_t p = 3; p <= 19; p += 2) if (c % p == 0) { ok = 0; break; }
        if (ok) return c;
    }
}

static int ndirs_total, nfiles_total;
static void count_dirs(RDir *d) { ndirs_total++; for (int i = 0; i < d->ndirs; i++) count_dirs(d->dirs[i]); }

static uint8_t *dmeta, *fmeta;
static uint32_t *dhash, *fhash;
static uint32_t dmeta_size, fmeta_size, dcount, fcount;
static uint64_t next_data;
static RFile **filelist;
static int nfilelist;

// Order: a directory, its files, then the subdirectories (depth first)
static void layout_dir(RDir *d, uint32_t parent_off) {
    d->off = dmeta_size;
    uint32_t nl = (uint32_t)strlen(d->name);
    dmeta_size += 0x18 + ((nl + 3) & ~3u);
    (void)parent_off;
    for (int i = 0; i < d->nfiles; i++) {
        RFile *f = d->files[i];
        f->off = fmeta_size;
        uint32_t fnl = (uint32_t)strlen(f->name);
        fmeta_size += 0x20 + ((fnl + 3) & ~3u);
        f->data_off = next_data;
        next_data = (next_data + f->size + 0xF) & ~0xFull;
        filelist[nfilelist++] = f;
    }
    for (int i = 0; i < d->ndirs; i++) layout_dir(d->dirs[i], d->off);
}

static void write_dir(RDir *d) {
    uint8_t *e = dmeta + d->off;
    uint32_t parent = d->parent ? d->parent->off : 0, sibling = EMPTY, child_dir = EMPTY, child_file = EMPTY;
    if (d->parent) {
        for (int i = 0; i < d->parent->ndirs; i++)
            if (d->parent->dirs[i] == d) { sibling = i + 1 < d->parent->ndirs ? d->parent->dirs[i + 1]->off : EMPTY; break; }
    }
    if (d->ndirs) child_dir = d->dirs[0]->off;
    if (d->nfiles) child_file = d->files[0]->off;
    uint32_t nl = (uint32_t)strlen(d->name);
    uint32_t h = romfs_hash(parent, d->name, nl) % dcount;
    uint32_t next_hash = dhash[h];
    dhash[h] = d->off;
    memcpy(e, &parent, 4); memcpy(e + 4, &sibling, 4); memcpy(e + 8, &child_dir, 4); memcpy(e + 12, &child_file, 4);
    memcpy(e + 16, &next_hash, 4); memcpy(e + 20, &nl, 4); memcpy(e + 24, d->name, nl);
    for (int i = 0; i < d->nfiles; i++) {
        RFile *f = d->files[i];
        uint8_t *fe = fmeta + f->off;
        uint32_t fsib = i + 1 < d->nfiles ? d->files[i + 1]->off : EMPTY, fnl = (uint32_t)strlen(f->name);
        uint32_t fh = romfs_hash(d->off, f->name, fnl) % fcount;
        uint32_t fnext = fhash[fh];
        fhash[fh] = f->off;
        uint64_t rel = f->data_off - DATA_START;
        memcpy(fe, &d->off, 4); memcpy(fe + 4, &fsib, 4); memcpy(fe + 8, &rel, 8); memcpy(fe + 16, &f->size, 8);
        memcpy(fe + 24, &fnext, 4); memcpy(fe + 28, &fnl, 4); memcpy(fe + 32, f->name, fnl);
    }
    for (int i = 0; i < d->ndirs; i++) write_dir(d->dirs[i]);
}

static void romfs_build_index(void) {
    pthread_mutex_lock(&rom_lock);
    if (rom.tables) { pthread_mutex_unlock(&rom_lock); return; }
    int total = 0;
    RDir *root = scan(g_romfs_dir, "", NULL, 0, &total);
    if (!root) rt_fatal("RomFS folder %s not readable (BDSP_ROMFS)\n", g_romfs_dir);
    nfiles_total = total;
    count_dirs(root);
    dcount = hash_count((uint32_t)ndirs_total);
    fcount = hash_count((uint32_t)nfiles_total);
    filelist = calloc(nfiles_total + 1, sizeof *filelist);
    next_data = DATA_START;
    // size of the meta tables in advance by a trial run of the layout
    layout_dir(root, 0);
    uint64_t data_end = next_data;
    dmeta = calloc(1, dmeta_size + 8); fmeta = calloc(1, fmeta_size + 8);
    dhash = malloc(dcount * 4); fhash = malloc(fcount * 4);
    for (uint32_t i = 0; i < dcount; i++) dhash[i] = EMPTY;
    for (uint32_t i = 0; i < fcount; i++) fhash[i] = EMPTY;
    write_dir(root);
    uint64_t t = (data_end + 0xFFF) & ~0xFFFull;
    uint64_t dh_off = t, dh_size = dcount * 4ull;
    uint64_t dm_off = dh_off + ((dh_size + 3) & ~3ull), dm_size = dmeta_size;
    uint64_t fh_off = dm_off + ((dm_size + 3) & ~3ull), fh_size = fcount * 4ull;
    uint64_t fm_off = fh_off + ((fh_size + 3) & ~3ull), fm_size = fmeta_size;
    uint64_t end = fm_off + fm_size;
    rom.tables_off = dh_off;
    rom.tables_size = end - dh_off;
    rom.tables = calloc(1, rom.tables_size);
    memcpy(rom.tables, dhash, dh_size);
    memcpy(rom.tables + (dm_off - dh_off), dmeta, dm_size);
    memcpy(rom.tables + (fh_off - dh_off), fhash, fh_size);
    memcpy(rom.tables + (fm_off - dh_off), fmeta, fm_size);
    uint64_t hdr[10] = {0x50, dh_off, dh_size, dm_off, dm_size, fh_off, fh_size, fm_off, fm_size, DATA_START};
    memcpy(rom.header, hdr, sizeof hdr);
    rom.data_end = data_end;
    rom.sorted = filelist;
    rom.nfiles = nfilelist;
    qsort(rom.sorted, rom.nfiles, sizeof *rom.sorted, by_off);
    LOG("[fs] RomFS index: %d files, %d folders, data %llu MiB, tables %llu KiB (virtual, no image)\n", nfiles_total, ndirs_total,
        (unsigned long long)(data_end >> 20), (unsigned long long)(rom.tables_size >> 10));
    pthread_mutex_unlock(&rom_lock);
}

// liest [off, off+size) des virtuellen Abbildes
static uint64_t romfs_read(uint8_t *dst, uint64_t size, uint64_t off) {
    uint64_t done = 0;
    while (done < size) {
        uint64_t o = off + done, n = size - done;
        if (o < sizeof rom.header) {
            if (n > sizeof rom.header - o) n = sizeof rom.header - o;
            memcpy(dst + done, rom.header + o, n);
        } else if (o < DATA_START) {
            if (n > DATA_START - o) n = DATA_START - o;
            memset(dst + done, 0, n);
        } else if (o < rom.data_end) {
            int lo = 0, hi = rom.nfiles - 1, idx = -1;
            while (lo <= hi) {
                int mid = (lo + hi) / 2;
                if (o < rom.sorted[mid]->data_off) hi = mid - 1;
                else if (o >= rom.sorted[mid]->data_off + rom.sorted[mid]->size) lo = mid + 1;
                else { idx = mid; break; }
            }
            if (idx < 0) {  // alignment gap between files
                uint64_t next = rom.data_end;
                if (lo < rom.nfiles) next = rom.sorted[lo]->data_off;
                if (n > next - o) n = next - o;
                memset(dst + done, 0, n);
            } else {
                RFile *f = rom.sorted[idx];
                uint64_t in = o - f->data_off;
                if (n > f->size - in) n = f->size - in;
                int fd = open(f->path, O_RDONLY);
                ssize_t r = fd >= 0 ? pread(fd, dst + done, n, (off_t)in) : -1;
                if (fd >= 0) close(fd);
                if (r < 0) r = 0;
                if ((uint64_t)r < n) memset(dst + done + r, 0, n - (uint64_t)r);
            }
        } else if (o >= rom.tables_off && o < rom.tables_off + rom.tables_size) {
            if (n > rom.tables_off + rom.tables_size - o) n = rom.tables_off + rom.tables_size - o;
            memcpy(dst + done, rom.tables + (o - rom.tables_off), n);
        } else {
            uint64_t lim = o < rom.tables_off ? rom.tables_off : o + n;
            if (n > lim - o) n = lim - o;
            memset(dst + done, 0, n);
        }
        done += n;
    }
    return done;
}

static RFile *rom_file_at(uint64_t o) {
    int lo = 0, hi = rom.nfiles - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (o < rom.sorted[mid]->data_off) hi = mid - 1;
        else if (o >= rom.sorted[mid]->data_off + rom.sorted[mid]->size) lo = mid + 1;
        else return rom.sorted[mid];
    }
    return NULL;
}

static void storage_romfs(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 0: {  // Read(offset, size) -> B
        uint64_t off = IN(uint64_t, 0), size = IN(uint64_t, 8);
        IpcBuf *b = out_buf(req, 0);
        if (!b) { resp->result = MAKE_RESULT(2, 6001); break; }
        if (size > b->size) size = b->size;
        static int slow_ms = -1;   // BDSP_FS_SLOW_MS=<ms> (diagnostics): log RomFS reads that take longer
        if (slow_ms < 0) slow_ms = getenv("BDSP_FS_SLOW_MS") ? atoi(getenv("BDSP_FS_SLOW_MS")) : 0;
        uint64_t t_read = slow_ms ? rt_now_ns() : 0;
        romfs_read(G2H8(b->addr), size, off);
        if (slow_ms) {
            uint64_t ms = (rt_now_ns() - t_read) / 1000000;
            RFile *f = ms >= (uint64_t)slow_ms ? rom_file_at(off) : NULL;
            if (ms >= (uint64_t)slow_ms)
                LOG("[fs] slow read: %llu ms, %llu bytes, %s\n", (unsigned long long)ms, (unsigned long long)size, f ? f->path : "(tables)");
        }
        rom.nreads++;
        rom.nbytes += size;
        if (getenv("BDSP_LOG_FILES")) {
            static RFile *last;
            RFile *f = rom_file_at(off);
            if (f && f != last) { last = f; LOG("[fs] Lesezugriff in %s (Offset %llu, %llu Byte)\n", f->path, (unsigned long long)(off - f->data_off), (unsigned long long)size); }
        }
        break;
    }
    case 4: OUT(uint64_t, 0) = rom.tables_off + rom.tables_size; resp_size(resp, 8); break;  // GetSize
    case 2: case 5: resp_size(resp, 0x10); break;  // Flush, OperateRange
    default: ipc_note("IStorage(romfs)", req->cmd, 1);
    }
}

void fs_report(FILE *f) { fprintf(f, "RomFS reads: %llu (%llu MiB)\n", (unsigned long long)rom.nreads, (unsigned long long)(rom.nbytes >> 20)); }

// ------------------------------------------------------------------ Host folder as IFileSystem
typedef struct { char root[1024]; } HostFs;
typedef struct { int fd; char path[1100]; } HostFile;
typedef struct { DIR *d; char path[1024]; int mode; } HostDir;

static const char *in_path(IpcReq *req, int i) {
    if (i < req->nx) return G2HC(req->x[i].addr);
    if (i < req->na) return G2HC(req->a[i].addr);
    return "";
}
static void host_path(HostFs *fs, const char *p, char *out, size_t n) { snprintf(out, n, "%s%s%s", fs->root, p[0] == '/' ? "" : "/", p); }

// Saves: deleting becomes renaming to _safety/ (outside the save folder). If the run aborts
// in the middle of saving, the last complete state is kept in <file>.prev.
static bool is_save_root(const HostFs *fs) { return strstr(fs->root, "save_") != NULL; }
static void safety_path(const HostFs *fs, const char *p, const char *suffix, char *out, size_t n) {
    const char *sub = strrchr(fs->root, '/'), *base = strrchr(p, '/');
    snprintf(out, n, "%s/_safety/%s_%s%s", g_save_dir, sub ? sub + 1 : fs->root, base ? base + 1 : p, suffix);
}
static void copy_file(const char *src, const char *dst) {
    int in = open(src, O_RDONLY);
    if (in < 0) return;
    int out = open(dst, O_CREAT | O_TRUNC | O_WRONLY, 0644);
    if (out >= 0) {
        char buf[65536];
        ssize_t n;
        while ((n = read(in, buf, sizeof buf)) > 0) if (write(out, buf, (size_t)n) != n) break;
        close(out);
    }
    close(in);
}
static void save_startup(HostFs *fs) {
    static const char *names[] = {"SaveData.bin", "Backup.bin"};
    char sf[2200], pv[2200], st[2200], dir[1200];
    snprintf(dir, sizeof dir, "%s/_safety", g_save_dir);
    mkdir(dir, 0755);
    for (int i = 0; i < 2; i++) {
        snprintf(sf, sizeof sf, "%s/%s", fs->root, names[i]);
        safety_path(fs, sf, ".prev", pv, sizeof pv);
        safety_path(fs, sf, ".start", st, sizeof st);
        struct stat sb;
        if (!stat(sf, &sb) && sb.st_size > 0) {
            copy_file(sf, st);
        } else if (!stat(pv, &sb) && rename(pv, sf) == 0) {
            LOG("[save] %s was missing or empty, restored from %s\n", names[i], pv);
        }
    }
}
static uint32_t errno_result(void) {
    if (errno == ENOENT || errno == ENOTDIR) return FS_PATH_NOT_FOUND;
    if (errno == EEXIST) return FS_PATH_EXISTS;
    if (errno == ENOTEMPTY) return FS_NOT_EMPTY;
    return FS_UNEXPECTED;
}

static void host_file(Service *s, IpcReq *req, IpcResp *resp) {
    HostFile *f = s->state;
    switch (req->cmd) {
    case 0: {  // Read(option, offset, size) -> B
        int64_t off = IN(int64_t, 8), size = IN(int64_t, 16);
        IpcBuf *b = out_buf(req, 0);
        if ((uint64_t)size > b->size) size = (int64_t)b->size;
        ssize_t n = pread(f->fd, G2H(b->addr), (size_t)size, off);
        OUT(int64_t, 0) = n < 0 ? 0 : n;
        resp_size(resp, 8);
        break;
    }
    case 1: {  // Write(option, offset, size) <- A
        int64_t off = IN(int64_t, 8), size = IN(int64_t, 16);
        IpcBuf *a = in_buf(req, 0);
        if (pwrite(f->fd, G2H(a->addr), (size_t)size, off) < 0) resp->result = errno_result();
        break;
    }
    case 2: fsync(f->fd); break;
    case 3: if (ftruncate(f->fd, IN(int64_t, 0))) resp->result = errno_result(); break;
    case 4: { struct stat sb; fstat(f->fd, &sb); OUT(int64_t, 0) = sb.st_size; resp_size(resp, 8); break; }
    case 5: resp_size(resp, 0x20); break;  // OperateRange
    default: ipc_note("IFile", req->cmd, 1);
    }
}

static void host_directory(Service *s, IpcReq *req, IpcResp *resp) {
    HostDir *d = s->state;
    switch (req->cmd) {
    case 0: {  // Read -> B: entries of 0x310 bytes
        IpcBuf *b = out_buf(req, 0);
        uint8_t *out = G2H8(b->addr);
        int64_t max = (int64_t)(b->size / 0x310), n = 0;
        struct dirent *e;
        while (n < max && (e = readdir(d->d))) {
            if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
            bool isdir = e->d_type == DT_DIR;
            if ((isdir && !(d->mode & 1)) || (!isdir && !(d->mode & 2))) continue;
            uint8_t *ent = out + n * 0x310;
            memset(ent, 0, 0x310);
            strncpy((char *)ent, e->d_name, 0x300);
            ent[0x304] = isdir ? 0 : 1;
            if (!isdir) {
                char p[2048];
                struct stat sb;
                snprintf(p, sizeof p, "%s/%s", d->path, e->d_name);
                if (!stat(p, &sb)) *(int64_t *)(ent + 0x308) = sb.st_size;
            }
            n++;
        }
        OUT(int64_t, 0) = n;
        resp_size(resp, 8);
        break;
    }
    case 1: {  // GetEntryCount: via a separate directory stream, the guest's read position stays untouched
        DIR *cd = opendir(d->path);
        int64_t n = 0;
        struct dirent *e;
        if (cd) {
            while ((e = readdir(cd))) {
                if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
                bool isdir = e->d_type == DT_DIR;
                if ((isdir && !(d->mode & 1)) || (!isdir && !(d->mode & 2))) continue;
                n++;
            }
            closedir(cd);
        }
        OUT(int64_t, 0) = n;
        resp_size(resp, 8);
        break;
    }
    default: ipc_note("IDirectory", req->cmd, 1);
    }
}

static int rm_rf(const char *p, bool keep_root) {
    DIR *d = opendir(p);
    if (!d) return unlink(p);
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char c[2048];
        snprintf(c, sizeof c, "%s/%s", p, e->d_name);
        rm_rf(c, false);
    }
    closedir(d);
    return keep_root ? 0 : rmdir(p);
}

static void host_filesystem(Service *s, IpcReq *req, IpcResp *resp) {
    HostFs *fs = s->state;
    char p[2048], p2[2048];
    host_path(fs, in_path(req, 0), p, sizeof p);
    if (req->cmd <= 9 && strstr(fs->root, "save_")) {
        static int nlog;
        if (nlog++ < 200) LOG("[fs-save] cmd %u %s\n", req->cmd, p);
    }
    switch (req->cmd) {
    case 0: {  // CreateFile(option, size)
        int fd = open(p, O_CREAT | O_EXCL | O_RDWR, 0644);
        if (fd < 0) { resp->result = errno_result(); break; }
        if (ftruncate(fd, IN(int64_t, 8))) resp->result = errno_result();
        close(fd);
        break;
    }
    case 1: {
        struct stat sb;
        if (is_save_root(fs) && !stat(p, &sb) && S_ISREG(sb.st_mode)) {
            char pv[2200];
            safety_path(fs, p, ".prev", pv, sizeof pv);
            if (rename(p, pv)) resp->result = errno_result();
            break;
        }
        if (unlink(p)) resp->result = errno_result();
        break;
    }
    case 2: if (mkdir(p, 0755)) resp->result = errno_result(); break;
    case 3: if (rmdir(p)) resp->result = errno_result(); break;
    case 4: if (rm_rf(p, false)) resp->result = errno_result(); break;
    case 5: case 6:
        host_path(fs, in_path(req, 1), p2, sizeof p2);
        if (rename(p, p2)) resp->result = errno_result();
        break;
    case 7: {
        struct stat sb;
        if (stat(p, &sb)) { resp->result = FS_PATH_NOT_FOUND; break; }
        OUT(uint32_t, 0) = S_ISDIR(sb.st_mode) ? 0 : 1;
        resp_size(resp, 4);
        break;
    }
    case 8: {  // OpenFile(mode)
        uint32_t mode = IN(uint32_t, 0);
        int fd = open(p, (mode & 2) ? O_RDWR : O_RDONLY);
        if (fd < 0) { resp->result = errno_result(); break; }
        HostFile *f = calloc(1, sizeof *f);
        f->fd = fd;
        snprintf(f->path, sizeof f->path, "%s", p);
        ipc_return_object(resp, service_new("IFile", host_file, f));
        break;
    }
    case 9: {
        DIR *d = opendir(p);
        if (!d) { resp->result = errno_result(); break; }
        HostDir *hd = calloc(1, sizeof *hd);
        hd->d = d;
        hd->mode = (int)IN(uint32_t, 0);
        snprintf(hd->path, sizeof hd->path, "%s", p);
        ipc_return_object(resp, service_new("IDirectory", host_directory, hd));
        break;
    }
    case 10: break;  // Commit
    case 11: case 12: OUT(int64_t, 0) = 0x40000000; resp_size(resp, 8); break;
    case 13: rm_rf(p, true); break;
    case 14: memset(resp->data, 0, 0x20); resp_size(resp, 0x20); break;
    case 15: resp_size(resp, 0x10); break;
    default: ipc_note("IFileSystem", req->cmd, 1);
    }
}

static Service *open_host_fs(const char *sub) {
    HostFs *fs = calloc(1, sizeof *fs);
    snprintf(fs->root, sizeof fs->root, "%s/%s", g_save_dir, sub);
    char cmd[1200];
    snprintf(cmd, sizeof cmd, "%s", fs->root);
    for (char *q = cmd + 1; *q; q++)
        if (*q == '/') { *q = 0; mkdir(cmd, 0755); *q = '/'; }
    mkdir(cmd, 0755);
    if (is_save_root(fs)) save_startup(fs);
    LOG("[fs] host folder mounted: %s\n", fs->root);
    return service_new("IFileSystem", host_filesystem, fs);
}

// ------------------------------------------------------------------ fsp-srv
static void fsp_srv(Service *s, IpcReq *req, IpcResp *resp) {
    (void)s;
    switch (req->cmd) {
    case 1: break;  // SetCurrentProcess
    case 18: ipc_return_object(resp, open_host_fs("sdcard")); break;
    case 22: case 23: break;  // CreateSaveDataFileSystem(BySystemSaveDataId)
    case 51: case 52: case 53: {  // OpenSaveDataFileSystem(space, attribute)
        uint8_t type = IN(uint8_t, 0x8 + 0x20);
        char sub[64];
        snprintf(sub, sizeof sub, "save_%u", type);
        ipc_return_object(resp, open_host_fs(sub));
        break;
    }
    case 200: romfs_build_index(); ipc_return_object(resp, service_new("IStorage(romfs)", storage_romfs, NULL)); break;  // OpenDataStorageByCurrentProcess
    case 202: LOG("[fs] OpenDataStorageByDataId %llx (not available)\n", (unsigned long long)IN(uint64_t, 8)); resp->result = MAKE_RESULT(2, 1001); break;
    case 203: resp->result = MAKE_RESULT(2, 1001); break;  // OpenPatchDataStorageByCurrentProcess: no update image
    case 601: OUT(int64_t, 0) = 0x10000000; resp_size(resp, 8); break;  // QuerySaveDataTotalSize
    case 1005: OUT(uint32_t, 0) = 0; resp_size(resp, 4); break;  // GetGlobalAccessLogMode
    case 1003: case 1004: case 1006: case 1002: case 600: break;
    case 1011: memset(resp->data, 0, 0x10); resp_size(resp, 0x10); break;
    default: ipc_note("fsp-srv", req->cmd, 1); resp_size(resp, 0x10);
    }
}

const ServiceDef g_service_defs_fs[] = {{"fsp-srv", fsp_srv}, {NULL, NULL}};
