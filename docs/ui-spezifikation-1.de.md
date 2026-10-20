# UI-Spezifikation 1: Aufbau der Original-UI, Inventar, Plan für den Rebuild

Stand: 2026-10-19, Todo `ap-ui` (Analysephase). Nur Strukturen, Klassen-/Feldnamen und Zahlen; keine Spielinhalte oder Texte.
Texte, Format, Tags und Schriften stehen in `docs/lokalisierung.md`. Alle Zahlen stammen aus dem eigenen Dump (Unity 2019.4.27f1, Switch), gelesen ohne Unity-Editor mit UnityPy und `work/il2cpp/dump.cs`.

## 0. Prüfstufen
**Belegstufen** der Aussagen:
- **[D]** aus den Daten gemessen (Katalog `Dpr.bin`, UnityPy über die Bundles, `resources.assets`, Stammdaten-JSON).
- **[S]** aus `dump.cs` (Klassen, Felder, Offsets, Konstanten, Signaturen), also Form, nicht Logik.
- **[A]** Annahme oder Schluss; im Text benannt.
- **[T]/[V]** Code durch Tests / gegen echte Daten geprüft (nur Abschnitt 9).
Ghidra-Pseudocode wurde **nicht** ausgewertet. Die Logik der Fensterklassen ist daher noch zu lesen, bevor ein Screen nachgebaut wird (Aufwand in Abschnitt 7 enthält das).

**Abnahmestufen** je nachgebautem Screen (für die spätere Umsetzung):
- **U1 Struktur:** Prefab/Bundle lädt, Hierarchie vollständig, keine fehlenden Verweise, Sprites aufgelöst.
- **U2 Layout:** bei 1280×720 (16:9) und 4:3 gleiche Positionen/Größen wie im Original (Maße aus RectTransform-Daten, Stichproben mit Referenzbildern des Nutzers, z. B. aus Ryujinx).
- **U3 Verhalten:** Navigation, Eingaben, Zustände und Texte folgen der Originallogik (Tests mit synthetischen Daten, Abgleich gegen Pseudocode).
- **U4 Pixelgleich:** Bildvergleich mit Referenz bei festen Zuständen (setzt die portierten UI-Shader voraus, Abschnitt 8).

## 1. Ergebnis in Kürze
- Die UI ist **Unity uGUI** (Canvas, RectTransform, Image, Slider, ScrollRect, LayoutGroups) mit **TextMeshPro** und einer eigenen Schicht `Dpr.UI.*` (325 Klassen, 4.834 Methoden), kein eigenes Zeichensystem. [D][S]
  Basis: `UIManager` (Singleton), `UIWindow` (Fenster-Basis), `UIWindowID` (74 Fenster), `UIText` (TMP-Unterklasse mit Anbindung an das Message-System), `UINavigator`/`Cursor` (Tastennavigation), `UIInputController` (Switch-Tastenmasken).
- Die Fenster sind **Prefabs in Bundles**: 82 Prefab-Wurzeln in `UIs/ui/*` und `Dpr/fieldui/*`; 53 davon stecken in einem Sammelbundle `ui/uiresidentwindow` (8,2 MB). Die Tabelle `UIDatabase.UIWindow` (74 Zeilen) ordnet jeder `UIWindowID` Bundle und Prefab zu. [D]
- Referenzauflösung **1280×720**, `CanvasScaler` „Scale With Screen Size“ in 78 von 84 Scalern der Prefab-Bundles, Abgleich nach Breite (Match 0). Das passt zu 16:9; auf 4:3 (1024×768, iPad) ändert sich die Höhe. [D]
- Gesamtumfang der UI-Assets: 1.994 Bundles im Projekt `UIs` plus 11 Message-Bundles (zusammen 95,3 MiB) plus 5 Schriftbundles (24,2 MiB); 7.282 Sprites, 2.584 Texturen, 12.812 GameObjects in den Prefabs, 499 Animationsclips, 303 Animatoren. [D]
- Texturen sind überwiegend **ASTC** (läuft auf Apple-GPUs nativ), ein Teil **DXT5** (BC3, auf iOS/iPadOS nicht nativ), kleine Icons RGBA32. [D]
- Die zentralen Laufzeitobjekte (`UIManager`, `MsgWindowManager`, `MessageManager`, `NowloadingController`, `UIModelViewController`) liegen in `Data/resources.assets` **ohne TypeTree**. Dort sind sie nur über die Feldlayouts aus `dump.cs` lesbar; wir bauen sie ohnehin selbst. [D]
- **Empfohlene Strategie:** Original-Prefabs aus den Bundles laden und durch **eigene Skripte mit denselben Klassen-/Feldnamen** (`Dpr.UI.*`, Assembly-CSharp) bedienen; Kandidat für einen Spike, sobald ein Editor frei ist (Abschnitt 6). Aufwand Kernumfang etwa **150–230 Entwicklertage** [A]; zuerst Framework und Nachrichtenfenster.
- Gebaut und getestet in diesem Schritt: der Text-Leser `Xnu.Text` (Abschnitt 9).

## 2. Inventar

