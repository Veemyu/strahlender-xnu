using System;
using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Battle.Flow;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Vergleicht die Ablauf-Regeln aus Xnu.Battle.Flow mit den Fixtures des Orakels (scripts/battle_oracle_flow.py, echte ARM64-Funktionen).
    public class BattleFlowOracleTests
    {
        static Dictionary<string, object> _root;

        static Dictionary<string, object> Group(string name)
        {
            if (_root == null) _root = Load("BattleFlow.json");
            return (Dictionary<string, object>)_root[name];
        }

        static ulong[] ULongs(object list)
        {
            var l = (List<object>)list;
            var r = new ulong[l.Count];
            for (int i = 0; i < r.Length; i++) r[i] = ulong.Parse((string)l[i]);
            return r;
        }

        static byte[] Bytes(object list)
        {
            var l = (List<object>)list;
            var r = new byte[l.Count];
            for (int i = 0; i < r.Length; i++) r[i] = Convert.ToByte(l[i]);
            return r;
        }

        [Test]
        public void ActPriMatchesTheRealFunctions()
        {
            var cases = Cases(Group("actpri"), "cases");
            Assert.GreaterOrEqual(cases.Count, 500);
            foreach (var c in cases)
            {
                Assert.AreEqual(U32(c, "make"), ActPri.Make(U32(c, "dominant"), U32(c, "operation"), U32(c, "wazaPri"), U32(c, "spPri"), U32(c, "agility")));
                uint pri = U32(c, "pri"), v = U32(c, "value");
                Assert.AreEqual(U32(c, "changeAgility"), ActPri.ChangeAgility(pri, v));
                Assert.AreEqual(U32(c, "changeWazaPriority"), ActPri.ChangeWazaPriority(pri, v));
                Assert.AreEqual(U32(c, "getWazaPri"), ActPri.GetWazaPri(pri));
                Assert.AreEqual(U32(c, "getSpPri"), ActPri.GetSpPri(pri));
                Assert.AreEqual(U32(c, "getOperationPri"), ActPri.GetOperationPri(pri));
                Assert.AreEqual(U32(c, "getDominantPri"), ActPri.GetDominantPri(pri));
                Assert.AreEqual(U32(c, "setDominantPri"), ActPri.SetDominantPri(pri, v));
                Assert.AreEqual(U32(c, "setSpPri"), ActPri.SetSpPri(pri, v));
                Assert.AreEqual(U32(c, "toHandlerPri"), ActPri.ToHandlerPri(pri));
                Assert.AreEqual(I(c, "toWazaOrgPri"), ActPri.ToWazaOrgPri(pri));
            }
        }

        static ulong BuildCont(string kind, List<long> a)
        {
            uint u(int i) => (uint)a[i];
            switch (kind)
            {
                case "makeNull": return SickCont.MakeNull();
                case "makeTurn": return SickCont.MakeTurn(u(0), u(1));
                case "makeTurnParam": return SickCont.MakeTurnParam(u(0), u(1), u(2));
                case "makePoke": return SickCont.MakePoke(u(0), u(1));
                case "makePermanent": return SickCont.MakePermanent(u(0));
                case "makePermanentInc": return SickCont.MakePermanentInc(u(0), u(1));
                case "makePermanentParam": return SickCont.MakePermanentParam(u(0), u(1));
                case "makePermanentIncParam": return SickCont.MakePermanentIncParam(u(0), u(1), u(2));
                case "makePokeTurn": return SickCont.MakePokeTurn(u(0), u(1), u(2));
                case "makePokeTurnParam": return SickCont.MakePokeTurnParam(u(0), u(1), u(2), u(3));
                case "makeMoudokuCont": return SickCont.MakeMoudokuCont(u(0));
                default: throw new ArgumentException(kind);
            }
        }

        [Test]
        public void SickContPackingMatchesTheRealFunctions()
        {
            var cases = Cases(Group("sickcont"), "cases");
            Assert.GreaterOrEqual(cases.Count, 600);
            var kinds = new HashSet<string>();
            foreach (var c in cases)
            {
                string kind = (string)c["kind"];
                kinds.Add(kind);
                ulong packed = BuildCont(kind, LongList(c["args"]));
                Assert.AreEqual(U64(c, "packed"), packed, kind);
                Assert.AreEqual(B(c, "isNull"), SickCont.IsNull(packed));
                Assert.AreEqual(B(c, "isMoudokuCont"), SickCont.IsMoudokuCont(packed));
                Assert.AreEqual(I(c, "getPokeID"), SickCont.GetPokeId(packed), kind);
                Assert.AreEqual(I(c, "getTurnMax"), SickCont.GetTurnMax(packed), kind);
                Assert.AreEqual(I(c, "getParam"), SickCont.GetParam(packed), kind);
            }
            Assert.AreEqual(11, kinds.Count);
        }

        [Test]
        public void SickTurnCheckMatchesTheRealFunction()
        {
            var cases = Cases(Group("sickturn"), "turnCheck");
            int cured = 0, active = 0;
            foreach (var c in cases)
            {
                int sick = I(c, "sick");
                var conts = ULongs(c["conts"]);
                var counters = Bytes(c["counters"]);
                bool ret = FlowRules.WazaSickTurnCheck(sick, ref conts[sick], ref counters[sick], out bool didCure, out ulong before);
                Assert.AreEqual(B(c, "ret"), ret, $"sick {sick}");
                Assert.AreEqual(U64(c, "outCont"), before);
                Assert.AreEqual(B(c, "outFlag"), didCure);
                CollectionAssert.AreEqual(ULongs(c["contsAfter"]), conts);
                CollectionAssert.AreEqual(Bytes(c["countersAfter"]), counters);
                if (didCure) cured++;
                if (ret) active++;
            }
            Assert.Greater(cured, 50);
            Assert.Greater(active, 300);
        }

        [Test]
        public void SleepAndConfusionWakeUpMatchTheRealFunctions()
        {
            foreach (var c in Cases(Group("sickturn"), "nemuri"))
            {
                byte counter = (byte)I(c, "counter");
                bool wake = FlowRules.CheckSleepWakeUp(U64(c, "cont"), ref counter, (ushort)I(c, "tokusei"));
                Assert.AreEqual(B(c, "ret"), wake);
                Assert.AreEqual(I(c, "counterAfter"), counter);
            }
            foreach (var c in Cases(Group("sickturn"), "konran"))
            {
                byte counter = (byte)I(c, "counter");
                bool wake = FlowRules.CheckConfusionWakeUp(U64(c, "cont"), ref counter);
                Assert.AreEqual(B(c, "ret"), wake);
                Assert.AreEqual(I(c, "counterAfter"), counter);
            }
        }

        [Test]
        public void SickDamageMatchesTheRealFunction()
        {
            var cases = Cases(Group("sickturn"), "sickDamage");
            int nonZero = 0;
            foreach (var c in cases)
            {
                int sick = I(c, "sick");
                var conts = ULongs(c["conts"]);
                var counters = Bytes(c["counters"]);
                uint dmg = FlowRules.CalcSickDamage(sick, conts[sick], counters[sick], (uint)I(c, "maxHp"), (ushort)I(c, "effTokusei"), conts[Sick.Sleep]);
                Assert.AreEqual(U32(c, "damage"), dmg, $"sick {sick}");
                if (dmg != 0) nonZero++;
            }
            Assert.Greater(nonZero, 100);
        }

        [Test]
        public void EscapeFormulaMatchesTheRealFunction()
        {
            var cases = Cases(Group("escape"), "cases");
            int ok = 0;
            foreach (var c in cases)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                bool res = FlowRules.EscapeByAgility((uint)I(c, "own"), (uint)I(c, "foe"), (uint)I(c, "tries"), rng);
                Assert.AreEqual(B(c, "ok"), res, $"own {c["own"]} foe {c["foe"]} tries {c["tries"]}");
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
                if (res) ok++;
            }
            Assert.Greater(ok, 100);
            Assert.Less(ok, cases.Count);
        }

        [Test]
        public void ActionOrderSortMatchesTheRealFunction()
        {
            var cases = Cases(Group("sort"), "cases");
            int ties = 0;
            foreach (var c in cases)
            {
                var pris = LongList(c["pris"]);
                var items = new List<int>();
                for (int i = 0; i < pris.Count; i++) items.Add(i);
                var rng = new BattleRandom(U64(c, "seed"));
                FlowRules.SortActionOrder(items, i => (uint)pris[i], rng);
                CollectionAssert.AreEqual(LongList(c["order"]), items.ConvertAll(i => (long)i));
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
                if (new HashSet<long>(pris).Count < pris.Count) ties++;
            }
            Assert.Greater(ties, 100);
        }

        [Test]
        public void AgilityMatchesTheRealFunction()
        {
            var cases = Cases(Group("agility"), "cases");
            foreach (var c in cases)
            {
                int gen = I(c, "genAfter");
                uint res = FlowRules.FinishAgility((uint)I(c, "value"), U32(c, "ratioIn"), I(c, "sick") == Sick.Paralysis, gen == -1 || gen != 0,
                    (I(c, "flag") & 1) != 0, B(c, "trick"));
                Assert.AreEqual(I(c, "out"), (int)res);
            }
        }

        [Test]
        public void ConfusionDamageMatchesTheRealFunction()
        {
            foreach (var c in Cases(Group("confdmg"), "cases"))
            {
                var rng = new BattleRandom(U64(c, "seed"));
                uint dmg = FlowRules.ConfusionDamage((uint)I(c, "atk"), (uint)I(c, "def"), (uint)I(c, "level"), rng);
                Assert.AreEqual(U32(c, "damage"), dmg);
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
            }
        }

        [Test]
        public void TurnCheckSickOrderMatchesTheStaticTable()
        {
            var expected = LongList(((Dictionary<string, object>)Group("tables"))["turnCheckSickOrder"]);
            var actual = new List<long>();
            foreach (int v in FlowRules.TurnCheckSickOrder) actual.Add(v);
            CollectionAssert.AreEqual(expected, actual);
        }
    }
}
