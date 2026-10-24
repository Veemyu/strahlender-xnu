// On-screen software keyboard: state, key logic, input and scene (see swkbd_ui.h). Own code.
// The layouts are the user's firmware files (BDSP_FIRMWARE_DATA); the key characters below are our own table.
#include "swkbd_ui.h"
#include "swkbd_snd.h"

#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void trace(const char *what, const char *arg) { if (getenv("BDSP_TRACE_APPLET")) fprintf(stderr, "[swkbd_ui] %s %s\n", what, arg ? arg : ""); }

enum { K_CHAR, K_BS, K_ENTER, K_SHIFT, K_SYMBOL, K_BACK, K_SPACE, K_NONE, K_TAB };
enum { SCR_QWERTY, SCR_SIGN, SCR_NUMERIC, SCR_COUNT };
#define MAX_KEYS 80
#define FN_LABEL_EM 22.2f   // em size of the labels on the function keys (tabs, space, return); the layouts give each of them its own size, the console draws them alike

typedef struct {
    LytInst *inst;
    int kind;
    char name[25];
    char normal[8], shifted[8];
    float r[4];                      // left, top, right, bottom in canvas pixels
    int page;                        // K_TAB: the keyboard page it opens
    int hidden;                      // no character on this page
    char tag[24];                    // running animation
    float t;
} Key;

typedef struct {
    LytBank *bank;
    LytInst *area, *bg, *kt, *caret, *mask;
    Key keys[MAX_KEYS];
    int nkeys;
    int ok;
    int fallback;                    // no layout files: keys and plates are our own simple drawing
} Screen;

static const char *const k_archives[SCR_COUNT] = {"Qwerty", "Sign", "Numeric"};
static const char *const k_keytop[SCR_COUNT] = {"SwkbdBaseKeytopQwerty", "SwkbdBaseKeytopSign", "SwkbdBaseKeytopNumeric"};

// Key characters: 4 rows of 11 from the top left, normal and with Shift, per layout (the standard national keyboard layouts as the
// Switch's keyboard has them). BDSP_SWKBD_LAYOUT selects one; default "us".
static const struct { const char *id, *normal, *shifted; } k_layouts[] = {
    {"us", "1234567890-qwertyuiop/asdfghjkl:'zxcvbnm,.?!", "#[]$%^&*()_QWERTYUIOP@ASDFGHJKL;\"ZXCVBNM<>+="},
    {"uk", "1234567890-qwertyuiop/asdfghjkl:'zxcvbnm,.?!", "#\xC2\xA3""\xE2\x82\xAC""$%^&*()_QWERTYUIOP@ASDFGHJKL;\"ZXCVBNM<>+="},
    {"de", "1234567890\xC3\x9F""qwertzuiop\xC3\xBC""asdfghjkl\xC3\xB6""\xC3\xA4""yxcvbnm,.-+", "!\"@\xE2\x82\xAC""%&/()=?QWERTZUIOP\xC3\x9C""ASDFGHJKL\xC3\x96""\xC3\x84""YXCVBNM;:_*"},
    {"fr", "1234567890-azertyuiop'qsdfghjklm;wxcvbn,.!?:", "@%&#*^\xC2\xBA""+\xC3\xB7""=_AZERTYUIOP/QSDFGHJKLM\xE2\x82\xAC""WXCVBN()\xC2\xAB""\xC2\xBB""\""},
    {"es", "1234567890@qwertyuiop\"asdfghjkl\xC3\xB1""\\zxcvbnm,.-*", "\xC2\xA1""!\xC2\xBF""?()$\xC2\xBA""\xC2\xAA""=#QWERTYUIOP%ASDFGHJKL\xC3\x91""/ZXCVBNM;:_&"},
    {"it", "1234567890'qwertyuiop\xC2\xB0""asdfghjkl@#zxcvbnm,.[]", "!\"\xC2\xA3""$%&/()=?QWERTYUIOP*ASDFGHJKL\xE2\x82\xAC""_ZXCVBNM;:+-"},
    {"pt", "1234567890=qwertyuiop\xC2\xBA""asdfghjkl\xC3\xA7""\xC2\xAA""zxcvbnm,.-+", "!\"#\xE2\x82\xAC""%&()?[]QWERTYUIOP@ASDFGHJKL\xC3\x87""*ZXCVBNM;:_\xC2\xA3"""},
    {"ru", "1234567890\xD1\x8A""\xD0\xB9""\xD1\x86""\xD1\x83""\xD0\xBA""\xD0\xB5""\xD0\xBD""\xD0\xB3""\xD1\x88""\xD1\x89""\xD0\xB7""\xD1\x85""\xD1\x84""\xD1\x8B""\xD0\xB2""\xD0\xB0""\xD0\xBF""\xD1\x80""\xD0\xBE""\xD0\xBB""\xD0\xB4""\xD0\xB6""\xD1\x8D""\xD1\x8F""\xD1\x87""\xD1\x81""\xD0\xBC""\xD0\xB8""\xD1\x82""\xD1\x8C""\xD0\xB1""\xD1\x8E""\xD1\x91"".", "!?\":;()-_@\xD0\xAA""\xD0\x99""\xD0\xA6""\xD0\xA3""\xD0\x9A""\xD0\x95""\xD0\x9D""\xD0\x93""\xD0\xA8""\xD0\xA9""\xD0\x97""\xD0\xA5""\xD0\xA4""\xD0\xAB""\xD0\x92""\xD0\x90""\xD0\x9F""\xD0\xA0""\xD0\x9E""\xD0\x9B""\xD0\x94""\xD0\x96""\xD0\xAD""\xD0\xAF""\xD0\xA7""\xD0\xA1""\xD0\x9C""\xD0\x98""\xD0\xA2""\xD0\xAC""\xD0\x91""\xD0\xAE""\xD0\x81"","},
};
// Symbol keyboard: rows of 11 from the top left; \1 = no key (hidden)
static const char *const k_sign = "1234567890-" "!@#$%^&*()_" "~`=\\+{}|[]\1" "<>;:\"',.?/\1" "\1\1\1\1\1\1\1\1\1\1\1";
static const char *const k_numeric = "1234567890";
// Accent pages (tabs "ÀÁÂ" and "ÑŃŅ"): lower case, and upper case with Shift
static const char *const k_acc_lo[2] = {"àáâãäåæāăąçćċčðďǆǳèéêëēęěğġģħìíîïīįıĳķĺļľł", "ñńņňòóôõöøœőōŕřšßśşþťțùúûüūůűųýÿźżž"};
static const char *const k_acc_up[2] = {"ÀÁÂÃÄÅÆĀĂĄÇĆĊČÐĎǅǲÈÉÊËĒĘĚĞĠĢĦÌÍÎÏĪĮİĲĶĹĻĽŁ", "ÑŃŅŇÒÓÔÕÖØŒŐŌŔŘŠßŚŞÞŤȚÙÚÛÜŪŮŰŲÝŸŹŻŽ"};
static const char *const k_tab_label[4] = {"ABC", "#+=", "ÀÁÂ", "ÑŃŅ"};

static struct {
    pthread_mutex_t lock;
    int inited, active, screen_built, display;
    char root[1024];
    Screen scr[SCR_COUNT];
    SwkbdParams p;
    SwkbdCallbacks cb;
    void *user;
    char text[1024];
    int caret;                       // byte offset
    int cur;                         // current screen
    int shift;                       // 0 off, 1 once, 2 caps
    int focus;
    int touch_mode;                  // last input was touch
    int busy;
    int closing;                     // the closing animation is playing (the keyboard no longer takes input)
    double close_t;                  // seconds since the close started
    double cnt_err;                  // frames since the counter's error shake started (>= 9: none)
    char msg[256];
    double msg_left;
    double fade, clock;
    uint64_t pad_prev;
    int stick_prev[4];               // left, right, up, down as digital
    double repeat_at;
    int repeat_dir;                  // 0 none, else button bit
    float scale, off[2];
    int tw, th;
    float (*measure)(const char *, float);
    LytScene scene;
    char ok_label[64], space_label[64];
    float field[4];                  // text field, canvas pixels (left, top, right, bottom)
    int page;                        // 0 letters, 1 symbols, 2 and 3 accents
    int li;                          // index in k_layouts
    struct { char name[56], text[96]; } labels[48];
    int nlabels;
    char lang[16];
} G;

// Recursive: the backend's callbacks may call swkbd_ui_resolve from inside submit
static pthread_once_t g_once = PTHREAD_ONCE_INIT;
static void lock_init(void) {
    pthread_mutexattr_t a;
    pthread_mutexattr_init(&a);
    pthread_mutexattr_settype(&a, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&G.lock, &a);
}
static void LOCK(void) { pthread_once(&g_once, lock_init); pthread_mutex_lock(&G.lock); }

// ---- utf-8 helpers
static int u8_len(unsigned char c) { return c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1; }
static int u8_count(const char *s) { int n = 0; for (; *s; s += u8_len((unsigned char)*s)) n++; return n; }
static void u8_nth(const char *s, int idx, char out[8]) {
    out[0] = 0;
    for (; *s; s += u8_len((unsigned char)*s), idx--)
        if (!idx) { int l = u8_len((unsigned char)*s); memcpy(out, s, l); out[l] = 0; return; }
}

