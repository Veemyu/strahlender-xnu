using System.Collections.Generic;
using System.Text;
using Xnu.Text;

namespace Xnu.Game
{
    // Textfenster als Datenmodell (ohne Darstellung). Seiten ergeben sich aus der zusammengesetzten Nachricht:
    // NewLine/ScrollLine bleiben auf der Seite, ScrollPage und das Ende beenden sie [A: Seitenwechsel ist ScrollPage, Wait zählt nicht].
    // Weiter mit Confirm (oder Cancel); nach der letzten Seite ist das Fenster fertig.
    public sealed class DialogModel
    {
        readonly List<string> _pages = new List<string>();
        int _index;

        public bool IsOpen { get; private set; }
        public bool IsFinished { get; private set; }
        public string Msbt { get; private set; } = "";
        public string Label { get; private set; } = "";
        public bool MissingLabel { get; private set; }
        public int PageCount => _pages.Count;
        public int PageIndex => _index;
        public string CurrentPage => _index < _pages.Count ? _pages[_index] : "";
        public int ShownPages { get; private set; }

        public void Open(string msbt, string label, ComposedMessage message)
        {
            Msbt = msbt;
            Label = label;
            _pages.Clear();
            _index = 0;
            IsOpen = true;
            IsFinished = false;
            MissingLabel = message == null;
            if (message == null)
            {
                _pages.Add("");
            }
            else
            {
                var sb = new StringBuilder();
                for (var i = 0; i < message.Lines.Count; i++)
                {
                    var l = message.Lines[i];
                    sb.Append(l.Text);
                    var last = i == message.Lines.Count - 1;
                    if (last || l.EndEvent == MessageEvent.ScrollPage)
                    {
                        _pages.Add(sb.ToString());
                        sb.Clear();
                    }
                    else if (l.EndEvent == MessageEvent.NewLine || l.EndEvent == MessageEvent.ScrollLine)
                    {
                        sb.Append('\n');
                    }
                }
                if (_pages.Count == 0) _pages.Add("");
            }
            ShownPages++;
        }

        public void Feed(GameInput input)
        {
            if (!IsOpen || IsFinished) return;
            if (!input.Confirm && !input.Cancel) return;
            _index++;
            if (_index >= _pages.Count) IsFinished = true;
        }

        // Die Darstellung (Xnu.UI.TextboxFlow) hat alle Seiten gezeigt und bestätigt: das Fenster gilt als fertig.
        public void ForceFinish()
        {
            if (IsOpen) IsFinished = true;
        }

        // TALK_CLOSE: Fenster schließen.
        public void Close()
        {
            IsOpen = false;
            IsFinished = false;
            _pages.Clear();
        }
    }

    // Auswahlfenster (Ja/Nein und eigene Fenster): Auf/Ab bewegt, Confirm wählt, Cancel wählt die Abbruchzeile.
    public sealed class ChoiceModel
    {
        public IReadOnlyList<string> Labels { get; private set; } = new List<string>();
        public int Cursor { get; private set; }
        public int Result { get; private set; } = -1;
        public bool IsOpen { get; private set; }
        public int CancelIndex { get; private set; }

        public void Open(IReadOnlyList<string> labels, int startIndex, int cancelIndex)
        {
            Labels = labels;
            Cursor = startIndex < 0 || startIndex >= labels.Count ? 0 : startIndex;
            CancelIndex = cancelIndex;
            Result = -1;
            IsOpen = true;
        }

        public void Feed(GameInput input)
        {
            if (!IsOpen || Result >= 0) return;
            var n = Labels.Count;
            if (n == 0) { Result = 0; return; }
            if (input.Down) Cursor = (Cursor + 1) % n;
            if (input.Up) Cursor = (Cursor + n - 1) % n;
            if (input.Confirm) Result = Cursor;
            else if (input.Cancel) Result = CancelIndex < 0 || CancelIndex >= n ? n - 1 : CancelIndex;
        }

        // Die Darstellung hat gewählt (Index der Zeile).
        public void Force(int index)
        {
            if (!IsOpen || Result >= 0 || Labels.Count == 0) return;
            Cursor = index < 0 || index >= Labels.Count ? 0 : index;
            Result = Cursor;
        }

        public void Close()
        {
            IsOpen = false;
            Result = -1;
        }
    }
}
