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
  macht die Frametimes deutlich stabiler. Bei ProMotion (120 Hz) war das Pacing für 60 fps nicht ideal (siehe unten, behoben).

## ProMotion, 60-fps-Ziel: phasenstarre Präsentation (Mac, Standard)

- Ursache: `presentDrawable` ohne Zielzeit. Das Bild erscheint am nächsten der 120-Hz-Ticks nach Fertigstellung; die Taktgeber-Uhr (`frame_pace`) ist nicht auf die Anzeige-Phase ausgerichtet, Bilder springen zwischen 1 und 3 Ticks (8,3 / 25 ms) hin und her.
- Lösung (`metal.m`, `BDSP_PRESENT_AT=lock`, Mac-Standard, `off` = altes Verhalten): jedes Bild bekommt `presentDrawable atTime:` genau `step` Anzeigeintervalle nach dem vorigen (Kette, 2 Ticks bei 60 fps), Raster aus der letzten echten `presentedTime`. Kommt ein Bild zu spät, wird mit Vorlauf (`BDSP_PRESENT_LEAD`, Standard 1,0 Intervalle von `step`) neu aufgesetzt. iPad: bis zur Messung aus (`BDSP_PRESENT_AT=lock` zum Testen).
- Messung (Mac, ProMotion, Overworld `auto-input2.txt`, `BDSP_PRESENT_STATS=1`, 3 Läufe je ~55 s ab Spielstart, Anteil der Abstände in 16,67 ± 0,3 ms): vorher 92,4 / 94,4 / 71,0 %; nachher 98,4 / 99,0 / 99,1 % (Standard 98,9 / 99,4 %, ohne Worker 99,0 %). Mittel 16,67 ms. Reste: Ladehänger (4+ Ticks).
- Verworfen: `afterMinimumDuration` (95,7 % einmal, ohne Worker kaputt), `grid` (60,8 % mit Worker), kürzerer Takt `BDSP_PACE_PCT=90/97` (92,6 / 85,9 %, nur Messhilfe).
- Zweite Messrunde (HUD aus, `BDSP_NO_HUD=1`, nur Frames nach Frame 1000, 3 Läufe Overworld mit Worker, `BDSP_PRESENT_OUT=1` listet jeden Abstand außerhalb 16,67 ± 0,3 ms): 99,51 / 99,49 / 99,39 % im Band (13 / 14 / 17 Ausreißer je ~2700 Frames, davon 6–8 Intervalle von 25 ms, je höchstens ein Intervall ≥ 33 ms). Ohne Worker 99,54 %. Abnahme (≥ 99,5 %, kein Intervall ≥ 25 ms) **nicht erreicht**.
- Ursache der Reste: Ein Bild erscheint einen Anzeige-Tick zu spät (25 ms), das nächste wieder im Raster (8,3 ms). Nicht GPU (GPU-Ende ~45 ms vor Anzeige), nicht Commit (Vorlauf ~35–50 ms), nicht Lade-/Szenenwechsel (gleich im Titelbild ohne Eingabe), nicht das Metal-HUD, kein Einfluss von Offset des `atTime` (0 / 0,25 / 0,5 / 0,75 Tick) oder Vorlauf (0,5–3,5). Die Ereignisse sitzen auf einem etwa sekündlichen Zeitraster. Ein minimales Metal-Testprogramm (leeres Fenster, gleiche Kette, ohne Spiel) zeigt dieselben 25/8,3-ms-Paare: 98,4–98,9 % im Band. Das ist die Grenze des ProMotion-Compositors, nicht des Spiels.
- Weitere verworfene Versuche (Testprogramm und Spiel): `CADisplayLink` mit `preferredFrameRateRange` 60 (Display bleibt bei 120-Hz-Ticks, 98,5 %), doppelte Präsentation pro Bild (98,4 %), `maximumDrawableCount` 2 (98,4 %). `afterMinimumDuration` im Testprogramm 99,55 % (nur 25-ms-Verspätungen, keine 8,3-ms-Nachzügler), im Spiel aber nur 44–82 % (der Gast-Takt hat bis 29 ms Streuung, keine Warteschlange vor der Anzeige).
- Selten (2 von etwa 45 Läufen, auch mit `BDSP_PRESENT_AT=off`): Start hängt vor dem ersten Bild (kein `[metal]`-Log). Unabhängig vom Lock-Modus, offen.
- Test: `BDSP_FPS=60` gewinnt jetzt gegen die gespeicherte Menü-Einstellung.

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

## Analyse Animationstempo 30/60/120 (Code-Beleg, ungemessen)

- Zeitquellen der Laufzeit sind echtzeitrichtig: `rt_ticks()` (`kernel.c:29`, 19,2 MHz aus `rt_now_ns`), SVC `GetSystemTick` (`kernel.c:680`),
  Vsync-Takt mit absoluten Deadlines (`services_gfx.c:31`). Spielfigur und Welt laufen bei 30/60/120 gleich schnell; die Zeitbasis ist also nicht der Fehler.
- Die Laufzeit gibt dem Gast keinen Wasser- oder NPC-Takt vor (kein Hook, keine Zeituniform in `renderer.m`). Die Abweichung entsteht im Gastcode:
  NPC-Animation und Wasser werden dort pro Update/Frame fortgeschrieben (Ryujinx mit 60-fps-Mods zeigt dasselbe), nicht per `DeltaTime.deltaTime`
  (`Dpr.Field.Walking.DeltaTime`, Figur/Welt nutzen es). Eine Laufzeit-Korrektur ohne Eingriff in den Gastcode gibt es nicht.
- Nächster Schritt: per Binäranalyse (REA, NPC-Animator-Update und Wasser-Material-Zeit im Gast-ELF) die Stelle suchen, die pro Frame addiert,
  und dort Schrittweite mit 30/fps skalieren oder nur jeden (fps/30)-ten Aufruf ausführen. Danach 30/60/120 messen.

### Gast-Befund per ISIL-Dump (Adressen = Offsets im Hauptmodul, ungemessen)

- `Sequencer::Update` (0x02BC2C70, AssetAssistant): holt `Time.get_deltaTime`, schreibt es in das Statics-Feld +0x50 (das liest `DeltaTime::get_deltaTime`, 0x01CD08B0, mal `TimeScale`) und ruft die `TickCallback`s mit `Time.deltaTime`.
- `Sequencer::Awake` ruft `Application.set_targetFrameRate(30)`: das Spiel ist auf 30 fps ausgelegt.
- NPC: `FieldCharacterEntity::OnUpdate` (0x017885E0) -> `AnimationPlayer::AdvanaceTime(deltaTime)` (0x0211EEA0): Überblendung `weight += _increase * dt`, also zeitbasiert. Im verwalteten Code (Assembly-CSharp) gibt es keinen Frame-Zähler für NPC oder Wasser, kein `Time.frameCount`, keine pro Frame addierte Konstante.
- Folgerung: Die pro Frame fortgeschriebene Größe liegt in der Unity-Engine (Playables/Animator, Shader-Zeit `_Time`), nicht in Spielskripten. Eine eindeutige Konstante für einen env-gesteuerten Fix ist nicht gefunden.
- Offene Prüfungen: mit `BDSP_IL2SYM` den Aufrufer der Engine-Zeit (`Time.deltaTime`-Icall, Zeitmanager) im Lauf bei 30 und 120 fps vergleichen; Update-Modus der PlayableGraphs prüfen (GameTime oder DSPClock).