### 2.1 Katalog (`Dpr.bin`), Projekt `UIs` und `Message`
| Gruppe (Pfad im Katalog) | Bundles | Größe | Assets (Katalog) | Inhalt |
|---|---:|---:|---|---|
| `UIs/ui` | 34 | 24,5 MiB | 87 Prefabs | Fenster-Prefabs: 53 in `uiresidentwindow`, je 1 für Wettbewerb/Handel/UG/Union/Team, 2 Übergänge, 6 Hall-of-Fame-Teile |
| `UIs/textures` | 70 | 10,7 MiB | 1.608 PNG, 19 SpriteAtlas | Atlanten je Bereich (`common`, `box`, `zukan`, `map`, `menutop`, `report`, `setting`, `trainercard`, `pokemon`, `field/*`, `halloffame/*`) |
| `UIs/textures_mass` | 1.845 | 38,4 MiB | 4.296 PNG, 1 SpriteAtlas | Pokémon-Icons: `pokemon_dp` 1.302 Bundles (7,1 MiB), `pokemon_l` 542 (14,9 MiB), `texturemass` 1 (16,4 MiB) |
| `UIs/shareduiassets` | 19 | 2,0 MiB | 450 PNG, 19 SpriteAtlas | `sharedui` (947 KB) + je 9 Sprachvarianten `sharedui_lang.*` und `battle_lang.*` |
| `UIs/gms` | 12 | 4,3 MiB | 4 Prefabs, 10 SpriteAtlas, 1 PNG | Minispiel-UI (Sprach-Grafiktexte `graphictext.*`) |
| `UIs/contestphoto` | 4 | 0,4 MiB | 4 PNG | Rahmen für Wettbewerbsfotos |
| `UIs/masterdatas` | 1 | 0,3 MiB | 6 `.asset` | `UIDatabase` (32 Sheets), `PlaceNameTable`, `TownMapTable`, `TownMapGuideTable`, `DistributionTable`, `InputLimitTable` |
| `UIs/searchdatas` | 9 | 0,2 MiB | 9 `.asset` | Suchindex der Pokédex-Suche, je Sprache |
| `Message` | 11 | 14,5 MiB | 1.280 `.asset` | Texte (siehe Lokalisierung) |
| zusammen | 2.005 | 95,3 MiB | | |
Weitere UI-nahe Quellen [D]: `Dpr/font` (5 Schriftbundles, 24,2 MiB, Abschnitt 2.4), `Dpr/fieldui` (2 Bundles, 0,8 MiB: `fieldcanvas` 24 GameObjects, `encseqgym`), `Union/unionroom` (1 Prefab, 2,9 MiB), `Contest/textures` (10 SpriteAtlas, 2,7 MiB),
`Dpr/scenes/title` (Szenenbundle, 287 KB), Szene `field` (3 Canvas mit CanvasScaler), `Data/resources.assets` (10 Canvas, 130 GameObjects). Nicht im Katalog, aber auf der Platte: 81 Sprach-Texturbundles `GMS/textures/graphictext/*` (`docs/bundle-katalog.md`).
**Sprachvarianten** (Endung `.en .fr .ge .it .jp .ko .si .sp .tr`): 11 Bundlefamilien × 9 = 99 Bundles, Summe 11,6 MB: `common_lang`, `sharedui_lang`, `battle_lang`, `gms/graphictext`, `contestgraphictexture`, `searchdatas/indexdata`, fünf Hall-of-Fame-Logos. Texte in Bildern (Logos, Beschriftungen) sind also je Sprache eigene Grafiken. [D]

### 2.2 Objekttypen aller 1.994 `UIs`-Bundles [D]
GameObject 12.812, RectTransform 12.753, MonoBehaviour 12.025, CanvasRenderer 9.598, Sprite 7.282, Texture2D 2.584, MonoScript 706, AnimationClip 499, CanvasGroup 452, Canvas 363, Animator 303, Material 119, AnimatorController 118, SpriteAtlas 55, Font 20, Camera 17, BoxCollider2D 22.
Skriptklassen in den Prefabs (11.883 MonoBehaviours, 337 Klassen): `UnityEngine.UI.Image` 6.923, `Dpr.UI.UIText` 1.648, `HorizontalLayoutGroup` 195, `Dpr.UI.UINavigator` 184, `PokemonIcon` 180, `SealIcon` 149, `Capsule2DGridCell` 148, `RawImage` 147, `VerticalLayoutGroup` 145,
`Slider` 90, `RectMask2D` 88, `Dpr.UI.Cursor` 87, `CanvasScaler` 84, `DOTweenAnimation` 75, `GraphicRaycaster` 50, `Dpr.UI.HpBar` 52, `UIWindowStateMachine` 54, `TMP_FontAsset` 49 (eingebettete Schriftobjekte). Assembly der Skripte: 240 × `Assembly-CSharp.dll`, 14 × `UnityEngine.UI.dll`, 1 × `Unity.TextMeshPro.dll`. [D]
Materialien (119, Shaderzuordnung über die Pfad-IDs des Shader-Bundles aufgelöst): 40 × `TextMeshPro/Mobile/Distance Field`, 9 × `TextMeshPro/Distance Field`, 23 × `UI/Custom`, 2 × `UI/UI-Multiply`, 1 × `UI/UI-SoundWave`,
19 × Nachbearbeitung (`Custom/Bloom*`, `Fxaa`, `Gaussian7x7`, `DepthOfField`, Focus-Shader, `Dpr/PostEffect/*`; gehören zu den Modellansichten, 3.5) und 22 mit Shader außerhalb von `Dpr/shaders` (vermutlich Unity-Standard-UI-Shader, [A]). [D]

