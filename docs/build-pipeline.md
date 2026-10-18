# Build-Pipeline: Werkzeuge und Entschlüsselung

Einstiegspunkt ist `scripts/build_all.sh` (bash 3.2-kompatibel, Hilfslogik in `scripts/build_helpers.py`). Umgesetzt sind bisher die Stufen `tools` und `extract`; die übrigen Stufen aus `docs/kernziel.md` (masterdata, assets, video, audio, unity, deploy) melden „noch nicht implementiert“ (Exit-Code 10).

## Aufruf

```
scripts/build_all.sh tools
scripts/build_all.sh extract --xci <Basisspiel.xci> --nsp <Update.nsp> --keys <Ordner> [--work <Ordner>] [--force]
scripts/build_all.sh --stage tools,extract <Optionen>     # oder --stage all
```

Stufen lassen sich als Unterbefehl oder per `--stage` (kommagetrennt, mehrfach erlaubt) wählen. Optionen für `extract`:

| Option | Bedeutung |
|---|---|
| `--xci`, `--nsp` | Eingaben. Die NSP ist optional; ohne sie entsteht nur der Stand des Basisspiels. |
| `--keys <Ordner>` | Ordner mit `prod.keys` und `title.keys`. |
| `--prod-keys`, `--title-keys` | Einzeldateien statt `--keys`; `title.keys` ist nur Rückfall. |
| `--work` | Zielordner, Standard `work/build`. |
| `--force` | Neu erzeugen, auch wenn `manifest.json` passt. |
| `--keep-nca` | Entpackte NCAs (mehrere GB) nicht löschen. |

Umgebungsvariablen: `TOOLS_DIR` (Standard `tools/`), `MIN_FREE_GB` (Standard 25), `UNITY_HUB`, `UNITY_EDITOR_ROOT`, `DEVELOPER_DIR`.

## Stufe `tools`

Prüft oder erzeugt alles lokal, nichts wird systemweit installiert:

- **hactool** (github.com/SciresM/hactool): fehlt das Binary unter `tools/hactool`, wird geklont (mit mbedtls-Submodul), `config.mk` aus dem Template angelegt und per `make` gebaut (Log in `tools/hactool/build.log`).
- **ffmpeg**, **python3 ≥ 3.9**: nur Prüfung.
- **Unity Hub CLI** und **Editor 6000.3.26f1** samt iOS-Modul: nur Prüfung mit klarer Meldung, keine Installation.
- **Xcode** unter `/Applications/Xcode.app`; `DEVELOPER_DIR` wird darauf gesetzt, sofern nicht schon gesetzt.

Fehlt etwas, werden alle Lücken aufgelistet und das Skript endet mit Exit-Code 4.

## Stufe `extract`

1. Secure-Partition der XCI und Inhalt der NSP nach `<work>/nca-base` bzw. `<work>/nca-update` entpacken.
2. Jede NCA per `hactool -i` lesen; nur Content-Type, Titel-ID, Master-Key-Revision, Rights-ID und Größe werden übernommen. Das Base-Programm ist die größte Program-NCA der XCI, das Update-Programm die Program-NCA der NSP mit derselben Titel-ID. Dateinamen spielen keine Rolle.
3. Titlekey: Das Ticket (`.tik`) in der NSP wird geparst (Signaturtyp bestimmt die Offsets, Rights-ID und Typ stehen im Ticketkörper); bei einem Common-Ticket sind die ersten 16 Byte des Schlüsselblocks der Titlekey. Gibt es kein passendes Ticket, wird `title.keys` nach der Rights-ID durchsucht.
4. Update per `--basenca` auf die Base-NCA anwenden; ExeFS und RomFS landen in `<work>/exefs` und `<work>/romfs` (zuerst in einem Staging-Ordner, am Ende umbenannt).
5. Version aus der cnmt (Titelversion) und `control.nacp` (Anzeigeversion), dann `<work>/manifest.json`: Titel-ID, Versionen, Eingabegrößen, SHA-256/SHA-1 von `exefs/main`, SHA-256 aller ExeFS-Dateien, Anzahl und Gesamtgröße der RomFS-Dateien. Kein Schlüsselmaterial.
6. Temporäre NCAs werden gelöscht (auch bei Fehlern), außer mit `--keep-nca`.

**Idempotenz:** Passt `manifest.json` zu den Eingabegrößen und zu den vorhandenen Ergebnissen (Hash von `exefs/main`, RomFS-Zahlen), wird die Stufe übersprungen.

**Schutz vor Schlüssel-Leaks:** hactool schreibt Schlüsselwerte nach stdout und stderr. Das Skript verwirft beides vollständig; sichtbar sind nur die gefilterten Felder. Der Titlekey liegt nur in einer Shell-Variable und wird hactool als Argument übergeben (kurzzeitig in der Prozessliste desselben Benutzers sichtbar).

**Platz:** Vorab wird geprüft, ob nach dem Lauf mindestens `MIN_FREE_GB` frei bleiben (Bedarf ca. 2 × XCI + NSP). Spitzenbedarf in der Praxis rund 12 GB.

## Exit-Codes

0 ok · 2 Aufruf · 3 Eingabedatei fehlt · 4 Werkzeug fehlt oder Build fehlgeschlagen · 5 hactool-Fehler · 6 Schlüssel/Titlekey · 7 passende NCA nicht gefunden · 8 zu wenig Platz · 9 Ergebnisprüfung fehlgeschlagen · 10 Stufe nicht implementiert.

## Tests

- `python3 -m unittest scripts/tests/test_build_helpers.py` (18 Tests, nur synthetische Daten: Ticket-Parser für alle Signaturtypen, title.keys, NCA-Info ohne Schlüsselzeilen, NCA-Auswahl, cnmt/NACP, Manifest).
- `bash -n scripts/build_all.sh` ist sauber; `shellcheck` ist auf diesem Rechner nicht installiert und wurde nicht ausgeführt.

## Testergebnis (Stand 2026-10-18, macOS arm64)

Lauf mit den vorhandenen Dateien in ein neues Verzeichnis `work/build-test` (inzwischen gelöscht):

| Schritt | Ergebnis |
|---|---|
| `tools` (alles vorhanden) | unter 1 s, alle Prüfungen OK |
| `tools` mit frischem Klon und Build von hactool in separatem Ordner | ca. 8 s |
| `extract` komplett | 31 s und 34 s (zwei Läufe; davon etwa 25 s für Update-Anwendung samt RomFS) |
| zweiter Aufruf mit passendem Manifest | 0,3 s, übersprungen |
| Fehlerfälle | fehlende XCI/Keys Exit 3, fehlender Parameter Exit 2, leere Keys Exit 6 (Aufräumen funktioniert), unbekannte Stufe Exit 10 |

Vergleich mit dem früher manuell erzeugten Stand:

- `exefs/main`: SHA-256 und SHA-1 identisch; alle fünf ExeFS-Dateien identisch.
- `romfs`: 18 022 Dateien / 5 061 234 364 Byte gegenüber 18 028 / 5 061 271 252 im alten `work/romfs`. Der Unterschied sind genau sechs `.DS_Store`-Dateien (6 × 6148 Byte), die Finder dort nachträglich angelegt hat. Ohne sie ist `diff -rq` leer, der Inhalt ist also byte-identisch.
- Ermittelte Version: Titelversion 393216, Anzeigeversion 1.3.0.
