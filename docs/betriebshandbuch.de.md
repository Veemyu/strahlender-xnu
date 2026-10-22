# Betriebshandbuch (Wiederaufnahme ohne Gesprächsverlauf)

Stand: 2026-10-19 17:20. Ergänzt `docs/arbeitsstand-2026-10-19.md` (Technik, Messwerte, Entscheidungen). Dieses Dokument hält fest, was **nicht** in den Technikdokumenten steht: Arbeitsregeln, Befehle, Spielstand-Verteilung, Agenten- und Todo-Stand, unbelegte Annahmen und die Reihenfolge nach einem Neustart der Sitzung.

## 1. Arbeitsregeln des Nutzers (gelten dauerhaft für dieses Projekt)

| Bereich | Regel |
|---|---|
| Rechte | Kein `sudo`, keine Umgehungen. Was Admin-Rechte braucht, wird als Installationsliste an den Nutzer gegeben. Plattenscan verboten (nur Repo und bekannte Ordner anfassen). |
| Ton | Früher verboten, jetzt freigegeben (Nutzer, 2026-10-19): Ton wird erforscht und darf umgesetzt und getestet werden (Todo `rc-audio`). Bis dahin sind die Audiodienste stumme Stummel. |
| Git | Commit nur mit der Identität des Nutzers (`Veemyu`), **kein Co-Author-Trailer**, nach jedem Commit `git push` (origin/main). Der Pre-Commit-Hook führt `scripts/repo_check.py` aus. Nur gezielt `git add <Datei>`, nie `-A`. |
| Repo-Inhalt | Nie Spieldaten, Keys, Dumps, erzeugten Code, Saves, Screenshots, Team-ID. Erzeugtes C und Binaries bleiben unter `work/`. Fremdprojekte nur als Klon in `research/` (gitignored), Zusammenfassungen in eigenen Worten, maschinell übersetzter Spielcode wird nie committet. Team-ID nur in `work/local.env`. |
| Dateien ändern | Repo-Dateien nur mit `edit`/`create`, nicht per `sed -i`, Heredoc oder Python-Schreibskript. Prozesse nur mit `kill <PID>` beenden, kein `pkill`/`killall`. Lange Läufe: `nohup`/`setsid` mit Logdatei. |
| Sprache | Dokumente und Antworten auf Deutsch, UTF-8 mit ä ö ü ß (keine Umschreibung). Code-Kommentare kurz, nur wo nötig. Antworten kurz. |
| Modelle | Nicht mit Kanonen auf Spatzen schießen: kleine Aufgaben (Läufe, Messungen, Sichtung, Doku) an `claude-haiku-5.5` oder `gpt-6-luna`; Fehlersuche und zentraler Code an Sonnet. Höchstens zwei große Agenten gleichzeitig. Agenten committen nie. |
| Platz | Mac: mindestens 15 GB frei halten (zuletzt ca. 36 GB). Bei weniger stoppen und melden. |
| Strategie | Unity-Rebuild ist deprecated (Entscheidung 4, `unity/DEPRECATED.md`): keine weitere Arbeit, nur Referenz. Es gibt einen Strang, die Rekompilation. Nicht drei Dinge parallel entwickeln. |
| Linux-Rechner | Nicht mehr an diesen Arbeitsablauf angebunden. Linux-Builds laufen nur lokal auf einem Linux-Rechner, vom Repo-Wurzelverzeichnis aus (`scripts/recomp/linux/local/`). |

## 2. Befehls-Spickzettel (aus den Kopfzeilen der Skripte, Stand geprüft)

macOS-Werkzeuge sind BSD-Varianten (`ls --time-style` und GNU-Optionen fehlen). Xcode über `DEVELOPER_DIR`.

