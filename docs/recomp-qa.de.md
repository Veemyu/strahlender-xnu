# Rekompilation, Qualitätssicherung (`ap-recomp-qa`)

Stand: 2026-10-19, Zwischenstand (wird nach jedem Szenario fortgeschrieben). Grundlage: `docs/recomp-gate2.md`, `docs/architektur-entscheidung.md` (Entscheidung 3: Rekompilation ist Hauptweg), `docs/visuelle-pruefung.md`. Auftrag: die rekompilierte Laufzeit (`work/recomp/bdsp_boot`, Metal, headless) systematisch testen, Fehler finden und beheben, Bild gegen die Ryujinx-Referenz messen. **Kein Ton** (die Audiodienste sind stumm), keine Spielbytes, Saves oder Screenshots im Repo (alles unter `work/recomp/qa/`).

**Kennzeichnung:** **gemessen** = in den Läufen unter `work/recomp/qa/<lauf>/` ermittelt; *vermutet* = Schluss ohne Test. **Messbedingung:** M1 Pro, 16 GB. Während der Läufe baute und testete ein anderer Agent parallel (Last des Macs im Mittel 25 bis 55, zeitweise lief eine zweite Spielinstanz); **Bildraten dieser Läufe sind deshalb nicht aussagekräftig** (Abschnitt Dauerlauf). Jeder Bericht enthält Last und Prozess-CPU.

## Harness (`scripts/recomp/qa/`)

| Datei | Inhalt |
|---|---|
| `qa_run.sh <szenario>` | Einstieg: `qa_run.sh --list`, `qa_run.sh <szenario> [--bin PFAD] [--img ORDNER] [--no-il2sym] [--timeout S] [--label TEXT]`, `qa_run.sh --report <lauf>` (Bericht neu erzeugen). Exit-Code 0 bestanden, 1 Prüfung gescheitert, 2 Aufruffehler, 3 Platte < 15 GB. Es läuft nur ein Lauf zugleich (Sperrdatei). |
| `qa_run.py` | Szenario laden, `bdsp_boot --headless` starten, RSS/CPU/Last alle 2 s messen, Eingaben einspeisen, Log auswerten, `report.md` und `report.json` schreiben, Kontaktbögen der Screenshots erzeugen |
| `scenarios/*.txt` | Szenarien (Syntax im Kopf von `qa_run.py`); Namen mit `_` sind Hilfsdateien oder Erkundungen |
| `patches/` | Vorschläge für Änderungen an Dateien, die andere Agenten gerade bearbeiten |

**Ablauf eines Laufs:** (1) Der Ausgangsspielstand `work/recomp/qa/save_base` (Stadt-Spielstand, `SaveData.bin` sha256 `0396a4a62735…`) wird je Lauf kopiert; der Ausgangsstand bleibt unverändert. (2) `bdsp_boot --headless --save <Lauf>/save --screenshot-after N --input-script …` mit `BDSP_IL2SYM` (jede Spielmethode beim ersten Aufruf mit Namen im Log), `BDSP_BT=1`, `BDSP_TRACE_SYNC=300`, `BDSP_DUMP=7004f91f60:24` (Wartezustände, Mutex-Besitzer, Synchronisationsfolge und Ereigniszustand im Bericht; kostet nur beim Beenden). (3) Auswertung.

**Eingaben, ereignisgesteuert.** Das Eingabeskript der Laufzeit (`--input-script "Sekunde:TASTE:Dauer"`) rechnet ab Prozessstart. Die Ladezeit bis zum Titel schwankt aber von 31 s bis über 120 s (Fremdlast, Shader-Cache, Platte), absolute Zeiten treffen deshalb nicht. Das Harness kennt **Anker** (`anchor feld EvDataManager::EnvironmentControllerCallBack`): Zeit des ersten Aufrufs einer Spielmethode (aus dem IL2CPP-Namensprotokoll); Eingaben stehen dann als `feld+12 UP 2.0` im Szenario. Es schreibt die Tastenmaske in eine Steuerdatei (`BDSP_INPUT_CTL`, neu in `nvn_glue.c`, wird bei jeder Npad-Abfrage gelesen und mit Skript und Tastatur verodert). `finish <s>` beendet den Lauf (SIGINT, die Laufzeit schreibt den Bericht) so viele Sekunden nach der letzten Eingabe, das Zeitlimit bleibt nur Sicherung. Das Skript der Laufzeit kann jetzt bis 8.192 Schritte haben und per `@datei` geladen werden (Dauerlauf).

