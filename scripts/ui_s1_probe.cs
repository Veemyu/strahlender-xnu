// Spike S1, Unity-Teil (Eval-Skript, kein Teil des Projekts):
//   unity command --project-path unity --result-only eval_file $PWD/scripts/ui_s1_probe.cs
// Lädt ui/uiresidentwindow samt Abhängigkeiten OHNE Shader-Bundle und mit genau einer Sprachvariante, zählt
// fehlende Skripte (null-Komponenten), Image-Sprites und Materialien. Braucht XNU_GAMEDATA oder das Standardverzeichnis.
// Variante wählen: LANG = "ge" (Deutsch), "en", "jp" ...
var LANG = "ge";
var sb = new System.Text.StringBuilder();
var report = Xnu.Boot.BootSequence.Run(Xnu.Core.GameDataPaths.AssetAssistant, new Xnu.Boot.UnityBundleSource());
var prov = report.Provider;
prov.UnloadAllLoadedObjects = false;
// Sprachvarianten (*.xx) enthalten dieselben Dateien: Unity lädt nur eine je Familie (sonst LoadFromFile = null).
prov.DependencyFilter = r => !(r.Name == "shaders" || r.Name.EndsWith("/shaders"))
    && !(r.Name.Length > 3 && r.Name[r.Name.Length - 3] == '.');
prov.Acquire("UIs/textures/common_lang." + LANG);
prov.Acquire("UIs/shareduiassets/sharedui_lang." + LANG);
var h = prov.Acquire("UIs/ui/uiresidentwindow");
int total = 0, missing = 0, images = 0, withSprite = 0, withMaterial = 0;
foreach (var n in h.GetAllAssetNames())
{
    var go = h.LoadAsset(n, typeof(UnityEngine.GameObject)) as UnityEngine.GameObject;
    if (go == null) continue;
    foreach (var c in go.GetComponentsInChildren<UnityEngine.Component>(true))
    {
        total++;
        if (c == null) { missing++; continue; }
        if (c is UnityEngine.UI.Image im)
        {
            images++;
            if (im.sprite != null) withSprite++;
            // Original-Materialien tragen Hidden/InternalErrorShader (Shader-Bundle ist nicht geladen); nie rendern.
            if (im.material != null && im.material.shader != null && im.material.shader.name == "Hidden/InternalErrorShader") withMaterial++;
        }
    }
}
sb.AppendLine("Komponenten " + total + ", Missing Script " + missing + ", Images " + images + ", mit Sprite " + withSprite + ", mit Fehlershader-Material " + withMaterial);
prov.UnloadAll();
return sb.ToString();
