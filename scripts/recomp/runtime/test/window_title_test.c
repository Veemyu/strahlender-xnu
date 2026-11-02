// Test of the window title helper (window_title.c): title composition, titles.json parsing, system language to NACP locale matching,
// fallbacks. Invented names only. Build and run: scripts/recomp/runtime/test/run_window_title_test.sh
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../window_title.h"

static int fails;
#define CHECK(x) do { if (!(x)) { printf("ERROR line %d: %s\n", __LINE__, #x); fails++; } } while (0)
#define CHECK_STR(a, b) do { const char *got_ = (a), *want_ = (b); if (!got_ || strcmp(got_, want_)) { printf("ERROR line %d: \"%s\" != \"%s\"\n", __LINE__, got_ ? got_ : "(null)", want_); fails++; } } while (0)

static const char *pick(const bdsp_title_set *set, const char *a, const char *b) {
    const char *languages[2] = {a, b};
    return bdsp_pick_game_name(set, languages, b ? 2 : (a ? 1 : 0));
}

static void candidates(const char *tag, const char *first, const char *second) {
    char c[3][12];
    int n = bdsp_title_candidates(tag, c);
    if (!first) { if (n) { printf("ERROR %s: expected no candidate, got %s\n", tag, c[0]); fails++; } return; }
    if (n != (second ? 2 : 1) || strcmp(c[0], first) || (second && strcmp(c[1], second))) {
        printf("ERROR %s: got %d candidates, first %s\n", tag, n, n ? c[0] : "-");
        fails++;
    }
}

