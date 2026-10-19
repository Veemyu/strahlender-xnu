using System.Collections.Generic;
using Xnu.Data;
using Xnu.EvScript;

namespace Xnu.Game
{
    // Schnittstelle zur Feldschicht (Xnu.Field, Unity-Szene). Der Spielkern kennt keine Objekte, nur Namen und Gitterpositionen.
    // Alle "IsDone"-Abfragen werden je Tick einmal gestellt, bis sie true liefern.
    public interface IFieldHost
    {
        int CurrentZone { get; }

        // MAP_CHANGE: Zonenwechsel; fade = mit Überblendung (MAP_CHANGE) oder ohne (MAP_CHANGE_NONE_FADE).
        void ChangeZone(int zoneId, int locator, bool fade);
        bool ChangeZoneIsDone();

        // Ereignisbetrieb: EVENT_START/TALK_START/TALK_OBJ_START pausieren Objekte und sperren die Eingabe; EVENT_END/TALK_END/TALK_OBJ_END heben das auf.
        void SetEventMode(bool active);
        // Spieler und Gesprächspartner einander zuwenden (TALK_OBJ_START, nicht bei *_TURN_NOT).
        void TurnToTalkPartner(bool turn);

        void SetObjectVisible(string objectName, bool visible);
        void SetObjectGrid(string objectName, int x, int z, int direction);
        bool GetPlayerGrid(out int x, out int z, out int direction);

        void Fade(bool white, bool fadeIn, float speed);
        bool FadeIsDone();

        // Bewegungsskript eines Objekts (AC_*-Befehle bis ACMD_END, aus demselben EvData-File).
        void AnimateObject(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed);
        bool AnimationsDone(string objectName);

        // Alle übrigen sichtbaren Befehle (Kamera, Effekte, Türen, Blick, Wartebefehle). true = fertig.
        bool RunVisual(EvCommandCall call);
    }

    // Feldschicht ohne Welt: jede Anfrage ist sofort fertig; Aufrufe werden protokolliert. Für Tests und den lokalen Lauf.
    public class NullFieldHost : IFieldHost
    {
        public readonly List<string> Log = new List<string>();
        public bool Record = true;
        public int WaitPolls;
        public int GridX, GridZ, GridDir;
        public readonly HashSet<string> Visible = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
        public bool EventMode;
        public int VisualCalls;
        public readonly Dictionary<int, int> VisualIds = new Dictionary<int, int>();
        public int Zone { get; set; }
        int _polls;

        public int CurrentZone => Zone;

        void Add(string s)
        {
            if (Record) Log.Add(s);
        }

        bool Poll()
        {
            if (_polls < WaitPolls)
            {
                _polls++;
                return false;
            }
            _polls = 0;
            return true;
        }

        public virtual void ChangeZone(int zoneId, int locator, bool fade)
        {
            Zone = zoneId;
            Add("zone " + zoneId + " " + locator + (fade ? "" : " nofade"));
        }

        public virtual bool ChangeZoneIsDone() => Poll();

        public virtual void SetEventMode(bool active)
        {
            EventMode = active;
            Add(active ? "event-start" : "event-end");
        }

        public virtual void TurnToTalkPartner(bool turn) => Add("turn " + turn);

        public virtual void SetObjectVisible(string objectName, bool visible)
        {
            if (visible) Visible.Add(objectName); else Visible.Remove(objectName);
            Add((visible ? "show " : "hide ") + objectName);
        }

        public virtual void SetObjectGrid(string objectName, int x, int z, int direction) => Add("grid " + objectName + " " + x + " " + z + " " + direction);

        public virtual bool GetPlayerGrid(out int x, out int z, out int direction)
        {
            x = GridX;
            z = GridZ;
            direction = GridDir;
            return true;
        }

        public virtual void Fade(bool white, bool fadeIn, float speed) => Add("fade " + (white ? "white " : "black ") + (fadeIn ? "in" : "out"));

        public virtual bool FadeIsDone() => Poll();

        public virtual void AnimateObject(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed) =>
            Add("anim " + (objectName ?? "#" + objectIndex) + " " + label);

        public virtual bool AnimationsDone(string objectName) => Poll();

        public virtual bool RunVisual(EvCommandCall call)
        {
            if (call.First)
            {
                VisualCalls++;
                VisualIds.TryGetValue(call.Id, out var n);
                VisualIds[call.Id] = n + 1;
            }
            return Poll();
        }
    }
}
