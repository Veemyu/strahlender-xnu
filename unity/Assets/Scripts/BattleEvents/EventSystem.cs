using System;

namespace Xnu.Battle.Events
{
    // Ereignissystem (EventSystem, Spezifikation Abschnitte 2 bis 4): verwaltet die Faktoren, den Variablen-Stapel und
    // ruft die Handler eines Ereignisses der Reihe nach auf.
    public sealed class EventSystem
    {
        readonly IEventBattleEnv _env;
        readonly EventFactorContainer _container;
        readonly EventVarStack _varStack = new EventVarStack();
        readonly EventVarSetStack _setStack = new EventVarSetStack();
        EventVarSet _currentSet;
        uint _eventLevel;

        public EventSystem(IEventBattleEnv env, EventFactorContainer container = null)
        {
            _env = env;
            _container = container ?? new EventFactorContainer();
            _setStack.ToEmpty();
            _varStack.ToEmpty();
        }

        public IEventBattleEnv Env => _env;
        public EventFactorContainer Container => _container;
        public EventVarStack VarStack => _varStack;
        public EventVarSetStack VarSetStack => _setStack;

        // Verschachtelungstiefe der laufenden CallEvent-Aufrufe (m_eventLevel).
        public uint EventLevel => _eventLevel;

        public void Initialize()
        {
            _currentSet = null;
            _eventLevel = 0;
            _setStack.ToEmpty();
            _varStack.ToEmpty();
        }

        // ------------------------------------------------------------------------------------------------------
        // Registrieren und Entfernen
        // ------------------------------------------------------------------------------------------------------

        // EventSystem.AddFactor @0x19f4740: der Faktor merkt sich die aktuelle Aufruftiefe (m_eventLevel). Wird er waehrend eines
        // Ereignisaufrufs registriert, reagiert er erst auf Aufrufe, die tiefer verschachtelt sind, oder nach dem
        // aeusseren Aufruf (Abschnitt 4.3); ausserhalb von Aufrufen ist die Stufe 0 und er reagiert sofort.
        public EventFactor AddFactor(EventFactorType type, ushort subId, EventPriority mainPri, uint subPri, byte dependId,
            EventHandlerTable[] table, byte numHandlers)
            => _container.AddFactor(type, subId, mainPri, subPri, dependId, table, numHandlers, (ushort)_eventLevel);

        // Entfernt sofort, ausser der Faktor laeuft gerade: dann nur Loeschvormerkung (wird nach dem Handler ausgefuehrt).
        public void RemoveFactor(EventFactor factor)
        {
            if (factor == null || !factor.Exists) return;
            if (factor.Calling) factor.RemoveReserve = true;
            else _container.RemoveFactor(factor);
        }

        public void RemoveIsolateFactors()
        {
            var f = _container.First;
            while (f != null)
            {
                var next = f.Next;
                if (f.FactorType == EventFactorType.ISOLATE && f.Exists) RemoveFactor(f);
                f = next;
            }
        }

        public void SleepFactors(ushort pokeId, EventFactorType type)
        {
            for (var f = _container.First; f != null; f = f.Next)
                if (f.PokeId == pokeId && f.FactorType == type) f.Sleep();
        }

        public void WakeFactors(ushort pokeId, EventFactorType type)
        {
            for (var f = _container.First; f != null; f = f.Next)
                if (f.PokeId == pokeId && f.FactorType == type) f.Wake();
        }

        public void WakeAllFactors()
        {
            for (var f = _container.First; f != null; f = f.Next) f.Wake();
        }

        // ------------------------------------------------------------------------------------------------------
        // Aufruf-Schleife
        // ------------------------------------------------------------------------------------------------------

        public void CallEvent(EventId eventId) => CallEventCore(eventId, EventFactorType.NUM, true);

        // Ohne Skip-Pruefung (Moldbreaker-artige Handler greifen nicht).
        public void CallEventForce(EventId eventId) => CallEventCore(eventId, EventFactorType.NUM, false);

        public void CallEventTargetType(EventId eventId, EventFactorType type) => CallEventCore(eventId, type, true);

