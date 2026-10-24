// Korean jamo -> syllables and Japanese romaji -> hiragana for the on-screen keyboard (see swkbd_ime.h). Own tables and rules.
#include "swkbd_ime.h"

#include <stdint.h>
#include <string.h>

static void put_cp(char *out, size_t cap, uint32_t c) {
    size_t n = strlen(out);
    char b[4]; int l;
    if (c < 0x80) { b[0] = (char)c; l = 1; }
    else if (c < 0x800) { b[0] = (char)(0xC0 | c >> 6); b[1] = (char)(0x80 | (c & 0x3F)); l = 2; }
    else { b[0] = (char)(0xE0 | c >> 12); b[1] = (char)(0x80 | ((c >> 6) & 0x3F)); b[2] = (char)(0x80 | (c & 0x3F)); l = 3; }
    if (n + (size_t)l + 1 > cap) return;
    memcpy(out + n, b, (size_t)l); out[n + l] = 0;
}

static uint32_t get_cp(const char *s) {
    const unsigned char *u = (const unsigned char *)s;
    if (u[0] < 0x80) return u[0];
    if (u[0] < 0xE0 && u[1]) return (uint32_t)(u[0] & 0x1F) << 6 | (u[1] & 0x3F);
    if (u[1] && u[2]) return (uint32_t)(u[0] & 0x0F) << 12 | (uint32_t)(u[1] & 0x3F) << 6 | (u[2] & 0x3F);
    return u[0];
}

void swkbd_ime_reset(SwkbdIme *m) { m->L = -1; m->V = -1; m->T = 0; m->pend[0] = 0; }
int swkbd_ime_active(const SwkbdIme *m) { return m->L >= 0 || m->V >= 0 || m->pend[0]; }

// ---- Korean
// compatibility jamo of the initials, the final consonants (index 0 = none) and the vowels start at U+314F
static const uint16_t k_cho[19] = {0x3131, 0x3132, 0x3134, 0x3137, 0x3138, 0x3139, 0x3141, 0x3142, 0x3143, 0x3145, 0x3146, 0x3147, 0x3148, 0x3149, 0x314A, 0x314B, 0x314C, 0x314D, 0x314E};
static const uint16_t k_jong[28] = {0, 0x3131, 0x3132, 0x3133, 0x3134, 0x3135, 0x3136, 0x3137, 0x3139, 0x313A, 0x313B, 0x313C, 0x313D, 0x313E, 0x313F, 0x3140, 0x3141, 0x3142, 0x3144, 0x3145, 0x3146, 0x3147, 0x3148, 0x314A, 0x314B, 0x314C, 0x314D, 0x314E};
// final consonants that are two consonants: first, second, together
static const int8_t k_jong2[][3] = {{1, 19, 3}, {4, 22, 5}, {4, 27, 6}, {8, 1, 9}, {8, 16, 10}, {8, 17, 11}, {8, 19, 12}, {8, 25, 13}, {8, 26, 14}, {8, 27, 15}, {17, 19, 18}};
// vowels that are two vowels: first, second, together
static const int8_t k_jung2[][3] = {{8, 0, 9}, {8, 1, 10}, {8, 20, 11}, {13, 4, 14}, {13, 5, 15}, {13, 20, 16}, {18, 20, 19}};

static int cho_of(uint32_t cp) { for (int i = 0; i < 19; i++) if (k_cho[i] == cp) return i; return -1; }
static int jong_of(uint32_t cp) { for (int i = 1; i < 28; i++) if (k_jong[i] == cp) return i; return -1; }
static int jong_to_cho(int j) { return cho_of(k_jong[j]); }
static int cho_to_jong(int c) { int j = jong_of(k_cho[c]); return j; }   // -1 for the doubled initials that never end a syllable
static int join_jong(int a, int b) { for (unsigned i = 0; i < sizeof k_jong2 / sizeof *k_jong2; i++) if (k_jong2[i][0] == a && k_jong2[i][1] == b) return k_jong2[i][2]; return 0; }
static int join_jung(int a, int b) { for (unsigned i = 0; i < sizeof k_jung2 / sizeof *k_jung2; i++) if (k_jung2[i][0] == a && k_jung2[i][1] == b) return k_jung2[i][2]; return -1; }

