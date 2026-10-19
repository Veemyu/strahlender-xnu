using System;
using System.IO;

namespace Xnu.Core
{
    // Ort der vom Nutzer bereitgestellten Spieldaten (eigener Dump, nie im Repo).
    // Reihenfolge: Umgebungsvariable XNU_GAMEDATA, dann StreamingAssets/GameData (vorgepackter Build,
    // Stufe assets von scripts/build_all.sh), sonst persistentDataPath/GameData
    // (macOS: Application Support, iPadOS: Documents-Container der App).
    public static class GameDataPaths
    {
        public const string EnvVar = "XNU_GAMEDATA";
        public const string BundledFolder = "GameData";

        public static string Root
        {
            get
            {
                var env = Environment.GetEnvironmentVariable(EnvVar);
                if (!string.IsNullOrEmpty(env)) return env;
                var bundled = Path.Combine(UnityEngine.Application.streamingAssetsPath, BundledFolder);
                if (Directory.Exists(bundled)) return bundled;
                return Path.Combine(UnityEngine.Application.persistentDataPath, "GameData");
            }
        }

        // StreamingAssets des Dumps (enthält AssetAssistant, Audio, Movie).
        public static string StreamingAssets => Path.Combine(Root, "romfs", "Data", "StreamingAssets");

        public static string AssetAssistant => Path.Combine(StreamingAssets, "AssetAssistant");
    }
}
