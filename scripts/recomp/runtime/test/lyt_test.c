// Test of the layout readers (lyt.c, lyt_tex.c). Part 1 is synthetic (invented bytes, no game content): Yaz0, SARC, curves, texture swizzle.
// Part 2 reads the user's own firmware layouts when BDSP_FIRMWARE_DATA (or argv[1]) points at a folder with swkbd/lyt/*.szs and checks the
// results for consistency; it is skipped when they are not there. "lyt_test dump <archive.szs>" prints every parsed value in a plain text
// form so that the output can be diffed against the Python prototype.
// Build and run: scripts/recomp/runtime/test/run_lyt_test.sh
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../lyt.h"

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)

static void put32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }
static void put16(uint8_t *p, uint16_t v) { memcpy(p, &v, 2); }

// Yaz0 stream that uses literals and one back-reference of each length form
static void test_yaz0(void) {
    uint8_t s[64] = "Yaz0";
    s[4] = 0; s[5] = 0; s[6] = 0; s[7] = 32;               // 32 bytes out
    size_t p = 16;
    s[p++] = 0xF8;                                         // 5 literals, then three references
    for (int i = 0; i < 5; i++) s[p++] = (uint8_t)('a' + i);
    s[p++] = 0x10; s[p++] = 4;                             // 3 bytes from 5 back: "abc"
    s[p++] = 0x00; s[p++] = 7; s[p++] = 2;                 // long form: 2 + 18 = 20 bytes from 8 back
    s[p++] = 0x20; s[p++] = 0;                             // 4 bytes from 1 back
    size_t n = 0;
    uint8_t *o = lyt_yaz0(s, p, &n);
    CHECK(o && n == 32);
    if (o) {
        CHECK(!memcmp(o, "abcdeabc", 8));
        for (int i = 8; i < 28; i++) CHECK(o[i] == o[i - 8]);
        for (int i = 28; i < 32; i++) CHECK(o[i] == o[27]);
        free(o);
    }
    s[p - 1] = 200;                                        // distance 201, more than has been written
    CHECK(lyt_yaz0(s, p, &n) == NULL);
    CHECK(lyt_yaz0(s, 10, &n) == NULL);                    // truncated header
    o = lyt_yaz0((const uint8_t *)"Yaz0\0\0\0\0\0\0\0\0\0\0\0\0", 16, &n);
    CHECK(o != NULL && n == 0);
    free(o);
}

static void test_sarc(void) {
    uint8_t b[256] = {0};
    memcpy(b, "SARC", 4);
    put16(b + 4, 0x14); b[6] = 0xFF; b[7] = 0xFE;
    memcpy(b + 0x14, "SFAT", 4); put16(b + 0x18, 0x0C); put16(b + 0x1A, 2);
    put32(b + 0x20 + 4, 0x01000000); put32(b + 0x20 + 8, 0); put32(b + 0x20 + 12, 4);   // node 0: name word 0, data 0..4
    put32(b + 0x30 + 4, 0x01000001); put32(b + 0x30 + 8, 4); put32(b + 0x30 + 12, 9);   // node 1: name word 1, data 4..9
    memcpy(b + 0x40, "SFNT", 4); put16(b + 0x44, 8);
    memcpy(b + 0x48, "a.x\0", 4);
    memcpy(b + 0x4C, "dir/b\0\0\0", 8);
    put32(b + 0x0C, 0x60);
    memcpy(b + 0x60, "ABCD", 4); memcpy(b + 0x64, "12345", 5);
    LytArchive a;
    CHECK(lyt_archive_open(&a, b, 0x70) == 0);
    CHECK(a.nfiles == 2);
    const LytFile *f = lyt_archive_find(&a, "a.x");
    CHECK(f && f->size == 4 && !memcmp(f->data, "ABCD", 4));
    f = lyt_archive_find(&a, "dir/b");
    CHECK(f && f->size == 5 && !memcmp(f->data, "12345", 5));
    CHECK(lyt_archive_find(&a, "nope") == NULL);
    lyt_archive_free(&a);
    put32(b + 0x30 + 12, 0x7000);                          // data end beyond the image
    CHECK(lyt_archive_open(&a, b, 0x70) != 0);
    CHECK(lyt_archive_open(&a, b, 0x30) != 0);            // truncated
}

