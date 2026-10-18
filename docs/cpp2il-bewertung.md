# Cpp2IL-Bewertung (BDSP-Dump, ARM64-NSO)

Stand: 2026-10-18. Frage: Kann Cpp2IL aus `work/exefs/main` + `global-metadata.dat`
lesbare C#-Rümpfe rekonstruieren, die unseren Ghidra-Pseudocode ersetzen oder ergänzen?

**Kurzfazit:** Nein, nicht als Ersatz. Cpp2IL liefert für alle Methoden *formal* einen Rumpf,
aber die Rümpfe sind für die Save-Logik größtenteils unbrauchbar (statische Felder, Feldzugriffe
und viele Aufrufe fehlen). Als **Ergänzung** ist der ISIL-Dump nützlich (aufgelöste
Methodennamen, Parameter, Feldnamen).

## Eingaben und Aufbau

| Punkt | Wert |
|---|---|
| Binary | `work/exefs/main` (NSO, unverändert) |
| Metadata | `work/romfs/Data/Managed/Metadata/global-metadata.dat`, von Cpp2IL als v24.5 erkannt |
| Unity | 2019.4.27 (`--force-unity-version 2019.4.27`) |
| Aufruf | `--force-binary-path`, `--force-metadata-path`, `--force-unity-version`, `--output-as <Format>` |
| Ausgabe | `work/cpp2il/{il_recovery,diffable-cs,isil}`, Logs `work/cpp2il/run-*.log` |

## Installation: Stolpersteine

1. Der Pre-Release-Asset `Cpp2IL-2022.1.0-pre-release.21-OSX-ARM64` (nach `tools/Cpp2IL/`) wird von macOS
   mit `Killed: 9` beendet, weil das Binary nicht signiert ist (Quarantäne-Attribut war nicht
   gesetzt, nur `com.apple.provenance`). `codesign --force --sign -` auf genau dieser Datei
   behebt das; `--help` läuft danach.
2. **Der Lauf auf unserem NSO scheitert mit diesem Release.** Ausnahme
   `NSO: Address 0x2CF6A30 is not present in any of the segments`: Die letzte Methode am Ende
   von `.text` (0x2CF6A00) wird bis zur Segmentgrenze und darüber hinaus disassembliert. Der
   Fehler liegt in Cpp2IL, nicht in unseren Daten (Pre-Release 21 ist der neueste Release;
   der Fix für die Grenzbehandlung steht nur auf `master`).
3. Abhilfe: `master` (b5ad444) geklont und mit `dotnet build -c Release -f net10.0` nach
   `tools/Cpp2IL/build/` gebaut (.NET 10 SDK ist vorhanden). Danach scheiterte derselbe Fall noch
   einmal im Pfad „unmanaged Funktion“ (liest ohne Segmentprüfung weiter bis zum ersten `B`).
   **Lokaler Ein-Zeilen-Patch** in `NewArm64Utils.cs` (Abbruch an der Segmentgrenze), liegt
   nur unter `tools/Cpp2IL/src`. Der 2022.0.7-Stable wurde nicht probiert, da älter.
   Das ist ein wichtiger Punkt für jeden Folgeeinsatz: ohne eigenen Build läuft es nicht.
4. Für die Ansicht der `dll_il_recovery`-DLLs wurde `ilspycmd` 11.1 lokal nach `tools/ilspy/`
   installiert (`dotnet tool install --tool-path`).

## Messwerte

| Format | Laufzeit | Peak-RSS | Ausgabegröße |
|---|---|---|---|
| `dll_il_recovery` | 24 s | 2,4 GB | 38 MB (DLLs) |
| `diffable-cs` | 11 s | 2,3 GB | 32 MB |
| `isil` | 36 s | 2,4 GB | 334 MB |
| ILSpy-Dekompilat von Assembly-CSharp.dll (Hilfsschritt) | 31 s | 2,4 GB | 106 MB, 3764 `.cs`-Dateien |

Das 6-GB-Limit wurde nie erreicht; Platz auf dem Datenvolume nach den Läufen: 76 GB frei.

Methodenzahlen:

- Metadata: 11 812 Typen; Cpp2IL ordnete 71 155 Code-Zeiger Methodendefinitionen zu
  (Assembly-CSharp: 48 084 Zeiger).
