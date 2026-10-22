# Inventar des Spielcodes (IL2CPP-Dump)

Eigene Auswertung von `work/il2cpp/dump.cs` (Typen, Basisklassen, Namespaces) und `work/il2cpp/script.json` (Methodeneinträge).
Erzeugt mit `scripts/dump_stats.py` (nur Standardbibliothek, streamend, ca. 2 s, unter 50 MB RAM).
Es stehen nur Zahlen und Namen hier, kein Code aus dem Dump und aus `opendpr`.

## Lesehilfe und Grenzen

- **Typen** = Klassen, Strukturen, Enums, Interfaces laut Dump, inklusive verschachtelter Typen. Insgesamt 11.812.
- **Compiler-Hilfstypen** (Lambda-Container, Iterator-Zustandsmaschinen, `<>c`) sind mitgezählt und in einer eigenen Spalte ausgewiesen.
- **Methoden** = Einträge in `ScriptMethod`, der Klasse über das Präfix vor `$$` zugeordnet (Generics-Argumente entfernt). 107.604 Einträge, 99,9 % einem Dump-Typ zugeordnet.
- Verschachtelte Typen stehen im Dump ohne Namespace; sie wurden dem Namespace des äußeren Typs zugeschlagen.
- Methodenzahlen **generischer** BCL-Klassen (`List`, `Array`, `Dictionary`, Enumeratoren) sind durch Instanziierungen stark aufgebläht, weil jede Instanz eigene Einträge hat. Sie sagen nichts über Umfang von Spielcode.
- Die Modulzuordnung läuft über Namespace-Präfixe und Namensmuster. Namespace-lose Typen (große Gruppe im Spielassembly) sind nur grob einsortiert (Wwise und Pia/Ilca nach Namen, Rest = Spiellogik).
- Abgeleitet-von-Prüfungen laufen über Kurznamen. Namenskollisionen sind möglich, die Größenordnung stimmt.

## 1. Assembly-Gruppen

| Gruppe | Klassen | Strukturen | Enums | Interfaces | Typen | davon Compiler-Hilfstypen | Methoden |
|---|---:|---:|---:|---:|---:|---:|---:|
| Assembly-CSharp (Spielcode) | 6.359 | 573 | 1.193 | 32 | 8.157 | 1.947 | 49.832 |
| .NET-BCL / Mono | 1.078 | 183 | 181 | 107 | 1.549 | 93 | 42.404 |
| UnityEngine (Module) | 568 | 285 | 168 | 31 | 1.052 | 41 | 6.692 |
| nn (Nintendo-Switch-SDK) | 81 | 126 | 53 | 0 | 260 | 28 | 1.468 |
| DOTween (inkl. DOTweenPro) | 152 | 17 | 30 | 5 | 204 | 92 | 1.840 |
| Unity UI (uGUI) | 115 | 8 | 39 | 34 | 196 | 16 | 1.818 |
| TextMeshPro | 97 | 41 | 32 | 3 | 173 | 24 | 1.802 |
| Unity Timeline | 81 | 7 | 19 | 10 | 117 | 14 | 802 |
| AssetAssistant (SmartPoint) | 86 | 7 | 6 | 3 | 102 | 25 | 806 |
| DebugLog | 2 | 0 | 0 | 0 | 2 | 1 | 38 |
| **Summe** | **8.619** | **1.247** | **1.721** | **225** | **11.812** | **2.281** | **107.502** |

Das Spielassembly ist mit 8.157 von 11.812 Typen (69 %) die mit Abstand größte Einheit. Es enthält aber auch die Wwise-Bindung, die NEX-/Pia-Netzwerkplugins und generierte Tabellen.

## 2. Namespaces (Top 40 von 231, nach Typenzahl)

