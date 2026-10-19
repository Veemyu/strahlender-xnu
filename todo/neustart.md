# Neustart: Todos, Kurzstand, Fundstellen

Stand: 2026-10-19 17:30. Zweck: an einem anderen Zeitpunkt ohne Gesprächsverlauf weitermachen. Ausführlich: `docs/arbeitsstand-2026-10-19.md` (Technik, Messwerte) und `docs/betriebshandbuch.md` (Regeln, Befehle, Spielstand-Verteilung, unbelegte Annahmen).

## 1. Kurzstand

- **Ziel:** Mit diesem Repo, einer eigenen NSP/XCI von Pokémon Brilliant Diamond und eigenen Keys lässt sich ein natives Spiel für macOS und iPadOS bauen (später Linux/Windows mit Vulkan). Das Repo enthält keine Spieldaten, Keys, Saves, Screenshots oder erzeugten Code. Ton bleibt aus.
- **Strategie:** Ein Strang, die **statische Rekompilation** des Original-ARM64-Codes (LAS-Methode) mit eigener Laufzeit `scripts/recomp/rt-bdsp/`. Der Unity-Rebuild ist deprecated (Entscheidung 4, `unity/DEPRECATED.md`) und wird nicht weiterentwickelt.
- **Läuft:** Mac (Metal) mit Film, Titel, Spielstand und 3D-Stadt bei ca. 46 Bildern/s; iPad (`dev.local.xnubdsp`) bei 50–52 Bildern/s, 1,6–2,1 GiB Footprint; Linux/Vulkan bis zur Sprachauswahl. Der Eröffnungsfilm (VP8 über FFmpeg) läuft stabil.
- **Falsch oder offen:** Wasser (weiß statt blau), Spielbetrieb auf dem iPad ungetestet (Menü, Kampf, Speichern, Dauerlauf), Touch/Controller nur gebaut.
- **Bewusst nicht verfolgt:** der seltene Startstillstand auf dem iPad (0–40 Bilder). Entscheidung des Nutzers (2026-10-19, nachmittags): keine Wiederholungsschleifen mehr.
- **Git:** alles committet und gepusht (zuletzt `164d43c`); nur Nutzer-Identität, kein Co-Author-Trailer.

## 2. Todos (Reihenfolge = Vorschlag)

Auch in der Session-SQL mit Präfix `rc-`; bei Verlust gilt diese Liste.

| # | ID | Aufgabe | Ausgang / Erledigt wenn |
|---|---|---|---|
| 1 | `rc-water` | **Wasser in Metal beheben.** Shader `Delphis/WaterSimulation/WaterSurface` liefert das weiße Wasser; die Simulationstextur (512×512, RG8) war in Abzügen komplett 0. Abzug nach `renderer_flush()` wiederholen, prüfen, ob sie wirklich nie beschrieben wird (Load/Store, Reihenfolge der Durchgänge). | Region-Mittel ≈ RGB 87/127/210, Streuung ≈ 26/17/25 (`docs/wasser.md`, Referenz `work/visual/ref/ryujinx/views/free_wasser_a/b.png`) |
| 2 | `rc-ipad-rebuild` | **iPad-App neu aus dem Repo bauen und installieren** (die installierte stammt aus einem Gegenversuch). Kurzer Lauf zur Kontrolle, keine Schleifen. | `deploy_ios.sh build && install`, Lauf mit Film, Titel, Stadt |
| 3 | `rc-qa-scenarios` | **QA-Szenarien vervollständigen:** `menue` mit Speichern, `speichern_laden`, `wildkampf`, `laufen_stadt` wiederholen, 30-Minuten-Dauerlauf auf Mac und iPad (Speicher: 1,98 GiB im 32-Bit-Modell). | Berichte in `work/recomp/qa/`, Fehlerliste in `docs/recomp-qa.md` |
| 4 | `rc-input-ipad` | **Touch-Gamepad, Controller, Tastatur** auf dem iPad von Hand testen (Nutzer). | Rückmeldung des Nutzers |
| 5 | `rc-game-clock` | **Spieluhr fest vorgeben**, damit die Beleuchtung reproduzierbar ist (folgt sonst der Rechneruhr); Referenz-Spielstunde ≈ 12. | Bildvergleich mit Ryujinx wird belastbar |
| 6 | `rc-vulkan-repeat` | **Linux/Vulkan-Lauf** mit Film und Spielstand wiederholen; Mac-Fixes (Ringpuffer für Vertex-/Indexdaten, Crop 1280×720 in 1920×1080) übertragen. | Lauf auf dem Ryzen zeigt Stadt |
| 7 | `rc-build-stage` | **Stufe `recomp-ios`** in `scripts/build_all.sh`/`build_stages.py` ergänzen; Unity-Stufen aus dem Standardlauf nehmen. | Ein-Befehl-Bau (Kernziel `docs/kernziel.md`) |
| 8 | `rc-todo-rework` | Die **19 blockierten Unity-Todos** für die Rekompilation neu zuschneiden (Auflösung/Bildrate, Packaging/Import, Save-Import, Einstellungsmenü). | Neue Todos oder gestrichen |
| 9 | `rc-minor-findings` | Kleinbefunde: 29× `[tex] type mismatch` je Lauf, `[texdump]` gibt falsche Größe aus, 4 unbehandelte IPC-Befehle. | Geprüft, kein sichtbarer Einfluss oder behoben |
| 10 | `rc-user-refs` | **Mehr Ryujinx-Referenzen** (Nutzer): F8 am Titelbild und im X-Menü; Freigabe für Bewegungs-/Menütasten über `ryzen_keys.py`. | Neue Bilder unter `~/.config/Ryujinx/screenshots/` auf dem Ryzen |
| 11 | `rc-legal` | **Rechtslage** vor einer öffentlichen Weitergabe klären. | Entscheidung des Nutzers |
| 12 | `rc-signature` | iPad-Signatur des kostenlosen Teams läuft nach **7 Tagen** ab: neu signieren und installieren. | App startet |