// ---- messages (MSBT labels of the firmware, optional)
static const char *lbl(const char *name, const char *dflt) {
    for (int i = 0; i < G.nlabels; i++) if (!strcmp(G.labels[i].name, name)) return G.labels[i].text;
    return dflt;
}

static void load_labels(void) {
    const char *lang = G.lang;
    static const char *const dirs[] = {"%s/swkbd/romfs/message/%s/swkbd.msbt.szs", "%s/swkbd/message/%s/swkbd.msbt.szs"};
    for (unsigned di = 0; di < 2; di++) {
        char path[1100];
        snprintf(path, sizeof path, dirs[di], G.root, lang ? lang : "USen");
        FILE *f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
        uint8_t *b = malloc((size_t)n);
        size_t got = b ? fread(b, 1, (size_t)n, f) : 0;
        fclose(f);
        size_t sz = 0;
        uint8_t *d = got == (size_t)n ? lyt_yaz0(b, (size_t)n, &sz) : NULL;
        free(b);
        if (!d) continue;
        if (sz > 0x20 && !memcmp(d, "MsgStdBn", 8) && d[8] == 0xFF) {
            uint16_t nsec; memcpy(&nsec, d + 0xE, 2);
            const uint8_t *lbl = NULL, *txt = NULL; size_t lsz = 0, tsz = 0;
            size_t o = 0x20;
            for (unsigned s = 0; s < nsec && o + 16 <= sz; s++) {
                uint32_t ssz; memcpy(&ssz, d + o + 4, 4);
                if (!memcmp(d + o, "LBL1", 4)) { lbl = d + o + 16; lsz = ssz; }
                if (!memcmp(d + o, "TXT2", 4)) { txt = d + o + 16; tsz = ssz; }
                o = (o + 16 + ssz + 15) & ~(size_t)15;
            }
            if (lbl && txt && lsz > 4 && tsz > 4) {
                uint32_t ng; memcpy(&ng, lbl, 4);
                uint32_t nt; memcpy(&nt, txt, 4);
                for (uint32_t g = 0; g < ng && 4 + g * 8 + 8 <= lsz; g++) {
                    uint32_t cnt, off; memcpy(&cnt, lbl + 4 + g * 8, 4); memcpy(&off, lbl + 8 + g * 8, 4);
                    for (uint32_t q = off; cnt-- && q < lsz;) {
                        unsigned l = lbl[q];
                        char name[128] = {0};
                        memcpy(name, lbl + q + 1, l < 127 ? l : 127);
                        uint32_t idx; memcpy(&idx, lbl + q + 1 + l, 4);
                        q += 5 + l;
                        if (idx >= nt || G.nlabels >= 48 || strncmp(name, "Swkbd", 5)) continue;
                        char *dst = G.labels[G.nlabels].text;
                        snprintf(G.labels[G.nlabels].name, sizeof G.labels[0].name, "%s", name);
                        G.nlabels++;
                        uint32_t so; memcpy(&so, txt + 4 + idx * 4, 4);
                        int w = 0;
                        for (size_t k = so; k + 1 < tsz && w < 90; k += 2) {   // UTF-16 -> utf-8 (BMP)
                            unsigned c = txt[k] | txt[k + 1] << 8;
                            if (!c) break;
                            if (c < 0x80) dst[w++] = (char)c;
                            else if (c < 0x800 && w < 58) { dst[w++] = (char)(0xC0 | c >> 6); dst[w++] = (char)(0x80 | (c & 0x3F)); }
                            else if (w < 57) { dst[w++] = (char)(0xE0 | c >> 12); dst[w++] = (char)(0x80 | ((c >> 6) & 0x3F)); dst[w++] = (char)(0x80 | (c & 0x3F)); }
                        }
                        dst[w] = 0;
                    }
                }
            }
        }
        free(d);
        break;
    }
    snprintf(G.ok_label, sizeof G.ok_label, "%s", lbl("SwkbdCommon_Enter_Confirm", "OK"));
    snprintf(G.space_label, sizeof G.space_label, "%s", lbl("SwkbdCommon_Space_Space", "Space"));
}

// ---- screens
static int cmp_keys(const void *a, const void *b) {
    const Key *x = a, *y = b;
    float yx = (x->r[1] + x->r[3]) / 2, yy = (y->r[1] + y->r[3]) / 2;
    if (fabsf(yx - yy) > 20) return yx < yy ? -1 : 1;
    float cx = x->r[0], cy = y->r[0];
    return cx < cy ? -1 : cx > cy ? 1 : 0;
}

// The layouts are white; the Switch's colour scheme is set by the program and is not in the layout files, so the two schemes below are ours,
// matched by eye to the original (light is the Switch's default; BDSP_SWKBD_THEME=dark selects the other).
typedef struct {
    uint8_t bg[3], plate[3], fn[3], dis[3], text[3], text_dis[3], icon[3], badge[3], focus[3], accent[3], accent_text[3], tab_on[3], cursor[3];
} Theme;
static const Theme k_theme_light = {{242, 242, 242}, {234, 234, 234}, {220, 220, 220}, {220, 220, 220}, {52, 52, 52}, {178, 178, 178}, {52, 52, 52},
                                    {52, 52, 52}, {255, 255, 255}, {77, 90, 234}, {255, 255, 255}, {80, 90, 231}, {110, 207, 204}};
static const Theme k_theme_dark = {{38, 41, 48}, {58, 62, 68}, {78, 82, 90}, {66, 70, 78}, {255, 255, 255}, {140, 144, 150}, {255, 255, 255},
                                   {190, 190, 190}, {0, 140, 180}, {0, 140, 180}, {255, 255, 255}, {0, 193, 242}, {0, 193, 242}};
static const Theme *g_theme = &k_theme_light;

#define COL(c) (c)[0], (c)[1], (c)[2]

static void style_key(LytInst *k, int plain) {
    const Theme *t = g_theme;
    const uint8_t *plate = plain ? t->plate : t->fn;
    static const char *const bases[] = {"P_BtnBase", "P_BtnBase_00", "P_BtnBase_01"};
    for (unsigned i = 0; i < 3; i++) { lytinst_set_color(k, bases[i], COL(plate)); lytinst_set_pane_alpha(k, bases[i], 255); }
    lytinst_set_color(k, "P_BtnFocus", COL(t->focus));
    lytinst_set_color(k, "P_BtnDecideKey", COL(t->cursor));
    lytinst_set_color(k, "P_BtnTouch", COL(t->cursor));
    static const char *const texts[] = {"T_00", "T_01", "T_02"};
    for (unsigned i = 0; i < 3; i++) lytinst_set_color(k, texts[i], COL(t->text));
    static const char *const badges[] = {"T_Key", "T_Key_00", "T_Key_01"};
    for (unsigned i = 0; i < 3; i++) lytinst_set_color(k, badges[i], COL(t->badge));
    static const char *const icons[] = {"P_00", "P_Image", "P_ShiftOn", "P_ShiftOff", "P_Key", "P_GlowOff"};
    for (unsigned i = 0; i < sizeof icons / sizeof *icons; i++) lytinst_set_color(k, icons[i], COL(t->icon));
    lytinst_set_color(k, "P_GlowOn", COL(t->accent));
    lytinst_set_color(k, "P_Active_00", COL(t->tab_on));
    lytinst_set_visible(k, "N_BtnFocusKey", 0);   // the focus frame is drawn by the keyboard itself (see swkbd_ui_scene)
}

static void apply_theme(Screen *s) {
    const Theme *t = g_theme;
    static const char *const bases[] = {"P_BaseD", "P_BaseU", "P_BaseF", "P_InlineMarginBtm", "P_BaseDMargin"};
    for (unsigned i = 0; i < sizeof bases / sizeof *bases; i++) lytinst_set_color(s->bg, bases[i], COL(t->bg));
    const LytLayout *kl = lytinst_layout(s->kt);
    for (uint32_t i = 0; i < kl->npanes; i++) {
        if (kl->panes[i].kind != LYT_PRT) continue;
        LytInst *k = lytinst_part(s->kt, kl->panes[i].name);
        if (k) style_key(k, !strncmp(kl->panes[i].name, "L_BtnNml", 8));
    }
    if (t == &k_theme_light) lytinst_set_color(s->caret, "P_Cursor", 90, 190, 230);   // the text caret is blue, the key frame turquoise
    else lytinst_set_color(s->caret, "P_Cursor", COL(t->cursor));
}

// Characters of a page: 4 rows of 11 in reading order over the ordinary keys; keys without a character are hidden
static void assign_chars(Screen *s, int page) {
    const char *nt, *st;
    if (page == 0) { nt = k_layouts[G.li].normal; st = k_layouts[G.li].shifted; }
    else if (page == 1) { nt = st = k_sign; }
    else { nt = k_acc_lo[page - 2]; st = k_acc_up[page - 2]; }
    int ci = 0;
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        if (k->kind != K_CHAR) continue;
        u8_nth(nt, ci, k->normal);
        u8_nth(st, ci, k->shifted);
        ci++;
        k->hidden = k->normal[0] == 1 || !k->normal[0];
        if (!k->shifted[0] || k->shifted[0] == 1) memcpy(k->shifted, k->normal, sizeof k->shifted);
        if (s->kt) lytinst_set_visible(s->kt, k->name, !k->hidden);
        lytinst_set_text(k->inst, "T_00", k->normal);
    }
}

