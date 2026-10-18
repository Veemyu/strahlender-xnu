# Daten-Inventar (RomFS-Dump)

Grundlage: lokaler, nur gelesener Dump `work/romfs/Data/StreamingAssets`. Alle Zahlen stammen aus
`scripts/data_inventory.py` (nur Header werden gelesen, nichts wird entpackt oder verändert).
Dieses Dokument enthält bewusst nur Namen, Zahlen und Header-Versionen, keine Spieldaten.

Hinweis: `docs/spielcode-inventar.md` existiert noch nicht. Die Lade-Hinweise unten stammen aus
`work/il2cpp/dump.cs` und `stringliteral.json`. In `work/decomp/*.c` liegen bisher nur Save-Funktionen,
daher gibt es von dort keine Hinweise zum Asset-Laden.

## 1. Verzeichnisstruktur

| Ordner | Dateien | Größe | Dateitypen |
|---|---:|---:|---|
| `AssetAssistant` | 14 053 | 3930 MiB | 14 052 Unity-Bundles (ohne Endung, bei Bundles für UIs/GMS/Contest mit Sprachendung), 1× `.bin` |
| `Audio/GeneratedSoundBanks/Switch` | 3 939 | 420 MiB | 3 241 `.wem`, 696 `.bnk`, `PluginInfo.xml`, `Wwise_IDs.h` |
| `Movie/dia` | 18 | 456 MiB | 18 `.webm` |

Im `AssetAssistant`-Ordner steht außerdem `Dpr.bin` (5,3 MB, kein UnityFS; Anfangsbytes sehen nach .NET-BinaryFormatter
aus, vermutlich die Bundle-Manifest-Datei, siehe offene Fragen). Auf Stammebene liegen nur die Unterordner.

Unterordner von `AssetAssistant` (Bundles, jede Datei ist ein Bundle):

| Unterordner | Bundles | Größe | Vermuteter Inhalt (nach Name) |
|---|---:|---:|---|
| Environments | 644 | 2239,5 MiB | Karten, Hintergründe, Untergrund |
| Characters | 414 | 642,8 MiB | Charaktermodelle |
| Pokemon Database | 5 748 | 596,2 MiB | Pokémon-Modelle (`pokemons/...`) |
| Effects | 2 987 | 252,4 MiB | Effekte, Seal-Daten |
| UIs | 1 995 | 80,9 MiB | UI-Texturen, Sprach-Varianten |
| Dpr | 141 | 66,6 MiB | Kernspiel: Szenen, Skripte, Shader, Einstellungen |
| Message | 12 | 14,5 MiB | Texte je Sprache |
| Battle | 1 411 | 6,8 MiB | Kampf-Kamera/Sequenzen, Kampf-Stammdaten |
| Contest | 579 | 6,3 MiB | Wettbewerbe |
| FureaiHiroba | 14 | 5,4 MiB | Freizeitbereich (Fureai-Plaza, Poffin) |
| StatuePlacementEdit | 3 | 4,4 MiB | Statuen |
| GMS | 87 | 3,1 MiB | Globale Tauschstation (GTS) |
| Union | 4 | 2,9 MiB | Union-Raum |
| DigFossil | 3 | 2,8 MiB | Fossilien-Minispiel |
| UnderGround | 4 | 0,5 MiB | Untergrund |
| Pml | 2 | 0,1 MiB | Pokémon-Bibliothek (Personal-Daten) |
| LightStone, UgFather | je 2 | < 0,1 MiB | klein |

## 2. Unity-Bundles (Header)

| Merkmal | Wert |
|---|---|
| Anzahl | 14 052 (alle `UnityFS`), 3925 MiB |
| Format-Version | 7 (alle) |
| Unity-Version / Revision | Plugin `5.x.x`, Revision `2019.4.27f1` (alle) |
| Header-Flags | `0x43` (alle): Kompression der Blockinfo = LZ4HC, Blockinfo direkt hinter dem Header |
| Größenangabe im Header | stimmt bei allen mit der Dateigröße überein |
| Datenblock-Kompression | 87 104 Blöcke LZ4HC, 86 Blöcke unkomprimiert |
| Knoten (innere Dateien) | 1 → 6 331 Bundles, 2 → 7 720, 4 → 1 |
| Blockinfo nicht lesbar | 0 |

