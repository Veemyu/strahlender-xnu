// Yaz0, SARC, BFLYT and BFLAN readers (see lyt.h). All reads are bounds-checked: malformed input fails the open, it never reads outside the buffer.
#include "lyt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *b, size_t n, size_t o) {
    uint32_t v = 0;
    if (o + 4 <= n) memcpy(&v, b + o, 4);
    return v;
}
static uint16_t rd16(const uint8_t *b, size_t n, size_t o) {
    uint16_t v = 0;
    if (o + 2 <= n) memcpy(&v, b + o, 2);
    return v;
}
static float rdf(const uint8_t *b, size_t n, size_t o) {
    float v = 0;
    if (o + 4 <= n) memcpy(&v, b + o, 4);
    return v;
}
static uint32_t be32(const uint8_t *b) { return (uint32_t)b[0] << 24 | b[1] << 16 | b[2] << 8 | b[3]; }

// Copies the NUL-terminated string at b+o (at most cap-1 characters, never past the buffer)
static void rd_str(char *dst, size_t cap, const uint8_t *b, size_t n, size_t o) {
    size_t i = 0;
    for (; i + 1 < cap && o + i < n && b[o + i]; i++) dst[i] = (char)b[o + i];
    dst[i] = 0;
}

static uint8_t *dup_bytes(const uint8_t *src, size_t size) {
    uint8_t *p = malloc(size ? size : 1);
    if (p) memcpy(p, src, size);
    return p;
}

// ---- Yaz0 -----------------------------------------------------------------------------------------------------

uint8_t *lyt_yaz0(const uint8_t *src, size_t size, size_t *out_size) {
    if (size < 16 || memcmp(src, "Yaz0", 4)) return NULL;
    size_t n = be32(src + 4);
    if (n > ((size_t)1 << 28)) return NULL;
    uint8_t *out = malloc(n ? n : 1);
    if (!out) return NULL;
    size_t p = 16, o = 0;
    while (o < n) {
        if (p >= size) goto bad;
        unsigned h = src[p++];
        for (int i = 0; i < 8 && o < n; i++, h <<= 1) {
            if (h & 0x80) {
                if (p >= size) goto bad;
                out[o++] = src[p++];
            } else {
                if (p + 2 > size) goto bad;
                unsigned b1 = src[p], b2 = src[p + 1];
                p += 2;
                size_t dist = ((b1 & 15) << 8 | b2) + 1, cnt = b1 >> 4;
                if (cnt == 0) {
                    if (p >= size) goto bad;
                    cnt = (size_t)src[p++] + 18;
                } else {
                    cnt += 2;
                }
                if (dist > o) goto bad;
                for (; cnt && o < n; cnt--, o++) out[o] = out[o - dist];
            }
        }
    }
    *out_size = n;
    return out;
bad:
    free(out);
    return NULL;
}

// ---- SARC -----------------------------------------------------------------------------------------------------

static int sarc_parse(LytArchive *a) {
    const uint8_t *d = a->buf;
    size_t n = a->size;
    if (n < 0x20 || memcmp(d, "SARC", 4) || memcmp(d + 0x14, "SFAT", 4)) return -1;
    if (d[6] != 0xFF || d[7] != 0xFE) return -1;   // the Switch firmware is little-endian only
    uint32_t dataoff = rd32(d, n, 0x0c);
    uint32_t cnt = rd16(d, n, 0x1a);
    size_t sfnt = 0x20 + (size_t)cnt * 16, nameoff = sfnt + 8;
    if (sfnt + 8 > n || dataoff > n) return -1;
    a->files = calloc(cnt ? cnt : 1, sizeof *a->files);
    if (!a->files) return -1;
    for (uint32_t i = 0; i < cnt; i++) {
        size_t nd = 0x20 + (size_t)i * 16;
        uint32_t attr = rd32(d, n, nd + 4), ns = rd32(d, n, nd + 8), de = rd32(d, n, nd + 12);
        size_t no = nameoff + (size_t)(attr & 0xFFFFFF) * 4;
        if (no >= n || de < ns || (size_t)dataoff + de > n) return -1;
        size_t k = no;
        while (k < n && d[k]) k++;
        if (k >= n) return -1;
        a->files[i].name = (const char *)d + no;
        a->files[i].data = d + dataoff + ns;
        a->files[i].size = de - ns;
    }
    a->nfiles = cnt;
    return 0;
}