| Namespace | Klassen | Strukturen | Enums | Interfaces | Typen | Methoden |
|---|---:|---:|---:|---:|---:|---:|
| (global) | 984 | 183 | 230 | 1 | 1.398 | 10.613 |
| Dpr.Battle.Logic | 1.060 | 46 | 205 | 0 | 1.311 | 7.337 |
| Dpr.UI | 1.098 | 10 | 123 | 1 | 1.232 | 7.723 |
| Dpr.SequenceEditor | 520 | 1 | 107 | 1 | 629 | 736 |
| XLSXContent | 414 | 0 | 3 | 0 | 417 | 541 |
| UnityEngine | 235 | 64 | 69 | 9 | 377 | 3.304 |
| System | 199 | 60 | 56 | 16 | 331 | 17.035 |
| Dpr.Battle.View.Systems | 190 | 10 | 31 | 0 | 231 | 1.639 |
| Dpr.Contest | 181 | 14 | 32 | 2 | 229 | 1.646 |
| DG.Tweening | 178 | 1 | 18 | 1 | 198 | 1.258 |
| NexPlugin | 100 | 58 | 33 | 1 | 192 | 1.325 |
| Dpr.NetworkUtils | 104 | 62 | 13 | 1 | 180 | 1.723 |
| DPData | 6 | 122 | 48 | 0 | 176 | 69 |
| TMPro | 93 | 36 | 31 | 3 | 163 | 1.798 |
| Dpr.Field.Walking | 146 | 0 | 5 | 1 | 152 | 855 |
| UnityEngine.UIElements | 91 | 16 | 17 | 14 | 138 | 1.361 |
| NexAssets | 109 | 1 | 26 | 0 | 136 | 421 |
| UnityEngine.UI | 83 | 4 | 32 | 15 | 134 | 1.354 |
| Dpr.SecretBase | 118 | 1 | 13 | 0 | 132 | 794 |
| Dpr.Battle.View | 97 | 8 | 21 | 1 | 127 | 657 |
| UnityEngine.PlayerLoop | 0 | 124 | 0 | 0 | 124 | 0 |
| Dpr.Message | 78 | 1 | 42 | 0 | 121 | 692 |
| UnityEngine.Timeline | 80 | 7 | 19 | 10 | 116 | 802 |
| nn.hid | 35 | 60 | 19 | 0 | 114 | 617 |
| Dpr.Demo | 98 | 0 | 5 | 0 | 103 | 602 |
| Dpr.DigFossil | 73 | 0 | 9 | 16 | 98 | 538 |
| INL1 | 66 | 0 | 28 | 0 | 94 | 730 |
| System.Reflection | 67 | 6 | 17 | 1 | 91 | 517 |
| AK | 88 | 0 | 0 | 0 | 88 | 88 |
| Dpr.EvScript | 68 | 4 | 15 | 0 | 87 | 1.781 |
| Dpr.SubContents | 74 | 4 | 6 | 2 | 86 | 528 |
| Dpr.FureaiHiroba | 77 | 0 | 5 | 0 | 82 | 521 |
| Dpr.GMS | 64 | 0 | 17 | 0 | 81 | 738 |
| SmartPoint.AssetAssistant | 67 | 5 | 4 | 3 | 79 | 632 |
| System.Threading | 60 | 10 | 6 | 2 | 78 | 482 |
| Pml.PokePara | 23 | 28 | 21 | 0 | 72 | 793 |
| System.Collections.Generic | 46 | 12 | 3 | 10 | 71 | 17.062 |
| Dpr.UnderGround | 64 | 5 | 2 | 0 | 71 | 391 |
| System.IO | 55 | 1 | 9 | 0 | 65 | 582 |
| SmartPoint.Components | 48 | 3 | 9 | 0 | 60 | 392 |
| (191 weitere Namespaces) | 1.382 | 280 | 372 | 114 | 2.148 | 16.825 |

## 3. Größte 30 Klassen nach Methodenzahl

Nur Spielassembly (die Gesamtliste wird von generischen BCL-Typen angeführt: `List` 7.116, `Array` 5.304, `Dictionary` 2.113 und deren Enumeratoren; erste Spielklasse ist dort Rang 6).