static void hangul_text(const SwkbdIme *m, char *out, size_t cap) {
    out[0] = 0;
    if (m->L >= 0 && m->V >= 0) put_cp(out, cap, 0xAC00 + (uint32_t)((m->L * 21 + m->V) * 28 + m->T));
    else if (m->V >= 0) put_cp(out, cap, 0x314Fu + (uint32_t)m->V);
    else if (m->L >= 0) put_cp(out, cap, k_cho[m->L]);
}

// what is composed becomes final, and the composition starts again empty
static void hangul_commit(SwkbdIme *m, char *commit, size_t cap) { char t[8]; hangul_text(m, t, sizeof t); if (strlen(commit) + strlen(t) < cap) strcat(commit, t); m->L = -1; m->V = -1; m->T = 0; }

void swkbd_ime_hangul(SwkbdIme *m, const char *jamo, char *commit, size_t cap) {
    commit[0] = 0;
    uint32_t cp = get_cp(jamo);
    if (cp >= 0x314F && cp <= 0x3163) {   // vowel
        int v = (int)(cp - 0x314F);
        if (m->T > 0) {   // the final consonant moves to the new syllable (the second of two goes alone)
            int t = m->T, first = 0, second = t;
            for (unsigned i = 0; i < sizeof k_jong2 / sizeof *k_jong2; i++) if (k_jong2[i][2] == t) { first = k_jong2[i][0]; second = k_jong2[i][1]; }
            m->T = first;
            hangul_commit(m, commit, cap);
            m->L = jong_to_cho(second); m->V = v; m->T = 0;
        } else if (m->V >= 0) {
            int j = join_jung(m->V, v);
            if (j >= 0) m->V = j; else { hangul_commit(m, commit, cap); m->V = v; }
        } else m->V = v;   // an initial or nothing before it
    } else {
        int c = cho_of(cp);
        if (c < 0) { hangul_commit(m, commit, cap); strncat(commit, jamo, cap - strlen(commit) - 1); return; }   // not a jamo: passes through
        if (m->L >= 0 && m->V >= 0 && m->T == 0) {
            int j = cho_to_jong(c);
            if (j > 0) { m->T = j; return; }
        } else if (m->T > 0) {
            int j = jong_of(cp), t = j > 0 ? join_jong(m->T, j) : 0;
            if (t) { m->T = t; return; }
        }
        hangul_commit(m, commit, cap);
        m->L = c;
    }
}

// ---- Japanese
static const char k_romaji[] =
    "a あ i い u う e え o お ka か ki き ku く ke け ko こ ga が gi ぎ gu ぐ ge げ go ご sa さ si し su す se せ so そ shi し sha しゃ shu しゅ sho しょ she しぇ "
    "za ざ zi じ zu ず ze ぜ zo ぞ ji じ ja じゃ ju じゅ jo じょ je じぇ ta た ti ち tu つ te て to と chi ち cha ちゃ chu ちゅ cho ちょ che ちぇ tsu つ "
    "da だ di ぢ du づ de で do ど na な ni に nu ぬ ne ね no の ha は hi ひ hu ふ he へ ho ほ fu ふ fa ふぁ fi ふぃ fe ふぇ fo ふぉ "
    "ba ば bi び bu ぶ be べ bo ぼ pa ぱ pi ぴ pu ぷ pe ぺ po ぽ ma ま mi み mu む me め mo も ya や yu ゆ yo よ ra ら ri り ru る re れ ro ろ "
    "wa わ wi ゐ we ゑ wo を nn ん n' ん "
    "kya きゃ kyu きゅ kyo きょ gya ぎゃ gyu ぎゅ gyo ぎょ sya しゃ syu しゅ syo しょ zya じゃ zyu じゅ zyo じょ tya ちゃ tyu ちゅ tyo ちょ dya ぢゃ dyu ぢゅ dyo ぢょ "
    "nya にゃ nyu にゅ nyo にょ hya ひゃ hyu ひゅ hyo ひょ bya びゃ byu びゅ byo びょ pya ぴゃ pyu ぴゅ pyo ぴょ mya みゃ myu みゅ myo みょ rya りゃ ryu りゅ ryo りょ "
    "xa ぁ xi ぃ xu ぅ xe ぇ xo ぉ la ぁ li ぃ lu ぅ le ぇ lo ぉ xya ゃ xyu ゅ xyo ょ lya ゃ lyu ゅ lyo ょ xtu っ ltu っ xtsu っ ltsu っ";

