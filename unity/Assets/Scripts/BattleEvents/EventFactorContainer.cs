using System;

namespace Xnu.Battle.Events
{
    // Vorrat und Liste der registrierten Faktoren (EventFactorContainer, Spezifikation Abschnitt 3).
    // 172 Faktoren werden einmal angelegt; freie liegen in einer "gelagerten" Liste (Kopf = zuletzt gelagert), belegte in
    // der laufenden Liste, die nach Prioritaet absteigend sortiert ist (Gleichstand: zuerst Registrierte zuerst).
    public sealed class EventFactorContainer
    {
        public const int FactorRegisterMax = 172;
        public const int SubPriorityBitWidth = 24;
        public const uint SubPriorityMax = 0xFFFFFF;

        readonly EventFactor[] _factors = new EventFactor[FactorRegisterMax];
        EventFactor _running;
        EventFactor _stored;

        public EventFactorContainer()
        {
            for (int i = 0; i < FactorRegisterMax; i++) _factors[i] = new EventFactor((ushort)i);
            foreach (var f in _factors) StoreFactor(f);
        }

        public EventFactor First => _running;

        public int StoredCount
        {
            get
            {
                int n = 0;
                for (var f = _stored; f != null; f = f.Next) n++;
                return n;
            }
        }

        // Hauptprioritaet wird invertiert (kleiner Enum-Wert = groesserer Wert = frueher), Unterprioritaet ODER-verknuepft.
        public static uint CalcFactorPriority(EventPriority mainPri, uint subPri) => unchecked((uint)((int)mainPri * -0x1000000) + 0x9000000u) | subPri;

        // Nur WAZA, TOKUSEI und ITEM gehoeren zu einem Pokemon (dependID = Pokemon-ID); alle anderen bekommen 0x1F.
        public static bool IsDependPokeFactorType(EventFactorType type) => type == EventFactorType.WAZA || type == EventFactorType.TOKUSEI || type == EventFactorType.ITEM;

        // Legt einen Faktor an; liefert null, wenn der Vorrat erschoepft ist.
        public EventFactor AddFactor(EventFactorType type, ushort subId, EventPriority mainPri, uint subPri, byte dependId,
            EventHandlerTable[] table, byte numHandlers, ushort eventLevel)
        {
            var f = _stored;
            if (f == null) return null;
            _stored = f.Next;
            Unlink(f);
            byte pokeId = (byte)type < 6 && IsDependPokeFactorType(type) ? dependId : (byte)0x1F;
            f.Clear();
            f.Priority = CalcFactorPriority(mainPri, subPri);
            f.FactorType = type;
            f.HandlerTable = table;
            f.NumHandlers = numHandlers;
            f.DependId = dependId;
            f.SubId = subId;
            f.PokeId = pokeId;
            f.EventLevel = eventLevel;
            f.Exists = true;
            AddRunningFactor(f);
            return f;
        }

        public void RemoveFactor(EventFactor f)
        {
            if (_running == f) _running = f.Next;
            StoreFactor(f);
        }

        public EventFactor GetFactor(ushort instanceId)
        {
            foreach (var f in _factors)
                if (f.InstanceId == instanceId) return f;
            return null;
        }

        // Erster vorhandener Faktor des Typs ohne Loeschvormerkung.
        public EventFactor SeekFactor(EventFactorType type)
        {
            var f = _running;
            while (f != null && (!f.Exists || f.FactorType != type || f.RemoveReserve)) f = f.Next;
            return f;
        }

        public EventFactor SeekFactor(EventFactorType type, byte dependId)
        {
            var f = _running;
            while (f != null && (!f.Exists || f.FactorType != type || f.DependId != dependId || f.RemoveReserve)) f = f.Next;
            return f;
        }

        // Naechster Faktor gleichen Typs ohne Loeschvormerkung; mit anyDepend egal welche dependID, sonst dieselbe.
        public EventFactor GetNextFactor(EventFactor f, bool anyDepend)
        {
            if (f == null) return null;
            var n = f.Next;
            while (n != null)
            {
                bool match = n.FactorType == f.FactorType && !n.RemoveReserve && (anyDepend || n.DependId == f.DependId);
                if (match) return n;
                n = n.Next;
            }
            return null;
        }

        // Tauscht bei allen SIDE-Faktoren mit der Seiteneffekt-ID die Seiten a und b.
        public void SwapFactorsSideEffect(byte sideA, byte sideB, ushort sideEffectId)
        {
            for (var f = _running; f != null; f = f.Next)
            {
                if (f.FactorType != EventFactorType.SIDE || f.SubId != sideEffectId) continue;
                if (f.DependId == sideA) f.DependId = sideB;
                else if (f.DependId == sideB) f.DependId = sideA;
            }
        }

        void Unlink(EventFactor f)
        {
            var prev = f.Prev;
            var next = f.Next;
            if (prev != null) prev.Next = next;
            if (next != null) next.Prev = prev;
            f.Prev = null;
            f.Next = null;
        }

        // Loest den Faktor aus seiner Liste, loescht ihn und legt ihn an den Kopf der gelagerten Liste.
        void StoreFactor(EventFactor f)
        {
            Unlink(f);
            f.Clear();
            f.Next = _stored;
            if (_stored != null) _stored.Prev = f;
            _stored = f;
        }

        void AddRunningFactor(EventFactor f)
        {
            var head = _running;
            if (head != null)
            {
                uint pri = f.Priority;
                if (pri <= head.Priority)
                {
                    var cur = head;
                    while (true)
                    {
                        var next = cur.Next;
                        if (next == null)
                        {
                            cur.Next = f;
                            f.Prev = cur;
                            return;
                        }
                        cur = next;
                        if (pri > cur.Priority) break;
                    }
                    var before = cur.Prev;
                    before.Next = f;
                    f.Prev = before;
                    f.Next = cur;
                    cur.Prev = f;
                    return;
                }
                f.Next = head;
                head.Prev = f;
            }
            _running = f;
        }
    }
}
