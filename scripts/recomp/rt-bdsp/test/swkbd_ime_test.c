// Test of the Korean and Japanese text composition (swkbd_ime.c): typed keys against the expected text.
#include "swkbd_ime.h"

#include <stdio.h>
#include <string.h>

static int fails;
// types the keys (each one utf-8 character of s) with the given engine and returns committed + composing text
static void typed(int hangul, const char *s, char *out, size_t cap, int bs) {
    SwkbdIme m; swkbd_ime_reset(&m);
    out[0] = 0;
    for (const char *p = s; *p;) {
        int l = (unsigned char)*p >= 0xE0 ? 3 : (unsigned char)*p >= 0xC0 ? 2 : 1;
        char k[8] = {0}, c[32];
        memcpy(k, p, (size_t)l); p += l;
        if (k[0] == '<') { if (!swkbd_ime_backspace(&m) && out[0]) { /* a deletion of committed text: drop the last character */ size_t n = strlen(out); do n--; while (n && (out[n] & 0xC0) == 0x80); out[n] = 0; } continue; }
        if (hangul) swkbd_ime_hangul(&m, k, c, sizeof c); else swkbd_ime_romaji(&m, k, c, sizeof c);
        strcat(out, c);
    }
    char t[32]; swkbd_ime_text(&m, t, sizeof t); strcat(out, t);
    (void)bs; (void)cap;
}
#define EXPECT(h, in, want) do { char o[128]; typed(h, in, o, sizeof o, 0); if (strcmp(o, want)) { printf("FAIL %s: \"%s\" -> \"%s\", wanted \"%s\"\n", h ? "ko" : "ja", in, o, want); fails++; } } while (0)

int main(void) {
    EXPECT(1, "ㅎㅏㄴ", "한");
    EXPECT(1, "ㅎㅏㄴㄱㅡㄹ", "한글");
    EXPECT(1, "ㅇㅏㄴㄴㅕㅇ", "안녕");
    EXPECT(1, "ㄱㅏㄱㅅ", "갃");            // two final consonants
    EXPECT(1, "ㄱㅏㄱㅅㅏ", "각사");          // the second one moves on before a vowel
    EXPECT(1, "ㅇㅗㅏ", "와");              // two vowels
    EXPECT(1, "ㅇㅗㅏㄴ", "완");
    EXPECT(1, "ㅂㅏㅂㅂㅏ", "밥바");
    EXPECT(1, "ㅂㅏㅂ<", "바");             // backspace takes the last jamo
    EXPECT(1, "ㅇㅗㅏ<", "오");
    EXPECT(1, "ㄱㅅ", "ㄱㅅ");              // no vowel: single jamo
    EXPECT(1, "ㅏㅏ", "ㅏㅏ");
    EXPECT(1, "ㄸㅏ", "따");
    EXPECT(0, "konnnichiha", "こんにちは");
    EXPECT(0, "nihongo", "にほんご");
    EXPECT(0, "gakkou", "がっこう");
    EXPECT(0, "kyou", "きょう");
    EXPECT(0, "shashin", "しゃしn");   // the last n is still composing
    EXPECT(0, "sensei", "せんせい");
    EXPECT(0, "ka-do", "かーど");
    EXPECT(0, "ky", "ky");               // composing
    EXPECT(0, "ky<", "k");
    EXPECT(0, "xtu", "っ");
    EXPECT(0, "n", "n");
    EXPECT(0, "Ab", "Ab");               // capitals and unknown letters stay
    if (!fails) printf("swkbd_ime_test: ok\n");
    return fails != 0;
}