// finds pend among the romaji entries: 2 = whole entry (kana in *kana), 1 = start of a longer entry, 0 = none
static int romaji_find(const char *pend, const char **kana, size_t *klen) {
    size_t n = strlen(pend);
    int res = 0;
    for (const char *p = k_romaji; *p;) {
        const char *sp = strchr(p, ' ');
        size_t rl = (size_t)(sp - p);
        const char *kp = sp + 1;
        const char *ke = strchr(kp, ' ');
        size_t kl = ke ? (size_t)(ke - kp) : strlen(kp);
        if (rl == n && !memcmp(p, pend, n)) { *kana = kp; *klen = kl; return 2; }
        if (rl > n && !memcmp(p, pend, n)) res = 1;
        p = ke ? ke + 1 : kp + kl;
    }
    return res;
}

static void add(char *commit, size_t cap, const char *s, size_t l) { size_t n = strlen(commit); if (n + l + 1 <= cap) { memcpy(commit + n, s, l); commit[n + l] = 0; } }

void swkbd_ime_romaji(SwkbdIme *m, const char *key, char *commit, size_t cap) {
    commit[0] = 0;
    char c = key[0];
    if (!((c >= 'a' && c <= 'z') || c == '\'')) {   // not a letter: ends the syllable; '-', ',' and '.' have their Japanese forms
        char t[8]; swkbd_ime_flush(m, t, sizeof t); add(commit, cap, t, strlen(t));
        const char *r = c == '-' && !key[1] ? "ー" : c == ',' && !key[1] ? "、" : c == '.' && !key[1] ? "。" : key;
        add(commit, cap, r, strlen(r));
        return;
    }
    size_t n = strlen(m->pend);
    if (n + 1 >= sizeof m->pend) n = 0;
    m->pend[n] = c; m->pend[n + 1] = 0;
    for (int guard = 0; m->pend[0] && guard < 8; guard++) {
        const char *k; size_t kl;
        int f = romaji_find(m->pend, &k, &kl);
        if (f == 2) { add(commit, cap, k, kl); m->pend[0] = 0; return; }
        if (f == 1) return;
        size_t pl = strlen(m->pend);
        if (m->pend[0] == 'n' && pl >= 2) add(commit, cap, "ん", 3);   // "n" before a consonant is ん
        else if (pl >= 2 && m->pend[0] == m->pend[1] && !strchr("aiueon", m->pend[0])) add(commit, cap, "っ", 3);   // a doubled consonant
        else add(commit, cap, m->pend, 1);   // no kana: the letter stays as it is
        memmove(m->pend, m->pend + 1, pl);
    }
}

// ---- both
void swkbd_ime_text(const SwkbdIme *m, char *out, size_t cap) {
    out[0] = 0;
    if (m->pend[0]) { strncpy(out, m->pend, cap - 1); out[cap - 1] = 0; return; }
    hangul_text(m, out, cap);
}

int swkbd_ime_backspace(SwkbdIme *m) {
    if (m->pend[0]) { m->pend[strlen(m->pend) - 1] = 0; return 1; }
    if (m->T > 0) {
        int first = 0;
        for (unsigned i = 0; i < sizeof k_jong2 / sizeof *k_jong2; i++) if (k_jong2[i][2] == m->T) first = k_jong2[i][0];
        m->T = first;
        return 1;
    }
    if (m->V >= 0) {
        int first = -1;
        for (unsigned i = 0; i < sizeof k_jung2 / sizeof *k_jung2; i++) if (k_jung2[i][2] == m->V) first = k_jung2[i][0];
        m->V = first;
        return 1;
    }
    if (m->L >= 0) { m->L = -1; return 1; }
    return 0;
}

void swkbd_ime_flush(SwkbdIme *m, char *commit, size_t cap) {
    commit[0] = 0;
    if (m->pend[0]) {
        if (!strcmp(m->pend, "n")) add(commit, cap, "ん", 3); else add(commit, cap, m->pend, strlen(m->pend));
        m->pend[0] = 0;
    }
    hangul_commit(m, commit, cap);
}
