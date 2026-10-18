# M0 – Bundle-Kompatibilität: BDSP-Dump in Unity 6.3 LTS

Stand: 2026-10-18. Geprüft wurde, ob die AssetBundles des eigenen BDSP-Dumps
(UnityFS v7, gebaut mit Unity 2019.4.27f1, LZ4HC, Switch) im Editor
6000.3.26f1 (macOS arm64, Metal, Build-Target StandaloneOSX) per
`AssetBundle.LoadFromFile` geladen werden können. Alle Bundles wurden über
absolute Pfade geladen (nicht nach Assets kopiert) und mit `Unload(true)`
wieder entladen. Dieses Dokument enthält nur Namen, Zahlen und Typen – keine
Spielinhalte.

## Kurzergebnis

- Alle Bundles lassen sich laden: Ein Durchlauf über den gesamten Ordner
  `AssetAssistant` ergab 14.052 von 14.052 Bundles `ok`, 0 Fehlschläge.
  Nicht ladbar waren nur `Dpr.bin` (kein Bundle) und macOS-`.DS_Store`-Dateien.
- Es trat **keine** Meldung der Art „was built with an incompatible …“ auf.
  Die Bundles enthalten TypeTrees; Unity 6 liest sie.
- Texturen, Meshes, Sprites, AnimationClips, TimelineAssets, TMP-Fonts und
  Prefabs sind als Objekte zugreifbar.
- ScriptableObjects/MonoBehaviours (Stammdaten) lassen sich ohne die
  Spiel-Skripte nicht instanziieren (erwartet).
- **Shader aus dem Dump dürfen nie gerendert werden:** Ein `Graphics.Blit`
  mit einem Material auf Basis eines Dump-Shaders hat den Editor abstürzen
  lassen (siehe unten).

## Ergebnis je Bundle

Pfade relativ zu `work/romfs/Data/StreamingAssets/AssetAssistant/`.

| Bundle | Größe | Art | Laden | Assets (`GetAllAssetNames`) | Objekte / Typen | Konsole |
|---|---|---|---|---|---|---|
| `Dpr/masterdatas` | 449 KB | Stammdaten | ja | 1118 (`.asset`) | `LoadAllAssets` = 0 Objekte, `LoadAsset` (auch mit Typ ScriptableObject/MonoBehaviour) = null, `LoadAssetWithSubAssets` = 0 | keine Meldung |
| `UIs/textures/box` | 110 KB | Texturen/UI | ja | 62 (1 `.spriteatlas`, 61 `.png`) | 61 Sprite, 1 SpriteAtlas | keine |
| `UIs/shareduiassets/sharedui` | 970 KB | UI | ja | 298 (297 `.png`, 1 `.spriteatlas`) | 322 Sprite, 1 SpriteAtlas | keine |
| `Pokemon Database/pokemons/common/pm0002_00` | 944 KB | Mesh/Textur/Anim | ja | 27 (14 `.anim`, 3 `.mesh`, 6 `.tga`, 4 `.png`) | 14 AnimationClip, 3 Mesh, 10 Texture2D | keine |
| `Characters/objects/ob1015_01` | 11,7 KB | Prefab/Mesh | ja | 3 | GameObject, Mesh, Material | keine |
| `Pokemon Database/pokemons/battle/pm0001_00_00` | 19 KB | Prefab | ja | 1 (`.prefab`) | 1 GameObject | keine |
| `Pokemon Database/pokemons/battle/animations/pm0292_00` | 6,6 KB | Animation | ja | 1 (`.anim`) | 1 AnimationClip | keine |
| `FureaiHiroba/demo/timeline/evolve` | 508 KB | Timeline | ja | 2 (`.playable`, `.prefab`) | 1 TimelineAsset, 1 GameObject, 20 AnimationClip | keine |
| `Dpr/common_resources` | 9 MB | Texturen/Font | ja | 8 | 7 Texture2D, 1 TMP_FontAsset, 2 Material | keine |
| `Dpr/shaders` | 6,7 MB | Shader | ja | 64 (63 `.shader`, 1 `.mat`) | 63 Shader, 1 Material (Laden ca. 0,7 s) | beim Laden keine; beim Rendern Absturz, s. u. |

