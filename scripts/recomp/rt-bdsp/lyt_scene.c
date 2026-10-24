// Layout bank, instances with animation state, and the scene builder (see lyt_scene.h).
#include "lyt_scene.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ARCH 8
#define MAX_PLAY 16
#define MAX_DEPTH 8

typedef struct { char name[96]; LytLayout lay; int arch; } BankLayout;
typedef struct { char name[96]; LytAnim anim; } BankAnim;

struct LytBank {
    LytArchive arch[MAX_ARCH];
    LytTexSet tex[MAX_ARCH];
    int narch;
    BankLayout **layouts; int nlayouts;
    BankAnim **anims; int nanims;
};

static int load_one(LytArchive *a, const char *root, const char *name) {
    char path[1024];
    snprintf(path, sizeof path, "%s/swkbd/lyt/%s.szs", root, name);
    if (!lyt_archive_load(a, path)) return 0;
    snprintf(path, sizeof path, "%s/swkbd/romfs/lyt/%s.szs", root, name);
    return lyt_archive_load(a, path);
}

LytBank *lytbank_open(const char *root, const char *const *archives, int n) {
    LytBank *b = calloc(1, sizeof *b);
    if (!b) return NULL;
    for (int i = 0; i < n && b->narch < MAX_ARCH; i++) {
        LytArchive *a = &b->arch[b->narch];
        if (load_one(a, root, archives[i])) continue;
        const LytFile *f = lyt_archive_find(a, "timg/__Combined.bntx");
        if (f) lyt_texset_open(&b->tex[b->narch], f->data, f->size);
        b->narch++;
    }
    if (!b->narch) { free(b); return NULL; }
    return b;
}

void lytbank_free(LytBank *b) {
    if (!b) return;
    for (int i = 0; i < b->nlayouts; i++) { lyt_layout_free(&b->layouts[i]->lay); free(b->layouts[i]); }
    for (int i = 0; i < b->nanims; i++) { lyt_anim_free(&b->anims[i]->anim); free(b->anims[i]); }
    for (int i = 0; i < b->narch; i++) { lyt_texset_free(&b->tex[i]); lyt_archive_free(&b->arch[i]); }
    free(b->layouts); free(b->anims); free(b);
}

static BankLayout *bank_layout(LytBank *b, const char *name) {
    for (int i = 0; i < b->nlayouts; i++)
        if (!strcmp(b->layouts[i]->name, name)) return b->layouts[i]->arch >= 0 ? b->layouts[i] : NULL;
    BankLayout *bl = calloc(1, sizeof *bl);
    if (!bl) return NULL;
    snprintf(bl->name, sizeof bl->name, "%s", name);
    bl->arch = -1;
    char file[160];
    snprintf(file, sizeof file, "blyt/%s.bflyt", name);
    for (int i = 0; i < b->narch && bl->arch < 0; i++) {
        const LytFile *f = lyt_archive_find(&b->arch[i], file);
        if (f && !lyt_layout_open(&bl->lay, f->data, f->size)) bl->arch = i;
    }
    BankLayout **nl = realloc(b->layouts, (b->nlayouts + 1) * sizeof *nl);
    if (!nl) { if (bl->arch >= 0) lyt_layout_free(&bl->lay); free(bl); return NULL; }
    b->layouts = nl;
    b->layouts[b->nlayouts++] = bl;       // negative results are cached too
    return bl->arch >= 0 ? bl : NULL;
}

const LytLayout *lytbank_layout(LytBank *b, const char *name) {
    BankLayout *bl = bank_layout(b, name);
    return bl ? &bl->lay : NULL;
}