### 2.3 Texturformate (Stichprobe über alle Gruppen; Zahlen = Texturen) [D]
| Gruppe | Formate | typische Größen |
|---|---|---|
| `textures` (37 Stichproben) | DXT5 25, ASTC 6×6 12 | 1264×240, 1280×400, 1024², 2048² |
| `shareduiassets` | ASTC 4×4 9, ASTC 6×6 11 | 1024×512, 1024×256, 512², 2048² |
| `gms` | ASTC 6×6 11, ASTC 4×4 1, Alpha8 2, RGBA32 1 | 1024×2048, 2048², 1280×720 |
| `contestphoto` | ASTC 6×6 | 1280×720 |
| `textures_mass` | RGBA32 | 88×88, 256² |
Folge: DXT5 muss auf iOS/iPadOS beim Laden dekomprimiert oder beim Build umkodiert werden (Speicher: RGBA32 ist 4× so groß wie BC3); gemessen ist das nicht. [A] `Sprite.texture` ist bei Atlas-Sprites `null`; Zugriff nur über das SpriteAtlas-Objekt (`docs/m0-bundle-kompatibilitaet.md`).

### 2.4 Schriften und Texte
Fünf TextMeshPro-Schriftbundles (SDF, statische Atlanten plus dynamischer Fallback mit eingebetteter TTF), 1 Schriftfamilie je Sprachgruppe: `efigs_font`, `jpn_font`, `kor_font`, `sch_font`, `tch_font`. Zahlen und Lizenzhinweis in `docs/lokalisierung.md` Abschnitt 7.
Message-Dateien: 11 Bundles, 119 Dateien je Sprache, Format `MsbtData` (siehe `docs/lokalisierung.md`). Im Spielcode: `UIText` bindet Datei und Label an ein Textfeld.

### 2.5 Animationen [D]
499 `AnimationClip` und 303 `Animator` (118 `AnimatorController`) in den UI-Bundles, 54 `UIWindowStateMachine`-Verhalten, 75 `DOTweenAnimation`-Komponenten (DOTween-Paket nötig). Fenster öffnen/schließen laufen über Animator-Zustände (`UIWindowStateMachine`, Parameter `animParamConnectId`, `animParamStateId`);
`UIDatabase.UIWindow.WindowAnimId` (20, 30, … 700) ist die Verbindungsnummer je Fensterpaar. [D][S]

## 3. Wie das Original die UI baut

### 3.1 Canvas und Skalierung [D]
- `CanvasScaler` in den Prefab-Bundles (84): `ScaleWithScreenSize`, Referenz 1280×720, Match-Modus „Width or Height“, Match 0,0 bei 77 Stück (Breite maßgeblich); 1 mit Match 1,0; 3 `ConstantPixelSize` mit Referenz 1280×720 und 3 mit Referenz 800×600 (die Referenz wirkt dort nicht). Die Szenen `title` (1 Scaler) und `field` (3) haben `ConstantPixelSize` mit 800×600.
- `Canvas`: 357 in den Prefab-Bundles (363 in allen `UIs`-Bundles); Render-Modus Overlay (0) 77, Kamera (1) 5, Wert 2 (WorldSpace) 275 (überwiegend verschachtelte Unter-Canvas ohne eigene Wirkung, [A]). `overrideSorting` bei 69.
- Sortierreihenfolge (Konstanten in `UIManager`): Poketch 200, Fenster 400 (+100 je weiteres Fenster), Kontextmenü 9900, Übergang 16384, Fehlerdialog 16484. [S]
- Das Original rendert auf 16:9 (Switch 1280×720/1920×1080). Der Rebuild-Ausschnitt (`DisplayController`, 16:9 mit Balken bei 4:3, siehe `docs/eingabe.md`) bleibt die Grundlage; Canvas wird mit Referenz 1280×720 und Breitenabgleich übernommen. [A]
- `UIWindow.EnableMainCameraByUiMode` und `UIDatabase.UIWindow.UiCameraMode` (−1 bei 5, 0 bei 27, 1 bei 42 Fenstern) steuern vermutlich, ob die Feldkamera bei geöffnetem Fenster abgeschaltet wird. [S][A]