| # | Klasse | Modul | Methoden |
|---:|---|---|---:|
| 1 | Dpr.EvScript.EvDataManager | Dpr.* (sonstige) | 1.582 |
| 2 | Dpr.NetworkUtils.ANetData | Online | 1.260 |
| 3 | AkSoundEnginePINVOKE | Wwise | 1.073 |
| 4 | Dpr.Battle.Logic.Handler.Waza | Dpr.Battle.Logic | 744 |
| 5 | Dpr.Battle.Logic.Handler.Tokusei | Dpr.Battle.Logic | 670 |
| 6 | Dpr.Battle.Logic.Handler.Item | Dpr.Battle.Logic | 532 |
| 7 | Dpr.Battle.View.Systems.BattleSequenceSystem | Dpr.Battle.View | 517 |
| 8 | Dpr.Battle.Logic.BTL_CLIENT | Dpr.Battle.Logic | 440 |
| 9 | Dpr.Battle.Logic.ServerCommandPutter | Dpr.Battle.Logic | 405 |
| 10 | AkSoundEngine | Wwise | 372 |
| 11 | PlayerWork | global | 314 |
| 12 | Pml.PokePara.CoreParam | Pml.PokePara | 308 |
| 13 | Dpr.Battle.Logic.MainModule | Dpr.Battle.Logic | 306 |
| 14 | Dpr.Battle.View.Systems.BattleViewSystem | Dpr.Battle.View | 296 |
| 15 | Dpr.Battle.Logic.BattleViewBase | Dpr.Battle.Logic | 292 |
| 16 | Dpr.UI.UIManager | Dpr.UI | 275 |
| 17 | Dpr.Battle.Logic.BtlAiExpert | Dpr.Battle.Logic | 258 |
| 18 | Dpr.Battle.Logic.BTL_POKEPARAM | Dpr.Battle.Logic | 255 |
| 19 | Pml.PokePara.Accessor | Pml.PokePara | 250 |
| 20 | Dpr.Battle.Logic.SectionContainer | Dpr.Battle.Logic | 242 |
| 21 | FieldPlayerEntity | global | 236 |
| 22 | Dpr.UI.BoxWindow | Dpr.UI | 210 |
| 23 | Dpr.Battle.Logic.Common | Dpr.Battle.Logic | 188 |
| 24 | Dpr.Battle.Logic.EventLauncher | Dpr.Battle.Logic | 176 |
| 25 | FieldObjectMoveCode | global | 171 |
| 26 | Dpr.Battle.Logic.BtlAiBasic | Dpr.Battle.Logic | 170 |
| 27 | Dpr.Battle.View.Systems.BattleViewUISystem | Dpr.Battle.View | 154 |
| 28 | INL1.IlcaNetSession | NEX/INL1 | 151 |
| 29 | FieldManager | global | 145 |
| 30 | Dpr.Battle.Logic.BattleAiCommand | Dpr.Battle.Logic | 145 |

Auffällig: Der Kampfkern (`Dpr.Battle.Logic`, Handler für Attacken, Fähigkeiten, Items, KI) stellt 14 der 30 größten Klassen, mit `Dpr.Battle.View` zusammen 17.

## 4. Modulkarte und Einordnung

Kategorie: **Spiellogik** = muss rekonstruiert werden; **Daten** = generierte Tabellen/Datenmodelle (meist aus Daten ableitbar); **Netzwerk** = Online-Funktionen (für ein Offline-Ziel stubbar); **Framework** = Studio-eigene Hilfsschicht (Engine-nah); **Middleware/Engine** = ersetzbar.

