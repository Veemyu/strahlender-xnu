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