- `dll_il_recovery` meldet „100 % decompiled (48 645 / 48 645)“. Diese 100 % bedeuten nur „es wurde
  ein Rumpf erzeugt“, nicht Korrektheit. 6 Methoden wurden als zu groß übersprungen
  (statische Konstruktoren der Textlisten/Tabellen, z. B. `Pml.DebugViewTable::.cctor`, 540 KB).
- `diffable-cs`: enthält **keine** Rümpfe, nur Signaturen mit `{ }` und Längenkommentar
  (`PlayerWork.cs`: 1818 Zeilen, alle Methoden leer). Als Ersatz für Ghidra ungeeignet,
  nur als Typ-/Feldübersicht mit Offsets brauchbar.
- Auswertung des ILSpy-Dekompilats von Assembly-CSharp (Heuristik per Skript
  `work/cpp2il/stats.py`, erfasst 35 888 reguläre Methoden; Property-Accessoren und einzelne
  Sonderformen fallen heraus):

| Kategorie | Anzahl | Anteil |
|---|---|---|
| Methoden erfasst | 35 888 | 100 % |
| Rumpf leer | 1 563 | 4,4 % |
| Rumpf ohne Platzhalter („sauber“) | 9 998 | 27,9 % |
| Rumpf mit Platzhaltern + echtem Code | 23 519 | 65,5 % |
| Rumpf nur aus Platzhaltern | 808 | 2,3 % |

  Insgesamt 330 241 `NoteDecompilerIssue`-Zeilen auf 1,86 Mio. Codezeilen (ca. 18 %).
  ILSpy scheiterte zusätzlich an 2 Konstruktoren (`INL1.PacketWriter/Reader`).
  „Sauber“ sind überwiegend kleine Getter/Setter und Delegat-Stubs.

## Qualität bei den Save-Methoden (PlayerWork)

Nicht-leere Rümpfe: alle vier. Gezählt sind Codezeilen ohne Kommentare.

| Methode | Cpp2IL (il_recovery) | davon Platzhalter | echte Aufrufe | Ghidra (`PlayerWork.c`) |
|---|---|---|---|---|
| `SaveAsync` | 16 | 4 | 0 (nur `DataSave`) | 18 Zeilen, vollständig lesbar |
| `LoadAsync` | 39 | 10 | 0 | 27 Zeilen |
| `DataSave` | 244 | 60 | 3 | 144 Zeilen |
| `VerifySaveData` | 927 | 115 | 4 | 167 Zeilen |

Bewertung in eigenen Worten:

- **`SaveAsync`:** Cpp2IL erkennt den Aufruf `DataSave(isAsync: true, writeMain, writeBackup)` korrekt
  samt Parameternamen aus den Metadaten. Der Rest ist die IL2CPP-Klasseninitialisierung und der
  Static-Check (Flag-Bit 1 und Feld bei +0xE0), der als Folge von „Unmanaged memory load“ mit
  Konstante 0 erscheint. Ghidra zeigt dieselbe Struktur kompakter, inklusive
  tatsächlicher Offsets und der Verknüpfung der Parameter (`& 1`).
- **`LoadAsync`:** Der Rumpf besteht aus der Initialisierungsprüfung, einem Gewirr von `goto`-Sprungmarken
  und zwei „Method not found“-Aufrufen (Adressen 0x2324910 / 0x2324AE0). Die
  Hauptsache (Lesen der Save-Daten über `PlayerPrefsProvider<PlayerWork>`, Flag
  `fromBackup`) fehlt vollständig. Ghidra zeigt den Aufruf `…PlayerWork___Load` und
  das Setzen des Backup-Flags an Feldoffset 0x829. Hier ist Ghidra klar besser.
- **`DataSave`:** Gefunden werden die benannten Aufrufe `FieldWalkingManager.UpdatePartnerPokeIndex`,
  `PlayReportManager.SaveRecordDataEvent`, `SystemTimeWork.GetSaveTime`. Statische Felder
  (`PlayerWork`-Singleton, Instanzfelder) und Feldzuweisungen (z. B. die Flags `writeMain`/`writeBackup`
  an 0x828/0x829 des `PlayerPrefsProvider`-Singletons) werden **nicht** rekonstruiert; die Methode liest sich wie eine Folge
  von Konstanten 0. Ghidra liefert hier die brauchbarere Gliederung.
