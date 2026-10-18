using System;

namespace Xnu.Boot
{
    // Normalisierung logischer Asset-Namen. Der Katalog führt Asset-Pfade kleingeschrieben
    // als "assets/<pfad>.<ext>"; der logische Schlüssel lässt "assets/" und die Endung weg
    // (z. B. "scriptableobjects/gamesettings").
    public static class AssetKey
    {
        const string AssetsPrefix = "assets/";

        public static string NormalizePath(string path)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            var p = path.Trim().Replace('\\', '/').ToLowerInvariant();
            while (p.StartsWith("./", StringComparison.Ordinal)) p = p.Substring(2);
            return p.TrimStart('/');
        }

        public static string StripAssetsPrefix(string normalized) =>
            normalized.StartsWith(AssetsPrefix, StringComparison.Ordinal) ? normalized.Substring(AssetsPrefix.Length) : normalized;

        public static string StripExtension(string normalized)
        {
            var slash = normalized.LastIndexOf('/');
            var dot = normalized.LastIndexOf('.');
            return dot > slash + 1 ? normalized.Substring(0, dot) : normalized;
        }

        // Asset-Pfad aus dem Katalog -> logischer Schlüssel.
        public static string ToLogicalKey(string assetPath) =>
            StripExtension(StripAssetsPrefix(NormalizePath(assetPath)));
    }
}
