# NOTICE: übernommener Code (LASRecomp)

Dieses Verzeichnis enthält Code, der aus einem fremden Projekt übernommen und von uns verändert wurde.

| | |
|---|---|
| Projekt | LASRecomp |
| Repository | https://github.com/peiikai/LASRecomp |
| Stand der Übernahme | Commit `09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5` (kurz `09f8e5e`, einziger Commit des Klons) |
| Urheber | Peiikai |
| Lizenz | MIT, „Copyright (c) 2026 Peiikai“. Der Lizenztext liegt unverändert in [`LICENSE-LASRecomp`](LICENSE-LASRecomp). |
| Übernommene Dateien | `runtime/nvn/maxwell/translate.c` → `translate.c`, `runtime/nvn/maxwell/shader.h` → `shader.h` |
| Nicht übernommen | alles andere des Originals (Laufzeit, NVN-Renderer, `third_party/`, UI, Schriften, Rekompilierer, Tests) |

Die Lizenz des Originals nimmt Nintendo-Eigentum und die Drittkomponenten in dessen `third_party/` ausdrücklich aus. Davon ist hier nichts enthalten. Der Nutzer des Repositories hat die Übernahme ausdrücklich freigegeben.

Die beiden übernommenen Dateien trugen im Original keinen eigenen Copyright-Kommentar. Wir haben je einen Herkunftskommentar mit Verweis auf Lizenz und Commit an den Dateianfang gesetzt.

## Hinweis des Originals zur Entstehung

Das README des Originals bezeichnet das Projekt als „almost exclusively“ mit einer KI (Anthropic Claude über Claude Code) erstellt und von einem Menschen gelenkt, getestet und geprüft. Der Klon hat nur einen Commit, eine Entstehungsgeschichte gibt es nicht. Der Code kommt daher ohne Gewähr; wir prüfen ihn mit eigenen Tests und, in Teil 2, mit numerischen Vergleichen gegen die Ryujinx-Referenz.

In Kommentaren von `translate.c` werden die Decoder des Ryujinx-Projekts als Quelle für einzelne Feldlayouts genannt (HADD2/HMUL2/HFMA2, XMAD, LDC). Das README des Originals führt Ryujinx nicht als Quelle auf. Welche Teile aus Fremdwerken (Ryujinx, envytools) in Struktur oder Tabellen eingeflossen sind, lässt sich aus dem Klon nicht klären. Wir nennen beide deshalb in `../THIRD_PARTY_NOTICES.md`.

## Unsere Änderungen

Alle Änderungen in den übernommenen Dateien sind mit `XNU:` kommentiert.

### `translate.c`

1. **Abdeckungsmodus (`--survey`).** Neue Funktion `maxwell_translate_ex()` mit optionalem `Survey`-Zeiger. Ist er gesetzt, bricht `fail()` nicht beim ersten Problem ab, sondern trägt es in die Survey ein (Name, Beispielwort, Anzahl) und die Übersetzung läuft weiter. Unbekannte Opcodes werden nach den oberen 12 Bit gruppiert (`op<hex>`). Zusätzlich meldet `approx()` im Survey-Modus Stellen, an denen der Übersetzer still einen Platzhalter erzeugt (unbekannte Attributadresse). `maxwell_translate()` behält Signatur und Verhalten.
2. **Codeende.** Der Übersetzer erkannte das Padding hinter dem letzten EXIT (unbedingter Sprung auf sich selbst) nur mit der Verschiebung −8. Der Unity-Compiler schreibt das Ziel auf das davorliegende Scheduling-Wort (−16). Dann wurden die Compiler-Konstanten hinter dem Code als Instruktionen gelesen. Jetzt gilt: unbedingtes BRA, dessen normiertes Ziel die eigene Position ist.
3. **Eingabeprüfung.** Zu kleine Blobs ergeben einen Fehler statt eines Zugriffs außerhalb des Puffers.
4. **Entfernt, weil LAS-spezifisch:** die Debug-Haken `maxwell_dbg_*` (Registerausgabe in ein Farbziel, Positions-Dump-Puffer 29), das `getenv("LARECOMP_NO_DISCARD")`, der „Tint“-Epilog für Farbziel 0 samt Puffer 19 und `uses_tint`.
5. **`LARECOMP_SAVE_MSL` → `ShaderKey.annotate`.** Die Kommentierung der Instruktionen (pc und Wort) kommt aus dem Schlüssel statt aus einer Umgebungsvariablen.
6. **`ShaderKey.no_rscale`.** Mit diesem Schalter liest der Übersetzer die Auflösungsskalierungs-Tabelle (Puffer 18) nicht: Fensterkoordinaten, Texel-Abrufe (TLD/TLDS) und Größenabfragen (TXQ) bleiben unskaliert. Das Werkzeug `maxwell2msl` setzt ihn standardmäßig; `--rscale` stellt das Original-Verhalten wieder her.

### `shader.h`

`Survey`/`SurveyItem` und `maxwell_translate_ex()` ergänzt; `ShaderKey.no_rscale`, `ShaderKey.annotate` ergänzt; `uses_tint`, die `maxwell_dbg_*`-Deklarationen und der Tint-Eintrag im Schnittstellenkommentar entfernt; Herkunftskommentar ergänzt.

### Bewusst (noch) unverändert

Globale Variablen `maxwell_gmem_base/size`, `flip_x`, der GLSL-Zweig, statische Puffer in `RSC2` (nicht threadsicher; die Übersetzung läuft in einem Thread), `sprintf` ohne Längenprüfung. Siehe `docs/shader-translator.md`, Aufgabenliste für Teil 2.

## Eigener Code in diesem Verzeichnis (kein Fremdcode)

`main.c` (Werkzeug `maxwell2msl`), `container.c`/`container.h` (Leser für Unity-Shaderprogramme), `Makefile`, `survey_report.py`, `tests/`.
