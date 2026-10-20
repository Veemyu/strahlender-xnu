# Vertikaler Durchstich: Titel → Weiter → Feld → Ereignis → Kampf → Speichern (Todo `ap-vertical-slice`)

> **Historisch (Stand 2026-10-20):** Unity-Weg, eingestellt. `scripts/ios_deploy.sh` ist auf `main` entfernt (nur Branch `unity`).

Stand: 2026-10-19, Messung im Haupteditor (Unity 6000.3.26f1, Metal) und im macOS-Player. Nur Namen, Zahlen und Struktur; keine Spieltexte, keine echten Saves, keine Bilder im Repo (Bilder und Logs liegen unter `work/`, gitignoriert).
Prüfstufen wie in `docs/spielkern-1.md`: **[A]** Annahme, **[P]** belegt. Kein Ton (AudioSafety unverändert).

## 1. Ergebnis in Kürze

Ein Durchlauf **ohne Hand-Eingabe** läuft im Editor und im macOS-Player bis zum Ende (Eingabeskript `work/vslice/run4.txt`, ca. 100 s Echtzeit, 1.215 Logikticks):

| Schritt | Ergebnis (Player-Lauf) |
|---|---|
| Boot → Szene `Game` (`-xnuScene Game`) | Titelbild mit „Weiter“ |
| „Weiter“ | Stammdaten 2,2–2,6 s (707 Trainer, 183 Zonen mit Begegnungen, 119 Textdateien + `msg_common`, 856 Skriptdateien, 12.985 Labels, 709 Trainer- und 659 Zonennamen); Spielstand aus dem lokalen Ryujinx-Save importiert (979.108 Byte, Quelle nur gelesen) |
| Feld | Zone 167 an der gespeicherten Position (Zelle (842, 597), Team 6, Geld 45.156, 8 Abzeichen), Feld nach 1,8 s |
| Gehen | Spieler läuft 4 Zellen (30 Hz-Gitterbewegung), geht durch die Tür: **Zonenwechsel 167 → 168** (Pokécenter innen, anderes Kartenbundle, Überblendung) |
| Sprechen | `nearnpc` + A: `GameEvHost` startet `ev_c10pc0101_pcwoman1`; **4 Textfenster** mit den echten Meldungstexten (Original-Rahmen aus `sharedui`), **Ja/Nein-Auswahl**, danach die Heilungsanimation (5 Host-Aufrufe ohne Umsetzung, siehe Lücken) und Ende des Ereignisses (1 gestartet, 1 beendet) |
| Begegnung | `encounter` (erzwungen, Tabelle der Zone 168 leer → Ersatz Art 396, Stufe 3) → Zustand `Battle` |
| Kampf | Befehlsmenü (Kampf/Beutel/Pokémon/Flucht), Attackenwahl mit PP, 9 abgespielte Protokollschritte, Meldungen mit Namen aus `ss_monsname`/`ss_wazaname`, KP-Balken; Sieg, Rückkehr ins Feld |
| Speichern | Skriptbefehl `save` (im Spiel: Menü-Taste → „Speichern“): 979.108 Byte, Hash neu, Backup `Backups/main/<Zeitstempel>/SaveData.bin`; die Quelle (Ryujinx) blieb byte- und zeitgleich |

Bilder (nur lokal): `work/visual/vslice/` – `s*.png` und `v*.png` aus dem Editor, `p*.png` aus dem Player, `t*.png` Zwischenstände. Log: `work/builds/player.log`.

## 2. Aufbau

Neue Assembly **`Xnu.Game.Unity`** (`unity/Assets/Scripts/Game/Runtime`), Editor-Teil `Game/Editor` (Menü `Xnu/Game/Spielszene erzeugen`, Szene `Assets/Scenes/Game.unity`, in `BuildScript.DefaultScenes` hinter `Boot`; das Boot-Menü listet sie automatisch).

