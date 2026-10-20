# Stubs 1: Original-Objektgraph laden (generierte Stub-Klassen für Assembly-CSharp)

> **Historisch (Stand 2026-10-20):** Unity-Weg, eingestellt. Auf `main` entfernt (nur Branch `unity`): `scripts/stub_gen.py`, `scripts/stub_dump.py`, `scripts/stub_verify.py`, `scripts/stub_probe.cs`, `scripts/stub_bridge/`, `scripts/tests/test_stub_gen.py`. Die Befehle unten laufen auf `main` nicht mehr.

Stand: 2026-10-19, Todo `ap-stubgen`. Nur Zahlen, Verfahren und eigener Code; keine Spielinhalte, Texte, Klassennamen oder Feldnamen aus dem Spiel im Repo.
Messungen: Unity 6000.3.26f1 (Apple Silicon, Batchmodus ohne Grafik), Apple M1 Pro; eigener Dump und Scans unter `work/` (gitignoriert).
Belegstufen: **[D]** gemessen, **[S]** aus `dump.cs`, **[A]** Annahme, **[T]** durch Tests belegt.

## 1. Ergebnis in Kürze
- **Entscheidung des Nutzers (heute):** Hauptweg = „Stubs + Original-Objektgraph + Logik-Pipeline“. Aus dem eigenen Dump entstehen **beim Build** Stub-Klassen für `Assembly-CSharp` (Namespace, Klassenname, Basisklasse, serialisierte Felder), damit Original-Prefabs/-Bundles mit intakter Verdrahtung laden. Die Logik folgt klassenweise in eigener Formulierung und wird per Orakel geprüft. Die Stubs sind generiert und **nicht im Repo** (gitignoriert); im Repo liegen nur der Generator und seine Tests.
- **Der Generator trägt:** `scripts/stub_gen.py` (+ `stub_dump.py`) erzeugt aus TypeTree und Dump **887 C#-Dateien und 4 asmdef** (1.310 Typen, 5.777 Felder) in einer Sekunde; Unity kompiliert sie in rund 2 s mit **0 Compilerfehlern** (Zwischenstand 2, siehe 4.1). [D]
- **Missing Script verschwindet:** über **13.889 Bundles** (alle bis 80 MB, 1.112.276 Komponenten) sinken fehlende Skripte von **34.101 auf 0**; `ui/uiresidentwindow` 2.650 → 0, `Environments/fields/area001` (Zone 422) 38 → 0. [D]
- **Feldbindung stimmt:** je Klasse ein Sample gegen den TypeTree: **574 Klassen** geprüft, 42.401 Felder-Blätter, **42.399 gleich (99,995 %)**; die 2 Abweichungen sind ein Feld aus der TextMeshPro-Basisklasse, das die Paketversion in Unity 6 nicht mehr hat. 0 Konsolenfehler durch die Stubs. [D]
- **Allein aus dem TypeTree** lassen sich 357 von 688 Klassen (85,8 % der Instanzen) exakt erzeugen, 642 (95,3 % der Instanzen) binden mit Abstrichen; nur 12 Klassen (2.045 Instanzen) brauchen den Dump zwingend (Basis ist eine UI-/TMP-Klasse). [D]
- **Brücke Xnu.* ↔ Stubs ist belastbar:** Assembly-CSharp darf autoReferenced-asmdef-Assemblies verwenden, nicht umgekehrt. Die Logik liegt in `Xnu.*` und kennt nur Schnittstellen; handgeschriebene `partial`-Teile der Stubs (ohne asmdef) implementieren sie. Getestet am Original-UI-Bundle (127 Komponenten, Anmeldung in `Awake`, Abmeldung in `OnDestroy`). [D]
- **Grenzen:** Szenen-Bundles lassen sich im Batchmodus nicht öffnen (Strukturprüfung nur per Scan), Shader/Materialien bleiben ungelöst, die Logik selbst fehlt (Abschnitt 6).

## 2. Analyse: was die Daten tatsächlich referenzieren [D]
Aufbau: `scripts/stub_gen.py scan` liest alle 14.057 Dateien (14.052 Bundles und 5 Player-Dateien) mit UnityPy in ca. 3 Minuten (5 Prozesse), je MonoBehaviour nur Skript-PPtr, TypeTree-Schema und Zähler (keine Instanzwerte). Skripte werden über `m_AssemblyName`/`m_Namespace`/`m_ClassName` des MonoScripts aufgelöst, auch über Bundle-Grenzen (CAB-Namen). Ergebnis in `work/stubs/scan.json`.

### 2.1 Skriptklassen insgesamt und tatsächlich referenzierte
- `globalgamemanagers.assets` enthält **2.761 MonoScripts** (Assembly-CSharp 2.229; Rest: Nintendo-SDK `nn` 104, uGUI 85 + 68 Tests, Timeline 70, TextMeshPro 59 + 1 Test, AssetAssistant 28, TestRunner 110, DOTweenPro 3, DOTween 2, Recorder 3, übrige 3).
- Davon haben Instanzen in Bundles/Player-Dateien: **727 Klassen, 54.064 Instanzen**.

