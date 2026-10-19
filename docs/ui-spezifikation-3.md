# UI-Spezifikation 3: Stubs im Hauptprojekt, Original-Fenster im Spiel, Kampf-UI

Stand: 2026-10-19, Todo `ap-ui`, Scheibe 2. Nur Zahlen, Verfahren und eigener Code; keine Spielinhalte, Texte oder Bilder im Repo (Aufnahmen und Dumps unter `work/`, gitignoriert). Die Logik ist von Hand in eigener Formulierung geschrieben, nichts maschinell aus Pseudocode übersetzt.
Messung: Haupteditor Unity 6000.3.26f1 (Metal), Spielstand und Daten lokal, Spielmodus im Editor mit Eingabeskript. Kein Ton.

## 1. Ergebnis in Kürze
- **Stubs laufen im Hauptprojekt:** `stub_gen.py gen` nach `unity/Assets/XnuStubs` (gitignoriert, 887 Dateien, 5 MB), 0 Compilerfehler, vorhandene Tests unverändert grün (696/696 vor den neuen Tests). Konflikte mit `Xnu.*`: 0 gleiche volle Namen.
- **Schalter:** `XNU_STUBS` per `unity/Assets/csc.rsp` (gitignoriert, gilt nur für Assembly-CSharp). Ohne die Datei fehlen die Hooks (`Assets/Scripts/DprHooks`, alles in `#if XNU_STUBS`), das Projekt baut ohne Stubs.
- **Original-UI im Spiel (Editor):** Hauptmenü (8 Einträge im Raster), Party (6 Pokémon: Name, Stufe, KP-Balken, Geschlecht, Icon), Beutel (8 Taschen, Items und Mengen aus dem Spielstand, Beschreibung, Geld), Auswahlfenster (Ja/Nein aus dem Original-Kontextmenü) und Kampf-Statusfenster/Attackenliste aus den Original-Prefabs. Alle Texte aus den lokalen Textdateien, Sprites aus den Bundles, Original-Shader nie geladen.
- **Tests:** `UiScreensTests` (Cursor, Menü-, Party-, Beutel-Modell, Bundle-Filter, Textbindung, Datenbindung aus dem Spielstand), 54 neue Tests.

## 2. Build-Reihenfolge
`tools extract il2cpp masterdata shaders video audio assets stubs unity-build deploy`. Die Stufe `stubs` schreibt `XnuStubs` **und** `csc.rsp`; die Stufe `unity-build` löscht `csc.rsp`, wenn `XnuStubs/manifest.json` fehlt. Hält ein Editor das Projekt, überspringt `stubs` (neue Dateien lösen Neukompilierung aus). Ohne Dump: Stufe auslassen, Projekt baut ohne Original-Prefabs; die Fenster fallen auf die eigenen (Textbox-Menü, Platzhalter-Kampfansicht) zurück (`UiWindowManager.IsAvailable`). `link.xml` hält Assembly-CSharp und die Stub-Assemblen (IL2CPP-Stripping; im Player ungeprüft).

## 3. Aufbau
| Teil | Inhalt |
|---|---|
| `Xnu.UI/Logic/ListCursor.cs`, `ScreenModels.cs` | `ListCursor`, `GridCursor`, `MainMenuModel`, `PartyScreenModel`, `BagScreenModel`, `HpStages`, Zeilenmodelle ohne Unity-Typen |
| `Xnu.UI/Runtime/UiBridge.cs` | Schnittstellen zu den Stubs (Textfeld, Menü, Party, Beutel, Kontextmenü, Kampf-UI) |
| `Scripts/DprHooks/UiBridgeHooks.cs` | partial-Teile der Stubs (Assembly-CSharp, nur `XNU_STUBS`): reichen serialisierte Felder durch, keine Logik |
| `UiBundles` | Provider für UI-Bundles: keine Shader-Bundles, nur Sprachvariante `.ge`, Atlas-Nachlieferung (`SpriteAtlasManager.atlasRequested`), Pokémon-Icons (`textures_mass/pokemon_dp`) |
| `OriginalWindowFactory`, `UiMaterialFixer`, `UiTextBinder` | Prefab instanziieren, Canvas auf 1280×720/Breitenabgleich, Materialien ohne Shader durch eigene Shader (`XnuUiAdd`, `XnuUiGray`) oder Standardmaterial ersetzen, Schrift = TMP-Standard, Beschriftungen aus Datei+Label füllen |
| `OriginalViews`, `UiWindowManager`, `BattleUiSkin` | Ansichten und Fensterstapel (Menü → Party/Beutel → Auswahl/Hinweis), Kampf-Skin |
| `Game.Unity/GameUiData`, `GameDriver`, `BattleView` | Daten aus Spielstand und Texten; Menü-Taste öffnet das Hauptmenü, Plus im Menü fragt „Speichern“; Kampfansicht nutzt das Skin |