- **`VerifySaveData`:** 927 Zeilen mit 100 „Unmanaged memory load“ und nur 4 benannten
  Aufrufen; die Prüfsummen-/Längenlogik ist nicht nachvollziehbar. Zusätzlich
  die IL-Kommentare „Expected Obj, but got I4“: Typkonflikte im erzeugten IL.
- Positiv: `CustomSaveAsyncOperation` wird im ISIL-Dump als
  `SaveSystem.SaveAsync(this._writeSrcBuffer, …Flags)` mit Feldnamen wiedergegeben, im
  IL-Recovery-Pfad dagegen nur teilweise (`makeSaveDataHash(ref buf)` wird erkannt, die
  Aufrufe an die Spezialadressen nicht).

## Typische Fehlerbilder

1. `Unmanaged memory load: [Adresse]` ersetzt jede Lesung eines Singletons oder statischen Felds; der
   Wert wird als 0 behandelt, die Folgezugriffe (`->0x12F`, `->0xE0`) sehen wie Konstanten aus.
2. `Method not found @Adresse`: Aufrufe an Hilfsfunktionen, die keiner Metadaten-Methode zugeordnet
   sind (z. B. IL2CPP-Runtime-Funktionen wie `il2cpp_codegen_initialize_method`, interne Helfer,
   Typinitialisierung, Marshalling).
3. `Indirect call` (Virtual/Interface-Dispatch über Klassen-Vtable) wird nicht aufgelöst.
4. `goto`-lastige Schleifen und `object`-getypte Hilfsvariablen statt echter Typen.
5. Generische Instanziierungen werden nur grob aufgelöst; `PlayerPrefsProvider<PlayerWork>` taucht nicht
   mit Typargumenten auf.

## Einschränkungen dieser Bewertung

- Die Statistik ist eine Textheuristik auf ILSpy-Ausgabe, keine exakte Metadaten-Zählung; sie erfasst
  ca. 74 % der 48 645 Methoden (der Rest sind u. a. Property-Accessoren, Operatoren und
  Sonderformen).
- Gebaut wurde `master` (b5ad444) mit lokalem Patch, nicht der Release; das Verhalten kann sich von
  `2022.1.0-pre-release.21` unterscheiden.
- Das ISIL-Format wurde nur stichprobenhaft (`PlayerWork`) angesehen.
- Spielcode-Ausgaben liegen nur unter `work/cpp2il/` (gitignored) und sind nicht in dieses
  Dokument kopiert.

## Empfehlung

- **Für die Rekonstruktion der C#-Logik: Ghidra-Pseudocode bleibt die Hauptquelle.** Cpp2IL-`dll_il_recovery`
  ist (Stand dieser Messung) kein Ersatz; es ist stark zerlückt, v. a. dort, wo die Logik über
  statische Felder/Singletons und Feldzugriffe läuft, also bei der gesamten Save-Kette.
- **Nützlich als Zusatz:**
  - `diffable-cs` für Typen, Feldoffsets und Methodensignaturen samt Parameternamen
    (ergänzt `dump.cs` von Il2CppDumper, das wir bereits haben).
  - `isil` zum Querlesen: es löst direkte Aufrufe und Instanzfelder (`this._isMainSave`)
    mit Namen auf, die in Ghidra als `param_1 + 0x…` erscheinen.
- **Ablauf, falls wir es einsetzen:**
  1. `tools/Cpp2IL/build/Cpp2IL` (selbstgebaut, mit Patch) mit `--output-as isil` und
     `diffable-cs` laufen lassen (≈ 50 s, ≈ 2,4 GB).
  2. Pro Zielmethode ISIL-Block und Ghidra-Funktion nebeneinander lesen; Offsets aus Ghidra,
     Namen aus ISIL übernehmen.
  3. Ergebnis in unsere Spec (`docs/save-spec-entwurf.md`) und Testvektoren überführen und mit
     dem Save-Validator gegen echte Saves prüfen.
  4. Bei Bedarf Cpp2IL-Version/Patch erneuern, sobald ein Release erscheint, der die
     NSO-Segmentgrenze beherrscht.