| Assembly des Skripts | Klassen | Instanzen | davon an GameObjects |
|---|---:|---:|---:|
| `Assembly-CSharp` | 688 | 44.233 | 34.406 |
| `UnityEngine.UI` | 18 | 8.909 | 8.909 |
| `Unity.Timeline` | 9 | 781 | 0 |
| `Unity.TextMeshPro` | 6 | 127 | 39 |
| `Unity.Polybrush` | 1 | 7 | 7 |
| `AssetAssistant` | 2 | 2 | 0 |
| `DOTweenPro` / `DOTween` | 1 / 1 | 2 / 1 | 2 / 0 |
| nicht auflösbar (externer Verweis) | 1 | 2 | 2 |
- Nur **30,9 %** der Assembly-CSharp-Klassen (688 von 2.229) werden überhaupt über Daten referenziert. Die übrigen 1.541 sind reine Logik und müssen nicht gestubbt werden, um Bundles zu laden.
- 170 der 688 Klassen sind ScriptableObjects (9.827 Instanzen: Stammdatentabellen, Nachrichten, Ereignisskripte), 518 sind Komponenten; es gibt keine Klasse, die beides ist.
- 647 der 688 Klassen kommen in genau einer Bundle-Gruppe vor, 41 in 2 bis 7.
- Konzentration: eine Klasse trägt 36,4 % aller Instanzen, die ersten 10 tragen 75,6 %, die ersten 50 95,5 %, die ersten 100 97,8 %; 442 Klassen haben genau eine Instanz, 35 haben mindestens 100.

### 2.2 Je Bundle-Gruppe (Oberordner unter `AssetAssistant`)
Klassen = Assembly-CSharp-Klassen mit mindestens einer Instanz in der Gruppe (eine Klasse zählt in jeder Gruppe, in der sie vorkommt).

| Gruppe | Dateien | Klassen | Instanzen | Komponenten | ScriptableObjects |
|---|---:|---:|---:|---:|---:|
| UIs | 1.995 | 332 | 3.866 | 3.778 | 88 |
| Dpr | 141 | 109 | 6.545 | 242 | 6.303 |
| Effects | 2.987 | 8 | 18.360 | 18.359 | 1 |
| Environments | 644 | 29 | 2.653 | 2.653 | 0 |
| Pokemon Database | 5.748 | 6 | 7.851 | 7.851 | 0 |
| Battle | 1.411 | 7 | 1.587 | 348 | 1.239 |
| Characters | 414 | 10 | 825 | 667 | 158 |
| Contest | 579 | 33 | 642 | 78 | 564 |
| Message | 12 | 1 | 1.280 | 0 | 1.280 |
| FureaiHiroba | 14 | 47 | 282 | 207 | 75 |
| übrige 8 Gruppen | 107 | 144 | 289 | 183 | 106 |
| Player (`resources.assets`, ohne TypeTree) | 5 | 41 | 53 | 40 | 13 |
Szenen-Bundles gibt es nur in `Dpr` (9). Insgesamt 1.827.593 Objekte und 51.006 Container-Einträge (Assets, darunter Prefabs); je Gruppe steht die Zahl in `work/stubs/stats.json` (`container_assets`).

### 2.3 Serialisierte Felder (Assembly-CSharp, dominantes TypeTree-Schema je Klasse, 654 Klassen mit TypeTree)
| Kategorie der Top-Level-Felder | Anzahl |
|---|---:|
| Referenzen `PPtr<T>` | 1.657 |
| Primitive (int, float, Bool, …) | 823 |
| Listen/Arrays | 635 (Elemente: 345 verschachtelte Klassen, 238 `PPtr`, 27 Unity-Strukturen, 23 Primitive, 2 Strings) |
| Unity-Strukturen (`Vector3`, `Color`, `Rect`, …) | 127 |
| verschachtelte `[Serializable]`-Klassen | 97 |
| Strings | 50 |
| `UnityEvent` | 10 |
- Summe 3.399 Top-Level-Felder. `PPtr`-Ziele (inklusive Array-Elemente): 1.087 auf Engine-Klassen, **808 auf Klassen des Spiels**.
- Verschachtelte Hilfstypen: **308 verschiedene** `[Serializable]`-Typen mit 3.133 Blattfeldern. Dictionary-Wrapper sind im TypeTree gewöhnliche verschachtelte Klassen (Schlüssel- und Wertlisten) und werden so erzeugt; sie lassen sich nicht gesondert zählen.
- Aus dem Dump kommen zusätzlich **143 Enums** (im TypeTree nur `int`), 24 Structs und 8 generische Typen.
- `managedReference` (SerializeReference) kommt **nicht** vor (0), ebenso keine Felder von Interface-Typen.

