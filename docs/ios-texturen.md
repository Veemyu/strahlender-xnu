# iOS-Texturen: BC → ASTC beim Bauen (Todo `ap-ios-textures`)

> **Hinweis (Stand 2026-10-20):** `scripts/bundle_retarget.py` ist auf `main` entfernt (nur Branch `unity`); die Schritte zur Plattformkennung sind historisch. `scripts/texture_transcode.py` bleibt.

Stand: 2026-10-19. Ziel: Die Karten-Bundles des Spiels enthalten BC1/BC3/BC4/BC5/BC7 (DXT). Apple-GPUs (iPhone, iPad) unterstützen BC nicht, Unity meldet auf iOS je Textur „format is not supported, decompressing texture“ und danach „Failed to decompress“ (Zone 422: 1.884 Meldungen, `docs/player-build-1.md`, Abschnitt 6). Lösung: `scripts/texture_transcode.py` wandelt die Texturen **beim Bauen** nach ASTC um. Alle Zahlen stammen aus Läufen auf dem Entwicklungsrechner (Apple M1 Pro, 8 Kerne); es sind keine Spieldaten im Repo.

## Ergebnis in Kürze

| Frage | Ergebnis |
|---|---|
| Werkzeuge | kein Homebrew nötig: `tools/pydeps` enthält `astc_encoder` (Python-Anbindung von ARM astcenc, aarch64-NEON), `texture2ddecoder` (BC-Dekodierer), `UnityPy`, `Pillow`. `astcenc` per `brew` wurde nicht installiert. |
| Zielformat | **ASTC 6×6** für Farbtexturen (3,56 Bit/Pixel, gleiche Wahl wie die Originaltexturen von Figuren und UI), **ASTC 4×4** für BC4/BC5 (Normal-/Einkanalmaps). Wählbar: `--texture-format 4x4\|6x6\|8x8\|off`. |
| Texturspeicher Zone 422 (`area001`, 208 Texturen) | **46,4 MiB → 25,5 MiB** (Unity-Laufzeitzähler `Profiler.GetRuntimeMemorySizeLong`, macOS-Editor 6000.3.26f1) |
| Qualität | PSNR gegen die dekodierte BC-Quelle, 50 Texturen, Hauptstufe: **Median 46,2 dB**, Mittel 47,8, Minimum 35,1 dB (Qualität `medium`). In Unity per GPU-Blit gemessen (alle 208 Texturen, 128×128): Median 43,6 dB, Minimum 31,7 dB. |
| Dauer | `area001` (205 BC-Texturen, 46,7 MB roh) **24 bis 26 s** auf einem Kern (`medium`), 10 s mit `fast`. Teilmenge `ipad-start` (5 Bundles): 24 s. Zweiter Lauf: 0,8 s (nichts mehr zu tun). |
| Größe auf der Platte | wächst, weil ASTC sich unter LZ4 schlechter packen lässt als BC: `area001` 23,4 MB → 36,7 MB; `ipad-start` gesamt 34,6 MB → 47,9 MB. Das ist Plattenplatz, nicht Arbeitsspeicher. |

## Was das Skript tut

`scripts/texture_transcode.py` (Aufruf mit `PYTHONPATH=tools/pydeps`):

