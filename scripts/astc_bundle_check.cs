// Prüft transkodierte Bundles in einem eigenen Batchmodus-Lauf (Wegwerfprojekt work/unity-astc-test, nicht unity/):
//   Unity -batchmode -projectpath work/unity-astc-test -executeMethod AstcBundleCheck.Run
//          -astcOriginal <Bundle mit BC> -astcTranscoded <Bundle mit ASTC> -astcReport <Ausgabedatei>
// Zählt Texturen je Format, summiert den Texturspeicher und vergleicht (GPU-Blit auf 128x128, PSNR) je Textur.
// Keine Spieldaten im Repo; der Bericht enthält nur Zahlen und Texturnamen.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;
using UnityEngine.Profiling;

public static class AstcBundleCheck
{
    static string Arg(string name)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
        return null;
    }

    class Entry { public string Name; public int W, H, Mips; public TextureFormat Format; public long Bytes; public byte[] Pixels; }

    static List<Entry> Load(string path, StringBuilder log, string label)
    {
        var bundle = AssetBundle.LoadFromFile(path);
        if (bundle == null) { log.AppendLine(label + ": Bundle lässt sich nicht laden"); return null; }
        var baseline = new HashSet<int>(Resources.FindObjectsOfTypeAll<Texture2D>().Select(x => x.GetInstanceID()));
        var loaded = bundle.LoadAllAssets();   // Prefabs/Materialien ziehen ihre Texturen mit; Texturen stehen selten selbst im Katalog
        log.AppendLine(label + ": Katalogeinträge " + bundle.GetAllAssetNames().Length + ", geladene Assets " + loaded.Length);
        var found = Resources.FindObjectsOfTypeAll<Texture2D>().Where(x => !baseline.Contains(x.GetInstanceID()));
        var list = new List<Entry>();
        var counts = new SortedDictionary<string, int>();
        long total = 0;
        foreach (var t in found.OrderBy(x => x.name).ThenBy(x => x.width).ThenBy(x => x.height))
        {
            long bytes = Profiler.GetRuntimeMemorySizeLong(t);
            var rt = RenderTexture.GetTemporary(128, 128, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            var prev = RenderTexture.active;
            Graphics.Blit(t, rt);
            RenderTexture.active = rt;
            var read = new Texture2D(128, 128, TextureFormat.RGBA32, false);
            read.ReadPixels(new Rect(0, 0, 128, 128), 0, 0);
            var px = read.GetRawTextureData();
            RenderTexture.active = prev;
            RenderTexture.ReleaseTemporary(rt);
            UnityEngine.Object.DestroyImmediate(read);
            var key = t.format.ToString();
            counts[key] = counts.TryGetValue(key, out var n) ? n + 1 : 1;
            total += bytes;
            list.Add(new Entry { Name = t.name, W = t.width, H = t.height, Mips = t.mipmapCount, Format = t.format, Bytes = bytes, Pixels = px });
        }
        log.AppendLine(label + ": " + list.Count + " Texturen, Laufzeitspeicher " + total + " Byte (" + (total / 1048576.0).ToString("F1") + " MiB)");
        foreach (var kv in counts) log.AppendLine("  " + kv.Key + ": " + kv.Value);
        log.AppendLine("  Mips: min " + (list.Count > 0 ? list.Min(e => e.Mips) : 0) + ", max " + (list.Count > 0 ? list.Max(e => e.Mips) : 0));
        bundle.Unload(true);
        Resources.UnloadUnusedAssets();
        return list;
    }

    public static void Run()
    {
        var log = new StringBuilder();
        string orig = Arg("-astcOriginal"), trans = Arg("-astcTranscoded"), report = Arg("-astcReport");
        int code = 0;
        try
        {
            log.AppendLine("Unity " + Application.unityVersion + ", Grafik: " + SystemInfo.graphicsDeviceType + ", ASTC unterstützt: "
                + SystemInfo.SupportsTextureFormat(TextureFormat.ASTC_6x6) + ", BC7: " + SystemInfo.SupportsTextureFormat(TextureFormat.BC7));
            var a = Load(orig, log, "Original");
            var b = Load(trans, log, "Transkodiert");
            if (a == null || b == null) code = 1;
            else
            {
                if (a.Count != b.Count) { log.AppendLine("FEHLER: Anzahl verschieden"); code = 1; }
                var psnrs = new List<double>();
                int mismatch = 0;
                for (int i = 0; i < Math.Min(a.Count, b.Count); i++)
                {
                    if (a[i].Name != b[i].Name || a[i].W != b[i].W || a[i].H != b[i].H || a[i].Mips != b[i].Mips) { mismatch++; continue; }
                    double se = 0;
                    for (int k = 0; k < a[i].Pixels.Length; k++) { double d = a[i].Pixels[k] - b[i].Pixels[k]; se += d * d; }
                    psnrs.Add(se == 0 ? 99.0 : 10 * Math.Log10(255.0 * 255.0 * a[i].Pixels.Length / se));
                }
                psnrs.Sort();
                log.AppendLine("Vergleich (GPU-Blit 128x128): " + psnrs.Count + " Paare, Abweichungen in Name/Größe/Mips: " + mismatch);
                if (psnrs.Count > 0)
                    log.AppendLine("PSNR dB: Minimum " + psnrs[0].ToString("F2") + ", Median " + psnrs[psnrs.Count / 2].ToString("F2")
                        + ", Mittel " + psnrs.Average().ToString("F2") + ", Maximum " + psnrs[psnrs.Count - 1].ToString("F2"));
                if (mismatch > 0) code = 1;
            }
        }
        catch (Exception e) { log.AppendLine("AUSNAHME: " + e); code = 1; }
        if (!string.IsNullOrEmpty(report)) File.WriteAllText(report, log.ToString());
        Debug.Log(log.ToString());
        EditorApplication.Exit(code);
    }
}
#endif
