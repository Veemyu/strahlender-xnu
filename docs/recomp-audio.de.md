# Ton der nativen Rekompilation

Stand: 2026-10-20, nach der Umsetzung und den Hörproben. Auftrag: `todo/sound.md`, fünf Fragen aus `rc-audio`.
Nur die native Laufzeit; der Unity-Rebuild bleibt unberührt. Messdaten liegen unter `work/`.

## Ergebnis und Entscheidung

**Ein erster Tonpfad ist ohne eigenen Wwise-Mischer, Audio-Renderer oder Opus-Decoder möglich.**
Der rekompilierte Gast liefert bereits nichtleere PCM16-Puffer an `IAudioOut`.
Die Laufzeit verwirft diese Samples bisher und simuliert lediglich ihre Spieldauer.
Diese Puffer werden jetzt auf macOS und iPadOS über Audio Queue Services ausgegeben.
Der Nutzer hat auf beiden Geräten sauberen Ton bestätigt.
Diese Aussage gilt für die untersuchten Start-, Titel- und Feldszenen; Kämpfe und
das Spielende sind damit nicht abgedeckt.

## 1. Tatsächlich verwendete Dienste

Die IPC-Zähler zählen Anfragen einmal im Dispatcher (`ipc.c:ipc_count`);
`ipc_note(..., 0)` erhöht sie nicht nochmals.

| Aufruf | Mac, Variante B | iPad | Mac, Pokécenter |
|---|---:|---:|---:|
| `audout:u:1` (Öffnen) | 2 | 2 | 2 |
| `IAudioOut:7` (Anhängen) | 6.201 | 5.390 | 12.378 |
| `IAudioOut:8` (fertige Puffer) | 69.199 | 14.725 | 34.110 |
| `audren:u:4` (Gerätedienst) | 3 | 3 | 3 |
| `hwopus:1` (Arbeitspuffergröße) | 10 | 10 | 10 |
| `audren:u:0` (Renderer öffnen) | nicht protokolliert | nicht protokolliert | nicht protokolliert |
| `IHardwareOpusDecoder` (Dekodieren) | nicht protokolliert | nicht protokolliert | nicht protokolliert |

Quellen: `work/builds/mac-b-run9.log`,
`work/builds/ipad-recomp-20261020-134156.log`,
`work/recomp/qa/pokecenter-20261019-164824-a4/log_p1.txt`.
Das sind unterschiedliche Lauflängen und ältere Builds; die absoluten Anzahlen
sind keine Vergleichsmessung der Leistung. Für `audin:u` gibt es in diesen
Ergebniszeilen keinen Aufruf.

**Schluss:** In diesen Szenen mischt offenbar der Wwise-Code im Gast selbst.
Ein `audren:u`-Dienstzugriff allein belegt keinen genutzten Audio-Renderer.

## 2. Datenformate und PCM-Messung

Erneute lokale Header-Inventur, begrenzt auf
`work/romfs/Data/StreamingAssets/Audio/GeneratedSoundBanks/Switch`:

- 3.241 WEM-Dateien: alle RIFF/WAVE, Formatkennung `0xFFFF`.
- 2.859 Mono-, 382 Stereo-Dateien.
- Abtastraten: 32.000 Hz (2.337), 48.000 (371), 36.000 (344), 24.000 (162),
  6.000 (8), 44.100 (7), 16.000 (5), 8.000 (4), 12.000 (3).
- 696 Banks mit `BKHD`, Version 135.

`docs/daten-inventar.md` ordnet `0xFFFF` Wwise-Vorbis zu. Der hiesige
`ffprobe` erkennt bei der geprüften WEM-Datei die Containerdaten, benennt aber
keinen Decoder. Die Formatkennung allein ist kein Beweis für eine erfolgreich
dekodierbare Vorbis-Datei. Banks werden für den ersten Tonpfad nicht auf dem
Host dekodiert oder ersetzt.

Die zuschaltbare Messung `BDSP_AUDIO_PROBE=1` liest die an `IAudioOut`
übergebenen Deskriptoren und protokolliert nur Zahlen, keine Samples:
`work/builds/audio-probe-mac.log` (Mac, Variante A).
Beobachtet: 48.000 Hz, zwei Kanäle, ausgehandeltes PCM16,
4.096 Byte je Puffer, Offset 0. Ein Ausgabestrom liefert zunächst Nullen;
ein weiterer enthält bei Puffer 512 insgesamt 214.918 von 1.048.576 Samples
ungleich null, Betragsspitze 2.666 von 32.768.
Ein Puffer enthält 1.024 Stereo-Frames und entspricht 21,333 ms.
Diese erste Messung lief noch ohne Ausgabe; die anschließenden Hörproben stehen unten.

