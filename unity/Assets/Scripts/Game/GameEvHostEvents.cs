using System.Collections.Generic;
using Xnu.EvScript;

namespace Xnu.Game
{
    // Erweiterung Spielkern Scheibe 2: Ereignisprotokoll für die Darstellung und Namenswörter aus Textlabels.
    public sealed partial class GameEvHost
    {
        public const int MaxEvents = 20000;

        // Ereignisse der Darstellung mit Dauer (nur wenn Record gesetzt ist); die Feldschicht bekommt dieselben Befehle über IFieldHost.RunVisual.
        public readonly List<HostEvent> Events = new List<HostEvent>();
        public int EventCount { get; private set; }

        // Ereignisprotokoll; Rückgabe null, wenn nicht aufgezeichnet wird. _openEvent: das Ereignis des gerade laufenden Wartebefehls (bekommt seine Dauer beim Ende).
        HostEvent _openEvent;

        internal HostEvent Emit(EvCommandCall c, string name, int frames)
        {
            EventCount++;
            if (!Record || Events.Count >= MaxEvents) return null;
            var args = new int[c.ArgCount];
            var strs = new string[c.ArgCount];
            for (var i = 1; i <= c.ArgCount; i++)
            {
                args[i - 1] = c.Type(i) == 5 ? 0 : c.Int(i);
                strs[i - 1] = c.Type(i) == 5 ? c.Str(i) : null;
            }
            var e = new HostEvent { Id = c.Id, Name = name, Args = args, Strings = strs, DurationFrames = frames, Tick = EventCount };
            Events.Add(e);
            return e;
        }

        // Namenswort aus einem Textlabel (Datei, Label); fehlendes Label ergibt ein leeres Wort.
        internal void WordFromLabel(int slot, string msbt, string label)
        {
            if (slot < 0 || slot >= Xnu.Text.TagWordBuffer.Size) return;
            Session.Words.SetText(slot, LabelText(msbt, label));
        }
    }
}