| Modul | Kategorie | Typen | davon Klassen | Methoden |
|---|---|---:|---:|---:|
| .NET-BCL / Mono | Engine (BCL) | 1.549 | 1.078 | 42.404 |
| Dpr.Battle.Logic | Spiellogik | 1.365 | 1.087 | 9.578 |
| Dpr.UI.* | Spiellogik (UI) | 1.232 | 1.098 | 7.723 |
| UnityEngine.* | Engine | 1.052 | 568 | 6.692 |
| Spiel-Typen ohne Namespace (global) | Spiellogik | 935 | 655 | 6.613 |
| Dpr.* (sonstige Spielmodule, u. a. EvScript, Demo, DigFossil, FureaiHiroba, SubContents) | Spiellogik | 587 | 473 | 4.931 |
| Wwise (AK.*, Ak*) | Middleware | 344 | 306 | 3.397 |
| Dpr.Battle.View (inkl. .Systems, .UI) | Spiellogik | 451 | 349 | 2.997 |
| Dpr.NetworkUtils / GMS / NetworkDbg / Security / NX | Netzwerk | 271 | 176 | 2.498 |
| NEX / INL1 / NexAssets | Middleware (Nintendo-Netzwerk) | 422 | 275 | 2.476 |
| DOTween (DG.Tweening) | Middleware | 290 | 236 | 2.178 |
| Unity UI (uGUI) | Engine | 196 | 115 | 1.818 |
| TextMeshPro | Middleware | 173 | 97 | 1.802 |
| Nintendo.MessageStudio / nn | Middleware (Switch-SDK) | 287 | 96 | 1.669 |
| Dpr.Contest | Spiellogik | 232 | 183 | 1.655 |
| SmartPoint.* (inkl. AssetAssistant) | Framework | 169 | 141 | 1.262 |
| Dpr.Message / MsgWindow / MessageViewer | Spiellogik (Text/UI) | 157 | 108 | 1.057 |
| Dpr.Field.* | Spiellogik | 171 | 157 | 953 |
| Unity Timeline | Engine | 117 | 81 | 802 |
| Dpr.SecretBase | Spiellogik | 132 | 118 | 794 |
| Pml.PokePara | Spiellogik | 72 | 23 | 793 |
| Dpr.SequenceEditor | Spiellogik (Sequenzen) | 629 | 520 | 736 |
| Pia / Ilca (nach Namen vermutet) | Middleware (Nintendo-Netzwerk) | 106 | 64 | 676 |
| XLSXContent | Daten | 417 | 414 | 541 |
| Dpr.UnderGround | Spiellogik | 93 | 82 | 535 |
| Pml.* (Rest: Personal, WazaData, Item, Local, UgFather) | Spiellogik | 80 | 41 | 347 |
| Effect / Audio / Ug / Field* / GameData / AttributeData u. ä. | Spiellogik | 59 | 43 | 312 |
| DPData | Daten (Save-/Datenmodell) | 192 | 12 | 72 |
| Xoroshiro128Plus | Spiellogik (Zufall) | 2 | 2 | 52 |
| DebugLog | Debug | 2 | 2 | 38 |
| Hilfsklassen (Mesh-Glättung, Scroll-Stabilisierung, Queue) | Framework | 5 | 4 | 32 |
| poketool | Spiellogik | 12 | 6 | 32 |
| Dpr.BattleMatching | Netzwerk | 5 | 4 | 27 |
| Debug-Klassen ohne Namespace | Debug | 2 | 2 | 6 |
| Dpr.Battle (Rest) | Spiellogik | 4 | 3 | 4 |

### Hauptkategorien

| Kategorie | Typen | Anteil Typen | Methoden | Anteil Methoden |
|---|---:|---:|---:|---:|
| Spiellogik (inkl. UI, Sequenzen, Text) | 6.213 | 52,6 % | 39.112 | 36,4 % |
| Engine-BCL (.NET/Mono) | 1.549 | 13,1 % | 42.404 | 39,4 % |
| Middleware (Wwise, DOTween, TMP, NEX/Pia, MessageStudio, nn) | 1.622 | 13,7 % | 12.198 | 11,3 % |
| Engine (Unity, uGUI, Timeline) | 1.365 | 11,6 % | 9.312 | 8,7 % |
| Daten (XLSXContent, DPData) | 609 | 5,2 % | 613 | 0,6 % |
| Netzwerk (eigener Online-Code) | 276 | 2,3 % | 2.525 | 2,3 % |
| Framework (SmartPoint) | 174 | 1,5 % | 1.294 | 1,2 % |
| Debug | 4 | < 0,1 % | 44 | < 0,1 % |

