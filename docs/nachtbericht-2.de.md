# Nachtbericht 2 (Autopilot, 2026-10-18 bis 2026-10-19)

> **Historisch (Stand 2026-10-20):** `scripts/bundle_retarget.py` ist auf `main` entfernt (nur Branch `unity`). Der Bericht beschreibt den damaligen Stand.

Dieser Bericht trennt Gemessenes von Angenommenem. **Ein fertiges, spielbares Spiel gibt es nicht.** Es gibt ein belegtes Fundament und einen headless lauffähigen Spielkern.

## 1. Was läuft (gemessen)

| Bereich | Stand | Beleg |
|---|---|---|
| Tests | 645 EditMode-Tests grün (Haupteditor), 268 Python-Tests und C-Tests grün | `unity test`, `scripts/tests`, `make test` |
| Stammdaten | 125 JSON-Tabellen exportiert, C#-Leser für Trainer, Zonen, Begegnungen, Items, Warps | `docs/masterdata.md` |
| Spielstand | Lesen und Schreiben, Roundtrip am echten Save byte-identisch (1206 Slots) | `docs/save-kompatibilitaet.md` |
| Pokémon-Slots | Kodierung, Prüfsummen, Felder, Statuswerte; Orakel mit den echten ARM64-Funktionen, 0 Abweichungen | `docs/pokepara-spezifikation.md` |
| Kampf | Schaden, Treffer, Kritisch, EXP, Ereignis-/Handler-System, 54 Fähigkeiten, 73 Items, ca. 105 Attacken-Effekte, Zugablauf, Statusprobleme, Seiten-/Feldeffekte; 694 von 706 echten Trainerteams laufen durch | `docs/kampf-spezifikation-1..5.md` |
| Event-Skripte | Interpreter, alle 13.139 Skripte laufen mit Mock-Host ohne unbekannten Befehl | `docs/evscript-spezifikation.md` |
| Spielkern | Anfangssequenz bis zum ersten Kampf (233 Ticks, 15 Textfenster, Wildkampf, Sieg); 168 von 599 Host-Befehlen umgesetzt (84,7 % der Aufrufe) | `docs/spielkern-1.md` |
| Feld | Zone 422 und 425 aus echten Bundles, Attribut-Kollision, Zonenwechsel (49–268 ms), Block-Streaming, Spielerfigur, 4.197 NPC-Platzierungen | `docs/feld-szene-1.md`, `-2.md` |
| UI | Original-Prefabs laden ohne Spielskripte (Spike S1), Textbox mit Schreibmaschine, Textformat gelesen | `docs/ui-spezifikation-2.md` |
| Shader | 6.804 von 6.820 Varianten verpackbar (99,8 %); Unity rendert bitgleich zum Harness in allen geprüften Fällen; Material-Umbau: 10.008 von 10.008 Materialien exakt zugeordnet | `docs/shader-unity-integration.md`, `docs/material-remap.md` |
| Spiel-Globals | Alle 35 Setter geklärt, 26 in C# umgesetzt | `docs/shader-globals.md` |
| iPad | Speicherlimit 5 GiB ohne, 8 GiB mit Increased Memory Limit; 120/60/30 FPS stabil; leere Metal-Szene ca. 180 MiB | `docs/ipad-messung-1.md` |
| Build | `scripts/build_all.sh` mit den Stufen tools bis deploy (Trockenlauf und Teilstufen getestet) | `docs/bauen.md` |

## 2. Was nicht läuft (ehrlich)

- **Bild mit den erzeugten Shadern:** Zone 422 rendert im Editor erkennbar korrekt (Abschnitt 5b). Ein Pixelvergleich mit der Switch fehlt (keine Referenz); Figur, Himmel und Nachbearbeitung fehlen noch.
- **Schatten und Wasser** sind nur strukturell geprüft. Ohne Referenzbilder der Switch ist ein Pixelvergleich nicht möglich.
- **Die Gegner-KI** ist nicht umgesetzt (kompilierter Code, grob 6–8 Tage). Die Gegner wählen zufällig.
- **Wildgenerierung und Begegnungsraten** sind teils angenommen.
- **431 Host-Befehle der Event-Skripte** fehlen noch. Shops, Menüs, Beutel, Pokédex, Box-Oberfläche und Kampf-UI sind nicht gebaut (UI-Kernumfang geschätzt 150–230 Entwicklertage).
- **Audio** ist nicht umgesetzt (Absicht: kein Ton, nur offline).
- **Cutscenes und Video** sind in Unity nicht getestet (nur die H.265-Konvertierung).
- **Gesamtbild:** Das Spiel ist noch weit von „fertig“ entfernt. Realistisch sind weitere Wochen bis Monate, selbst mit vielen parallelen Agenten.

## 3. Verbindliche Entscheidungen dieser Nacht

