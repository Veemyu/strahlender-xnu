using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle.Events;
using static Xnu.Tests.BattleFixtures;
using L = Xnu.Battle.Events.EventVarLabel;

namespace Xnu.Tests
{
    // Handler-Abdeckung der Scheibe 3 (docs/kampf-spezifikation-3.md): Orakel-Fixtures BattleHandlers.json und Handrechnungen [P].
    public class BattleEventsSlice3Tests
    {
        static EventHandlerTable[] TableFor(string cls, int no)
        {
            switch (cls)
            {
                case "Tokusei":
                    var f = TokuseiHandlers.GetHandlerGetFunc((ushort)no);
                    var pri = EventPriority.TOKUSEI;
                    return f?.Invoke(ref pri);
                case "Item": return ItemHandlers.GetTable((ushort)no);
                case "Waza": return WazaHandlers.GetTable((ushort)no);
                default: throw new ArgumentException(cls);
            }
        }

        [Test]
        public void HandlersAgreeWithTheRealFunctionsForEveryOracleCase()
        {
            var root = Load("BattleHandlers.json");
            var cases = Cases(root, "cases");
            Assert.GreaterOrEqual(cases.Count, 1500);
            var covered = new Dictionary<string, HashSet<int>> { { "Tokusei", new HashSet<int>() }, { "Item", new HashSet<int>() }, { "Waza", new HashSet<int>() } };
            var missing = new HashSet<string>();
            int compared = 0;
            foreach (var c in cases)
            {
                string cls = (string)c["cls"];
                int no = Convert.ToInt32(c["no"]);
                int ev = Convert.ToInt32(c["event"]);
                string where = cls + " " + no + " Ereignis " + ev + " Fall " + cases.IndexOf(c);
                var entry = TableFor(cls, no)?.FirstOrDefault(t => (int)t.EventId == ev);
                if (entry == null)
                {
                    missing.Add(cls + ":" + no + ":" + ev);
                    continue;
                }
                var env = BattleEventsTestEnv.FromJson((Dictionary<string, object>)c["env"]);
                var sc = new BattleEventsScenario(env);
                var spec = (Dictionary<string, object>)((List<object>)c["adds"])[0];
                var logged = new[]
                {
                    new EventHandlerTable(entry.EventId, (args, d) =>
                    {
                        sc.Log.Add(new long[] { ev, args.MyFactor.InstanceId, d, sc.Es.EventLevel });
                        entry.Handler(args, d);
                    }),
                };
                sc.Es.AddFactor((EventFactorType)Convert.ToInt32(spec["type"]), Convert.ToUInt16(spec["subID"]),
                    (EventPriority)Convert.ToInt32(spec["mainPri"]), Convert.ToUInt32(spec["subPri"]), Convert.ToByte(spec["dependID"]), logged, 1);
                foreach (var step in (List<object>)c["steps"]) sc.Exec((List<object>)step);

                var expectedLog = Matrix(c["log"]);
                Assert.AreEqual(expectedLog.Count, sc.Log.Count, where + " Anzahl");
                for (int i = 0; i < expectedLog.Count; i++) CollectionAssert.AreEqual(expectedLog[i], sc.Log[i], where + " Protokoll " + i);
                var expectedVars = Matrix(c["vars"]);
                var actualVars = sc.VarSnapshot();
                Assert.AreEqual(expectedVars.Count, actualVars.Count, where + " Variablen");
                for (int i = 0; i < expectedVars.Count; i++) CollectionAssert.AreEqual(expectedVars[i], actualVars[i], where + " Variable " + i);
                covered[cls].Add(no);
                compared++;
            }
            Assert.GreaterOrEqual(compared, 1500, "Anzahl verglichener Faelle");
            Assert.GreaterOrEqual(covered["Tokusei"].Count, 40, "Fähigkeiten mit Orakelbeleg");
            Assert.GreaterOrEqual(covered["Item"].Count, 40, "Items mit Orakelbeleg");
            Assert.GreaterOrEqual(covered["Waza"].Count, 40, "Attacken mit Orakelbeleg");
            foreach (var m in missing) TestContext.WriteLine("kein C#-Handler fuer " + m);
        }

        [Test]
        public void ImplementedNumbersAreCoveredByTheOracle()
        {
            var root = Load("BattleHandlers.json");
            var seen = new HashSet<string>();
            foreach (var c in Cases(root, "cases")) seen.Add((string)c["cls"] + ":" + Convert.ToInt32(c["no"]));
            int lacking = 0;
            for (ushort no = 0; no < 1200; no++)
            {
                if (TokuseiHandlers.IsImplemented(no) && !seen.Contains("Tokusei:" + no)) lacking++;
                if (ItemHandlers.IsImplemented(no) && !seen.Contains("Item:" + no) && no != 270) lacking++;
                if (WazaHandlers.IsImplemented(no) && !seen.Contains("Waza:" + no)) lacking++;
            }
            Assert.AreEqual(0, lacking, "umgesetzte Nummern ohne Orakelfall");
        }

        // ------------------------------------------------------------------------------------------------------
        // Handrechnungen [P] und Registrierung
        // ------------------------------------------------------------------------------------------------------

        static (EventSystem es, BattleEventsTestEnv env) World(params BattlePoke[] pokes)
        {
            var env = new BattleEventsTestEnv();
            foreach (var p in pokes) env.AddPoke(p);
            var es = new EventSystem(env);
            es.VarPush();
            return (es, env);
        }

