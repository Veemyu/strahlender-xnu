using System;
using System.IO;

namespace Xnu.Boot
{
    // Startoptionen des Players (reine Logik, ohne Unity-Aufrufe, damit testbar).
    // Startszene: Kommandozeile "-xnuScene <Name>" vor der Umgebungsvariable XNU_START_SCENE; leer = Menü anzeigen.
    public static class BootOptions
    {
        public const string SceneArg = "-xnuScene";
        public const string SceneEnv = "XNU_START_SCENE";

        public static string ResolveStartScene(string[] args, Func<string, string> getEnv)
        {
            if (args != null)
                for (var i = 0; i < args.Length - 1; i++)
                    if (args[i] == SceneArg && !string.IsNullOrWhiteSpace(args[i + 1])) return args[i + 1].Trim();
            var env = getEnv?.Invoke(SceneEnv);
            return string.IsNullOrWhiteSpace(env) ? null : env.Trim();
        }

        // Szenenname aus einem Build-Pfad ("Assets/Scenes/FieldTest2.unity" -> "FieldTest2").
        public static string SceneName(string path) => Path.GetFileNameWithoutExtension(path ?? "");

        // Passende Szene (Name ohne Beachtung der Groß-/Kleinschreibung) aus den Pfaden der Build-Szenen; sonst null.
        public static string FindScenePath(string[] scenePaths, string wanted)
        {
            if (scenePaths == null || string.IsNullOrEmpty(wanted)) return null;
            foreach (var p in scenePaths)
                if (string.Equals(SceneName(p), wanted, StringComparison.OrdinalIgnoreCase)) return p;
            return null;
        }
    }
}