### 3.2 Verwaltung: `UIManager`, `UIWindow` [S][D]
- `UIManager.CreateUIWindow<T>(UIWindowID)` instanziiert das Prefab aus einem Objektpool (`ObjectPool<UIWindowID, UIInstance>`), `GetCurrentUIWindow<T>`, `GetExistWindow<T>`, `SetTransitionWindowIds`, `PlayTransition(TransitionID, FadeType)` (2 Übergangs-Prefabs, Fade-Dauer 0,1 s).
- Laden: `LoadResidents` / `LoadWindows` lesen `UIDatabase` (`UIWindow` 74 Einträge: 54 resident, 20 nachladbar, 6 mit `Firstload`), danach `OpLoadSpriteAtlases` (7 Atlanten: `SharedUI`, `Common`, `Common_Lang`, `TextureMass`, `SharedUI_Lang`, `Battle_Lang`, `Zukan`; 3 davon sprachabhängig). Atlanten werden über `SpriteAtlasManager`-Rückruf `OnAtlasRequested` gebunden. `Reload(langId)` tauscht die Sprachatlanten.
- `UIWindow` ist die Basis aller Fenster: `OnCreate`, `OnOpen(prevWindowId)`, `OnTransition…`, `PlayOpenWindowAnimation`, Animator-Zustände „In/Out“, Hilfen `OpenMessageWindow`, `CreateContextMenuYesNo`, Abfragen `IsPushButton/IsRepeatButton/IsOnButton/IsAccelButton`. 74 Fenster-IDs: `XMENU 0, ZUKAN 1, POKEMON 2, BAG 3, CARD 4, REPORT 5, MAP 6, GIFT 7, SETTING 8, SEAL 9, POKEMON_STATUS 10, CONTEXTMENU 11, LEVEL_UP 12, KEYGUIDE 13, SELL_ITEM 14, POKEMON_BATTLE 15, BOX 16 …, BATTLE_MATCHING_* 66–69, TVRANKING 71, YUNION 72, UNION_RECODE_MATCHING 73`.
- Datenbank: `UIDatabase` mit 32 Sheets, darunter `PokemonIcon` 1.958 (Icon-Bundle und -Asset je Pokémon/Form), `Keyguide` 226, `ContextMenu` 112 (Datei+Label), `ZukanDisplay` 1.958, `ZukanCompareHeight` 1.954, `Wallpaper` 32, `Box` 40, `SealTemplate` 34, `ShopMessage` 26 (je 9 Label), `RankingDisplay` 10, `HideWazaName` 101. `MsgWindowData` (Dpr/masterdatas): 2.380 Sprechernamen-Zeilen, 25 Fensterrahmen, 4 Hintergründe, 12 Schilder, 7 Ton-Tags. [D]
- Der Bundle `ui/prefab/teammix` ist in `UIWindow` genannt (ID `BATTLE_MATCHING_TEAM_MIX`), fehlt aber im Katalog (Online-Funktion). [D]

### 3.3 Eingabe [S][D]
- `UIInputController` liest **Switch-Tastenmasken** (Bitwerte, die zu `nn::hid::NpadButton` passen, [A]): `ButtonA/B/X/Y`, `StickLLeft/Right/Up/Down`, `ButtonPlusMinus` (statische Felder in `UIManager`); `UIWindow.MoveLeftButton` 69632 (0x11000 = Stick links + D-Pad links), `MoveRight` 278528 (0x44000), `MoveUp` 139264 (0x22000), `MoveDown` 557056 (0x88000).
  Abgefragt wird je Tastenmaske mit `IsPush`, `IsRelease`, `IsRepeat`, `IsOn`, `IsAccel` (beschleunigte Wiederholung); `SetAutoButton` simuliert Tasten.
  Folgerung: `Xnu.Input` braucht einen kleinen **Adapter**, der `GameInput` in diese Maske plus Push/Repeat/Accel-Zeitlogik übersetzt (die Zeiten sind noch zu lesen). [A]
- Navigation: `UINavigator` (Nachbarn `left/right/top/bottom` und Stopp-Flags, 184 Instanzen in den Prefabs, also im Editor vorverdrahtet) plus `Cursor` (Animator-Zustände In/Out/Decide/Wait). Alles datengetrieben aus den Prefabs; nur die Logik fehlt.
- Touch: `UITouchInputController` (bis 10 Berührungen, Langtipp 1 s, Zustände Began/Moved/Stationary/Ended). iPad-Touch kann darauf abgebildet werden. Das Original nutzt Touch auf der Switch zusätzlich zu den Tasten (Pokédex, Box, Karte). [S][A]

### 3.4 Texte, Schrift, Nachrichtenfenster [S][D]
- `UIText : TextMeshProUGUI` (1.648 Instanzen): Felder `_useMessage`, `_messageFile`, `_messageId`, `_useTag`, `_sizeId` (`UIFontSizeID` SSS…XL), `_fontMaterialDataIndex`; Text wird beim Start und bei Sprachwechsel aus dem Message-System geholt. Textgrößen/Materialien liegen in `TextFontData`/`FontMaterialData` (`resources.assets`, nicht gelesen).
- Nachrichtenfenster: `MsgWindowManager` (Singleton) → `MsgWindow` (Zustandsmaschine: Öffnen, Schreiben, Tastenwarten, Beenden, Schließen) → `WindowMessage` (Schreibmaschine, Ereignisse) → `MsgTextContainer`/`WindowMsgText` (TMP). Varianten: Normal, **Schild** (`OpenBoardMsg`, 12 Schilder, 5 Texturen), **Item-Erhalt** (`OpenItemGetMsg`), **Kampf** (`OpenBtlMsg`, einzeilig). Zusatz: Sprechername (bis 10 Zeichen), Weiter-Symbol (`UIKeywaitIcon`), Ladesymbol, Fensterrahmen (25), Ja/Nein-Menü (`OpenYesNoMenu`, `OpenCustomMenu`).
  `MsgWindow`, `WindowMessage` usw. stecken als GameObjects in `resources.assets` (ohne TypeTree). Textgeschwindigkeit und Zeitwerte: `docs/lokalisierung.md` Abschnitt 9.