Weitere Stichproben: `Dpr/ev_script`, `Dpr/Dpr`, `Pml/personal_masterdatas`,
`Battle/battle_masterdatas`, `FureaiHiroba/fureai/prefabs` (1 Prefab) und
`UIs/textures_mass/pokemon_dp/*` (je 1 Sprite + 1 Texture2D) laden ebenfalls.

### Asset-Arten im Gesamtdurchlauf (Namenserweiterungen, Anzahl Bundles)

`.prefab` 7050, `.png` 2836, `.asset` 1898, `.anim` 1882, `.tga` 1632,
`.mesh` 945, `.mat` 414, `.spriteatlas` 60, `.controller` 6, `.playable` 5,
`.shader` 3, `.fbx` 2, `.jpg` 1, `.shadervariants` 1. Es kommen keine
Audio-Erweiterungen (`.wav`, `.ogg` …) vor; die Tonausgabe liegt also nicht in
diesen Unity-Bundles, ein Zugriff auf AudioClips war daher nicht prüfbar.

## Zugriff auf Texturen, Meshes, Animationen

| Quelle | Befund |
|---|---|
| `box` (Sprite-Atlas) | 1 Atlas-Textur, ASTC_6x6, 1024×1024, 1 Mip, nicht lesbar. `Sprite.texture` ist für 61/61 Sprites `null`; die Textur ist nur über das SpriteAtlas-Objekt erreichbar (`SpriteAtlas.GetSprite` liefert Sprites) |
| `sharedui` | 2 Atlas-Texturen, ASTC_6x6, je 2048×2048, 1 Mip; `Sprite.texture` ebenfalls `null` bei 322/322 |
| `pm0002_00` | 10 Texturen: DXT1 512×512 (3), DXT1 256×512, DXT1 32×32 (2), ASTC_6x6 512×512 (2), ASTC_6x6 256×512, ASTC_6x6 256×128; 6–10 Mips |
| `pm0002_00` Meshes | 2309 / 1111 / 896 Vertices, 1–4 Submeshes, lesbar |
| `ob1015_01` | Mesh mit 50 Vertices, nicht lesbar; Material zeigt `Hidden/InternalErrorShader`, weil der Shader in einem anderen Bundle liegt |
| `common_resources` | DXT1 512² und 256², BC5 512², BC4 256² / 1024² / 256², Alpha8 4096² (lesbar) |
| `textures_mass/pokemon_dp/…` | RGBA32 88×88, 1 Mip, Sprite referenziert die Textur korrekt |
| Animation | `pm0292_00`: Länge 0,67 s, 30 fps, nicht Legacy; `evolve`: Clips mit 10 s, 14,4 s, 11,8 s und 30 fps, teils Events. `AnimationUtility.GetCurveBindings` lieferte 0 Bindings, die Kurvenauswertung wurde nicht weiter untersucht |

ASTC wird auf Apple Silicon problemlos als `Texture2D` geladen. Dazu kommen
auch DXT/BC-Formate; Unity dekomprimiert diese bei Bedarf auf dem Mac.

## Typbaum-/Versionskompatibilität

Keine Meldung wie „The AssetBundle … was built with an incompatible …“, keine
Lesefehler, kein Null-Ergebnis bei einem echten Bundle. Die einzigen
Konsolenmeldungen im gesamten Durchlauf waren:

- `Failed to read data for the AssetBundle '.DS_Store'.` (3×)
- `Failed to read data for the AssetBundle 'Dpr.bin'.`
- `The AssetBundle 'sharedui' can't be loaded because another AssetBundle with the same files is already loaded.` – Folge eines von mir abgebrochenen Testskripts, das das Bundle nicht entladen hatte, kein Bundle-Fehler.