### Einschätzung: Spiellogik gegen Engine/Middleware

- **Zu rekonstruieren:** rund 6.200 Spiel-Typen mit etwa 39.000 Methodeneinträgen. Rechnet man die BCL-Instanziierungen heraus (Methodenbasis ohne BCL: ca. 65.100), sind das etwa **60 %** aller Methoden; nach Typen sind es 53 % aller Dump-Typen bzw. 76 % des Spielassemblys (6.213 von 8.157; der Rest dort ist Wwise, NEX/Pia, Daten, Netzwerk).
- **Schwerpunkte:** Kampf (`Dpr.Battle.*`, 1.816 Typen, 12.575 Methoden), UI (`Dpr.UI`, 1.232 Typen, 7.723 Methoden), global benannte Feld-/Entity-Klassen (935 Typen, 6.613 Methoden), `Dpr.Contest`, Geheimbasis, Untergrund, Pml (Pokémon-Parameter, Attacken-/Personaldaten).
- **Sequenzen:** `Dpr.SequenceEditor` hat 629 Typen, aber nur 736 Methoden. Das sind überwiegend Befehls-/Datenklassen für Kampf- und Cutscene-Abläufe, also viel Inhalt, wenig Logik.
- **Ersetzbar:** Unity-Engine, uGUI, Timeline, .NET-BCL, DOTween, TextMeshPro, Wwise, Nintendo-SDK (`nn`, MessageStudio) und die NEX-/Pia-Plugins. Zusammen etwa 3.000 Typen (ohne BCL) bzw. rund 4.500 (mit BCL). Das sind 25 % der Dump-Typen (mit BCL 38 %) und 20 % der Methodeneinträge (mit BCL 59 %).
- **Weder noch:** `SmartPoint` (174 Typen) ist Asset-/Komponenten-Framework des Studios. Es muss funktional ersetzt werden (Asset-Laden, Provider für PlayerPrefs, Render-Prioritäten), ist aber kein Spielinhalt.
- **Daten:** `XLSXContent` (417 Typen) und `DPData` (192 Typen) sind generierte Tabellenschichten bzw. Datenmodelle; sie hängen am Dateiformat (Save-Format siehe `docs/save-format.md`) und sind eher Layout- als Logikarbeit.
- **Online:** 276 eigene Netzwerktypen plus 528 Middleware-Typen (NEX, Pia, Ilca) lassen sich für ein Offline-Ziel stubben.

## 5. Manager-, System-, Controller- und Provider-Klassen

Spielassembly, ohne Compiler-Typen: **159** Klassen (Manager 86, Controller 48, System 24, Provider 1; eine davon verschachtelt).
**22** davon haben ein Singleton-Merkmal (Basisklasse `Singleton`/`Provider<T>` oder statisches Instanzfeld). Das ist eine untere Schranke, weil andere Zugriffsmuster nicht erkannt werden.

| Modul | Typen | mit Singleton-Merkmal |
|---|---:|---:|
| Global (ohne Namespace) | 41 | 4 |
| Dpr.* (sonstige) | 26 | 4 |
| Dpr.UI | 16 | 1 |
| Dpr.Battle.View | 12 | 1 |
| Dpr.Battle.Logic | 9 | 0 |
| Dpr.SecretBase | 9 | 0 |
| Dpr.Field.* | 6 | 0 |
| Wwise | 6 | 0 |
| kleine Spielnamespaces (Effect, Audio …) | 5 | 2 |
| Pml.* (Rest) | 5 | 0 |
| Online (NetworkUtils/GMS) | 5 | 2 |
| Dpr.Contest | 5 | 1 |
| Dpr.UnderGround | 4 | 3 |
| Dpr.Message/MsgWindow | 3 | 3 |
| Pml.PokePara | 3 | 0 |
| SmartPoint | 2 | 1 |
| übrige (NEX, SequenceEditor) | 2 | 0 |