| Zweck | Befehl |
|---|---|
| Repo-Prüfung und Tests | `python3 scripts/repo_check.py` · `python3 -m unittest discover -s scripts/tests` (zuletzt 358–370 grün) |
| Gesamtbau (Stufen) | `scripts/build_all.sh` (Stufen in `scripts/build_stages.py`; Unity-Stufen sind deprecated, Stufe `recomp-ios` fehlt noch) |
| Mac, headless | `work/recomp/bdsp_boot --headless --save <Ordner> --timeout S --input-script "Sek:TASTE:Dauer,…" --screenshot-after N` (Bilder nach `BDSP_SHOT_DIR`); Symbole mit `BDSP_IL2SYM`/`work/recomp/il2sym.tsv` |
| Mac-App | `work/builds/macos-recomp/BDSP.app` (`docs/recomp-macapp.md`) |
| Spielstand in die Laufzeit | `scripts/recomp/rt-bdsp/install_save.sh` (Quelle `BDSP_SAVE_SRC`, optional `BDSP_SAVE_EXTRA`, Ziel `work/recomp/save`) |
| iPad bauen/starten | `scripts/recomp/ios/deploy_ios.sh build|install|run [Sek]|data|save|shots|files`; Lauf-Umgebung per `RUN_ENV='{"BDSP_TIMEOUT":"40","BDSP_BT":"1","BDSP_WAIT":"1"}'`; Logs `work/builds/ipad-recomp-<Zeit>.log` (`docs/recomp-ios.md` Abschnitt 6) |
| iPad-Spielstand | `scripts/ios_push_save.sh [--source DATEI] [--reimport] [--dry-run]` |
| QA-Szenarien | `scripts/recomp/qa/qa_run.sh <szenario>|--list|--report <ordner>` (Sperrdatei, Spielstand-Kopie aus `work/recomp/qa/save_base`) |
| Unity (deprecated, nur falls je wieder nötig) | `scripts/unity_safe.sh open|restart|status|test|watch` liegt nur auf Branch `unity` (auf `main` fehlt es; `visual_auto.sh` braucht es für den Editor-Start); Tests nie im Play-Modus (hängt), vorher `editor_stop` |

Bekannte Laufzeit-Hilfsvariablen: `BDSP_TIMEOUT`, `BDSP_BT` (Rückverfolgung), `BDSP_WAIT` (Warteberichte), `BDSP_WATCH`, `BDSP_ALIAS_BASE/SIZE`, `BDSP_APPMEM`, `BDSP_SHOT_DIR`, `BDSP_SCREENSHOT_*`.

## 3. Standard-Testspielstand und Verteilung

- **Inhalt:** Ryujinx-Spielstand des Nutzers von 2026-10-19: Stadt in Zone 24 (Fleetburg-Gegend), Spielzeit 69:08:16, 79.996 Geld, 179 Gegenstände, gleiche Trainer-ID. SaveData sha256 beginnt mit `0396a4a62735`, Backup `7a324b865ea9`. Stand vor der Siegesstraße ist archiviert unter `work/save-archive/`.
- **Position:** `PLAYER_DATA` bei 0x79BF4/0x79BF8 = Gitterzelle (57, 729); `zoneID` bei 0x5634 = 24; `TownMapLocation` ist veraltet (Zone 416, nicht verwenden). Nächste Übereinstimmung mit dem Ryujinx-Bild: Zelle (58, 729), aber nur ein Bild als Beleg.
- **Installiert in** (jeweils mit Sicherung des alten Stands):

| Ziel | Pfad |
|---|---|
| Mac Ryujinx-Ordner | `Ryujinx/bis/user/save/0000000000000006/{0,1}` |
| Rekompilation Mac | `work/recomp/save/save_1` (über `install_save.sh`) |
| iPad | `Documents/SaveData.bin` (Ablage; wird beim nächsten „Weiter“ nach `Documents/Saves/save_1` importiert, Sicherung unter `work/ipad-save-backup/`) |
| Unity-Editor (deprecated) | `~/Library/Application Support/DefaultCompany/xnu/Saves/Saves/main` |

- **Falle, die schon einmal zuschlug:** Ryujinx legt je Profil einen eigenen Ordner an. Lag der Spielstand im Ordner `…04`, das aktive Profil las aber `…0e`, erschien „Select the language“. Den Profilordner wählt man jetzt von Hand. Die Benutzer-ID steht in `ExtraData0` (Bytes 8–23, jede 8-Byte-Hälfte byteweise umgedreht).
- Mit Spielstand überspringt das Spiel die Sprachauswahl: Titel nach ca. 22 s, „Weiter“, Stadt nach ca. 91 s.