Die Typbäume sind also vorhanden und mit Unity 6 lesbar. Für
MonoBehaviour/ScriptableObject-Objekte (z. B. `masterdatas`) fehlen die
Skriptklassen; die Objekte werden nicht erzeugt. Ihre Daten müssen daher
außerhalb von Unity (Typbaum-Parser, z. B. UnityPy/AssetRipper) gelesen
werden oder die Skriptklassen müssen nachgebaut werden.

## Shader und der Editor-Absturz

`Dpr/shaders` wird vollständig geladen: 63 Shader-Objekte, `isSupported` ist
bei allen `true`, Namen und Eigenschaften (z. B. 35 bis 65 Properties bei den
TextMeshPro-Shadern) sind lesbar, die Konsole bleibt dabei leer. Das sagt
aber nichts über die Brauchbarkeit aus.

Absturz: Ein Eval-Skript hat aus allen 63 Shadern Materialien erzeugt und sie
mit `Graphics.Blit` auf eine RenderTexture gezeichnet. Der Editor stürzte
am 2026-10-18 um 21:25:30 mit `SIGSEGV` ab (Segmentation fault: 11). Im
Editor.log stand direkt davor:

`GpuProgram creation error: shader program type is unrecognised. You might have a precompiled shader asset from an old Unity version.`

Der verwaltete Stacktrace endet in `UnityEngine.Graphics:Blit` →
`Graphics:Internal_BlitMaterial5`. Wahrscheinliche Ursache (aus der Meldung
abgeleitet): Die Shader im Dump enthalten nur vorkompilierte Programme für die
Switch-Plattform; Metal kann daraus kein GPU-Programm erzeugen, und der
Render-Aufruf fängt das nicht ab. `isSupported == true` ist dafür kein
verlässlicher Test.

Regel für alles Weitere: Dump-Shader nie rendern (kein Blit/Draw, keine
Materialien mit diesen Shadern in Szenen). Laden, Auflisten und Inspizieren ist
unkritisch. Der Editor wurde danach neu gestartet; der Absturz wurde bewusst nicht
erneut provoziert.

## Schlussfolgerung für Option A (neues Unity-Projekt)

Option A ist für die Daten machbar: Alle Bundles lassen sich in Unity 6.3
öffnen, Geometrie, Texturen (ASTC/DXT/BC), Sprites/Atlanten, Animationen,
Timelines, Fonts und Prefab-Hierarchien sind als Objekte verfügbar. Es gibt
keinen Versionsbruch durch fehlende TypeTrees.

Einschränkungen:

1. **Shader müssen neu geschrieben werden** (URP/HDRP oder eigene Shader für
   Metal); die Dump-Shader dienen nur als Referenz für Namen und
   Properties. Materialien müssen auf neue Shader umgehängt werden, sonst
   erscheint `Hidden/InternalErrorShader`.
2. **Stammdaten (ScriptableObjects) brauchen eigene Skriptklassen** oder einen
   externen Parser, weil Unity die Objekte ohne Skripte nicht lädt.
3. Sprite-Atlanten liefern `Sprite.texture == null`; Texturen müssen über den
   Atlas oder per Export aufgelöst werden.
4. Audio liegt nicht in diesen Bundles.
5. Der Ladeweg „Bundle direkt zur Laufzeit“ sollte Materialien/Shader
   strikt vom Rendern ausschließen; empfohlen ist ein Importschritt, der
   Meshes, Texturen, Animationen und Prefabs in eigene Assets überführt.

Nicht geprüft: Rendern von Dump-Materialien mit neuen Shadern, Animator-
Controller-Funktion, Skinning/Rigs im Play-Modus, Audio, Verhalten im Player-
Build.
