# UI-Spezifikation 2: Spike S1 (Original-UI-Prefabs ohne Skripte) und Meldungsfenster

Stand: 2026-10-19, Todo `ap-ui`, Scheibe 1. Nur Zahlen, Klassen-/Feldnamen und eigener Code; keine Spielinhalte, Texte oder Bilder im Repo.
Messungen: Unity 6000.3.26f1 (Haupteditor `unity/`, Built-in-RP, Metal), Apple M1 Pro, eigener Dump unter `work/` (gitignoriert).
Belegstufen wie in `docs/ui-spezifikation-1.md`: **[D]** gemessen, **[S]** aus `dump.cs`, **[A]** Annahme, **[T]** durch Tests belegt.

## 1. Ergebnis in Kürze
- **S1 ist positiv:** Die Original-UI-Prefabs laden in Unity 6 ohne die Spielskripte. uGUI-Komponenten (`Image`, `Slider`, Layout-Gruppen, `CanvasScaler` …) binden von selbst; nur die 240 Klassen aus `Assembly-CSharp` fehlen (Missing Script). Layout (RectTransform), Verdrahtung und Sprites sind vollständig da. [D]
- **Gleichnamige eigene Klassen binden** die gespeicherten Felder, aber **nur, wenn sie in `Assembly-CSharp` liegen**. Dieselbe Klasse in einer eigenen Assembly (asmdef) bindet nicht (0 von 1.103). [D]
- **Entscheidung:** Variante A (Original-Prefabs laden, eigene `Dpr.UI.*`-Klassen in einem Ordner ohne asmdef) für die Fenster mit Prefab; Variante B (Export per UnityPy und Neuaufbau) bleibt Rückfall. Das Meldungsfenster hat im Original gar kein Prefab in den Bundles (liegt in `resources.assets` ohne TypeTree) und wird deshalb in jedem Fall **in eigenem C#** gebaut (Abschnitt 4).
- Original-Shader werden nie geladen: alle 263 `Image`- und 1.052 TMP-Materialien tragen im Spike `Hidden/InternalErrorShader`, nichts davon wurde gezeichnet. [D]
- Geliefert: `Xnu.UI` mit `TextboxView`/`TextboxFlow`, Szene `UiTest.unity`, 34 neue EditMode-Tests (Gesamt 481 grün, davon 447 bestehende).

## 2. Spike S1: Messungen [D]
Aufbau: `BundleProvider` mit Filter (kein Shader-Bundle, je Sprachfamilie genau eine Variante), `ui/uiresidentwindow` (8,2 MB, 53 Prefabs) samt 19 Abhängigkeiten, Auswertung per Eval-Skript (`scripts/ui_s1_probe.cs`); Offline-Zählung der Skriptbindung mit `scripts/ui_s1_scan.py` (UnityPy).

### 2.1 Skriptbindung
| Messgröße | Wert |
|---|---|
| Objekte im Bundle / MonoBehaviours / Skriptklassen | 35.988 / 8.619 / 255 |
| Assemblies der Skripte | `UnityEngine.UI.dll` 5.906 (14 Klassen), `Assembly-CSharp.dll` 2.710 (240 Klassen), `Unity.TextMeshPro.dll` 3 (1 Klasse) |
| Klassen in `Assembly-CSharp` | 230 in `Dpr.UI`, übrige: `DG.Tweening.DOTweenAnimation` (49 Instanzen, 55 Felder), `SmartPoint.Rendering.{Fxaa,Bloom,PostProcessFilter}`, Klassen ohne Namespace (`KeyguideItem`, `XMenuTopItem`, `RaycastTarget`, `EnvironmentSettings`, `EnvironmentController`, `CameraSortTragroups`) |
| Komponenten in allen 53 Prefabs (Assets geladen) | 25.293, davon **2.650 Missing Script** (alle aus `Assembly-CSharp`; die Differenz zu 2.710 sind vor allem `UIWindowStateMachine`, das in Animator-Controllern liegt [A]) |
| `UnityEngine.UI.*` und TMP | binden ohne Zutun; `CanvasScaler` im instanziierten Prefab = Skalierung nach Bildschirmgröße, 1280×720, Match 0 (Breite) |
| Prefab laden | `bag.prefab` 409 GameObjects in 98 ms (erstes Prefab), `dialog` 8 GO 2 ms, `xmenu` 131 GO 15 ms; Instanziieren 2–11 ms; Bundle samt 20 Bundles öffnen 31 ms; Managed-Heap +17,8 MB; **0 Konsolenfehler** (kein Missing-Script-Spam) |

