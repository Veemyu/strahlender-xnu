// Window title of the game window: <game name from the game's own control.nacp in the system language>[ - <mod>][ [<tag>]].
// The names come from titles.json next to the app icons (written by scripts/recomp/app/game_icons.py); nothing is hard-coded here.
#pragma once
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BDSP_TITLE_LOCALES 16
#define BDSP_TITLE_FALLBACK "BDSP Recomp"

typedef struct {
    char mod[256];                                   // mod name, empty for the plain game
    struct { char id[12]; char name[256]; } entry[BDSP_TITLE_LOCALES];  // NACP locale id (en-US, de, es-419 ...) and name
    int count;
} bdsp_title_set;

// "<game>[ - <mod>][ [<tag>]]"; an empty game name gives BDSP_TITLE_FALLBACK. Truncates on a UTF-8 character boundary.
void bdsp_build_window_title(char *out, size_t capacity, const char *game_name, const char *mod_name, const char *tag);

// Parses titles.json ({"schema":1,"mod":"...","titles":{"de":"..."}}). False when it is not valid JSON.
bool bdsp_title_set_parse(const char *json, size_t length, bdsp_title_set *set);

// NACP locale ids that suit one system language tag (de-DE, en_GB.UTF-8, zh-Hant-TW ...), best first; returns the count (0 to 3).
int bdsp_title_candidates(const char *language_tag, char candidates[3][12]);

// Name for the first system language that has an entry; else en-US, then the first entry; NULL without any entry.
const char *bdsp_pick_game_name(const bdsp_title_set *set, const char *const *languages, int count);

// The system's preferred languages in order (CoreFoundation, GetUserPreferredUILanguages, LANGUAGE/LC_ALL/LC_MESSAGES/LANG).
// BDSP_UI_LANGUAGES="de-DE:en-US" replaces that list (for tests; the game language BDSP_LANG is unrelated).
int bdsp_system_languages(char languages[][32], int capacity);

// Complete title for the running app: finds titles.json under base_dir (icons/windows, icons/linux, AppIcons, or BDSP_ICON_DIR),
// takes the system language and BDSP_WINDOW_TAG. mod_override replaces the mod name of the file when not empty.
void bdsp_window_title(char *out, size_t capacity, const char *base_dir, const char *mod_override);

#ifdef __cplusplus
}
#endif
