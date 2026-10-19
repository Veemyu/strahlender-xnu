using System;
using System.IO;
using UnityEngine;
using Xnu.Core;

namespace Xnu.Render
{
    // Zugang zu den erzeugten Shadern (docs/shader-unity-integration.md, docs/feld-szene-2.md Kapitel 6).
    // Die Shader liegen NICHT im Repo: Der Editor-Menüpunkt "Xnu/Render/Sync Generated Shaders" kopiert sie nach
    // Assets/XnuGenerated/Resources (gitignoriert); Dateien in Resources sind im Build enthalten, Shader.Find findet sie dort.
    // Die Variantentabelle (variants.json) liegt als Resources/XnuGeneratedVariants.json daneben.
    public static class GeneratedShaderLibrary
    {
        public const string VariantsResource = "XnuGeneratedVariants";
        public const string ShadersEnvVar = "XNU_SHADERS";
        public const string MaterialsEnvVar = "XNU_MATERIALS";

        // Variantentabelle: Resources, sonst <XNU_SHADERS | GameData>/shaders/variants.json. null = nicht vorhanden.
        public static ShaderVariantIndex LoadIndex(out string source)
        {
            var ta = Resources.Load<TextAsset>(VariantsResource);
            if (ta != null) { source = "Resources/" + VariantsResource; return ShaderVariantIndex.FromJson(ta.text); }
            foreach (var dir in ShaderDirectories())
            {
                var p = Path.Combine(dir, "variants.json");
                if (!File.Exists(p)) continue;
                source = p;
                return ShaderVariantIndex.FromJson(File.ReadAllText(p));
            }
            source = null;
            return null;
        }

        static string[] ShaderDirectories()
        {
            var env = Environment.GetEnvironmentVariable(ShadersEnvVar);
            return string.IsNullOrEmpty(env)
                ? new[] { Path.Combine(GameDataPaths.Root, "shaders", "combined"), Path.Combine(GameDataPaths.Root, "shaders") }
                : new[] { env };
        }

        // Materialexporte (scripts/material_export.py): <XNU_MATERIALS | GameData/materials>/<Bundle mit __>.json
        public static string MaterialsDirectory
        {
            get
            {
                var env = Environment.GetEnvironmentVariable(MaterialsEnvVar);
                return !string.IsNullOrEmpty(env) ? env : Path.Combine(GameDataPaths.Root, "materials");
            }
        }

        public static string MaterialFileFor(string bundleName) =>
            Path.Combine(MaterialsDirectory, bundleName.Replace("/", "__") + ".json");

        // Zählt, wie viele erzeugte Shader der Index über Shader.Find tatsächlich liefert (Diagnose).
        public static int CountFindable(ShaderVariantIndex index, out int total)
        {
            var found = 0;
            total = 0;
            var seen = new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
            foreach (var s in index.ShaderNames)
                foreach (var pass in index.Passes(s))
                    foreach (var v in index.Variants(s, pass))
                        if (seen.Add(v.UnityName)) { total++; if (Shader.Find(v.UnityName) != null) found++; }
            return found;
        }
    }
}
