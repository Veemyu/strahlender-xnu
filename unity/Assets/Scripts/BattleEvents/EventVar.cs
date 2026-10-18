using System;

namespace Xnu.Battle.Events
{
    // Eine Ereignis-Variable (EventVar). Wie im Original bleiben beim Freigeben (Pop) Wert, Zustand und Grenzen
    // stehen; nur das Label wird auf 0 gesetzt (Spezifikation Abschnitt 2).
    public sealed class EventVar
    {
        public ushort Label;
        public EventVarState State;
        public int Value;
        public int MulMin;
        public int MulMax;
        public object Address;

        public void SetValue(int value)
        {
            Address = null;
            Value = value;
            MulMin = 0;
            MulMax = 0;
            State = EventVarState.FREE;
        }

        public void SetConstValue(int value)
        {
            SetValue(value);
            State = EventVarState.LOCK;
        }

        public void SetRewriteOnceValue(int value)
        {
            SetValue(value);
            State = EventVarState.ONCE;
        }

        public void SetMulValue(int value, int min, int max)
        {
            Address = null;
            Value = value;
            MulMin = min;
            MulMax = max;
            State = EventVarState.MUL;
        }

        public void SetAddress(object address)
        {
            Address = address;
            Value = 0;
            MulMin = 0;
            MulMax = 0;
            State = EventVarState.FREE;
        }

        // Nur FREE und ONCE duerfen umgeschrieben werden; ONCE wird dabei zu END.
        public bool RewriteValue(int value)
        {
            if (State >= EventVarState.END) return false;
            Value = value;
            if (State == EventVarState.ONCE) State = EventVarState.END;
            return true;
        }

        public void RecoverRewriteOncePermission() => State = EventVarState.ONCE;

        // (Wert * Faktor + 0x800) >> 12 in 64 Bit, dann auf 32 Bit gekuerzt (wie das Original); Grenzen gelten, sobald eine von
        // 0 verschieden ist, und werden auf dem gekuerzten Wert angewandt. Nur im Zustand MUL.
        public void MulValue(int ratio)
        {
            if (State != EventVarState.MUL) return;
            int v = unchecked((int)(((long)Value * ratio + 0x800) >> 12));
            if (MulMin != 0 || MulMax != 0) v = Math.Min(MulMax, Math.Max(MulMin, v));
            Value = v;
        }
    }

    // Variablen eines Ereignisrahmens, nach Label indiziert (124 Slots).
    public sealed class EventVarSet
    {
        public const int Count = 124;
        readonly EventVar[] _vars = new EventVar[Count];

        public void Clear() => Array.Clear(_vars, 0, _vars.Length);

        public EventVar GetVariable(ushort label) => label < Count ? _vars[label] : null;

        public void SetVariable(EventVar variable)
        {
            if (variable.Label < Count) _vars[variable.Label] = variable;
        }
    }

    // Vorrat von 96 Variablen; Rahmen werden durch Trennzeichen (Label 1) markiert.
    public sealed class EventVarStack
    {
        public const int Depth = 96;
        readonly EventVar[] _vars = new EventVar[Depth];
        uint _sp;

        public EventVarStack()
        {
            for (int i = 0; i < Depth; i++) _vars[i] = new EventVar();
        }

        public uint StackPointer => _sp;

        public EventVar Slot(int index) => _vars[index];

        public bool IsEmpty => _sp == 0;

        public void ToEmpty()
        {
            _sp = 0;
            foreach (var v in _vars) v.Label = 0;
        }

        // Setzt hinter die belegten Slots ein Trennzeichen; der Zeiger zeigt danach hinter das Trennzeichen.
        public void Push()
        {
            if (_sp >= Depth) return;
            uint i = _sp;
            while (true)
            {
                if (_vars[i].Label == 0) break;
                _sp = i + 1;
                bool more = i < Depth - 1;
                i++;
                if (!more) break;
            }
            if (i < Depth - 1)
            {
                _vars[i].Label = 1;
                _sp++;
            }
        }

        // Gibt die Variablen des Rahmens und sein Trennzeichen frei; der Zeiger springt hinter das vorige Trennzeichen.
        public void Pop()
        {
            if (_sp == 0) return;
            uint i = _sp & 0xFFFF;
            if (i < Depth)
            {
                do
                {
                    var v = _vars[i];
                    if (v.Label == 0) break;
                    i = (i + 1) & 0xFFFF;
                    v.Label = 0;
                } while (i < Depth);
            }
            uint u = _sp - 1;
            _sp = u;
            _vars[u].Label = 0;
            int p = (int)_sp + 1;
            while (true)
            {
                int q = p - 1;
                if (q == 0) return;
                u = (uint)(p - 2);
                _sp = u;
                p = q;
                if (_vars[u].Label == 1)
                {
                    _sp = (uint)q;
                    return;
                }
            }
        }

        // Erster freier oder gleich benannter Slot ab dem Zeiger (EventVarStack.GetNewPoint); null, wenn keiner frei ist.
        public EventVar GetNewPoint(ushort label)
        {
            for (uint i = _sp; i < Depth; i++)
            {
                var v = _vars[i];
                if (v.Label == 0 || v.Label == label) return v;
            }
            return null;
        }
    }

    // Stapel der Variablensaetze (32 Stueck, einer je geschachteltem Ereignisrahmen).
    public sealed class EventVarSetStack
    {
        public const int StackSize = 32;
        readonly EventVarSet[] _sets = new EventVarSet[StackSize];
        uint _sp;

        public EventVarSetStack()
        {
            for (int i = 0; i < StackSize; i++) _sets[i] = new EventVarSet();
        }

        public uint StackPointer => _sp;

        public void ToEmpty()
        {
            _sp = 0;
            foreach (var s in _sets) s.Clear();
        }

        public EventVarSet GetCurrent() => _sets[_sp];

        public void Push()
        {
            if (_sp < StackSize - 1) _sp++;
        }

        public void Pop()
        {
            if (_sp == 0) return;
            _sets[_sp].Clear();
            _sp--;
        }
    }
}
