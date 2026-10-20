# Shader-Harness: Offscreen-Referenzrenderer für Cache-Shader (Stand: 2026-10-18)

Eigenes Kommandozeilenprogramm (Swift, Swift Package unter `scripts/shader_harness/`), das ein Vertex+Fragment-Paar aus dem Ryujinx-Shader-Cache nach MSL übersetzt, zur Laufzeit mit Metal kompiliert und offscreen in ein PNG rendert. Ziel: ein reproduzierbarer Referenzrenderer für Differenztests. Dieselben Eingaben laufen später durch einen nach Unity portierten Shader; danach folgt ein Pixelvergleich mit `scripts/shader_compare.py`.

Es wird kein Fenster geöffnet und nichts abgespielt. Alle Ausgaben liegen unter `work/shaders/` (gitignored). Testdaten sind synthetisch (Farbverlauf, Schachbrett), keine Spieltexturen.

## Bestandteile

| Datei | Aufgabe |
|---|---|
| `scripts/shader_cache_extract.py` | liest `vulkan_apple.toc/.data` (nur lesend) und schreibt SPIR-V nach `work/shaders/spirv/<index>_<stage>.spv` |
| `scripts/shader_harness/` | Swift-Package `shader-harness` (Renderer) und `examples/*.json` (drei Beispiel-Beschreibungen) |
| `scripts/shader_compare.py` | PNG-Vergleich, nur Standardbibliothek |
| `scripts/tests/test_shader_compare.py` | 20 Tests mit synthetischen Bildern |

## Aufruf

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

# 1. Module exportieren (Stufen: vert, frag, comp; dazu index.json)
python3 scripts/shader_cache_extract.py --smallest 12 --list           # kleinste Paare anzeigen
python3 scripts/shader_cache_extract.py --index 68 2741 136            # gezielt exportieren

# 2. Harness bauen (Build-Ordner bewusst unter work/)
swift build -c release --package-path scripts/shader_harness --scratch-path work/shaders/build

# 3. Rendern
H=work/shaders/build/release/shader-harness
$H info   scripts/shader_harness/examples/pair_0068.json        # Bindings anzeigen, nicht rendern
$H render scripts/shader_harness/examples/pair_0068.json --out work/shaders/out/pair_0068.png \
          --dump-msl work/shaders/out/msl_0068                  # MSL zusätzlich ablegen

# 4. Vergleichen
python3 scripts/shader_compare.py a.png b.png --threshold 2 --diff work/shaders/out/diff.png \
          --max-diff 3 --min-psnr 40