### 2.4 Anteil abdeckbar allein aus dem TypeTree (ohne dump.cs) [D]
Stufen je Klasse (`stub_gen.py gen --no-dump` gegen den Lauf mit Dump):
- **A exakt:** alle Felder sind aus dem Feldbaum eindeutig typisierbar (Primitive, Strings, Unity-Strukturen, `PPtr` auf Engine-Klassen, Arrays, verschachtelte Klassen, Events), Basis ist `MonoBehaviour`/`ScriptableObject`. Enums erscheinen als `int`.
- **B bindet mit Abstrichen:** zusätzlich `PPtr` auf Klassen des Spiels; ohne Dump bleibt nur `UnityEngine.Object` als Feldtyp (Bindung und Wert stimmen, die Typisierung fehlt; 855 solcher Felder, 253 verschiedene Zielklassen).
- **C braucht den Dump:** die Basisklasse ist keine `MonoBehaviour`-Ableitung (uGUI/TMP-Komponenten): ohne Basis erbt der Stub falsch.
- **ohne TypeTree:** Klassen nur in `resources.assets` (Player-Daten ohne TypeTree): Felder nur aus dem Dump.

| Stufe | Klassen | Anteil | Instanzen | Anteil |
|---|---:|---:|---:|---:|
| A exakt | 357 | 51,9 % | 37.932 | 85,8 % |
| B mit Abstrichen | 285 | 41,4 % | 4.213 | 9,5 % |
| C braucht Dump | 12 | 1,7 % | 2.045 | 4,6 % |
| ohne TypeTree | 34 | 4,9 % | 43 | 0,1 % |
| gesamt | 688 | 100 % | 44.233 | 100 % |
**Antwort:** allein aus dem Feldbaum (A + B) sind 642 Klassen (93,3 %) mit 42.145 Instanzen (95,3 %) bindbar; den Dump braucht man für Basisklassen, Namespaces der Ziele, Enum-Namen/-Werte, generische Basen und die 34 Klassen ohne TypeTree. Alle Feldnamen und die Reihenfolge stammen aus dem TypeTree, nie aus dem Dump.

## 3. Verfahren (Generator)
Dateien: `scripts/stub_gen.py` (Scan, Erzeugung, Statistik, Konfliktprüfung), `scripts/stub_dump.py` (Dump-Parser und Typindex), Tests `scripts/tests/test_stub_gen.py` (35 Tests mit erfundenen Namen und synthetischen Fragmenten, ohne UnityPy und ohne Spieldaten).

