using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Xnu.UI
{
    // Textquelle der Fenster (Labelname in einer Textdatei, z. B. "ss_xmenu" / "SS_xmenu_28"). null = nicht vorhanden.
    public interface IUiLabelSource
    {
        string Label(string msbt, string label);
    }

    // Textquelle mit Zahlenplatzhaltern (z. B. Stufe): die Zahl belegt die Platzhalterplätze des Labels.
    public interface IUiNumberLabelSource : IUiLabelSource
    {
        string Label(string msbt, string label, long number);
    }

    // Eigenes Ersatzmaterial für Grafiken, deren Original-Shader fehlt (Hidden/InternalErrorShader nach dem Laden ohne Shader-Bundle).
    // Zuordnung nach dem Materialnamen des Originals; Original-Shader werden nie geladen.
    public static class UiMaterialFixer
    {
        static Material _add, _gray;
        static readonly Dictionary<string, Material> Cache = new Dictionary<string, Material>();

        public static int FixedGraphics { get; private set; }
        public static int FixedTexts { get; private set; }

        public static bool IsBroken(Material m) => m != null && (m.shader == null || m.shader.name.StartsWith("Hidden/InternalError"));

        public static Material Replacement(Material original)
        {
            var n = original.name;
            if (n.IndexOf("Gray", System.StringComparison.OrdinalIgnoreCase) >= 0)
                return _gray != null ? _gray : _gray = Make("XnuUiGray");
            if (n.IndexOf("Add", System.StringComparison.OrdinalIgnoreCase) >= 0 || n.IndexOf("LightFrame", System.StringComparison.OrdinalIgnoreCase) >= 0)
                return _add != null ? _add : _add = Make("XnuUiAdd");
            return null;
        }

        static Material Make(string resource)
        {
            if (Cache.TryGetValue(resource, out var c) && c != null) return c;
            var shader = Resources.Load<Shader>(resource);
            if (shader == null) return null;
            var m = new Material(shader) { name = resource, hideFlags = HideFlags.HideAndDontSave };
            Cache[resource] = m;
            return m;
        }

        // Ersetzt Grafik- und Schriftmaterialien ohne gültigen Shader. Texte bekommen die mitgelieferte Standardschrift (TextMeshPro Essentials).
        public static void Fix(GameObject root)
        {
            foreach (var g in root.GetComponentsInChildren<Graphic>(true))
            {
                if (g is TMP_Text t) { FixText(t); continue; }
                if (!IsBroken(g.material)) continue;
                g.material = Replacement(g.material);
                FixedGraphics++;
            }
        }

        public static void FixText(TMP_Text t)
        {
            var font = TMP_Settings.defaultFontAsset;
            if (font == null) return;
            if (t.font == font && !IsBroken(t.fontSharedMaterial)) return;
            t.font = font;
            t.fontSharedMaterial = font.material;
            FixedTexts++;
        }
    }

    // Füllt statische Beschriftungen (Textfeld mit Datei und Label) aus der Textquelle.
    public static class UiTextBinder
    {
        // Rückgabe: gefüllte Felder. Felder ohne Label (dynamische Texte) bleiben unberührt.
        public static int Apply(GameObject root, IUiLabelSource labels, out int missing)
        {
            var n = 0;
            missing = 0;
            foreach (var mb in root.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (!(mb is IUiText ut) || !ut.UseMessage || string.IsNullOrEmpty(ut.MessageFile) || string.IsNullOrEmpty(ut.MessageId)) continue;
                var text = labels?.Label(ut.MessageFile, ut.MessageId);
                if (text == null) { missing++; continue; }
                // Laufzeitwerte (Zahl, Name) setzt die Logik; unbelegte Platzhalter blieben sonst als {Gruppe:Nr} sichtbar.
                ut.Text.text = System.Text.RegularExpressions.Regex.Replace(text, @"\{\d+:\d+\}", "");
                n++;
            }
            return n;
        }
    }

    // Instanziiert ein Original-Fenster-Prefab, bindet den Canvas an die Spielkamera und behebt Materialien und Beschriftungen.
    public static class OriginalWindowFactory
    {
        public static string LastError { get; private set; }

        public static GameObject Create(string prefabKey, Camera camera, int sortingOrder, Transform parent, IUiLabelSource labels, out int bound)
        {
            bound = 0;
            var prefab = UiBundles.LoadPrefab(prefabKey);
            if (prefab == null) { LastError = UiBundles.Error ?? "Prefab nicht ladbar: " + prefabKey; return null; }
            var go = Object.Instantiate(prefab, parent, false);
            go.name = prefab.name;
            var canvas = go.GetComponent<Canvas>();
            var scaler = go.GetComponent<CanvasScaler>();
            if (scaler != null)
            {
                // Einige Prefabs tragen ConstantPixelSize mit Faktor 0; alle Fenster gelten mit Referenz 1280×720, Breitenabgleich (docs/ui-spezifikation-1.md 3.1).
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(UiCanvasFactory.ReferenceWidth, UiCanvasFactory.ReferenceHeight);
                scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
                scaler.matchWidthOrHeight = 0f;
            }
            if (canvas != null)
            {
                if (camera != null)
                {
                    canvas.renderMode = RenderMode.ScreenSpaceCamera;
                    canvas.worldCamera = camera;
                    canvas.planeDistance = 1f;
                }
                else canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                canvas.overrideSorting = false;
                canvas.sortingOrder = sortingOrder;
            }
            UiMaterialFixer.Fix(go);
            bound = UiTextBinder.Apply(go, labels, out _);
            StartWindowAnimation(go);
            return go;
        }

        // Fenster-Animator: Zustand „In“ (Öffnen) abspielen, wenn er existiert; sonst Animatoren abschalten, damit die Fenster sichtbar bleiben.
        static readonly string[] OpenStates = { "In", "Open", "Opening", "Show", "Idle", "Loop", "Wait", "Default" };

        static void StartWindowAnimation(GameObject go)
        {
            foreach (var cg in go.GetComponentsInChildren<CanvasGroup>(true))
                if (cg.gameObject.name == "Window") cg.alpha = 1f;
            foreach (var a in go.GetComponentsInChildren<Animator>(true))
            {
                if (a.gameObject.name != "Window") continue;
                var found = "";
                foreach (var s in OpenStates)
                    if (a.runtimeAnimatorController != null && a.HasState(0, Animator.StringToHash(s))) found += s + " ";
                Debug.Log("[UI] Animator " + go.name + "/Window: Zustände " + (found.Length == 0 ? "keiner der bekannten (Animator aus, Fenster sichtbar)" : found));
                var hash = Animator.StringToHash("In");
                if (a.runtimeAnimatorController != null && a.HasState(0, hash)) a.Play(hash, 0, 1f);
                else a.enabled = false;
            }
        }
    }
}