## 4. Stand der Agenten, offene Arbeit, Todos (Session-Daten, nicht im Repo)

**Laufend (beide Sonnet, harte Endzeit 19:00):**
- `ap-recomp-qa`: Testharness `scripts/recomp/qa/`, `docs/recomp-qa.md`. Priorität 1 Wasser (Metal), danach Pokécenter-Innenraum (einfarbig blau mit dunklen Streifen). Verdacht: Render-Target-Texturen `_OpaqueDepthTexture`/`_ReflectionTex` werden im Metal-Pfad falsch gelesen.
- `ap-recomp-ios`: `scripts/recomp/ios/`, `docs/recomp-ios.md`. Reproduktion des seltenen Startstillstands: Schleife über bis zu 8 Läufe mit `BDSP_TIMEOUT=40`, Abbruch mit „HANG“, wenn das letzte Metal-Bild unter 600 liegt (um 17:12 waren 22 Läufe im Log, keiner mit Absturzsignal, zwei ohne Filmstart). Bereits behoben: Selbstverklemmung in `block_current` (`kernel.c`), Audio-Endlosschleife (`services_audio.c`). Das iPad muss dabei entsperrt bleiben.
- Alle weiteren Agenten (ca. 55) sind inaktiv. Das Modell der `ap-recomp-*`-Agenten ist der Standard der Umgebung (vermutlich Sonnet, nicht geprüft).

**Nicht committet (gehört den laufenden Agenten, erst nach deren Bericht prüfen):** `scripts/recomp/ios/`, `scripts/recomp/qa/`, `docs/recomp-ios.md`, `docs/recomp-qa.md`, Änderungen an `rt-bdsp/kernel.c`, `rt-bdsp/nvn/nvn_glue.c`, `rt-bdsp/services_audio.c`, `rt32/cpu.h`. Ablauf: Bericht lesen, Tests und `repo_check.py` laufen lassen, Dateien einzeln `git add`, committen (nur Nutzer-Identität), pushen.

**Todos (SQL der Sitzung, bei Verlust hier rekonstruierbar):**
- Erledigt: 43 (Extraktion, Analyse, Unity-Slices, Rekompilation Gate 1/2, Bildprüfung).
- Blockiert wegen Unity-Stilllegung (19): `ap-audio`, `ap-battle`, `ap-cutscenes-video`, `ap-effects-fidelity`, `ap-field`, `ap-ipad-perf`, `ap-localization`, `ap-packaging`, `ap-qa-ci`, `ap-resolution-framerate`, `ap-save-compat`, `ap-save-io`, `ap-settings-ui`, `ap-shaders`, `ap-ui`, `todo-ai`, `todo-astc`, `todo-host-cmds`, `todo-ui-screens`. Sie müssen für die Rekompilation neu zugeschnitten werden, falls noch relevant (Teile wie Auflösung/Bildrate, Packaging, Save-Import entstehen dort neu).
- `ap-build-all` (läuft weiter, Ziel: Ein-Befehl-Bau, jetzt mit Stufe `recomp`/`recomp-ios`). `ap-shader-unity` und `ryzen-optional` waren veraltet und sind als erledigt/blockiert markiert.

## 5. Unbelegtes und Annahmen (nicht als Tatsache weitergeben)