        void CallEventCore(EventId eventId, EventFactorType target, bool skipCheck)
        {
            _eventLevel++;
            var cur = _container.First;
            while (cur != null)
            {
                var next = NotifyHandler(eventId, target, skipCheck, cur);
                if (next == null) break;
                if (!next.Exists) next = cur.Next;
                cur = next;
            }
            _eventLevel--;
            if (_eventLevel == 0)
                for (var f = _container.First; f != null; f = f.Next) f.SetEventLevel(0);
        }

        // Ruft den Handler eines Faktors auf, falls er zum Ereignis passt; liefert den naechsten Faktor der Liste.
        EventFactor NotifyHandler(EventId eventId, EventFactorType target, bool skipCheck, EventFactor f)
        {
            var next = f.Next;
            if (f.Calling && !f.RecallEnable) return next;
            if (f.Sleeping) return next;
            if (target != EventFactorType.NUM && f.FactorType != target) return next;
            ushort level = (ushort)f.EventLevel;
            if (level != 0 && _eventLevel <= f.EventLevel) return next;
            if (!f.Exists) return next;
            if (eventId == EventId.USE_ITEM_TMP && !f.TempItem) return next;
            var table = f.HandlerTable;
            byte count = (byte)f.NumHandlers;
            if (count == 0) return next;

            for (int i = 0; ; )
            {
                if (table[i].EventId == eventId)
                {
                    if (skipCheck && CheckHandlerSkip(f, eventId)) return next;
                    f.Calling = true;
                    var args = new EventHandlerArgs { System = this, Env = _env, Vars = _currentSet, MyFactor = f };
                    table[i].Handler(args, f.DependId);
                    if (!f.RecallEnable) f.Calling = false;
                    else f.ResetRecallEnable();
                    if (!f.RemoveReserve) return next;
                    if (next != null)
                    {
                        while (true)
                        {
                            if (next.Exists) break;
                            next = f.Next;
                            if (next == null) break;
                        }
                    }
                    if (f.Exists)
                    {
                        if (!f.Calling) _container.RemoveFactor(f);
                        else f.RemoveReserve = true;
                    }
                    return next;
                }
                i++;
                if (count <= i) return next;
            }
        }

        // Soll der Handler des Faktors f fuer dieses Ereignis uebersprungen werden? (checkHandlerSkip)
        bool CheckHandlerSkip(EventFactor f, EventId eventId)
        {
            BattlePoke poke = null;
            if (f.PokeId != 0x1F) poke = _env.GetPoke(f.PokeId);
            var type = f.FactorType;
            if (poke != null && type == EventFactorType.TOKUSEI)
            {
                if (poke.CheckSick(WazaSickIds.IEKI)) return true;
                if (poke.TokuseiDisabledByGas) return true;
                if (poke.IsTransformed && _env.OmmitAfterTransform(f.SubId)) return true;
                if (poke.IsGMode && _env.OmmitOnGMode(f.SubId)) return true;
            }
            if (eventId != EventId.MEMBER_IN_EVO && type == EventFactorType.ITEM)
            {
                if (_env.IsFieldEffectActive(FieldEffects.MagicRoom)) return true;
                if (poke != null)
                {
                    if (poke.CheckSick(WazaSickIds.SASIOSAE)) return true;
                    if (poke.GetTurnFlag(TurnFlags.ItemCantUse)) return true;
                }
            }
            for (var other = _container.First; other != null; other = other.Next)
            {
                if (other.SkipCheckHandler == null || other.Sleeping) continue;
                if (other.FactorType == EventFactorType.TOKUSEI)
                {
                    var op = _env.GetPoke(other.PokeId);
                    if (op != null && (op.CheckSick(WazaSickIds.IEKI) || op.TokuseiDisabledByGas)) continue;
                }
                var args = new SkipCheckHandlerArgs
                {
                    Env = _env, MyFactor = other, EventId = eventId, FactorType = type, SubId = f.SubId, DependId = f.DependId,
                };
                if (other.SkipCheckHandler(args)) return true;
            }
            return false;
        }