static int build_screen(int si) {
    Screen *s = &G.scr[si];
    const char *names[3] = {k_archives[si], "Swkbd", "common"};
    s->bank = lytbank_open(G.root, names, 3);
    if (!s->bank) return -1;
    s->kt = lytinst_new(s->bank, k_keytop[si]);
    s->bg = lytinst_new(s->bank, "SwkbdBgKeytop");
    s->area = lytinst_new(s->bank, "SwkbdBaseTextAreaLine");
    s->caret = lytinst_new(s->bank, "SwkbdCaret");
    s->mask = lytinst_new(s->bank, "BgMask");       // dims the game picture (colour and alpha are in the file)
    if (!s->kt || !s->bg || !s->area || !s->caret || !s->mask) return -1;
    lytinst_default_state(s->kt); lytinst_default_state(s->bg); lytinst_default_state(s->area); lytinst_default_state(s->caret);
    lytinst_set_visible(s->area, "L_BgMask", 0);           // its own mask would dim the text area
    lytinst_set_visible(s->bg, "P_FShdwD", 0);             // the shadow under the key area would run through the footer row (the footer has its own line)
    lytinst_set_anim(s->area, "TextAreaType", 1);          // frame 1: the long single-line text field
    lytinst_set_anim(s->area, "TextAreaPos", 1);           // frame 1: the field as high as it stands over the full size keyboard (frame 0 and 3 are for the other keyboard heights)
    lytinst_set_offset(s->area, "T_Header", 0, -6.0f);         // header and typed text stand 6 / 5.5 px lower than the layout puts them (measured on the console)
    lytinst_set_offset(s->area, "T_TextBox_Long", 0, -5.5f);
    lytinst_set_visible(s->area, "T_TextBox_Long", 1);
    lytinst_set_visible(s->area, "N_UnFixed", 0);          // composition markers of the input methods we do not have
    apply_theme(s);
    const LytLayout *kl = lytinst_layout(s->kt);
    for (uint32_t i = 0; i < kl->npanes && s->nkeys < MAX_KEYS; i++) {
        const LytPane *p = &kl->panes[i];
        if (p->kind != LYT_PRT) continue;
        int kind = -1, page = 0;
        if (!strncmp(p->name, "L_BtnNml", 8)) kind = K_CHAR;
        else if (!strcmp(p->name, "L_BtnBS")) kind = K_BS;
        else if (!strncmp(p->name, "L_BtnEnter", 10)) kind = K_ENTER;
        else if (!strcmp(p->name, "L_BtnShift")) kind = K_SHIFT;
        else if (!strcmp(p->name, "L_BtnSpace_00")) kind = si == SCR_QWERTY ? -2 : K_SPACE;   // the letter keyboard uses the narrower one next to the tabs
        else if (!strcmp(p->name, "L_BtnSpace_01") && si == SCR_QWERTY) kind = K_SPACE;
        else if (!strncmp(p->name, "L_InputMode_0", 13) && p->name[13] >= '0' && p->name[13] <= '3' && si != SCR_NUMERIC) { kind = K_TAB; page = p->name[13] - '0'; }
        if (kind == -1 || kind == -2) {
            // not a key: hidden (symbol key and unused widths) or decoration (language globe, Return)
            if (!strcmp(p->name, "L_BtnSymbol") || kind == -2 || !strncmp(p->name, "L_BtnSpace", 10) || !strncmp(p->name, "L_InputMode", 11)) lytinst_set_visible(s->kt, p->name, 0);
            if (!strcmp(p->name, "L_BtnArray")) {   // the language key: a globe, no function here
                LytInst *g = lytinst_part(s->kt, p->name);
                lytinst_set_visible(g, "N_Image", 1); lytinst_set_visible(g, "N_Text", 0);
            }
            if (!strcmp(p->name, "L_BtnLineBreak")) {   // Return: only for several-line fields, shown disabled
                LytInst *g = lytinst_part(s->kt, p->name);
                lytinst_set_text(g, "T_00", lbl("SwkbdCommon_Enter_LineBreak", "Return"));
                lytinst_set_color(g, "T_00", COL(g_theme->text_dis));
                lytinst_set_font_size(g, "T_00", FN_LABEL_EM, FN_LABEL_EM * 1.5f);   // the layout gives the key 30 px, the console draws it like the other function keys
                lytinst_set_visible(g, "N_Key", 0);
            }
            continue;
        }
        LytInst *inst = lytinst_part(s->kt, p->name);
        if (!inst) continue;
        if (kind == K_TAB) lytinst_set_visible(s->kt, p->name, 1);
        if (kind == K_SPACE) lytinst_set_visible(s->kt, p->name, 1);
        Key *k = &s->keys[s->nkeys];
        memset(k, 0, sizeof *k);
        k->inst = inst; k->kind = kind; k->page = page;
        snprintf(k->name, sizeof k->name, "%s", p->name);
        if (!lyt_pane_bounds(s->kt, s->kt, p->name, 0, 0, 1, k->r)) continue;
        snprintf(k->tag, sizeof k->tag, "UnFocusKey");
        k->t = 1e9f;
        if (kind == K_BS) lytinst_set_text(inst, "T_Key", "");           // button badges: B, Y, +
        if (kind == K_SPACE) lytinst_set_text(inst, "T_Key", "");
        if (kind == K_ENTER) lytinst_set_text(inst, "T_Key_00", "");
        if (kind == K_ENTER) lytinst_set_offset(inst, "N_Key", 22, 38);   // badges sit 16 px from the right edge and 15 px from the top of their key, as on the console
        if (kind == K_BS) lytinst_set_offset(inst, "N_Key", 5, 8);
        if (kind == K_SPACE) { lytinst_set_font_size(inst, "T_00", FN_LABEL_EM, FN_LABEL_EM * 1.5f); lytinst_set_font_size(inst, "T_01", FN_LABEL_EM, FN_LABEL_EM * 1.5f); }   // the labels of the function keys are smaller than the layouts say
        if (kind == K_SPACE) { float kw = k->r[2] - k->r[0]; lytinst_set_offset(inst, "N_Key", kw / 2 - 16 - 34 * kw / 100, 4.4f); }
        if (kind == K_SHIFT) { lytinst_set_visible(inst, "P_GlowOff", 0); lytinst_set_visible(inst, "P_GlowOn", 0); }   // the caps lock dot is drawn by tick (a round one)
        s->nkeys++;
    }
    qsort(s->keys, s->nkeys, sizeof s->keys[0], cmp_keys);
    if (si == SCR_NUMERIC) {
        static const char *const nm[] = {"-", "."};
        for (int i = 0; i < s->nkeys; i++) {
            Key *k = &s->keys[i];
            if (k->kind != K_CHAR) continue;
            if (!strcmp(k->name, "L_BtnNmlL") || !strcmp(k->name, "L_BtnNmlR")) snprintf(k->normal, sizeof k->normal, "%s", nm[!strcmp(k->name, "L_BtnNmlR")]);
            else u8_nth(k_numeric, 0, k->normal);
            snprintf(k->shifted, sizeof k->shifted, "%s", k->normal);
            lytinst_set_text(k->inst, "T_00", k->normal);
        }
        int ci = 0;
        for (int i = 0; i < s->nkeys; i++) {
            Key *k = &s->keys[i];
            if (k->kind != K_CHAR || !strncmp(k->name, "L_BtnNmlL", 9) || !strncmp(k->name, "L_BtnNmlR", 9)) continue;
            u8_nth(k_numeric, ci++, k->normal);
            snprintf(k->shifted, sizeof k->shifted, "%s", k->normal);
            lytinst_set_text(k->inst, "T_00", k->normal);
        }
    } else {
        assign_chars(s, si == SCR_QWERTY ? 0 : 1);
    }
    s->ok = 1;
    return 0;
}

static int fb_build_screen(int si);