### 3.5 Modellansichten und Sonderrendering [S]
`UIModelViewController`, `PokemonModelView`, `CharacterModelView`, `MultiModelView`, `ModelViewBgCamera`, `ModelViewReflectionCamera` zeigen **3D-Modelle in der UI** (Pokédex, Party, Karte, Pokémon-Status, Trainerkarte) über eigene Kameras und Render-Texturen (`modelBgRoot`, Spiegelung). Das hängt von den Pokémon-/Charaktermodellen und deren Shadern ab (anderer Arbeitsstrang). `UIManager` hat zudem Unschärfe-Hintergrund (`_blurBg`, `UI/Blur` mit GrabPass), Graustufen (`_id_GrayscaleAmount`, `UI/UI-Gray`) und doppelte Materialien (`DuplicateImageMaterialParam`).

### 3.6 Eigene Bestandteile außerhalb des Fensterbaums
`HpBar`/`BUIHpSlider` (Slider mit Farbstufen: Allert unter 50 %, Danger unter 25 %, `HpDead` 0; Dauer und Ease-Funktion aus DOTween), `PokemonIcon`, `TypePanel`, `PokemonSick` (Zustandsmarke), `RaderChart` (Statuspolygon), `Capsule2D/3D*` (Sticker-Kapseln), `TownmapSymbol` (75), `Poketch*` (27 Klassen, 14 Mini-Apps).

## 4. Screens (Zuordnung und Umfang)
Umfang = GameObjects/Bilder/Textfelder in der Prefab-Hierarchie ([D], `scripts/ui_inventory.py windows`) und Methodenzahl der zugehörigen `Dpr.UI`-Klassen ([S]; Zählung der Methodensignaturen je Familie, grob).

| Screen | `UIWindowID` / Prefab | GameObjects | Bilder | Textfelder | Klassen / Methoden | Besonderheiten |
|---|---|---:|---:|---:|---|---|
| **Titel** | Szene `Dpr/scenes/title` (kein Fenster) | 210 | 22 | 140 | `Title`, `TitlePlayer`, `MoviePlayer`, `StaffrollRow` (20) | Video + Abspannzeilen (140 `UIText`); Canvas 800×600 konstant; Video siehe `ap-cutscenes-video`; keine Eingabemenüs im Bundle |
| **Hauptmenü** | `XMENU` / `xmenu` | 131 | 83 | 14 | `XMenuTop` | 8 Einträge (`XMenuTopItem`); Spieler-Grafiken aus `CharacterBag` (28 Zeilen) |
| **Beutel** | `BAG` / `bag`; `BAG_UG` / `bagug` | 409; 59 | 208; 26 | 87; 9 | 11 / 187 | Taschen-Kategorien (`BagCategoryButton` 16), Item-Liste, Beschreibung, Mengenwahl, Attacken-Maschinen (`BagWazaSelectPanel`) |
| **Party / Pokémon** | `POKEMON`, `POKEMON_SELECT`, `ROTOM_SELECT` / `pokemon`, `pokemonselect`, `rotomselect` | je 259 | je 128 | je 56 | 41 / 497 (mit Status/Attacken) | 30 `PokemonPartyItem`; Modellansicht; Kontextmenü |
| **Pokémon-Status** | `POKEMON_STATUS`, `WAZA_MANAGE` / `pokestatus`, `wazamanage` | 383; 247 | 217; 113 | 69; 52 | in obigem | Reiter (`PokemonStatusTab` 9), Radar-Diagramm, Attackenliste, Wettbewerbsattacken, Bänder |
| **Box** | `BOX` / `box` | **2.220** | 1.705 | 81 | 22 / 437 | größtes Prefab; Tray (30 `BoxTrayItem`), Suche, Hintergrundbilder (32 Wallpaper), Mehrfachauswahl, unendliches Scrollen |
| **Pokédex** | `ZUKAN`, `ZUKAN_REGISTER`, `_HABITAT`, `_COMPARE`, `_MOVING` / `zukan`, `zukanregister`, `zukanhabitat`, `zukancompare`, `zukanmoving` | 103; 75; 115; 89; 153 | 52; 38; 70; 47; 126 | 15; 10; 1; 9; 2 | 24 / 327 | Modelle (1.958 Anzeigeparameter), Verbreitungskarte, Größenvergleich; `zukanmoving` (Ton-Spielerei, Wwise, ohne Ton nur Optik) |
| **Kampf-UI** | Prefab `battleviewuisystem` (kein `UIWindowID`) | 638 | 390 | 93 | 24 / 276 (`Dpr.Battle.View.UI`) | Befehlsmenü `BUIActionList` (Kampf/Beutel/Pokémon/Flucht + XY-Rahmen), Attackenliste `BUIWazaList` (4 Knöpfe, Typ-Sprites, PP-Farben), Zielwahl `BUITargetSelect`, Statusfenster `BUIStatusWindow` (Name, Geschlecht, Stufe, HP-Balken `HpBar`/`BUIHpSlider`, EP-Slider, Zustand, Ball-Leiste), Situationsanzeige, Ergebnis, Meldungsbox über `MsgWindow.OpenBtlMsg` (einzeilig, `controlID` 1) |
| **Shop** | `SHOP_BUY`, `SHOP_EXCHANGE`, `SELL_ITEM` / `shopfriendly` (71), `shopflower` (80), `sellitem` (100); Boutique `shopboutique*` (35) | 35–100 | 13–53 | 5–24 | 19 / 286 | Kaufen/Verkaufen/Tauschen, Mengenwahl, Beschreibung; `ShopMessage` 26 Zeilen; UG-Shops (`shopug` u. a.) optional |
| **Dialog / Textbox** | `MsgWindow` (resources.assets), `DIALOG`, `CONTEXTMENU(_SCROLL)`, `KEYGUIDE` | 8 / 7 / 14 / 7 | 2 / 2 / 4 / 2 | 1–2 | 14 / 328 + `Dpr.MsgWindow` 23 / 336 + `Dpr.Message` 64 / 666 | siehe 3.4 und `docs/lokalisierung.md`; Ja/Nein-Menü aus `ss_box`-Labels |
| **Einstellungen** | `SETTING` / `setting` | 472 | 93 | 113 | 7 / 105 (mit XMenu, Report) | 14 Zeilen (`SettingMenuItem`); `ConfigID` 14 Einträge (Textgeschwindigkeit, Kampfanimation, Kampfregel, Fensterstil, Lautstärken …) |
| **Karte** | `MAP`, `MAP_WALL` / `map`, `mapwall` | 85; 91 | 50; 52 | 6; 7 | 10 / 73 | `TownMapTable` 218, `PlaceNameTable` 774, `TownMapGuideTable` 135 |
| **Trainerkarte / Bericht** | `CARD`, `REPORT`, `CERTIFICATE`, `BADGE_GET` | 61 / 35 / 8 / 3 | 10 / 13 / 2 / 1 | 40 / 12 / 3 / 0 | 10 / 152 | Modell, Abzeichen; Bericht = Speichern (`BackUpReport`) |
| **Sprache/Spieler/Start** | `SELECT_LANGUAGE`, `SELECT_PLAYER`, `BACKUP_START`, `NOW_LOADING`, Fehlerdialog | 49 / 42 / 51 / 6 / 5 | 34 / 29 / 23 / 3 / 1 | 0 / 0 / 12 / 0 / 1 | je 1–2 Fensterklassen | erster Start, Ladeanzeige |
| Poketch (Uhr-App) | `POKETCH` / `poketch` | 974 | 641 | 2 | 27 / 363 | 14 Mini-Apps; spät |
| Sticker | `SEAL`, `SEAL_TEMPLATE` / `seal` (637), `sealtemplate` | 637; 258 | 354; 137 | 12; 9 | 20 / 367 | 3D-Aufkleber; spät |
| Wettbewerb | `CONTEST_*` / `cont*` | 27–276 | | | 22 / 584 | spät |
| Beeren/Pofin | `KINOMI`, `POFIN*` | 46–106 | | | 9 / 138 | spät |
| Geschenke, Union, Kampfsuche, Online | `GIFT`, `UNION*`, `BATTLE_MATCHING_*`, `TVRANKING`, `YUNION` | | | | ≈ 50 / ≈ 500 | Online/Netzwerk; nicht im Umfang |

