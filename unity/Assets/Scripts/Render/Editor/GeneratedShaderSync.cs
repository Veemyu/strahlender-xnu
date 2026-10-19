using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using Xnu.Core;
using Xnu.Data;

namespace Xnu.Render.Editor
{
    // Bringt die erzeugten Shader (nicht im Repo) in das Unity-Projekt: kopiert die in variants.json mit Status "ok"
    // aufgeführten .shader-Dateien aus dem Shader-Ordner nach Assets/XnuGenerated/Resources/Shaders (gitignoriert)
    // und variants.json nach Assets/XnuGenerated/Resources/XnuGeneratedVariants.json.
    // Quelle: Umgebungsvariable XNU_SHADERS, sonst <XNU_GAMEDATA>/shaders/combined.
    // Dateien in Resources sind im Player-Build enthalten, dadurch findet Shader.Find sie auch im Player.
    public static class GeneratedShaderSync
    {
        public const string TargetRoot = "Assets/XnuGenerated/Resources";
        public const string ShaderFolder = TargetRoot + "/Shaders";
        public const string VariantsTarget = TargetRoot + "/" + GeneratedShaderLibrary.VariantsResource + ".json";

        public sealed class Result
        {
            public int Listed, Copied, Unchanged, Missing;
            public string Source;
            public override string ToString() =>
                "Quelle " + Source + ": " + Listed + " Varianten (ok), kopiert " + Copied + ", unverändert " + Unchanged + ", Datei fehlt " + Missing;
        }

        [MenuItem("Xnu/Render/Sync Generated Shaders")]
        public static void SyncMenu() => Debug.Log("[Render] " + Sync());

        // Quellordner der erzeugten Shader: XNU_SHADERS, sonst der erste Ordner mit variants.json unter <GameData>/shaders/combined_all,
        // <GameData>/shaders/combined, <GameData>/build/shaders (Ausgabe von scripts/shader_build.sh). null = keiner vorhanden.
        public static string FindSourceDirectory()
        {
            var env = Environment.GetEnvironmentVariable(GeneratedShaderLibrary.ShadersEnvVar);
            if (!string.IsNullOrEmpty(env)) return File.Exists(Path.Combine(env, "variants.json")) ? env : null;
            foreach (var d in new[] { Path.Combine(GameDataPaths.Root, "shaders", "combined_all"), Path.Combine(GameDataPaths.Root, "shaders", "combined"),
                                      Path.Combine(GameDataPaths.Root, "build", "shaders") })
                if (File.Exists(Path.Combine(d, "variants.json"))) return d;
            return null;
        }

        public static Result Sync(string sourceDirectory = null)
        {
            var src = sourceDirectory;
            if (string.IsNullOrEmpty(src)) src = FindSourceDirectory() ?? Path.Combine(GameDataPaths.Root, "shaders", "combined_all");
            var res = new Result { Source = src };
            var variants = Path.Combine(src, "variants.json");
            if (!File.Exists(variants)) throw new FileNotFoundException("variants.json fehlt (scripts/shader_build.sh ausführen)", variants);

            var json = File.ReadAllText(variants);
            foreach (var file in OkFiles(json))
            {
                res.Listed++;
                var from = Path.Combine(src, file);
                if (!File.Exists(from)) { res.Missing++; continue; }
                if (CopyIfChanged(from, Path.Combine(ProjectRoot(), ShaderFolder, file))) res.Copied++; else res.Unchanged++;
            }
            CopyIfChanged(variants, Path.Combine(ProjectRoot(), VariantsTarget));
            AssetDatabase.Refresh();
            return res;
        }

        // Dateinamen aller Varianten mit Status "ok" (reine Funktion, testbar).
        public static List<string> OkFiles(string variantsJson)
        {
            var list = new List<string>();
            var root = MiniJson.Parse(variantsJson) as Dictionary<string, object> ?? throw new FormatException("variants.json: Objekt erwartet");
            if (!root.TryGetValue("variants", out var vo) || !(vo is List<object> arr)) return list;
            foreach (var o in arr)
            {
                var d = o as Dictionary<string, object>;
                if (d == null || !d.TryGetValue("file", out var f) || !(f is string file)) continue;
                if (d.TryGetValue("status", out var st) && (st as string) != "ok") continue;
                if (d.TryGetValue("sub", out var sub) && Convert.ToInt32(sub) != 0) continue;
                list.Add(file);
            }
            return list;
        }

        static string ProjectRoot() => Path.GetDirectoryName(Application.dataPath);

        static bool CopyIfChanged(string from, string to)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(to));
            if (File.Exists(to) && new FileInfo(to).Length == new FileInfo(from).Length && File.ReadAllText(to) == File.ReadAllText(from)) return false;
            File.Copy(from, to, true);
            return true;
        }
    }
}
