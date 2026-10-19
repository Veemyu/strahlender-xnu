// Hülle der macOS-App (BDSP.app): Pfade und Konfiguration, Spielstand (Sicherung, Import, Zurücksetzen), Menü, Eingabe.
// Nur mit -DBDSP_APP gebaut (build.sh BDSP_APP=1). Eigener Code, siehe docs/recomp-macapp.md.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef struct {
    char exe[1024];         // Pfad der ausführbaren Datei
    char bundle[1024];      // BDSP.app (leer, wenn nicht aus einem Bundle gestartet)
    char resources[1024];   // Contents/Resources (Modulbilder, main.npdm) oder leer
    char home[1024];        // ~/Library/Application Support/dev.local.xnubdsp (BDSP_HOME)
    char romfs[1024];       // RomFS-Ordner (enthält Data/)
    char save[1024];        // Spielstand-Ordner (save_1/SaveData.bin, Backup.bin, user_id.hex)
    char cache[1024];       // ~/Library/Caches/dev.local.xnubdsp (Shader-Cache, Bildschirmfotos)
    char logs[1024];        // ~/Library/Logs/dev.local.xnubdsp
    char config[1024];      // Konfigurationsdatei
    char pad_layout[16];    // "nintendo" (Position wie bei der Switch) oder "xbox" (Beschriftung)
    int pause_on_focus_loss;
    int fullscreen;
    int win_w, win_h;
    int backups;            // Anzahl der Sicherungen beim Start
    int headless;
    int argc;
    char **argv;
} BdspApp;
extern BdspApp g_app;

// Aus main(): Pfade/Konfiguration lesen, Umgebungsvariablen der Laufzeit setzen, Log umleiten, Sicherung des Spielstands.
void bdsp_app_init(int argc, char **argv);

// Spielstand (app_save.c)
int bdsp_save_backup_start(char *msg, size_t n);                       // Sicherung beim Start; 1 = angelegt, 0 = unverändert/keine, <0 Fehler
int bdsp_save_import(const char *path, char *msg, size_t n);           // Datei oder Ordner (Ryujinx/Switch) prüfen und installieren; 0 = ok
int bdsp_save_reset(char *msg, size_t n);                              // aktuellen Stand in backups/ verschieben; 0 = ok
int bdsp_save_validate(const uint8_t *data, size_t len, char *msg, size_t n);   // 0 = Größe und MD5 gültig (wie scripts/bdsp_save.py)
void bdsp_save_dir(char *out, size_t n);                               // <save>/save_1

// Neustart des Prozesses (Bundle: open -n, sonst exec); kehrt nicht zurück
void bdsp_app_restart(void) __attribute__((noreturn));
// Meldung als Fenster (nur wenn nicht headless), sonst nur stderr
void bdsp_app_alert(const char *title, const char *msg);

extern volatile int g_bdsp_paused;   // services_gfx.c: hält das Vsync-Ereignis an
extern volatile int g_bdsp_fps;      // services_gfx.c: Bildrate 30/60/120
void bdsp_set_fps(int fps);          // ungültige Werte werden ignoriert