Bei ähnlichen Fenstern ist die Hierarchie gleich (z. B. `pokemon`, `pokemonselect`, `rotomselect` je 259 GameObjects): dieselbe Vorlage, nur Zustand und Skript unterscheiden sich. Das senkt den Aufwand. [D]
Die Zahlen „Klassen/Methoden“ umfassen nur die Namensfamilie; gemeinsame Hilfsklassen stehen im Framework (3.2, 3.3: 14 Klassen/328 Methoden). [S]

## 5. Abhängigkeiten zu anderen Arbeitsfeldern
- **Texte** (`Xnu.Text`): fertig als Leser; Grammatik fehlt (Lokalisierung Abschnitt 6).
- **Eingabe** (`Xnu.Input`): Adapter auf Tastenmasken, Wiederholungs-/Beschleunigungszeiten (Abschnitt 3.3).
- **Shader**: UI braucht die sieben UI-Shader und TextMeshPro-SDF; die 1:1-Treue der UI-Optik hängt an den portierten Shadern (`docs/shader-translator.md`). Bis dahin ist nur U1–U3 erreichbar.
- **Stammdaten/Speicher**: Beutel (ItemTable, Speicherstand), Party/Box/Pokédex (`PokePara`, `Save`), Shop (`ShopTable`), Karte (Zonen); Kampf-UI an die Kampf-Ansicht (nicht Teil dieses Teils).
- **Pokémon-Modelle** in UI-Ansichten (3.5) und **Video** (Titel).
- **Ton**: UI-Klänge (`SoundTag`, `MsgWindowSoundPlayer`, Wwise-Ereignisse in `PokemonVoice`) bleiben aus (Vorgabe: kein Ton, `AudioSafety`).