static int ensure_built(void) {
    if (G.inited) return G.screen_built ? 0 : -1;
    G.inited = 1;
    snprintf(G.ok_label, sizeof G.ok_label, "OK");
    snprintf(G.space_label, sizeof G.space_label, "Space");
    const char *th = getenv("BDSP_SWKBD_THEME");
    g_theme = th && !strcmp(th, "dark") ? &k_theme_dark : &k_theme_light;
    const char *lg = getenv("BDSP_SWKBD_LANG");
    snprintf(G.lang, sizeof G.lang, "%s", lg && *lg ? lg : "USen");
    if (!(lg && *lg) && getenv("BDSP_LANG")) {   // the console language of the runtime (e.g. de-DE) selects the label language of the applet's messages
        static const struct { const char *prefix, *dir; } lm[] = {{"en-GB", "EUen"}, {"en", "USen"}, {"de", "EUde"}, {"fr-CA", "USfr"}, {"fr", "EUfr"}, {"es-419", "USes"},
            {"es", "EUes"}, {"it", "EUit"}, {"nl", "EUnl"}, {"pt-BR", "USpt"}, {"pt", "EUpt"}, {"ru", "EUru"}, {"ja", "JPja"}, {"ko", "KRko"},
            {"zh-TW", "TWzh"}, {"zh-Hant", "TWzh"}, {"zh", "CNzh"}};
        const char *bl = getenv("BDSP_LANG");
        for (unsigned q = 0; q < sizeof lm / sizeof *lm; q++)
            if (!strncmp(bl, lm[q].prefix, strlen(lm[q].prefix))) { snprintf(G.lang, sizeof G.lang, "%s", lm[q].dir); break; }
    }
    {   // keyboard layout: BDSP_SWKBD_LAYOUT, else from the language
        static const struct { const char *lang, *id; } map[] = {{"EUde", "de"}, {"EUfr", "fr"}, {"USfr", "fr"}, {"EUes", "es"}, {"USes", "es"}, {"EUit", "it"},
                                                                  {"EUpt", "pt"}, {"USpt", "pt"}, {"EUru", "ru"}, {"EUen", "uk"}, {"USen", "us"}};
        const char *want = getenv("BDSP_SWKBD_LAYOUT");
        for (unsigned q = 0; q < sizeof map / sizeof *map && !want; q++) if (!strcmp(G.lang, map[q].lang)) want = map[q].id;
        G.li = 0;
        for (unsigned q = 0; q < sizeof k_layouts / sizeof *k_layouts; q++) if (want && !strcmp(want, k_layouts[q].id)) G.li = (int)q;
    }
    const char *root = getenv("BDSP_FIRMWARE_DATA");
    if (root && *root && !getenv("BDSP_SWKBD_SIMPLE")) {
        snprintf(G.root, sizeof G.root, "%s", root);
        swkbd_snd_set_root(root);
        load_labels();
        for (int i = 0; i < SCR_COUNT; i++) build_screen(i);
    }
    if (!G.scr[SCR_QWERTY].ok) {     // no (readable) firmware layouts: simple keyboard of our own
        for (int i = 0; i < SCR_COUNT; i++) fb_build_screen(i);
        trace("simple keyboard", "no firmware layouts");
    }
    G.screen_built = G.scr[SCR_QWERTY].ok;
    return G.screen_built ? 0 : -1;
}

// A renderer announces itself (the Metal overlay does); without one an open keyboard would be invisible and block the game.
void swkbd_ui_set_display(int on) { LOCK(); G.display = on; pthread_mutex_unlock(&G.lock); }

int swkbd_ui_available(void) {
    LOCK();
    int r = G.display && ensure_built() == 0;
    pthread_mutex_unlock(&G.lock);
    return r;
}

// ---- state
static Screen *cur(void) { return &G.scr[G.cur]; }

// The console's sounds of the keyboard (swkbd_snd.c); nothing plays without the firmware data.
static int g_quiet;   // set while the keyboard moves the focus by itself (page change)
static void snd(const char *name) { swkbd_snd_play(name); }
static const char *focus_sound(int kind) {
    switch (kind) {
    case K_CHAR: return "SeSwkbdGlyphFocus";
    case K_BS: return "SeSwkbdBsFocus";
    case K_ENTER: return "SeSwkbdEnterFocus";
    default: return "SeSwkbdOptFocus";   // shift, tabs, symbols, space, globe
    }
}

// A one-shot animation (the press flash) that is left for another state must end on its last frame, otherwise its colour stays on the key.
static void finish_oneshots(Key *k) {
    static const char *const tags[] = {"DecideKey", "DecideTouch", "RepeatKey", "RepeatTouch"};
    if (!k->inst) return;
    for (unsigned i = 0; i < sizeof tags / sizeof *tags; i++) {
        float f = lytinst_anim_frames(k->inst, tags[i]);
        if (f > 0) lytinst_set_anim(k->inst, tags[i], f);
    }
}

static void set_key_anim(Key *k, const char *tag) {
    if (!strcmp(k->tag, tag) && k->t < 1e8f) return;
    if (!strncmp(k->tag, "Decide", 6) || !strncmp(k->tag, "Repeat", 6)) finish_oneshots(k);
    snprintf(k->tag, sizeof k->tag, "%s", tag);
    k->t = 0;
}

static void set_focus(int i) {
    Screen *s = cur();
    if (i < 0 || i >= s->nkeys) return;
    if (G.focus >= 0 && G.focus < s->nkeys && G.focus != i) set_key_anim(&s->keys[G.focus], G.touch_mode ? "UnFocusTouch" : "UnFocusKey");
    if (G.active && !G.touch_mode && !g_quiet && G.focus != i) snd(focus_sound(s->keys[i].kind));
    G.focus = i;
    set_key_anim(&s->keys[i], G.touch_mode ? "FocusTouch" : "FocusKey");
}

static void refresh_labels(void) {
    Screen *s = cur();
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        const char *t = NULL;
        switch (k->kind) {
        case K_CHAR: t = G.shift ? k->shifted : k->normal; break;
        case K_ENTER: t = G.ok_label; break;
        case K_SPACE: t = G.space_label; break;
        case K_SYMBOL: t = "#+="; break;
        case K_BACK: t = "ABC"; break;
        case K_TAB: t = k_tab_label[k->page]; break;
        default: break;
        }
        if (t) lytinst_set_text(k->inst, "T_00", t);
        if (k->kind == K_TAB) {
            int on = k->page == G.page;
            lytinst_set_font_size(k->inst, "T_00", FN_LABEL_EM, FN_LABEL_EM * 1.5f); lytinst_set_offset(k->inst, "T_00", 0, on ? 2.4f : -1.8f);   // the label of the open tab stands 4 px higher, over its underline   // the layouts give each tab its own size; all four look the same
            lytinst_set_visible(k->inst, "P_Active_00", 0);   // the underline of the open tab is drawn by tick (it follows the label width)
            (void)on;
            lytinst_set_color(k->inst, "T_00", COL(on ? g_theme->tab_on : g_theme->text));
        }
        if (k->kind == K_SHIFT) {
            lytinst_set_visible(k->inst, "P_ShiftOn", G.shift != 0);
            lytinst_set_visible(k->inst, "P_ShiftOff", G.shift == 0);
            lytinst_set_visible(k->inst, "P_GlowOn", 0);   // (the dot is drawn by tick)
            lytinst_set_visible(k->inst, "P_GlowOff", 0);
        }
    }
}

static void close_ui(void) {
    trace("close", NULL);
    G.active = 0;
    G.closing = 1; G.close_t = 0;
    G.busy = 0;
}

static void do_cancel(void) {
    if (!G.active) return;
    snd("SeFooterDecideBack");
    close_ui();
    if (G.cb.cancel) G.cb.cancel(G.user);
}

static void do_submit(void) {
    if (!G.active || G.busy) return;
    if (u8_count(G.text) < G.p.minlen) { snd("SeSwkbdLengthError"); return; }
    snd("SeSwkbdEnterDecide");
    trace("submit", G.text);
    G.busy = 1;
    if (G.cb.submit) G.cb.submit(G.user, G.text);
}

static void insert_text(const char *s) {
    for (; *s; s += u8_len((unsigned char)*s)) {
        int l = u8_len((unsigned char)*s);
        unsigned char c = (unsigned char)*s;
        if (c < 0x20 || c == 0x7F) { if (!(c == '\n' && G.p.multiline)) continue; }
        if (G.p.maxlen > 0 && u8_count(G.text) >= G.p.maxlen) { G.cnt_err = 0; snd("SeSwkbdLengthError"); return; }   // the counter shakes
        int n = (int)strlen(G.text);
        if (n + l >= (int)sizeof G.text) return;
        memmove(G.text + G.caret + l, G.text + G.caret, (size_t)(n - G.caret + 1));
        memcpy(G.text + G.caret, s, (size_t)l);
        G.caret += l;
    }
}

static void backspace(void) {
    if (G.caret <= 0) return;
    int p = G.caret - 1;
    while (p > 0 && ((unsigned char)G.text[p] & 0xC0) == 0x80) p--;
    memmove(G.text + p, G.text + G.caret, strlen(G.text + G.caret) + 1);
    G.caret = p;
}

static void caret_move(int dir) {
    if (dir < 0 && G.caret > 0) { int p = G.caret - 1; while (p > 0 && ((unsigned char)G.text[p] & 0xC0) == 0x80) p--; G.caret = p; }
    if (dir > 0 && G.text[G.caret]) G.caret += u8_len((unsigned char)G.text[G.caret]);
}

static void switch_page(int page) {
    if (G.cur == SCR_NUMERIC) return;
    int si = page == 0 ? SCR_QWERTY : SCR_SIGN;
    if (!G.scr[si].ok) return;
    G.page = page; G.cur = si; G.shift = 0;
    Screen *s = cur();
    assign_chars(s, page);
    refresh_labels();
    int f = 0;
    for (int i = 0; i < s->nkeys; i++) if (s->keys[i].kind == K_TAB && s->keys[i].page == page) f = i;
    G.focus = -1;
    g_quiet = 1; set_focus(f); g_quiet = 0;
}