## 4. Beobachtungen und Lücken
- **Meldungsfenster:** hat im Original kein Prefab (`resources.assets`); die eigene `TextboxView` mit Original-Rahmen bleibt.
- **Animator-Zustände** der Fenster sind in den Bundles nicht benennbar (kein Editor-Controller); die Fenster-Animatoren werden abgeschaltet, kein Öffnen/Schließen-Effekt. DOTween-Animationen laufen nicht (Farbbänder oben in der Party stehen still).
- **Kampf:** Statusfenster und Attackenliste aus dem Original; die **Befehlsliste** (`BUIActionList`) steht im Prefab an der Ausblendposition (Position nur im Code), bis dahin das eigene Textmenü. Kein Ziel-/Beutel-/Pokémon-Wechsel-Fenster aus dem Original, Meldungen weiter eigene Box. Typ-Grafik der Attacken nimmt den Typindex der Stammdaten an [A]. Pokémon-Modelle im Kampf: **nicht umgesetzt** (Platzhalter-Kästen).
- **Sprites zur Laufzeit belegt:** Beutel-Symbol im Hauptmenü, Taschen-Kopfbild, Geschlechtsgrafik der Party sind im Prefab leer und werden ausgeblendet bzw. nur eingefärbt; Item-Symbole fehlen (Quelle in den Bundles nicht gefunden). Status (Vergiftung usw.) wird nicht angezeigt.
- **Schrift:** TMP-Standard (LiberationSans); japanische Reststrings aus Prefabs erscheinen als Kästchen (Warnungen „Unicode … nicht gefunden“); Originalschrift nicht angebunden.
- **Party/Beutel-Unterseiten:** Auswahl in Party/Beutel tut nichts (Kontextmenü, Item-Verwendung, Status fehlen). Pokédex, Trainerpass, Karte, Kapsel-Deko, Einstellungen, Geheimgeschenk: nur Rahmen, nicht anwählbar.
- **Beschriftungen:** unbelegte Platzhalter `{n:m}` werden geleert; im Beutel überlagert sich noch ein statischer Text („Kampf“) mit der Beschreibung.
- **Player-Test (macOS) und iPad:** **nicht durchgeführt** (Zeit). Bundles für den Player: `UIs/ui/uiresidentwindow` 8,15 MB, `UIs/ui/prefab/battleviewuisystem` 1,05 MB, dazu deren Abhängigkeiten (Atlanten, `.ge`-Varianten); in `scripts/subsets/vslice-start.txt` vermerkt, Gesamtgröße der Abhängigkeiten ungemessen. Ob die Stufe `assets` Abhängigkeiten mitkopiert und ob `bundle_retarget` die UI-Bundles unverändert lässt, ist ungeprüft.
- **Neuer Testspielstand (Stadt):** Die Szenarien oben liefen noch mit dem alten Stand (Zone 167); Umstellung auf die Ablagezone aus dem Save steht aus.

## 5. Nächste Screens
1. Befehlsliste des Kampfs (Position, Ein-/Ausblendung), Ziel- und Beutelfenster; danach Modelle der Pokémon (Katalog `Pokemon Database/pokemons/battle/pmNNNN_FF_00`, 1.304 Prefabs) mit `MaterialRemapper`.
2. Party-Kontextmenü, Pokémon-Status (`pokestatus`), Item-Verwendung, Statusanzeige.
3. Original-Schrift und Zeilenbreiten, Fensteranimation (DOTween-Ersatz), Player-/iPad-Lauf mit Subset und Größenmessung.

## 6. Reproduktion
```
python3 scripts/stub_gen.py gen --out unity/Assets/XnuStubs          # oder scripts/build_all.sh --only stubs
unity command … recompile ; scripts/unity_safe.sh test               # Tests
# Spielmodus: Szene Game, Umgebungsvariablen XNU_GAMEDATA/XNU_SCRIPTED_INPUT/XNU_SHOT_DIR, Eingabeskript (Tasten Plus, A, B, Pfeile; shot NAME)
```