        static BattlePoke Poke(byte id, ushort tokusei = 0, ushort item = 0) =>
            new BattlePoke(id) { Tokusei = tokusei, Item = item, Hp = 100, MaxHp = 100, Level = 50, Agility = 80 };

        [Test]
        public void RivalryDependsOnTheSexOfBothPokemon()
        {
            foreach (var (sexA, sexB, expected) in new[] { ((byte)0, (byte)0, 0x1400), ((byte)0, (byte)1, 0xC00), ((byte)2, (byte)0, 0x1000), ((byte)1, (byte)2, 0x1000) })
            {
                var a = Poke(0, 79);
                a.Sex = sexA;
                var b = Poke(1);
                b.Sex = sexB;
                var (es, _) = World(a, b);
                TokuseiHandlers.Add(es, a);
                es.SetConstValue(L.POKEID_ATK, 0);
                es.SetConstValue(L.POKEID_DEF, 1);
                es.SetMulValue(L.WAZA_POWER_RATIO, 0x1000, 0x29, 0x200000);
                es.CallEvent(EventId.WAZA_POWER);
                Assert.AreEqual(expected, es.GetValue(L.WAZA_POWER_RATIO), $"{sexA}/{sexB}");
            }
        }

        [Test]
        public void PlatesAndIncensesBoostOnlyTheirOwnMoveType()
        {
            var me = Poke(0, item: 298);
            var (es, env) = World(me);
            env.ItemAttackValue = 20;
            ItemHandlers.Add(es, me);
            es.SetConstValue(L.POKEID_ATK, 0);
            es.SetConstValue(L.WAZA_TYPE, 9);
            es.SetMulValue(L.WAZA_POWER_RATIO, 0x1000, 0x29, 0x200000);
            es.CallEvent(EventId.WAZA_POWER);
            Assert.AreEqual(ItemHandlers.AttackValueToRatio(20), es.GetValue(L.WAZA_POWER_RATIO), "Feuer-Tafel auf Feuer");
            es.VarPop();
            es.VarPush();
            es.SetConstValue(L.POKEID_ATK, 0);
            es.SetConstValue(L.WAZA_TYPE, 10);
            es.SetMulValue(L.WAZA_POWER_RATIO, 0x1000, 0x29, 0x200000);
            es.CallEvent(EventId.WAZA_POWER);
            Assert.AreEqual(0x1000, es.GetValue(L.WAZA_POWER_RATIO), "andere Typen unveraendert");
        }

        [Test]
        public void WazaHandlersRegisterWithWazaPriority()
        {
            var me = Poke(0);
            var (es, _) = World(me);
            var f = WazaHandlers.Add(es, 512, 0, 7);
            Assert.IsNotNull(f);
            Assert.AreEqual(EventFactorType.WAZA, f.FactorType);
            Assert.AreEqual((uint)((9 - (int)EventPriority.WAZA) << 24) | 7u, f.Priority);
            Assert.IsNull(WazaHandlers.Add(es, 1, 0, 0), "Attacke ohne Handler");
        }

        [Test]
        public void AcrobatDoublesItsPowerWithoutAnItemOnly()
        {
            foreach (var (item, expected) in new[] { ((ushort)0, 110), ((ushort)5, 55) })
            {
                var me = Poke(0, item: item);
                var (es, _) = World(me);
                WazaHandlers.Add(es, 512, 0, 0);
                es.SetConstValue(L.POKEID_ATK, 0);
                es.SetRewriteOnceValue(L.WAZA_POWER, 55);
                es.CallEvent(EventId.WAZA_POWER_BASE);
                Assert.AreEqual(expected, es.GetValue(L.WAZA_POWER));
            }
        }

        [Test]
        public void MorningSunHealsByWeather()
        {
            var me = Poke(0);
            var (es, env) = World(me);
            WazaHandlers.Add(es, 234, 0, 0);
            foreach (var (weather, expected) in new[] { (0, 0x800), (1, 0xAAC), (2, 0x400), (4, 0x400), (6, 0xAAC), (7, 0x800) })
            {
                env.LocalWeather = weather;
                es.VarPush();
                es.SetConstValue(L.POKEID_ATK, 0);
                es.SetValue(L.RATIO, 0x800);
                es.CallEvent(EventId.RECOVER_HP_RATIO);
                Assert.AreEqual(expected, es.GetValue(L.RATIO), "Wetter " + weather);
                es.VarPop();
            }
        }

        [Test]
        public void SuperFangStyleDamageHalvesTheFoeHp()
        {
            var me = Poke(0);
            var foe = Poke(1);
            foe.Hp = 101;
            var (es, _) = World(me, foe);
            WazaHandlers.Add(es, 162, 0, 0);
            es.SetConstValue(L.POKEID_ATK, 0);
            es.SetConstValue(L.POKEID_DEF, 1);
            es.SetValue(L.FIX_DAMAGE, 0);
            es.SetValue(L.FIX_DAMAGE_FLAG, 0);
            es.CallEvent(EventId.WAZA_DMG_PROC1);
            Assert.AreEqual(50, es.GetValue(L.FIX_DAMAGE));
            Assert.AreEqual(1, es.GetValue(L.FIX_DAMAGE_FLAG));
        }
    }
}