**Was der Bericht prüft (immer):** Absturz (Exit-Code, `*** Signal`, `FATAL`, fehlender Ergebnisbericht, Harness-Abbruch) mit Host-Rückverfolgung und **letztem Gast-Stack, symbolisiert mit IL2CPP-Namen** (`il2sym.tsv`) und den zuletzt erstmals aufgerufenen Spielmethoden; **Bildstillstand** (> 12 s ohne Bild) mit Thread-Zuständen, Mutex-Besitzern, Synchronisationsfolge und Gastspeicher; **unbehandelte IPC-Befehle** (Dienst:Befehl, Häufigkeit), nicht umgesetzte SVCs, NVN-Funktionen ohne Host-Umsetzung; auffällige Logzeilen (`unimplemented`, `nicht umgesetzt`, `failed`, `mismatch`, …) nach Muster gezählt; Bildrate (Median, p5, Minimum) und RSS-Verlauf; Screenshots (schwarz, unverändert zum Vorgänger); Spielstand (`bdsp_save.py check`, geändert?). Je Szenario kommen `expect`-Prüfungen dazu.

## Szenarien

Stand beim Abbruch auf Wunsch des Nutzers (2026-10-19, ca. 17:25, vorzeitig statt 19:00). **Es wurden nur die ersten Szenarien kalibriert; `menue`, `wildkampf`, `speichern_laden` und `dauerlauf` sind NICHT umgesetzt/gemessen** (`_menue_erkunden.txt` ist nur eine Erkundung, kein Szenario). Insgesamt 26 Läufe unter `work/recomp/qa/<lauf>/` (Berichte `report.md`/`report.json`). Läufe vor 16:44 liefen mit Fehlern, die unten beschrieben und behoben sind; die Fassungen davor werden nicht mitgezählt.

| Szenario | Datei | Ergebnis | Beleg |
|---|---|---|---|
| Sprachauswahl (ohne Spielstand) | `sprachauswahl.txt` | **nicht gelaufen** (nur geschrieben) | – |
| boot_titel | `boot_titel.txt` | **nicht aussagekräftig**: einziger Lauf `boot_titel-…-a2` stürzte durch einen Fehler meiner eigenen Zwischenänderung ab (Signal 11, siehe Fehler 3); danach nicht wiederholt. Titel wurde in allen `weiter_stadt`-Läufen erreicht (Titelbild gesehen). | `work/recomp/qa/boot_titel-20261019-164130-a2/` |
| weiter_stadt | `weiter_stadt.txt` | **bestanden** (mit Fassung v2 und v5: Title::Start 21–86 s je nach Last, Stadt 36–102 s) | `weiter_stadt-…-161239-v2`, `…-171256-skipws2`, `…-171924-wlog2` |
| laufen_stadt | `laufen_stadt.txt` | **nicht bestanden/nicht erneut gemessen**: die fünf Läufe `laufen_stadt-…-rep1..5` (Zeitskript, vor der Audio-Korrektur) hingen zweimal (Fehler 1); mit ereignisgesteuerten Eingaben und korrigierter Laufzeit **nicht** wiederholt | `work/recomp/qa/laufen_stadt-2026101916*` |
| pokecenter | `pokecenter.txt` | **bestanden** (3 von 3 Läufen mit Audio-Pacing: Tür betreten, Innenraum gezeichnet (Halle, Schwester, Ja/Nein-Dialog „Guten Tag! Willkommen im Pokémon-Center!“, Heilung, Bildschirm mit Pokémon), 0 Hänger). Ein Lauf vorher (k1, ohne Pacing) hing im Innenraum (Fehler 2). | `pokecenter-…-162752-k2`, `…-164447-a3`, `…-164824-a4` |
| menue | – | **nicht umgesetzt**; Erkundung `_menue_erkunden-…-165203-m1`: X öffnet das Menü (Pokédex, Pokémon, Beutel, Trainerpass, Karte, Kapsel-Deko, Einstellungen, Geheimgeschenk; Hinweis „Speichern R“, „Karte öffnen +“), B schließt es; 0 Fehler. Speichern wurde nicht getestet. | `work/recomp/qa/_menue_erkunden-20261019-165203-m1/` |
| wildkampf | – | **nicht umgesetzt** | – |
| speichern_laden | – | **nicht umgesetzt** (Harness kennt `phase`, `save-valid`, `save-changed`; ungetestet) | – |
| dauerlauf (30 min) | – | **nicht gelaufen**: keine Speicherleck- und FPS-Dauerzahlen | – |

