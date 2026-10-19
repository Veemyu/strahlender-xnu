using System.Collections.Generic;
using UnityEngine;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Field;

namespace Xnu.Game.Unity
{
    // Verbindet den Spielkern (IFieldHost) mit der Feldszene (FieldController):
    //  - Zonenwechsel des Ereignisses (MAP_CHANGE) laufen über FieldController.BeginSwitchZone, Warps/Türen/Zonengrenzen löst das Feld selbst aus;
    //  - Ansprechen/Berühren (IFieldInteractionHandler) werden als FieldSignal an die Spielschleife gereicht;
    //  - Work-/Systemflags des Spielstands bestimmen, welche Objekte aktiv sind (IFieldFlags);
    //  - Überblendung und Spielerposition für Skripte. Bewegung/Animation von Objekten und Kamera-Befehle sind Lücken (zählen nur).
    public sealed class FieldHostAdapter : IFieldHost, IFieldInteractionHandler, IFieldFlags
    {
        readonly FieldController _field;
        readonly GameSession _session;
        FieldSignal? _pending;
        (int Zone, int Locator)? _queuedChange;
        bool _changeRequested;
        bool _fadingIn;

        // true, solange die Spielschleife nicht im Feldzustand ist (dann nimmt das Feld keine neuen Anfragen an).
        public System.Func<bool> LoopBusy = () => false;

        public bool EventMode { get; private set; }
        public int ZoneChanges { get; private set; }
        public int TalkRequests { get; private set; }
        public int ContactRequests { get; private set; }
        public int VisualCalls { get; private set; }
        public int VisibilityCalls { get; private set; }
        public int AnimationCalls { get; private set; }
        public readonly Dictionary<int, int> VisualIds = new Dictionary<int, int>();
        public readonly HashSet<string> Hidden = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase);
        public string LastTalkLabel = "";

        public FieldHostAdapter(FieldController field, GameSession session)
        {
            _field = field ? field : throw new System.ArgumentNullException(nameof(field));
            _session = session ?? throw new System.ArgumentNullException(nameof(session));
            _field.Flags = this;
            _field.InteractionHandler = this;
            _field.ZoneChanged += OnZoneChanged;
        }

        public void Detach()
        {
            if (_field == null) return;
            _field.ZoneChanged -= OnZoneChanged;
            _field.InteractionHandler = null;
        }

        void OnZoneChanged(int zone)
        {
            _session.BeforeZoneId = _session.ZoneId;
            _session.ZoneId = zone;
            ZoneChanges++;
            _changeRequested = false;
        }

        // Je Tick: wartende Zonenwechsel nachholen.
        public void Tick()
        {
            if (_queuedChange.HasValue && !_field.InTransition && _field.Loaded)
            {
                var q = _queuedChange.Value;
                if (_field.BeginSwitchZone(q.Zone, q.Locator)) _queuedChange = null;
            }
        }

        public FieldSignal? TakePending()
        {
            var p = _pending;
            _pending = null;
            return p;
        }

        // ---- IFieldFlags ----

        public bool IsSet(int flagIndex) => flagIndex >= 0 && flagIndex < EvMemoryVariables.FlagCount && _session.Vars.GetFlag(flagIndex);

        // ---- IFieldInteractionHandler ----

        public bool Busy => _pending.HasValue || LoopBusy();

        public bool Handle(InteractionRequest request)
        {
            if (Busy || string.IsNullOrEmpty(request.Label)) return false;
            LastTalkLabel = request.Label;
            if (request.Kind == InteractionKind.Talk) { _pending = FieldSignal.Talk(request.Label); TalkRequests++; }
            else { _pending = FieldSignal.Contact(request.Label); ContactRequests++; }
            return true;
        }

        // ---- IFieldHost ----

        public int CurrentZone => _field.ZoneIdNow;

        public void ChangeZone(int zoneId, int locator, bool fade)
        {
            _changeRequested = true;
            if (!_field.BeginSwitchZone(zoneId, locator)) _queuedChange = (zoneId, locator);
        }

        public bool ChangeZoneIsDone() => !_changeRequested && !_queuedChange.HasValue && !_field.InTransition;

        public void SetEventMode(bool active)
        {
            EventMode = active;
            if (!active && _field.Loaded) _field.RefreshNpcsNow();
        }

        public void TurnToTalkPartner(bool turn) { }

        public void SetObjectVisible(string objectName, bool visible)
        {
            VisibilityCalls++;
            if (string.IsNullOrEmpty(objectName)) return;
            if (visible) Hidden.Remove(objectName); else Hidden.Add(objectName);
            if (_field.Loaded) _field.RefreshNpcsNow();
        }

        public void SetObjectGrid(string objectName, int x, int z, int direction) => VisibilityCalls++;

        public bool GetPlayerGrid(out int x, out int z, out int direction)
        {
            var m = _field.Mover;
            if (m == null) { x = z = direction = 0; return false; }
            x = m.GridX;
            z = m.GridY;
            direction = (int)m.Facing;
            return true;
        }

        public void Fade(bool white, bool fadeIn, float speed)
        {
            var f = _field.Fade;
            if (!fadeIn)
            {
                f.OutSeconds = 0.25f;
                f.Begin();
                _fadingIn = false;
            }
            else
            {
                f.InSeconds = 0.25f;
                f.Release();
                _fadingIn = true;
            }
        }

        public bool FadeIsDone() => _fadingIn ? !_field.Fade.Active : (_field.Fade.IsBlack || !_field.Fade.Active);

        public void AnimateObject(string objectName, int objectIndex, string label, IReadOnlyList<EventCommand> actions, float speed) => AnimationCalls++;

        public bool AnimationsDone(string objectName) => true;

        public bool RunVisual(EvCommandCall call)
        {
            if (call.First)
            {
                VisualCalls++;
                VisualIds.TryGetValue(call.Id, out var n);
                VisualIds[call.Id] = n + 1;
            }
            return true;
        }
    }
}
