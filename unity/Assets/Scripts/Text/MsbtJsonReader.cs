using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.Text
{
    // Liest den JSON-Export der MsbtData-Objekte (scripts/masterdata_export.py --messages):
    // {"class":"MsbtData","instances":[{"name":..., "data":{"hash","langID","isResident","isKanji","labelDataArray":[...]}}]}.
    // Fehlende optionale Felder bekommen Standardwerte; falsche Typen und eine falsche Klasse werfen FormatException.
    public static class MsbtJsonReader
    {
        public static List<MsbtFile> Parse(string json)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object>;
            if (root == null) throw new FormatException("Wurzel ist kein JSON-Objekt");
            var cls = Str(root, "class", "");
            if (cls != "MsbtData") throw new FormatException("Klasse '" + cls + "' statt 'MsbtData'");

            var files = new List<MsbtFile>();
            foreach (var inst in Objects(root, "instances"))
            {
                var data = Obj(inst, "data");
                var file = new MsbtFile
                {
                    Name = Str(inst, "name", ""),
                    Hash = Int(data, "hash", 0),
                    LanguageId = Int(data, "langID", 0),
                    IsResident = Bool(data, "isResident"),
                    IsKanji = Bool(data, "isKanji"),
                };
                foreach (var l in Objects(data, "labelDataArray")) file.Labels.Add(ReadLabel(l));
                files.Add(file);
            }
            return files;
        }

        static MsbtLabel ReadLabel(Dictionary<string, object> l)
        {
            var label = new MsbtLabel
            {
                LabelIndex = Int(l, "labelIndex", 0),
                ArrayIndex = Int(l, "arrayIndex", 0),
                Name = Str(l, "labelName", ""),
            };
            if (l.TryGetValue("styleInfo", out var si) && si is Dictionary<string, object> s)
            {
                label.Style = new MsbtStyle
                {
                    StyleIndex = Int(s, "styleIndex", 0),
                    ColorIndex = Int(s, "colorIndex", -1),
                    FontSize = Int(s, "fontSize", 0),
                    MaxWidth = Int(s, "maxWidth", 0),
                    ControlId = Int(s, "controlID", 0),
                };
            }
            label.Attributes = IntArray(l, "attributeValueArray");

            var tags = new List<MsbtTag>();
            foreach (var t in Objects(l, "tagDataArray"))
            {
                tags.Add(new MsbtTag
                {
                    Index = Int(t, "tagIndex", 0),
                    GroupId = Int(t, "groupID", 0),
                    TagId = Int(t, "tagID", 0),
                    Pattern = Int(t, "tagPatternID", 0),
                    ForceArticle = Int(t, "forceArticle", 0),
                    Parameter = Int(t, "tagParameter", 0),
                    Words = StrArray(t, "tagWordArray"),
                    ForceGrm = Int(t, "forceGrmID", 0),
                });
            }
            label.Tags = tags.ToArray();

            var words = new List<MsbtWord>();
            foreach (var w in Objects(l, "wordDataArray"))
            {
                words.Add(new MsbtWord
                {
                    Pattern = Int(w, "patternID", 0),
                    Event = ReadEvent(Int(w, "eventID", 0)),
                    TagIndex = Int(w, "tagIndex", -1),
                    TagValue = (float)Dbl(w, "tagValue", 0),
                    Text = Str(w, "str", ""),
                    Width = (float)Dbl(w, "strWidth", -1),
                });
            }
            label.Words = words.ToArray();
            return label;
        }

        // Werte außerhalb von 0..7 (z. B. -1 als "kein Ereignis") gelten als None.
        static MessageEvent ReadEvent(int id) => id >= 0 && id <= (int)MessageEvent.End ? (MessageEvent)id : MessageEvent.None;

        static List<Dictionary<string, object>> Objects(Dictionary<string, object> d, string key)
        {
            var result = new List<Dictionary<string, object>>();
            if (!d.TryGetValue(key, out var v) || v == null) return result;
            var list = v as List<object>;
            if (list == null) throw new FormatException("'" + key + "' ist keine Liste");
            foreach (var item in list)
            {
                var o = item as Dictionary<string, object>;
                if (o == null) throw new FormatException("Eintrag in '" + key + "' ist kein Objekt");
                result.Add(o);
            }
            return result;
        }

        static Dictionary<string, object> Obj(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || !(v is Dictionary<string, object> o)) throw new FormatException("'" + key + "' fehlt oder ist kein Objekt");
            return o;
        }

        static int Int(Dictionary<string, object> d, string key, int fallback)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is long l) return checked((int)l);
            if (v is double x) return (int)x;
            if (v is bool b) return b ? 1 : 0;
            throw new FormatException("'" + key + "' ist keine Zahl");
        }

        static double Dbl(Dictionary<string, object> d, string key, double fallback)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is long l) return l;
            if (v is double x) return x;
            throw new FormatException("'" + key + "' ist keine Zahl");
        }

        static bool Bool(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return false;
            if (v is bool b) return b;
            if (v is long l) return l != 0;
            throw new FormatException("'" + key + "' ist kein Wahrheitswert");
        }

        static string Str(Dictionary<string, object> d, string key, string fallback)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is string s) return s;
            throw new FormatException("'" + key + "' ist kein Text");
        }

        static int[] IntArray(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return new int[0];
            var list = v as List<object>;
            if (list == null) throw new FormatException("'" + key + "' ist keine Liste");
            var r = new int[list.Count];
            for (var i = 0; i < r.Length; i++)
            {
                if (list[i] is long l) r[i] = checked((int)l);
                else if (list[i] is double x) r[i] = (int)x;
                else throw new FormatException("'" + key + "' enthält Nicht-Zahlen");
            }
            return r;
        }

        static string[] StrArray(Dictionary<string, object> d, string key)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return new string[0];
            var list = v as List<object>;
            if (list == null) throw new FormatException("'" + key + "' ist keine Liste");
            var r = new string[list.Count];
            for (var i = 0; i < r.Length; i++) r[i] = list[i] as string ?? "";
            return r;
        }
    }
}