Größenverteilung (Dateigröße):

| Klasse | Bundles |
|---|---:|
| < 1 KiB | 0 |
| 1–4 KiB | 639 |
| 4–16 KiB | 4 888 |
| 16–64 KiB | 4 394 |
| 64–256 KiB | 2 394 |
| 256 KiB–1 MiB | 1 067 |
| 1–4 MiB | 424 |
| 4–16 MiB | 228 |
| 16–64 MiB | 18 |
| ≥ 64 MiB | 0 |

Minimum 1 961 B, Median 31 299 B, Maximum 32,9 MiB. Blöcke pro Bundle: 1 Block bei 6 618 Bundles,
2–9 Blöcke bei 6 189, ≥ 10 Blöcke bei 1 320.

Stichprobe (kleine Bundles, bei 5 %, 15 % und 25 % der Größenreihenfolge):

| Bundle | Größe | Knoten | Blöcke (unkomp. → komp., Art) |
|---|---:|---:|---|
| `Battle/btlv/waza/sequence/ew306` | 4 196 B | 1 | 1: 12 800 → 4 067, LZ4HC |
| `UIs/textures_mass/pokemon_dp/pm0136_00_00_00_dp` | 5 364 B | 2 | 1: 42 052 → 5 213, LZ4HC |
| `Battle/btlv/waza/camera/wait/envcamera_w_f_138` | 10 527 B | 1 | 1: 36 740 → 10 398, LZ4HC |

Die Blockinfo wurde nur in die Tabelle (wenige Dutzend Bytes) entpackt, die Nutzdaten blieben unberührt.

## 3. Stammdaten (Master-Daten) und Laden

Bundles mit Stammdaten laut Namen (Größe in Bytes):

| Bundle | Größe | Vermuteter Inhalt |
|---|---:|---|
| `Pml/personal_masterdatas` | 125 957 | Pokémon-Grunddaten (Personal-Tabelle) |
| `Dpr/masterdatas` | 449 274 | Haupt-Stammdaten des Spiels (Items, Moves, Trainer, Shops …) |
| `Battle/battle_masterdatas` | 37 820 | Kampf |
| `UIs/masterdatas/uimasterdatas` | 353 687 | UI-Daten |
| `Effects/masterdatas/effectdatabase` | 38 342 | Effekt-Datenbank |
| `Contest/md/contest_masterdatas` | 23 744 | Wettbewerb |
| `GMS/md/gms_masterdatas` | 15 821 | GTS |
| `FureaiHiroba/fureai/masterdata` | 153 624 | Freizeitbereich |
| `UnderGround/masterdata` | 12 629 | Untergrund |
| `Union/unionroom/masterdata` | 2 259 | Union-Raum |
| `Dpr/scriptableobjects/gamesettings` | 18 056 668 | Einstellungen, ScriptableObjects (groß) |
| `Message/*` | 1,2–1,5 MB je Sprache | Texte (siehe 6.) |

Lade-Hinweise aus dem Code (Il2CppDumper-Ausgabe):

- Der Asset-Zugriff läuft über die Klasse `SmartPoint.AssetAssistant.AssetManager` (`RequestAssetBundle`, `LoadAssetBundle`,
  `LoadAsset(assetPath)`), konfiguriert über ein `AssetBundleDownloadManifest` (Version 6, Liste von `AssetBundleRecord`).
  Bundle-Namen entsprechen den relativen Pfaden unter `AssetAssistant`.
- `DataManager` (`StartUpLoad`, `Load(string assetBundleName)`) hält die statischen Tabellen (u. a. Trainer-, Shop-,
  Turm-Tabellen) und lädt sie beim Start aus Bundles.
- Tabellenklassen sind `ScriptableObject`s mit „Sheet“-Unterklassen: `PersonalTable`, `ItemTable`, `WazaTable`,
  `GMSMasterData`. Das bestätigt, dass die Stammdaten als serialisierte ScriptableObjects im Bundle liegen und nicht als
  eigenes Binärformat.