## 6. Strategie und Spike
**Ergebnis des Spikes S1: siehe `docs/ui-spezifikation-2.md` (Variante A bestätigt, Bindung nur in `Assembly-CSharp`).**
**Variante A (empfohlen): Original-Prefabs laden, Skripte nachbauen.** Die Bundles laden in Unity 6 (`docs/m0-bundle-kompatibilitaet.md`: alle 14.052 Bundles `ok`), uGUI-Komponenten und TMP-Schriften werden als Objekte erkannt. Die Prefabs verweisen auf `Dpr.UI.*` in `Assembly-CSharp.dll`.
Hypothese [A]: Legen wir im Projekt Klassen mit **gleichem Namespace, Klassennamen und Feldnamen** in der Standard-Assembly (`Assembly-CSharp`) an, bindet Unity die serialisierten Felder beim Laden der Prefabs automatisch (so wie bei den Stammdaten die `XLSXContent`-Klassen fehlten, siehe `docs/masterdata.md`).
Folgen: Layouts, Verdrahtung (`UINavigator`, Animatoren, Referenzen auf Sprites/Schriften) kommen 1:1 aus den Daten; nur die Logik wird geschrieben. Risiken: (a) Unity 6 vs. 2019.4 beim `UnityEngine.UI`-Skriptabgleich (`UnityEngine.UI.dll` vs. Paket `com.unity.ugui` 2.0.0, TMP darin), (b) Zwang zur Assembly-CSharp widerspricht der Aufteilung in `Xnu.*`-Assemblies (UI-Skripte liegen dann außerhalb), (c) `TMP_FontAsset`-Verweise auf eingebettete TTFs, (d) die Zuweisung der Original-Shader (Materialien müssen auf unsere portierten Shader zeigen).
**Spike S1** (sobald ein Editor frei ist, ca. 2–3 Tage): `ui/uiresidentwindow` laden, `bag.prefab` instanziieren, `UIText`/`UINavigator`/`Cursor` als Skelett anlegen, Fehlermeldungen („missing script“, Feldabgleich) zählen; danach Entscheidung. Messungen: Ladezeit des 8,2-MB-Bundles, Speicher der Atlanten (DXT5 auf iOS), Verhalten der Sprachatlanten.
**Variante B (Rückfall): Neuaufbau in C#.** Eigene Prefabs/Layouts aus RectTransform-Daten generieren (ein Exporter liest Ankerpunkte, Größen, Sprites) und nur Sprites/Schriften aus dem Dump verwenden. Mehr Aufwand (Layout und Animationen müssen übertragen werden), aber unabhängig vom Skriptabgleich und passend zu `Xnu.*`. Ein Zwischenweg ist ein **Prefab-Konverter** im Build: Original-Prefab lesen (UnityPy) → JSON → Unity-Editor-Skript baut Prefab mit eigenen Komponenten.
Fenster, die Modelle zeigen (3.5), brauchen in beiden Varianten die Modell-Pipeline.

## 7. Aufwand je Screen und Reihenfolge
Aufwand in **Entwicklertagen** (ED) eines Entwicklers mit Dump und Projektkenntnis, inklusive Lesen der Originallogik (Pseudocode) und Tests, **ohne** Hardwaretests; Schätzung [A] aus Umfang (Abschnitt 4), nicht aus Messung. Untergrenze = Variante A funktioniert (S1 positiv), Obergrenze = Variante B.

| Nr. | Baustein / Screen | ED | Voraussetzung | Abnahme zuerst |
|---:|---|---:|---|---|
| 0 | Spike S1 (Prefab-Bindung) und Schrift-Setup (TMP aus Dump, UI-Shader-Platzhalter) | 3–5 | freier Editor | U1 |
| 1 | UI-Framework: `UIManager` (klein), `UIWindow`, `UIText`, Atlas-/Sprite-Laden, Canvas-Setup 1280×720, `UINavigator`/`Cursor`, Eingabe-Adapter, Übergänge | 25–40 | 0, `Xnu.Input`, `Xnu.Text` | U1–U3 |
| 2 | Nachrichtenfenster: `MsgWindow`, `WindowMessage`, Schild, Item-Erhalt, Ja/Nein/Kontextmenü, Keyguide, Dialog | 12–18 | 1; Grammatik für Deutsch (3–6 ED extra, Lokalisierung Abschnitt 6) | U3 |
| 3 | Titel (Video + Abspann) | 3–5 | Video-Pfad (`ap-cutscenes-video`), 1 | U1–U2 |
| 4 | Sprache/Spieler/Name (`SelectLanguage`, `SelectPlayer`, `SoftwareKeyboard`, Laden) | 5–8 | 1, 2 | U3 |
| 5 | Hauptmenü + Einstellungen | 8–12 | 1, 2 | U3 |
| 6 | Party und Pokémon-Status (mit Attackenverwaltung) | 20–30 | 1, 2, `PokePara`, Modellansicht (3.5) | U3 |
| 7 | Beutel (+ Item-Verwendung im Feld) | 8–12 | 1, 2, Item-Daten | U3 |
| 8 | Shop (Kaufen/Verkaufen) | 8–12 | 7, `ShopTable` | U3 |
| 9 | Kampf-UI (Befehle, Attacken, Ziele, Status, HP-Balken, Meldungen) | 15–25 | 1, 2, Kampfsystem + Kampfansicht | U3, später U4 |
| 10 | Box | 15–25 | 6, Speicherstand-Boxen | U3 |
| 11 | Pokédex (Liste, Info, Verbreitung, Vergleich) | 20–30 | 6, Modelle, Karte | U3 |
| 12 | Karte, Trainerkarte, Bericht/Speichern | 9–15 | 1, 2, Speicher | U3 |
| | **Summe Kernumfang (1–12)** | **150–230** | | |
| 13 | Poketch, Sticker, Wettbewerb, Beeren/Pofin | 60–100 | 1, 2 | nach Bedarf |
| 14 | Geschenke, Union, Online, Kampfsuche | – | Netzwerk | nicht im Umfang |
Anmerkungen: (a) Die Summen enthalten nicht das Pixelgleich-Ziel U4, das an den Shader-Port gebunden ist. (b) Die größten Unsicherheiten sind Spike S1 (Variante A/B), die Grammatik und die Modellansichten.
**Empfohlene Reihenfolge:** 0 → 1 → 2 (Nachrichtenfenster macht jede Feldszene mit Gesprächen erst sinnvoll) → 3/4 (Start) → 5 → 6/7 (Party, Beutel) → 9 (Kampf-UI, parallel zum Kampf) → 8 → 12 → 10 → 11 → 13.
**Paralleles Arbeiten** ist möglich: Eingabe-Adapter und Nachrichtenfenster (2) unabhängig von Party/Beutel; Kampf-UI an Kampf-Agent koppeln; Texte/Grammatik parallel zum Framework.

