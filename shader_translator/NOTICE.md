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

Teil 2 (2026-10-18):

7. **TEX.B (bindlose Textur).** Das Original brach bei diesem Befehl mit „bindless tex“ ab. Jetzt verfolgt `prov_track()` für jedes Register, ob sein Wert aus Konstantenpuffer-Wörtern aufgebaut wurde (MOV c[][], LOP.OR mit c[][], LDC, MOV Rb; jeder andere Schreibzugriff setzt zurück, erkannt am erzeugten Text). `emit_tex()` liest damit das Handle-Register von TEX.B; die Textur ist durch das Wortpaar (Samplerwort | Texturwort) bestimmt und bekommt einen Slot (`bindless_slot()`, Reihenfolge der ersten Benutzung). Die Register hinter dem Handle liefern LOD, Offset und Tiefenvergleich. Fehlt die Herkunft, bleibt der Befehl ein Fehler („bindless handle not from cbuf words“). `ShaderTexture` bekam `bindless_has_sampler` und `bindless_sampler_offset`.
8. **HSETP2 mit Konstantenpuffer- und Immediate-Operand** (0x7e80/0x7f80 und 0x7e00/0x7f00). Die Registerform war im Original vorhanden und wurde verallgemeinert: Vergleichsfeld Bit 49..52 statt 35..38, HAND Bit 53 statt 49, Operand B als ein f32 (cbuf) bzw. zwei Halbwerte (imm).
9. **Daten für die Ressourcenkarte:** statisch adressierter Bereich je Konstantenpuffer (`cbuf_min_off`/`cbuf_end_off`, gesetzt in `cbuf_ref()`), Komponentenmasken der Ein- und Ausgaben (`in_comp`/`out_comp`), `flat_mask`/`noperspective_mask`, Beginn der Compiler-Konstanten im Blob (`cbuf1_blob_offset`: auf 0x100 aufgerundetes Codeende).
10. **Exakte Arithmetik.** Die MSL beginnt jetzt mit `#pragma METAL fp math_mode(safe)` und `#pragma METAL fp contract(off)` (Schlüssel `fast_math` schaltet das ab). Das Original ließ Fast-Math und die FMA-Verschmelzung von Metal an.
11. **`ShaderKey.half_compat`** (nur als Testorakel): hält zu Registern, die Halb-Befehle schreiben, einen ungerundeten `float2`-Schatten, wie Ryujinx es durch das Entfernen von Pack/Unpack-Paaren tut. Standard ist die Rundung auf fp16 wie auf der Hardware.

### `shader.h`

`Survey`/`SurveyItem` und `maxwell_translate_ex()` ergänzt; `ShaderKey.no_rscale`, `ShaderKey.annotate` ergänzt; `uses_tint`, die `maxwell_dbg_*`-Deklarationen und der Tint-Eintrag im Schnittstellenkommentar entfernt; Herkunftskommentar ergänzt. Teil 2: `ShaderKey.fast_math`, `ShaderKey.half_compat`; `ShaderTexture.bindless_has_sampler`/`bindless_sampler_offset`; `ShaderInfo.cbuf_min_off`, `cbuf_end_off`, `cbuf1_blob_offset`, `in_comp`, `out_comp`, `flat_mask`, `noperspective_mask`.

Teil 3 (2026-10-19): `ShaderKey.hlsl` und der Schnittstellenkommentar „HLSL contract“ (Strukturen, Namen der Konstantenpuffer/Texturen, Grenzen).

### `translate.c`, Teil 3: HLSL-Ausgabe für Unity (`ShaderKey.hlsl`, Werkzeug: `--lang hlsl`)

Alle Stellen sind mit `XNU:` oder im Kopfkommentar der Datei markiert. Die MSL- und GLSL-Ausgabe bleibt byteidentisch (an 500 zufälligen Blobs mit je drei Optionssätzen gegen die Vorversion geprüft).

