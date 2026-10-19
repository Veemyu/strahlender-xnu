using System.Text;
using Xnu.Text;

namespace Xnu.UI
{
    // Baut aus einer einfachen Zeichenkette eine ComposedMessage: '\n' Zeilenumbruch, '\v' Zeile scrollen,
    // '\f' Seite scrollen (alle mit Tastenwarten außer dem Umbruch). Das Ende ist immer End.
    public static class PlainMessage
    {
        public static ComposedMessage Parse(string text)
        {
            var msg = new ComposedMessage();
            var sb = new StringBuilder();
            foreach (var ch in text ?? "")
            {
                MessageEvent ev;
                switch (ch)
                {
                    case '\n': ev = MessageEvent.NewLine; break;
                    case '\v': ev = MessageEvent.ScrollLine; break;
                    case '\f': ev = MessageEvent.ScrollPage; break;
                    default: sb.Append(ch); continue;
                }
                msg.Lines.Add(new ComposedLine { Text = sb.ToString(), EndEvent = ev });
                sb.Clear();
            }
            msg.Lines.Add(new ComposedLine { Text = sb.ToString(), EndEvent = MessageEvent.End });
            return msg;
        }
    }
}