static void test_curve(void) {
    float h[2][3] = {{0, 0, 0}, {10, 1, 0}};
    CHECK(fabsf(lyt_curve_eval(h, 2, 2, 5) - 0.5f) < 1e-5f);
    CHECK(lyt_curve_eval(h, 2, 2, -3) == 0 && lyt_curve_eval(h, 2, 2, 99) == 1);
    float st[2][3] = {{0, 7, 0}, {4, 9, 0}};
    CHECK(lyt_curve_eval(st, 2, 1, 3.9f) == 7 && lyt_curve_eval(st, 2, 1, 4) == 9);
    CHECK(lyt_curve_eval(h, 0, 2, 1) == 0);
}

// BC4 block with two equal end points decodes to a flat colour, and the block-linear order places block 0 first
static void test_tex(void) {
    LytTex t;
    memset(&t, 0, sizeof t);
    t.fmt = 0x1d01; t.w = 4; t.h = 4; t.bw = t.bh = 1; t.block_bytes = 8; t.chan = 0x05040302;
    uint8_t blk[8] = {200, 200, 0, 0, 0, 0, 0, 0};
    t.blocks = blk;
    uint8_t px[64];
    CHECK(lyt_tex_decode_raw(&t, px) == 1);
    CHECK(px[0] == 200 && px[1] == 200 && px[2] == 200 && px[3] == 255 && px[63] == 255);
    t.chan = 0x03020201;                                   // R=one, G=R, B=G, A=R-of-source
    CHECK(lyt_tex_decode(&t, px) == 1);
    CHECK(px[0] == 255 && px[1] == 200 && px[2] == 200 && px[3] == 200);
    t.fmt = 0x2d01;
    CHECK(lyt_tex_decode_raw(&t, px) == 0 && lyt_tex_is_astc(&t));
    LytTexSet ts;
    CHECK(lyt_texset_open(&ts, (const uint8_t *)"BNTX____________________________", 32) == 0 && ts.ntex == 0);
    lyt_texset_free(&ts);
    CHECK(lyt_texset_open(&ts, (const uint8_t *)"nope", 4) != 0);
}

// ---- firmware part --------------------------------------------------------------------------------------------

static const char *lyt_dir;

static int load_archive(LytArchive *a, const char *name) {
    char path[1024];
    snprintf(path, sizeof path, "%s/swkbd/lyt/%s.szs", lyt_dir, name);
    if (!lyt_archive_load(a, path)) return 0;
    snprintf(path, sizeof path, "%s/swkbd/romfs/lyt/%s.szs", lyt_dir, name);   // layout of a plain RomFS extraction
    return lyt_archive_load(a, path);
}

static int cmp_file(const void *x, const void *y) { return strcmp(((const LytFile *)x)->name, ((const LytFile *)y)->name); }

static const char *ext(const char *n) { const char *e = strrchr(n, '.'); return e ? e : ""; }