### 2.2 Wiederverwendung durch eigene Klassen (Bindungstest) [D]
Vier Stub-Klassen mit denselben Namespace-, Klassen- und `[SerializeField]`-Feldnamen (`Dpr.UI.UINavigator`, `Cursor`, `HpBar`, `UIText : TextMeshProUGUI`) in einem Ordner **ohne** asmdef (= `Assembly-CSharp`):

| Klasse | Instanzen | Ergebnis |
|---|---:|---|
| `UINavigator` | 184 | gebunden; `_left` bei 182 aufgelöst, `_isStop*`-Flags korrekt (28 mit `_isStopRight`) |
| `Cursor` | 44 | gebunden; Bild- und Sprite-Arrays vorhanden, 90 von 90 Sprite-Verweisen aufgelöst (externe Bundles) |
| `HpBar` | 30 | gebunden; `Slider` 30/30, 90 Sprites |
| `UIText` (TMP-Unterklasse, 78 Felder im Original) | 1.103 | gebunden; Schrift bei 1.052 aufgelöst, 1.032 mit `_useMessage`, 1.083 mit `_sizeId ≠ 0` |
Missing Script danach: 2.650 → 2.392 (Cursor, Navigator, HpBar) → 1.289 (mit `UIText`). Die gleichen Klassen in der asmdef `Xnu.S1Spike`: **0 gebunden**, 2.650 fehlend. Bindung läuft also über (Assembly `Assembly-CSharp`, Namespace, Klassenname); Unity gleicht die Felder per TypeTree des Bundles nach Namen ab, unbekannte Felder werden verworfen, fehlende bleiben Standardwert. Ein falsch geschriebener Feldname geht **still** verloren (Prüfwerkzeug nötig, 5.).

### 2.3 Sprites, Schriften, Materialien
- `Image` 5.171 (Python zählt 5.181, die 10 fehlenden liegen auf nicht ladbaren Objekten [A]); Sprite aufgelöst bei **4.368** (Python: 4.378 mit Sprite). Ohne Sprachvarianten nur 4.226: Die Sprachatlanten (`common_lang`, `sharedui_lang`, `battle_lang`) müssen vor dem Prefab geladen sein.
- Sprachvarianten (`.en .fr .ge .it .jp .ko .si .sp .tr`) enthalten **dieselben Dateinamen**: Lädt man zwei Varianten, liefert `AssetBundle.LoadFromFile` `null` („same files already loaded“). Der Katalog nennt als Abhängigkeit zufällig `.jp`/`.si`. Die Verweise in den Prefabs lösen aber auch gegen eine andere Variante auf (`.ge` statt `.jp`: ebenfalls 4.368). **Sprachwechsel = andere Variante laden, Prefabs bleiben gleich.** Der `DependencyFilter` muss deshalb je Sprachfamilie genau eine Variante zulassen.
- Materialien: 263 `Image`-Materialien (nur solche mit eigenem Material) und 1.052 TMP-Schriftmaterialien tragen `Hidden/InternalErrorShader`; Lesen von Name und Shadername ist gefahrlos, solange das Shader-Bundle fehlt. Der Rückbau folgt `docs/material-remap.md` (Material kopieren, `shader` auf unseren Shader setzen, Eigenschaften bleiben nach Namen erhalten); für TMP: das Standard-Shader-Paar von TextMeshPro.
- Texturformate (ASTC/DXT5, Speicher auf iPadOS) sind weiter ungemessen.