**Messwerte (gemessen, jeweils ein Lauf):** `pokecenter-…-164447-a3` (Mac fast leer, Last 3): Bildrate Median 46,6, p5 33,3, Minimum 11,8, 5.684 Bilder in 137 s; RSS Spitze 1.968 MiB, Median 869 MiB, CPU 138 %; 58.231 IPC, 2,35 Mio. SVC. `…-164824-a4`: Median 51,2, p5 29,4; RSS Spitze 1.882 MiB. Bei Fremdlast (Last 25–55 durch parallele Compiler/Unity) fiel die Rate auf Median 17–35 mit Minimum 0,5; **diese Läufe sagen nichts über die Laufzeit aus**. Kein Absturz in der Stadt/im Pokécenter mit Fassung ab v4.

## Gefundene Fehler

| Nr. | Fehler | Ursache | Stand |
|---|---|---|---|
| 1 | **Hänger im Spiel** (Bild bleibt stehen, 2 von 5 Läufen `laufen_stadt` (rep1, rep2), 1 von 2 `pokecenter`): Hauptthread wartet in `AkGameObj::SetPosition` auf die Wwise-Sperre (Mutex `700501f008`), Besitzer ist Thread 113, die Audio-Schleife `GetReleasedAudioOutBuffer` (50.000 IPC) | **belegt** (Thread-Zustand und Mutex-Besitzer im Bericht): `audout_obj` gab jeden angehängten Puffer sofort zurück; die Wwise-Audioschleife sah dadurch immer freie Puffer und rechnete ohne Pause weiter, hielt dabei die globale Wwise-Sperre. Außerdem war `ntags` ohne Sperre (zwei Gastthreads: Anhängen/Abfragen) | **behoben** in `services_audio.c`: Sperre je `AudOut`, Puffer werden erst nach ihrer Spieldauer (aus `dataSize`, mindestens 5 ms) zurückgegeben, Zeitgeber-Thread meldet das Ereignis. Danach 3 Läufe ohne Hänger. Kein Ton. |
| 2 | Selbstverklemmung des Kernels nach Zeitablauf, der mit einem Weckruf zusammenfällt (Thread besitzt Mutex und sperrt ihn selbst erneut; Lauf `weiter_stadt-…-170620-skipws` hing bei 23 s, Thread 113 `ArbitrateLock` auf eigenen Mutex `700501f40c = 4000015e`) | **belegt** (Mutex-Besitzer im Bericht) | In `kernel.c` hat der Strang `ap-recomp-ios` zeitgleich dieselbe Korrektur eingebaut (`block_current`: gilt der Weckruf des Wakers). Von mir nicht angefasst. Mit Fassung v5 (enthält sie) kein weiterer Hänger in 5 Läufen. |
| 3 | Absturz Signal 11 beim Start (`GetAudioOutBufferDataPointer`, Adresse 0x30) | **belegt**: meine erste Pacing-Fassung gab den Tag schon nach 0 ms zurück, bevor das Gastsystem den Puffer in seine Warteschlange eingetragen hatte | **behoben** (Mindestdauer 5 ms), Zwischenfassung nie committet |
| 4 | Harness: ereignisgesteuerte Eingaben nötig (Ladezeit 21–120 s) | – | behoben (Anker, `BDSP_INPUT_CTL`) |