static void dump_layout(const LytFile *f) {
    LytLayout l;
    if (lyt_layout_open(&l, f->data, f->size)) { printf("FAIL %s\n", f->name); return; }
    printf("L %s size %.1f %.1f parts %.1f %.1f origin %d panes %u mats %u\n", f->name, l.size_xy[0], l.size_xy[1], l.parts_size[0], l.parts_size[1], l.origin, l.npanes, l.nmats);
    for (uint32_t i = 0; i < l.ntex; i++) printf(" tex %s\n", l.tex[i]);
    for (uint32_t i = 0; i < l.nfonts; i++) printf(" font %s\n", l.fonts[i]);
    for (uint32_t i = 0; i < l.nmats; i++) {
        const LytMaterial *m = &l.mats[i];
        printf(" mat %s flags %x white %d,%d,%d,%d tex", m->name, m->flags, m->white[0], m->white[1], m->white[2], m->white[3]);
        for (int k = 0; k < m->ntex; k++) printf(" %d", m->tex[k].idx);
        for (int k = 0; k < m->nmtx; k++) printf(" srt %.3f,%.3f,%.3f,%.3f,%.3f", m->srt[k][0], m->srt[k][1], m->srt[k][2], m->srt[k][3], m->srt[k][4]);
        printf("\n");
    }
    for (uint32_t i = 0; i < l.npanes; i++) {
        const LytPane *p = &l.panes[i];
        printf(" P %s %s parent %d base %x flags %x alpha %d mag %d t %.4f,%.4f,%.4f s %.4f,%.4f size %.4f,%.4f", lyt_pane_kind_name(p->kind), p->name,
               p->parent, p->base, p->flags, p->alpha, p->mag, p->t[0], p->t[1], p->t[2], p->s[0], p->s[1], p->size[0], p->size[1]);
        if (p->kind == LYT_PIC) printf(" mat %d ntc %d vcol %d,%d,%d,%d", p->mat, p->ntc, p->vcol[0][0], p->vcol[0][1], p->vcol[0][2], p->vcol[0][3]);
        if (p->kind == LYT_TXT) printf(" tbytes %d tlen %d mat %d font %d align %d,%d fsize %.1f,%.1f", p->text_bytes, p->text_len, p->mat, p->font, p->halign, p->valign, p->font_size[0], p->font_size[1]);
        if (p->kind == LYT_PRT) printf(" nprop %u pscale %.4f,%.4f part %s", p->nprop, p->pscale[0], p->pscale[1], p->part);
        printf("\n");
    }
    for (uint32_t i = 0; i < l.ngroups; i++) printf(" grp %s %u\n", l.groups[i].name, l.groups[i].npanes);
    lyt_layout_free(&l);
}

static void dump_anim(const LytFile *f) {
    LytAnim a;
    if (lyt_anim_open(&a, f->data, f->size)) { printf("FAIL %s\n", f->name); return; }
    printf("A %s name %s start %d end %d frames %d entries %u groups %u\n", f->name, a.name, a.start, a.end, a.frames, a.nentries, a.ngroups);
    for (uint32_t i = 0; i < a.nentries; i++) {
        const LytAnimEntry *e = &a.entries[i];
        printf(" E %s %d %d %d keys %d", e->pane, e->tag, e->target, e->curve, e->nkeys);
        if (e->nkeys) {
            float t[3] = {0, a.frames / 2.0f, (float)a.frames};
            for (int k = 0; k < 3; k++) printf(" %.3f", lyt_curve_eval((const float (*)[3])e->keys, e->nkeys, e->curve, t[k]));
        }
        printf("\n");
    }
    lyt_anim_free(&a);
}

static void dump_tex(const LytFile *f) {
    LytTexSet ts;
    if (lyt_texset_open(&ts, f->data, f->size)) { printf("FAIL %s\n", f->name); return; }
    for (uint32_t i = 0; i < ts.ntex; i++) {
        const LytTex *t = &ts.tex[i];
        uint32_t sum = 2166136261u;
        uint8_t *px = malloc((size_t)t->w * t->h * 4 + 4);
        int ok = px && lyt_tex_decode_raw(t, px);
        if (ok) for (size_t k = 0; k < (size_t)t->w * t->h * 4; k++) sum = (sum ^ px[k]) * 16777619u;
        printf("T %s %s fmt %x %ux%u chan %x decoded %d hash %08x\n", f->name, t->name, t->fmt, t->w, t->h, t->chan, ok, ok ? sum : 0);
        free(px);
    }
    lyt_texset_free(&ts);
}

static void dump_archive(LytArchive *a) {
    qsort(a->files, a->nfiles, sizeof *a->files, cmp_file);
    for (uint32_t i = 0; i < a->nfiles; i++) {
        const LytFile *f = &a->files[i];
        if (!strcmp(ext(f->name), ".bflyt")) dump_layout(f);
        else if (!strcmp(ext(f->name), ".bflan")) dump_anim(f);
        else if (!strcmp(ext(f->name), ".bntx")) dump_tex(f);
    }
}

