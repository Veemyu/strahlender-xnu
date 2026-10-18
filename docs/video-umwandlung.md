# Video-Umwandlung

## Quelle und Messmethode

Untersucht wurden alle 18 WebM-Dateien unter `work/romfs/Data/StreamingAssets/Movie` mit ffprobe. Alle sind VP8, 1280×720, 30 fps, `yuv420p`; keine Quelle enthält eine Audiospur. Bitraten sind die von ffprobe gemeldeten mittleren Container-Bitraten. Dateigrößen sind MiB (1 MiB = 1.048.576 Byte).

| Datei (relativ zu Movie/) | Codec | Auflösung | FPS | Pixelformat | Dauer (s) | Bitrate (kbit/s) | Größe (MiB) | Audio |
|---|---:|---:|---:|---|---:|---:|---:|---|
| dia/Ending/movie_dia_ed_female_00.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 993.1 | 35.52 | nein |
| dia/Ending/movie_dia_ed_female_01.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.1 | 35.41 | nein |
| dia/Ending/movie_dia_ed_female_02.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.6 | 35.43 | nein |
| dia/Ending/movie_dia_ed_female_03.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 991.5 | 35.46 | nein |
| dia/Ending/movie_dia_ed_male_00.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.3 | 35.42 | nein |
| dia/Ending/movie_dia_ed_male_01.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 989.9 | 35.40 | nein |
| dia/Ending/movie_dia_ed_male_02.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 989.6 | 35.39 | nein |
| dia/Ending/movie_dia_ed_male_03.webm | VP8 | 1280×720 | 30 | yuv420p | 300.000 | 990.5 | 35.42 | nein |
| dia/Opening/movie_dia_en_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1500.1 | 18.97 | nein |
| dia/Opening/movie_dia_fr_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1499.2 | 18.96 | nein |
| dia/Opening/movie_dia_ge_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1496.7 | 18.93 | nein |
| dia/Opening/movie_dia_it_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1495.3 | 18.91 | nein |
| dia/Opening/movie_dia_jp_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1559.4 | 19.72 | nein |
| dia/Opening/movie_dia_ko_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1553.3 | 19.64 | nein |
| dia/Opening/movie_dia_op_loop.webm | VP8 | 1280×720 | 30 | yuv420p | 4.000 | 1934.3 | 0.92 | nein |
| dia/Opening/movie_dia_si_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1502.0 | 18.99 | nein |
| dia/Opening/movie_dia_sp_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1498.6 | 18.95 | nein |
| dia/Opening/movie_dia_tr_op.webm | VP8 | 1280×720 | 30 | yuv420p | 106.067 | 1503.0 | 19.00 | nein |

Auf dem Mac waren `libx265`, `hevc_videotoolbox`, `libx264` und `h264_videotoolbox` verfügbar. Verglichen wurden der 4-s-Loop und ein 300-s-Endvideo. Die Wandzeit umfasst den vollständigen ffmpeg-Aufruf. SSIM ist der Gesamtwert, PSNR der Mittelwert; Referenz war jeweils dieselbe dekodierte Quelle. Es wurde nichts abgespielt oder visuell beurteilt. Alle Befehle schlossen Audio mit `-an` aus.

| Quelle | Variante | Ausgabe (MiB) | Kodierung (s) | SSIM | PSNR (dB) |
|---|---|---:|---:|---:|---:|
| Loop, 4 s | libx265 CRF 14 | 2.10 | 3.49 | 0.982360 | 36.60 |
| Loop, 4 s | libx265 CRF 18 | 1.29 | 2.38 | 0.980649 | 36.54 |
| Loop, 4 s | libx264 CRF 14 | 2.45 | 0.99 | 0.982428 | 36.57 |
| Loop, 4 s | hevc_videotoolbox `-q:v 75` | 1.48 | 0.69 | 0.979559 | 36.50 |
| Ending, 300 s | libx265 CRF 14 | 99.19 | 133.43 | 0.988261 | 40.68 |
| Ending, 300 s | libx265 CRF 18 | 50.24 | 99.06 | 0.986286 | 40.50 |
| Ending, 300 s | libx264 CRF 14 | 138.08 | 54.38 | 0.988603 | 40.68 |
| Ending, 300 s | hevc_videotoolbox `-q:v 75` | 62.98 | 29.15 | 0.982772 | 40.20 |
| Ending, erster 10-s-Ausschnitt | libx265 `lossless=1` | 16.19 | 9.43 | 0.992953 | 45.47 |

## Empfehlung und Skript

`scripts/video_convert.sh` nutzt standardmäßig `libx265` CRF 18, MP4 mit `hvc1`, `yuv420p` und `+faststart`; CRF 14 ist als Profil verfügbar. VideoToolbox war über dreimal schneller als CRF 18, lieferte beim langen Test aber rund 25 % größere Ausgabe und niedrigere SSIM/PSNR-Werte. Deshalb ist die gemessene Qualitäts-/Größenbalance nicht vergleichbar genug für das Standardprofil. CRF 18 erzeugte in beiden Stichproben größere Dateien als die VP8-Quelle (rund 40 % mehr); Platzersparnis wird daher nicht zugesichert.

Die 18 Quellen belegen zusammen 478.591.999 Byte (456,42 MiB). Hochgerechnet mit dem größen-gewichteten CRF-18-Verhältnis der beiden Stichproben (1,414) ergibt sich ungefähr **645 MiB (677 MB)** für alle Zieldateien. Das ist eine grobe, inhaltsabhängige Schätzung; die 106-s-Opening-Dateien wurden nicht einzeln kodiert.

Eine Neukodierung einer bereits verlustbehafteten VP8-Quelle ist nie verlustfrei gegenüber dem ursprünglichen Bildsignal. `lossless=1` bewahrt allenfalls den dekodierten Eingang der Neukodierung, stellt verlorene VP8-Information nicht wieder her. Hardware-Decodierung auf iPad und Mac ist eine Annahme des Nutzers, kein Messergebnis.

Aufruf: `scripts/video_convert.sh QUELLORDNER ZIELORDNER [h265-crf14|h265-crf18]`. Das Skript erhält Ordnerstruktur und Basisnamen, protokolliert SHA-256 und Größen in `video-manifest.json` im Zielordner, überspringt unveränderte Einträge und bricht bei Fehlern ab. Ein H.264-Fallback ist absichtlich nicht vorgesehen.