int lyt_archive_open(LytArchive *a, const uint8_t *src, size_t size) {
    memset(a, 0, sizeof *a);
    if (size >= 4 && !memcmp(src, "Yaz0", 4)) a->buf = lyt_yaz0(src, size, &a->size);
    else { a->buf = dup_bytes(src, size); a->size = size; }
    if (!a->buf || sarc_parse(a)) { lyt_archive_free(a); return -1; }
    return 0;
}

static uint8_t *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *b = n >= 0 ? malloc((size_t)n + 1) : NULL;
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); b = NULL; }
    fclose(f);
    if (b) *size = (size_t)n;
    return b;
}

int lyt_archive_load(LytArchive *a, const char *path) {
    size_t n = 0;
    uint8_t *b = read_file(path, &n);
    if (!b) { memset(a, 0, sizeof *a); return -1; }
    int r = lyt_archive_open(a, b, n);
    free(b);
    return r;
}

const LytFile *lyt_archive_find(const LytArchive *a, const char *name) {
    for (uint32_t i = 0; i < a->nfiles; i++)
        if (!strcmp(a->files[i].name, name)) return &a->files[i];
    return NULL;
}

void lyt_archive_free(LytArchive *a) {
    free(a->buf);
    free(a->files);
    memset(a, 0, sizeof *a);
}

// ---- BFLYT ----------------------------------------------------------------------------------------------------

const char *lyt_pane_kind_name(int kind) {
    static const char *const k[] = {"pan1", "pic1", "txt1", "prt1", "bnd1", "wnd1"};
    return kind >= 0 && kind < 6 ? k[kind] : "?";
}

int lyt_layout_find_pane(const LytLayout *l, const char *name) {
    for (uint32_t i = 0; i < l->npanes; i++)
        if (!strcmp(l->panes[i].name, name)) return (int)i;
    return -1;
}

static int parse_names(char (**out)[65], uint32_t *count, const uint8_t *b, size_t bn) {
    uint32_t cnt = rd32(b, bn, 0);
    if (cnt > bn / 4) return -1;
    *out = calloc(cnt ? cnt : 1, sizeof **out);
    if (!*out) return -1;
    for (uint32_t i = 0; i < cnt; i++) rd_str((*out)[i], 65, b, bn, 4 + (size_t)rd32(b, bn, 4 + i * 4));
    *count = cnt;
    return 0;
}

static void parse_mat(LytMaterial *m, const uint8_t *d, size_t n) {
    rd_str(m->name, sizeof m->name, d, n, 0);
    m->flags = rd32(d, n, 28);
    for (int i = 0; i < 4; i++) { m->black[i] = 32u + i < n ? d[32 + i] : 0; m->white[i] = 40u + i < n ? d[40 + i] : 0; }
    m->ntex = m->flags & 3;
    m->nmtx = (m->flags >> 2) & 3;
    m->ngen = (m->flags >> 4) & 3;
    size_t o = 44;
    for (int i = 0; i < m->ntex; i++, o += 4) {
        m->tex[i].idx = rd16(d, n, o);
        m->tex[i].wrap_s = o + 2 < n ? d[o + 2] : 0;
        m->tex[i].wrap_t = o + 3 < n ? d[o + 3] : 0;
    }
    for (int i = 0; i < m->nmtx; i++, o += 20)
        for (int k = 0; k < 5; k++) m->srt[i][k] = rdf(d, n, o + k * 4);
}

