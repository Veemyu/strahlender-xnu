# Machbarkeit Shader und Audio für ein Mac/iPad-Rebuild (Stand: 2026-10-18)

Alles hier ist eigene Auswertung aus dem eigenen Dump und lokal erzeugten Daten. Es wurden nur Zahlen, Größen und Formate notiert, keine Spielinhalte ins Repo gelegt.
Ausgaben liegen unter `work/shader-test/`, `work/audio-test/` und `tools/vgmstream/` (alles gitignored).
Hilfsskripte: `scripts/shader_bundle_scan.py`, `scripts/shader_cache_scan.py`, `scripts/shader_msl_check.swift`.
Markierung: **belegt** = selbst gemessen oder gelesen, *vermutet* = Schluss ohne Test.

## Kurzfazit

- Shader: Der Ryujinx-Vulkan-Cache enthält 5937 fertige SPIR-V-Module. `spirv-cross` übersetzt alle 5932 Grafik-Module ohne Fehler nach MSL. 401 Stichproben-Module (6 + jedes 15. von 5932 = 395) lassen sich mit dem Metal-Laufzeit-Compiler übersetzen (Apple M1 Pro). Technisch ist Weg B also machbar.
- Der eigentliche Aufwand ist nicht die Übersetzung, sondern Bindings, Renderzustand und die Zuordnung zu Unity-Shadern und Materialien.
- Audio: Alle 3241 `.wem` sind Wwise-Vorbis. `vgmstream` dekodiert die getesteten Dateien sauber. Die Bänke haben Version 135 (Wwise 2019.2) und passen zur Wwise-Version in opendpr.
- Empfehlung: Weg A (Unity-Neuprojekt über das opendpr-Gerüst), den Cache nur als Referenz für Shader-Rewrites nutzen. Weg B nur als späteres Forschungsprojekt.

## 1. Shader

### 1a. Shader-Bundles im RomFS

| Datei | Größe | UnityFS | Inhalt (UnityPy) |
|---|---|---|---|
| `AssetAssistant/Dpr/shaders` | 6.744.100 B | Format 7, Unity `2019.4.27f1`, Flags `0x43` | 63 `Shader`, 1 `Material`, 1 `AssetBundle` |
| `AssetAssistant/Effects/fxparticle` | 3.857.759 B | Format 7, Unity `2019.4.27f1`, Flags `0x43` | 400 `ShaderVariantCollection`, 1 `Shader`, 1 `AssetBundle` |

- **belegt:** Flags `0x43` heißt Kompressionsart 3 (LZ4HC) für den Blockindex, Verzeichnis und Blockindex liegen zusammen (Bit `0x40`).
- **belegt:** Beide Bundles haben nur eine Plattform-ID: `19`. *Vermutet:* das ist die Unity-Plattform "Switch" (NVN-Binärcode), also kein Windows-, Metal- oder Vulkan-Code.
- **belegt:** In `shaders` sind die 63 Shader-Objekte zusammen 7.909.771 B komprimiert (LZ4) und 42.487.172 B entpackt. Das größte ist `Delphis/Map/Standard` (rund 10,7 MB als Objekt). Namensgruppen: Delphis 22, Custom 17, Mitake 9, UI 6, Dpr 6, TextMeshPro 2, MovieTexture 1.
- **belegt:** Die Subprogramme enthalten Binärdaten und Uniform-Namen (zum Beispiel `unity_MatrixVP`, `_MainTex_ST`), keinen lesbaren Quelltext.
- **belegt:** Der Dump-Export von AssetRipper (`work/ripper/out/ExportedProject/Assets/Shader`) enthält 9 `.shader`-Dateien (insgesamt 11.593 B), alle mit der Zeile `//DummyShaderTextExporter`. Das sind Platzhalter mit Name und Properties und einem Standard-Surface-Shader, aber keine Originallogik. Es sind 9 von rund 64 Shadern; kein Quelltext, kein Binärcode.

### 1b. Ryujinx-Shader-Cache

Das Format steht im öffentlichen Ryujinx-Quellcode (`Ryujinx.Graphics.Gpu/Shader/DiskCache`). Die Originalrepos `Ryujinx/Ryujinx` und `Ryubing/Ryujinx` liefern auf GitHub 404. Gelesen habe ich den Fork `NextendoNetwork/Ryujinx-Nextendo`. Das Layout ist selbst nachgebaut (kein Code kopiert).

Grundaufbau, alles little-endian, Header je 32 B:

| Datei | Magic | Eintrag | Inhalt |
|---|---|---|---|
| `guest.toc/.data` | `TOCG` | 16 B: Offset, Code-Größe, CB1-Größe, Hash | Maxwell-Shadercode der Konsole (hardwareunabhängig) |
| `shared.toc/.data` | `TOCS` | 8 B: Offset | je Programm: Stufenmaske, Guest-Indizes, Spezialisierungszustand |
| `vulkan_apple.toc/.data` | `TOCH` | 16 B: Offset, entpackte Größe, gepackte Größe | je Programm: Paket mit SPIR-V je Stufe (`[Anzahl][Stufe, Länge, Bytes]`), danach Stufeninfos |