## 3. Host-Ausgabe und Aufwand

Umgesetzt: eigene kleine PCM-Ausgabe über Apples Audio Queue Services für macOS und
iPadOS. C-Schnittstelle, Kopie in begrenzte Hostpuffer, kein Gastzugriff und
keine Kernel-/IPC-Aufrufe aus dem Audio-Callback. Die API unterstützt lineares
PCM und das erneute Einreihen ausgegebener Puffer
([Apple: Audio Queue Services](https://developer.apple.com/documentation/audiotoolbox/audio-queue-services)).
Ein Callback bedeutet laut Apple noch nicht, dass ein Puffer bereits hörbar
abgespielt wurde; daher bleiben Callback und Gastfreigabe getrennt
([Apple: Output-Callback](https://developer.apple.com/documentation/audiotoolbox/audioqueueoutputcallback)).

Reihenfolge:

1. macOS: PCM-Ausgabe, begrenzte Warteschlange, Start/Stop/Schließen,
   Lautstärke und stummer Rückfall bei fehlendem Gerät sind umgesetzt.
   Kurzer Lauf mit PCM-Zählern und Hörprobe durch den Nutzer bestanden.
2. iPadOS: dieselbe Ausgabe und eine Audio-Session sind eingebunden.
   Beim Verlust des Vordergrunds oder einer Audio-Unterbrechung werden Hostpuffer
   gestoppt und verworfen; bei Rückkehr wird die angeforderte Wiedergabe fortgesetzt.
   Bibliothek und App gebaut, ein gezielter Gerätetest bestanden, keine Startschleifen.
   Die persönliche Signing-Projektdatei und der abgenommene Shader-Startpfad wurden nicht geändert.
3. Linux später: SDL3-Ausgabe hinter derselben PCM-Schnittstelle;
   kein eigener PulseAudio-/PipeWire-Client erforderlich, sofern SDL das Gerät öffnet.
4. Erst bei beobachteten zusätzlichen Dienstaufrufen Renderer-/Opus-Unterstützung
   planen. Der LAS-Quelltext `research/LASRecomp/runtime/services/audio.c`
   bestätigt als Referenz das Prinzip PCM-Warteschlange; keine Übernahme seines Mischers.

Ursprüngliche grobe Aufwandsschätzung, nicht gemessen: macOS ein Arbeitstag einschließlich
Lebenszyklus und Prüfung, iPadOS ein weiterer Arbeitstag einschließlich Gerätetest.
Ein eigener Audio-Renderer mit Stimmen, Effekten und Opus ist ein separates,
wesentlich größeres Vorhaben und derzeit nicht als Voraussetzung belegt.

## 4. Echtzeit-Taktung und Regressionen

Die vorhandene Freigabe nach Spieldauer und die Nullantwort bei leerer
Freigabeliste bleiben erhalten (`docs/recomp-qa.md`, Fehler 1 und 3;
`docs/recomp-ios.md`, Abschnitt 4.2). Keine sofortige Freigabe nach dem Kopieren
auf den Host: sonst kann Wwise seine Sperre dauerhaft halten.
Die Dauerrechnung verwendet jetzt die beim Öffnen ausgehandelten Werte.
Der Sicherheitsabstand von 5 ms und die Ereignissignalisierung bleiben erhalten.

Zu prüfen: Start/Stop und wiederholtes Öffnen ohne Ressourcenverlust,
Pufferüberlauf und Geräteausfall ohne Wwise-Endlosschleife,
Titel/Feld/Pokécenter ohne Hänger, keine unbegrenzt wachsende Audiolatenz.
Stumme Ausgabe muss die bisherigen Freigaben weiter bedienen.

## 5. Ton des Eröffnungsfilms

Alle 18 WebM-Dateien unter `work/romfs/Data/StreamingAssets/Movie/dia`
wurden mit `ffprobe -show_entries stream=codec_type,codec_name` untersucht:
jeweils genau ein VP8-Videostream, kein Audiostream.
Der deutsche Eröffnungsfilm dauert 106,067 s.
Der jetzige Movie-HLE berücksichtigt zwar ohnehin nur Videostreams, aber
ein FFmpeg-Audiodecoder würde diesen Dateien keine Tonspur hinzufügen.
Die Zuordnung des Filmtons zu einem Wwise-Ereignis ist noch ungeklärt.
Die kurzen Hörproben mit Überspringen des Intros ersetzen keinen vollständigen
Durchlauf des Films und keine Messung seiner Synchronität.

## Umsetzung und Prüfung

- `audio_output.c/.h`: Apple-Ausgabe, acht wiederverwendbare Hostpuffer mit
  jeweils höchstens 25 ms PCM, zusammen höchstens etwa 200 ms je Ausgabestrom.
  Der Callback gibt ausschließlich Hostpuffer frei. Bei voller Warteschlange wird
  die neue Hostkopie verworfen und gezählt; die Gastfreigabe bleibt zeitgesteuert.
- `services_audio.c`: PCM-Deskriptor mit Kapazität und Offset auswerten,
  Gastadressen über `G2H`, Pufferinhalt auf den Host kopieren, Ausgabe beim
  Schließen des Dienstobjekts freigeben. Der Zeitgeber kann geschlossene Objekte
  nicht mehr gleichzeitig lesen; die acht Registrierungsslots sind wiederverwendbar.
- `ios/app/app.m`: `AVAudioSession` mit Wiedergabekategorie und Vordergrund-/
  Unterbrechungsbehandlung. Frameworks werden über `deploy_ios.sh` eingebunden,
  ohne Änderung von `project.pbxproj`.
- Synthetischer C-Test über `scripts/tests/test_recomp_audio.py`: echte
  Dienstimplementierung mit nachgebildetem Host und Kernel. Prüft verzögerte
  Freigabe, Nulltag bei leerer Antwort, Mono/24-kHz-Takt, 5-ms-Mindestdauer,
  Offset, Grenzverletzungen, volle Gastwarteschlange und 24 Öffnen-/Schließen-Zyklen.
- Gesamtsuite: 309 Tests, 3 übersprungen, erfolgreich. `repo_check.py` erfolgreich.
- Mac: `work/builds/audio-output-mac.log`, 45 s, anschließend sauberer Ton vom
  Nutzer bestätigt. Zwei Ausgabeströme; beim bisher stillen Strom einmal eine
  verworfene Hostkopie beim Start, danach kein Wachstum dieses Zählers. Beim
  Strom mit Samples ungleich null keine verworfene Hostkopie.
- iPad: `work/builds/ipad-recomp-20261020-204619.log`, genau ein Lauf, 60 s,
  am Ende 60 fps, 39 Gastthreads, Footprint 2.202 MiB, `thermalState` 0.
  Beide Ausgabeströme ohne verworfene Hostpuffer; der zweite enthält bei 2.560
  Puffern 4.390.474 von 5.242.880 Samples ungleich null, Spitze 7.002.
  Sauberer Ton vom Nutzer bestätigt. Gate: 2.845 Pipelines in 362 ms bei warmem
  Cache, unveränderter Zähler oben links. Beendigung durch das vereinbarte
  60-s-Zeitlimit des Deploy-Skripts (Signal 15).

Der Gerätespielstand wurde vor der Installation unter
`work/recomp/audio/ipad-save-before-audio` gesichert. Nach der Installation
blieben RomFS und Spielstand erhalten; SaveData.bin, Backup.bin und user_id.hex
wurden mit der Sicherung verglichen. Daher war kein erneutes Kopieren nötig.

Umgebung beim direkten Start des Mac-Binarys bzw. über `RUN_ENV` auf dem iPad:

| Variable | Wirkung |
|---|---|
| `BDSP_AUDIO=0` | Stumme Ausgabe mit weiterhin zeitgesteuerter Gastfreigabe |
| `BDSP_AUDIO_GAIN=0.10` | App-Lautstärke 10 %; Bereich 0 bis 1, Standard 1; verändert keine Gerätelautstärke |
| `BDSP_AUDIO_PROBE=1` | PCM-Zahlen je Strom und Hostpufferzähler; keine Samples speichern |

Beide Hörproben liefen mit `BDSP_AUDIO_GAIN=0.10`.

## Noch offen

- Langfristige Qualität, vollständige Musik-/Effektabdeckung und gemessene Bild-Ton-Synchronität.
- Eindeutige Zuordnung der beiden `IAudioOut`-Objekte zu Spiel und Film.
- Gastformate und Dienstpfade in Kämpfen und beim Spielende.
- Echte iPad-Unterbrechungen, Hintergrund/Vordergrund und Gerätewechsel sind noch nicht von Hand geprüft.
- Nach einem Neustart der System-Audiodienste werden Audio-Queues noch nicht neu aufgebaut.
- Langzeitprüfung der Warteschlange und gezielter Geräteausfalltest.
- Linux bleibt vorerst stumm, wie mit dem Nutzer vereinbart.