| Datei | Aufgabe |
|---|---|
| `GameDriver` | MonoBehaviour: Titel, Laden, 30-Hz-Takt (`LogicStep`), Eingabe (Geräte oder Skript) als `GameInput`-Daten, Textbrücke, Kampfansicht, Speichern, Skriptwelt (`IScriptWorld`) |
| `FieldHostAdapter` | `IFieldHost` + `IFieldInteractionHandler` + `IFieldFlags` für den `FieldController`: MAP_CHANGE → `BeginSwitchZone`, Ansprechen/Berühren → `FieldSignal`, Work-/Systemflags des Spielstands → Objektsichtbarkeit, Überblendung, Spielerposition |
| `BattleView` | uGUI: Infotafeln mit KP-Balken, Platzhalter-Kästen statt Modelle, Meldungsfenster, Menüs; spielt `BattleBeat`-Schritte, gibt den Spielerbefehl zurück; Ersatz nach Besiegt automatisch |
| `SaveSlotService`, `SavedPosition` | eigener Slot `main` im Save-Ordner der App (`-xnuSaveRoot`/`XNU_SAVE_ROOT`, sonst `persistentDataPath`, Slot unter `Saves/main`; seit `docs/ipad-durchstich-1.md` nur bei gültiger Datei, mit Ablage-Datei `SaveData.bin` im Documents-Ordner); Import der Quelle (`XNU_SAVE_SOURCE` oder `<GameData>/../Ryujinx/…/0`), Backup vor jedem Überschreiben |
| `GameDataLoader`, `GameBattleTexts` | Stammdaten, Texte (`msg_german` + `msg_common`), Namenstabellen; Namen und Originalmeldungen für den Kampf |
| `GameOptions` | `-xnuInputScript`/`XNU_SCRIPTED_INPUT`, `-xnuSaveSource`, `-xnuSaveRoot`, `-xnuShotDir`, `-xnuAutoContinue` |

Reine Logik in `Xnu.Game` (ohne UnityEngine): `BattlePresentation.cs` (`BattleLogPlayer`: Ereignisprotokoll → `BattleBeat`, mit KP-Nachführung) und `InputScript.cs` (Parser und Ablauf des Eingabeskripts).
Änderungen an Bestehendem (abwärtskompatibel): `FieldController` (`Flags`, `ExternalTick`/`LogicTickExternal`, `BeginSwitchZone`, `SetStartCell`, `ZoneChanged`, `RefreshNpcsNow`; Innenräume zeigen nur eigene Platzierungen), `GameInput` (`InputOverride`), `DialogModel.ForceFinish`, `ChoiceModel.Force`, `GameLoop.BeginBattle`, `HostCommands` (523), `scripts/field_zone_names.py` (schreibt zusätzlich `TrainerID`-Namen).

**Text:** Der Host öffnet ein Fenster im `DialogModel`; der Treiber zeigt es mit `TextboxView` (Schreibmaschine, Seiten, Ja/Nein) und meldet das Ende per `ForceFinish`/`Force` zurück. Während Textbox oder Auswahl offen sind, bekommt die Spielschleife keine Bestätigung. Namen und Variablen setzt `GameEvHost` über `TagWordBuffer` (Xnu.Text).
**Kampf-Text:** Originalmeldungen nur dort, wo Datei, Label und Platzhalterbelegung zuordenbar sind **[A]**: Begegnung (`BTL_STRID_STD_Encount_Wild1`), Erfahrung, Stufenanstieg, Flucht (`ss_btl_std`). Alles andere sind eigene Platzhaltertexte (Namen aus den echten Dateien).

## 3. Eingabeskript

Eine Anweisung je Zeile: `wait N`, `tap A|B|Plus|Up|Down|Left|Right`, `hold <Richtung> N`, `mash N`, `mashuntil <Zustand> N`, `waitstate <Zustand> N` (Titel, Loading, Field, Transition, Event, Textbox, Choice, Battle…), `fight S`, `starter I`, dazu Sonderbefehle des Treibers: `goto X Y DIR`, `nearnpc [Teil-ID]`, `encounter`, `shot NAME`, `save`, `report`, `state`, `log TEXT`, `quit`. Richtungen sind **Bildschirmrichtungen**; in Innenräumen und im Feld (Kamera-Gier 180) liegt „Up“ bei Zellrichtung gy−1.
Die Eingabe wirkt über `InputOverride` in `GameInput` (ohne Fokus, ohne Maus); `waitstate` mit Zeitlimit macht den Lauf von der Taktung unabhängig (Timeouts werden gezählt, hier 1 beim `Transition`-Fenster, das nur wenige Ticks sichtbar ist).

