# Architektur-Entscheidung (Vorlage, keine Entscheidung)

Stand: 2026-10-18. Grundlage sind die eigenen Notizen in `docs/`. Zahlen sind Messungen aus unserem Dump, Einschätzungen sind als solche gekennzeichnet. Die Entscheidung trifft der Nutzer.

## Ausgangslage in Zahlen
- **Spiellogik:** ca. 6.200 Typen (53 %) mit ca. 39.100 Methoden (rund 60 % der Methoden ohne .NET-Basisbibliothek). Schwerpunkte: Kampf (1.816 Typen), UI (1.232), Feldklassen (935). Engine und Middleware (Unity, uGUI, DOTween, TMP, Wwise, Nintendo-SDK) sind rund 20 % der Methoden (`spielcode-inventar.md`).
- **Rekonstruktionswerkzeug:** Ghidra mit 166.095 benannten Funktionen ist die Hauptquelle. Cpp2IL liefert nur 27,9 % saubere Rümpfe, 65,5 % haben Platzhalter. Es gibt keine automatische C#-Rekonstruktion in brauchbarer Qualität (`cpp2il-bewertung.md`).
- **Save:** Format ist belegt und mit einem eigenen Validator geprüft (Größe 0xEF0A4, Version 0x34, MD5 bei 0xE9818). Die Innenlayouts der Unterstrukturen sind offen (`save-spec-entwurf.md`, `save-validator.md`).
- **Daten:** 14.052 UnityFS-Bundles (v7, Unity 2019.4.27f1, LZ4HC), 696 Wwise-Banks (v135) und 3.241 WEM (Vorbis) (`daten-inventar.md`).
- **Shader:** Switch-Bundles `shaders` (63 Shader) und `fxparticle` (1 Shader), ohne Quelltext. Der Ryujinx-Cache enthält 2.971 Einträge und 5.937 SPIR-V-Module. `spirv-cross` übersetzt alle 5.932 Grafik-Module nach MSL, Bildgleichheit ungeprüft (`shader-audio-machbarkeit.md`).
- **opendpr** (Referenz, ohne Lizenz): Gerüst mit ca. 3.800 Dateien, 93 % der Typnamen des Dumps, viele Platzhalter. Im Unity-2019.4-Editor unter Rosetta kompiliert es, der Boot scheitert (`UIManager.Instance` null, Shader-Bundle fehlt) (`opendpr-aufbau.md`).
- **Recomp-Projekte** (LASRecomp, letsgo-recomp): keine Unity-Spiele, kompilieren beim Nutzer, liefern Nintendo-Code mit. Für iPadOS ungeeignet. Nur Checkliste für Switch-Dienste (`recomp-referenzen.md`).
- **Editor-Lage:** Unity 2019.4.27f1 läuft nur als Intel-Editor unter Rosetta. Im Batchmodus scheitert die Lizenz, in der GUI geht es.

## Optionen

### A – Neues Unity-Projekt (neuere LTS) mit rekonstruierter C#-Logik
- **Dafür:** Unity liefert Szenengraph, Animation, Timeline, UI und Partikel, die die Bundles voraussetzen. Nur ca. 64 Shader sind neu zu schreiben (ShaderLab), der Cache dient als Referenz. IL2CPP ist AOT und braucht kein JIT (nicht selbst geprüft).
- **Dagegen:** ca. 39.100 Methoden Logik per Hand aus Ghidra-Pseudocode. Ob eine neuere Unity-LTS die 2019er Bundles lädt, ist ungeprüft. Wwise-Laufzeit für Mac/iPad ist nicht geklärt. Lizenz und Batchbetrieb bei neuer LTS ungetestet.

### B – Eigene native Runtime (Metal)
- **Dafür:** Volle Kontrolle, kein Fremd-Engine-Ballast, passt zu `goal.md` (Metal oder SPIR-V/MoltenVK). Shader könnten per SPIR-V→MSL kommen.
- **Dagegen:** Unity-Serialisierung (Bundles), Animation, Timeline, UI-Layout und Partikel müssten selbst gebaut werden. Zusätzlich dieselbe Logik-Rekonstruktion wie bei A. Mit Abstand größter Umfang.