        // ------------------------------------------------------------------------------------------------------
        // Ereignis-Variablen (EVENTVAR_*)
        // ------------------------------------------------------------------------------------------------------

        // Neuer Rahmen: Trennzeichen im Variablenvorrat, neuer (leerer) Variablensatz; Variablen aeusserer Rahmen sind
        // im inneren nicht sichtbar.
        public void VarPush()
        {
            _varStack.Push();
            _setStack.Push();
            _currentSet = _setStack.GetCurrent();
        }

        public void VarPop()
        {
            _setStack.Pop();
            _currentSet = _setStack.GetCurrent();
            _varStack.Pop();
        }

        public void VarCheckStackCleared()
        {
            if (_varStack.IsEmpty) return;
            _varStack.ToEmpty();
            _setStack.ToEmpty();
            _currentSet = _setStack.GetCurrent();
        }

        EventVar Allocate(ushort label)
        {
            var v = _varStack.GetNewPoint(label);
            if (v == null) return null;
            v.Label = label;
            return v;
        }

        void Register(EventVar v)
        {
            if (_currentSet == null) throw new InvalidOperationException("Kein Ereignisrahmen (VarPush fehlt)");
            _currentSet.SetVariable(v);
        }

        public void SetValue(EventVarLabel label, int value) => SetValue((ushort)label, value);
        public void SetValue(ushort label, int value)
        {
            var v = Allocate(label);
            if (v == null) return;
            v.SetValue(value);
            Register(v);
        }

        public void SetConstValue(EventVarLabel label, int value) => SetConstValue((ushort)label, value);
        public void SetConstValue(ushort label, int value)
        {
            var v = Allocate(label);
            if (v == null) return;
            v.SetConstValue(value);
            Register(v);
        }

        public void SetRewriteOnceValue(EventVarLabel label, int value) => SetRewriteOnceValue((ushort)label, value);
        public void SetRewriteOnceValue(ushort label, int value)
        {
            var v = Allocate(label);
            if (v == null) return;
            v.SetRewriteOnceValue(value);
            Register(v);
        }

        public void SetMulValue(EventVarLabel label, int value, int mulMin, int mulMax) => SetMulValue((ushort)label, value, mulMin, mulMax);
        public void SetMulValue(ushort label, int value, int mulMin, int mulMax)
        {
            var v = Allocate(label);
            if (v == null) return;
            v.SetMulValue(value, mulMin, mulMax);
            Register(v);
        }

        // Variable mit Objektverweis statt Zahl (EVENTVAR_SetWorkAddress); der Wert wird 0.
        public void SetWorkObject(EventVarLabel label, object work)
        {
            var v = Allocate((ushort)label);
            if (v == null) return;
            v.SetAddress(work);
            Register(v);
        }

        public object GetWorkObject(EventVarLabel label) => Find((ushort)label)?.Address;

        EventVar Find(ushort label)
        {
            if (_currentSet == null) throw new InvalidOperationException("Kein Ereignisrahmen (VarPush fehlt)");
            return _currentSet.GetVariable(label);
        }

        public void RecoverRewriteOncePermission(EventVarLabel label) => RecoverRewriteOncePermission((ushort)label);
        public void RecoverRewriteOncePermission(ushort label) => Find(label)?.RecoverRewriteOncePermission();

        public bool RewriteValue(EventVarLabel label, int value) => RewriteValue((ushort)label, value);
        public bool RewriteValue(ushort label, int value)
        {
            var v = Find(label);
            return v != null && v.RewriteValue(value);
        }

        public void MulValue(EventVarLabel label, int ratio) => MulValue((ushort)label, ratio);
        public void MulValue(ushort label, int ratio) => Find(label)?.MulValue(ratio);

        // Fehlende Variablen lesen als 0.
        public int GetValue(EventVarLabel label) => GetValue((ushort)label);
        public int GetValue(ushort label) => Find(label)?.Value ?? 0;

        public bool TryGetValue(EventVarLabel label, out int value) => TryGetValue((ushort)label, out value);
        public bool TryGetValue(ushort label, out int value)
        {
            var v = Find(label);
            value = v?.Value ?? 0;
            return v != null;
        }
    }
}