Die Datenblöcke beginnen mit einem Byte für den Kompressionsalgorithmus (0 keine, 1 Deflate, 2 Brotli).

**belegt (selbst gezählt):**

| Datei | TOC-Version | Einträge | Datengröße |
|---|---|---|---|
| `guest.toc` | 1.1 | 1388 | 2.256.780 B |
| `shared.toc` | 1.2, Codegen 5311 | 2971 | 623.941 B |
| `vulkan_apple.toc` | 1.2 | 2971 | 58.521.808 B |

- Zeitstempel in `shared`/`vulkan_apple`: 2023-07-07. Der Codegen-Stand 5311 ist älter als der aktuelle Quellstand (7355). Moderne Ryujinx-Builds würden den Host-Cache verwerfen. Das ist für uns egal, da wir ihn selbst lesen.
- Alle 2971 Host-Einträge sind Deflate-komprimiert und ließen sich ohne Fehler entpacken (entpackt zusammen 199.915.580 B, 5528 bis 99.864 B je Eintrag).
- **SPIR-V ja:** 5937 Module (Magic `0x07230203`), davon 2966 Vertex, 2966 Fragment und 5 Compute. Das sind 2966 Vertex+Fragment-Paare plus 5 Compute-Programme. Keine Geometry- oder Tessellation-Shader (das passt gut zu Metal).
- Das ist nur die Auswahl, die beim damaligen Spielen tatsächlich gebraucht wurde. Sie ist nicht vollständig. Auch Namen und Materialzuordnung fehlen.

### 1c. spirv-cross nach MSL

Aufruf: `spirv-cross --msl --msl-version 20300 <modul>.spv`. Alle 5932 Vertex- und Fragment-Module wurden extrahiert (202 MB unter `work/shader-test/all`).

- **belegt:** 5932 von 5932 geben Exit-Code 0 (keine Fehler).
- **belegt:** Die 3 Stichproben-Programme (je Vertex + Fragment, also 6 Module) ergaben 102 bis 247 Zeilen MSL. Zusätzlich wurden 395 weitere Module übersetzt (jedes 15.).
- **belegt:** Alle 401 MSL-Dateien kompiliert der Metal-Laufzeit-Compiler (`MTLDevice.makeLibrary`, MSL 2.3, Apple M1 Pro) ohne Fehler. Das Kommandozeilenwerkzeug `metal` ist nicht nutzbar, weil die Metal-Toolchain nicht installiert ist. Ich habe sie nicht nachgeladen.
- Qualität: syntaktisch korrekt, aber maschinell. Variablennamen wie `_42`, jede Komponente einzeln, Konstantenpuffer als `float4[4096]` (64 KB, Ryujinx-Layout), Eingänge als `user(locn0)`. Lesbar genug zur Analyse, nicht zum Pflegen.
- *Vermutet:* Es ist nur Kompilierbarkeit geprüft, nicht Bildgleichheit. Ungeprüft sind Bindings (Buffer-/Textur-Indizes), y-Flip/Clipspace (`--flip-vert-y`, `--fixup-clipspace`) und Spezialisierungszustand (Blending, Vertexformat).

### 1d. Bewertung

**Weg A: Unity-Neuprojekt, Shader als ShaderLab neu schreiben.**
- Pro: passt zu opendpr (Unity 2019.4.27f1, Scripts, Wwise). Läuft auf Mac per Rosetta-Editor und kann auf iPad gebaut werden. Rund 64 Shader, davon etwa 9 Standard-Shader (TMP, UI, Bloom, FXAA) sind Standardware.
- Contra: Handarbeit pro Shader (Delphis/Map/Standard, Character, Poffin, Mitake). Als Vorlage dienen die MSL-Ausgaben, Uniform-Namen aus den Bundles und die Referenz-SPIR-V. Es entsteht kein 1:1-Ergebnis, nur "sieht ähnlich aus". Das Hauptproblem bleibt der Blocker B1 aus dem opendpr-Machbarkeitsbericht (entfernt, siehe Git-Verlauf): Die Switch-Shaderbundles sind auf Mac unbrauchbar.

**Weg B: eigene Runtime, SPIR-V nach MSL.**
- Pro: 100 % der im Cache vorhandenen Shader sind automatisch übersetzbar; keine Handarbeit pro Shader.
- Contra: Man bräuchte eine komplette eigene Engine (Szenen, Materialien, Zustände, Spiellogik). Das ist der größte Posten und hat mit Shadern nur am Rand zu tun. Zusätzlich fehlen die Zuordnung Cache-Programm ↔ Material und die Zustände aus `shared`. Cache-Abdeckung ist lückenhaft (nur gespielte Varianten). *Vermutet:* Man könnte Cache-Programme über den Guest-Code mit den Switch-Binärdaten in den Bundles abgleichen und so Namen gewinnen. Das ist ungetestet.

**Gerüst (opendpr-Skripte, Unity-Projekt):** ist die Grundlage von Weg A. Es ersetzt keine Shader.

