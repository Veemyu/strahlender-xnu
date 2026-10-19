using System;

namespace Xnu.Field
{
    public enum InteractionKind
    {
        Talk,       // A-Taste vor einem NPC/Objekt: TalkLabel
        Contact,    // Spieler betritt die Fläche eines Objekts mit ContactLabel (Trainer-Blick, Auslöser)
    }

    // Anfrage des Feldes an den Event-Interpreter. Enthält nur Daten (Labels, Orte); das Feld kennt kein EvScript.
    public readonly struct InteractionRequest
    {
        public readonly InteractionKind Kind;
        public readonly int ZoneId;
        public readonly PlacementRecord Target;
        public readonly int PlayerX, PlayerY;
        public readonly MoveDir PlayerFacing;

        public InteractionRequest(InteractionKind kind, int zoneId, PlacementRecord target, int playerX, int playerY, MoveDir facing)
        {
            Kind = kind; ZoneId = zoneId; Target = target; PlayerX = playerX; PlayerY = playerY; PlayerFacing = facing;
        }

        public string Label => Kind == InteractionKind.Talk ? Target.TalkLabel : Target.ContactLabel;
        public override string ToString() => Kind + " " + Target.Id + " (" + Label + ") in Zone " + ZoneId;
    }

    // Schnittstelle zum späteren Event-Interpreter (nicht von EvScript abhängig). Der Interpreter übernimmt die Anfrage
    // und meldet über Busy, solange ein Ereignis läuft (Eingabe und Spielerbewegung ruhen dann).
    public interface IFieldInteractionHandler
    {
        bool Busy { get; }
        // true = Anfrage angenommen. false = keine Reaktion (z. B. leeres Label).
        bool Handle(InteractionRequest request);
    }

    // Ersatz ohne Interpreter: protokolliert die Anfrage und ist sofort wieder frei.
    public sealed class LoggingInteractionHandler : IFieldInteractionHandler
    {
        public Action<string> Log;
        public int Handled { get; private set; }
        public InteractionRequest? Last { get; private set; }
        public bool Busy => false;

        public bool Handle(InteractionRequest request)
        {
            Handled++;
            Last = request;
            Log?.Invoke("[Field] Interaktion: " + request);
            return true;
        }
    }

    // Findet das Ziel der A-Taste und die Berührung beim Betreten einer Zelle.
    public sealed class FieldInteraction
    {
        readonly PlacementDirectory _placements;
        readonly IFieldFlags _flags;

        public IFieldInteractionHandler Handler { get; set; }

        public FieldInteraction(PlacementDirectory placements, IFieldFlags flags = null)
        {
            _placements = placements ?? throw new ArgumentNullException(nameof(placements));
            _flags = flags;
        }

        public bool Busy => Handler != null && Handler.Busy;

        // Ziel vor dem Spieler: die Zelle in Blickrichtung (TalkToRange 1,25 deckt die Nachbarzelle). Hinter einem Tresen
        // (TalkToSize) wird zusätzlich die zweite Zelle geprüft, wenn die erste leer ist und ein Objekt mit TalkRange >= 2 dort liegt.
        public PlacementRecord FindTalkTarget(int zone, int gx, int gy, MoveDir facing)
        {
            if (facing == MoveDir.None) return null;
            var d = facing.GridDelta();
            var t = _placements.FindAt(zone, gx + d.Dx, gy + d.Dy, _flags);
            if (t != null && t.HasTalk) return t;
            var far = _placements.FindAt(zone, gx + 2 * d.Dx, gy + 2 * d.Dy, _flags);
            if (far != null && far.HasTalk && far.TalkRange >= 2f) return far;
            return null;
        }

        // A-Taste. true = Anfrage wurde an den Handler übergeben.
        public bool TryTalk(int zone, int gx, int gy, MoveDir facing)
        {
            if (Handler == null || Busy) return false;
            var t = FindTalkTarget(zone, gx, gy, facing);
            return t != null && Handler.Handle(new InteractionRequest(InteractionKind.Talk, zone, t, gx, gy, facing));
        }

        // Schritt beendet: Fläche mit ContactLabel betreten.
        public bool TryContact(int zone, int gx, int gy, MoveDir facing)
        {
            if (Handler == null || Busy) return false;
            var t = _placements.FindAt(zone, gx, gy, _flags);
            return t != null && t.HasContact && Handler.Handle(new InteractionRequest(InteractionKind.Contact, zone, t, gx, gy, facing));
        }
    }
}