### C – Nur Referenz und Analyse
- **Dafür:** Kein Release-Risiko. Alle Ergebnisse bleiben Dokumentation und Werkzeug (Save-Validator, Inventare).
- **Dagegen:** Kein spielbares Ergebnis.

### D – Durchstich auf A, dann entscheiden (Vorschlag zur Diskussion)
- Ein kleiner vertikaler Schnitt in einer neueren Unity-LTS: Boot, Daten laden (Master-Daten), Menü, Save lesen. Ziel: Aufwand und Kompatibilität messen (Bundle-Ladbarkeit, Wwise, Shader), danach A, B oder C wählen.

## Kriterien im Vergleich (Einschätzung, nicht gemessen)
| Kriterium | A | B | C |
|---|---|---|---|
| Kein JIT auf iPadOS | gut (AOT) | gut | – |
| Aufwand Engine | gering | sehr hoch | – |
| Aufwand Spiellogik | hoch | hoch | – |
| Shader | ca. 64 neu, Referenz vorhanden | SPIR-V→MSL | – |
| Save-Kompatibilität | gut (Format belegt) | gut | Validator vorhanden |
| Rechtliche Lage | heikel bei Verbreitung | heikel bei Verbreitung | unkritisch |

## Rechtlicher Hinweis
Rekonstruierter Code aus Decompilation kann urheberrechtlich heikel sein, sobald er verbreitet wird. Das gilt für A und B gleich. Unser Grundsatz bleibt: Assets nur aus dem eigenen Dump, keine Spieldateien, Keys oder extrahierten Inhalte im Repo. Eine Trennung von Spezifikation und Implementierung kann das Risiko senken. Das ist keine Rechtsberatung.

## Offene Fragen an den Nutzer
1. Ist das Ziel ein vollständig spielbares Spiel oder zunächst ein Durchstich mit Save-Import?
2. Wie wird mit der Verbreitung umgegangen (rein privat oder öffentlich)?
3. Soll der Durchstich (Option D) in einer neueren Unity-LTS laufen, und wie sehen Lizenz und Unity-Account dafür aus?
4. Wie viel manuelle Rekonstruktion der Spiellogik ist akzeptabel, und wo beginnen wir (Save-nahe Klassen, Kampf, Feld)?
5. Wwise: eigene Wiedergabe über konvertierte WEMs oder Wwise-SDK-Laufzeit?
6. Rolle des Ryzen und des M2 mini (nur noch Batch-Analysen)?

## Entscheidung des Nutzers (2026-10-18)
- **Richtung D:** Durchstich in einer neueren Unity-LTS, danach A, B oder C wählen.
- **Ziel:** vollständig spielbares Spiel.
- **Verbreitung:** später öffentlich, nur Code ohne Spielinhalte. Damit wird die rechtliche Trennung wichtig: keine Spieldateien, Keys oder extrahierten Inhalte im Repo, Spezifikationen in eigenen Worten, Implementierung getrennt davon. Das ist keine Rechtsberatung. Vor einer Veröffentlichung sollte die Rechtslage geklärt werden.
- **Unity-Version für den Durchstich:** 6.3 LTS (6000.3.26f1, native Apple-silicon-Variante), weil das die aktuelle LTS ist. Neben dieser Wahl steht 6.0 LTS (6000.0.85f1) als Alternative.

