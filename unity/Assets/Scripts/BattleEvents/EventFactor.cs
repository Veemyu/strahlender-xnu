namespace Xnu.Battle.Events
{
    // Handler eines Ereignisses (EventFactor.EventHandler): bekommt die Aufrufdaten und die dependID des Faktors
    // (bei WAZA/TOKUSEI/ITEM die ID des Pokemon, bei SIDE die Seite usw.).
    public delegate void EventHandlerDelegate(EventHandlerArgs args, byte dependId);

    // Prueft vor dem Aufruf, ob der Handler eines anderen Faktors uebersprungen werden soll (z. B. Moldbreaker-Arten).
    public delegate bool SkipCheckHandlerDelegate(SkipCheckHandlerArgs args);

    // Eintrag der Handler-Tabelle eines Faktors: Ereignis -> Handler (EventFactor.EventHandlerTable).
    public sealed class EventHandlerTable
    {
        public EventHandlerTable(EventId eventId, EventHandlerDelegate handler)
        {
            EventId = eventId;
            Handler = handler;
        }

        public EventId EventId { get; }
        public EventHandlerDelegate Handler { get; }
    }

    // Aufrufdaten eines Handlers (EventFactor.EventHandlerArgs). Das Original reicht zusaetzlich MainModule, BattleEnv,
    // PokeActionContainer usw. durch; hier genuegt der Kampfkontext (Env).
    public sealed class EventHandlerArgs
    {
        public EventSystem System { get; internal set; }
        public IEventBattleEnv Env { get; internal set; }
        public EventVarSet Vars { get; internal set; }
        public EventFactor MyFactor { get; internal set; }

        // Common.GetEventVar & Co.: Variablen des aktuellen Rahmens lesen/aendern.
        public int GetVar(EventVarLabel label) => System.GetValue(label);
        public bool TryGetVar(EventVarLabel label, out int value) => System.TryGetValue(label, out value);
        public void MulVar(EventVarLabel label, int ratio) => System.MulValue(label, ratio);
        public bool RewriteVar(EventVarLabel label, int value) => System.RewriteValue(label, value);
    }

    public sealed class SkipCheckHandlerArgs
    {
        public IEventBattleEnv Env { get; internal set; }
        public EventFactor MyFactor { get; internal set; }
        public EventId EventId { get; internal set; }
        public EventFactorType FactorType { get; internal set; }
        public ushort SubId { get; internal set; }
        public byte DependId { get; internal set; }
    }

    // Registrierter Handler-Satz eines Tokusei/Items/Attacke/Seite/... (EventFactor). Faktoren liegen in einer doppelt
    // verketteten Liste; ein fester Vorrat wird im Container angelegt und wiederverwendet.
    public sealed class EventFactor
    {
        public const int WorkElems = 7;

        public EventFactor(ushort instanceId)
        {
            InstanceId = instanceId;
            Clear();
        }

        public ushort InstanceId { get; }
        public EventFactor Prev { get; internal set; }
        public EventFactor Next { get; internal set; }

        public EventHandlerTable[] HandlerTable { get; internal set; }
        public SkipCheckHandlerDelegate SkipCheckHandler { get; internal set; }
        public EventFactorType FactorType { get; internal set; }

        // Hauptprioritaet (invertiert) in den oberen, Unterprioritaet in den unteren 24 Bit; grosser = frueher.
        public uint Priority { get; internal set; }
        public ushort SubId { get; internal set; }
        public byte DependId { get; internal set; }
        public byte PokeId { get; internal set; }
        public uint EventLevel { get; internal set; }
        public uint NumHandlers { get; internal set; }
        public bool Calling { get; internal set; }
        public bool RecallEnable { get; internal set; }
        public bool RemoveReserve { get; internal set; }
        public bool Sleeping { get; internal set; }
        public bool TempItem { get; internal set; }
        public bool Exists { get; internal set; }
        readonly int[] _work = new int[WorkElems];

        internal void Clear()
        {
            Prev = null;
            Next = null;
            HandlerTable = null;
            SkipCheckHandler = null;
            FactorType = 0;
            Priority = 0;
            SubId = 0;
            DependId = 0;
            PokeId = 0;
            EventLevel = 0;
            NumHandlers = 0;
            Calling = false;
            RecallEnable = false;
            RemoveReserve = false;
            Sleeping = false;
            TempItem = false;
            Exists = false;
            ClearWork();
        }

        public void ClearWork()
        {
            for (int i = 0; i < _work.Length; i++) _work[i] = 0;
        }

        public int GetWorkValue(byte index) => _work[index];

        public void SetWorkValue(byte index, int value) => _work[index] = value;

        public void AttachSkipCheckHandler(SkipCheckHandlerDelegate handler) => SkipCheckHandler = handler;

        public void DetachSkipCheckHandler() => SkipCheckHandler = null;

        // Nur waehrend des Aufrufs sinnvoll: erlaubt, dass der eigene Handler waehrend seiner Ausfuehrung erneut aufgerufen wird.
        public void SetRecallEnable()
        {
            if (Calling) RecallEnable = true;
        }

        public void ResetRecallEnable() => RecallEnable = false;

        public void SetTempItemFlag() => TempItem = true;

        public void ConvertForIsolate() => FactorType = EventFactorType.ISOLATE;

        // Wie SetRemoveReserverFlag des Originals: Loeschvormerkung (der Faktor wird nach seinem Handler entfernt).
        public void SetRemoveReserveFlag(bool value) => RemoveReserve = value;

        public bool IsIsolateMode => FactorType == EventFactorType.ISOLATE;

        public bool Sleep()
        {
            if (Sleeping) return false;
            Sleeping = true;
            return true;
        }

        public bool Wake()
        {
            if (!Sleeping) return false;
            Sleeping = false;
            return true;
        }

        public void SetEventLevel(ushort value) => EventLevel = value;
    }
}