const LytAnim *lytbank_anim(LytBank *b, const LytLayout *owner, const char *tag) {
    const char *lname = NULL;
    int arch = 0;
    for (int i = 0; i < b->nlayouts; i++)
        if (b->layouts[i]->arch >= 0 && &b->layouts[i]->lay == owner) { lname = b->layouts[i]->name; arch = b->layouts[i]->arch; }
    if (!lname) return NULL;
    char key[200];
    snprintf(key, sizeof key, "%s_%s", lname, tag);
    for (int i = 0; i < b->nanims; i++)
        if (!strcmp(b->anims[i]->name, key)) return b->anims[i]->anim.buf ? &b->anims[i]->anim : NULL;
    BankAnim *ba = calloc(1, sizeof *ba);
    if (!ba) return NULL;
    snprintf(ba->name, sizeof ba->name, "%s", key);
    char file[260];
    snprintf(file, sizeof file, "anim/%s.bflan", key);
    for (int k = 0; k < b->narch && !ba->anim.buf; k++) {
        int i = (arch + k) % b->narch;
        const LytFile *f = lyt_archive_find(&b->arch[i], file);
        if (f) lyt_anim_open(&ba->anim, f->data, f->size);
    }
    BankAnim **na = realloc(b->anims, (b->nanims + 1) * sizeof *na);
    if (!na) { lyt_anim_free(&ba->anim); free(ba); return NULL; }
    b->anims = na;
    b->anims[b->nanims++] = ba;
    return ba->anim.buf ? &ba->anim : NULL;
}

const LytTex *lytbank_tex(const LytBank *b, const char *name) {
    for (int i = 0; i < b->narch; i++) {
        const LytTex *t = lyt_texset_find(&b->tex[i], name);
        if (t) return t;
    }
    return NULL;
}

int lytbank_ntex(const LytBank *b) {
    int n = 0;
    for (int i = 0; i < b->narch; i++) n += (int)b->tex[i].ntex;
    return n;
}

const LytTex *lytbank_tex_at(const LytBank *b, int idx) {
    for (int i = 0; i < b->narch; i++) {
        if (idx < (int)b->tex[i].ntex) return &b->tex[i].tex[idx];
        idx -= (int)b->tex[i].ntex;
    }
    return NULL;
}

// ---- instances ------------------------------------------------------------------------------------------------

typedef struct {
    uint16_t mask;                  // FLPA targets 0..9 set
    float v[10];
    int has_vis; float vis;
    int has_alpha; float alpha;
} Pose;

typedef struct { const LytAnim *a; float frame; char tag[48]; } Play;

struct LytInst {
    LytBank *bank;
    const LytLayout *lay;
    LytInst **sub;                  // per pane, part instances
    Play play[MAX_PLAY];
    int nplay;
    char **text;                    // per pane
    uint8_t *vis_ov;               // per pane: 0 none, 1 hide, 2 show
    uint8_t (*col)[4];             // per pane colour override (a != 0: set)
    int16_t *aov;                  // per pane alpha override (-1: none)
    float (*off)[2];               // per pane position offset (parent's units, y up)
    Pose *pose;                     // per pane, scratch of the scene builder
    float alpha;
};

static LytInst *inst_new(LytBank *b, const char *layout, int depth) {
    const LytLayout *l = lytbank_layout(b, layout);
    if (!l) return NULL;
    LytInst *in = calloc(1, sizeof *in);
    if (!in) return NULL;
    in->bank = b; in->lay = l; in->alpha = 1;
    in->sub = calloc(l->npanes, sizeof *in->sub);
    in->text = calloc(l->npanes, sizeof *in->text);
    in->vis_ov = calloc(l->npanes, 1);
    in->col = calloc(l->npanes, sizeof *in->col);
    in->aov = malloc(l->npanes * sizeof *in->aov);
    if (in->aov) for (uint32_t i = 0; i < l->npanes; i++) in->aov[i] = -1;
    in->off = calloc(l->npanes, sizeof *in->off);
    in->pose = calloc(l->npanes, sizeof *in->pose);
    if (!in->sub || !in->text || !in->vis_ov || !in->col || !in->aov || !in->off || !in->pose) { lytinst_free(in); return NULL; }
    if (depth < MAX_DEPTH)
        for (uint32_t i = 0; i < l->npanes; i++)
            if (l->panes[i].kind == LYT_PRT && l->panes[i].part[0]) in->sub[i] = inst_new(b, l->panes[i].part, depth + 1);
    return in;
}

