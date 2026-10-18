# Bundle-Katalog (`Dpr.bin`)

Stand: 2026-10-18. Dieses Dokument beschreibt `AssetAssistant/Dpr.bin` und die darauf
aufbauende Boot-Schicht (`unity/Assets/Scripts/Boot`, Assembly `Xnu.Boot`). Es enthält nur
Formate, Namen und Zahlen – keine Spielinhalte.

## Kurzergebnis

- `Dpr.bin` ist der **Bundle-Katalog** des Spiels: eine mit dem .NET-`BinaryFormatter`
  serialisierte Instanz der Klasse `SmartPoint.AssetAssistant.AssetBundleDownloadManifest`
  (Il2Cpp-Dump: TypeDefIndex 3006, Konstante `currentVersion = 6`). Sie ist **weder
  verschlüsselt noch komprimiert**.
- Pro Bundle steht dort: Projekt, Bundle-Name, 128-Bit-Hash, Änderungszeit, Szenen-Flag,
  Liste aller (transitiven) Abhängigkeiten, Liste der enthaltenen Asset-Pfade und Dateigröße.
- Damit ist die Zuordnung *logischer Asset-Name → Bundle* und *Bundle → Abhängigkeiten*
  vollständig aus `Dpr.bin` lesbar. Ein Verzeichnis-Scan reicht nur für Bundle-Namen und
  Größen, nicht für Abhängigkeiten und Asset-Namen.
- Die Dateien liegen unter `AssetAssistant/<Projekt>/<Bundle-Name>`; der Bundle-Name darf
  selbst `/` enthalten (Unterordner).

## Container: .NET-BinaryFormatter (MS-NRBF)

Die Datei ist ein Strom aus „Records“ (Spezifikation MS-NRBF). Ganzzahlen sind
little-endian, Strings sind UTF-8 mit 7-Bit-Längenpräfix. Reihenfolge in `Dpr.bin`:

| Offset | Inhalt |
|---|---|
| 0x00 | Record 0 `SerializedStreamHeader`: Root-ID = 1, Header-ID = -1, Major 1, Minor 0 |
| 0x11 | Record 12 `BinaryLibrary`, ID 2, Name `AssetAssistant, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null` |
| danach | Record 5 `ClassWithMembersAndTypes` (ID 1) für `AssetBundleDownloadManifest` |
| danach | Record 7 `BinaryArray` (ID 4, Einzel-Array, Länge N, Elementtyp Klasse) mit N × Record 9 `MemberReference` auf die Einträge |
| danach | Record 17 `ArraySingleString` (ID 5) = Variantenliste |
| danach | N Eintragsobjekte: erster als Record 5 (Klassenbeschreibung), die übrigen als Record 1 `ClassWithId` |
| Ende | Record 11 `MessageEnd` |

Die Dateigröße (5.278.300 Byte) wird vom Strom exakt verbraucht; kein Rest.

### Klassen und Felder

`AssetBundleDownloadManifest` (4 Mitglieder, Typ in Klammern = BinaryType/Primitiv):

| Feld | Typ | Bedeutung |
|---|---|---|
| `_version` | Int32 | 6 |
| `_projectName` | String | `Dpr` |
| `_records` | Klassen-Array | N Einträge (Wert in diesem Dump: 13.660) |
| `_assetBundleNamesWithVariant` | String-Array | Bundle-Namen mit Sprachvariante (99 Stück) |

Hinweis: Die Typinformation von `_records` lautet formal `AssetBundleRecord[]` als Klasse
(Mono-Eigenheit), das Objekt dahinter ist ein normales `BinaryArray`.

`AssetBundleRecord` (8 serialisierte Mitglieder; `latest`, `isBeginInstalled`,
`isSimulation` sind Laufzeitfelder und nicht enthalten):

| Feld | Typ | Bedeutung |
|---|---|---|
| `projectName` | String | Projektordner (18 verschiedene, s. u.) |
| `assetBundleName` | String | Name relativ zum Projektordner, kleingeschrieben, ggf. mit `/` |
| `hash` | `RecordedHash` (Wertklasse, inline) | 4 × UInt32 `u0..u3`; nur für Projekt `Dpr` gesetzt (146 Einträge), sonst 0 |
| `lastWriteTime` | DateTime (Primitiv 13) | roher 64-Bit-Wert: Bits 0–61 Ticks, Bits 62–63 Kind (hier immer 1 = UTC); Spanne 2021-08-01 bis 2022-03-01 |
| `isStreamingSceneAssetBundle` | Boolean | Szenen-Bundle (16 Stück) |
| `allDependencies` | String-Array oder Null | alle transitiven Abhängigkeiten als Bundle-Namen |
| `assetPaths` | String-Array oder Null | Asset-Pfade im Bundle (kleingeschrieben, `assets/…`) |
| `size` | Int64 | Dateigröße in Byte |

