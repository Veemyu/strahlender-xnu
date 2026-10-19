using System;
using System.Text.RegularExpressions;

namespace Xnu.Core
{
    // Setzt Boolesche Schlüssel in einer Info.plist (XML-Text, oberstes Wörterbuch). Reiner Text, ohne Unity/Xcode-API,
    // damit der Build-Schritt (IosPostBuild) und die EditMode-Tests dieselbe Logik nutzen.
    public static class InfoPlistPatch
    {
        // Dateien-App/Finder zeigen den Documents-Ordner der App (iPadOS: dort liegen Saves/main/SaveData.bin und Import/).
        public const string FileSharingKey = "UIFileSharingEnabled";
        public const string OpenInPlaceKey = "LSSupportsOpeningDocumentsInPlace";

        public static readonly string[] DocumentSharingKeys = { FileSharingKey, OpenInPlaceKey };

        public static string SetBool(string plistXml, string key, bool value)
        {
            if (plistXml == null) throw new ArgumentNullException(nameof(plistXml));
            if (string.IsNullOrEmpty(key) || key.IndexOfAny(new[] { '<', '>', '&' }) >= 0) throw new ArgumentException("ungültiger Schlüssel", nameof(key));
            var literal = value ? "<true/>" : "<false/>";
            var keyXml = "<key>" + key + "</key>";

            var existing = new Regex("(" + Regex.Escape(keyXml) + @"\s*)<(?:true|false)\s*/>");
            if (existing.IsMatch(plistXml)) return existing.Replace(plistXml, "${1}" + literal, 1);
            if (plistXml.Contains(keyXml)) throw new FormatException("Schlüssel " + key + " existiert mit einem Wert, der kein Boolean ist");

            // Vor dem schließenden </dict> des obersten Wörterbuchs (letztes </dict> vor </plist>) einfügen.
            var end = Regex.Match(plistXml, @"</dict>\s*</plist>\s*$");
            if (!end.Success) throw new FormatException("Info.plist hat kein oberstes Wörterbuch");
            return plistXml.Insert(end.Index, "\t" + keyXml + "\n\t" + literal + "\n");
        }

        public static string EnableDocumentSharing(string plistXml)
        {
            foreach (var k in DocumentSharingKeys) plistXml = SetBool(plistXml, k, true);
            return plistXml;
        }

        public static bool HasBool(string plistXml, string key, bool value) =>
            Regex.IsMatch(plistXml ?? "", Regex.Escape("<key>" + key + "</key>") + @"\s*<" + (value ? "true" : "false") + @"\s*/>");
    }
}