LytInst *lytinst_new(LytBank *b, const char *layout) { return inst_new(b, layout, 0); }

void lytinst_free(LytInst *in) {
    if (!in) return;
    for (uint32_t i = 0; i < in->lay->npanes; i++) {
        if (in->sub) lytinst_free(in->sub[i]);
        if (in->text) free(in->text[i]);
    }
    free(in->sub); free(in->text); free(in->vis_ov); free(in->col); free(in->aov); free(in->off); free(in->pose); free(in);
}

const LytLayout *lytinst_layout(const LytInst *in) { return in ? in->lay : NULL; }

LytInst *lytinst_part(LytInst *in, const char *path) {
    if (!in) return NULL;
    char buf[256];
    snprintf(buf, sizeof buf, "%s", path);
    for (char *tok = strtok(buf, "/"); tok && in; tok = strtok(NULL, "/")) {
        int i = lyt_layout_find_pane(in->lay, tok);
        in = i >= 0 ? in->sub[i] : NULL;
    }
    return in;
}

static void drop_play(LytInst *in, const char *tag) {
    for (int i = 0; i < in->nplay; i++)
        if (!strcmp(in->play[i].tag, tag)) {
            memmove(&in->play[i], &in->play[i + 1], (size_t)(in->nplay - i - 1) * sizeof in->play[0]);
            in->nplay--;
            return;
        }
}

int lytinst_set_anim(LytInst *in, const char *tag, float frame) {
    if (!in) return 0;
    const LytAnim *a = lytbank_anim(in->bank, in->lay, tag);
    if (!a) return 0;
    drop_play(in, tag);
    if (in->nplay == MAX_PLAY) { memmove(&in->play[0], &in->play[1], (MAX_PLAY - 1) * sizeof in->play[0]); in->nplay--; }
    Play *p = &in->play[in->nplay++];
    p->a = a; p->frame = frame;
    snprintf(p->tag, sizeof p->tag, "%s", tag);
    return 1;
}

void lytinst_clear_anims(LytInst *in) { if (in) in->nplay = 0; }

float lytinst_anim_frames(LytInst *in, const char *tag) {
    if (!in) return 0;
    const LytAnim *a = lytbank_anim(in->bank, in->lay, tag);
    return a ? (float)a->frames : 0;
}

void lytinst_default_state(LytInst *in) {
    if (!in) return;
    static const struct { const char *tag; float frame; } st[] = {{"UnFocusKey", -1}, {"UnFocusTouch", -1}, {"Alpha", 10}, {"Wait", -1}};
    for (unsigned i = 0; i < sizeof st / sizeof *st; i++) {
        float f = st[i].frame < 0 ? lytinst_anim_frames(in, st[i].tag) : st[i].frame;
        lytinst_set_anim(in, st[i].tag, f);
    }
    for (uint32_t i = 0; i < in->lay->npanes; i++)
        if (in->sub[i]) lytinst_default_state(in->sub[i]);
}

void lytinst_set_text(LytInst *in, const char *pane, const char *utf8) {
    if (!in) return;
    int i = lyt_layout_find_pane(in->lay, pane);
    if (i < 0) return;
    free(in->text[i]);
    in->text[i] = utf8 ? strdup(utf8) : NULL;
}

void lytinst_set_visible(LytInst *in, const char *pane, int visible) {
    if (!in) return;
    int i = lyt_layout_find_pane(in->lay, pane);
    if (i >= 0) in->vis_ov[i] = visible ? 2 : 1;
}

void lytinst_set_color(LytInst *in, const char *pane, uint8_t r, uint8_t g, uint8_t b) {
    if (!in) return;
    int i = lyt_layout_find_pane(in->lay, pane);
    if (i < 0) return;
    in->col[i][0] = r; in->col[i][1] = g; in->col[i][2] = b; in->col[i][3] = 255;
}