## Bildvergleich gegen Ryujinx (`scripts/visual_ref.py import --source recomp` / `refs`, bereits im Arbeitsbaum vorhanden; ich habe nichts daran geändert)

- Stadt Zone 24 (`ref_01_feld_weiter`): bestes Recomp-Bild (Bild 1440, `pokecenter-…-164447-a3`) gegen die Ryujinx-Referenz: **SSIM 0,708 (angeglichen 0,704), MAD 16,0 (16,6), 17,8 % geänderte Pixel, 10 von 64 Rasterzellen schlecht**, Helligkeitsverhältnis 1,02. Sichtbar gleich: Haus, Figuren, Bäume, Straßenmuster. **Abweichung: Wasser links** (siehe unten). Kamerazeitpunkt weicht ab (28 Pixel), deshalb SSIM begrenzt.
- **Tageszeit:** die Beleuchtung folgt der Uhr des Rechners (Lauf um 16:xx ergibt violette/blaue Dämmerungsfarben, Lauf um 17:xx rötlich). Ein Vergleich mit der Referenz (Spielstunde ≈ 12) ist nur bedingt fair; für reproduzierbare Messungen müsste die Uhr (`ITimeZoneService`/`ISystemClock`) fest eingestellt werden (nicht umgesetzt).
- Heatmap: `work/visual/ref/recomp_vs_ryujinx/` (lokal).

## Wasser (Priorität 1, nicht fertig)

Belegt durch Auslassen von Fragment-Shadern (`BDSP_SKIP_FSHASH`, Läufe `…-skipwater`, `…-skipws2`): das weiße Wasser links im Stadtbild kommt **nicht** von `Delphis/Map/FlowmapWater` (Hash `87bfeb6485a0650a`, Auslassen ändert nichts am Bild), sondern von **`Delphis/WaterSimulation/WaterSurface`** (Hash `81f72a1870a4930f`, ein Zeichenaufruf, 6 Mal je Messbild). Ohne diesen Shader erscheint an der Stelle ein violett-blauer Untergrund, mit ihm ein überbelichtetes Weiß. Eingänge des Shaders (4 Texturen laut Übersetzung, aus `BDSP_LOG_WATER` in einer lokalen Debug-Fassung): #0 512×512 RG8 (`0xd`), #1 1280×720 Tiefe/Stencil (`0x35`, = `_OpaqueDepthTexture`), #2 1280×720 R11G11B10F (`0x3f`, Szenenfarbe, kopiert aus 1920×1080 `0x25`), #3 512×512 RGBA8 (`0x25`, Reflexions-/Simulationstextur). Die gespeicherten Abzüge zeigen **#0 komplett 0** (Normal-/Strömungsabbild der Wassersimulation nie beschrieben oder nicht sichtbar) und #2 in den ersten Zeichenaufrufen fast schwarz, später hell (Mittel ≈ 213); ob die Abzüge zeitlich stimmen (der Metal-Befehlspuffer ist beim Speichern evtl. noch nicht ausgeführt), ist **nicht geklärt**. **Vermutung (nicht belegt):** Die Texturen der Simulation (`Custom/WaterInteration/DynamicNormalMap`, `WaterSimulation`, je 1 Zeichenaufruf) werden in einem Rendertarget geschrieben, das der Wasser-Shader leer/ohne Ladeaktion liest (Load/Store oder Reihenfolge der Durchgänge im Metal-Pfad). Nächster Schritt: Abzug erst nach `renderer_flush()` und Vergleich mit Ryujinx-Wasserbildern `free_wasser_a/b` (Zielwerte siehe `docs/wasser.md`: Mittel ≈ 87/127/210).