### 2.4 Verlust gegenüber dem Original
Aus den Daten **erhalten**: Hierarchie, RectTransform (Anker, Größen), Sprites inklusive 9-Slice-Rändern, Farben, `CanvasScaler`, Layout-Gruppen, Animator-Verweise, Verdrahtung zwischen Skripten (nach Bindung). **Verloren** ohne eigene Klassen: das gesamte Verhalten (Navigation, Fenstersteuerung, `DOTweenAnimation`-Kurven), Skript-Referenzen der 2.650 Komponenten; Original-Materialien/Shader (Ersatz nötig); Animator-Zustandsverhalten (`UIWindowStateMachine`).

## 3. Entscheidung und Begründung
| Kriterium | A: Prefabs laden + `Dpr.UI.*` nachbauen | B: Export (UnityPy) + Neuaufbau |
|---|---|---|
| Layout, Sprites, Verdrahtung | 1:1 aus den Daten, geprüft | muss exportiert und nachgebaut werden (Anker, Layout-Gruppen, Maskierung, Animatoren) |
| Aufwand je Screen | nur Logik (Felder deklarieren, Verhalten schreiben) | zusätzlich Exporter, Builder, Animationen |
| Treue (U1/U2) | Struktur und Layout ab dem ersten Tag deckungsgleich | Abweichungen wahrscheinlich, Prüfung je Screen |
| Technische Kosten | Klassen in `Assembly-CSharp`; Feldnamen müssen stimmen; IL2CPP-Stripping [A] | keine Bindung nötig, passt zu `Xnu.*` |
| Rechtslage | Repo enthält nur eigene Klassen gleichen Namens, Daten bleiben lokal | wie A (Export liegt unter `work/`) |
**Wahl: A**, weil die Messung zeigt, dass die kritischen Teile (Bindung, Sprites, Schriften, Sprachvarianten) funktionieren und B denselben Datenweg plus Mehrarbeit bräuchte. B wird nicht gebaut; Rückfall nur für einzelne Prefabs, deren Feldlayout sich nicht binden lässt. Die Schätzung in `docs/ui-spezifikation-1.md` (150–230 ED) bleibt; es gilt die **Untergrenze**, solange die Punkte in 5. beherrscht sind.
Bindung und `Xnu.*`-Assemblies: Der Ordner für die `Dpr.UI.*`-Klassen (z. B. `Assets/Scripts/DprUi/`, ohne asmdef) kann alle `autoReferenced`-Assemblies (`Xnu.Core`, `Xnu.Text`, `Xnu.UI` …) verwenden; die Gegenrichtung geht nicht. Spiellogik gehört daher in `Xnu.*`, die `Dpr.UI.*`-Klassen bleiben dünne Hüllen mit den serialisierten Feldern.