static int parse_pane(LytPane *p, int kind, const uint8_t *b, size_t bn) {
    if (bn < 76) return -1;
    memset(p, 0, sizeof *p);
    p->kind = kind;
    p->flags = b[0]; p->base = b[1]; p->alpha = b[2]; p->mag = b[3];
    rd_str(p->name, sizeof p->name, b, 28, 4);
    for (int i = 0; i < 3; i++) { p->t[i] = rdf(b, bn, 36 + i * 4); p->r[i] = rdf(b, bn, 48 + i * 4); }
    for (int i = 0; i < 2; i++) { p->s[i] = rdf(b, bn, 60 + i * 4); p->size[i] = rdf(b, bn, 68 + i * 4); }
    p->raw = b; p->raw_size = (uint32_t)bn;
    p->parent = p->first_child = p->next_sibling = -1;
    if (kind == LYT_PIC) {
        if (bn >= 92) memcpy(p->vcol, b + 76, 16);
        p->mat = rd16(b, bn, 92);
        p->ntc = bn > 94 ? b[94] : 0;
        for (unsigned i = 0; i < p->ntc && i < 4; i++)
            for (int k = 0; k < 8; k++) p->tc[i][k] = rdf(b, bn, 96 + i * 32 + k * 4);
    } else if (kind == LYT_TXT) {
        p->text_bytes = rd16(b, bn, 76); p->text_len = rd16(b, bn, 78);
        p->mat = rd16(b, bn, 80); p->font = rd16(b, bn, 82);
        p->halign = bn > 84 ? b[84] : 0; p->valign = bn > 85 ? b[85] : 0;
        p->text_flags = bn > 86 ? b[86] : 0;
        p->italic = rdf(b, bn, 88);
        p->text_off = rd32(b, bn, 92);
        for (int i = 0; i < 4; i++) { p->top_color[i] = 96u + i < bn ? b[96 + i] : 0; p->bottom_color[i] = 100u + i < bn ? b[100 + i] : 0; }
        p->font_size[0] = rdf(b, bn, 104); p->font_size[1] = rdf(b, bn, 108);
        p->char_space = rdf(b, bn, 112); p->line_space = rdf(b, bn, 116);
    } else if (kind == LYT_PRT) {
        p->nprop = rd32(b, bn, 76);
        p->pscale[0] = rdf(b, bn, 80); p->pscale[1] = rdf(b, bn, 84);
        if (p->nprop > bn / 40) return -1;
        p->props = calloc(p->nprop ? p->nprop : 1, sizeof *p->props);
        if (!p->props) return -1;
        for (uint32_t i = 0; i < p->nprop; i++) {
            size_t o = 88 + (size_t)i * 40;
            rd_str(p->props[i].name, sizeof p->props[i].name, b, o + 24 <= bn ? o + 24 : bn, o);
            p->props[i].usage = o + 24 < bn ? b[o + 24] : 0;
            for (int k = 0; k < 3; k++) p->props[i].off[k] = rd32(b, bn, o + 28 + k * 4);
        }
        rd_str(p->part, sizeof p->part, b, bn, 88 + (size_t)p->nprop * 40);
    }
    return 0;
}

static int parse_group(LytGroup *g, const uint8_t *b, size_t bn) {
    rd_str(g->name, sizeof g->name, b, bn, 0);
    g->npanes = rd16(b, bn, 34);
    if (g->npanes > bn / 24) return -1;
    g->panes = calloc(g->npanes ? g->npanes : 1, sizeof *g->panes);
    if (!g->panes) return -1;
    for (uint32_t i = 0; i < g->npanes; i++) rd_str(g->panes[i], 25, b, bn, 36 + (size_t)i * 24);
    return 0;
}

