using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Kampfumgebung der Ereignis-Tests, gespeist aus dem "env"-Block der Orakel-Fixtures.
    sealed class BattleEventsTestEnv : IEventBattleEnv
    {
        readonly Dictionary<int, BattlePoke> _pokes = new Dictionary<int, BattlePoke>();
        readonly HashSet<int> _fieldEffects = new HashSet<int>();
        readonly HashSet<ushort> _ommitTransform = new HashSet<ushort>();
        readonly HashSet<ushort> _ommitG = new HashSet<ushort>();

        public int ItemAttackValue;
        public int Weather;
        public int LocalWeather;
        public readonly HashSet<int> WazaFlags = new HashSet<int>();

        public static BattleEventsTestEnv FromJson(Dictionary<string, object> env)
        {
            var e = new BattleEventsTestEnv();
            if (env.TryGetValue("itemParam", out var ip)) e.ItemAttackValue = Convert.ToInt32(ip);
            if (env.TryGetValue("weather", out var w)) e.Weather = Convert.ToInt32(w);
            if (env.TryGetValue("localWeather", out var lw)) e.LocalWeather = Convert.ToInt32(lw);
            if (env.TryGetValue("wazaFlags", out var wf)) foreach (var v in (List<object>)wf) e.WazaFlags.Add(Convert.ToInt32(v));
            if (env.TryGetValue("fieldEffects", out var fe)) foreach (var v in (List<object>)fe) e._fieldEffects.Add(Convert.ToInt32(v));
            if (env.TryGetValue("ommitHensin", out var oh)) foreach (var v in (List<object>)oh) e._ommitTransform.Add(Convert.ToUInt16(v));
            if (env.TryGetValue("ommitG", out var og)) foreach (var v in (List<object>)og) e._ommitG.Add(Convert.ToUInt16(v));
            if (env.TryGetValue("pokes", out var pokes))
            {
                foreach (var kv in (Dictionary<string, object>)pokes)
                {
                    var cfg = (Dictionary<string, object>)kv.Value;
                    var p = new BattlePoke(byte.Parse(kv.Key));
                    foreach (var s in (List<object>)cfg["sick"]) p.SetSick(Convert.ToInt32(s), 1);
                    foreach (var f in (List<object>)cfg["turnFlags"]) p.SetTurnFlag(Convert.ToInt32(f), true);
                    p.TokuseiDisabledByGas = Convert.ToInt32(cfg["gas"]) != 0;
                    p.IsTransformed = Convert.ToInt32(cfg["hensin"]) != 0;
                    p.IsGMode = Convert.ToInt32(cfg["gmode"]) != 0;
                    if (cfg.ContainsKey("maxHp"))
                    {
                        p.MaxHp = Convert.ToUInt16(cfg["maxHp"]);
                        p.Hp = Convert.ToUInt16(cfg["hp"]);
                        p.Level = Convert.ToByte(cfg["level"]);
                        p.Sex = Convert.ToByte(cfg["sex"]);
                        p.Tokusei = Convert.ToUInt16(cfg["tokusei"]);
                        p.Item = Convert.ToUInt16(cfg["item"]);
                        p.MonsNo = Convert.ToUInt16(cfg["monsNo"]);
                        foreach (var cf in (List<object>)cfg["contFlags"]) p.SetContFlag(Convert.ToInt32(cf), true);
                        p.Type1 = 18;
                        p.Type2 = 18;
                        p.TypeEx = 18;
                        var types = (List<object>)cfg["types"];
                        if (types.Count > 0) p.Type1 = Convert.ToByte(types[0]);
                        if (types.Count > 1) p.Type2 = Convert.ToByte(types[1]);
                    }
                    e._pokes[p.Id] = p;
                }
            }
            return e;
        }

        public void AddPoke(BattlePoke p) => _pokes[p.Id] = p;
        public BattlePoke GetPoke(int pokeId) => _pokes.TryGetValue(pokeId, out var p) ? p : null;
        public bool IsFieldEffectActive(int effect) => _fieldEffects.Contains(effect);
        public bool OmmitAfterTransform(ushort tokuseiId) => _ommitTransform.Contains(tokuseiId);
        public bool OmmitOnGMode(ushort tokuseiId) => _ommitG.Contains(tokuseiId);
        public int GetItemAttackValue(ushort itemId) => ItemAttackValue;
        public int GetWeather() => Weather;
        public int GetLocalWeather(int pokeId) => LocalWeather;
        public bool WazaHasFlag(ushort wazaId, int flag) => WazaFlags.Contains(flag);
        public bool IsFriend(int pokeIdA, int pokeIdB) => (pokeIdA & 0xFF) % 2 == (pokeIdB & 0xFF) % 2;
    }

    // Fuehrt die Szenario-Schritte der Fixtures (gleiche Operationen wie scripts/battle_oracle_heap.py) gegen die C#-Umsetzung aus.
    sealed class BattleEventsScenario
    {
        public readonly EventSystem Es;
        public readonly BattleEventsTestEnv Env;
        public readonly List<EventFactor> Added = new List<EventFactor>();
        public readonly List<long[]> Log = new List<long[]>();

        public BattleEventsScenario(BattleEventsTestEnv env)
        {
            Env = env;
            Es = new EventSystem(env);
        }

        public EventFactor AddFactor(Dictionary<string, object> spec)
        {
            var entries = (List<object>)spec["entries"];
            var table = new EventHandlerTable[entries.Count];
            for (int i = 0; i < entries.Count; i++)
            {
                var ent = (Dictionary<string, object>)entries[i];
                int ev = Convert.ToInt32(ent["event"]);
                var ops = ent.TryGetValue("ops", out var o) ? (List<object>)o : new List<object>();
                table[i] = new EventHandlerTable((EventId)ev, (args, depend) =>
                {
                    Log.Add(new long[] { ev, args.MyFactor.InstanceId, depend, Es.EventLevel });
                    ExecOps(ops, args.MyFactor);
                });
            }
            var type = (EventFactorType)Convert.ToInt32(spec["type"]);
            ushort sub = Convert.ToUInt16(spec["subID"]);
            var pri = (EventPriority)Convert.ToInt32(spec["mainPri"]);
            uint subPri = Convert.ToUInt32(spec["subPri"]);
            byte depend = Convert.ToByte(spec["dependID"]);
            byte num = (byte)entries.Count;
            EventFactor f = Es.AddFactor(type, sub, pri, subPri, depend, table, num);
            if (f != null && spec.TryGetValue("skip", out var skip) && skip != null)
            {
                var rules = new List<long[]>();
                foreach (var r in (List<object>)skip) rules.Add(LongList(r).ToArray());
                f.AttachSkipCheckHandler(a =>
                {
                    long[] actual = { (long)a.EventId, (long)a.FactorType, a.SubId };
                    foreach (var rule in rules)
                    {
                        bool all = true;
                        for (int k = 0; k < 3; k++) all &= rule[k] == -1 || rule[k] == actual[k];
                        if (all) return true;
                    }
                    return false;
                });
            }
            Added.Add(f);
            return f;
        }

        public void ExecOps(List<object> ops, EventFactor my = null)
        {
            foreach (var op in ops) Exec((List<object>)op, my);
        }

        public void Exec(List<object> op, EventFactor my = null)
        {
            string name = (string)op[0];
            int A(int i) => Convert.ToInt32(op[i]);
            long L(int i) => Convert.ToInt64(op[i]);
            switch (name)
            {
                case "call": if (Es.EventLevel < 4) Es.CallEvent((EventId)A(1)); break;
                case "call_force": if (Es.EventLevel < 4) Es.CallEventForce((EventId)A(1)); break;
                case "call_target": if (Es.EventLevel < 4) Es.CallEventTargetType((EventId)A(1), (EventFactorType)A(2)); break;
                case "push": Es.VarPush(); break;
                case "pop": Es.VarPop(); break;
                case "check_cleared": Es.VarCheckStackCleared(); break;
                case "remove_isolate": Es.RemoveIsolateFactors(); break;
                case "wake_all": Es.WakeAllFactors(); break;
                case "set": Es.SetValue((ushort)A(1), unchecked((int)L(2))); break;
                case "const": Es.SetConstValue((ushort)A(1), unchecked((int)L(2))); break;
                case "once": Es.SetRewriteOnceValue((ushort)A(1), unchecked((int)L(2))); break;
                case "mulset": Es.SetMulValue((ushort)A(1), unchecked((int)L(2)), unchecked((int)L(3)), unchecked((int)L(4))); break;
                case "mul": Es.MulValue((ushort)A(1), unchecked((int)L(2))); break;
                case "recover": Es.RecoverRewriteOncePermission((ushort)A(1)); break;
                case "rewrite":
                    Log.Add(new long[] { -2, A(1), Es.RewriteValue((ushort)A(1), unchecked((int)L(2))) ? 1 : 0, 0 });
                    break;
                case "val": Log.Add(new long[] { -1, A(1), Es.GetValue((ushort)A(1)), 0 }); break;
                case "remove_self": Es.RemoveFactor(my); break;
                case "remove": if (A(1) < Added.Count) Es.RemoveFactor(Added[A(1)]); break;
                case "recall": my.SetRecallEnable(); break;
                case "tmpitem": (my ?? Added[A(1)]).SetTempItemFlag(); break;
                case "setwork": my.SetWorkValue((byte)A(1), unchecked((int)L(2))); break;
                case "getwork": Log.Add(new long[] { -3, A(1), my.GetWorkValue((byte)A(1)), 0 }); break;
                case "add": if (Added.Count < 14) AddFactor((Dictionary<string, object>)op[1]); break;
                case "sleep": Es.SleepFactors((ushort)A(1), (EventFactorType)A(2)); break;
                case "wake": Es.WakeFactors((ushort)A(1), (EventFactorType)A(2)); break;
                case "isolate": Added[A(1)].ConvertForIsolate(); break;
                default: throw new InvalidOperationException("Unbekannte Operation " + name);
            }
        }

        // Faktoren in Aufrufreihenfolge, gleiche Spaltenreihenfolge wie EventWorld.factor_list im Orakel.
        public List<long[]> FactorList()
        {
            var list = new List<long[]>();
            for (var f = Es.Container.First; f != null; f = f.Next)
                list.Add(new long[]
                {
                    f.InstanceId, (long)f.FactorType, f.SubId, f.Priority, f.DependId, f.PokeId, f.NumHandlers & 0xFF, f.EventLevel,
                    f.Calling ? 1 : 0, f.RecallEnable ? 1 : 0, f.RemoveReserve ? 1 : 0, f.Sleeping ? 1 : 0, f.TempItem ? 1 : 0, f.Exists ? 1 : 0,
                });
            return list;
        }

        // Belegte Slots des Variablenstapels: [index, label, state, value, min, max].
        public List<long[]> VarSnapshot()
        {
            var list = new List<long[]>();
            for (int i = 0; i < EventVarStack.Depth; i++)
            {
                var v = Es.VarStack.Slot(i);
                if (v.Label != 0) list.Add(new long[] { i, v.Label, (long)v.State, v.Value, v.MulMin, v.MulMax });
            }
            return list;
        }

        public long[] StackPointers() => new long[] { Es.VarStack.StackPointer, Es.VarSetStack.StackPointer };
    }
}