int main(void) {
    char title[64];
    bdsp_build_window_title(title, sizeof title, "Game \xC3\xA9", NULL, NULL);
    CHECK_STR(title, "Game \xC3\xA9");
    bdsp_build_window_title(title, sizeof title, "Game", "", "");
    CHECK_STR(title, "Game");
    bdsp_build_window_title(title, sizeof title, "Game", "Mod X", NULL);
    CHECK_STR(title, "Game - Mod X");
    bdsp_build_window_title(title, sizeof title, "Game", NULL, "issue24-m12");
    CHECK_STR(title, "Game [issue24-m12]");
    bdsp_build_window_title(title, sizeof title, "Game", "Mod X", "t");
    CHECK_STR(title, "Game - Mod X [t]");
    bdsp_build_window_title(title, sizeof title, NULL, NULL, NULL);
    CHECK_STR(title, "BDSP Recomp");
    bdsp_build_window_title(title, sizeof title, "", "Mod X", "t");
    CHECK_STR(title, "BDSP Recomp - Mod X [t]");
    {   // never cuts inside a UTF-8 character, never overflows
        char small[8];
        bdsp_build_window_title(small, sizeof small, "ab\xC3\xA9\xC3\xA9\xC3\xA9", NULL, NULL);
        CHECK_STR(small, "ab\xC3\xA9\xC3\xA9");
        bdsp_build_window_title(small, sizeof small, "abcdef\xC3\xA9", NULL, NULL);
        CHECK_STR(small, "abcdef");
        bdsp_build_window_title(small, 1, "abc", NULL, NULL);
        CHECK(small[0] == 0);
    }

    candidates("de", "de", NULL);
    candidates("de-DE", "de", NULL);
    candidates("de_AT.UTF-8", "de", NULL);
    candidates("en-US", "en-US", "en-GB");
    candidates("en-GB", "en-GB", "en-US");
    candidates("en_AU", "en-GB", "en-US");
    candidates("en", "en-US", "en-GB");
    candidates("es-MX", "es-419", "es-ES");
    candidates("es-419", "es-419", "es-ES");
    candidates("es-ES", "es-ES", "es-419");
    candidates("pt-BR", "pt-BR", "pt-PT");
    candidates("pt-PT", "pt-PT", "pt-BR");
    candidates("fr-CA", "fr-CA", "fr");
    candidates("fr-FR", "fr", "fr-CA");
    candidates("zh-CN", "zh-Hans", "zh-Hant");
    candidates("zh-Hans-CN", "zh-Hans", "zh-Hant");
    candidates("zh-TW", "zh-Hant", "zh-Hans");
    candidates("zh-HK", "zh-Hant", "zh-Hans");
    candidates("zh-Hant", "zh-Hant", "zh-Hans");
    candidates("zh_Hant_TW", "zh-Hant", "zh-Hans");
    candidates("zh-Hans-HK", "zh-Hans", "zh-Hant");
    candidates("ja-JP", "ja", NULL);
    candidates("ko", "ko", NULL);
    candidates("it-IT", "it", NULL);
    candidates("nl-NL", "nl", NULL);
    candidates("ru_RU", "ru", NULL);
    candidates("sv-SE", NULL, NULL);
    candidates("C", NULL, NULL);
    candidates("", NULL, NULL);

    // what scripts/recomp/app/game_icons.py writes for a mod build: names of the game, mod name, ASCII-free text
    static const char json[] =
        "{\n  \"mod\": \"Luminescent \\\"Platinum\\\"\",\n  \"schema\": 1,\n"
        "  \"titles\": {\n    \"de\": \"Pok\xC3\xA9mon Strahlender Diamant\",\n    \"en-US\": \"Pok\\u00e9mon Brilliant Diamond\",\n"
        "    \"ja\": \"\\u30dd\\u30b1\\u30e2\\u30f3\",\n    \"ko\": \"\\ud83d\\ude00\"\n  },\n  \"unknown\": [1, {\"a\": null}, \"x\"]\n}\n";
    bdsp_title_set set;
    CHECK(bdsp_title_set_parse(json, sizeof json - 1, &set));
    CHECK(set.count == 4);
    CHECK_STR(set.mod, "Luminescent \"Platinum\"");
    CHECK_STR(pick(&set, "de-DE", NULL), "Pok\xC3\xA9mon Strahlender Diamant");
    CHECK_STR(pick(&set, "en-GB", NULL), "Pok\xC3\xA9mon Brilliant Diamond");
    CHECK_STR(pick(&set, "ja-JP", NULL), "\xE3\x83\x9D\xE3\x82\xB1\xE3\x83\xA2\xE3\x83\xB3");
    CHECK_STR(pick(&set, "ko-KR", NULL), "\xF0\x9F\x98\x80");
    // the order of the system languages decides; a language without an entry is skipped
    CHECK_STR(pick(&set, "sv-SE", "de-DE"), "Pok\xC3\xA9mon Strahlender Diamant");
    CHECK_STR(pick(&set, "en-US", "de-DE"), "Pok\xC3\xA9mon Brilliant Diamond");
    // no entry for the language (es, fr): English; no languages at all: English
    CHECK_STR(pick(&set, "fr-FR", NULL), "Pok\xC3\xA9mon Brilliant Diamond");
    CHECK_STR(pick(&set, "sv-SE", NULL), "Pok\xC3\xA9mon Brilliant Diamond");
    CHECK_STR(pick(&set, NULL, NULL), "Pok\xC3\xA9mon Brilliant Diamond");
    // without en-US: the first entry
    static const char german[] = "{\"titles\": {\"de\": \"Nur Deutsch\", \"fr\": \"Seulement\"}}";
    CHECK(bdsp_title_set_parse(german, sizeof german - 1, &set));
    CHECK(set.mod[0] == 0);
    CHECK_STR(pick(&set, "ja-JP", NULL), "Nur Deutsch");
    CHECK_STR(pick(&set, "fr-CA", NULL), "Seulement");
    // no data at all: no name, so the title falls back to BDSP Recomp
    static const char empty[] = "{}";
    CHECK(bdsp_title_set_parse(empty, sizeof empty - 1, &set));
    CHECK(pick(&set, "de", NULL) == NULL);
    bdsp_build_window_title(title, sizeof title, pick(&set, "de", NULL), set.mod, NULL);
    CHECK_STR(title, "BDSP Recomp");
    // damaged files are rejected
    static const char *const bad[] = {"", "[]", "{", "{\"titles\": {\"de\": \"x\"", "{\"titles\": {\"de\": \"\\q\"}}",
                                      "{\"titles\": {\"de\": \"\\ud800\"}}", "{\"mod\": \"a\" \"b\": 1}", "{\"titles\": {\"de\": \"a\"},}"};
    for (size_t i = 0; i < sizeof bad / sizeof *bad; i++) {
        if (bdsp_title_set_parse(bad[i], strlen(bad[i]), &set)) { printf("ERROR bad json %zu accepted\n", i); fails++; }
    }

    {   // BDSP_UI_LANGUAGES replaces the system list, in order
        char languages[16][32];
#ifdef _WIN32
        _putenv_s("BDSP_UI_LANGUAGES", "sv-SE:de-DE,en-US");
#else
        setenv("BDSP_UI_LANGUAGES", "sv-SE:de-DE,en-US", 1);
#endif
        int n = bdsp_system_languages(languages, 16);
        CHECK(n == 3);
        CHECK_STR(languages[0], "sv-SE");
        CHECK_STR(languages[1], "de-DE");
        CHECK_STR(languages[2], "en-US");
        CHECK(bdsp_system_languages(languages, 2) == 2);
    }

    printf(fails ? "FAILED: %d errors\n" : "OK: window title test\n", fails);
    return fails ? 1 : 0;
}