Auswahl der zentralen Namen (vollständige Liste: `scripts/dump_stats.py` ausführen):

- **Manager:** GameManager, FieldManager, UIManager, DataManager (GameData), EvDataManager, MessageManager, MsgWindowManager, NetworkManager, EffectManager, AudioManager, EntityManager, ItemManager, UgFieldManager, UgFatherManager, TrainerCardManager, PlayTimeManager, SessionManager, FureaiManager, SecretBaseMasterDataManager, BattleDataTableManager, BattleViewAssetManager, DemoSceneManager, UnionRoomManager, UnionTradeManager, EvolveManager, AkBankManager, AkCallbackManager.
- **System:** BattleAiSystem, EventSystem (Kampf), BattleViewSystem, BattleSequenceSystem, BattleCameraSystem, BattleCharacterSystem, BattleWeatherSystem, ContestViewSystem, SequenceSystem, SaveSystem (`Dpr.NX`), PersonalSystem, WazaDataSystem, TrainerSystem.
- **Controller:** GameController, ContestController, GMSController, SecretBaseController, DigFossilController, UIInputController, UIModelViewController, UIMsgWindowController, OpeningController, EnvironmentController, FieldAnimatorController, Union*Controller (Spieler-Treffpunkt).
- **Provider:** `PlayerPrefsProvider` (SmartPoint); `PlayerWork` erbt davon und ist der zentrale Spielstand-Singleton.

Die „System“-Klassen des Kampfs (`Dpr.Battle.View.Systems`) sind **kein ECS**: Sie haben kein Entities-Basistypen, sondern sind gewöhnliche Klassen (meist Objekt oder MonoBehaviour).

## 6. MonoBehaviour- und ScriptableObject-Ableitungen

| Basis | Typen (direkt/indirekt) | davon Spielassembly | Rest |
|---|---:|---:|---|
| MonoBehaviour | 773 | 708 | uGUI 42, TextMeshPro 12, AssetAssistant 6, DOTween 4, Timeline 1 |
| ScriptableObject | 251 | 213 | Timeline 18, UnityEngine 8, TextMeshPro 7, AssetAssistant 4, DOTween 1 |

MonoBehaviours im Spielassembly nach Modul: Dpr.UI 295, global 125, Dpr.* (sonstige) 60, Dpr.SecretBase 43, Dpr.Battle.View 41, Wwise 37, Dpr.Contest 25, SmartPoint 16, Online 14, Dpr.UnderGround 13, NEX/INL1 12, Dpr.Message 10.
Die Oberfläche ist also stark komponentenbasiert (UI-Fenster als Komponenten), der Kampfkern dagegen nicht (41 in `Dpr.Battle.View`, nur 1 in `Dpr.Battle.Logic`).

## 7. Klassen mit Save-Bezug

Auswahl nach Name (Save, PlayerWork, PlayerPrefs), Spielassembly ohne Enums: **42** Typen, zusammen 419 Methoden.

| Typ | Methoden |
|---|---:|
| PlayerWork (zentraler Spielstand, 4 verschachtelte Typen) | 314 |
| SmartPoint.Components.PlayerPrefsProvider | 29 |
| Dpr.NX.SaveSystem | 16 |
| DPData.PoffinSaveData | 11 |
| Dpr.SecretBase.SecretBaseSaveDataWork | 9 |
| Dpr.UI.AutoSaveWindow | 8 |
| Dpr.SaveDataLinkage | 5 |
| Pml.PokePara.SavePokeParty | 4 |
| DPData.UgSaveData, DPData.UnionSaveData | je 3 |
| Dpr.Box.SaveBoxTrayData, Dpr.Battle.Logic.DiarySave, XLSXContent.MoveAfterSaveGrid | je 2 |

