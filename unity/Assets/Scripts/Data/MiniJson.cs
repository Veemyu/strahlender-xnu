using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Xnu.Data
{
    // Minimaler JSON-Parser ohne Abhängigkeiten (Unity liefert kein System.Text.Json).
    // Ergebnis: Dictionary<string, object>, List<object>, string, long, double, bool oder null.
    // Akzeptiert zusätzlich NaN/Infinity/-Infinity, die der Python-Exporter für Floats schreiben kann.
    public static class MiniJson
    {
        public static object Parse(string json)
        {
            if (json == null) throw new ArgumentNullException(nameof(json));
            var p = new Parser(json);
            p.SkipWhitespace();
            var value = p.ReadValue();
            p.SkipWhitespace();
            if (!p.AtEnd) throw p.Error("Unerwartete Zeichen nach dem JSON-Wert");
            return value;
        }

        sealed class Parser
        {
            readonly string _s;
            int _i;

            public Parser(string s)
            {
                _s = s;
                if (_s.Length > 0 && _s[0] == '\uFEFF') _i = 1;
            }

            public bool AtEnd => _i >= _s.Length;

            public FormatException Error(string msg) => new FormatException(msg + " (Position " + _i + ")");

            public void SkipWhitespace()
            {
                while (_i < _s.Length && (_s[_i] == ' ' || _s[_i] == '\t' || _s[_i] == '\n' || _s[_i] == '\r')) _i++;
            }

            public object ReadValue()
            {
                if (AtEnd) throw Error("Unerwartetes Ende");
                var c = _s[_i];
                switch (c)
                {
                    case '{': return ReadObject();
                    case '[': return ReadArray();
                    case '"': return ReadString();
                    case 't': Expect("true"); return true;
                    case 'f': Expect("false"); return false;
                    case 'n': Expect("null"); return null;
                    case 'N': Expect("NaN"); return double.NaN;
                    case 'I': Expect("Infinity"); return double.PositiveInfinity;
                    default: return ReadNumber();
                }
            }

            void Expect(string word)
            {
                if (string.CompareOrdinal(_s, _i, word, 0, word.Length) != 0) throw Error("Ungültiges Token");
                _i += word.Length;
            }

            Dictionary<string, object> ReadObject()
            {
                var dict = new Dictionary<string, object>();
                _i++;
                SkipWhitespace();
                if (Peek('}')) { _i++; return dict; }
                while (true)
                {
                    SkipWhitespace();
                    if (!Peek('"')) throw Error("Objektschlüssel erwartet");
                    var key = ReadString();
                    SkipWhitespace();
                    if (!Peek(':')) throw Error("':' erwartet");
                    _i++;
                    SkipWhitespace();
                    dict[key] = ReadValue();
                    SkipWhitespace();
                    if (Peek(',')) { _i++; continue; }
                    if (Peek('}')) { _i++; return dict; }
                    throw Error("',' oder '}' erwartet");
                }
            }

            List<object> ReadArray()
            {
                var list = new List<object>();
                _i++;
                SkipWhitespace();
                if (Peek(']')) { _i++; return list; }
                while (true)
                {
                    SkipWhitespace();
                    list.Add(ReadValue());
                    SkipWhitespace();
                    if (Peek(',')) { _i++; continue; }
                    if (Peek(']')) { _i++; return list; }
                    throw Error("',' oder ']' erwartet");
                }
            }

            bool Peek(char c) => _i < _s.Length && _s[_i] == c;

            string ReadString()
            {
                _i++;
                var sb = new StringBuilder();
                while (true)
                {
                    if (AtEnd) throw Error("String nicht abgeschlossen");
                    var c = _s[_i++];
                    if (c == '"') return sb.ToString();
                    if (c != '\\') { sb.Append(c); continue; }
                    if (AtEnd) throw Error("Ungültige Escape-Sequenz");
                    var e = _s[_i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (_i + 4 > _s.Length) throw Error("Ungültige \\u-Sequenz");
                            sb.Append((char)int.Parse(_s.Substring(_i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                            _i += 4;
                            break;
                        default: throw Error("Unbekannte Escape-Sequenz");
                    }
                }
            }

            object ReadNumber()
            {
                var start = _i;
                if (Peek('-'))
                {
                    _i++;
                    if (Peek('I')) { Expect("Infinity"); return double.NegativeInfinity; }
                }
                var isFloat = false;
                while (_i < _s.Length)
                {
                    var c = _s[_i];
                    if (c >= '0' && c <= '9') { _i++; continue; }
                    if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') { isFloat = true; _i++; continue; }
                    break;
                }
                var text = _s.Substring(start, _i - start);
                if (text.Length == 0 || text == "-") throw Error("Zahl erwartet");
                if (!isFloat && long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var l)) return l;
                if (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var d)) return d;
                throw Error("Ungültige Zahl '" + text + "'");
            }
        }
    }
}