- Pfad A für Shader (HLSL-Backend plus ShaderLab-Wrapper), Metal-Plugin nur als Reserve.
- Entitlement „Increased Memory Limit“ bleibt an (5 GiB gegen 8 GiB), Budget bleibt: Obergrenze 4 GB, Richtwert 2,5 GB.
- UI: Original-Prefabs laden und `Dpr.UI.*` nachbauen; Meldungsfenster in eigenem C#.
- Alle Plattformen nutzen jetzt die Qualitätsstufe des Originals (vorher stand iOS auf Medium mit vSync 1).

## 4. Offene Punkte für dich

1. Schriftlizenz und TMP: Die TMP-Grundressourcen (LiberationSans, OFL) liegen jetzt im Repo (ca. 3 MB). Original-Schriften bleiben im Build aus dem eigenen Dump.
2. Free-Team-Signatur läuft nach sieben Tagen ab; auf dem iPad ist die Feld-App installiert (Zone 422 lädt, 30 FPS laut Log). Die Messapp `MemoryProbe` ist ebenfalls noch installiert.
3. **iPad-Texturen:** Die Karten-Bundles enthalten BC1/BC3/BC7; auf iOS schlagen 1.884 Texturen der Zone 422 fehl. Eine ASTC-Umwandlung als Build-Stufe fehlt und ist der nächste wichtige Schritt.
4. **Ob das Bild stimmt, ist ungeprüft** (kein Screenshot auf Mac/iPad, kein Switch-Referenzbild).

## 5. Nachtrag: End-to-End-Builds und Render-Ursachen

- **Player-Builds laufen:** macOS (kalt 202 s, 44 s inkrementell, App 4,1 GB, Zone 422 nach 1,2 s, 470–570 MB RSS) und iPad (Build 19 s, Deploy 2 min 40 s, Zone 422 nach 1,1 s, thermisch nominal). Die iPad-Teilmenge umfasst 5 Bundles (179 MB inklusive Stammdaten). Details: `docs/player-build-1.md`.
- **Größter Fund:** Die Original-Bundles tragen die Zielplattform Switch; Player lehnen sie ab. `scripts/bundle_retarget.py` setzt die Kennung (14.052 Bundles, 0 Fehler) und ist Teil der Stufe `assets`.
- **Editor-Hänger:** Ursache war `run_tests` im laufenden Spielmodus, nicht die Shader. Regel: erst `editor_stop`.
- **Schwarzes Bild:** fehlendes Richtungslicht. Mit Licht und Spielwerten (Stunde 12) Bildmittel (83, 104, 63) statt (0, 0, 0).
- **Offen:** Zone 367 und die Kamera-Gier sind behoben (siehe Nachtrag 2). Weiter offen: Figur und NPC-Marker tragen noch den Ersatz-Shader (Charakter-Materialien nicht exportiert); nach Zone 54 sind andere Zonen ca. 19 % dunkler (Ursache offen); kein Himmel, keine Nachbearbeitung.
- Endstand: **645 EditMode-Tests grün.**

## 5b. Nachtrag 2: Sichtprüfung und iOS-Texturen

- **Erstes belegtes Bild:** Zone 422 (Zwieblüh) rendert im Editor mit den erzeugten Shadern erkennbar wie im Spiel (Blockhaus, Briefkasten, Nadelbäume, Wiese, Weg; Fenster leuchten nachts). Auch Zone 425, 54 und 367 rendern vollständig. Bildmittel Zone 422 bei Stunde 12: (101, 125, 72); 155 Draw-Calls, 53.793 Dreiecke. Die Bilder liegen nur unter `work/visual/` (`docs/sichtpruefung-1.md`). Ein Vergleich mit dem Original ist mangels Referenzbild nicht möglich.
- **Behoben:** Kamera-Gier im Freien, Zone 367 ohne Karte (Container über mehrere Blöcke), Spielerhöhe am Start, Magenta nach Zonenwechsel.
- **iOS-Texturen:** `scripts/texture_transcode.py` wandelt BC nach ASTC (6x6 Farbe, 4x4 BC4/BC5). Zone 422: 46,4 → 25,5 MiB, PSNR Median 46,2 dB; alle 208 Texturen laden in Unity (macOS/Metal). Ein Lauf auf dem iPad steht aus. Aktivierung über `--texture-format` (Standard bei `--target ios`: 6x6). Details: `docs/ios-texturen.md`.
- Der Punkt „iPad-Texturen“ aus Abschnitt 4 ist damit umgesetzt, aber noch nicht auf dem Gerät geprüft.

## 6. Regeln, die eingehalten wurden

Kein Ton und keine Lautstärkeänderung. Keine Keys, Dumps, Spielwerte oder Screenshots im Repo. Commits nur mit deiner Identität, ohne Co-Author-Trailer. Kein sudo.
Abweichungen: Ein Agent hat kurz ein `find /` gestartet und sofort abgebrochen (dein Verbot, die ganze Platte zu scannen, wurde damit verletzt). Zur Platzbeschaffung hat ein Agent alte Mess-Builds gelöscht (MemoryProbe-Derived-Data, `xnu-m0`/`ios-xnu`, macOS-Build). Einige Agenten haben trotz Anweisung Dateien in `work/` per Python oder `sed` geschrieben; im Repo wurde der Inhalt jeweils geprüft.
