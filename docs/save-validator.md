# Save-Validator (`scripts/bdsp_save.py`)

## Zweck
Eigenständiger, abhängigkeitsfreier Prüfer für BDSP-`SaveData.bin` und `Backup.bin` (gleiches Format).
Er liest Version und Größe, berechnet den MD5-Hash so, wie es das Spiel laut `docs/save-spec-entwurf.md`
tut, und enthält die Top-Level-Feldtabelle (Offset, Größe, Name, Typ) für Version 0x34.
Die Struktur stammt allein aus unserer Spec; es wurde kein Fremdcode übernommen.

## Aufruf
```
python3 scripts/bdsp_save.py check <datei> [--fields]
python3 scripts/bdsp_save.py dump-fields
python3 scripts/bdsp_save.py fix-hash <eingabe> <ausgabe>
python3 -m unittest discover -s scripts/tests -v
```
- `check`: Exit-Code 0 = Größe und Hash stimmen, 1 = Abweichung, 2 = nicht prüfbar (z. B. unbekannte Version, abgeschnitten).
- `fix-hash` schreibt nur in eine neue Ausgabedatei (bestehende Dateien und die Eingabe werden nie überschrieben).

## Grenzen
- Geprüft werden nur Version, Größe und Hash; die Inhalte der Unterstrukturen und die Pokémon-Kodierung werden nicht ausgewertet.
- Versionen > 0x34 sind unbekannt und werden gemeldet, nicht geraten. Versionen < 0x25 prüft das Spiel selbst nicht; der Validator meldet „nicht prüfbar“.
- Das Spiel füllt zu kurze Dateien beim Laden mit Nullen auf; der Validator behandelt abgeschnittene Dateien dagegen als Fehler.
- Dass die Dateigröße älterer Versionen exakt der BINARY_SIZE-Tabelle entspricht, ist nur für 0x34 an einer echten Datei belegt.
- Die Feldtabelle ist lückenlos und ergibt 0xEF0A4, Größen enthalten ggf. Padding (siehe offene Punkte in der Spec).
- Negative Versionswerte werden als vorzeichenbehaftetes `int` gelesen (wie in der Spec) und gelten als „< 0x25“. Ob das Spiel signed vergleicht, ist nicht geprüft.

## Testergebnis
- Unit-Tests (nur synthetisch erzeugte Bytes): 23 Tests, alle grün.
- Lokaler Lauf, nur lesend:

| Datei | Version | Größe | Größe passt | Hash gültig |
|---|---|---|---|---|
| `SaveData.bin` | 52 (0x34) | 979108 (0xEF0A4) | ja | ja |
| `Backup.bin` | 52 (0x34) | 979108 (0xEF0A4) | ja | ja |

## C#-Portierung (`unity/Assets/Scripts/Save`, Assembly `Xnu.Save`)
- Gleiche Logik als reine C#-Klassen ohne UnityEngine-Abhängigkeit (netstandard2.1, `System.Security.Cryptography.MD5`):
  `SaveLayout` (Konstanten, Größentabelle, Feldtabelle mit Name/Offset/Größe/Typ), `SaveValidator` (`ReadHeader`, `ExpectedSize`,
  `ComputeHash`, `StoredHash`, `VerifyHash`, `Validate` mit `SaveValidationResult` inkl. Fehlerliste) und `SaveWriter.FixHash`.
- `FixHash` arbeitet auf Byte-Arrays und gibt eine neue Kopie zurück; Eingaben werden nie verändert. Datei-I/O ist bewusst nicht enthalten.
- Fehlerverhalten wie in Python: `SaveFormatException` bei zu kurzer, abgeschnittener oder unbekannter Version; `Validate` wirft nie,
  sondern sammelt Befunde (`HashValid`/`SizeOk` sind `null`, wenn nicht prüfbar).
- Tests: `unity/Assets/Tests/EditMode/SaveValidatorTests.cs` (NUnit, nur synthetische Bytes, spiegelt die Python-Tests). Außerhalb von Unity
  wurden sie in einem Wegwerf-Projekt mit `dotnet test` ausgeführt (21 Tests grün); zusätzlich stimmen Version, Größe, Hash-Status und
  `FixHash`-Ergebnis auf synthetischen Fällen mit der Python-Implementierung überein, und die lokalen `SaveData.bin`/`Backup.bin` werden
  lesend als gültig erkannt (Version 0x34, 979108 Byte). Der Lauf im Unity-Editor (`run_tests`) steht noch aus.