static void press_key(int i) {
    Screen *s = cur();
    if (i < 0 || i >= s->nkeys) return;
    Key *k = &s->keys[i];
    set_key_anim(k, G.touch_mode ? "DecideTouch" : "DecideKey");
    switch (k->kind) {
    case K_CHAR: snd(G.touch_mode ? "SeSwkbdGlyphDown" : "SeSwkbdGlyph"); break;
    case K_BS: snd("SeSwkbdBsDecide"); break;
    case K_ENTER: break;   // do_submit plays its own
    case K_SHIFT: break;   // plays after the state changed
    default: snd("SeSwkbdOptDecide"); break;   // space, tabs, symbols, globe
    }
    switch (k->kind) {
    case K_CHAR:
        insert_text(G.shift ? k->shifted : k->normal);
        if (G.shift == 1) { G.shift = 0; refresh_labels(); }
        break;
    case K_SPACE: insert_text(" "); break;
    case K_BS: backspace(); break;
    case K_ENTER: do_submit(); break;
    case K_SHIFT:
        if (G.cur != SCR_NUMERIC) { G.shift = (G.shift + 1) % 3; refresh_labels(); snd(G.shift == 1 ? "SeSwkbdOptShiftOn" : G.shift == 2 ? "SeSwkbdOptCapsLock" : "SeSwkbdOptShiftOff"); }
        break;
    case K_TAB: if (k->page != G.page) switch_page(k->page); break;
    case K_SYMBOL: switch_page(1); break;
    case K_BACK: switch_page(0); break;
    }
}

static int find_key(int kind) {
    Screen *s = cur();
    for (int i = 0; i < s->nkeys; i++) if (s->keys[i].kind == kind) return i;
    return -1;
}

// Focus move: nearest key whose centre lies in the direction, preferring the same row / column
static void move_focus(int dx, int dy) {
    Screen *s = cur();
    if (G.focus < 0) { set_focus(0); return; }
    const Key *f = &s->keys[G.focus];
    float fx = (f->r[0] + f->r[2]) / 2, fy = (f->r[1] + f->r[3]) / 2;
    int best = -1;
    float bs = 1e30f;
    for (int i = 0; i < s->nkeys; i++) {
        if (i == G.focus || s->keys[i].kind == K_NONE || s->keys[i].hidden) continue;
        const Key *k = &s->keys[i];
        float kx = (k->r[0] + k->r[2]) / 2, ky = (k->r[1] + k->r[3]) / 2;
        float along = dx ? (kx - fx) * dx : (ky - fy) * dy, across = dx ? fabsf(ky - fy) : fabsf(kx - fx);
        if (along < 8) continue;
        float sc = along + 3 * across;
        if (sc < bs) { bs = sc; best = i; }
    }
    if (best >= 0) { G.touch_mode = 0; set_focus(best); }
    else snd("SeKeyErrorCursor");   // nothing in that direction
}

// ---- open / resolve
int swkbd_ui_open(const SwkbdParams *p, SwkbdCallbacks cb, void *user) {
    LOCK();
    if (ensure_built() != 0 || G.active) { pthread_mutex_unlock(&G.lock); return -1; }
    G.p = *p;
    G.cb = cb; G.user = user;
    snprintf(G.text, sizeof G.text, "%s", p->initial);
    while (G.p.maxlen > 0 && u8_count(G.text) > G.p.maxlen) {
        int n = (int)strlen(G.text) - 1;
        while (n > 0 && ((unsigned char)G.text[n] & 0xC0) == 0x80) n--;
        G.text[n] = 0;
    }
    G.caret = (int)strlen(G.text);
    G.busy = 0; G.msg[0] = 0; G.msg_left = 0; G.fade = 0; G.clock = 0; G.closing = 0; G.cnt_err = 99;
    G.pad_prev = 0; memset(G.stick_prev, 0, sizeof G.stick_prev); G.repeat_dir = 0;
    G.touch_mode = 0;
    int si = p->mode == 1 && G.scr[SCR_NUMERIC].ok ? SCR_NUMERIC : SCR_QWERTY;
    G.cur = si; G.focus = -1; G.shift = 0; G.page = 0;
    for (int ki = 0; ki < G.scr[si].nkeys; ki++) { Key *rk = &G.scr[si].keys[ki]; finish_oneshots(rk); snprintf(rk->tag, sizeof rk->tag, "UnFocusKey"); rk->t = 1e9f; }   // keys start at rest (the focus and press states of the last session are gone)
    if (si == SCR_QWERTY) assign_chars(&G.scr[SCR_QWERTY], 0);
    refresh_labels();
    set_focus(0);
    trace("open", p->header);
    if (getenv("BDSP_SWKBD_TYPE")) insert_text(getenv("BDSP_SWKBD_TYPE"));   // test hook: types this text on opening
    G.active = 1;
    pthread_mutex_unlock(&G.lock);
    return 0;
}

void swkbd_ui_resolve(int accepted, const char *message) {
    LOCK();
    if (G.active) {
        G.busy = 0;
        if (accepted) close_ui();
        else if (message) { snprintf(G.msg, sizeof G.msg, "%s", message); G.msg_left = 4; }
    }
    pthread_mutex_unlock(&G.lock);
}

int swkbd_ui_active(void) { return __atomic_load_n(&G.active, __ATOMIC_ACQUIRE); }
int swkbd_ui_visible(void) { return __atomic_load_n(&G.active, __ATOMIC_ACQUIRE) || __atomic_load_n(&G.closing, __ATOMIC_ACQUIRE); }
float swkbd_ui_backdrop(void) { return G.closing ? fmaxf(0, 1 - (float)(G.close_t * 60) / 6) : 1; }
const char *swkbd_ui_text_value(void) { return G.text; }
const char *swkbd_ui_focus_name(void) { Screen *s = &G.scr[G.cur]; return G.focus >= 0 && G.focus < s->nkeys ? s->keys[G.focus].name : ""; }
void swkbd_ui_set_measure(float (*fn)(const char *, float)) { G.measure = fn; }
const char *swkbd_ui_root(void) { return G.root; }

// The text field (for tapping it to bring up the system keyboard), canvas pixels, set by the last scene
int swkbd_ui_field_hit(float nx, float ny) {
    LOCK();
    int hit = 0;
    if (G.active && G.scale > 0) {
        float x = (nx * G.tw - G.off[0]) / G.scale, y = (ny * G.th - G.off[1]) / G.scale;
        hit = x >= G.field[0] && x < G.field[2] && y >= G.field[1] && y < G.field[3];
    }
    pthread_mutex_unlock(&G.lock);
    return hit;
}

// ---- input
enum { B_A, B_B, B_X, B_Y, B_LSTICK, B_RSTICK, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN };

static int g_rep;   // the edge is a repeat of a held button
static void pad_edge(int b) {
    G.touch_mode = 0;
    switch (b) {
    case B_LEFT: move_focus(-1, 0); break;
    case B_RIGHT: move_focus(1, 0); break;
    case B_UP: move_focus(0, -1); break;
    case B_DOWN: move_focus(0, 1); break;
    case B_A: press_key(G.focus); break;
    case B_B: { int i = find_key(K_BS); if (i >= 0) set_key_anim(&cur()->keys[i], "DecideKey"); snd(g_rep ? "SeSwkbdBsRepeat" : "SeSwkbdBsDecide"); backspace(); } break;
    case B_X: do_cancel(); break;
    case B_Y: snd("SeSwkbdOptDecide"); insert_text(" "); break;
    case B_L: snd("SeSwkbdTextAreaMove"); caret_move(-1); break;
    case B_R: snd("SeSwkbdTextAreaMove"); caret_move(1); break;
    case B_LSTICK: { int i = find_key(K_SHIFT); if (i >= 0) press_key(i); } break;
    case B_PLUS: do_submit(); break;
    default: break;
    }
}

void swkbd_ui_pad(uint64_t buttons, int lx, int ly) {
    LOCK();
    if (G.active) {
        int st[4] = {lx < -16000, lx > 16000, ly > 16000, ly < -16000};   // left, right, up, down (stick y is up-positive)
        uint64_t eff = buttons;
        if (st[0]) eff |= 1ull << B_LEFT;
        if (st[1]) eff |= 1ull << B_RIGHT;
        if (st[2]) eff |= 1ull << B_UP;
        if (st[3]) eff |= 1ull << B_DOWN;
        uint64_t down = eff & ~G.pad_prev;
        for (int b = 0; b < 16; b++) if (down & (1ull << b)) {
            pad_edge(b);
            if (b == B_LEFT || b == B_RIGHT || b == B_UP || b == B_DOWN || b == B_B) { G.repeat_dir = b; G.repeat_at = G.clock + 0.4; }
        }
        if (G.repeat_dir && !(eff & (1ull << G.repeat_dir))) G.repeat_dir = 0;
        G.pad_prev = eff;
    }
    pthread_mutex_unlock(&G.lock);
}

void swkbd_ui_touch(int down, float nx, float ny) {
    LOCK();
    if (G.active && down && G.scale > 0) {
        float x = (nx * G.tw - G.off[0]) / G.scale, y = (ny * G.th - G.off[1]) / G.scale;
        Screen *s = cur();
        for (int i = 0; i < s->nkeys; i++) {
            const Key *k = &s->keys[i];
            if (k->kind != K_NONE && !k->hidden && x >= k->r[0] && x < k->r[2] && y >= k->r[1] && y < k->r[3]) {
                G.touch_mode = 1;
                set_focus(i);
                press_key(i);
                break;
            }
        }
    }
    pthread_mutex_unlock(&G.lock);
}