## 4. Meldungsfenster (`Xnu.UI`)
Dateien (`unity/Assets/Scripts/UI`, Assembly `Xnu.UI`, Editor-Teil `Xnu.UI.Editor`):
| Datei | Inhalt |
|---|---|
| `Logic/TextboxFlow.cs` | Ablauf ohne Unity-Typen: Öffnen → Schreibmaschine je Abschnitt → Ereignisse → Tastenwarten → Schließen; Zustand `Held` für Fragen |
| `Logic/ChoiceMenuModel.cs` | Auswahl (Ja/Nein): Cursor mit Umlauf, Bestätigen wählt, Abbrechen wählt den Abbruch-Eintrag |
| `Logic/UiInput.cs`, `PlainMessage.cs` | `UiInputState` (Bestätigen/Abbrechen/Halten/Rauf-Runter), `ManualUiInput`, `MergedUiInput`; einfache Zeichenkette → `ComposedMessage` |
| `Runtime/TextboxView.cs` | baut Canvas, Rahmen, TMP-Text mit Maske, Weiter-Symbol und Auswahlfeld selbst; `Show`, `Ask`, `Tick` |
| `Runtime/UiCanvasFactory.cs` | Canvas wie im Original: Skalierung nach Bildschirmgröße, Referenz 1280×720, Breitenabgleich (Match 0); mit Kamera = Screen Space Camera (folgt dem 16:9-Ausschnitt des `DisplayController`) |
| `Runtime/TextboxSkin.cs` | Rahmen/Weiter-Symbol: aus dem lokalen Dump (`sharedui`, nur zur Laufzeit, Sprites `cmn_wd_message_01_NN_l`, `cmn_ico_messagenext_01`), sonst Platzhalter aus eigenen Pixeln |
| `Runtime/GameInputUiSource.cs` | `Xnu.Input` → `UiInputState`: A bestätigt, B bricht ab, D-Pad/Stick wählen |
| `Runtime/UiTestDriver.cs`, `Editor/UiSceneBuilder.cs` | Szene `unity/Assets/Scenes/UiTest.unity` (Menü `Xnu/UI/Create UiTest Scene`): Kamera, `DisplayController` (16:9), `GameInput`, `TextboxView`, Treiber mit erfundenen Texten |

**Verhalten** (Zahlen aus `MsgWindowConfig`, `docs/lokalisierung.md` Abschnitt 9; Rest [A]):
- Schreibmaschine 0,06 / 0,03 / 0,01 s je Zeichen (Langsam/Normal/Schnell), Rich-Text bleibt erhalten (Markup zählt nicht als Zeichen), Taste halten = Faktor 5, ein einzelner Druck überspringt nichts.
- Ereignisse: `NewLine` fortlaufend; `Wait` Wartezeit in Sekunden; `ScrollLine` Tastenwarten, dann Zeile 0,15 s nach oben scrollen (Text bleibt, Maske schneidet); `ScrollPage` Tastenwarten, Seite leeren; `CallBack` Rückruf mit Nummer; `End` Tastenwarten, schließen.
- Nach dem Textende werden 4 Bilder lang Eingaben ignoriert (`waitAfterFinishMsgFrame`); Bestätigen **und** Abbrechen schalten weiter.
- Weiter-Symbol: Hub 8 px, 210 °/s (`iconMoveDist`, `addAngleSec`).
- Fenster: 144 px hoch (Spritehöhe), 40 px Rand links/rechts, 24 px über dem unteren Rand, Textrand 100 px, Schrift 36 [A]; Öffnen/Schließen je 0,1 s [A]; Frage: Nachricht, Fenster bleibt offen, Auswahl rechts darüber, nach der Wahl schließt das Fenster; B wählt „Nein“ (letzter Eintrag) [A].
- Rahmen: 24 Stile `cmn_wd_message_01_01…24_l` (124×144, 9-Slice-Ränder z. B. 60/30/60/30, ppu 100); `Sprite.texture` ist `null`, aber `SpriteAtlas.GetSprite` liefert Sprites, die sich normal als `Image` (Sliced) zeichnen. Das Bundle-Handle wird nach dem Holen mit `Unload(false)` freigegeben. Gezeichnet wird mit dem Standard-UI-Material von Unity, kein Original-Shader.
- Schrift: TextMeshPro mit der von Unity mitgelieferten LiberationSans (Platzhalter). Dafür wurden die „TMP Essential Resources“ importiert (`Assets/TextMesh Pro`, Shader, Schrift mit OFL-Text, Settings; Shadergraph-Dateien und Emoji-Sprites entfernt, rund 3 MB). Die Original-Schrift (`efigs_font`, Material-Umbau auf das TMP-Shader-Paar) ist **nicht** angebunden.