Reproduktion (Editor): Szene `Game` öffnen; per `unity command eval` `XNU_GAMEDATA` (=`<Repo>/work`), `XNU_SCRIPTED_INPUT`, `XNU_SHOT_DIR`, `XNU_ENV_HOUR` setzen; `editor_play`. Player: `scripts/build_all.sh --only assets --target macos --bundle-subset scripts/subsets/vslice-start.txt --min-free-gb 20` mit `ASSETS_DEST=<gitignorierter Ordner>` (182 MB, 788 Dateien, 4 s), Menü `Xnu/Build/macOS (arm64, IL2CPP)` (93 s, 972 MB), dann `xnu -xnuScene Game -logFile <Pfad>` mit denselben Umgebungsvariablen (`XNU_GAMEDATA` = Zielordner der Stufe `assets`; die Original-Bundles der Switch lädt der Player nicht, ohne `bundle_retarget` bricht das Feld mit „LoadFromFile lieferte null“ ab).

## 4. Zahlen

| Messgröße | Wert |
|---|---|
| EditMode-Tests | **688 von 688 grün** (645 vorher; 24 neue in `GameUnityTests`: Skript, Optionen, Protokoll-Player, Kampfansicht, Feld-Adapter, Spielstand-Slot, Treiber im EditMode; weitere von anderen Agenten) |
| Datenladen | 2,2–2,6 s (Editor), Feldstart 1,8 s (Player) |
| Skriptlauf Player | 1.215 Ticks = 40,5 s Logikzeit; real ca. 100 s wegen Laden und Bildaufnahmen |
| Bildrate Player | 27–30 FPS (Logik 30 Hz) |
| Ereignis Schwester | 4 Textfenster, 1 Auswahl, 5 Host-Lücken-Aufrufe, Dauer 497 Ticks (16,6 s) |
| Kampf | 9 Protokollschritte bis zum Ende, 1 Spielerbefehl |
| Save | 979.108 Byte, Hash gültig (Roundtrip im Test), Backup angelegt |

## 5. Gefundene und behobene Fehler auf dem Weg

- **Gespeicherter Ort liegt auf einer gesperrten Zelle:** `TownMapLocation` (Zone 167, Zelle (842, 597)) ist eine Kartenmarke vor der Pokécenter-Tür, kein Standort **[A]**; der Treiber nimmt die nächste begehbare Zelle ((840, 599)). Beim Speichern schreibt der eigene Slot Zone und Ort in dieselben Felder.
- **Innenräume zeigten NPC-Marker aller gleichartigen Räume** (gleiches Kartenbundle): `FieldController` nimmt jetzt nur die Platzierungen der eigenen Zone.
- **Textbox unsichtbar in Aufnahmen:** `Awake` baute sie als Overlay; der Treiber bindet sie an die Spielkamera.
- **Veraltete Bewegung:** `GameInput.Move` blieb zwischen Bildern stehen, wenn mehrere Logikticks pro Bild liefen (`InputOverride.Enabled`).
- **Heilung hing:** Befehl 523 (zählt die Bälle der Pokécenter-Animation bis zur Teamgröße) fehlte → Endlosschleife; jetzt als Teamgröße **[A]** umgesetzt.
- **Artnamen fehlten:** `ss_monsname` liegt in `msg_common`, nicht in `msg_german`.

## 6. Lücken (ehrlich)