void swkbd_ui_text(const char *utf8) {
    LOCK();
    if (G.active && !G.busy) insert_text(utf8);
    pthread_mutex_unlock(&G.lock);
}

void swkbd_ui_key(int key) {
    LOCK();
    if (G.active && !G.busy) {
        switch (key) {
        case SWKBD_KEY_BACKSPACE: backspace(); break;
        case SWKBD_KEY_DELETE: if (G.text[G.caret]) { caret_move(1); backspace(); } break;
        case SWKBD_KEY_LEFT: caret_move(-1); break;
        case SWKBD_KEY_RIGHT: caret_move(1); break;
        case SWKBD_KEY_HOME: G.caret = 0; break;
        case SWKBD_KEY_END: G.caret = (int)strlen(G.text); break;
        case SWKBD_KEY_ENTER: do_submit(); break;
        case SWKBD_KEY_ESCAPE: do_cancel(); break;
        }
    }
    pthread_mutex_unlock(&G.lock);
}


// ---- simple keyboard without layout files (same logic, own drawing)
static void fb_key(Screen *s, int kind, const char *name, float cx, float cy, float w, float h) {
    if (s->nkeys >= MAX_KEYS) return;
    Key *k = &s->keys[s->nkeys++];
    memset(k, 0, sizeof *k);
    k->kind = kind;
    snprintf(k->name, sizeof k->name, "%s", name);
    k->r[0] = cx - w / 2; k->r[1] = cy - h / 2; k->r[2] = cx + w / 2; k->r[3] = cy + h / 2;
    snprintf(k->tag, sizeof k->tag, "UnFocusKey");
    k->t = 1e9f;
}

static int fb_build_screen(int si) {
    Screen *s = &G.scr[si];
    memset(s, 0, sizeof *s);
    s->fallback = 1;
    if (si == SCR_NUMERIC) {
        static const char *const nm[] = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "-", "0", "."};
        for (int i = 0; i < 12; i++) {
            fb_key(s, K_CHAR, "num", 452 + 188 * (i % 3), 382 + 64 * (i / 3), 184, 60);
            snprintf(s->keys[s->nkeys - 1].normal, 8, "%s", nm[i]);
            snprintf(s->keys[s->nkeys - 1].shifted, 8, "%s", nm[i]);
        }
        fb_key(s, K_BS, "bs", 982, 382, 116, 60);
        fb_key(s, K_ENTER, "enter", 982, 510, 116, 188);
    } else {
        const char *table = si == SCR_QWERTY ? k_layouts[G.li].normal : k_sign;
        for (int i = 0; i < 44; i++) {
            Key tmp;
            memset(&tmp, 0, sizeof tmp);
            u8_nth(table, i, tmp.normal);
            fb_key(s, K_CHAR, "key", 100 + 96 * (i % 11), 328 + 64 * (i / 11), 92, 60);
            Key *k = &s->keys[s->nkeys - 1];
            k->hidden = tmp.normal[0] == 1 || !tmp.normal[0];
            memcpy(k->normal, tmp.normal, sizeof k->normal);
            if (si == SCR_QWERTY) u8_nth(k_layouts[G.li].shifted, i, k->shifted); else memcpy(k->shifted, k->normal, sizeof k->shifted);
        }
        fb_key(s, K_BS, "bs", 1168, 328, 116, 60);
        fb_key(s, K_ENTER, "enter", 1168, 552, 116, 124);
        if (si == SCR_QWERTY) { fb_key(s, K_SHIFT, "shift", 196, 584, 92, 60); fb_key(s, K_SYMBOL, "symbol", 292, 584, 92, 60); }
        else fb_key(s, K_BACK, "back", 196, 584, 92, 60);
        fb_key(s, K_SPACE, "space", 724, 584, 764, 60);
    }
    s->ok = 1;
    return 0;
}

static float g_sa = 1;   // alpha of everything the keyboard itself draws (fades out while it closes)
static void fb_quad(LytScene *sc, float x, float y, float w, float h, int r, int g, int b, float a);
// focus frame around a key rectangle (drawn by the renderer: rounded outer corners, soft edges)
static void fb_frame(LytScene *sc, float x0, float y0, float x1, float y1, int r, int g, int b) {
    fb_quad(sc, x0, y0, x1 - x0, y1 - y0, r, g, b, 1);
    if (sc->n > 0) sc->items[sc->n - 1].type = LYT_ITEM_FRAME;
}
static void fb_quad(LytScene *sc, float x, float y, float w, float h, int r, int g, int b, float a) {
    if (sc->n == sc->cap) {
        int nc = sc->cap ? sc->cap * 2 : 256;
        LytItem *ni = realloc(sc->items, (size_t)nc * sizeof *ni);
        if (!ni) return;
        sc->items = ni; sc->cap = nc;
    }
    LytItem *it = &sc->items[sc->n++];
    memset(it, 0, sizeof *it);
    it->type = LYT_ITEM_QUAD;
    it->x[0] = it->x[2] = x; it->x[1] = it->x[3] = x + w;
    it->y[0] = it->y[1] = y; it->y[2] = it->y[3] = y + h;
    it->alpha = a * g_sa;
    static const float uv[4][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}};
    memcpy(it->uv, uv, sizeof uv);
    for (int k = 0; k < 4; k++) { it->col[k][0] = (uint8_t)r; it->col[k][1] = (uint8_t)g; it->col[k][2] = (uint8_t)b; it->col[k][3] = 255; }
}

// text in a box; origin like a pane base position (0 centre, 1 left/top, 2 right/bottom) in x and y bits
static void fb_text(LytScene *sc, const char *str, float x, float y, float w, float h, float px, int origin, int gray, float a) {
    if (!str || !*str) return;
    if (sc->n == sc->cap) {
        int nc = sc->cap ? sc->cap * 2 : 256;
        LytItem *ni = realloc(sc->items, (size_t)nc * sizeof *ni);
        if (!ni) return;
        sc->items = ni; sc->cap = nc;
    }
    LytItem *it = &sc->items[sc->n++];
    memset(it, 0, sizeof *it);
    it->type = LYT_ITEM_TEXT;
    it->x[0] = it->x[2] = x; it->x[1] = it->x[3] = x + w;
    it->y[0] = it->y[1] = y; it->y[2] = it->y[3] = y + h;
    it->alpha = a * g_sa;
    it->str = str;
    it->font_size[0] = it->font_size[1] = px;
    it->origin = (uint8_t)origin;
    memset(it->top_color, gray, 3); it->top_color[3] = 255;
    memcpy(it->bottom_color, it->top_color, 4);
}

static void fb_scene(Screen *s, const char *shown) {
    LytScene *sc = &G.scene;
    sc->n = 0;
    int n = u8_count(G.text), len_ok = n >= G.p.minlen && !G.busy;
    fb_quad(sc, 0, 0, SWKBD_CANVAS_W, SWKBD_CANVAS_H, 10, 20, 30, 180 / 255.0f);          // dims the game
    fb_quad(sc, 0, 296, SWKBD_CANVAS_W, SWKBD_CANVAS_H - 296, 38, 41, 48, 1.0f);           // keyboard base
    fb_text(sc, G.p.header, 129, 45, 1022, 42, 36, 0x01, 255, 1);
    fb_text(sc, G.msg[0] ? G.msg : G.p.sub, 131, 87, 1018, 30, 26, 0x01, 215, 0.67f);
    fb_text(sc, G.text[0] ? shown : G.p.guide, 134, 154, 1020, 62, 45, 0x05, G.text[0] ? 255 : 180, G.text[0] ? 1.0f : 0.5f);
    fb_quad(sc, 130, 215, 1020, 3, 255, 255, 255, 1);
    char cnt[32];
    if (G.p.maxlen > 0) snprintf(cnt, sizeof cnt, "%d/%d", n, G.p.maxlen); else snprintf(cnt, sizeof cnt, "%d", n);
    fb_text(sc, cnt, 950, 226, 200, 32, 28, 0x02, 200, 0.6f);
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        if (k->hidden) continue;
        float w = k->r[2] - k->r[0], h = k->r[3] - k->r[1];
        int focus = i == G.focus;
        int pressed = !strncmp(k->tag, "Decide", 6) && k->t < 9;
        int r = 58, g = 62, b = 68;
        if (k->kind == K_BS || k->kind == K_SHIFT || k->kind == K_SYMBOL || k->kind == K_BACK || k->kind == K_SPACE) { r = 78; g = 82; b = 90; }
        if (k->kind == K_ENTER) { if (len_ok) { r = 0; g = 140; b = 180; } else { r = 66; g = 70; b = 78; } }
        if (focus) { r = 0; g = 140; b = 180; }
        if (pressed) { r = 0; g = 193; b = 242; }
        fb_quad(sc, k->r[0], k->r[1], w, h, r, g, b, 1);
        if (focus) {   // frame of the cursor
            fb_quad(sc, k->r[0] - 3, k->r[1] - 3, w + 6, 3, 0, 193, 242, 1); fb_quad(sc, k->r[0] - 3, k->r[3], w + 6, 3, 0, 193, 242, 1);
            fb_quad(sc, k->r[0] - 3, k->r[1], 3, h, 0, 193, 242, 1); fb_quad(sc, k->r[2], k->r[1], 3, h, 0, 193, 242, 1);
        }
        const char *t = NULL;
        switch (k->kind) {
        case K_CHAR: t = G.shift ? k->shifted : k->normal; break;
        case K_ENTER: t = G.ok_label; break;
        case K_SPACE: t = G.space_label; break;
        case K_SYMBOL: t = "#+="; break;
        case K_BACK: t = "ABC"; break;
        case K_SHIFT: t = G.shift == 2 ? "\xE2\x87\xAA" : G.shift == 1 ? "\xE2\x87\xA7" : "\xE2\x87\xA7"; break;
        case K_BS: t = "\xE2\x8C\xAB"; break;
        default: break;
        }
        fb_text(sc, t, k->r[0], k->r[1], w, h, k->kind == K_CHAR ? 36 : 28, 0x00, 255, 1);
    }
}