python3 -m unittest scripts/tests/test_shader_compare.py
```

`spirv-cross` wird in `/opt/homebrew/bin`, `/usr/local/bin` und `PATH` gesucht (oder über `SPIRV_CROSS=<Pfad>`). Übersetzt wird mit `--msl --msl-version 20300`; kompiliert wird mit Metal Language Version 2.3.

`--xcrun-check` (mit `--dump-msl`) probiert zusätzlich `xcrun metal -c`. Auf diesem Rechner schlägt das fehl, weil die Metal-Toolchain nicht installiert ist; der Kompiliercheck läuft deshalb über `MTLDevice.makeLibrary`.

Das Programm liefert Exit-Code 0 bei Erfolg, 1 bei Fehlern (Spec, Übersetzung, Compiler, GPU), 2 bei falscher Bedienung. Bei `render` steht am Ende eine Zeile mit Pfad, Größe, Anzahl der Pixel, die von der Clear-Farbe abweichen, und dem SHA-256 der RGBA-Bytes. Der Hash dient als schneller Reproduzierbarkeitstest.

## Eingabeformat (JSON)

Relative Pfade gelten ab dem Ordner der JSON-Datei. Unbekannte Schlüssel sind ein Fehler (Schutz vor Tippfehlern). Vollständige Beispiele: `scripts/shader_harness/examples/`.

| Schlüssel | Bedeutung |
|---|---|
| `size` | `[Breite, Höhe]`, Standard `[256, 256]`, Format `rgba8Unorm` |
| `clearColor`, `clearDepth` | Hintergrund RGBA (0..1), Tiefe (Standard 1) |
| `vertex`, `fragment` | je `spirv` **oder** `msl` (Datei), optional `entry` (Standard `main0`), `flipVertY`, `fixupClipspace`, `spirvCrossArgs` |
| `topology` | `triangle`, `triangleStrip`, `line`, `lineStrip`, `point` |
| `vertexCount`, `instanceCount`, `indices` (+ `indexType` `uint16`/`uint32`) | Zeichenaufruf; ohne `vertexCount` wird aus Puffergröße und Stride abgeleitet |
| `vertexBuffers[]` | `slot`, optional `stride`, `step` (`vertex`/`instance`) und genau eine Datenquelle (s. u.) |
| `attributes[]` | `location`, `buffer` (Slot), `offset`, `format` (`float`…`float4`, `int*`, `uint*`, `uchar4`, `uchar4Normalized`, `ushort2/4`, `half2/4`) |
| `buffers[]` | Uniform-Puffer: `stage` (`vertex`/`fragment`), `slot`, optional `size` (Mindestgröße), entweder direkte Datenquelle oder `writes[]` mit `offset` (Bytes) bzw. `offsetFloats` und Datenquelle |
| `textures[]` | `stage`, `slot`, optional `samplerSlot`, `format` (`rgba8Unorm`, `rgba8Unorm_srgb`, `r8Unorm`), `mipmaps`, `sampler`; Quelle `file` (PNG/JPEG) oder `generate` (`solid`, `checker`, `gradient`) |
| `sampler` | `min`, `mag` (`nearest`/`linear`), `mip` (`none`/`nearest`/`linear`), `address` bzw. `s`/`t`/`r` (`clamp`, `repeat`, `mirror`, `border`) |
| `state` | `cull` (`none`/`front`/`back`), `frontFace` (`ccw`/`cw`), `wireframe`, `colorMask` (z. B. `"rgb"`), `blend` (`preset`: `alpha`/`additive`/`premultiplied` oder `srcRGB`, `dstRGB`, `opRGB`, `srcA`, `dstA`, `opA`), `depth` (`test`, `write`) |
| `viewport` | `[x, y, Breite, Höhe]`, Standard: ganzes Bild |

**Datenquellen** (genau eine pro Eintrag): `floats`, `ints`, `uints`, `bytes` (0..255) oder `file` (Rohbytes). Alles little-endian. Das ist auch die Form für „Float-Liste oder Byte-Array“ bei Uniform-Puffern.

**Konventionen aus dem Cache:** Die MSL-Ausgabe legt den Konstantenpuffer jeder Stufe auf `buffer(0)` (`float4[4096]`, 64 KB). Vertexdaten gehören deshalb in einen anderen Slot; die Beispiele nehmen 30. Die Puffergröße wird aus der Metal-Reflexion übernommen und mit Nullen aufgefüllt. `info` zeigt, welche Bindings ein Paar braucht (Buffer, Textur, Sampler, Attribute). Werte in Puffern, die der Shader nicht beschreibt, bleiben 0; fehlt ein ganzer Puffer, erscheint eine Warnung.

## Reproduzierbarkeit

- Zielformat `rgba8Unorm` (kein sRGB-Umweg), eine feste Pipeline, keine Zufallswerte, kein MSAA, keine Anisotropie.
- PNG-Ausgabe über ImageIO, Alpha nicht vormultipliziert. Die rohen Pixelbytes aus dem PNG sind identisch mit dem gemeldeten Hash (mit dem Decoder aus `shader_compare.py` gegengeprüft).
- Zweimaliges Rendern erzeugte bitgleiche PNG-Dateien (`cmp`) und identische Vergleichswerte (max. Abweichung 0, PSNR inf). Das gilt für diese Maschine (Apple M1 Pro); andere GPUs können bei Gleitkomma, Interpolation und Mip-Erzeugung abweichen.

## Vergleichsskript

`shader_compare.py a.png b.png` meldet `max_abs_diff`, `mean_abs_diff` (über alle Kanalwerte), `pixels_over` (Pixel mit mindestens einem Kanal über `--threshold`), `mse` und `psnr` (inf bei Gleichheit). `--ignore-alpha` vergleicht nur RGB, `--diff` schreibt ein Differenzbild (`--diff-gain` verstärkt), `--json` gibt maschinenlesbar aus. Mit `--max-diff`, `--max-pixels` und `--min-psnr` wird der Exit-Code 1, wenn ein Grenzwert verletzt ist (2 bei Lese-/Größenfehlern). Der eigene PNG-Decoder kann alle Farbtypen, Bittiefen 1 bis 16, Adam7 und `tRNS`, prüft CRCs und ignoriert Farbprofile.

## Testergebnis (Apple M1 Pro, macOS 26, Metal Language 2.3)

Drei Paare aus dem eigenen Cache, das kleinste zuerst. Größe in Bytes (Vertex + Fragment); alle Eingaben synthetisch.

| Index | SPIR-V | Was geprüft wird | Ergebnis |
|---|---|---|---|
| 68 | 3120 + 2388 | Quad aus 2 Dreiecken, Rotation/Skalierung per Uniform, Textur (Farbverlauf, linear), Fragment gibt `min(Textur.x, Uniform)` aus | rot, bei 0,75 begrenzter Verlauf; 10404 Pixel bedeckt |
| 2741 | 5684 + 952 | Dreiecke mit Index-Puffer, 2x 4x4-Matrix aus Uniform, Cull `back`, Tiefentest, `colorMask` `rgb`; Fragment schreibt konstant 0 | ein schwarzes Dreieck, das rückwärtige (CW) Dreieck ist weggeschnitten, Alpha bleibt 1; 8194 Pixel |
| 136 | 6044 + 2588 | Triangle-Strip, UV-Attribut, Schachbrett mit Alpha, `discard_fragment` per Alpha-Schwelle, Farbe aus Uniform | orangefarbenes Schachbrett, transparente Felder verworfen; 26450 Pixel |

- Alle drei Paare übersetzen, kompilieren und rendern ohne Fehler. Zweiter Lauf: bitgleich (0 Abweichung).
- Zusätzlich geprüft: PNG-Datei als Textur (`r8Unorm`, Mipmaps, `repeat`), Fehlermeldungen bei fehlender Textur, fehlendem Attribut und unbekanntem JSON-Schlüssel.
- `scripts/tests/test_shader_compare.py`: 20 Tests grün (Decoder für alle Filter, Farbtypen, Bittiefen, Adam7, Palette/`tRNS`, defekte Dateien; Metriken; Kommandozeile; Gegenprobe mit `sips`).

## Grenzen

- **Ein Zeichenaufruf**, ein Farbziel (`rgba8Unorm`), optional Tiefe `depth32Float`. Kein MSAA, kein Stencil, keine Compute-Shader, keine Geometry/Tessellation (kommen im Cache nicht vor).
- **Bindings:** Uniform-Puffer, 2D-Texturen und Sampler, jeweils für Vertex- und Fragmentstufe. Keine Cube-/Array-/3D-Texturen, keine Storage-Puffer, keine Argument-Buffer, keine Spezialisierungskonstanten. Der Sampler wird über die Textur beschrieben (`samplerSlot`); Vergleichssampler und Anisotropie fehlen.
- **Texturformate:** `rgba8Unorm`, `rgba8Unorm_srgb`, `r8Unorm`. Es gibt keine komprimierten Formate (BCn/ASTC) und keine Float-Texturen. PNG-Dateien werden über Core Graphics als vormultipliziertes sRGB-RGBA geladen; bei transparenten Pixeln ändern sich dadurch die Farbwerte. `r8Unorm` nimmt den Rotkanal.
- **Vertexformate** nur die oben genannten; keine gepackten Formate (`10_10_10_2`).
- **Clipspace:** Standardmäßig unverändert. Ob der Cache-Shader `--flip-vert-y` und/oder `--fixup-clipspace` braucht (Ryujinx arbeitet mit Vulkan-Konventionen und Viewport-Tricks), ist nicht geklärt und muss pro Vergleich festgelegt werden. Die Option wird je Stufe in der Spec gesetzt.
- **Renderzustand** kommt aus der JSON-Datei, nicht aus dem Cache (`shared.data` enthält Spezialisierungszustand, der hier nicht ausgewertet wird).
- Die Zuordnung der Eingaben (welches Attribut ist Position, was steht in welchem Uniform-Float) ist von Hand aus der MSL gelesen; das Harness leitet sie nicht ab.
- Die Reflexions-API (`MTLArgument`) ist ab macOS 13 als veraltet markiert; der Build zeigt dazu Warnungen, funktioniert aber.
- Der Renderer nimmt `storageModeShared` an (Apple-Silicon-GPU); auf Intel/diskreten GPUs fehlt die Synchronisation vor dem Auslesen.
- Offen: ein echter Unity-Vergleich. Die Metriken stehen, aber die Schwellen (z. B. 1 bis 3 Stufen pro Kanal durch Rundung, Interpolation, Farbraum) sind noch nicht an einem portierten Shader kalibriert.