void lytinst_set_pane_alpha(LytInst *in, const char *pane, int a) {
    if (!in) return;
    int i = lyt_layout_find_pane(in->lay, pane);
    if (i >= 0) in->aov[i] = (int16_t)a;
}

void lytinst_set_offset(LytInst *in, const char *pane, float dx, float dy) {
    if (!in) return;
    int i = lyt_layout_find_pane(in->lay, pane);
    if (i >= 0) { in->off[i][0] = dx; in->off[i][1] = dy; }
}

void lytinst_set_alpha(LytInst *in, float alpha) { if (in) in->alpha = alpha; }

// ---- scene ----------------------------------------------------------------------------------------------------

typedef struct { float a, b, c, d, e, f; } Mat;   // x' = a x + c y + e, y' = b x + d y + f

static Mat mat_mul(Mat p, Mat q) {   // p after q
    Mat r = {p.a * q.a + p.c * q.b, p.b * q.a + p.d * q.b, p.a * q.c + p.c * q.d, p.b * q.c + p.d * q.d,
             p.a * q.e + p.c * q.f + p.e, p.b * q.e + p.d * q.f + p.f};
    return r;
}
static void mat_apply(Mat m, float x, float y, float *ox, float *oy) { *ox = m.a * x + m.c * y + m.e; *oy = m.b * x + m.d * y + m.f; }

typedef struct {
    LytScene *sc;
    LytInst *target_inst;
    int target_pane, found;
    float bounds[4];
} Walk;

static LytItem *scene_add(LytScene *sc) {
    if (sc->n == sc->cap) {
        int nc = sc->cap ? sc->cap * 2 : 256;
        LytItem *ni = realloc(sc->items, (size_t)nc * sizeof *ni);
        if (!ni) return NULL;
        sc->items = ni; sc->cap = nc;
    }
    LytItem *it = &sc->items[sc->n++];
    memset(it, 0, sizeof *it);
    return it;
}

static void compute_pose(LytInst *in) {
    const LytLayout *l = in->lay;
    memset(in->pose, 0, l->npanes * sizeof *in->pose);
    for (int k = 0; k < in->nplay; k++) {
        const LytAnim *a = in->play[k].a;
        float t = in->play[k].frame;
        for (uint32_t i = 0; i < a->nentries; i++) {
            const LytAnimEntry *e = &a->entries[i];
            if (e->kind != 0 || e->nkeys == 0) continue;
            int pi = lyt_layout_find_pane(l, e->pane);
            if (pi < 0) continue;
            Pose *p = &in->pose[pi];
            float v = lyt_curve_eval((const float (*)[3])e->keys, e->nkeys, e->curve, t);
            if (e->tag == LYT_TAG_FLPA && e->target < 10) { p->mask |= 1u << e->target; p->v[e->target] = v; }
            else if (e->tag == LYT_TAG_FLVI && e->target == 0) { p->has_vis = 1; p->vis = v; }
            else if (e->tag == LYT_TAG_FLVC && e->target == 0x10) { p->has_alpha = 1; p->alpha = v; }
        }
    }
}

static float anchor_x(int o, float w) { return o == 1 ? -w / 2 : o == 2 ? w / 2 : 0; }   // point of a rectangle, centre-based, y up
static float anchor_y(int o, float h) { return o == 1 ? h / 2 : o == 2 ? -h / 2 : 0; }