- String-Literale nennen die Bundle-Namen `personal_masterdatas`, `battle_masterdatas`, `masterdatas`, `md/gms_masterdatas`,
  `md/contest_masterdatas`, `masterdatas/uimasterdatas`, `masterdatas/effectdatabase`; ebenso `pokemons/battle/{0}`,
  `pokemons/field/pm{0:D4}_00_00`.
- Texte: `MessageManager` mit `MsgDataFileLoader`, Sprach-IDs wählen das Bundle (`GetFileNameByLanguageId`).

## 4. Audio (Wwise)

| Merkmal | Wert |
|---|---|
| `.bnk` | 696 Dateien, 56,5 MiB (kleinste 2 804 B, Median 39 457 B, größte 23,4 MiB) |
| `.wem` | 3 241 Dateien, 361,5 MiB |
| Gesamt Audio | 419,6 MiB (inkl. `PluginInfo.xml`, `Wwise_IDs.h`) |
| Bank-Header | alle 696 Banks beginnen mit `BKHD`, Versionsfeld = **135** |
| WEM-Container | alle RIFF/WAVE, `fmt`-Codec-Tag `0xFFFF` (Wwise-Vorbis) |

Bankversion 135 entspricht nach meiner Kenntnis Wwise 2019.2.x (nicht anhand des Dumps bestätigt).
Im Code gibt es `AkSoundEngine`, `AkSwitchSettings`, `Init.bnk` und die Meldung zum Kopieren der Banks in StreamingAssets.

## 5. Movie

18 Dateien, 456 MiB, alle `.webm` (EBML, DocType `webm`). In den ersten 64 KiB ist bei allen der
Videocodec **VP8** (`V_VP8`) erkennbar, kein VP9. Eine Audiospur ist in diesem Bereich nicht
gekennzeichnet (nicht geklärt).

| Gruppe | Dateien | je Datei |
|---|---:|---|
| Opening je Sprache (`op`) | 9 | ca. 19,8–20,7 MB |
| Opening-Loop | 1 | 0,97 MB |
| Ending (`ed_female/male_00–03`) | 8 | ca. 37 MB |

## 6. Texte und Lokalisierung

Message-Bundles (12): `Message/Message` (3,7 KB, vermutlich Index), `common_msbt` (sprachunabhängig), sowie
`jpn`, `jpn_kanji`, `english`, `french`, `german`, `italian`, `spanish`, `korean`, `simp_chinese`, `trad_chinese`.
Das sind 10 Sprachvarianten (Japanisch in Kana und mit Kanji). Der Code kennt die Sprach-IDs JPN, USA, FRA, ITA, DEU,
ESP, KOR, SCH, TCH (ID 6 fehlt).

Sprachendungen an Dateinamen, jeweils 9 Sprachen (`en`, `fr`, `ge`, `it`, `jp`, `ko`, `si`, `sp`, `tr`):
UIs (10 Dateien je Sprache), GMS (9), Contest (1), alle 9 Opening-Movies. Die Kürzel `si`/`tr` stehen vermutlich für
vereinfachtes/traditionelles Chinesisch (Vermutung).

## 7. Offene Fragen

- ~~Was genau ist `Dpr.bin`?~~ Geklärt: Bundle-Katalog (`AssetBundleDownloadManifest`, .NET-BinaryFormatter, Version 6), siehe `docs/bundle-katalog.md`.
- Welche Assets (Pfade) stecken in den Bundles? Dafür müssen die Blockdaten entpackt und die Serialisierung gelesen werden (Typbaum, TypeTree).
- Wie `Message/Message` und `common_msbt` zusammenspielen, welches Format die Texte im Bundle haben (MSBT?).
- In welchen Bundles liegen Items, Moves, Karten, Trainer genau (vermutlich `Dpr/masterdatas`, aber nicht verifiziert)?
- Aufruferkette `DataManager.StartUpLoad` → konkrete Bundle-Namen ist noch nicht durch Decompile belegt.
- Hat der Movie-Container eine Audiospur (Vorbis/Opus), Auflösung und Framerate?
- Wwise-Version exakt, und Zuordnung `.wem` ↔ Bank (Event-IDs aus `Wwise_IDs.h`).
- Dienen Bundles mit 4 Knoten (1 Stück) und die 86 unkomprimierten Blöcke einem Sonderzweck?