1. Liest ein UnityFS-Bundle mit UnityPy und findet alle `Texture2D` mit Format DXT1 (BC1), DXT5 (BC3), BC4, BC5, BC7 sowie `DXT1Crunched`/`DXT5Crunched`.
2. Dekodiert **jede Mip-Stufe einzeln** (`texture2ddecoder`, BGRA) und kodiert sie mit astcenc (`astc_encoder`) als ASTC. Die Mip-Kette der Vorlage bleibt also erhalten (kein neu berechnetes Mip-Chain), Breite, Höhe und Mip-Anzahl ändern sich nicht. Ausnahme: Crunch-Texturen (selten, hier ein 4×4-Platzhalter) werden nur in der Hauptstufe dekodiert, die Mips entstehen per Box-Filter.
3. Setzt `m_TextureFormat` (ASTC_4x4 = 48, 5x5 = 49, **6x6 = 50**, 8x8 = 51; dieselben Kennungen wie die ASTC-Texturen im Spiel) und `m_CompleteImageSize`. Namen, PathIDs, `m_ColorSpace`, Wrap/Filter/Aniso, `m_IsReadable` und alle übrigen Felder bleiben unangetastet. Der sRGB-Flag der Textur wählt das astcenc-Profil (`LDR_SRGB` bzw. `LDR`).
4. **Streaming bleibt erhalten:** Die Texturdaten liegen in der `.resS`-Datei des Bundles; sie wird neu aufgebaut (neue Daten an derselben Stelle der Reihenfolge), `m_StreamData.offset/size` werden gesetzt, **auch bei unveränderten Texturen**, deren Offset sich verschiebt (ein Test deckt das ab). Nutzt ein anderes Objekt (Mesh, AudioClip, VideoClip, …) dieselbe `.resS`, wird stattdessen nur angehängt; der alte Bereich bleibt als Totraum.
5. Schreibt das Bundle mit den ursprünglichen Flags (LZ4HC, Blockinfo am Anfang), sodass `scripts/bundle_retarget.py` es weiter lesen und patchen kann. Die Plattformkennung bleibt unverändert (gemessen).

Nicht umgewandelt (und gezählt/gemeldet): ASTC, RGBA32, Alpha8 und andere iOS-taugliche Formate, BC6H (HDR), Cubemap, Texture2DArray, Texture3D. In `area001` kommen sie nicht vor (nur Alpha8 ×1 und RGBA32 ×2, beide iOS-tauglich). Ob andere Bundles BC6H enthalten, ist nicht ausgewertet.

### Warum diese Formate

- **ASTC 4×4** hat 8 Bit/Pixel, also so viel wie BC3/BC7 und **doppelt so viel wie BC1**. Gemessen: `area001` wüchse von 46,7 MB auf **54,4 MB**. Für das Ziel „Texturspeicher klein“ ungeeignet, nur für Daten-/Normalmaps (BC4/BC5) und als Option für maximale Qualität (PSNR Median 61,6 dB, Mittel 62,5 dB).
- **ASTC 6×6** (3,56 Bit/Pixel): 24,8 MB statt 46,7 MB (−47 %), Median 46,2 dB. Standard. Das ist auch, was das Spiel für Figuren und UI nutzt (`ASTC_RGB_6x6`).
- **ASTC 8×8** (2 Bit/Pixel): 13,9 MB, aber Median nur 39,5 dB (Qualität `fast`); als Notbremse für die Speicherbudget-Planung, nicht als Standard.
- Qualität (`--quality`): `medium` ist Standard. `fast` kostet rund 1 dB (Median 43,8 statt 46,2 dB bei 6×6) und spart rund 60 % der Zeit.

| Variante (`area001`, nur Textur-Nutzdaten) | Texturbytes | PSNR Median | Zeit |
|---|---|---|---|
| BC-Original | 46,7 MB | – | – |
| ASTC 4×4, medium | 54,4 MB | 61,6 dB | 14 s |
| **ASTC 6×6, medium** | **24,8 MB** | **46,2 dB** | 26 s |
| ASTC 6×6, fast | 24,8 MB | 43,8 dB | 10 s |
| ASTC 8×8, fast | 13,9 MB | 39,5 dB | 11 s |

(Zeiten bei parallel laufenden Messungen, daher ungefähr.) Der hohe PSNR bei 4×4 kommt daher, dass die BC-Quelle selbst in 4×4-Blöcken mit wenigen Farben codiert ist. PSNR misst die Abweichung gegen die **dekodierte BC-Quelle**, nicht gegen ein Original, das es nicht gibt. 99 dB in den Tabellen bedeuten identisch (flache Texturen).

## Aufruf

```
export PYTHONPATH=tools/pydeps
scripts/texture_transcode.py info    BUNDLE                       # Formate und Größen
scripts/texture_transcode.py bundle  QUELLE ZIEL [--block 6x6] [--quality medium]
scripts/texture_transcode.py tree    ORDNER [--list DATEI] [--jobs N] [--dry-run]
scripts/texture_transcode.py psnr    QUELLE ZIEL --samples 50     # nur Zahlen
```