static void walk(Walk *w, LytInst *in, int idx, Mat pm, float pw, float ph, float alpha, float mx, float my, int depth) {
    const LytLayout *l = in->lay;
    const LytPane *p = &l->panes[idx];
    const Pose *po = &in->pose[idx];
    int vis = p->flags & 1;
    if (in->vis_ov[idx]) vis = in->vis_ov[idx] == 2;
    if (po->has_vis) vis = po->vis != 0;
    if (!vis) return;
    float t[3] = {p->t[0], p->t[1], p->t[2]}, r[3] = {p->r[0], p->r[1], p->r[2]}, s[2] = {p->s[0], p->s[1]}, sz[2] = {p->size[0], p->size[1]};
    float al = in->aov[idx] >= 0 ? (float)in->aov[idx] : p->alpha;
    for (int k = 0; k < 10; k++) {
        if (!(po->mask & (1u << k))) continue;
        if (k < 3) t[k] = po->v[k];
        else if (k < 6) r[k - 3] = po->v[k];
        else if (k < 8) s[k - 6] = po->v[k];
        else sz[k - 8] = po->v[k];
    }
    if (po->has_alpha) al = po->alpha;
    if (p->mag & 1) { t[0] *= mx; t[1] *= my; }
    t[0] += in->off[idx][0]; t[1] += in->off[idx][1];
    if (p->mag & 4) {
        float kx = mx, ky = my;
        if (p->kind == LYT_PIC && p->mat < l->nmats && l->mats[p->mat].ntex > 0 && l->mats[p->mat].tex[0].idx < l->ntex
            && strncmp(l->tex[l->mats[p->mat].tex[0].idx], "White", 5))   // icons keep their proportions when the part is not square
            kx = ky = fminf(mx, my);
        sz[0] *= kx; sz[1] *= ky;
    }
    if (p->mag & 2) { s[0] *= mx; s[1] *= my; }   // bit 1: the pane's scale follows the part magnification (BgMask, cursor)
    float a = alpha * al / 255.0f;
    int ox = p->base & 3, oy = (p->base >> 2) & 3, qx = (p->base >> 4) & 3, qy = (p->base >> 6) & 3;
    float px = anchor_x(qx, pw) + t[0], py = anchor_y(qy, ph) + t[1];
    float rad = r[2] * 0.01745329252f, cs = cosf(rad), sn = sinf(rad);
    Mat place = {1, 0, 0, 1, px, py};
    Mat rot = {cs, sn, -sn, cs, 0, 0};
    Mat scl = {s[0], 0, 0, s[1], 0, 0};
    Mat shift = {1, 0, 0, 1, -anchor_x(ox, sz[0]), -anchor_y(oy, sz[1])};   // from the origin point to the rectangle centre
    Mat m = mat_mul(pm, mat_mul(place, mat_mul(rot, mat_mul(scl, shift))));
    float hw = sz[0] / 2, hh = sz[1] / 2;
    float cx[4] = {-hw, hw, -hw, hw}, cy[4] = {hh, hh, -hh, -hh};
    float X[4], Y[4];
    for (int k = 0; k < 4; k++) mat_apply(m, cx[k], cy[k], &X[k], &Y[k]);
    if (in == w->target_inst && idx == w->target_pane) {
        w->found = 1;
        w->bounds[0] = fminf(fminf(X[0], X[1]), fminf(X[2], X[3])); w->bounds[2] = fmaxf(fmaxf(X[0], X[1]), fmaxf(X[2], X[3]));
        w->bounds[1] = fminf(fminf(Y[0], Y[1]), fminf(Y[2], Y[3])); w->bounds[3] = fmaxf(fmaxf(Y[0], Y[1]), fmaxf(Y[2], Y[3]));
    }
    if (w->sc && (p->kind == LYT_PIC || (p->kind == LYT_TXT && in->text[idx]))) {
        LytItem *it = scene_add(w->sc);
        if (it) {
            memcpy(it->x, X, sizeof X); memcpy(it->y, Y, sizeof Y);
            it->alpha = a;
            it->pane = p->name;
            if (p->kind == LYT_PIC) {
                it->type = LYT_ITEM_QUAD;
                const LytMaterial *mt = p->mat < l->nmats ? &l->mats[p->mat] : NULL;
                static const float dflt[8] = {0, 0, 1, 0, 0, 1, 1, 1};
                const float *tc = p->ntc ? p->tc[0] : dflt;
                memcpy(it->uv, tc, sizeof it->uv);
                if (mt && mt->ntex > 0 && mt->tex[0].idx < l->ntex) it->tex = lytbank_tex(in->bank, l->tex[mt->tex[0].idx]);
                for (int k = 0; k < 4; k++)
                    for (int c = 0; c < 4; c++) it->col[k][c] = (uint8_t)((p->vcol[k][c] * (mt ? mt->white[c] : 255) + 127) / 255);
                if (in->col[idx][3])   // colour override replaces the material colour (the corner colours still shade it)
                    for (int k = 0; k < 4; k++)
                        for (int c = 0; c < 3; c++) it->col[k][c] = (uint8_t)((p->vcol[k][c] * in->col[idx][c] + 127) / 255);
            } else {
                it->type = LYT_ITEM_TEXT;
                it->str = in->text[idx];
                float fx = 1, fy = 1;   // the glyph size is authored for the part as placed; only the parents' own scale counts
                it->font_size[0] = p->font_size[0] * fx * hypotf(m.a, m.b);   // and the accumulated scale of the parents
                it->font_size[1] = p->font_size[1] * fy * hypotf(m.c, m.d);
                it->char_space = p->char_space; it->line_space = p->line_space;
                memcpy(it->top_color, p->top_color, 4); memcpy(it->bottom_color, p->bottom_color, 4);
                if (in->col[idx][3])
                    for (int c = 0; c < 3; c++) it->top_color[c] = it->bottom_color[c] = in->col[idx][c];
                it->origin = p->halign; it->align = p->valign;
                it->rot = atan2f(-m.b, m.a);
            }
        }
    }
    if (p->kind == LYT_PRT && in->sub[idx] && depth < MAX_DEPTH) {
        LytInst *sub = in->sub[idx];
        float psx = sub->lay->parts_size[0], psy = sub->lay->parts_size[1];
        float m2x = psx ? sz[0] / psx : 1, m2y = psy ? sz[1] / psy : 1;
        compute_pose(sub);
        const LytPane *root = &sub->lay->panes[0];
        for (int c = root->first_child; c >= 0; c = sub->lay->panes[c].next_sibling)
            walk(w, sub, c, m, sz[0], sz[1], a * sub->alpha, m2x, m2y, depth + 1);
    }
    for (int c = p->first_child; c >= 0; c = l->panes[c].next_sibling)
        walk(w, in, c, m, sz[0], sz[1], a, mx, my, depth);
}

