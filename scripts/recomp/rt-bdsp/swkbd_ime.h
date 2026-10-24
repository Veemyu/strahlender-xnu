// Text composition of the on-screen keyboard for languages whose keys are not letters of the text: Korean (jamo keys form syllables) and
// Japanese romaji (latin keys form hiragana). Own code, no data files. The caller keeps the committed text; the engine only tells what
// to commit and what is still being composed (shown in the text field in place of the next character).
#ifndef SWKBD_IME_H
#define SWKBD_IME_H

#include <stddef.h>

typedef struct {
    int L, V, T;       // Korean: index of the initial, vowel and final of the syllable being composed (-1 / -1 / 0 = none)
    char pend[8];      // Japanese: romaji typed so far that no kana was formed from yet
} SwkbdIme;

void swkbd_ime_reset(SwkbdIme *m);
int swkbd_ime_active(const SwkbdIme *m);                                  // 1 while something is being composed
void swkbd_ime_text(const SwkbdIme *m, char *out, size_t cap);           // the text being composed (utf-8), empty when nothing is
// Korean: one jamo (compatibility jamo, utf-8). Returns the text that is complete now (possibly empty) in commit; the composition goes on.
void swkbd_ime_hangul(SwkbdIme *m, const char *jamo, char *commit, size_t cap);
// Japanese romaji: one typed character. Lower case letters, '-', ',' and '.' make kana; everything else passes through unchanged.
void swkbd_ime_romaji(SwkbdIme *m, const char *key, char *commit, size_t cap);
// Backspace: takes the last typed letter out of the composition. Returns 1 when there was a composition (the caller then deletes nothing).
int swkbd_ime_backspace(SwkbdIme *m);
// Ends the composition: what is composed becomes final and is returned in commit.
void swkbd_ime_flush(SwkbdIme *m, char *commit, size_t cap);

// Kana keys: the same kana in hiragana or katakana (hiragana in, kana of the other script out; anything else is copied)
void swkbd_ime_to_katakana(const char *hira, char *out, size_t cap);
// The small-kana / dakuten key: the next form of one kana (か -> が -> か, は -> ば -> ぱ -> は, つ -> っ -> づ, や -> ゃ ...), in hiragana or katakana.
// Returns 1 and the next form in out, 0 when the kana has no other form.
int swkbd_ime_rotate_kana(const char *kana, char *out, size_t cap);

#endif
