using System;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;
using Xnu.Core;

namespace Xnu.Field.Editor
{
    // Sichtprüfung (docs/sichtpruefung-1.md): Bild der Feldkamera im Spielmodus in eine RenderTexture rendern und als PNG speichern
    // (ScreenCapture liefert in den ersten Sekunden Cyan). Bilder gehören nach work/visual/, nie ins Repo oder unter Assets/.
    // Aufruf per eval: FieldShot.Prepare(12f) vor dem Spielmodus, dann FieldShot.Capture(pfad, 1280, 720) im Spielmodus.
    public static class FieldShot
    {
        // Umgebungsvariablen des Editor-Prozesses für den nächsten Start der Feldszene.
        public static string Prepare(float hour)
        {
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable(GameDataPaths.EnvVar)))
                Environment.SetEnvironmentVariable(GameDataPaths.EnvVar, Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "work")));
            Environment.SetEnvironmentVariable("XNU_GENERATED_SHADERS", "1");
            if (hour >= 0f) Environment.SetEnvironmentVariable("XNU_ENV_HOUR", hour.ToString("F2", System.Globalization.CultureInfo.InvariantCulture));
            return GameDataPaths.EnvVar + "=" + GameDataPaths.Root;
        }

        public static FieldController Find() => UnityEngine.Object.FindFirstObjectByType<FieldController>();

        // Zustand der Feldszene als Text (Spielmodus).
        public static string Status()
        {
            var f = Find();
            if (f == null) return "kein FieldController";
            if (!f.Loaded) return "nicht geladen; Fehler=" + f.Error;
            var sb = new StringBuilder();
            sb.Append("Zone ").Append(f.zoneId).Append(" geladen; ").Append(f.MaterialMode).Append("; ").Append(f.EnvironmentNote);
            sb.Append("; Renderer ").Append(f.BuildStats.Renderers).Append("; Blöcke ").Append(f.Streamer.Loaded.Count);
            sb.Append("; Spieler (").Append(f.Mover.GridX).Append(", ").Append(f.Mover.GridY).Append(") Weltpos ")
              .Append(f.Player.position.ToString("F1"));
            var cam = Camera.main;
            if (cam != null) sb.Append("; Kamera ").Append(cam.transform.position.ToString("F1")).Append(" Neigung ").Append(cam.transform.eulerAngles.x.ToString("F1"))
                              .Append(" FOV ").Append(cam.fieldOfView.ToString("F1"));
            return sb.ToString();
        }

        // Wie Capture, aber am Bildende (WaitForEndOfFrame) im Spielmodus: so entsteht auch die Aufnahme im Labor; Capture per eval läuft
        // außerhalb der Bildschleife und zeigt mit Schatten abweichende Helligkeit. Ergebnis in LastResult.
        public static string LastResult = "";

        public static string CaptureAtFrameEnd(string path, int width = 1280, int height = 720)
        {
            var f = Find();
            if (f == null) return "kein FieldController";
            LastResult = "läuft";
            f.StartCoroutine(CaptureRoutine(path, width, height));
            return "gestartet";
        }

        static System.Collections.IEnumerator CaptureRoutine(string path, int width, int height)
        {
            yield return null;
            yield return new WaitForEndOfFrame();
            LastResult = Capture(path, width, height);
        }

        // Rendert die Hauptkamera (volles Rechteck) in eine RenderTexture, schreibt PNG (Alpha 255) und liefert "Mittel R,G,B".
        public static string Capture(string path, int width = 1280, int height = 720)
        {
            var cam = Camera.main;
            if (cam == null) return "keine Kamera";
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            var rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            var oldRt = cam.targetTexture; var oldRect = cam.rect;
            cam.rect = new Rect(0, 0, 1, 1); cam.targetTexture = rt;
            var sw = System.Diagnostics.Stopwatch.StartNew();
            cam.Render();
            cam.targetTexture = oldRt; cam.rect = oldRect;
            var prev = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, width, height), 0, 0); tex.Apply();
            RenderTexture.active = prev;
            var px = tex.GetPixels32();
            long r = 0, g = 0, b = 0;
            for (var i = 0; i < px.Length; i++) { r += px[i].r; g += px[i].g; b += px[i].b; px[i].a = 255; }
            tex.SetPixels32(px); tex.Apply();
            File.WriteAllBytes(path, tex.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex);
            var n = px.Length;
            return "Mittel " + (r / n) + "," + (g / n) + "," + (b / n) + " " + width + "x" + height + " " + sw.ElapsedMilliseconds + " ms -> " + path;
        }
    }
}