static void walk_root(Walk *w, LytInst *root, float ox, float oy, float scale) {
    const LytLayout *l = root->lay;
    compute_pose(root);
    Mat m0 = {scale, 0, 0, -scale, l->size_xy[0] / 2 + ox, l->size_xy[1] / 2 + oy};   // y up -> screen, zoom around the canvas centre
    for (int c = l->panes[0].first_child; c >= 0; c = l->panes[c].next_sibling)
        walk(w, root, c, m0, l->size_xy[0], l->size_xy[1], root->alpha, 1, 1, 0);
}

void lyt_scene_build(LytScene *sc, LytInst *root, float ox, float oy, float scale) {
    sc->n = 0;
    lyt_scene_append(sc, root, ox, oy, scale);
}

void lyt_scene_append(LytScene *sc, LytInst *root, float ox, float oy, float scale) {
    Walk w = {.sc = sc, .target_pane = -1};
    walk_root(&w, root, ox, oy, scale);
}

void lyt_scene_free(LytScene *sc) {
    free(sc->items);
    memset(sc, 0, sizeof *sc);
}

int lyt_pane_bounds(LytInst *root, LytInst *inst, const char *pane, float ox, float oy, float scale, float out[4]) {
    int i = lyt_layout_find_pane(inst->lay, pane);
    if (i < 0) return 0;
    Walk w = {.sc = NULL, .target_inst = inst, .target_pane = i};
    walk_root(&w, root, ox, oy, scale);
    if (w.found) memcpy(out, w.bounds, sizeof w.bounds);
    return w.found;
}