1. **Scan** (`stub_gen.py scan`): Skriptklassen, Instanzen, Komponenten (GameObject ≠ 0), TypeTree-Schemata (md5-Kurzhash), CAB-Namen und Abhängigkeiten je Bundle, Klassenliste je Bundle. Schemata je Klasse können sich unterscheiden (8 Fälle): Der Generator nimmt das häufigste und ergänzt fehlende Felder der übrigen.
2. **Basiskette** aus dem Dump: Basisklassen bis zur ersten Klasse außerhalb der Stub-Assemblies (Engine, uGUI, TMP, Timeline gelten als vorhanden). Generische Basen (`Foo<T>`), verschachtelte Typen und Außenklassen werden mitgeführt.
3. **Felder auf die Kette verteilen:** Die flache TypeTree-Feldliste (Basisfelder zuerst) wird von hinten mit den im Dump deklarierten Namen der Klassen der Kette abgeglichen. Treffer landen in der deklarierenden Klasse, der Rest gehört der externen Basis (80 Felder, nicht neu deklariert). Felder ohne Gegenstück im Dump (19) stehen bei einer `MonoBehaviour`-Basis auf der Blattklasse.
4. **Typen:** Dump-Typ (Namespace, Enum, Liste/Array, generisch) wird gegen die TypeTree-Form geprüft (Enum ↔ `int`, Klasse ↔ Struktur, Objekt ↔ `PPtr`); bei Abweichung gewinnt der TypeTree (2 Fälle). Mehrdeutige Kurznamen im Dump (Spiel- und Engine-Klasse gleichen Namens) löst bei `PPtr` die Bedingung „Ableitung von `UnityEngine.Object`“, sonst Namespace-Nähe, dann Engine vor Spiel. Ohne Dump: `PPtr<$Engine>` → Engine-Typ, sonst `UnityEngine.Object`; verschachtelte Klassen → Hilfstypen in `Xnu.Stubs.Auto`; Enums → `int`.
5. **Ausgabe:** je Klasse eine Datei `<Namespace als Ordner>/<Name>.cs` unter `Assets/XnuStubs` (ohne asmdef = Assembly-CSharp), `public partial class`, `[SerializeField] private` bzw. `public` je nach Dump, vollqualifizierte `global::`-Typen (keine `using`-Konflikte), Pragmas gegen Warnungen, keine Logik. Verschachtelte Typen liegen in der Datei der Außenklasse; **Typen in generischen Außenklassen** werden zu eigenen Top-Level-Typen (`Outer_Inner`), weil der Compiler sonst CS7002 meldet. Ordner mit Sonderbedeutung (`Editor`, `Resources`, `Plugins`, …) bekommen im Pfad ein `_`, sonst landet die Klasse im Editor-Assembly und bindet nicht (so fehlten zuerst 3 Komponenten einer Gruppe). Feldnamen mit Nicht-ASCII-Zeichen bleiben erhalten (C# erlaubt sie; sonst fehlten in einer Tabellenstichprobe 28 Blätter).
6. **Fremd-Assemblies:** Skripte, deren MonoScript eine andere Assembly nennt (DOTween, DOTweenPro, AssetAssistant, Polybrush), landen unter `XnuStubs/_asm/<Assembly>/` mit einer `<Assembly>.asmdef` **mit dem Originalnamen** (`autoReferenced: true`, `references` aus den Typabhängigkeiten). Unity bindet über den Assemblynamen; so binden diese Klassen (9 Komponenten: 2 DOTweenPro, 7 Polybrush; Gegenprobe in der Gruppe `Contest`: 2 → 0 fehlend mit asmdef). Assembly-CSharp-Stubs dürfen diese Assemblies verwenden. Fremdtypen: uGUI, TextMeshPro und Timeline kommen aus den Paketen (uGUI 2.0 enthält TMP), 33 Skriptklassen daraus werden nicht gestubbt; DOTween/DOTweenPro/AssetAssistant bekommen nur die Typen, die Felder und Basen brauchen (29 Typen), keine Logik; Nintendo-SDK (`nn`, 104 Skripte im Player) wird von keiner Bundle-Instanz referenziert und nicht erzeugt.
7. **Manifest und Bericht:** `manifest.json` (Klassen, Felder, Quelle je Feld `typetree`/`dump`/`typetree+dump`, Assembly, Datei-Liste) im Ausgabeordner; `work/stubs/report.json` (Zählung, nicht abgedeckte Typen). Idempotent: nur geänderte Dateien werden geschrieben, veraltete (samt `.meta`) gelöscht; deterministisch (sortiert, Hash-Schemata). `--dry-run` schreibt nichts.

Erzeugt (Stand dieser Messung, [D]): 1.310 Typen = 693 Skriptklassen, 46 Basisklassen, 411 Datenklassen/-structs (aus Dump oder Hilfstypen), 143 Enums, 17 reine Referenzziele (Hüllen ohne Felder); Felder 5.777 (5.232 TypeTree + Dump, 195 nur TypeTree, 350 nur Dump). Lücken: 5 Klassen ohne Dumpeintrag (alle in fremden Paketen, Basis geraten), 37 Klassen nur aus dem Dump (kein TypeTree), 1 nicht auflösbare Basis.

## 4. Verifikation im Wegwerf-Projekt `work/unity-stubs` [D]
Eigenes Projekt (Unity 6000.3.26f1, Pakete uGUI 2.0 und Timeline), kein Zusammenhang mit `unity/` und `work/unity-shader-lab`; nur ein Batch-Editor zugleich. Werkzeuge: `scripts/stub_verify.py` (Plan, Vorher/Nachher, Abdeckung, Brücke) und `scripts/stub_probe.cs` (Editor-Skript, wird ins Projekt kopiert). Geladen werden nie Shader-Bundles (`shaders`, `fxparticle`, `tmpshader` sind ausgeschlossen), nichts wird gerendert (`-nographics`), Sprachvarianten je Familie genau eine (`.ge`).

### 4.1 Kompilieren
- Erster Versuch: 2 Compilerfehler (CS7002, Aufzählung in generischer Außenklasse) → Hochziehen der Typen (3, Punkt 5). Danach **0 Fehler, 0 Warnungen**; bei 887 Dateien braucht der Compiler rund 2 s.
- Bei einer ersten Gesamtprüfung fehlten 3 Komponenten einer Gruppe: Klassen in einem Namespace `….Editor` liegen im Ordner `Editor` (Editor-Assembly) → Pfad entschärft (3, Punkt 5).

### 4.2 Missing Script vorher/nachher
Messung: `GetComponentsInChildren<Component>` an jedem geladenen Prefab; vorher ohne den Ordner `XnuStubs`, nachher mit.

| Messung | Komponenten | Missing vorher | Missing nachher | Stub-Komponenten |
|---|---:|---:|---:|---:|
| `ui/uiresidentwindow` (53 Prefabs, mit 21 Abhängigkeiten) | 25.293 | 2.650 | **0** | 2.650 |
| `Environments/fields/area001` (Zone 422) | 21.081 | 38 | **0** | 38 |
| Charakter-Prefab (kleinstes mit Stubs) | 21 | 3 | **0** | 3 |
| Ereignisskripte `Dpr/ev_script` (ScriptableObjects) | – | – | – | 936 SO geladen |
| Stammdaten (`Dpr/masterdatas`, `Battle/battle_masterdatas`) | – | – | – | 1.122 SO geladen |
| **13.889 Bundles** (alle bis 80 MB, Sprachvarianten nur `.ge`; 1.112.276 Komponenten) | 1.112.276 | **34.101** | **0** | 34.092 (+ 9 über asmdef) |
| davon Pokemon Database / Effects / Environments / UIs | | 7.851 / 18.359 / 2.660 / 3.755 | 0 | |
- ScriptableObjects, deren Skript fehlt, laden gar nicht (vorher 12, nachher 5.325 geladene SOs in der Gesamtmessung).
- Nicht prüfbar: das Szenen-Bundle (`Dpr/scenes/…`) lässt sich im Editor-Batch nicht öffnen (`EditorSceneManager.OpenScene` kennt nur Szenen aus dem Projekt; Play-Mode-Test steht aus). Für die 9 Szenen-Bundles gilt nur die Strukturzählung aus dem Scan.

### 4.3 Feldbindungs-Prüfer
`stub_verify.py` liest je Klasse zwei Instanzen mit UnityPy (`read_typetree`), flacht sie in Pfade (`feld.Array.data[3].unterfeld`) und vergleicht sie im Editor mit `SerializedObject` der geladenen Instanz (Instanz über die lokale Objekt-ID, Zahlen mit Toleranz 1e-5, Referenzen nur als „gesetzt/leer“).
- **Gruppen-Lauf** (UI, Zone 422, Ereignisse, Stammdaten, Charakter, Szene): 469 Samples, 435 gefunden (die übrigen liegen im nicht ladbaren Szenen-Bundle), 17.483 Blätter, 17.480 gleich.
- **Abdeckungs-Lauf** (gierige Auswahl von 97 Bundles, die 627 der 654 Klassen mit TypeTree enthalten): 780 Samples, 711 gefunden, **574 Klassen geprüft, 573 vollständig gleich**; 42.401 Blätter, **42.399 gleich (99,995 %)**, 0 Wertabweichungen, 0 unaufgelöste Referenzen (gesetzt-aber-leer). 53 Klassen blieben ohne auffindbares Sample (ihre Instanz ließ sich über die lokale ID nicht zuordnen; auch sie zählen in 4.2 mit 0 fehlend), 27 Klassen kommen in keinem ladbaren Bundle ≤ 80 MB vor.
- Die zwei einzigen Abweichungen: ein TMP-Feld der Basisklasse (`m_enableWordWrapping`), das die in Unity 6 mitgelieferte Paketversion umbenannt hat. Folge: dieser Wert geht für alle TMP-Texte verloren (Ersatz: Wert aus dem TypeTree lesen und auf die neue Eigenschaft abbilden, später mit dem Material-Umbau).
- Zwei Fehler im ersten Prüfer-Lauf zeigten, dass er scharf ist: ein `PPtr<$…>` auf eine Spielklasse, die denselben Kurznamen wie eine statische Engine-Klasse trägt (Stub hatte die falsche gewählt, Feld fehlte → jetzt Auflösung über „Ableitung von `UnityEngine.Object`“), und Feldnamen mit Nicht-ASCII-Zeichen (28 Blätter fehlten → jetzt erhalten).

### 4.4 Konsole, Zeit, Speicher
- **Konsole:** 0 Serialisierungsfehler, 0 Warnungen durch die Stubs. In der Gesamtmessung erscheinen 2 Meldungen (`m_PreventLoadingFromFile`-Assertion, `UnloadAssetBundle failed`), **identisch mit und ohne Stubs** (also kein Stub-Effekt).
- **Gesamtlauf** (13.889 Gruppen, je Bundle Laden aller Prefabs und ScriptableObjects, Entladen): 57 s ohne, 59 s mit Stubs, d. h. die Bindung kostet etwa 4 %.
- **UI-Gruppe** (22 Bundles): Bundles öffnen 33 ms, Prefabs und Assets 1,1 s (ohne) bzw. 1,2 bis 1,4 s (mit Stubs); verwalteter Heap +11 MB (ohne) bzw. +21 MB (mit); nativ ca. 172 MB. Zone 422: 10 ms, 0,27 bzw. 0,29 s, Heap +2 MB.
- Speicher/Ladezeit auf dem iPad bleiben ungemessen (Editor, Apple M1 Pro).

## 5. Integration in die Build-Pipeline und Brücke zu `Xnu.*`
### 5.1 Stufe `stubs` (`scripts/build_all.sh`, `scripts/build_stages.py`)
- Stufe `stubs` steht **nach `assets` und vor `unity-build`** (Reihenfolge jetzt: tools extract il2cpp masterdata shaders video audio assets stubs unity-build deploy). Sie braucht `work/il2cpp/dump.cs`, die Bundles unter `work/romfs/…/AssetAssistant` und `tools/pydeps` (UnityPy).
- Ablauf: `stub_gen.py scan` → `stub_gen.py gen --out unity/Assets/XnuStubs` → `stub_gen.py conflicts` (nur Meldung). Marker-Hash: `stub_gen.py`/`stub_dump.py`, Marker der Stufe `il2cpp`, Bundle-Listing; die Stufe `unity-build` hängt zusätzlich am Marker von `stubs`.
- Zielordner `unity/Assets/XnuStubs` (überschreibbar mit `STUBS_DEST`); `.gitignore` nimmt `unity/Assets/XnuStubs/` und `unity/Assets/XnuStubs.meta` auf; die Stufe bricht ab (Exit 2), wenn der Zielordner nicht ignoriert ist.
- **Haupteditor nicht stören:** Hält ein Editor das Projekt `unity/`, überspringt die echte Stufe (Meldung wie bei `unity-build`), denn neue Skriptdateien lösen im offenen Editor eine Neukompilierung aus. `--dry-run` zeigt Plan und Kommandos, schreibt nichts. Es wurde nur im Dry-run geprüft, `unity/Assets` blieb unangetastet. [T] (`test_build_all.py`: Stufenliste, Reihenfolge `assets < stubs < unity-build`, Dry-run der Stufe).
- Stubs sind `partial`: Hooks (Abschnitt 5.3) liegen als handgeschriebene Dateien im Repo, nicht im generierten Ordner.

### 5.2 Konflikte mit handgeschriebenen `Xnu.*`-Typen
`stub_gen.py conflicts --manifest … --scripts unity/Assets/Scripts` vergleicht voll qualifizierte Typnamen (nur Namen, keine Inhalte): **464 handgeschriebene Typen, 1.310 Stub-Typen, 0 gleiche volle Namen** (4 gleiche Kurznamen in verschiedenen Namespaces, unkritisch). Die Beispiele aus der Aufgabe sind keine Treffer: die Stubs liegen im globalen Namespace bzw. in `Dpr.*`/`SmartPoint.*`, die eigenen Typen in `Xnu.*`; `EnvironmentSettingsData`/`…Catalog` heißen anders als die Stub-Klasse, ein `GameInput`-Stub existiert nicht (keine Bundle-Instanz). Regeln für die Zukunft:
- Eigene Typen immer in `Xnu.*`. Gleichnamige Typen in einer autoReferenced-Assembly und in Assembly-CSharp ergeben nur CS0436-Warnungen (Quelltyp gewinnt), **aber** CS0433 (Fehler), wenn zwei referenzierte Assemblies denselben vollen Namen liefern. Die Prüfung `conflicts` läuft deshalb in der Stufe und schlägt bei Treffern an.
- Gleiche Kurznamen in verschiedenen Namespaces sind unkritisch, solange Stubs vollqualifiziert referenzieren (tun sie).

### 5.3 Wie ruft die Logik (Xnu.*) in die Stubs? Varianten und Test
Randbedingung [D, siehe `docs/ui-spezifikation-2.md`]: Bindung läuft über (`Assembly-CSharp`, Namespace, Klassenname); Assembly-CSharp darf autoReferenced-asmdef-Assemblies verwenden, asmdef-Assemblies dürfen Assembly-CSharp **nicht** referenzieren.

| Variante | Prinzip | Urteil |
|---|---|---|
| **A: Schnittstellen in `Xnu.*` + handgeschriebener `partial`-Teil im Stub** | `Xnu.Core` (oder eine Brücken-Assembly) definiert `IBridgeHost`-artige Schnittstellen und Registrierung; ein handgeschriebener `partial`-Teil des Stubs (Ordner ohne asmdef, im Repo) implementiert sie und meldet sich in `Awake`/`OnEnable`/`OnDestroy` an. Die Logik sieht nur die Schnittstelle. | **belastbar, getestet** |
| B: Registrierung per Delegate/Factory | wie A, aber der Stub trägt nur Delegates (`Action`, `Func`) und die Logik registriert sich zur Laufzeit; keine Schnittstelle nötig | tragfähig, schwächer typisiert; für kleine Hüllen gut |
| C: Reflection aus `Xnu.*` | Logik liest Felder per Name | funktioniert, aber untypisiert, langsam und braucht bei IL2CPP `link.xml`/`[Preserve]`; nur für Werkzeuge/Prüfer |
| D: Stubs nach `Assembly-CSharp-firstpass` (`Assets/Plugins`) | firstpass wird vor Assembly-CSharp kompiliert und kann es nicht sehen | **nicht tragfähig** [A]: der Assemblyname im MonoScript lautet `Assembly-CSharp`, firstpass bindet nicht; nicht eigens getestet |
| E: Logik direkt in den Stubs (Assembly-CSharp) | Spiellogik als `partial` im Stub | widerspricht der testbaren Trennung (`Xnu.*` mit EditMode-Tests); nur für dünne Unity-Callbacks sinnvoll |

**Test der Variante A** (`scripts/stub_bridge/`: `Xnu.Bridge.asmdef`, `BridgeHub.cs`; Probe in `stub_probe.cs`, Aufruf `stub_verify.py --phase bridge`): Das Skript erzeugt im Wegwerf-Projekt zu einer Klasse des Original-UI-Bundles einen `partial`-Teil (Assembly-CSharp, getrennter Ordner) mit `[ExecuteAlways]`, der `IBridgeHost` aus `Xnu.Bridge` implementiert und in `Awake`/`OnDestroy` `BridgeHub.Attach/Detach` ruft. Ergebnis [D]:
- 127 `IBridgeHost`-Komponenten in 13 Prefabs des Bundles über `GetComponentsInChildren<IBridgeHost>` gefunden (Logikseite kennt die Stub-Klasse nicht),
- beim Instanziieren eines Prefabs: 6 `Attach`-Aufrufe (`Awake` lief), 18 Instanzfelder über die Schnittstelle gelesen,
- nach `DestroyImmediate`: 0 angemeldete Hosts; 0 Konsolenfehler.
Merke: Der Hook-Ordner darf **nicht** im asmdef-Ordner der Brücke liegen (sonst landet er in `Xnu.Bridge`; im Test passierte genau das zuerst und erzeugte einen CS0436 gegen den Stub).

Empfehlung: Variante A mit Konvention `unity/Assets/Scripts/DprHooks/<Namespace>/<Klasse>.Hook.cs` (ohne asmdef, `partial`), die Schnittstellen in `Xnu.Core`; Hooks bleiben dünn (Weiterleiten, Anmelden), Logik und Tests in `Xnu.*`. Für Unity-Callbacks (`Awake`, `Update`, `OnDestroy`) gilt: nur im Hook definieren, nie im generierten Teil (der ist logikfrei).

## 6. Grenzen und offene Punkte
1. **Szenen-Bundles** (Dpr/scenes, 9 Stück) und Player-Szenen konnten nicht geladen werden; Play-Mode-Test oder Player-Build nötig. Die Gruppe `Dpr` hat 242 Komponenten insgesamt, davon ein Teil in den Szenen (Strukturzählung nur aus dem Scan).
2. **Paketdrift:** Basisklassen aus Paketen (TMP, uGUI) haben in Unity 6 andere Felder als in Unity 2019.4. Gefunden: 1 TMP-Feld (siehe 4.3). Für alle 12 Klassen der Stufe C und alle TMP-/uGUI-Instanzen (8.909 + 127) ist ein Feldabgleich Paket ↔ TypeTree als eigener Schritt sinnvoll.
3. **Shader/Materialien:** unverändert offen (`docs/material-remap.md`); die Stubs laden nur Objekte, rendern nichts. Materialien mit Original-Shader bleiben bis zum Umbau auf `Hidden/InternalErrorShader`.
4. **DOTween/DOTweenPro:** nur Typen für Felder/Basen, keine Tween-Logik. Für die `DOTweenAnimation`-Instanzen in UI/Event-Prefabs (u. a. 49 im UI-Hauptbundle) ist das Verhalten (Kurven, Dauer, Ease) zwar als Daten da, abgespielt wird nichts; Entscheidung Paket oder Eigenbau steht aus (siehe `docs/ui-spezifikation-2.md`, Punkt 3).
5. **Klassen ohne TypeTree** (34 Klassen, 43 Instanzen in `resources.assets`): Felder nur aus dem Dump (Sichtbarkeit und Attribute entscheiden, was Unity serialisiert); ungeprüft, weil keine Referenzwerte existieren.
6. **Interfaces, Methoden, Generics-Constraints** fehlen absichtlich; Konstanten aus dem Dump werden nicht übernommen. Enum-Werte stammen aus dem Dump und sind nicht gegen Instanzwerte geprüft (die Prüfer vergleichen den `int`).
7. **IL2CPP-Stripping** [A]: Klassen, die nur über Bundles gebunden werden, brauchen `link.xml` für Assembly-CSharp (und die asmdef-Assemblies); Player-Test mit gebautem macOS/iPad steht aus (alle Messungen im Editor).
8. **Domain-Reload im Haupteditor:** 887 neue Skriptdateien lösen im offenen Editor eine größere Neukompilierung aus (im Wegwerf-Projekt 2 s Compiler, zuzüglich Reload); deshalb überspringt die Stufe bei offenem Editor.
9. **Unity.Polybrush** (7 Instanzen, Editor-Überbleibsel) und 2 Instanzen mit nicht auflösbarem Skriptverweis werden nicht abgedeckt; kein Einfluss auf das Spiel [A].
10. Lizenz/Rechtliches: Der Generator erzeugt zur Laufzeit Klassenhüllen aus den Daten des Nutzers; das Repo enthält weder Stubs noch Dump-Auszüge. Das ist keine Rechtsberatung.

## 7. Nächste Schritte (Priorisierung der Logik-Nachlieferung)
Gewichte (aus `stub_gen.py stats`, Namen nur in `work/stubs/stats.json`): Instanzen je Klasse (Bedeutung für geladene Szenen), Anzahl der Methoden im Dump als Aufwand (Methoden der 688 referenzierten Klassen: 8.769 von ca. 47.800 in Assembly-CSharp = 18,3 %).
1. **Klasse für Klasse nach „Instanzen je Methode“, innerhalb des Vertikalschnitts:** Die ersten 20 Klassen tragen 87,6 % der Instanzen, haben aber zusammen nur 187 Methoden (hauptsächlich Marker- und Datenhalter: Effekt-, Umgebungs- und Datenbankobjekte). Sie liefern am meisten Sichtbares für wenig Logik: zuerst.
2. **Dann je Gruppe geschlossene Pakete** (Aufwand = Methoden mit Basen; Zahlen aus der Gruppenzuordnung nach der größten Instanzzahl): `Effects` 7 Klassen/18.389 Instanzen/113 Methoden, `Pokemon Database` 6/7.851/213, `Message` 1/1.280/1, `Battle` 7/2.116/58, `Environments` 28/2.754/1.480, `Dpr` (Stammdaten-SOs und Systeme) 101/6.429/1.048, `Characters` 9/795/660; am Ende `UIs` mit 305 Klassen/3.965 Instanzen/8.457 Methoden (größter Block, hängt an der Brücke und am TMP-Abgleich), dann `Contest`, `FureaiHiroba`, `UnderGround`, `DigFossil` und die übrigen kleinen Gruppen.
3. **Abhängigkeiten** (PPtr-Graph, 808 Verweise auf Spielklassen): Klassen mit eingehenden Verweisen vor ihren Nutzern; der Generator kennt den Graphen bereits, ein `stats`-Ausgabefeld „Eingangsgrad“ ist der nächste kleine Schritt.
4. **Brücke festschreiben:** `IBridgeHost`-artige Schnittstellen nach `Xnu.Core`, Hook-Ordner `DprHooks` anlegen, ein Orakeltest je nachgelieferter Klasse (Feldwerte der Instanzen ↔ Logikergebnis), Prüfer `stub_verify.py --coverage` als Regression nach jeder Stubs-Erzeugung.
5. **Offene Messungen:** Szenen-Bundles im Play-Mode/Player, IL2CPP-Player mit `link.xml`, Material-Umbau (Shader/TMP), DOTween-Entscheidung, TMP-Feldabgleich, Hauptprojekt-Editor-Lauf mit echter Stufe `stubs` (erst nach Schließen des Editors).
6. Optional: `--all-classes` (alle 2.229 Klassen aus dem Dump als dump-only-Hüllen), falls handgeschriebene Logik später Typen aus nicht referenzierten Klassen braucht; der Generator kann das mit `dump_only_fields`, ist aber noch nicht als Schalter verdrahtet.

## 8. Reproduktion
```
python3 scripts/stub_gen.py scan                                   # work/stubs/scan.json (ca. 3 min)
python3 scripts/stub_gen.py stats                                  # Zahlen: work/stubs/stats.json
python3 scripts/stub_gen.py gen --out work/unity-stubs/Assets/XnuStubs   # Stubs, manifest.json, work/stubs/report.json
python3 scripts/stub_gen.py gen --out … --dry-run                  # nichts schreiben
python3 scripts/stub_gen.py conflicts --manifest …/manifest.json   # gleiche Typnamen wie handgeschriebener Code?
python3 scripts/stub_verify.py --phase both                        # Missing Script vorher/nachher, Feldbindung (Gruppen)
python3 scripts/stub_verify.py --phase both --bulk "UIs,Battle,Effects,…" --bulk-max-mb 80   # Zählung über alle Bundles
python3 scripts/stub_verify.py --phase after --coverage --per-class 2                          # je Klasse ein Sample
python3 scripts/stub_verify.py --phase bridge                      # Brückentest
python3 -m unittest scripts.tests.test_stub_gen                    # 35 Tests
scripts/build_all.sh --dry-run --only stubs                        # Stufe im Pipeline-Plan
```
Voraussetzung Wegwerf-Projekt: `work/unity-stubs/Packages/manifest.json` mit uGUI 2.0 (enthält TMP), Timeline und den Engine-Modulen, `ProjectSettings/ProjectVersion.txt` mit `6000.3.26f1`; Unity legt den Rest beim ersten Batch-Start an.
