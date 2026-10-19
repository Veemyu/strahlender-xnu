using System.Collections.Generic;
using UnityEngine;

namespace Xnu.Render
{
    // Licht für die erzeugten Forward-Shader. Ohne aktives Richtungslicht zeichnen sie schwarz (docs/material-remap.md,
    // Abschnitt 10b): Der Hauptlicht-Wert _LightColor0 ist dann 0, und das Original multipliziert alles damit.
    public static class SunLight
    {
        // Alle Richtungslichter in Szenen (auch solche mit HideFlags.DontSave, die FindObjectsByType auslässt; Prefab-Assets nicht).
        static IEnumerable<Light> SceneLights()
        {
            foreach (var l in Resources.FindObjectsOfTypeAll<Light>())
                if (l != null && l.gameObject.scene.IsValid() && l.type == LightType.Directional && l.isActiveAndEnabled) yield return l;
        }

        // Hellstes aktives Richtungslicht oder null.
        public static Light FindActive()
        {
            Light best = null;
            foreach (var l in SceneLights())
                if (best == null || l.intensity > best.intensity) best = l;
            return best;
        }

        // Vorhandenes aktives Richtungslicht oder ein neues ("FieldSun", Euler 50/-30/0, weiß, Intensität 1, ohne Schatten);
        // EnvironmentDriver überschreibt Farbe, Intensität und Drehung je Bild mit den Spielwerten.
        public static Light Ensure(Transform parent = null, LightShadows shadows = LightShadows.None)
        {
            ShadowMapGuard.Install();
            var l = FindActive();
            if (l != null) return l;
            var go = new GameObject("FieldSun");
            if (parent != null) go.transform.SetParent(parent, false);
            go.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            l = go.AddComponent<Light>();
            l.type = LightType.Directional;
            l.color = Color.white;
            l.intensity = 1f;
            l.shadows = shadows;
            return l;
        }

        public static RenderFacts Collect(GameGlobals globals, int generatedMaterials)
        {
            var n = 0; var max = 0f;
            foreach (var l in SceneLights()) { n++; if (l.intensity > max) max = l.intensity; }
            return new RenderFacts
            {
                GeneratedMaterials = generatedMaterials,
                ActiveDirectionalLights = n,
                BrightestSunIntensity = max,
                GlobalsSet = globals != null ? globals.CountSet : 0,
                GlobalsTotal = GameGlobals.Specs.Count,
            };
        }
    }

    // Prüft alle 2 s die Regeln aus RenderChecks und meldet jedes Problem einmal (Debug.LogWarning), bis es behoben ist.
    // Hängt der Aufrufer an das Szenenobjekt, das die erzeugten Materialien baut.
    public sealed class RenderHealthWatch : MonoBehaviour
    {
        public GameGlobals Globals;
        public int GeneratedMaterials;
        public float IntervalSeconds = 2f;
        public List<RenderProblem> Current { get; private set; } = new List<RenderProblem>();

        float _next;
        readonly HashSet<RenderProblemKind> _reported = new HashSet<RenderProblemKind>();

        void Update()
        {
            if (Time.unscaledTime < _next) return;
            _next = Time.unscaledTime + Mathf.Max(0.1f, IntervalSeconds);
            Current = RenderChecks.Evaluate(SunLight.Collect(Globals, GeneratedMaterials));
            var now = new HashSet<RenderProblemKind>();
            foreach (var p in Current)
            {
                now.Add(p.Kind);
                if (_reported.Add(p.Kind)) Debug.LogWarning("[Render] " + p.Message);
            }
            _reported.IntersectWith(now);
        }
    }
}