- **Trainerkampf und Gras-Begegnung** sind im Code verdrahtet (`HostCommands`, `FieldSignal.Step`), im Durchlauf aber **nicht** ausgeführt (nur erzwungene Wildbegegnung). Zone 168 hat keine Begegnungstabelle (Ersatzart 396).
- **Kampf-UI minimal:** Platzhalter-Kästen statt Modellen und Sprites, kein Beutel (Hinweistext), kein Mehrfachkampf, Ersatz nach Besiegt automatisch, Meldungen größtenteils eigener Text, KP-Anzeige nur Balken und Zahl der eigenen Seite, keine Animation, keine Statusanzeige.
- **Feld:** NPCs stehen still (Marker, kein Modell); `SetObjectVisible/Grid`, Animationen (`AC_*`), Kamera- und Effektbefehle (`RunVisual`) sind Lücken (nur gezählt); Warps/Türen löst das Feld selbst aus, nicht über `FieldSignal.Warp`. Die Spielerfigur trägt im Player den Ersatz-Shader (grau).
- **Menü:** nur „Speichern“ und „Zurück“; Beutel, Team, Pokédex fehlen. „Neues Spiel“ fehlt (Titel sperrt es).
- **Spielstand-Ort** ist eine Annahme (siehe oben); die Zuordnung von Richtung 0/1 ist offen. Der Zeitstand (`PeriodOfDay`) kommt nicht aus der Uhr.
- **Heilungsanimation:** Befehle 977/978/765 (Bälle, Schwester) sind Lücken; 523 ist angenommen.
- **Drei Zustände im Skript sind flüchtig** (`Transition`), daher `waitstate` mit Zeitlimit.
- **iPad:** Build, Installation und Start gelungen, Durchlauf nicht abgeschlossen (siehe Abschnitt 7).

## 7. iPad (teilweise durchgeführt, nicht abgeschlossen)

**Aktualisiert (später am selben Tag):** Der Durchlauf läuft auf dem iPad ohne Hand-Eingabe bis zum Ende; Ursache von „Slot keiner“ (doppelter Ordner `Saves`, von `devicectl` angelegte Ordner mit Besitzer root), Verfahren zur Save-Übertragung (`scripts/ios_push_save.sh`) und Messwerte (Texturfehler 0, 30/60/120 FPS, Footprint ≤ 861 MiB) stehen in `docs/ipad-durchstich-1.md`. Der folgende Text ist der Stand vor der Behebung.

- **Erweitert:** `scripts/subsets/ipad-start.txt` um `Environments/fields/area008` und `Environments/prefab_map/t02pc0101` (7 Bundles). `scripts/build_all.sh --only assets --target ios --texture-format 6x6 --bundle-subset scripts/subsets/ipad-start.txt`: 789 Dateien, **229 MB** (vorher 179 MB), 31 s inklusive ASTC-Umwandlung.
- **Gebaut und installiert:** iOS-Build über das Menü (Zielwechsel des Haupteditors: 502–505 s, 1.107 MB), `scripts/ios_deploy.sh … --no-launch` 2 min 8 s.
- **Gestartet:** Die App startet mit `XNU_START_SCENE=Game` und `XNU_SCRIPTED_INPUT=run5.txt` (per `devicectl --environment-variables`; Argumente nach `--` kamen nicht an), das Skript wird gelesen. Der Durchlauf blieb am Titel stehen: **„Slot keiner“**, der Spielstand (per `devicectl device copy to` nach `Documents/Saves/main/SaveData.bin`) lag nach dem erneuten Installieren nicht im Container bzw. wurde nicht als Slot erkannt. Damit wurde das Feld auf dem iPad **nicht** geladen; **Texturfehler (vorher 1.884) und 60-s-Lauf sind nicht gemessen** (im Log 0 Fehlermeldungen, aber ohne geladene Karte nicht aussagekräftig). 60 FPS im Titel.
- Offen: Spielstand-Kopie in den Container (Pfad `Documents/Saves/main` prüfen, Datei nach dem Installieren kopieren), Lauf wiederholen und Texturfehler zählen. Die iPad-Zeit reichte nicht (Build 2 × 8,5 min wegen Zielwechsel).

## 8. Nächste Schritte

1. Trainerkampf im Durchlauf (ein Trainer mit Sichtfeld, `TRAINER_BTL_SET`) und Gras-Begegnung mit Schrittprüfung messen.
2. Charakter-Materialien exportieren (Figur, NPCs), NPCs als Modelle mit Laufmustern.
3. Kampf: Beutel, Pokémon-Wechsel mit Anzeige, Statuszeichen, Modelle aus den Bundles, Original-Layout aus `ui_masterdatas`.
4. Menüinhalte (Beutel, Team, Karte) und „Neues Spiel“ (`FIRST_POKE_SELECT`).
5. Original-Position im Spielstand klären (`SetPlayerPosData`), danach `SavedPosition` anpassen.
6. iPad: ASTC-Teilmenge bauen, Deploy, Texturfehler zählen.