## Zielplattformen und Reihenfolge (Nutzervorgabe 2026-10-18)
- **Endziel:** native Metal-Anwendung auf ARM für iOS/iPadOS (ohne JIT, AOT/IL2CPP).
- **Vorstufe:** macOS-Port (Apple Silicon), darf als MVP einfacher sein.
- **Plattformübergreifend** (z. B. Windows/Linux) wird mitgedacht, ist aber erst später wichtig: keine Architekturentscheidung darf macOS-/iPadOS-Spezifisches verbauen, aber es wird noch nichts dafür gebaut.
- Meilensteine: M0 Durchstich (Unity 6.3 LTS, macOS), M1 macOS-MVP (1080p 16:9, Metal, Save-Import), M2 iPadOS-Build (Speicherbudget, Touch/Controller), danach plattformübergreifend.
- **Beobachtet:** `/Applications/Xcode.app` ist vorhanden, `xcode-select` zeigt aber auf `/Library/Developer/CommandLineTools`, ein iPhoneOS-SDK wird darüber nicht gefunden. Für iOS-Builds muss die Xcode-Developer-Umgebung gewählt werden (z. B. per `DEVELOPER_DIR` oder `xcode-select -s`, Letzteres braucht Admin). Das iOS-Build-Support-Modul von Unity ist noch nicht installiert.

## Entscheidung 2 (Autopilot, 2026-10-18 23:55): Rekompilation zurückgestellt
Grundlage: `docs/recomp-machbarkeit.md` (Spike, gemessen).
- **Weiter mit Option D** (Unity 6.3 LTS, Logik rekonstruieren, Shader per Maxwell-Übersetzer treu portieren).
- **Gründe gegen R als Hauptweg:** C++-Exceptions in 2.917 Funktionen brechen das LAS-Modell „Host-Stack = Gast-Stack“ (Forschungsaufwand ohne Schätzung), Thread-Anhalten für den Boehm-GC fehlt in LAS (8 von 50 SVCs), 32-Bit-Rebasing wegen iPadOS-Adressraum (3–6 Wochen geschätzt), Leistung ungemessen, 1,01 GB erzeugtes C.
- **Was für R sprach:** 1:1-Logik automatisch, sehr gute CPU-Abdeckung (58 von 14,1 Mio. Wörtern nicht abgedeckt), Repo ohne abgeleiteten Code.
- **Offen gehalten:** R als Referenzimplementierung für Treuevergleiche (Hybrid). Spike-Phase 2 beginnt mit dem Exception-Test als Ausschlusskriterium; nur wenn Zeit bleibt.
- Der Nutzer hat die Entscheidung dem Autopiloten überlassen („weiseste Entscheidung“). Revidierbar.

### Nachtrag zu Entscheidung 2 (2026-10-19): Ergebnis des Phase-2-Spikes, Entscheidung offen beim Nutzer
Grundlage: `docs/recomp-spike-2.md` (gemessen). Die drei Hauptgründe gegen R aus Entscheidung 2 haben sich verändert: **C++-Exceptions** sind im LAS-Modell lösbar (der echte Unwinder des SDK läuft rekompiliert, 100 von 100 erreichten echten BDSP-Funktionen wählen das richtige Landing-Pad, 1 bis 2 Wochen Produktionsarbeit), das **Thread-Anhalten für den Boehm-GC** ist lösbar (Mach-API, 2 bis 4 Tage), das **32-Bit-Speichermodell** läuft als Header-Schalter (1,5 bis 3 Wochen statt 3 bis 6). Alle vier Module sind erzeugt und übersetzt (270.299 Funktionen, 15,6 min, 224 MiB Bibliothek); das SDK initialisiert sich rekompiliert bis zur ersten Dienstanfrage. Offen sind Leistung, Speicher auf dem iPad, der Unity-Start auf dem Gast und die Dienstschicht. Empfehlung des Spikes: **Hybrid** (R als parallel verfolgter Hauptkandidat mit Entscheidungspunkt nach 4 bis 6 Wochen auf dem Mac, D läuft weiter ohne neue große Rekonstruktionsblöcke). Diese Empfehlung ersetzt Entscheidung 2 nicht; sie liegt beim Nutzer.