**Tests** [T]: `Assets/Tests/EditMode/UiTextboxTests.cs`, 34 Tests mit erfundenen Texten: Schreibmaschinen-Zeiten für alle drei Stufen, Halten/Einzeldruck, Rich-Text, Tastenwarten mit Schonfrist, Abbrechen, Zeilenumbruch, Wartezeit, Rückruf, Seite/Zeile scrollen, Öffnen/Schließen-Fortschritt, `Held`, Auswahlmenü (Umlauf, Abbruch, ungültige Argumente), Eingabequellen, Canvas-Werte (1280×720, Match 0), Platzhalter-Skin, Ansicht (Text, Schließen, Ask, Label über `MessageComposer`). Lauf im Haupteditor: **481 von 481 grün** (447 bestehende + 34 neue).

**Beobachtung im Game View** (Aufnahmen `work/ui/shots/ui_a.png … ui_e.png`, nicht im Repo; Spielfenster 1814×934, Aufnahme auf 1280×720 skaliert, daher leicht gestaucht, Seitenbalken von `DisplayController`): Der Original-Rahmen wird mit seinen 9-Slice-Rändern korrekt gezeichnet (grauer Rand, helle Fläche, seitliche Zierleisten). Text erscheint zeichenweise; Rich-Text (`<color>`, `<size>`) wird richtig dargestellt; Zeilenscrollen zeigt die zweite und dritte Zeile; das Weiter-Symbol erscheint nur im Tastenwarten (kleines Dreieck mit diagonalem Strich: vermutlich Teil des Original-Sprites, Ursache nicht geprüft [A]); die Auswahl „Ja/Nein“ erscheint rechts über dem Fenster, der Cursor `>` folgt der Eingabe, „Nein“ wurde über Bestätigen gewählt und das Fenster schloss. Laufzeitwarnung: `SpriteAtlasManager.atlasRequested wasn't listened to while SharedUI requested` (harmlos, Atlas ist geladen; beim Anbinden von `UIManager`-Atlaslogik zu behandeln). Die Fensterposition/-breite stammt nicht aus Originaldaten; ein Bildvergleich (U2/U4) steht aus.

## 5. Lücken und nächste Schritte
1. **Feldabgleich-Prüfung**: Werkzeug, das die Feldnamen je Klasse aus den Bundles (`ui_s1_scan.py` zählt bisher nur) gegen die `[SerializeField]`-Felder der eigenen Klassen vergleicht; Tippfehler sind sonst unsichtbar.
2. **IL2CPP-Stripping** [A]: Klassen, die nur über Bundles gebunden werden, brauchen `link.xml`/`[Preserve]`; Player-Test mit gebautem macOS/iPad steht aus (Spike lief nur im Editor).
3. **DOTween** (49 `DOTweenAnimation` im Hauptbundle): Paket oder eigener Ersatz mit gleichem Namespace/Feldlayout; Lizenz/Quelle offen.
4. **Material-Umbau** der 263 + 1.052 Materialien im Prefab-Ladepfad (Kopie + `shader` setzen) und der Original-TMP-Schriften; Sprachvarianten im `DependencyFilter` und `SpriteAtlasManager`-Anbindung.
5. **Textbox**: Rahmenstil aus `MsgWindowData` (25 Rahmen; hier fest Stil 1), Sprechername, Schilder, Item-Erhalt, Kampf-Einzeiler, Originalmaße (`resources.assets`), Original-Schrift mit Zeilenbreiten (`strWidth`), Touch/Zeigereingabe, Tastenwiederholung der Cursorbewegung, Grammatik (`docs/lokalisierung.md` Abschnitt 6), Bildvergleich.
6. Texturspeicher (DXT5 auf iOS/iPadOS) und Ladezeiten auf dem Gerät ungemessen.

## 6. Reproduktion
```
python3 scripts/ui_s1_scan.py ui/uiresidentwindow --json work/ui/s1_scan.json        # Skriptbindung offline
unity command --project-path unity --result-only eval_file $PWD/scripts/ui_s1_probe.cs  # Laden, Missing Script, Sprites (Haupteditor)
unity command --project-path unity --result-only run_tests editor Xnu.Tests.EditMode assembly
# Szene: Menü Xnu/UI/Create UiTest Scene, Play; A/L/Enter bestätigt, B/K bricht ab
```
