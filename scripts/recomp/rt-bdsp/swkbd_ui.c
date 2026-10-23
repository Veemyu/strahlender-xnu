// On-screen software keyboard: state, key logic, input and scene (see swkbd_ui.h). Own code.
// The layouts are the user's firmware files (BDSP_FIRMWARE_DATA); the key characters below are our own table.
#include "swkbd_ui.h"

#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void trace(const char *what, const char *arg) { if (getenv("BDSP_TRACE_APPLET")) fprintf(stderr, "[swkbd_ui] %s %s\n", what, arg ? arg : ""); }

enum { K_CHAR, K_BS, K_ENTER, K_SHIFT, K_SYMBOL, K_BACK, K_SPACE, K_NONE };
enum { SCR_QWERTY, SCR_SIGN, SCR_NUMERIC, SCR_COUNT };
#define MAX_KEYS 80

typedef struct {
    LytInst *inst;
    int kind;
    char name[25];
    char normal[8], shifted[8];
    float r[4];                      // left, top, right, bottom in canvas pixels
    char tag[24];                    // running animation
    float t;
} Key;

typedef struct {
    LytBank *bank;
    LytInst *area, *bg, *kt, *caret;
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
static void load_labels(void) {
    snprintf(G.ok_label, sizeof G.ok_label, "OK");
    snprintf(G.space_label, sizeof G.space_label, "Space");
    const char *lang = getenv("BDSP_SWKBD_LANG");
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
                        char *dst = !strcmp(name, "SwkbdCommon_Enter_Confirm") ? G.ok_label : !strcmp(name, "SwkbdCommon_Space_Space") ? G.space_label : NULL;
                        if (!dst || idx >= nt) continue;
                        uint32_t so; memcpy(&so, txt + 4 + idx * 4, 4);
                        int w = 0;
                        for (size_t k = so; k + 1 < tsz && w < 60; k += 2) {   // UTF-16 -> utf-8 (BMP)
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
}

// ---- screens
static int cmp_keys(const void *a, const void *b) {
    const Key *x = a, *y = b;
    float yx = (x->r[1] + x->r[3]) / 2, yy = (y->r[1] + y->r[3]) / 2;
    if (fabsf(yx - yy) > 20) return yx < yy ? -1 : 1;
    float cx = x->r[0], cy = y->r[0];
    return cx < cy ? -1 : cx > cy ? 1 : 0;
}

// The layouts are white; the Switch's colour scheme is set by the program. This is our dark scheme: dark key plates, cyan focus.
static void apply_theme(Screen *s) {
    static const char *const bases[] = {"P_BaseD", "P_BaseU", "P_BaseF", "P_InlineMarginBtm", "P_BaseDMargin"};
    for (unsigned i = 0; i < sizeof bases / sizeof *bases; i++) lytinst_set_color(s->bg, bases[i], 0x26, 0x29, 0x30);
    static const char *const shadows[] = {"P_ShdwD", "P_ShdwU", "P_ShdwLD", "P_ShdwLU", "P_ShdwRD", "P_ShdwRU", "P_FShdwL", "P_FShdwR", "P_FShdwD", "P_FShdwU"};
    for (unsigned i = 0; i < sizeof shadows / sizeof *shadows; i++) lytinst_set_color(s->bg, shadows[i], 0, 0, 0);
    const LytLayout *kl = lytinst_layout(s->kt);
    for (uint32_t i = 0; i < kl->npanes; i++) {
        LytInst *k = kl->panes[i].kind == LYT_PRT ? lytinst_part(s->kt, kl->panes[i].name) : NULL;
        if (!k) continue;
        lytinst_set_color(k, "P_BtnFocus", 0x00, 0x8C, 0xB4);
        lytinst_set_color(k, "P_BtnBase_00", 0x00, 0x8C, 0xB4);
        lytinst_set_color(k, "P_BtnBase_01", 0x00, 0x8C, 0xB4);
        lytinst_set_color(k, "P_BtnDecideKey", 0x00, 0xC1, 0xF2);
        lytinst_set_color(k, "P_BtnTouch", 0x00, 0xC1, 0xF2);
    }
    lytinst_set_color(s->caret, "P_Cursor", 0xE6, 0xE6, 0xE6);
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
    if (!s->kt || !s->bg || !s->area || !s->caret) return -1;
    lytinst_default_state(s->kt); lytinst_default_state(s->bg); lytinst_default_state(s->area); lytinst_default_state(s->caret);
    lytinst_set_anim(s->area, "TextAreaType", 1);          // frame 1: the long single-line text field
    lytinst_set_visible(s->area, "T_TextBox_Long", 1);
    lytinst_set_visible(s->area, "N_UnFixed", 0);          // composition markers of the input methods we do not have
    lytinst_set_visible(s->kt, "L_BtnLineBreak", 0);
    apply_theme(s);
    const LytLayout *kl = lytinst_layout(s->kt);
    for (uint32_t i = 0; i < kl->npanes && s->nkeys < MAX_KEYS; i++) {
        const LytPane *p = &kl->panes[i];
        if (p->kind != LYT_PRT || !(p->flags & 1)) continue;
        int kind = -1;
        if (!strncmp(p->name, "L_BtnNml", 8)) kind = K_CHAR;
        else if (!strcmp(p->name, "L_BtnBS")) kind = K_BS;
        else if (!strncmp(p->name, "L_BtnEnter", 10)) kind = K_ENTER;
        else if (!strcmp(p->name, "L_BtnShift")) kind = K_SHIFT;
        else if (!strcmp(p->name, "L_BtnSymbol")) kind = K_SYMBOL;
        else if (!strcmp(p->name, "L_BtnArray") && si == SCR_SIGN) kind = K_BACK;
        else if (!strncmp(p->name, "L_BtnSpace", 10)) kind = K_SPACE;
        if (kind < 0) {
            // the language switch and the symbol page tabs have no function here
            if (!strcmp(p->name, "L_BtnArray") || !strncmp(p->name, "L_InputMode", 11)) lytinst_set_visible(s->kt, p->name, 0);
            continue;
        }
        LytInst *inst = lytinst_part(s->kt, p->name);
        if (!inst) continue;
        Key *k = &s->keys[s->nkeys];
        memset(k, 0, sizeof *k);
        k->inst = inst; k->kind = kind;
        snprintf(k->name, sizeof k->name, "%s", p->name);
        if (!lyt_pane_bounds(s->kt, s->kt, p->name, 0, 0, 1, k->r)) continue;
        snprintf(k->tag, sizeof k->tag, "UnFocusKey");
        k->t = 1e9f;
        s->nkeys++;
    }
    qsort(s->keys, s->nkeys, sizeof s->keys[0], cmp_keys);
    // characters in reading order over the ordinary keys (the wide numeric keys L/R last)
    const char *lay = getenv("BDSP_SWKBD_LAYOUT");
    int li = 0;
    for (unsigned q = 0; q < sizeof k_layouts / sizeof *k_layouts; q++) if (lay && !strcmp(lay, k_layouts[q].id)) li = (int)q;
    const char *table = si == SCR_QWERTY ? k_layouts[li].normal : si == SCR_SIGN ? k_sign : k_numeric;
    int ci = 0;
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        if (k->kind != K_CHAR) continue;
        if (si == SCR_NUMERIC && (!strcmp(k->name, "L_BtnNmlL") || !strcmp(k->name, "L_BtnNmlR"))) {
            snprintf(k->normal, sizeof k->normal, "%s", !strcmp(k->name, "L_BtnNmlL") ? "-" : ".");
            snprintf(k->shifted, sizeof k->shifted, "%s", k->normal);
        } else {
            u8_nth(table, ci, k->normal);
            if (si == SCR_QWERTY) u8_nth(k_layouts[li].shifted, ci, k->shifted); else snprintf(k->shifted, sizeof k->shifted, "%s", k->normal);
            ci++;
        }
        if (k->normal[0] == 1 || !k->normal[0]) { k->kind = K_NONE; lytinst_set_visible(s->kt, k->name, 0); continue; }   // no key at this place
        lytinst_set_text(k->inst, "T_00", k->normal);
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
    const char *root = getenv("BDSP_FIRMWARE_DATA");
    if (root && *root && !getenv("BDSP_SWKBD_SIMPLE")) {
        snprintf(G.root, sizeof G.root, "%s", root);
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

static void set_key_anim(Key *k, const char *tag) {
    if (!strcmp(k->tag, tag) && k->t < 1e8f) return;
    snprintf(k->tag, sizeof k->tag, "%s", tag);
    k->t = 0;
}

static void set_focus(int i) {
    Screen *s = cur();
    if (i < 0 || i >= s->nkeys) return;
    if (G.focus >= 0 && G.focus < s->nkeys && G.focus != i) set_key_anim(&s->keys[G.focus], G.touch_mode ? "UnFocusTouch" : "UnFocusKey");
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
        default: break;
        }
        if (t) lytinst_set_text(k->inst, "T_00", t);
        if (k->kind == K_SHIFT) {
            lytinst_set_visible(k->inst, "P_ShiftOn", G.shift != 0);
            lytinst_set_visible(k->inst, "P_ShiftOff", G.shift == 0);
            lytinst_set_visible(k->inst, "P_GlowOn", G.shift == 2);
            lytinst_set_visible(k->inst, "P_GlowOff", G.shift != 2);
        }
    }
}

static void close_ui(void) {
    trace("close", NULL);
    G.active = 0;
    G.busy = 0;
}

static void do_cancel(void) {
    if (!G.active) return;
    close_ui();
    if (G.cb.cancel) G.cb.cancel(G.user);
}

static void do_submit(void) {
    if (!G.active || G.busy) return;
    if (u8_count(G.text) < G.p.minlen) return;
    trace("submit", G.text);
    G.busy = 1;
    if (G.cb.submit) G.cb.submit(G.user, G.text);
}

static void insert_text(const char *s) {
    for (; *s; s += u8_len((unsigned char)*s)) {
        int l = u8_len((unsigned char)*s);
        unsigned char c = (unsigned char)*s;
        if (c < 0x20 || c == 0x7F) { if (!(c == '\n' && G.p.multiline)) continue; }
        if (G.p.maxlen > 0 && u8_count(G.text) >= G.p.maxlen) return;
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

static void switch_screen(int si) {
    if (!G.scr[si].ok) return;
    G.cur = si;
    G.focus = -1;
    G.shift = 0;
    refresh_labels();
    set_focus(0);
}

static void press_key(int i) {
    Screen *s = cur();
    if (i < 0 || i >= s->nkeys) return;
    Key *k = &s->keys[i];
    set_key_anim(k, G.touch_mode ? "DecideTouch" : "DecideKey");
    switch (k->kind) {
    case K_CHAR:
        insert_text(G.shift ? k->shifted : k->normal);
        if (G.shift == 1) { G.shift = 0; refresh_labels(); }
        break;
    case K_SPACE: insert_text(" "); break;
    case K_BS: backspace(); break;
    case K_ENTER: do_submit(); break;
    case K_SHIFT:
        if (G.cur == SCR_QWERTY) { G.shift = (G.shift + 1) % 3; refresh_labels(); }
        break;
    case K_SYMBOL: switch_screen(SCR_SIGN); break;
    case K_BACK: switch_screen(SCR_QWERTY); break;
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
        if (i == G.focus || s->keys[i].kind == K_NONE) continue;
        const Key *k = &s->keys[i];
        float kx = (k->r[0] + k->r[2]) / 2, ky = (k->r[1] + k->r[3]) / 2;
        float along = dx ? (kx - fx) * dx : (ky - fy) * dy, across = dx ? fabsf(ky - fy) : fabsf(kx - fx);
        if (along < 8) continue;
        float sc = along + 3 * across;
        if (sc < bs) { bs = sc; best = i; }
    }
    if (best >= 0) { G.touch_mode = 0; set_focus(best); }
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
    G.busy = 0; G.msg[0] = 0; G.msg_left = 0; G.fade = 0; G.clock = 0;
    G.pad_prev = 0; memset(G.stick_prev, 0, sizeof G.stick_prev); G.repeat_dir = 0;
    G.touch_mode = 0;
    int si = p->mode == 1 && G.scr[SCR_NUMERIC].ok ? SCR_NUMERIC : SCR_QWERTY;
    G.cur = si; G.focus = -1; G.shift = 0;
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
const char *swkbd_ui_text_value(void) { return G.text; }
const char *swkbd_ui_focus_name(void) { Screen *s = &G.scr[G.cur]; return G.focus >= 0 && G.focus < s->nkeys ? s->keys[G.focus].name : ""; }
void swkbd_ui_set_measure(float (*fn)(const char *, float)) { G.measure = fn; }

// ---- input
enum { B_A, B_B, B_X, B_Y, B_LSTICK, B_RSTICK, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN };

static void pad_edge(int b) {
    G.touch_mode = 0;
    switch (b) {
    case B_LEFT: move_focus(-1, 0); break;
    case B_RIGHT: move_focus(1, 0); break;
    case B_UP: move_focus(0, -1); break;
    case B_DOWN: move_focus(0, 1); break;
    case B_A: press_key(G.focus); break;
    case B_B: { int i = find_key(K_BS); if (i >= 0) set_key_anim(&cur()->keys[i], "DecideKey"); backspace(); } break;
    case B_X: do_cancel(); break;
    case B_Y: insert_text(" "); break;
    case B_L: caret_move(-1); break;
    case B_R: caret_move(1); break;
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
            if (k->kind != K_NONE && x >= k->r[0] && x < k->r[2] && y >= k->r[1] && y < k->r[3]) {
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
    const char *lay = getenv("BDSP_SWKBD_LAYOUT");
    int li = 0;
    for (unsigned q = 0; q < sizeof k_layouts / sizeof *k_layouts; q++) if (lay && !strcmp(lay, k_layouts[q].id)) li = (int)q;
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
        const char *table = si == SCR_QWERTY ? k_layouts[li].normal : k_sign;
        for (int i = 0; i < 44; i++) {
            Key tmp;
            memset(&tmp, 0, sizeof tmp);
            u8_nth(table, i, tmp.normal);
            if (tmp.normal[0] == 1 || !tmp.normal[0]) continue;
            fb_key(s, K_CHAR, "key", 100 + 96 * (i % 11), 328 + 64 * (i / 11), 92, 60);
            Key *k = &s->keys[s->nkeys - 1];
            memcpy(k->normal, tmp.normal, sizeof k->normal);
            if (si == SCR_QWERTY) u8_nth(k_layouts[li].shifted, i, k->shifted); else memcpy(k->shifted, k->normal, sizeof k->shifted);
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
    it->alpha = a;
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
    it->alpha = a;
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

// ---- scene
static float text_width(const char *s, float px) {
    if (G.measure) return G.measure(s, px);
    return (float)u8_count(s) * px * 0.55f;
}

static void tick(double dt) {
    Screen *s = cur();
    G.clock += dt;
    G.fade = 1.0;
    if (G.msg_left > 0) { G.msg_left -= dt; if (G.msg_left <= 0) G.msg[0] = 0; }
    if (G.repeat_dir && G.clock >= G.repeat_at) { pad_edge(G.repeat_dir); G.repeat_at = G.clock + 0.07; }
    int len = u8_count(G.text);
    for (int i = 0; i < s->nkeys; i++) {
        Key *k = &s->keys[i];
        k->t += (float)(dt * 60);
        float fr = k->inst ? lytinst_anim_frames(k->inst, k->tag) : (!strncmp(k->tag, "Decide", 6) ? 9.0f : 0.0f);
        if (k->t >= fr) {
            // a finished press falls back to the resting state of the key
            if (!strncmp(k->tag, "Decide", 6)) {
                snprintf(k->tag, sizeof k->tag, i == G.focus ? (G.touch_mode ? "FocusTouch" : "FocusKey") : "UnFocusKey");
                k->t = 1e9f;
                fr = lytinst_anim_frames(k->inst, k->tag);
            }
            k->t = fr;
        }
        lytinst_set_anim(k->inst, k->tag, k->t);
        if (k->kind == K_ENTER) lytinst_set_anim(k->inst, "Alpha", len >= G.p.minlen && !G.busy ? 100 : 10);
        
        if (i == G.focus) {
            LytInst *c = lytinst_part(k->inst, "UF_Cursor");
            if (c) { float cf = lytinst_anim_frames(c, "Wait"); if (cf > 0) lytinst_set_anim(c, "Wait", fmodf((float)G.clock * 60, cf)); }
        }
    }
}

const LytScene *swkbd_ui_scene(double dt, int tw, int th, float *scale, float off[2]) {
    LOCK();
    if (!G.active) { pthread_mutex_unlock(&G.lock); return NULL; }
    tick(dt);
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
    }
    float a = (float)G.fade;
    lytinst_set_alpha(s->bg, a); lytinst_set_alpha(s->kt, a); lytinst_set_alpha(s->area, a);
    if (getenv("BDSP_TRACE_APPLET") && ((int)(G.clock * 2) != (int)((G.clock - dt) * 2))) fprintf(stderr, "[swkbd_ui] t=%.1f fade=%.2f scale=%.2f target %dx%d screen %d\n", G.clock, G.fade, sc, tw, th, G.cur);
    lyt_scene_build(&G.scene, s->bg, 0, 0, 1);
    lyt_scene_append(&G.scene, s->kt, 0, 0, 1);
    lyt_scene_append(&G.scene, s->area, 0, 0, 1);
    // caret: left edge of the text box plus the width of the text before it, blinking
    float b[4];
    if (fmod(G.clock, 1.0) < 0.6 && lyt_pane_bounds(s->area, s->area, "T_TextBox_Long", 0, 0, 1, b)) {
        const LytLayout *al = lytinst_layout(s->area);
        int ti = lyt_layout_find_pane(al, "T_TextBox_Long");
        float fpx = ti >= 0 ? al->panes[ti].font_size[1] : 40;
        char pre[1100];
        snprintf(pre, sizeof pre, "%.*s", G.caret, G.p.password ? shown : G.text);
        float x = b[0] + text_width(pre, fpx);
        float y = b[1] + 2;
        const LytLayout *cl = lytinst_layout(s->caret);
        lyt_scene_append(&G.scene, s->caret, x - cl->size_xy[0] / 2, y - cl->size_xy[1] / 2, 1);
    }
    if (getenv("BDSP_TRACE_APPLET") && ((int)(G.clock * 2) != (int)((G.clock - dt) * 2))) fprintf(stderr, "[swkbd_ui] items %d\n", G.scene.n);
    return &G.scene;
}

void swkbd_ui_unlock(void) { pthread_mutex_unlock(&G.lock); }
