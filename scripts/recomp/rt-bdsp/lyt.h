// Readers for the Nintendo layout formats the on-screen keyboard is drawn from: Yaz0, SARC, BFLYT (layouts),
// BFLAN (animations) and BNTX (textures). The files come from the user's own firmware at run time
// (BDSP_FIRMWARE_DATA); nothing from them is stored in this repository. Self-contained, no dependency on the runtime.
#ifndef LYT_H
#define LYT_H

#include <stddef.h>
#include <stdint.h>

// ---- Yaz0 + SARC ----------------------------------------------------------------------------------------------

// Decompresses a Yaz0 stream. Returns a malloc'd buffer (free it) or NULL on malformed input.
uint8_t *lyt_yaz0(const uint8_t *src, size_t size, size_t *out_size);

typedef struct {
    const char *name;        // points into the archive buffer
    const uint8_t *data;
    size_t size;
} LytFile;

typedef struct {
    uint8_t *buf;            // decompressed SARC image, owned
    size_t size;
    LytFile *files;
    uint32_t nfiles;
} LytArchive;

// Opens a .szs (Yaz0-compressed) or plain SARC image already in memory; takes a copy.
int lyt_archive_open(LytArchive *a, const uint8_t *src, size_t size);
int lyt_archive_load(LytArchive *a, const char *path);
const LytFile *lyt_archive_find(const LytArchive *a, const char *name);
void lyt_archive_free(LytArchive *a);

// ---- BFLYT ----------------------------------------------------------------------------------------------------

enum { LYT_PAN, LYT_PIC, LYT_TXT, LYT_PRT, LYT_BND, LYT_WND };

typedef struct {
    char name[25];
    uint8_t usage;           // usage flags byte
    uint32_t off[3];         // raw words at +28/+32/+36 of the property record (offset of overridden data), not decoded yet
} LytPartProp;

typedef struct {
    int kind;
    uint8_t flags;           // bit0 visible, bit1 alpha inherited from parent, bit2 position adjust
    uint8_t base;            // bits 0-1 x, 2-3 y, 4-5 / 6-7 parent origin: 0 centre, 1 left/top, 2 right/bottom
    uint8_t alpha;
    uint8_t mag;             // flag byte 3 (bit0 scales position of a part, bit2 its size)
    char name[25];
    float t[3], r[3], s[2], size[2];
    int parent, first_child, next_sibling;   // pane indices or -1
    const uint8_t *raw;      // pane body (starts at the flags byte), into the file buffer
    uint32_t raw_size;
    // pic1
    uint8_t vcol[4][4];      // corner colours RGBA
    uint16_t mat;            // pic1, txt1, wnd1 (first material)
    uint8_t ntc;
    float tc[4][8];          // texture coordinates, 4 per set
    // txt1
    uint16_t text_bytes, text_len, font;
    uint8_t halign, valign, text_flags;
    float italic;
    uint32_t text_off;       // offset of the default text from the start of the pane section (header included)
    uint8_t top_color[4], bottom_color[4];
    float font_size[2], char_space, line_space;
    // prt1
    uint32_t nprop;
    float pscale[2];
    char part[65];           // name of the part layout
    LytPartProp *props;
} LytPane;

typedef struct {
    char name[29];
    uint32_t flags;
    uint8_t black[4], white[4];
    int ntex;
    struct { uint16_t idx; uint8_t wrap_s, wrap_t; } tex[3];
    int nmtx;
    float srt[3][5];         // translate xy, rotate, scale xy
    int ngen;
} LytMaterial;

typedef struct {
    char name[35];
    uint32_t npanes;
    char (*panes)[25];       // pane names
} LytGroup;

typedef struct {
    uint8_t *buf;            // file image, owned
    size_t size;
    uint32_t version;        // as in the header, major in the high byte
    uint8_t origin;
    float size_xy[2], parts_size[2];
    uint32_t ntex, nfonts, nmats, npanes, ngroups;
    char (*tex)[65];
    char (*fonts)[65];
    LytMaterial *mats;
    LytPane *panes;          // in file order; panes[0] is the root
    LytGroup *groups;
} LytLayout;

int lyt_layout_open(LytLayout *l, const uint8_t *src, size_t size);   // takes a copy
void lyt_layout_free(LytLayout *l);
const char *lyt_pane_kind_name(int kind);
int lyt_layout_find_pane(const LytLayout *l, const char *name);

// ---- BFLAN ----------------------------------------------------------------------------------------------------

enum { LYT_TAG_FLPA, LYT_TAG_FLVI, LYT_TAG_FLVC, LYT_NTAGS };

typedef struct {
    char pane[29];
    uint8_t kind;            // 0 pane, 1 material
    uint8_t tag;             // LYT_TAG_*
    uint8_t id, target;
    uint16_t curve;          // 1 step, 2 hermite
    uint16_t nkeys;
    float (*keys)[3];        // frame, value, slope (step keys: slope 0)
} LytAnimEntry;

typedef struct {
    char name[65];
    int16_t start, end;      // signed: "In" animations start before frame 0
    uint16_t frames;
    uint32_t nentries, nskipped;   // entries read / tags of other kinds not decoded yet
    LytAnimEntry *entries;
    uint32_t ngroups;
    char (*groups)[29];
    uint8_t *buf;
} LytAnim;

int lyt_anim_open(LytAnim *a, const uint8_t *src, size_t size);       // takes a copy
void lyt_anim_free(LytAnim *a);
// Value of one animated field at frame t. Returns 0 and leaves *v untouched when the animation does not drive it.
int lyt_anim_eval(const LytAnim *a, const char *pane, int tag, int target, float t, float *v);
float lyt_curve_eval(const float (*keys)[3], int nkeys, int curve, float t);

// ---- BNTX -----------------------------------------------------------------------------------------------------

typedef struct {
    char name[65];
    uint32_t fmt;            // BRTI format word: high byte 0x1a/0x1d BC4, 0x1e BC5, 0x2d ASTC 4x4 (see lyt_tex_*)
    uint32_t w, h;
    uint32_t chan;           // channel mapping, bytes R,G,B,A: 0 zero, 1 one, 2 R, 3 G, 4 B, 5 A of the decoded data
    uint32_t block_bytes;    // 8 or 16
    uint32_t bw, bh;         // blocks per row / column
    uint8_t *blocks;         // deswizzled linear block data (bw*bh*block_bytes), owned; NULL for unknown formats
} LytTex;

typedef struct {
    uint8_t *buf;
    LytTex *tex;
    uint32_t ntex;
} LytTexSet;

int lyt_texset_open(LytTexSet *t, const uint8_t *src, size_t size);   // takes a copy
void lyt_texset_free(LytTexSet *t);
const LytTex *lyt_texset_find(const LytTexSet *t, const char *name);
int lyt_tex_is_astc(const LytTex *t);
// Decodes BC4 (grey) / BC5 (R, G) to RGBA8 like the file stores them (no channel mapping). out = w*h*4 bytes. Returns 0 for other formats.
int lyt_tex_decode_raw(const LytTex *t, uint8_t *out);
// Same, then applies the channel mapping from the texture header.
int lyt_tex_decode(const LytTex *t, uint8_t *out);

#endif
