# Bildrate, Metal-HUD und Animationstakt

## Verhaltensanforderung (Nutzerbeobachtung, nicht aus dem Code belegt)

Im Original-Emulator, mit 60 fps beobachtet, läuft das Spiel mit Spielgeschwindigkeit 1x. NPCs und die Wasser-Animation laufen
dabei aber 2x so schnell. Die Wasser-Animation ist im Original an 30 fps gebunden. Die Rekompilation soll bei 60 fps Präsentation
das Spiel mit 1x laufen lassen und NPCs und Wasser mit dem gleichen Verhalten wie auf der Konsole zeigen. Ob sie das schon tut, ist
**gemessen zu prüfen** (Vergleichsaufnahme gleicher Szene bei 30 und 60 fps), nicht anzunehmen. Noch nicht umgesetzt.

## Bildrate: Stand

- Auswahl 30, 60 oder 120 fps. Der Wert wirkt auf den Vsync-Takt (`services_gfx.c`, `bdsp_set_fps()`) und auf die Präsentation (`frame_pace` in `scripts/recomp/rt-bdsp/nvn/nvn_glue.c`, nur macOS).
- iPad: Einstellung „Bildrate“ in den iOS-Einstellungen der App (`Settings.bundle`, Schlüssel `bdsp_fps`). Wirkt nach einem Neustart der App. Lokalisiert (en, de).
- Mac: Menü „Bildrate“ (`app_ui.m`, Schlüssel `bdsp_fps`, Vorgabe in `config.ini` über `fps`). Noch nicht lokalisiert, 30/60/120 noch nicht gemessen.
- Umgebungsvariable `BDSP_FPS_INTERVAL` steuert den Log-Takt der fps-Anzeige (Standard 2 s).

## Ursache der 50-fps-Grenze (behoben)

- Der Vsync-Thread in `services_gfx.c` schlief mit `nanosleep(16666667)` ohne absolute Deadline. Die Schlafdauer addierte
  sich Frame für Frame, der Takt fiel auf etwa 19,8 ms (rund 50 Hz).
- Fix: absolute Deadlines (`CLOCK_MONOTONIC`). Messung Mac: 59,98 und 59,87 fps. Das MacBook-Display auf 60 Hz gestellt
  macht die Frametimes deutlich stabiler. Bei ProMotion (120 Hz) ist das Pacing für 60 fps nicht ideal; mögliche Umgehungen sind offen.
- Frühere Einbrüche auf etwa 20 fps kamen von Debug-Instrumentierung (`waitUntilCompleted`, `getBytes`), nicht von der Laufzeit.
- Debug-Thread: `BDSP_DEBUG_THREAD=1` führt Readbacks auf eigenem Thread aus (`nvn/dbgthread.patch`, `nvn/debug_thread.c`). Mac: 43,4 fps ohne, 49,6 fps mit Debug-Thread (Messung vor dem Vsync-Fix).

## Metal-HUD

- macOS: `MTL_HUD_ENABLED=1` beim Start setzen (zeigt FPS, GPU-Zeit, Frametime auf der Metal-Ebene). Im headless-Lauf nicht sichtbar prüfbar.
- iPad: Schalter „Metal-HUD anzeigen“ im Bereich „Debug“ der App-Einstellungen (Schlüssel `bdsp_metal_hud`). Die App setzt
  `MTL_HUD_ENABLED=1` beim Start, bevor Metal initialisiert wird. Wirkt nach einem Neustart. Auf dem Gerät bestätigt.
- App-Store-Apps lassen sich ohne Xcode oder Drittwerkzeug nicht per Gerät anzeigen; der App-Schalter ist deshalb der Weg.
- Log: `[metal] … fps` alle `BDSP_FPS_INTERVAL` Sekunden.

## Wo der Animationstakt sitzt (Analyse, offen)

Der Spieltakt kommt aus dem Gastcode (Unity-IL2CPP, Zeitdelta pro Frame); Wasser-Shader-Zeit und NPC-Updates laufen darin und
werden nicht von der Laufzeit getaktet. Die Laufzeit liefert nur die Zeitquellen (`rt_now_ns`, kernel.c) und die Präsentation
(metal.m). Stellen zum Prüfen: Zeitbasis/Delta des Gastes, Wasser-Zeitvariable in den Shader-Uniforms (Wasser-Agent, renderer.m).