## Entscheidung 3 (Autopilot, 2026-10-19 15:30): Rekompilation wird Hauptweg, Unity-Rebuild bleibt Gegenprobe
Grundlage: `docs/recomp-gate2.md`, `docs/recomp-diff.md`, `docs/recomp-spike-2.md` (gemessen) und der Lauf vom 2026-10-19 15:25.
- **Beleg:** Der rekompilierte BDSP-Code läuft auf dem Mac über rtld, Eröffnungsfilm, Titelbild und Spielstand bis in die 3D-Stadt (Metal, 45 Bilder/s, RSS ca. 1,0–1,5 GiB, stabil 135 s); unter Linux/Vulkan (RTX 2080 Ti) zeichnet derselbe Code die Sprachauswahl. Logik, UI, Events, Kampf, Speicherformat und Engine-Verhalten sind damit 1:1 das Original.
- **Gründe:** Exceptions, GC-Anhalten und 32-Bit-Rebasing sind gemessen lösbar; der c-Modus ist bitgenau (0 Abweichungen, `docs/recomp-diff.md`); Shader laufen durch unseren Maxwell-Übersetzer (0 Fehler bei 5.959 Programmen). Aufwandsschätzung R 18–35 Wochen gegen D 40–80 Wochen (±50 %), seither deutlich vorgezogen.
- **Hauptweg:** (R) Rekompilation → macOS-App (arm64, Metal), danach iPadOS (rebase32, Speicherfenster ≤ 4 GiB), Linux/Windows (Vulkan, x86-`c`-Modus) als Zusatz. Repo enthält nur Recompiler, Runtime, Skripte und Doku; der erzeugte Code entsteht beim Bauen aus dem eigenen Dump.
- **Unity-Rebuild (D):** läuft weiter als Referenz und Fallback (Orakel, Spezifikationen, Daten-/Save-Werkzeuge, Bildprüfung); keine neuen Großblöcke.
- **Offen/Risiken:** iPadOS (Metal-Puffer 5 GiB-Fenster, rebase32 auf Gerät ungemessen, Build-Zeit des Generats in Xcode), Touch-/Controller-Eingabe, Audio derzeit stumm (wird erforscht, Todo `rc-audio`), Online-Dienste als Stubs, Rechtslage vor öffentlicher Weitergabe klären.
- Der Nutzer hat die Strategie dem Autopiloten überlassen; revidierbar.

## Entscheidung 4 (Nutzer, 2026-10-19 16:57): Unity-Rebuild ist deprecated
- **Wortlaut des Nutzers:** „unity rebuild somit komplett deprecaten! keine weitere arbeit mehr damit verschwenden!“
- **Folge:** Der Unity-Rebuild (`unity/`, Stubs, UI-Fenster, Feld-/Kampf-/Event-Nachbau, Unity-Shader-Wrapper) wird **nicht mehr weiterentwickelt**. Auf `main` entfernt, stattdessen vollständig auf dem Branch `unity` (origin). Keine neuen Aufgaben, keine Fehlerbehebung dort, außer wenn ein Werkzeug daraus die Rekompilation direkt braucht. Der Code bleibt im Repo als Referenz (Orakel-Fixtures, Spezifikationen `docs/kampf-spezifikation-*.md`, `docs/pokepara-spezifikation.md`, `docs/evscript-spezifikation.md`), wird aber nicht mehr gebaut oder getestet.- **Hauptweg und einziger Entwicklungsstrang:** die Rekompilation (`scripts/recomp/`, macOS `BDSP.app`, iPadOS `dev.local.xnubdsp`, Linux/Vulkan). Build: `scripts/build_all.sh` mit der Stufe `recomp`.
- **Weiter genutzt (gemeinsame Werkzeuge):** Extraktion (`tools`, `extract`, `il2cpp`), Maxwell→MSL/GLSL-Übersetzer (`shader_translator/`), Video-Umwandlung, ASTC-Transcode, Save-Werkzeuge (`scripts/bdsp_save.py`, `ryujinx_sync_save.sh`, `ios_push_save.sh`), Bildprüfung (`visual_*`, Ryujinx-Referenz), Ryzen-Farm (`scripts/recomp/linux/`).
- **Stillgelegt (nicht löschen):** Build-Stufen `shaders` (Unity-Wrapper), `assets`-Anteile für Unity, `stubs`, `unity-build`, Skripte `unity_safe.sh`, `shader_wrap*.py`, `stub_gen.py`, `material_*.py` sowie `ap-*`-Todos zu Unity. Details: `unity/DEPRECATED.md`.
- Revidierbar nur durch den Nutzer.
