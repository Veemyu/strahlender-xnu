using System;
using System.Collections.Generic;
using System.Text;

namespace Xnu.Text
{
    // TextMeshPro-Rich-Text im Nachrichtentext (die Daten enthalten color, size, pos und line-indent; Rest vorsorglich).
    public static class RichText
    {
        static readonly HashSet<string> Known = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "color", "size", "pos", "line-indent", "font", "b", "i", "u", "s", "sub", "sup", "sprite", "space", "align",
            "cspace", "voffset", "alpha", "nobr", "indent", "margin", "mark", "style", "width",
        };

        // Länge des Markups, das bei Index i beginnt, sonst 0.
        public static int MarkupLength(string s, int i)
        {
            if (s == null || i < 0 || i >= s.Length || s[i] != '<') return 0;
            var j = i + 1;
            if (j < s.Length && s[j] == '/') j++;
            var nameStart = j;
            while (j < s.Length && (char.IsLetter(s[j]) || s[j] == '-')) j++;
            if (j == nameStart) return 0;
            if (!Known.Contains(s.Substring(nameStart, j - nameStart))) return 0;
            while (j < s.Length && s[j] != '>')
            {
                if (s[j] == '<') return 0;
                j++;
            }
            return j < s.Length ? j - i + 1 : 0;
        }

        // Text ohne Markup.
        public static string Strip(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new StringBuilder(s.Length);
            for (var i = 0; i < s.Length;)
            {
                var m = MarkupLength(s, i);
                if (m > 0) { i += m; continue; }
                sb.Append(s[i]);
                i++;
            }
            return sb.ToString();
        }

        // Anzahl sichtbarer Zeichen (Surrogatpaare zählen einfach).
        public static int CountGlyphs(string s)
        {
            if (string.IsNullOrEmpty(s)) return 0;
            var n = 0;
            for (var i = 0; i < s.Length;)
            {
                var m = MarkupLength(s, i);
                if (m > 0) { i += m; continue; }
                if (char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1])) i++;
                n++;
                i++;
            }
            return n;
        }

        // Präfix mit den ersten count sichtbaren Zeichen; Markup vor und direkt nach dem letzten Zeichen bleibt erhalten.
        public static string TakeGlyphs(string s, int count)
        {
            if (string.IsNullOrEmpty(s) || count < 0) return "";
            var sb = new StringBuilder();
            var seen = 0;
            var i = 0;
            while (i < s.Length)
            {
                var m = MarkupLength(s, i);
                if (m > 0)
                {
                    sb.Append(s, i, m);
                    i += m;
                    continue;
                }
                if (seen >= count) break;
                var len = char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]) ? 2 : 1;
                sb.Append(s, i, len);
                i += len;
                seen++;
            }
            return sb.ToString();
        }
    }
}