## Pokécenter-Innenraum (Meldung `ap-recomp-macapp`: einfarbig blau, dunkle Striche)

**Nicht reproduziert:** in 3 Läufen (v3, v4, v5, jeweils Titel → Stadt → Pokécenter) zeigt der Innenraum die richtige orange/gelbe Halle mit Schwester, Dialogfenster und Heilbildschirm (`contact_p1_03/04.png` unter `pokecenter-…-164824-a4/`). Der gemeldete Fehler gehört vermutlich zu einer anderen Fassung (App-Hülle/anderes Bild-Verzeichnis) oder zu einer anderen Tageszeit; ungeklärt.

## Offene Punkte (Priorität)

1. **Wasser `WaterSurface`** (P1, siehe oben).
2. `laufen_stadt` mit der korrigierten Laufzeit wiederholen, Szenarien `menue` (inkl. Speichern), `speichern_laden`, `wildkampf`, `dauerlauf` schreiben und messen (P2); das Harness ist dafür vorbereitet.
3. Spieluhr festlegen (reproduzierbare Beleuchtung) (P2).
4. Kleinere Befunde: `[tex] type mismatch` (29 Meldungen je Lauf, Dummy-Textur), `[texdump]` gibt „3555734656959,2 MB“ aus (Ausgabefehler im Debug-Text), unbehandelte IPC: `ICommonStateGetter:66` ×7, `IParentalControlService:1`, `acc:u0:130`, `IAudioController:0` (alle seit Gate 2 bekannt, ohne sichtbare Folge) (P3).

## Geänderte Dateien (Stand Abbruch)

Alle bauen (Fassung v5 und die lokale Debug-Fassung wurden aus diesem Stand gelinkt).

| Datei | Änderung | Status |
|---|---|---|
| `scripts/recomp/qa/qa_run.sh`, `qa_run.py` | Harness (Anker, Steuerdatei, Berichte, Kontaktbögen) | fertig, nur an den Szenarien oben erprobt |
| `scripts/recomp/qa/scenarios/*.txt` | 7 Dateien (2 Erkundungen mit `_`, `sprachauswahl` ungetestet) | teilweise fertig |
| `scripts/recomp/rt-bdsp/services_audio.c` | Audio-Pacing, Sperre, Zeitgeber, `BDSP_TRACE_AUDIO` | fertig (Fehler 1 behoben) |
| `scripts/recomp/rt-bdsp/nvn/nvn_glue.c` | Eingabeskript bis 8.192 Schritte, `@datei`, `BDSP_INPUT_CTL` (der Strang `ap-recomp-macapp` hat im selben Abschnitt `g_ext_buttons` ergänzt, beides vereinbar) | fertig |
| `scripts/recomp/rt-bdsp/kernel.c` | nur Bericht: Mutex-Besitzer im Thread-Zustand (`BDSP_BT`); die Zeitablauf-Korrektur stammt von `ap-recomp-ios` | fertig |
| `docs/recomp-qa.md` | dieses Dokument | fertig (Stand wie beschrieben) |
| `work/recomp/nvn-qa/nvn/renderer.m` (nicht im Repo) | Debug-Ausgabe `BDSP_LOG_WATER` | nur lokal, **kein** Patch im Repo (`scripts/recomp/qa/patches/` leer) |

Nicht im Repo: Läufe, Spielstandkopien, Screenshots, Binärkopien unter `work/recomp/qa/` (ca. 300 MB; `bdsp_v5`, `bdsp_dbg`). Keine Prozesse mehr aktiv, Sperrdatei entfernt, Linux-Rechner nicht benutzt.