- **Entscheidung des Nutzers (2026-10-19, nachmittags): keine Wiederholungsläufe mehr.** Der frühere Absturz kam vom VP8-Film, der läuft seit langem stabil. Den seltenen Startstillstand (0–40 Bilder, in den letzten Läufen ca. 4 von 9) jagen wir nicht weiter, er ist ein Randfall mit niedriger Priorität. Kein Agent startet dafür Schleifen auf dem iPad. Nur wieder aufnehmen, wenn er im echten Spielbetrieb stört.
- Der **iPad-Absturz bei nicht übersprungenem Intro** ist nicht reproduziert; die Selbstverklemmung ist die belegte, aber nicht bewiesene Ursache. Ein einzelner Stillstand (2 Bilder) nach der Korrektur ist ungeklärt.
- **32-Bit-Modell (`rebase32`) auf dem Gerät:** läuft laut `recomp-ios.md`, aber nur 1,98 GiB statt 3,14 GiB Gastspeicher; Langzeit und Kämpfe ungemessen.
- **Bildvergleich:** Kameraversatz 28 px (vermutlich Timing), Zellenzuordnung (58,729) aus einem Bild, Zuordnung der Spieluhr zur Tageszeit in Ryujinx angenommen.
- **FPSR/QC-Flags** der ARM64-Gleitkomma-Einheit sind nicht modelliert (`recomp-diff.md`).
- **Vulkan/Linux:** Lauf mit Film und Spielstand nicht wiederholt; die Mac-Fixes (Ringpuffer für Vertex-/Indexdaten, Crop 1280×720 in 1920×1080) sind nicht überall übertragen. Gemeinsame Include-Zeilen in `nvn_glue.c` wurden aus dem `__APPLE__`-Block gezogen (Bau auf dem Linux-Rechner scheiterte vorher).
- **Wasser-Ursache** ist eine Hypothese; Zielwerte der Region: Mittel RGB ≈ 87/127/210, Streuung ≈ 26/17/25, ≈ 0,3 % sehr helle Pixel (`docs/wasser.md`).
- **Rechtslage** für eine öffentliche Weitergabe ist offen. opendpr verbietet generative KI: nur Referenz, kein Code übernommen. LASRecomp ist MIT (Hinweise in `shader_translator/NOTICE.md`).
- Free-Team-Signatur der iPad-App läuft nach 7 Tagen ab; nur drei Apps mit kostenlosem Profil erlaubt (Messsonde wurde deshalb entfernt).

## 6. Verlauf in Kürze

1. 2026-10-18: Setup, Extraktion (Titel `0100000011d90000`, Update `…800`, Master-Key-Rev 0xC), Ghidra (166.095 Funktionen), Il2CppDumper, Save-Spec, Weg D (Unity 6.3) beschlossen.
2. Unity-Rebuild mit Emulations-Orakel (763 Tests grün), Shader-Übersetzer, Player-Builds für macOS und iPad.
3. 2026-10-19: Rekompilations-Spike, Gate 1 (Boot bis NVN), Gate 2 (Metal zeichnet, Film, Eingabe, Stadt mit 45 Bildern/s), Vulkan, bitgenauer Differenztest, Linux-Rechner (zeitweise Build-/Testhilfe), Bildprüfung gegen Ryujinx.
4. Nutzerbeobachtungen auf dem iPad: „sieht super aus“; Wasser falsch; Start brauchte 2–3 Versuche; Absturz, wenn das Intro nicht sofort mit A übersprungen wird. Das Intro-Video läuft per VP8-Software-Decoder (FFmpeg, `movie::`-HLE).
5. Entscheidung 4 (16:57): Unity deprecated. Seitdem arbeiten zwei Agenten (QA/Wasser, iPad).

## 7. Reihenfolge nach einem Neustart der Sitzung

1. `git status`, `git log -3`, `git log origin/main -1`: ist alles gepusht?
2. `docs/README.md` und `docs/arbeitsstand-2026-10-19.md` lesen, dann dieses Handbuch.
3. Berichte von `ap-recomp-qa` und `ap-recomp-ios` abholen (Agentenliste); bei fehlenden Berichten die Dateien in Abschnitt 4 prüfen.
4. Prüfen, ob noch ein iPad-Lauf läuft (`ps`, nur eigene PIDs beenden).
5. Tests, `repo_check.py`, gezieltes `git add`, Commit, Push.
6. Danach Abschnitt 8 des Arbeitsstands abarbeiten (Wasser, Innenraum, iPad-Start, QA-Szenarien, Touch/Controller, Vulkan-Lauf, Stufe `recomp-ios`).

Außerhalb des Repos liegen nur: Sitzungs-Checkpoints (`~/.copilot/session-state/…/checkpoints/`), die Todo-Tabelle der Sitzung und gespeicherte Memories. Alles Übrige steht in `docs/`.