Dazu kommen über 20 Typen mit 0 bis 1 Methoden, fast alle in `DPData` (Strukturen wie `PLAYER_SAVE_DATA`, `_FIELDOBJ_SAVE`, `DENDOU_SAVE_*`, `IMC_SAVEDATA_*`, `BTLTOWER_SAVEWORK`, `KinomiGrowSaveData`) sowie `Dpr.Item.SaveItem`, `Dpr.Box.SaveBoxData`, `Dpr.BallDeco.Save*`. Das ist die Struktur-Schicht aus `docs/save-spec-entwurf.md`; die Logik sitzt fast vollständig in `PlayerWork`.

## 8. Wwise / Ak

- **344 Typen** (306 Klassen, 38 Enums), **3.397 Methoden**: 245 ohne Namespace (`Ak*`), 88 in `AK`, 11 in `AK.Wwise`.
- Größte Klassen: AkSoundEnginePINVOKE (1.073, reine Native-Brücke), AkSoundEngine (372), AkBaseArray (75), AkMIDIEvent (44), AkPositioningInfo (42), AkInitSettings (35), AkPlaylistArray (34), AkRoomPortal (31), AkSpatialAudioInitSettings (28), AkDeviceSettings (27).
- Davon 37 MonoBehaviours (Unity-Integration). Das ist Middleware: komplett ersetzbar durch ein anderes Audiosystem; einzig die Bank-/Event-IDs der Spieldaten sind relevant.
- Spielseitige Audioanbindung (Namen mit Audio/Sound): 88 Klassen mit 342 Methoden (z. B. `AudioManager`, `AudioAmbientManager`, `SecretBaseAudioManager`, `DigAudioManager`). Das ist eigene Logik und bleibt zu rekonstruieren.

## 9. ECS / DOTS

Nicht vorhanden. Keine Entities-, Burst- oder Jobs-Assembly in der Image-Liste, keine Typen mit `IComponentData`, `ISystem`, `SystemBase` oder `IJob*`. Es gibt nur 26 Hilfstypen aus `Unity.Collections` (11 im Namespace, 14 `LowLevel.Unsafe`) und `Unity.Jobs` (1) in `UnityEngine.CoreModule`.
Namen wie `EntityManager`, `BattleJobSystem` oder `*Entity` sind eigene Klassen des Spiels, kein DOTS. Das Spiel läuft auf klassischem GameObject/MonoBehaviour plus eigenen Managern.

## 10. Quervergleich mit `tools/opendpr/Assets/Scripts`

Nur gezählt, nichts kopiert. Abgeglichen wird der Kurzname (ohne Generics) gegen die Typnamen, die in den `.cs`-Dateien von opendpr deklariert sind (5.150 Namen in 3.812 Dateien, ca. 310.600 Zeilen).

### Dateien pro Ordner

| Ordner | .cs-Dateien | Zeilen |
|---|---:|---:|
| Dpr | 2.477 | 176.710 |
| (Wurzel, namespace-lose Spieltypen) | 395 | 53.505 |
| nn | 196 | 7.045 |
| DPData | 188 | 3.133 |
| XLSXContent | 133 | 5.280 |
| Pml | 106 | 12.049 |
| SmartPoint | 97 | 8.552 |
| NexPlugin | 74 | 6.897 |
| INL1 | 41 | 2.991 |
| NexAssets | 32 | 2.489 |
| Nintendo | 25 | 1.007 |
| poketool | 11 | 296 |
| AK | 8 | 26.259 |
| Effect | 8 | 1.187 |
| DG | 4 | 693 |
| Audio | 3 | 803 |
| FieldDoor | 3 | 80 |
| Ug, Xoroshiro128Plus, AttributeData | je 2 | 19 / 535 / 259 |
| FieldWall, ScriptableObjectFormat, FieldCommon, GameData, Editor | je 1 | 8 / 43 / 287 / 352 / 99 |

