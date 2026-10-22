// Shell of the macOS app (BDSP.app): paths and configuration, save game (backup, import, reset), menu, input.
// Built only with -DBDSP_APP (build.sh BDSP_APP=1). Own code, see docs/recomp-macapp.md.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef struct {
    char exe[1024];         // path of the executable
    char bundle[1024];      // BDSP.app (empty if not started from a bundle)
    char resources[1024];   // Contents/Resources (module images, main.npdm) or empty
    char home[1024];        // ~/Library/Application Support/dev.local.xnubdsp (BDSP_HOME)
    char romfs[1024];       // RomFS folder (contains Data/)
    char save[1024];        // save folder (save_1/SaveData.bin, Backup.bin, user_id.hex)
    char cache[1024];       // ~/Library/Caches/dev.local.xnubdsp (shader cache, screenshots)
    char logs[1024];        // ~/Library/Logs/dev.local.xnubdsp
    char config[1024];      // configuration file
    char pad_layout[16];    // "nintendo" (button positions as on the Switch) or "xbox" (labels)
    int pause_on_focus_loss;
    int fullscreen;
    int win_w, win_h;
    int backups;            // number of backups kept at start
    int headless;
    int argc;
    char **argv;
} BdspApp;
extern BdspApp g_app;

// Called from main(): read paths/configuration, set the runtime's environment variables, redirect the log, back up the save.
void bdsp_app_init(int argc, char **argv);

// Save game (app_save.c)
int bdsp_save_backup_start(char *msg, size_t n);                       // backup at start; 1 = created, 0 = unchanged/none, <0 error
int bdsp_save_import(const char *path, char *msg, size_t n);           // check and install a file or folder (Ryujinx/Switch); 0 = ok
int bdsp_save_reset(char *msg, size_t n);                              // move the current state to backups/; 0 = ok
int bdsp_save_validate(const uint8_t *data, size_t len, char *msg, size_t n);   // 0 = size and MD5 valid (as scripts/bdsp_save.py)
void bdsp_save_dir(char *out, size_t n);                               // <save>/save_1

// Restart the process (bundle: open -n, otherwise exec); does not return
void bdsp_app_restart(void) __attribute__((noreturn));
// Message as a window (only if not headless), otherwise stderr only
void bdsp_app_alert(const char *title, const char *msg);

extern volatile int g_bdsp_paused;   // services_gfx.c: stops the vsync event
extern volatile int g_bdsp_fps;      // services_gfx.c: frame rate 30/60/120
void bdsp_set_fps(int fps);          // invalid values are ignored