static void test_firmware(void) {
    static const char *const names[] = {"Qwerty", "50on", "Numeric", "Sign", "Swkbd", "common"};
    LytArchive a;
    if (load_archive(&a, "Qwerty")) { printf("firmware layouts not found under %s, skipped\n", lyt_dir); return; }
    lyt_archive_free(&a);
    unsigned layouts = 0, anims = 0, texs = 0;
    for (unsigned n = 0; n < sizeof names / sizeof *names; n++) {
        CHECK(load_archive(&a, names[n]) == 0);
        for (uint32_t i = 0; i < a.nfiles; i++) {
            const LytFile *f = &a.files[i];
            if (!strcmp(ext(f->name), ".bflyt")) {
                LytLayout l;
                CHECK(lyt_layout_open(&l, f->data, f->size) == 0);
                if (!l.npanes) continue;
                layouts++;
                // tree integrity: every pane except the root has a parent that lists it among its children
                CHECK(l.panes[0].parent == -1);
                for (uint32_t k = 1; k < l.npanes; k++) {
                    int par = l.panes[k].parent, found = 0;
                    CHECK(par >= 0 && par < (int)k);
                    for (int c = l.panes[par].first_child; c >= 0; c = l.panes[c].next_sibling) found += c == (int)k;
                    CHECK(found == 1);
                }
                for (uint32_t k = 0; k < l.npanes; k++) if (l.panes[k].kind == LYT_PIC) CHECK(l.panes[k].mat < l.nmats);
                if (!strcmp(f->name, "blyt/SwkbdBaseKeytopQwerty.bflyt")) {
                    int keys = 0;
                    for (uint32_t k = 0; k < l.npanes; k++) {
                        const LytPane *p = &l.panes[k];
                        if (strncmp(p->name, "L_BtnNml_", 9)) continue;
                        keys++;
                        CHECK(p->kind == LYT_PRT && !strcmp(p->part, "SwkbdBtn_Root"));
                    }
                    CHECK(keys == 44);
                    CHECK(l.size_xy[0] == 1280 && l.size_xy[1] == 720);
                }
                lyt_layout_free(&l);
            } else if (!strcmp(ext(f->name), ".bflan")) {
                LytAnim an;
                CHECK(lyt_anim_open(&an, f->data, f->size) == 0);
                CHECK(an.end >= an.start);
                anims++;
                lyt_anim_free(&an);
            } else if (!strcmp(ext(f->name), ".bntx")) {
                LytTexSet ts;
                CHECK(lyt_texset_open(&ts, f->data, f->size) == 0 && ts.ntex > 0);
                for (uint32_t k = 0; k < ts.ntex; k++) {
                    const LytTex *t = &ts.tex[k];
                    CHECK(t->name[0] && t->w && t->h && t->blocks);
                    uint8_t *px = malloc((size_t)t->w * t->h * 4);
                    if (!lyt_tex_is_astc(t)) CHECK(lyt_tex_decode(t, px) == 1);
                    free(px);
                    texs++;
                }
                lyt_texset_free(&ts);
            }
        }
        lyt_archive_free(&a);
    }
    CHECK(layouts > 20 && anims > 100 && texs > 10);
    printf("firmware layouts: %u layouts, %u animations, %u textures read\n", layouts, anims, texs);
}

int main(int argc, char **argv) {
    if (argc >= 3 && !strcmp(argv[1], "dump")) {
        LytArchive a;
        if (lyt_archive_load(&a, argv[2])) { fprintf(stderr, "cannot open %s\n", argv[2]); return 2; }
        dump_archive(&a);
        lyt_archive_free(&a);
        return 0;
    }
    lyt_dir = argc > 1 ? argv[1] : getenv("BDSP_FIRMWARE_DATA");
    test_yaz0();
    test_sarc();
    test_curve();
    test_tex();
    if (lyt_dir) test_firmware();
    else printf("BDSP_FIRMWARE_DATA not set, firmware part skipped\n");
    if (fails) { printf("%d errors\n", fails); return 1; }
    printf("lyt_test: ok\n");
    return 0;
}