Kodierungsdetails, die ein Leser beherrschen muss:

- Strings, die mehrfach vorkommen (z. B. Abhängigkeitsnamen), stehen nur einmal; weitere
  Vorkommen sind `MemberReference` (Record 9) auf die Objekt-ID. Referenzen zeigen auch
  vorwärts (das Eintrags-Array steht vor den Eintragsobjekten).
- Objekt-IDs können negativ sein (die Klasse `RecordedHash` hat ID −13767).
- Leere Arrays/Strings können als `ObjectNull` (Record 10) und Folgen davon als
  `ObjectNullMultiple(256)` (Record 13/14) kodiert sein.
- Ab dem zweiten Eintrag nutzen Klassenobjekte `ClassWithId` (Record 1) und verweisen auf die
  zuerst beschriebene Klasse; das gilt auch für den inline eingebetteten `RecordedHash`.

### Hash-Darstellung

`u0..u3` sind die vier Little-Endian-Wörter eines Unity-`Hash128`. Die Textform (32 Hex-Zeichen)
entsteht, indem jedes Wort byte-vertauscht als 8 Hex-Ziffern ausgegeben wird (entspricht
`Hash128.ToString()`). Geprüft: Für alle 146 Einträge mit Hash stimmt der Wert mit
`AssetBundleManifest.GetAssetBundleHash` aus dem Bundle `Dpr/Dpr` überein (146/146).

## Zuordnung zu Dateien auf der Platte

- Pfad = `AssetAssistant/<projectName>/<assetBundleName>`. Auf der Platte stimmen Groß-/
  Kleinschreibung der Projektordner mit dem Katalog überein (`Pokemon Database`, `UIs`, …).
- Bundle-Namen sind **global eindeutig** (13.660 verschiedene Namen); Abhängigkeiten
  referenzieren daher nur den Namen ohne Projekt. Alle Abhängigkeiten sind im Katalog auflösbar
  (0 fehlende). Maximal 23 Abhängigkeiten pro Bundle, 6.721 Bundles haben keine.
- 13.651 von 13.660 Katalogdateien existieren mit **exakt** der im Katalog genannten Größe.
  Die 9 fehlenden sind Debug-/Viewer-Szenenbundles (z. B. `Dpr/debug/…`, `Dpr/assetviewer/viewer`,
  `Dpr/scenes/messageviewer`, `Battle/debug/…`, `GMS/debug/…`); sie werden vom Spiel nicht benötigt.
- Auf der Platte liegen 14.052 UnityFS-Dateien, davon 401 **nicht** im Katalog:
  18 Manifest-Bundles je Projekt (`<Projekt>/<Projekt>`, Unity-`AssetBundleManifest`),
  296 Pokémon-Animationsbundles (`Pokemon Database/pokemons/battle/animations/pm…`),
  81 Sprach-Textur-Bundles (`GMS/textures/graphictext/*`) und 6 einzelne weitere
  (`Dpr/tmpshader`, `Effects/bg/arenas/sky/s037`, vier unter `GMS/`). Der Loader kann sie über
  den Verzeichnis-Scan finden; ein Katalogeintrag fehlt dafür.
- Verteilung der Einträge je Projekt: Pokemon Database 5451, Effects 2985, UIs 1994,
  Battle 1411, Environments 643, Contest 578, Characters 413, Dpr 146, FureaiHiroba 13,
  Message 11, UnderGround 3, Union 3, DigFossil 2, GMS 2, StatuePlacementEdit 2, Pml 1,
  UgFather 1, LightStone 1. Summe der Größen: 4.101.784.513 Byte.
- Sprachvarianten (`…lang.en`, `.fr`, `.ge`, `.it`, `.jp`, `.ko`, `.si`, `.sp`, `.tr`) sind
  ganz normale Katalogeinträge mit vollem Namen inkl. Endung; `_assetBundleNamesWithVariant`
  listet sie nur zusätzlich (99 Namen, alle im Katalog).

## Asset-Schlüssel

Insgesamt enthält der Katalog 44.431 Asset-Pfade, alle eindeutig und kleingeschrieben, alle mit
Präfix `assets/`. Der logische Schlüssel entsteht durch Entfernen von `assets/` und der Endung,
z. B. `assets/scriptableobjects/gamesettings.asset` → `scriptableobjects/gamesettings`
→ Bundle `Dpr/scriptableobjects/gamesettings`. Es gibt 44.393 verschiedene logische Schlüssel;
bei 38 gehören mehrere Assets mit unterschiedlicher Endung zum selben Namen (z. B. `.asset`
neben `.xlsx`, `.shader` neben `.cginc`). Diese Namen löst der Loader nicht auf; man fragt mit
Endung an (`TryResolveAsset("md/a/foo.xlsx")`). Die `.xlsx`-/`.cginc`-Einträge sind
Editor-Quelldateien, die im Bundle selbst nicht als Asset vorhanden sind (Beispiel
`Dpr/masterdatas`: Katalog 1119 Pfade, im Bundle 1118 Assets).