### Abdeckung per Klassenname

Grundmenge: Typen aus Spielassembly und AssetAssistant ohne Compiler-Hilfstypen.

| Menge | Dump-Typen | in opendpr | Anteil |
|---|---:|---:|---:|
| Alle (inkl. verschachtelt) | 6.287 | 5.839 | 92,9 % |
| Top-Level-Typen | 3.826 | 3.560 | 93,0 % |
| – Klassen | 2.978 | 2.777 | 93,3 % |
| – Strukturen | 297 | 295 | 99,3 % |
| – Enums | 520 | 457 | 87,9 % |
| – Interfaces | 31 | 31 | 100 % |
| Top-Level mit passendem Namespace und Name | 3.826 | 3.174 | 83,0 % |

Methodeneinträge in Dump-Klassen mit Namenstreffer: 36.597 von 39.951 (91,6 %, nur Top-Level).
Ohne die beiden Middleware-Lücken (Wwise 213 Typen mit 9 Treffern, DOTween-Anteil im Spielassembly 11 mit 4 Treffern) liegt die Namensabdeckung bei etwa 98,5 % (3.547 von 3.602).
Nur 4 von 5.150 deklarierten Namen in opendpr tauchen im Dump nicht auf.

### Abdeckung je Modul (Top-Level)

| Modul | Dump-Typen | in opendpr | Anteil |
|---|---:|---:|---:|
| Dpr.SequenceEditor | 620 | 620 | 100 % |
| Dpr.Battle.Logic | 571 | 571 | 100 % |
| global (ohne Namespace) | 382 | 335 | 87,7 % |
| Dpr.UI | 329 | 329 | 100 % |
| Online (NetworkUtils/GMS …) | 214 | 214 | 100 % |
| Wwise | 213 | 9 | 4,2 % |
| DPData | 188 | 188 | 100 % |
| Dpr.* (sonstige) | 183 | 182 | 99,5 % |
| Dpr.Battle.View | 160 | 160 | 100 % |
| Dpr.Contest | 150 | 150 | 100 % |
| NEX / INL1 / NexAssets | 147 | 145 | 98,6 % |
| XLSXContent | 133 | 133 | 100 % |
| SmartPoint | 96 | 94 | 97,9 % |
| Dpr.Message / MsgWindow | 90 | 90 | 100 % |
| Dpr.Field.* | 70 | 69 | 98,6 % |
| Dpr.SecretBase | 62 | 62 | 100 % |
| Pml.* (Rest) | 56 | 56 | 100 % |
| Pml.PokePara | 50 | 50 | 100 % |
| DOTween (Teil im Spielassembly) | 11 | 4 | 36,4 % |

### Lesart

- Auf Namensebene ist opendpr dem Dump praktisch deckungsgleich. Die Lücken sind Wwise (liegt dort als eigenes Projekt `Dpr_WwiseProject` und in nur 8 Dateien im Ordner `AK`), DOTween-Teile und etwa 47 global benannte Spieltypen.
- **Das heißt nicht, dass die Logik fertig ist.** Ein Namenstreffer sagt nichts über Methodenrumpf, Korrektheit oder Vollständigkeit. Der Umfang in Zeilen (ca. 310.600 für ca. 43.400 Methodeneinträge der Spieltypen) spricht für ausgefüllte Rümpfe, geprüft wurde das hier nicht.
- Ob die Dateien „handgeschrieben“ sind, lässt sich aus Zahlen nicht ableiten; die README von opendpr nennt handgeschriebenen und skriptgenerierten Code. Wiederverwendung gehört in eine eigene Lizenz- und Qualitätsprüfung (siehe opendpr-Machbarkeitsbericht im Git-Verlauf).
- Für den Aufwand heißt das: Die Rekonstruktion ist nach Dump-Umfang groß (ca. 6.200 Typen), die verbleibende Arbeit steckt weniger in der Menge der Klassen als in Prüfung, Lauffähigkeit und dem Ersatz der Middleware.