12. **Neuer Zweig `hlsl_rewrite()` / `hlsl_prelude` / `hlsl_finish()`** nach dem Muster des GLSL-Zweigs: Der Befehlsrumpf entsteht weiter in der MSL-Schreibweise und wird tokenweise umgeschrieben (`as_type<float/uint/int>` → `asfloat/asuint/asint`, `fmin/fmax` → `min/max`, `rint` → `round`, `fma` → `mx_fma` (= `mad`), `isnan` → `mx_isnan` (Bittest, weil FXC `isnan` wegfaltet), `popcount` → `countbits`, `char()/short()` → `sx8/sx16`, `in`/`out` → `i_`/`o_`, `cb<k>` → `mx_cb<k>`; nicht abbildbare Bezeichner wie `ulong`, `half`, `gmem`, `simd_shuffle*` brechen mit einer „hlsl:“-Meldung ab). Die Hilfsfunktionen (Bitfelder, `mulhi`, `clz`, `prmt`, `hx`/`hpack` über `f16tof32`/`f32tof16`, 32-Bit-Übertrag `mx_adc3`, Trichterverschiebung `mx_shf_*`, `fswzadd` mit Lane aus der Pixelposition) liegen im Prelude, das eine Include-Wache trägt (Vertex und Fragment teilen ein Programm).
13. **Pro Dialekt neu erzeugt:** Texturabrufe (`hlsl_sample()`: `Sample/SampleLevel/SampleBias/SampleCmp(LevelZero)`, Register-Offsets über Koordinatenverschiebung, weil HLSL nur Literal-Offsets kennt), `TLDS` als `Load`, `TXQ` über `tsize<i>()`/`tlevels<i>()` (GetDimensions), 16-Bit-Packen in `TEXS.F16`/`F2F`/`F2I`/`I2F`, `IADD32I`/`IADD3` mit Übertrag und `SHF` ohne 64-Bit-Ganzzahlen, `KIL` → `discard`, Deklarationen und Einstiegspunkte (`mx_vs`, `mx_fs`, Strukturen ohne Semantik; die Semantik setzt der Wrapper).
14. **Zustandsautomat für Sprünge:** HLSL (FXC) verträgt weder `continue` im `switch` noch Zuweisungen an die `switch`-Variable in einer Schleife („l-value expected“). Der `switch (pc)` wird daher als Kette `if (pc == N) { … pc = nächste; }` erzeugt (Durchfall = Setzen von `pc`, Sprung = `pc = X; continue;`).
15. **`ShaderKey.hlsl`** schließt sich mit `glsl` aus; Compute, `half_compat`, globaler Speicher, Auflösungsskalierung, Punktkoordinate und Subgroup-Befehle werden mit einer Meldung abgelehnt.
16. **`main.c`** (eigener Code): `--lang msl|glsl|hlsl`, `--hlsl`, Schlüssel `language` in der Ressourcenkarte. Tests: 16 neue C-Prüfungen (`test_hlsl_backend`) und ein CLI-Test.

### Bewusst (noch) unverändert

Globale Variablen `maxwell_gmem_base/size`, `flip_x`, der GLSL-Zweig (TEX.B und `half_compat` gelten nur für MSL; der GLSL-Zweig wurde nicht getestet), statische Puffer in `RSC2` (nicht threadsicher; die Übersetzung läuft in einem Thread), `sprintf` ohne Längenprüfung. Siehe `docs/shader-translator.md`, Aufgabenliste für Teil 3.

## Eigener Code in diesem Verzeichnis (kein Fremdcode)

`main.c` (Werkzeug `maxwell2msl`; Teil 2: Ressourcenkarte in `--info`, `--cbuf1`, `--fast-math`, `--half-compat`; Teil 3: `--lang`), `container.c`/`container.h` (Leser für Unity-Shaderprogramme), `Makefile`, `survey_report.py`, `tests/`. Außerhalb des Verzeichnisses: `scripts/shader_fidelity.py` (Treue-Test), `scripts/tests/test_shader_fidelity.py`; Teil 3: `scripts/shader_wrap.py` (ShaderLab-Wrapper-Generator), `scripts/tests/test_shader_wrap.py`, `docs/shader-unity-integration.md`.