int lyt_layout_open(LytLayout *l, const uint8_t *src, size_t size) {
    memset(l, 0, sizeof *l);
    if (size < 0x14 || memcmp(src, "FLYT", 4)) return -1;
    l->buf = dup_bytes(src, size);
    l->size = size;
    if (!l->buf) return -1;
    const uint8_t *d = l->buf;
    l->version = rd32(d, size, 8);
    size_t o = rd16(d, size, 6);
    uint32_t nsec = rd16(d, size, 0x10);
    uint32_t cap = 0;
    int *stack = NULL, *lastkid = NULL, depth = 0, last = -1;
    int err = 0;
    size_t maxdepth = 64;
    stack = malloc(maxdepth * sizeof *stack);
    if (!stack) err = 1;
    while (!err && nsec > 0 && o + 8 <= size) {
        const char *k = (const char *)d + o;
        size_t sz = rd32(d, size, o + 4);
        if (sz < 8 || o + sz > size) { err = 1; break; }
        const uint8_t *b = d + o + 8;
        size_t bn = sz - 8;
        nsec--;
        int kind = -1;
        if (!memcmp(k, "pan1", 4)) kind = LYT_PAN;
        else if (!memcmp(k, "pic1", 4)) kind = LYT_PIC;
        else if (!memcmp(k, "txt1", 4)) kind = LYT_TXT;
        else if (!memcmp(k, "prt1", 4)) kind = LYT_PRT;
        else if (!memcmp(k, "bnd1", 4)) kind = LYT_BND;
        else if (!memcmp(k, "wnd1", 4)) kind = LYT_WND;
        if (!memcmp(k, "lyt1", 4)) {
            l->origin = bn > 0 ? b[0] : 0;
            for (int i = 0; i < 2; i++) { l->size_xy[i] = rdf(b, bn, 4 + i * 4); l->parts_size[i] = rdf(b, bn, 12 + i * 4); }
        } else if (!memcmp(k, "txl1", 4)) {
            err = parse_names(&l->tex, &l->ntex, b, bn);
        } else if (!memcmp(k, "fnl1", 4)) {
            err = parse_names(&l->fonts, &l->nfonts, b, bn);
        } else if (!memcmp(k, "mat1", 4)) {
            uint32_t cnt = rd32(b, bn, 0);
            if (cnt > bn / 4) { err = 1; break; }
            l->mats = calloc(cnt ? cnt : 1, sizeof *l->mats);
            if (!l->mats) { err = 1; break; }
            l->nmats = cnt;
            for (uint32_t i = 0; i < cnt; i++) {
                size_t a = rd32(b, bn, 4 + i * 4), e = i + 1 < cnt ? rd32(b, bn, 8 + i * 4) : sz;
                if (a > e || e > sz) { err = 1; break; }
                parse_mat(&l->mats[i], d + o + a, e - a);
            }
        } else if (kind >= 0) {
            if (l->npanes == cap) {
                cap = cap ? cap * 2 : 64;
                LytPane *np = realloc(l->panes, cap * sizeof *np);
                int *nl = realloc(lastkid, cap * sizeof *nl);
                if (np) l->panes = np;
                if (nl) lastkid = nl;
                if (!np || !nl) { err = 1; break; }
            }
            LytPane *p = &l->panes[l->npanes];
            if (parse_pane(p, kind, b, bn)) { err = 1; break; }
            int idx = (int)l->npanes++;
            lastkid[idx] = -1;
            if (depth > 0) {
                int par = stack[depth - 1];
                p->parent = par;
                if (lastkid[par] < 0) l->panes[par].first_child = idx;
                else l->panes[lastkid[par]].next_sibling = idx;
                lastkid[par] = idx;
            }
            last = idx;
        } else if (!memcmp(k, "pas1", 4)) {
            if (last < 0 || (size_t)depth >= maxdepth) { err = 1; break; }
            stack[depth++] = last;
        } else if (!memcmp(k, "pae1", 4)) {
            if (depth == 0) { err = 1; break; }
            depth--;
        } else if (!memcmp(k, "grp1", 4)) {
            LytGroup *ng = realloc(l->groups, (l->ngroups + 1) * sizeof *ng);
            if (!ng) { err = 1; break; }
            l->groups = ng;
            memset(&ng[l->ngroups], 0, sizeof *ng);
            if (parse_group(&ng[l->ngroups], b, bn)) { err = 1; break; }
            l->ngroups++;
        }
        o += sz;
    }
    free(stack);
    free(lastkid);
    if (err || l->npanes == 0) { lyt_layout_free(l); return -1; }
    return 0;
}

void lyt_layout_free(LytLayout *l) {
    for (uint32_t i = 0; i < l->npanes; i++) free(l->panes[i].props);
    for (uint32_t i = 0; i < l->ngroups; i++) free(l->groups[i].panes);
    free(l->panes); free(l->groups); free(l->mats); free(l->tex); free(l->fonts); free(l->buf);
    memset(l, 0, sizeof *l);
}

// ---- BFLAN ----------------------------------------------------------------------------------------------------

float lyt_curve_eval(const float (*keys)[3], int nkeys, int curve, float t) {
    if (nkeys <= 0) return 0;
    if (t <= keys[0][0]) return keys[0][1];
    if (t >= keys[nkeys - 1][0]) return keys[nkeys - 1][1];
    for (int i = 0; i + 1 < nkeys; i++) {
        const float *a = keys[i], *b = keys[i + 1];
        if (a[0] <= t && t < b[0]) {
            if (curve == 1) return a[1];
            float h = b[0] - a[0], s = (t - a[0]) / h;
            float s2 = s * s, s3 = s2 * s;
            return (2 * s3 - 3 * s2 + 1) * a[1] + (s3 - 2 * s2 + s) * h * a[2] + (-2 * s3 + 3 * s2) * b[1] + (s3 - s2) * h * b[2];
        }
    }
    return keys[nkeys - 1][1];
}