## 8. Offene Fragen und Risiken
1. **Variante A oder B** (Spike S1): entscheidet über den Aufwand. Beides setzt voraus, dass UI-Shader und TMP in Unity 6 mit den Original-Materialien funktionieren (Shader-Port).
2. **Schriftlizenz:** Die Schriften (Fontworks/Nintendo-Hausschrift) sind Fremdinhalt, nur aus dem eigenen Dump im persönlichen Build; ein offener Ersatz würde Textbreiten und Umbrüche verändern (1:1 gebrochen). Entscheidung des Nutzers nötig.
3. **Texturformate:** DXT5-Anteil auf iOS/iPadOS (Unity dekomprimiert beim Laden oder Build-Umkodierung), Speicherbedarf der Atlanten und der 1.845 Icon-Bundles (38 MiB) auf dem iPad ungemessen.
4. **`resources.assets` ohne TypeTree:** `UIManager`, `MsgWindow*`, `MessageManager`, `TextFontData`, `FontMaterialData`, Stiltabelle. Entweder per Feldlayout aus `dump.cs` lesen (Vorbild `ui_resources_scan.py`, `MsgWindowConfig` gelungen) oder in C# neu definieren.
5. **Eingabe-Zeiten** (Wiederholung, Beschleunigung, Langtipp) und die Zuordnung der Tastenmaske auf `GameInput`: noch zu lesen (Pseudocode `UIInputController`).
6. **Fenster-Kamera-Modus** (`UiCameraMode`) und **Fenster-Animation** (`WindowAnimId`): Bedeutung geschlossen, nicht belegt.
7. **Touch auf iPad:** Das Original nutzt Touch parallel zu Tasten (Box, Pokédex, Karte); iPad-Touch-Bedienung muss je Screen festgelegt werden; Overlay-Konflikt mit dem Touch-Overlay von `Xnu.Input` (Zeigereingabe in der UI).
8. **Sprachen/Atlanten:** Sprachatlanten (`_lang.*`) und Texte in Bildern je Sprache: Welche Sprachen kommen in die erste Version (Vorschlag Deutsch/Englisch)? Auswahlregel des Originals für `GetLanguageVariant` nicht gelesen.
9. **3D-Modelle in UI:** Pokédex, Party, Karte, Trainerkarte hängen an Modell-Pipeline und Shadern.
10. **DOTween** (75 Animationen, Paket nötig; Lizenz/Quelle klären, im Dump nur als Verweis) und Wwise-Verweise im UI (ignorieren).
11. **Missing Bundle:** `ui/prefab/teammix` fehlt im Katalog (Online); beim Laden aller 74 Fenster abfangen.
12. **Unity-Lauf der Tests** (`TextTests`, 35 Tests) steht aus; zusätzlicher Editor erst nach Freigabe.

## 9. Gebaut in diesem Schritt
- `unity/Assets/Scripts/Text` (`Xnu.Text`, rein C#): JSON-Leser für `MsbtData`, Dateimodell, Sprachtabellen, `MessageBank`, `MessageComposer` (Abschnitte mit Ereignissen), `TagWordBuffer`/`ITagFormatter` (Gerüst), `RichText`, `MessageTimingConfig` und `MessageTypewriter`.
- `unity/Assets/Tests/EditMode/TextTests.cs`: 35 Tests (`dotnet test` im Wegwerfprojekt `work/dotnet-text`: grün; Verweis `Xnu.Text` in `Xnu.Tests.EditMode.asmdef` ergänzt). Gegenprobe mit den echten Exporten [V]: 119 + 119 + 90 Dateien, 0 ungültige Verweise.
- Skripte (nur lesen): `scripts/ui_inventory.py` (`catalog`, `bundles`, `deep`, `windows`, `fonts`), `scripts/msg_stats.py`, `scripts/ui_dump_view.py`, `scripts/ui_find_script.py`, `scripts/ui_resources_scan.py`. Ausgaben unter `work/ui` (gitignored): `catalog_stats.json`, `bundle_types.json`, `deep.json`, `windows.json`, `fonts.json`, `msg_stats.json`, `resources_scan.json`, `dump_uimanager.txt`.

## 10. Belege (Reproduktion)
```
python3 scripts/ui_inventory.py catalog | bundles | deep | windows | fonts     # Katalog, Objekttypen, Skriptklassen/CanvasScaler, Prefab-Umfang, Schriften
python3 scripts/msg_stats.py german english                                      # Message-Statistik
python3 scripts/ui_resources_scan.py                                             # resources.assets, MsgWindowConfig
python3 scripts/ui_dump_view.py UIWindowID UIManager UIText --methods            # Klassen aus dump.cs
cd work/dotnet-text && dotnet test                                               # 35 Tests (Wegwerfprojekt)
```
