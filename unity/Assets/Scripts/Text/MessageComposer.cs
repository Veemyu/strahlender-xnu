using System;
using System.Collections.Generic;
using System.Text;

namespace Xnu.Text
{
    // Eine Zeile (genauer: ein Abschnitt zwischen zwei Ereignissen) der aufgelösten Nachricht.
    public sealed class ComposedLine
    {
        // Text mit Rich-Text-Markup, Platzhalter sind bereits ersetzt.
        public string Text { get; set; } = "";
        // Ereignis am Ende des Abschnitts.
        public MessageEvent EndEvent { get; set; }
        // Wert des Ereignisses: Wartezeit in Sekunden (Wait) oder Rückrufnummer (CallBack).
        public float EventValue { get; set; }
        // Summe der Textbreiten (strWidth) der festen Textstücke ohne Platzhalter, in Pixeln der Originalschrift.
        public float StaticWidth { get; set; }
    }

    public sealed class ComposedMessage
    {
        public List<ComposedLine> Lines { get; } = new List<ComposedLine>();
        // Platzhalter, deren Position im Label nicht existierte (Datenfehler).
        public int InvalidTagReferences { get; set; }

        // Text als eine Zeichenkette: NewLine und ScrollLine werden zu '\n', ScrollPage zu '\f', die übrigen Ereignisse fügen nichts ein.
        public string FlatText
        {
            get
            {
                var sb = new StringBuilder();
                for (var i = 0; i < Lines.Count; i++)
                {
                    sb.Append(Lines[i].Text);
                    if (i == Lines.Count - 1) break;
                    switch (Lines[i].EndEvent)
                    {
                        case MessageEvent.NewLine:
                        case MessageEvent.ScrollLine: sb.Append('\n'); break;
                        case MessageEvent.ScrollPage: sb.Append('\f'); break;
                    }
                }
                return sb.ToString();
            }
        }
    }

    // Baut aus einem Label die Abschnittsliste (Text, Ereignis) mit ersetzten Platzhaltern. Entspricht in der Wirkung
    // MessageFormatter.Format des Originals (aus Daten und Signaturen abgeleitet, Prüfstufe [P]).
    public sealed class MessageComposer
    {
        readonly ITagFormatter _formatter;

        public MessageComposer(ITagFormatter formatter = null)
        {
            _formatter = formatter ?? new DefaultTagFormatter();
        }

        public ComposedMessage Compose(MsbtLabel label, TagWordBuffer buffer = null)
        {
            if (label == null) throw new ArgumentNullException(nameof(label));
            buffer = buffer ?? new TagWordBuffer();
            var result = new ComposedMessage();
            var sb = new StringBuilder();
            var width = 0f;
            var closedWithEnd = false;

            foreach (var w in label.Words)
            {
                closedWithEnd = false;
                switch (w.Pattern)
                {
                    case WordPattern.WordTag:
                        if (w.TagIndex >= 0 && w.TagIndex < label.Tags.Length) sb.Append(_formatter.Format(label.Tags[w.TagIndex], buffer));
                        else result.InvalidTagReferences++;
                        break;
                    default:
                        // Str, Event, Font-/Farb-/Größen-/Positions-Markup und Sprite-Zeichen: Text unverändert übernehmen.
                        sb.Append(w.Text);
                        if ((w.Pattern == WordPattern.Str || w.Pattern == WordPattern.Event) && w.Width > 0) width += w.Width;
                        break;
                }

                if (w.Event == MessageEvent.None) continue;
                result.Lines.Add(new ComposedLine { Text = sb.ToString(), EndEvent = w.Event, EventValue = w.TagValue, StaticWidth = width });
                sb.Clear();
                width = 0;
                closedWithEnd = w.Event == MessageEvent.End;
            }

            // Text ohne abschließendes Ereignis (oder ein leeres Label) bekommt ein End.
            if (sb.Length > 0 || (!closedWithEnd && result.Lines.Count == 0))
                result.Lines.Add(new ComposedLine { Text = sb.ToString(), EndEvent = MessageEvent.End, StaticWidth = width });
            return result;
        }
    }
}