int lyt_anim_open(LytAnim *a, const uint8_t *src, size_t size) {
    memset(a, 0, sizeof *a);
    if (size < 0x14 || memcmp(src, "FLAN", 4)) return -1;
    a->buf = dup_bytes(src, size);
    if (!a->buf) return -1;
    const uint8_t *d = a->buf;
    size_t o = rd16(d, size, 6);
    uint32_t nsec = rd16(d, size, 0x10);
    uint32_t cap = 0;
    int err = 0;
    while (!err && nsec > 0 && o + 8 <= size) {
        size_t sz = rd32(d, size, o + 4);
        if (sz < 8 || o + sz > size) { err = 1; break; }
        nsec--;
        if (!memcmp(d + o, "pat1", 4)) {
            uint16_t gc = rd16(d, size, o + 10);
            uint32_t noff = rd32(d, size, o + 12), goff = rd32(d, size, o + 16);
            a->start = (int16_t)rd16(d, size, o + 24); a->end = (int16_t)rd16(d, size, o + 26);
            rd_str(a->name, sizeof a->name, d, size, o + noff);
            if (gc > sz / 36) { err = 1; break; }
            a->groups = calloc(gc ? gc : 1, sizeof *a->groups);
            if (!a->groups) { err = 1; break; }
            a->ngroups = gc;
            for (uint32_t i = 0; i < gc; i++) rd_str(a->groups[i], 29, d, size, o + goff + (size_t)i * 36);
        } else if (!memcmp(d + o, "pai1", 4)) {
            a->frames = rd16(d, size, o + 8);
            uint32_t ec = rd16(d, size, o + 14), eo = rd32(d, size, o + 16);
            if (ec > sz / 4) { err = 1; break; }
            for (uint32_t e = 0; e < ec && !err; e++) {
                size_t ea = o + rd32(d, size, o + eo + e * 4);
                unsigned tcnt = ea + 29 < size ? d[ea + 28] : 0, kind = ea + 29 < size ? d[ea + 29] : 0;
                for (unsigned t = 0; t < tcnt && !err; t++) {
                    size_t ta = ea + rd32(d, size, ea + 32 + t * 4);
                    if (ta + 8 > size) { err = 1; break; }
                    int tag = !memcmp(d + ta, "FLPA", 4) ? LYT_TAG_FLPA : !memcmp(d + ta, "FLVI", 4) ? LYT_TAG_FLVI :
                              !memcmp(d + ta, "FLVC", 4) ? LYT_TAG_FLVC : -1;
                    unsigned n = d[ta + 4];
                    if (tag < 0) { a->nskipped++; continue; }
                    for (unsigned i = 0; i < n; i++) {
                        size_t b = ta + rd32(d, size, ta + 8 + i * 4);
                        if (b + 12 > size) { err = 1; break; }
                        if (a->nentries == cap) {
                            cap = cap ? cap * 2 : 64;
                            LytAnimEntry *ne = realloc(a->entries, cap * sizeof *ne);
                            if (!ne) { err = 1; break; }
                            a->entries = ne;
                        }
                        LytAnimEntry *x = &a->entries[a->nentries];
                        memset(x, 0, sizeof *x);
                        rd_str(x->pane, sizeof x->pane, d, size, ea);
                        x->kind = (uint8_t)kind; x->tag = (uint8_t)tag;
                        x->id = d[b]; x->target = d[b + 1];
                        x->curve = rd16(d, size, b + 2);
                        unsigned kc = rd16(d, size, b + 4);
                        size_t ko = b + rd32(d, size, b + 8);
                        a->nentries++;
                        if (x->curve != 1 && x->curve != 2) continue;
                        size_t stride = x->curve == 2 ? 12 : 8;
                        if (kc > size / stride || ko + (size_t)kc * stride > size) { err = 1; break; }
                        x->keys = calloc(kc ? kc : 1, sizeof *x->keys);
                        if (!x->keys) { err = 1; break; }
                        x->nkeys = (uint16_t)kc;
                        for (unsigned j = 0; j < kc; j++) {
                            size_t ka = ko + j * stride;
                            x->keys[j][0] = rdf(d, size, ka);
                            if (x->curve == 2) { x->keys[j][1] = rdf(d, size, ka + 4); x->keys[j][2] = rdf(d, size, ka + 8); }
                            else x->keys[j][1] = rd16(d, size, ka + 4);
                        }
                    }
                }
            }
        }
        o += sz;
    }
    if (err) { lyt_anim_free(a); return -1; }
    return 0;
}

void lyt_anim_free(LytAnim *a) {
    for (uint32_t i = 0; i < a->nentries; i++) free(a->entries[i].keys);
    free(a->entries); free(a->groups); free(a->buf);
    memset(a, 0, sizeof *a);
}

int lyt_anim_eval(const LytAnim *a, const char *pane, int tag, int target, float t, float *v) {
    int hit = 0;
    for (uint32_t i = 0; i < a->nentries; i++) {
        const LytAnimEntry *e = &a->entries[i];
        if (e->tag != tag || e->target != target || e->nkeys == 0 || strcmp(e->pane, pane)) continue;
        *v = lyt_curve_eval((const float (*)[3])e->keys, e->nkeys, e->curve, t);
        hit = 1;   // later entries win, like the prototype
    }
    return hit;
}
