using System;
using System.Collections.Generic;

namespace Xnu.Text
{
    // Sprach-IDs des Originals (Dpr.Message.MessageEnumData.MsgLangId). Die Werte 6 und 0 sind unbelegt.
    public enum MessageLanguage
    {
        Jpn = 1,
        Usa = 2,
        Fra = 3,
        Ita = 4,
        Deu = 5,
        Esp = 7,
        Kor = 8,
        Sch = 9,
        Tch = 10,
    }

    // Textgeschwindigkeit (MSGSPEED des Originals, Einstellung "MessageSpeed"): langsam, normal, schnell.
    public enum MessageSpeed
    {
        Slow = 0,
        Normal = 1,
        Fast = 2,
    }

    // WordData.patternID: Art eines Wortes in der Wortliste eines Labels.
    public static class WordPattern
    {
        public const int Str = 0;
        public const int FontTag = 1;
        public const int ColorTag = 2;
        public const int SizeTag = 3;
        public const int CtrlTag = 4;
        public const int WordTag = 5;
        public const int SpriteFont = 6;
        public const int Event = 7;
    }

    // WordData.eventID: Ereignis nach dem Text des Wortes (MsgEventID).
    public enum MessageEvent
    {
        None = 0,
        NewLine = 1,
        Wait = 2,
        ScrollPage = 3,
        ScrollLine = 4,
        CallBack = 5,
        GuidIcon = 6,
        End = 7,
    }

    // TagData.tagPatternID.
    public static class TagPattern
    {
        public const int Word = 0;
        public const int Digit = 1;
        public const int Conversion = 2;
        public const int RichText = 3;
        public const int Grammar = 4;
        public const int GrammarWord = 5;
        public const int ControlDesign = 6;
        public const int ControlMessage = 7;
        public const int SpriteFont = 8;
    }

    // TagData.groupID (Auswahl; weitere Werte bleiben als Zahl erhalten).
    public static class TagGroup
    {
        public const int System = 0;
        public const int Name = 1;
        public const int Digit = 2;
        public const int Grm = 16;
        public const int English = 19;
        public const int French = 20;
        public const int Italian = 21;
        public const int German = 22;
        public const int Spanish = 23;
        public const int Korean = 25;
        public const int SimpChinese = 26;
        public const int Character1 = 50;
        public const int Character2 = 51;
        public const int Ctrl1 = 189;
        public const int Ctrl2 = 190;
    }

    // Sonderwerte von TagData.tagParameter bei Grammatik-Wörtern: Verweis auf das Geschlecht einer Laufzeitquelle.
    public static class TagParameterRef
    {
        public const int UserParty = 253;
        public const int Tv = 254;
        public const int User = 255;
    }

    // LabelData.styleInfo: Darstellungsstil des Labels.
    public sealed class MsbtStyle
    {
        public int StyleIndex { get; set; }
        public int ColorIndex { get; set; } = -1;
        public int FontSize { get; set; }
        public int MaxWidth { get; set; }
        public int ControlId { get; set; }
    }

    // LabelData.tagDataArray: Platzhalter. Index = Platz im Laufzeitpuffer (0..18), nicht die Position im Array.
    public sealed class MsbtTag
    {
        public int Index { get; set; }
        public int GroupId { get; set; }
        public int TagId { get; set; }
        public int Pattern { get; set; }
        public int ForceArticle { get; set; }
        public int Parameter { get; set; }
        public string[] Words { get; set; } = new string[0];
        public int ForceGrm { get; set; }
    }

    // LabelData.wordDataArray: Textstück, Markup, Platzhalter-Verweis oder Ereignis.
    public sealed class MsbtWord
    {
        public int Pattern { get; set; }
        public MessageEvent Event { get; set; }
        // Position in MsbtLabel.Tags (nur bei WordPattern.WordTag gültig, sonst -1).
        public int TagIndex { get; set; } = -1;
        public float TagValue { get; set; }
        public string Text { get; set; } = "";
        public float Width { get; set; } = -1f;
    }

    public sealed class MsbtLabel
    {
        public int LabelIndex { get; set; }
        public int ArrayIndex { get; set; }
        public string Name { get; set; } = "";
        public MsbtStyle Style { get; set; } = new MsbtStyle();
        public int[] Attributes { get; set; } = new int[0];
        public MsbtTag[] Tags { get; set; } = new MsbtTag[0];
        public MsbtWord[] Words { get; set; } = new MsbtWord[0];

        // Auffüll-Einträge ohne Name und Wörter (in den Daten zahlreich, z. B. 4.261 je Sprache); sie gehören zu keinem Label.
        public bool IsPadding => string.IsNullOrEmpty(Name) && Words.Length == 0;
    }

    // Eine Textdatei (Dpr.Message.MsbtData).
    public sealed class MsbtFile
    {
        Dictionary<string, MsbtLabel> _byName;
        Dictionary<int, MsbtLabel> _byIndex;

        public string Name { get; set; } = "";
        public int Hash { get; set; }
        public int LanguageId { get; set; }
        public bool IsResident { get; set; }
        public bool IsKanji { get; set; }
        public List<MsbtLabel> Labels { get; } = new List<MsbtLabel>();

        // Dateiname ohne Sprachpräfix (z. B. "ss_bag"); leer, wenn der Name kein bekanntes Präfix trägt.
        public string ShortName => MessageLanguages.TrySplitFileName(Name, out _, out _, out var shortName) ? shortName : Name;

        public int LabelCount
        {
            get
            {
                EnsureIndex();
                return _byName.Count;
            }
        }

        public bool TryGetLabel(string labelName, out MsbtLabel label)
        {
            EnsureIndex();
            if (labelName == null) { label = null; return false; }
            return _byName.TryGetValue(labelName, out label);
        }

        public bool TryGetLabel(int labelIndex, out MsbtLabel label)
        {
            EnsureIndex();
            return _byIndex.TryGetValue(labelIndex, out label);
        }

        void EnsureIndex()
        {
            if (_byName != null) return;
            var byName = new Dictionary<string, MsbtLabel>(StringComparer.Ordinal);
            var byIndex = new Dictionary<int, MsbtLabel>();
            foreach (var l in Labels)
            {
                if (l.IsPadding) continue;
                if (!string.IsNullOrEmpty(l.Name) && !byName.ContainsKey(l.Name)) byName.Add(l.Name, l);
                if (!byIndex.ContainsKey(l.LabelIndex)) byIndex.Add(l.LabelIndex, l);
            }
            _byIndex = byIndex;
            _byName = byName;
        }
    }
}