**Empfehlung:** Weg A. Die Cache-Übersetzung (spirv-cross → MSL) ist ein gutes Referenzwerkzeug, um Rewrites zu prüfen, und erlaubt später ein reines Metal-Rendering einzelner Effekte. Eine eigene Runtime nach Weg B lohnt erst, wenn Weg A scheitert.

## 2. Audio

Pfad: `work/romfs/Data/StreamingAssets/Audio/GeneratedSoundBanks/Switch` (427 MB).

**belegt:**

| Messwert | Wert |
|---|---|
| `.bnk` | 696, alle `BKHD`-Version 135 (Wwise 2019.2.x) |
| `.wem` | 3241, zusammen 379.052.108 B (529 B bis 9.163.998 B, Median 7379 B) |
| Weitere Dateien | `Wwise_IDs.h` (1,7 MB), `PluginInfo.xml` |
| Bank-Chunks | `BKHD`, `HIRC` je 696, `DIDX`/`DATA` je 695 (eingebettete Medien: 2344 Einträge, 56.496.146 B), je 1x `INIT`, `STMG`, `ENVS`, `PLAT` |
| Größte Bank | `Delphis_Main.bnk`, 24.561.004 B |
| Codec | RIFF-Format-Tag `0xFFFF`: Wwise-Vorbis (kein Opus) |
| Abtastraten | 32 kHz 2337, 48 kHz 371, 36 kHz 344, 24 kHz 162, andere 27 |
| Events in `Wwise_IDs.h` | 24.278 benannte IDs im Namespace `EVENTS` |

- Versionsabgleich: opendpr bringt Wwise 2019.2.4 mit Mac-Plugins mit (siehe opendpr-Machbarkeitsbericht im Git-Verlauf). Bankversion 135 passt dazu. *Vermutet:* Die Switch-Bänke laufen mit dem Umbenennen des Ordners nach `Windows` (so schreibt es opendpr vor), ungetestet.
- **vgmstream:** Release `r2117`. Das Mac-Release `vgmstream-mac.zip` hat feste Pfade zu Homebrew-Bibliotheken (`libvorbis`, `libogg`, ffmpeg-Version 62), die hier fehlen oder zu neu sind. Also habe ich vgmstream r2117 samt libogg 1.3.5 und libvorbis 1.3.7 nach `tools/vgmstream/` gebaut (ohne ffmpeg/mpg123/speex/celt). Der Build liegt unter `tools/vgmstream/b-vgm/cli/vgmstream-cli`. Homebrew wurde nicht verändert.
- Dekodiertests nach `work/audio-test/*.wav` (alle erfolgreich, Encoding "Custom Vorbis"):

| Datei | Quelle | Format | Dauer |
|---|---|---|---|
| `284133277.wem` | 1661 B | 32 kHz, mono | 0,22 s |
| `1000209917.wem` | 10.663 B | 32 kHz, mono | 1,32 s |
| `382403544.wem` | 563 B | 6 kHz, 2 Kanäle | 5,00 s |

- Alle 3241 `.wem` wurden zusätzlich nur per Metadaten (`-m`) geprüft und von vgmstream als Custom Vorbis erkannt, keine Fehlermeldung. Vollständig dekodiert habe ich nur die 3 Dateien oben.
- **wwiser (bnnm/wwiser, nur README gelesen):** liest `.bnk` komplett inklusive `HIRC` (Event-, Aktions-, Container-Struktur), kann Namen aus `Wwise_IDs.h` und `SoundbanksInfo.xml` nutzen, erzeugt XML/TXT-Dumps und `.txtp`-Dateien, die vgmstream abspielt. *Vermutet:* Das ist unser Werkzeug, um Event → Aktion → `.wem` aufzulösen. Es kann Wwise-Features nur teilweise simulieren und verändert keine Bänke.

### Bewertung Audio
- Bei Weg A läuft Wwise 2019.2.4 über das opendpr-Gerüst nativ auf Mac (Plugins im Repo). Auf iPad fehlen nach unserem Wissensstand iOS-Plugins in opendpr (*vermutet*, nicht geprüft). Das SDK ist proprietär (Audiokinetic-Konto/Lizenz nötig).
- Alternative ohne Wwise-Runtime: `.wem` mit vgmstream nach WAV/OGG wandeln und Events über wwiser-Dumps in einen eigenen Mixer abbilden. Das ist deutlich mehr Arbeit (RTPC, Switches, States, Container-Logik).

## 3. Empfehlung und nächste Schritte

1. Weg A weiterverfolgen. Shader: eine kleine Liste priorisieren (TMP/UI/Bloom/FXAA zuerst, dann Delphis Map/Character).
2. Die Cache-Programme mit den Bundle-Shadern abgleichen (Guest-Code ↔ Switch-Binärdaten), um Namen/Varianten zu bekommen. Das ist der einzige noch unbekannte Schritt für Weg B.
3. Audio: wwiser einmal über `Delphis_Main.bnk` laufen lassen, Eventliste prüfen, danach Wwise-Bänke im Unity-Projekt auf Mac testen.
4. Offene Risiken: Spielversion von Dump und Ryujinx-Cache (2023) nicht verglichen; MSL nur kompiliert, nicht gerendert; iPad-Wwise-Plugins ungeprüft.