## Implementierung (`Xnu.Boot`)

| Klasse | Aufgabe |
|---|---|
| `NrbfReader` | allgemeiner Leser für den benötigten NRBF-Ausschnitt (Klassen mit Typinfo, Strings, Arrays, Referenzen, Null-Läufe), mit Grenzprüfungen; Fehler → `FormatException` |
| `BundleCatalog` | `FromFile`/`FromBytes` (Dpr.bin, nur Version 6), `FromDirectory` (Ersatz-Scan: UnityFS-Magic, Projekt = erstes Pfadsegment), Bundle-Suche (`Projekt/Name` oder nur Name, case-insensitiv), `GetDependencyClosure`, `TryResolveAsset` |
| `AssetKey` | Normalisierung (Kleinschreibung, `/`, ohne `assets/` und Endung) |
| `BundleProvider` | `Acquire`/`Release` mit Referenzzähler, Abhängigkeiten werden mitgezählt, Rollback bei Ladefehlern, `LoadAsset<T>(Schlüssel)`, `UnloadAll` |
| `IBundleSource`/`UnityBundleSource` | `AssetBundle.LoadFromFile`; in Tests durch Attrappe ersetzbar |
| `BootSequence`/`BootLoader` | Pfade prüfen, Katalog lesen (Rückfall auf Scan mit Warnung), Konsistenz prüfen, Provider anlegen; `BootLoader` ist ein MonoBehaviour, das beim Start die Schritte nur ins Log schreibt (keine UI, nichts wird abgespielt/gerendert) |

Pfade kommen aus `Xnu.Core.GameDataPaths` (Umgebungsvariable `XNU_GAMEDATA`, Root enthält
`romfs/Data/StreamingAssets`); der Katalog liegt unter `AssetAssistant/Dpr.bin`.
`Acquire` erhöht den Zähler des Bundles und aller transitiven Abhängigkeiten; `Release` senkt
sie symmetrisch, bei 0 wird mit `Unload(true)` entladen. Ein Bundle darf in Unity nicht zweimal
per Datei geladen werden – der Zähler verhindert das.

## Tests und Messwerte

EditMode-Tests (`Assets/Tests/EditMode/BootTests.cs`, Schreiber für synthetische Kataloge in
`BootTestCatalogWriter.cs`, gleiches NRBF-Layout wie `Dpr.bin`, aber erfundene Namen): 16 neue
Tests (Katalogparser inkl. Null-/Referenz-Kodierung, Fehlerfälle, Name-/Asset-Auflösung,
Mehrdeutigkeit, Provider-Zähler/Rollback/Dispose, Verzeichnis-Scan, Boot-Ablauf). Lauf
`Xnu.Tests.EditMode`: 46/46 grün.

Integrationscheck gegen die echten Daten (`unity-eval`, `XNU_GAMEDATA=<Repo>/work`,
Editor 6000.3.26f1, M1 Pro):

| Messung | Wert |
|---|---|
| Boot (Pfade + Katalog + Konsistenz) | 307 ms; Katalog lesen 189 ms |
| Katalog | 13.660 Bundles, 44.431 Assets, 99 Varianten, Version 6 |
| Konsistenz | 9 Bundle-Dateien fehlen, 0 fehlende Abhängigkeiten, 38 mehrdeutige Namen |
| Verzeichnis-Scan | 14.052 UnityFS-Dateien in 954 ms |
| `Dpr/masterdatas` | per Namen aufgelöst, geladen, 1118 Assets (Katalog 1119), 0 Abhängigkeiten |
| `Pml/personal_masterdatas` | geladen, 16 Assets (Katalog 16) |
| `scriptableobjects/gamesettings` | per Name → `Dpr/scriptableobjects/gamesettings`, 1 Asset (Katalog 1) |
| Refcount/Unload | nach 3 Acquire 3 geladen, nach Release 0, `UnloadAll` 0 |
| Hash-Vergleich Katalog ↔ `Dpr/Dpr`-Manifest | 146/146 gleich; Abhängigkeiten stimmen (Stichprobe) |

Es wurde nur geladen und aufgelistet; keine Materialien/Shader gerendert, kein Audio.

## Offene Punkte

- Asynchrones Laden (`LoadFromFileAsync`) und Szenen-Bundles sind noch nicht im Provider.
- Die 401 Dateien ohne Katalogeintrag (v. a. Pokémon-Animationen) braucht der Loader über den
  Verzeichnis-Scan; wie das Spiel sie adressiert (Bundle-Namen aus `Pml`/Masterdaten?), ist
  noch zu klären.
- `docs/daten-inventar.md` nennt `Dpr.bin` noch als offen; dieses Dokument löst die Frage.
