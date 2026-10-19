using System;
using System.Collections.Generic;
using System.Globalization;

namespace Xnu.Text
{
    // Laufzeitwert für einen Platzhalter (WORD_PARAM_ARRAY_SIZE = 19 Plätze im Original, TagWordBuffer).
    public sealed class TagWord
    {
        public string Text { get; set; } = "";
        // Zahl für Zahlen-Platzhalter (TagPattern.Digit).
        public long Number { get; set; }
        // 1 = Einzahl, sonst Mehrzahl.
        public int Count { get; set; } = 1;
        // Grammatisches Geschlecht des Wortes: 0 maskulin, 1 feminin, 2 neutral (GenderID).
        public int Gender { get; set; }
    }

    public sealed class TagWordBuffer
    {
        public const int Size = 19;

        readonly TagWord[] _slots = new TagWord[Size];

        // Geschlechter der Laufzeitquellen, auf die Grammatik-Platzhalter mit TagParameterRef verweisen.
        public int UserGender { get; set; }
        public int TvGender { get; set; }
        public int UserPartyGender { get; set; }

        public void Set(int slot, TagWord word)
        {
            Check(slot);
            _slots[slot] = word;
        }

        public void SetText(int slot, string text) => Set(slot, new TagWord { Text = text ?? "" });

        public void SetNumber(int slot, long number) => Set(slot, new TagWord { Number = number });

        public TagWord Get(int slot)
        {
            Check(slot);
            return _slots[slot];
        }

        public bool IsSet(int slot)
        {
            Check(slot);
            return _slots[slot] != null;
        }

        public void Clear() => Array.Clear(_slots, 0, _slots.Length);

        static void Check(int slot)
        {
            if (slot < 0 || slot >= Size) throw new ArgumentOutOfRangeException(nameof(slot));
        }
    }

    // Ersetzt einen Platzhalter durch Text.
    public interface ITagFormatter
    {
        string Format(MsbtTag tag, TagWordBuffer buffer);
    }

    // Gerüst mit den belegten Grundregeln. Was hier steht, ist Prüfstufe [P]/[A] (docs/lokalisierung.md, Abschnitt 6):
    //  - Namens-Platzhalter und Wort-Platzhalter: Text aus dem Puffer.
    //  - Zahlen: ganze Zahl, Tausendertrenner nach TagParameter (2 Komma, 3 Punkt, 4 Leerzeichen, 5 schmales Leerzeichen),
    //    keine Auffüllung (Annahme).
    //  - Grammatik-Wörter: Auswahl nach Geschlecht der Quelle (Annahme), sonst nach Einzahl/Mehrzahl.
    //  - Alles andere: sichtbarer Platzhalter "{gruppe:id}", damit fehlende Laufzeitwerte auffallen.
    public sealed class DefaultTagFormatter : ITagFormatter
    {
        public const char QuarterSpace = '\u202F';

        public string Format(MsbtTag tag, TagWordBuffer buffer)
        {
            if (tag == null) throw new ArgumentNullException(nameof(tag));
            if (buffer == null) throw new ArgumentNullException(nameof(buffer));
            switch (tag.Pattern)
            {
                case TagPattern.Word:
                    return WordText(tag, buffer);
                case TagPattern.Digit:
                    return DigitText(tag, buffer);
                case TagPattern.GrammarWord:
                    return GrammarText(tag, buffer);
                default:
                    return Missing(tag);
            }
        }

        static string WordText(MsbtTag tag, TagWordBuffer buffer)
        {
            var w = SlotOrNull(tag, buffer);
            return w == null ? Missing(tag) : w.Text;
        }

        static string DigitText(MsbtTag tag, TagWordBuffer buffer)
        {
            var w = SlotOrNull(tag, buffer);
            if (w == null) return Missing(tag);
            var digits = Math.Abs(w.Number).ToString(CultureInfo.InvariantCulture);
            var sep = Separator(tag.Parameter);
            if (sep.Length > 0 && digits.Length > 3)
            {
                var sb = new System.Text.StringBuilder();
                var first = digits.Length % 3;
                if (first > 0) sb.Append(digits, 0, first);
                for (var i = first; i < digits.Length; i += 3)
                {
                    if (sb.Length > 0) sb.Append(sep);
                    sb.Append(digits, i, 3);
                }
                digits = sb.ToString();
            }
            return w.Number < 0 ? "-" + digits : digits;
        }

        static string Separator(int parameter)
        {
            switch (parameter)
            {
                case 2: return ",";
                case 3: return ".";
                case 4: return " ";
                case 5: return QuarterSpace.ToString();
                default: return "";
            }
        }

        static string GrammarText(MsbtTag tag, TagWordBuffer buffer)
        {
            if (tag.Words == null || tag.Words.Length == 0) return Missing(tag);
            int pick;
            switch (tag.Parameter)
            {
                case TagParameterRef.User: pick = buffer.UserGender; break;
                case TagParameterRef.Tv: pick = buffer.TvGender; break;
                case TagParameterRef.UserParty: pick = buffer.UserPartyGender; break;
                default:
                    var w = SlotOrNull(tag, buffer);
                    pick = w == null || w.Count == 1 ? 0 : 1;
                    break;
            }
            if (pick < 0) pick = 0;
            return tag.Words[Math.Min(pick, tag.Words.Length - 1)];
        }

        static TagWord SlotOrNull(MsbtTag tag, TagWordBuffer buffer) =>
            tag.Index >= 0 && tag.Index < TagWordBuffer.Size ? buffer.Get(tag.Index) : null;

        static string Missing(MsbtTag tag) => "{" + tag.GroupId + ":" + tag.TagId + "}";
    }
}