`tree` schreibt je Bundle eine neue Datei und benennt sie über die alte (ein APFS-Klon des Originals bleibt unberührt). `--list` (Teilmenge, gleiche Datei wie `--bundle-subset`, Pfade relativ zum Ordner) und `--dry-run` (zählt BC-Texturen, schreibt nichts) sind **selektives Transkodieren**; `--jobs` verteilt Bundles auf Prozesse (Standard: halbe Kernzahl).

### In der Build-Pipeline

In der Stufe `assets` läuft der Schritt **nach** dem Setzen der Plattformkennung und vor dem Kopieren von Videos/Stammdaten, wenn `--texture-format` nicht `off` ist. Standard: `6x6` bei Bundle-Plattform `ios` (`--target ios`), sonst `off` (macOS-GPUs können BC). Beispiel für das iPad:

```
scripts/build_all.sh --only assets --target ios --bundle-subset scripts/subsets/ipad-start.txt
scripts/build_all.sh --only assets --target ios --texture-format 4x4      # alle Bundles, beste Qualität
```

**Idempotenz:** Ein Bundle ohne BC-Texturen bleibt unverändert; ein zweiter Lauf ändert nichts (0,8 s für die Teilmenge, gemessen). Zusätzlich enthält der Marker-Hash der Stufe `assets` (`work/.stages/assets.json`) jetzt `texture_transcode.py` und das gewählte Format; ein Wechsel des Formats erzeugt die Stufe neu. Ein bereits transkodiertes Bundle lässt sich nicht in ein anderes ASTC-Format „umbauen“ (kein BC mehr in der Quelle): für einen Formatwechsel `--force` bzw. die Stufe neu aus den Original-Bundles erzeugen.

## Prüfungen

1. **Python-Roundtrip** (`scripts/tests/test_texture_transcode.py`, nur synthetische Texturen und ein handgebautes Mini-Bundle): Mip-Layout und Größen für 4×4/6×6/8×8 auch bei Maßen, die kein Vielfaches des Blocks sind, PSNR-Mindestwerte, `.resS` lückenlos und die unveränderte Textur mit verschobenem Offset byte-gleich, Idempotenz, Listen-/Probelauf-Optionen, Weiterverarbeitung mit `bundle_retarget` (Plattform bleibt 38, lässt sich auf 9 setzen). Beim Schreiben der Tests fiel ein echter Fehler auf (unveränderte Texturen mit verschobenem Offset wurden nicht neu geschrieben); er ist behoben.
2. **PSNR gegen die dekodierte BC-Quelle**, 50 Texturen aus `area001` (6×6, `medium`): Minimum 35,06 / Median 46,20 / Mittel 47,79 dB; Qualität `fast`: 34,38 / 43,80 / 45,58 dB.
3. **Unity-Test auf macOS** (Metal, ASTC unterstützt), eigener Batchmodus-Lauf im Wegwerfprojekt `work/unity-astc-test` (nicht im Haupt-Editor): `scripts/astc_bundle_check.cs` lädt das Original- und das transkodierte `area001` nacheinander (Plattformkennung macOS) und vergleicht. Ergebnis: **208 von 208 Texturen laden**; vorher Alpha8 ×1, BC5 ×2, BC7 ×28, DXT1 ×55, DXT5 ×119, DXT5Crunched ×1, RGBA32 ×2; nachher Alpha8 ×1, **ASTC_6x6 ×203, ASTC_4x4 ×2**, RGBA32 ×2; Name, Größe und Mip-Anzahl bei allen 208 gleich (Mips 5 bis 11); Laufzeitspeicher 46,4 → 25,5 MiB; GPU-Vergleich Median 43,6 dB, Mittel 45,0 dB, Minimum 31,7 dB. **Nicht geprüft:** Anzeige auf dem iPad (kein Gerät in diesem Lauf) und eine Sichtprüfung des Bildes.
4. **Größe/Dauer der iPad-Teilmenge** (`scripts/subsets/ipad-start.txt`, 5 Bundles plus Katalog):

| | vorher | nachher |
|---|---|---|
| Gesamtgröße (Bundles + Katalog) | 34.565.820 Byte (34,6 MB) | 47.886.074 Byte (47,9 MB) |
| Texturbytes in den umgewandelten Bundles | 48,1 MB | 26,2 MB |
| Dauer | – | 24,3 s gesamt (4 Prozesse; `area001` 23,8 s, `fc0001_11` 0,8 s) |

   Umgewandelt werden dort nur `area001` (205 Texturen) und `fc0001_11` (eine BC5-Textur; sie wäre auf iOS ebenfalls ausgefallen). Die übrigen drei Bundles (Figur `fc0001_00`, `pc_parts`, UI) tragen schon ASTC 6×6.