// Footer with the button hints (glyphs of the system's button font): controller, caret keys, shift, cancel, select
// round dot (a black circle glyph), centre and radius in canvas pixels
static void fb_dot(LytScene *sc, float cx, float cy, float r, int cr, int cg, int cb) {
    fb_text(sc, "\xE2\x97\x8F", cx - 16, cy - 16, 32, 32, r * 2.7f, 0x00, 255, 1);
    LytItem *it = &sc->items[sc->n - 1];
    it->top_color[0] = it->bottom_color[0] = (uint8_t)cr; it->top_color[1] = it->bottom_color[1] = (uint8_t)cg; it->top_color[2] = it->bottom_color[2] = (uint8_t)cb;
}

static float text_width(const char *s, float px);
static void footer_items(LytScene *sc) {
    const Theme *t = g_theme;
    int gray = t->text[0];
    float y = 664, h = 40;
    fb_text(sc, "\uE12C", 67.3f, y + 2.4f, 60, h, 44.7f, 0x01, gray, 1);
    fb_quad(sc, 70.7f, 657.7f, 8, 8, 149, 205, 58, 1);   // pagination dots: the current one green and 8 px, the others 6 px grey (measured at half height)
    for (int i = 0; i < 3; i++) fb_quad(sc, 81.7f + 10 * i, 658.7f, 6, 6, 188, 188, 188, 1);
    // the hints are laid out from the right edge with the width of each text (the labels differ in length between languages)
    // glyph or label, its em size and the gap that follows it: 9 px between a key badge and its arrow, 10 px between a glyph and its label, 41 px between the hints
    struct { const char *s; float px; float gap; } it[] = {
        {"\uE0E4", 26.2f, 10.1f}, {"\uE145", 22, 41.9f}, {"\uE0E5", 26.2f, 10.1f}, {"\uE146", 22, 41.4f}, {"\uE103", 25.2f, 11.6f},
        {G.shift == 2 ? lbl("SwkbdFooter_CapsLockOn", "Caps Lock") : lbl("SwkbdFooter_Shift", "Shift"), 22.2f, 40}, {"\uE0E2", 26.2f, 10.7f},
        {lbl("SwkbdFooter_Close", "Cancel"), 22.2f, 41.3f}, {"\uE0E0", 26.2f, 11}, {lbl("SwkbdFooter_Decide", "Select"), 22.2f, 0}};
    enum { N = sizeof it / sizeof *it };
    float w[N], total = 0;
    for (int i = 0; i < N; i++) { w[i] = text_width(it[i].s, it[i].px); total += w[i] + (i < N - 1 ? it[i].gap : 0); }
    float x = 1218.8f - total;   // the right end of the last label is 61 px from the screen edge on the console
    for (int i = 0; i < N; i++) {
        fb_text(sc, it[i].s, x, y, w[i] + 2, h, it[i].px, 0x01, gray, 1);
        x += w[i] + it[i].gap;
    }
}

// ---- scene
static float text_width(const char *s, float px) {
    if (G.measure) return G.measure(s, px);
    return (float)u8_count(s) * px * 0.55f;
}

static void tick(double dt) {
    Screen *s = cur();
    G.clock += dt;
    G.fade = 1.0;
    if (G.cnt_err < 99) G.cnt_err += dt * 60;
    if (G.closing) { G.close_t += dt; if (G.close_t * 60 >= 14) G.closing = 0; }
    if (G.msg_left > 0) { G.msg_left -= dt; if (G.msg_left <= 0) G.msg[0] = 0; }
    if (G.repeat_dir && G.clock >= G.repeat_at) { g_rep = 1; pad_edge(G.repeat_dir); g_rep = 0; G.repeat_at = G.clock + 0.07; }
    int len = u8_count(G.text);
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        k->t += (float)(dt * 60);
        float fr = k->inst ? lytinst_anim_frames(k->inst, k->tag) : (!strncmp(k->tag, "Decide", 6) ? 9.0f : 0.0f);
        if (k->t >= fr) {
            // a finished press falls back to the resting state of the key
            if (!strncmp(k->tag, "Decide", 6)) {
                finish_oneshots(k);
                snprintf(k->tag, sizeof k->tag, i == G.focus ? (G.touch_mode ? "FocusTouch" : "FocusKey") : "UnFocusKey");
                k->t = 1e9f;
                fr = lytinst_anim_frames(k->inst, k->tag);
            }
            k->t = fr;
        }
        lytinst_set_anim(k->inst, k->tag, k->t);
        if (!strncmp(k->tag, "UnFocus", 7)) {   // the two unfocus animations (key / touch) each undo only their own focus animation: run both
            const char *other = !strcmp(k->tag, "UnFocusKey") ? "UnFocusTouch" : "UnFocusKey";
            float of = lytinst_anim_frames(k->inst, other);
            if (of > 0) lytinst_set_anim(k->inst, other, fr > 0 ? k->t / fr * of : of);   // same progress: both end at rest together
        }
        lytinst_set_anim(k->inst, "Alpha", 100);   // full plate (the layouts start dimmed at frame 10)
        if (k->kind == K_BS && g_theme == &k_theme_light) {   // dark with a white icon as soon as there is something to delete
            int on = len > 0;
            lytinst_set_color(k->inst, "P_BtnBase", on ? 52 : g_theme->fn[0], on ? 52 : g_theme->fn[1], on ? 52 : g_theme->fn[2]);
            lytinst_set_color(k->inst, "P_00", on ? 255 : 160, on ? 255 : 160, on ? 255 : 160);   // white icon on the dark key, grey while there is nothing to delete
            lytinst_set_color(k->inst, "T_Key", on ? 255 : 170, on ? 255 : 170, on ? 255 : 170);
        }
        if (k->kind == K_ENTER) {
            int en = len >= G.p.minlen && !G.busy;
            lytinst_set_color(k->inst, "P_BtnBase_00", COL(en ? g_theme->accent : g_theme->dis));
            lytinst_set_color(k->inst, "T_00", COL(en ? g_theme->accent_text : g_theme->text_dis));
            lytinst_set_color(k->inst, "T_Key_00", COL(en ? g_theme->accent_text : g_theme->badge));   // the + badge is white on the blue key
        }
        
        if (i == G.focus) {
            LytInst *c = lytinst_part(k->inst, "UF_Cursor");
            if (c) { float cf = lytinst_anim_frames(c, "Wait"); if (cf > 0) lytinst_set_anim(c, "Wait", fmodf((float)G.clock * 60, cf)); }
        }
    }
}

