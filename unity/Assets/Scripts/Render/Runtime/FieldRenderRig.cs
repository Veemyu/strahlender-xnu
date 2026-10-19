using UnityEngine;

namespace Xnu.Render
{
    // Kamera-Ausstattung für die erzeugten Shader im Feld (docs/sichtpruefung-3.md): Tiefentexturen für Wasser und Nebel
    // (_OpaqueDepthTexture, _GlobalDepthTexture), Reflexionskamera (_ReflectionTex, _ReflectionVP) und Nachbearbeitung
    // (Bloom, Nebel, FXAA). Ohne die Tiefentexturen zeichnen die Wasser-Shader eine einfarbig braune Fläche.
    public sealed class FieldRenderRig
    {
        public DepthCaptureDriver Depth { get; private set; }
        public ReflectionCameraDriver Reflection { get; private set; }
        public PostChain Post { get; private set; }

        GameObject _reflectionCamera;
        bool _addedDepth, _addedPost;

        public override string ToString() =>
            "Tiefe " + (Depth != null ? "an" : "aus") + ", Reflexion " + (Reflection != null ? "an" : "aus") + ", Nachbearbeitung " + (Post != null ? "an (" + Post.Status + ")" : "aus");

        // Idempotent: schon vorhandene Komponenten der Kamera werden wiederverwendet.
        // reflectionScale: Auflösung der Reflexionstextur relativ zum Bildschirm (0,5 = halbe Breite und Höhe).
        public static FieldRenderRig Attach(Camera main, EnvironmentDriver driver, bool reflection = true, bool post = true, float reflectionScale = 0.5f)
        {
            var rig = new FieldRenderRig();
            if (main == null) return rig;
            rig.Depth = main.GetComponent<DepthCaptureDriver>();
            if (rig.Depth == null) { rig.Depth = main.gameObject.AddComponent<DepthCaptureDriver>(); rig._addedDepth = true; }
            if (post)
            {
                rig.Post = main.GetComponent<PostChain>();
                if (rig.Post == null) { rig.Post = main.gameObject.AddComponent<PostChain>(); rig._addedPost = true; }
                rig.Post.Driver = driver;
            }
            if (reflection)
            {
                var go = new GameObject("ReflectionCamera", typeof(Camera)) { hideFlags = HideFlags.DontSave };
                var c = go.GetComponent<Camera>();
                c.CopyFrom(main);
                c.rect = new Rect(0f, 0f, 1f, 1f);          // die Hauptkamera kann auf ein Seitenverhältnis begrenzt sein
                c.depth = main.depth - 10f;
                c.clearFlags = CameraClearFlags.SolidColor;
                c.backgroundColor = Color.white;
                c.allowHDR = false;
                c.allowMSAA = false;
                c.targetTexture = null;
                var d = go.AddComponent<ReflectionCameraDriver>();
                d.Target = main;
                d.CustomWidth = Mathf.Max(64, Mathf.RoundToInt(Screen.width * reflectionScale));
                d.CustomHeight = Mathf.Max(64, Mathf.RoundToInt(Screen.height * reflectionScale));
                rig._reflectionCamera = go;
                rig.Reflection = d;
            }
            return rig;
        }

        // Entfernt, was Attach angelegt hat (Reflexionskamera, Nachbearbeitung, Tiefenaufnahme); vorhandene Komponenten bleiben.
        public void Detach()
        {
            Kill(_reflectionCamera);
            if (_addedPost) Kill(Post);
            if (_addedDepth) Kill(Depth);
            _reflectionCamera = null;
            Reflection = null; Post = null; Depth = null;
        }

        static void Kill(Object o)
        {
            if (o == null) return;
            if (Application.isPlaying) Object.Destroy(o); else Object.DestroyImmediate(o);
        }
    }
}