## Hochrechnung für alle Bundles

Trockenlauf `tree --dry-run` über das gesamte `AssetAssistant` (14.053 Dateien, 3,8 GB, 30 s): **2.838 Bundles** enthalten BC-Texturen, zusammen **24.690 Texturen mit 5,21 GB** roher BC-Daten; 11.214 Bundles haben keine. Aus `area001` (rund 0,5 bis 0,55 s je MB roher BC-Daten auf einem Kern, `medium`) folgt für alle: **rund 45 bis 50 Minuten Rechenzeit, bei 4 bis 6 Prozessen rund 10 bis 15 Minuten** (geschätzt, nicht gemessen; `fast` etwa ein Drittel davon). Texturspeicher aller Bundles zusammen: rund 5,2 GB (BC) → rund 2,8 GB (ASTC 6×6, Verhältnis von `area001`); wegen der Größe auf der Platte: Bundles insgesamt voraussichtlich rund 1,5-fach (≈ 5,5 bis 6 GB statt 3,8 GB; geschätzt). Entscheidend für das iPad ist der gleichzeitig geladene Anteil (zonenweise), nicht die Summe; gegen das Planungsbudget „Texturen ca. 1,2 GB“ (`docs/ipad-messung-1.md`) sind die 25,5 MiB der Zone 422 unkritisch.

## Abwägung: Alternativen

- **Unity-Editor-Transcode** (`TextureImporter`, `EditorUtility.CompressTexture`) arbeitet auf importierten Assets im Projekt. Die Texturen liegen aber fertig in Fremd-Bundles, die nicht importiert werden; der Weg wäre „Bundle-Texturen auslesen, ins Projekt importieren, neu bauen“ und verlöre PathIDs und Referenzen. Nicht gewählt.
- **Laufzeitkonvertierung** im Player: Ein ASTC-Encoder steht im Player nicht zur Verfügung (`Texture2D.Compress` ist kein Weg, BC nach ASTC zu übersetzen, und ein GPU-Blit kodiert nicht). Das Ausweichen auf RGBA32 (Dekodieren beim Laden) verachtfacht bei BC1 und vervierfacht bei BC3/BC7 den Speicher (Zone 422: grob 180 MiB statt 25 MiB, aus dem Verhältnis geschätzt, nicht gemessen) und kostet Ladezeit. Als Notlösung denkbar, nicht empfohlen.
- **Offline im Bundle (gewählt):** keine Laufzeitkosten, kleinster Speicher, PathIDs und Referenzen bleiben.

## Grenzen und offene Punkte

- Kein Lauf auf dem iPad mit den umgewandelten Bundles und keine Sichtprüfung des Bildes; der macOS-Test belegt Laden, Format und Speicher.
- Der Lauf der Stufe `assets` über `scripts/build_all.sh` (echt, nicht Trockenlauf) wurde nicht ausgeführt, um die Marker und `unity/Assets/StreamingAssets` des laufenden Editors nicht zu ändern; getestet sind der Trockenlauf des Skripts (Planzeile `Texturformat`), `bash -n` und der Aufruf `texture_transcode.py tree` direkt auf einer geklonten Teilmenge.
- Normalmaps: BC5 wird als RGBA mit B = 0, A = 255 nach ASTC 4×4 kodiert; die Abtastung entspricht damit der von BC5 (RG gültig). Ein eigener ASTC-Normalmapmodus (`MAP_NORMAL`) wäre qualitativ besser, ändert aber die Abtastsemantik und wurde nicht verwendet.
- BC6H (HDR) und Cubemaps werden nicht angefasst; falls vorhanden, bleiben sie auf iOS fehlerhaft (nicht ausgewertet).
- Das Ergebnis hängt von UnityPy ab (Version in `tools/pydeps`); das Schreiben der Serialized Files läuft über dessen Typbaum-Schreiber (für Texturobjekte getestet, übrige Objekte bleiben als Rohdaten unverändert).