Niedrige Priorität: Startstillstand (siehe oben), HEVC/VideoToolbox (nur falls der Software-Decoder je die Bildrate drückt, `docs/recomp-ios.md` 4.4), 3,14 GiB statt 1,98 GiB Gastspeicher (erst nach Dauer- und Kampftest relevant), MetalFX.

## 3. Arbeitsweise (Kurzfassung, vollständig im Betriebshandbuch)

Kein sudo, kein Plattenscan, kein Ton. Repo-Dateien nur mit `edit`/`create`. Prozesse nur mit `kill <PID>`. Kein Spiel-/Key-/Save-Inhalt im Repo. Commit nur als Veemyu, ohne Co-Author, danach pushen; `scripts/repo_check.py` läuft als Hook. Kleine Aufgaben an `claude-haiku-5.5`/`gpt-6-luna`, Code und Fehlersuche an Sonnet, höchstens zwei große Agenten, Agenten committen nie.

## 4. Fundstellen

| Thema | Wo |
|---|---|
| Einstieg, Index aller Dokumente | `docs/README.md` |
| Gesamtstand, Entscheidungen 1–4 | `docs/arbeitsstand-2026-10-19.md`, `docs/architektur-entscheidung.md`, `docs/kernziel.md` |
| Regeln, Befehle, Spielstand, Annahmen | `docs/betriebshandbuch.md` |
| Rekompilation (Verlauf) | `docs/recomp-machbarkeit.md` → `recomp-spike-2.md` → `recomp-gate1.md` → `recomp-gate2.md` |
| Mac-App, iPad, QA | `docs/recomp-macapp.md`, `docs/recomp-ios.md`, `docs/recomp-qa.md` |
| Vulkan, Ryzen-Farm, Bitgenauigkeit | `docs/recomp-vulkan.md`, `docs/recomp-ryzen.md`, `docs/recomp-diff.md` |
| Wasser, Shader, Texturen, Video | `docs/wasser.md`, `docs/shader-translator.md`, `docs/ios-texturen.md`, `docs/video-umwandlung.md` |
| Bildvergleich mit Ryujinx | `docs/visuelle-pruefung.md`, `scripts/visual_auto.sh`, `scripts/visual_compare.py` |
| Extraktion, Daten, Saves | `docs/extraktion.md`, `docs/daten-inventar.md`, `docs/save-format.md`, `docs/save-kompatibilitaet.md` |
| Laufzeit-Quellen | `scripts/recomp/rt-bdsp/` (`kernel.c`, `ipc.c`, `services*.c`, `loader.c`, `main.c`), NVN/Metal `scripts/recomp/rt-bdsp/nvn/`, Vulkan `…/nvn/vulkan/` |
| iPad-Bau und Deploy | `scripts/recomp/ios/` (`deploy_ios.sh`, `gen32.sh`, `build_rt32.sh`, `app/`) |
| QA-Harness | `scripts/recomp/qa/` (`qa_run.sh`, `scenarios/`) |
| Ryzen-Farm | `scripts/recomp/ryzen/`, Zugang `ssh nobara`, nur `~/xnu-recomp` |
| Spielstand-Werkzeuge | `scripts/ryujinx_sync_save.sh`, `scripts/ios_push_save.sh`, `scripts/recomp/rt-bdsp/install_save.sh` |
| Unity (deprecated, nur Referenz) | `unity/DEPRECATED.md`, `docs/unity-autopilot.md`, `scripts/unity_safe.sh` |
| Spezifikationen des Originalverhaltens | `docs/kampf-spezifikation-1…7.md`, `docs/pokepara-spezifikation.md`, `docs/evscript-spezifikation.md`, `docs/ui-spezifikation-1…3.md` |

**Lokal, nie im Repo:** `work/` (Dumps, Generat, Builds, Logs unter `work/builds/`, Bilder unter `work/visual/`, QA-Läufe unter `work/recomp/qa/`, Spielstand-Archive `work/save-archive/`), `tools/`, `research/` (Fremdklone, u. a. LASRecomp), `nsp/`, `Ryujinx/`, `Ryujinx_July23/`, `cache/`, `work/local.env` (Team-ID). Außerhalb des Repos: Sitzungs-Checkpoints unter `~/.copilot/session-state/`.

## 5. Wiederaufnahme in fünf Schritten

1. `git status`, `git log -3`, `git log origin/main -1`: alles gepusht? Läuft noch ein Prozess (`ps`, nur eigene PIDs)? Mac-Platz prüfen (mindestens 15 GB frei).
2. `docs/README.md`, `docs/arbeitsstand-2026-10-19.md`, `docs/betriebshandbuch.md` lesen, dann diese Liste.
3. Mit Todo 1 (Wasser) beginnen oder die Reihenfolge mit dem Nutzer neu abstimmen.
4. Nach jeder Änderung: `python3 -m unittest discover -s scripts/tests`, `python3 scripts/repo_check.py`, gezielt `git add`, committen, pushen.
5. Danach diese Datei und, wenn sich Technik oder Messwerte ändern, den Arbeitsstand aktualisieren.