const LytScene *swkbd_ui_scene(double dt, int tw, int th, float *scale, float off[2]) {
    LOCK();
    if (!G.active && !G.closing) { pthread_mutex_unlock(&G.lock); return NULL; }
    tick(dt);
    if (!G.active && !G.closing) { pthread_mutex_unlock(&G.lock); return NULL; }   // the closing animation has just finished
    float cf = G.closing ? (float)(G.close_t * 60) : 0;   // frames of the closing animation
    g_sa = G.closing ? fmaxf(0, 1 - cf / 6) : 1;
    Screen *s = cur();
    float sc = fminf((float)tw / SWKBD_CANVAS_W, (float)th / SWKBD_CANVAS_H);
    G.scale = sc; G.tw = tw; G.th = th;
    G.off[0] = (tw - SWKBD_CANVAS_W * sc) / 2;
    G.off[1] = (th - SWKBD_CANVAS_H * sc) / 2;
    *scale = sc; off[0] = G.off[0]; off[1] = G.off[1];
    if (s->fallback) {
        char shown[1100];
        int n0 = u8_count(G.text);
        if (G.p.password) { int k = n0 < (int)sizeof shown - 1 ? n0 : (int)sizeof shown - 1; memset(shown, '*', (size_t)k); shown[k] = 0; }
        else snprintf(shown, sizeof shown, "%s", G.text);
        fb_scene(s, shown);
        footer_items(&G.scene);
        G.field[0] = 134; G.field[1] = 130; G.field[2] = 1154; G.field[3] = 236;
        if (fmod(G.clock, 1.0) < 0.6) {   // caret
            char pre[1100];
            snprintf(pre, sizeof pre, "%.*s", G.caret, G.p.password ? shown : G.text);
            fb_quad(&G.scene, 134 + text_width(pre, 45), 158, 4, 58, 230, 230, 230, 1);
        }
        return &G.scene;
    }
    // text area: header, explanation / message, typed text or guide, counter
    lytinst_set_text(s->area, "T_Header", G.p.header[0] ? G.p.header : NULL);
    lytinst_set_text(s->area, "T_Explanation_00", G.msg[0] ? G.msg : G.p.sub[0] ? G.p.sub : NULL);
    char shown[1100];
    int n = u8_count(G.text);
    if (G.p.password) { int k = n < (int)sizeof shown - 1 ? n : (int)sizeof shown - 1; memset(shown, '*', (size_t)k); shown[k] = 0; }
    else snprintf(shown, sizeof shown, "%s", G.text);
    lytinst_set_text(s->area, "T_TextBox_Long", G.text[0] ? shown : NULL);
    lytinst_set_text(s->area, "T_Guide_Long", !G.text[0] && G.p.guide[0] ? G.p.guide : NULL);
    LytInst *cnt = lytinst_part(s->area, "L_Count");
    if (cnt) {
        char c[32];
        if (G.p.maxlen > 0) snprintf(c, sizeof c, "%d/%d", n, G.p.maxlen); else snprintf(c, sizeof c, "%d", n);
        lytinst_set_text(cnt, "T_TextLimit", c);
        if (G.cnt_err < 9) lytinst_set_anim(cnt, "Err", (float)G.cnt_err);   // typing past the limit: the counter shakes
        else if (G.p.maxlen > 0 && n >= G.p.maxlen) lytinst_set_anim(cnt, "Limit", 1);   // and shows its limit colour at the maximum
    }
    float a = (float)G.fade;
    lytinst_set_alpha(s->bg, a); lytinst_set_alpha(s->kt, a * g_sa); lytinst_set_alpha(s->area, a);
    if (getenv("BDSP_TRACE_APPLET") && ((int)(G.clock * 2) != (int)((G.clock - dt) * 2))) fprintf(stderr, "[swkbd_ui] t=%.1f fade=%.2f scale=%.2f target %dx%d screen %d\n", G.clock, G.fade, sc, tw, th, G.cur);
    // entrance: the layouts' own In animations (the keytop slides up and fades in, the text area fades in); the mask fades over 6 frames
    float tf = (float)(G.clock * 60);
    float fr = lytinst_anim_frames(s->bg, "In");
    lytinst_set_anim(s->bg, "In", tf < fr ? tf : fr);
    fr = lytinst_anim_frames(s->area, "In");
    lytinst_set_anim(s->area, "In", tf < fr ? tf : fr);
    lytinst_set_alpha(s->mask, tf < 6 ? tf / 6 : 1);
    if (G.closing) {   // the layouts' own Out animations: the keytop sinks and fades, the text area leaves, the mask fades over 6 frames
        float fo = lytinst_anim_frames(s->bg, "Out");
        lytinst_set_anim(s->bg, "Out", cf < fo ? cf : fo);
        fo = lytinst_anim_frames(s->area, "Out");
        lytinst_set_anim(s->area, "Out", cf < fo ? cf : fo);
        lytinst_set_alpha(s->mask, g_sa);
    }
    G.scene.n = 0;
    fb_quad(&G.scene, 0, 0, SWKBD_CANVAS_W, SWKBD_CANVAS_H, 10, 20, 30, (180 / 255.0f) * (tf < 6 ? tf / 6 : 1));   // the BgMask layout's colour (10,20,30,180) over the whole screen; it fades in over 6 frames (and out with g_sa)
    fb_quad(&G.scene, 0, 320, SWKBD_CANVAS_W, SWKBD_CANVAS_H - 320, COL(g_theme->bg), 1.0f);   // keyboard base (its pane is hidden in the file); the console's starts at y 320
    fb_quad(&G.scene, 0, 320, SWKBD_CANVAS_W, 1, 225, 228, 231, 1.0f);   // with a one pixel highlight at its top edge
    lyt_scene_append(&G.scene, s->bg, 0, 0, 1);
    lyt_scene_append(&G.scene, s->kt, 0, 0, 1);
    for (int i = 0; i < s->nkeys; i++) {   // the tab keys touch: the gap between them is filled and carries a thin dark seam
        const Key *tk = &s->keys[i];
        if (tk->kind != K_TAB || tk->hidden) continue;
        for (int j = 0; j < s->nkeys; j++) {
            const Key *nk = &s->keys[j];
            if (nk->hidden || nk == tk || fabsf(nk->r[1] - tk->r[1]) > 1 || nk->r[0] < tk->r[2] || nk->r[0] - tk->r[2] > 6) continue;
            float gx = tk->r[2], gw = nk->r[0] - tk->r[2];
            if (nk->kind != K_TAB) continue;   // (the gap to the space bar stays open)
            fb_quad(&G.scene, gx, tk->r[1], gw, tk->r[3] - tk->r[1], COL(g_theme->fn), 1);
            fb_quad(&G.scene, gx + gw / 2 - 1.25f, tk->r[1], 2.5f, tk->r[3] - tk->r[1], 188, 188, 188, 1);   // seam between two tabs
        }
    }
    for (int i = 0; i < s->nkeys; i++) {   // underline of the open tab
        const Key *tk = &s->keys[i];
        if (tk->kind != K_TAB || tk->hidden || tk->page != G.page) continue;
        float tw = text_width(k_tab_label[tk->page], 22.2f) * 0.905f, cx = (tk->r[0] + tk->r[2]) / 2, cy = (tk->r[1] + tk->r[3]) / 2;
        fb_quad(&G.scene, cx - tw / 2, cy + 14.6f, tw, 3.4f, 66, 78, 229, 1);   // 45 px wide under ABC, about 3.4 px high (measured on the console)
    }
    for (int i = 0; i < s->nkeys; i++) {   // caps lock dot in the top left corner of the shift key
        const Key *sk = &s->keys[i];
        if (sk->kind != K_SHIFT || sk->hidden) continue;
        const uint8_t *dc = G.shift == 2 ? g_theme->accent : (const uint8_t[]){193, 194, 198};
        fb_dot(&G.scene, sk->r[0] + 13.96f, sk->r[1] + 13.67f, 3.75f, dc[0], dc[1], dc[2]);
    }
    if (G.focus >= 0 && G.focus < s->nkeys && !s->keys[G.focus].hidden && s->keys[G.focus].kind != K_NONE) {   // focus frame
        const Key *fk = &s->keys[G.focus];
        const uint8_t *cc = g_theme->cursor;
        fb_frame(&G.scene, fk->r[0], fk->r[1], fk->r[2], fk->r[3], COL(cc));   // the console's frame lies outside the key: 7 px, soft outer edge, 4.5 px core, rounded outer corners
    }
    footer_items(&G.scene);
    lyt_scene_append(&G.scene, s->area, 0, 0, 1);
    {
        float fb[4];
        if (lyt_pane_bounds(s->area, s->area, "T_TextBox_Long", 0, 0, 1, fb)) { G.field[0] = fb[0]; G.field[1] = fb[1] - 20; G.field[2] = fb[2]; G.field[3] = fb[3] + 40; }
    }
    // caret: left edge of the text box plus the width of the text before it, blinking
    float b[4];
    if (fmod(G.clock, 1.0) < 0.6 && lyt_pane_bounds(s->area, s->area, "T_TextBox_Long", 0, 0, 1, b)) {
        const LytLayout *al = lytinst_layout(s->area);
        int ti = lyt_layout_find_pane(al, "T_TextBox_Long");
        float fpx = ti >= 0 ? al->panes[ti].font_size[0] : 26;   // the renderer draws a glyph with the layout's glyph width as its em size
        char pre[1100];
        snprintf(pre, sizeof pre, "%.*s", G.caret, G.p.password ? shown : G.text);
        float cs = ti >= 0 ? al->panes[ti].char_space : 0;
        float x = b[0] + text_width(pre, fpx) + u8_count(pre) * cs + (pre[0] ? 0.4f : 0.7f);   // measured on the console
        float lh = fpx * 1.45f;                    // height of a text line (37.7 px for the 26 px font on the console)
        float y = b[1] - 7.6f;                     // the caret pane hangs down from its origin (top left), so this is the top of the caret (measured on the console: 161.7 to 199.3 for the 26 px line)
        const LytLayout *cl = lytinst_layout(s->caret);
        lyt_scene_append(&G.scene, s->caret, x - cl->size_xy[0] / 2, y - cl->size_xy[1] / 2, lh / 58.0f);   // the layout's caret is 58 high
    }
    if (getenv("BDSP_TRACE_APPLET") && ((int)(G.clock * 2) != (int)((G.clock - dt) * 2))) fprintf(stderr, "[swkbd_ui] items %d\n", G.scene.n);
    return &G.scene;
}

void swkbd_ui_unlock(void) { pthread_mutex_unlock(&G.lock); }
