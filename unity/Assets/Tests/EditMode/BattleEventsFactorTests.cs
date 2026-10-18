using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle.Events;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Faktor-Registrierung, Reihenfolge, Aufruf-Schleife (Spezifikation docs/kampf-spezifikation-2.md Abschnitte 3 und 4).
    // Die Fixtures stammen aus den echten Funktionen (scripts/battle_oracle_heap.py); die Handtests rechnen aus dem Text.
    public class BattleEventsFactorTests
    {
        static EventHandlerTable[] Table(EventId ev, EventHandlerDelegate handler = null) =>
            new[] { new EventHandlerTable(ev, handler ?? ((a, d) => { })) };

        static EventSystem NewSystem(BattleEventsTestEnv env = null)
        {
            var es = new EventSystem(env ?? new BattleEventsTestEnv());
            es.VarPush();
            return es;
        }

        static EventFactor Add(EventSystem es, EventFactorType type, ushort sub, EventPriority pri, uint subPri, byte depend, EventHandlerTable[] table) =>
            es.AddFactor(type, sub, pri, subPri, depend, table, (byte)table.Length);

        // ------------------------------------------------------------------------------------------------------
        // Prioritaet und Reihenfolge
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void PriorityInvertsMainPriorityAndKeepsSubPriorityInTheLow24Bits()
        {
            Assert.AreEqual(0x9000000u, EventFactorContainer.CalcFactorPriority(EventPriority.DEFAULT_POWERUP, 0));
            Assert.AreEqual(0x8000005u, EventFactorContainer.CalcFactorPriority(EventPriority.WAZA, 5));
            Assert.AreEqual(0x2000000u | 0xFFFFFFu, EventFactorContainer.CalcFactorPriority(EventPriority.TOKUSEI, 0xFFFFFF));
            Assert.AreEqual(0x1000000u, EventFactorContainer.CalcFactorPriority(EventPriority.ITEM, 0));
            Assert.AreEqual(0u, EventFactorContainer.CalcFactorPriority(EventPriority.TOKUSEI_atodasi, 0));
        }

        [Test]
        public void ListIsOrderedByMainPriorityThenSubPriorityThenRegistrationOrder()
        {
            var es = NewSystem();
            var item = Add(es, EventFactorType.ITEM, 1, EventPriority.ITEM, 100, 0, Table(EventId.ACTPROC_START));
            var tokFast = Add(es, EventFactorType.TOKUSEI, 2, EventPriority.TOKUSEI, 200, 1, Table(EventId.ACTPROC_START));
            var tokSlow = Add(es, EventFactorType.TOKUSEI, 3, EventPriority.TOKUSEI, 50, 2, Table(EventId.ACTPROC_START));
            var waza = Add(es, EventFactorType.WAZA, 4, EventPriority.WAZA, 0, 0, Table(EventId.ACTPROC_START));
            var side = Add(es, EventFactorType.SIDE, 5, EventPriority.SIDE, 0, 1, Table(EventId.ACTPROC_START));
            var tokTie = Add(es, EventFactorType.TOKUSEI, 6, EventPriority.TOKUSEI, 200, 3, Table(EventId.ACTPROC_START));
            var late = Add(es, EventFactorType.TOKUSEI, 7, EventPriority.TOKUSEI_atodasi, 999, 0, Table(EventId.ACTPROC_START));
            var order = new List<EventFactor>();
            for (var f = es.Container.First; f != null; f = f.Next) order.Add(f);
            // Attacke, Seite, Faehigkeit schnell, Faehigkeit gleich schnell (spaeter registriert), Faehigkeit langsam, Item, "atodasi"
            CollectionAssert.AreEqual(new[] { waza, side, tokFast, tokTie, tokSlow, item, late }, order);
        }

        [Test]
        public void InstanceIdsAreHandedOutFromTheTopOfThePool()
        {
            var es = NewSystem();
            var a = Add(es, EventFactorType.FIELD, 0, EventPriority.FIELD, 0, 0, Table(EventId.ACTPROC_START));
            var b = Add(es, EventFactorType.FIELD, 0, EventPriority.FIELD, 0, 0, Table(EventId.ACTPROC_START));
            Assert.AreEqual(171, a.InstanceId);
            Assert.AreEqual(170, b.InstanceId);
            Assert.AreEqual(170, es.Container.StoredCount);
            es.RemoveFactor(a);
            Assert.AreEqual(171, es.Container.StoredCount);
            // das zuletzt freigegebene Objekt wird zuerst wiederverwendet
            var c = Add(es, EventFactorType.FIELD, 0, EventPriority.FIELD, 0, 0, Table(EventId.ACTPROC_START));
            Assert.AreEqual(171, c.InstanceId);
        }

        [Test]
        public void PoolOfFactorsIsFiniteAndReturnsNullWhenExhausted()
        {
            var es = NewSystem();
            for (int i = 0; i < EventFactorContainer.FactorRegisterMax; i++)
                Assert.IsNotNull(Add(es, EventFactorType.TOKUSEI, (ushort)i, EventPriority.TOKUSEI, 0, 0, Table(EventId.ACTPROC_START)), "Faktor " + i);
            Assert.IsNull(Add(es, EventFactorType.TOKUSEI, 999, EventPriority.TOKUSEI, 0, 0, Table(EventId.ACTPROC_START)));
        }

        [Test]
        public void PokeIdIsOnlyStoredForWazaTokuseiAndItemFactors()
        {
            var es = NewSystem();
            foreach (var type in new[] { EventFactorType.WAZA, EventFactorType.TOKUSEI, EventFactorType.ITEM })
                Assert.AreEqual(2, Add(es, type, 1, EventPriority.WAZA, 0, 2, Table(EventId.ACTPROC_START)).PokeId);
            foreach (var type in new[] { EventFactorType.POS, EventFactorType.SIDE, EventFactorType.FIELD, EventFactorType.DEFAULT_POWERUP, EventFactorType.RAIDBOSS })
                Assert.AreEqual(0x1F, Add(es, type, 1, EventPriority.WAZA, 0, 2, Table(EventId.ACTPROC_START)).PokeId, type.ToString());
        }

        [Test]
        public void SeekAndGetNextFollowTypeAndDependId()
        {
            var es = NewSystem();
            var t1 = Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 30, 1, Table(EventId.ACTPROC_START));
            var t2 = Add(es, EventFactorType.TOKUSEI, 2, EventPriority.TOKUSEI, 20, 2, Table(EventId.ACTPROC_START));
            var t3 = Add(es, EventFactorType.TOKUSEI, 3, EventPriority.TOKUSEI, 10, 1, Table(EventId.ACTPROC_START));
            Add(es, EventFactorType.ITEM, 4, EventPriority.ITEM, 10, 1, Table(EventId.ACTPROC_START));
            var c = es.Container;
            Assert.AreSame(t1, c.SeekFactor(EventFactorType.TOKUSEI));
            Assert.AreSame(t2, c.SeekFactor(EventFactorType.TOKUSEI, 2));
            Assert.AreSame(t3, c.GetNextFactor(t1, false), "gleiche dependID ueberspringt t2");
            Assert.AreSame(t2, c.GetNextFactor(t1, true), "beliebige dependID");
            Assert.IsNull(c.GetNextFactor(t3, true), "das Item hat einen anderen Typ");
            Assert.IsNull(c.SeekFactor(EventFactorType.SIDE));
            t2.SetRemoveReserveFlag(true);
            Assert.AreSame(t1, c.SeekFactor(EventFactorType.TOKUSEI, 1));
            Assert.IsNull(c.SeekFactor(EventFactorType.TOKUSEI, 2), "Faktoren mit Loeschvormerkung zaehlen nicht");
        }

        [Test]
        public void SwapFactorsSideEffectExchangesTheSidesOfMatchingFactors()
        {
            var es = NewSystem();
            var a = Add(es, EventFactorType.SIDE, 7, EventPriority.SIDE, 0, 0, Table(EventId.ACTPROC_START));
            var b = Add(es, EventFactorType.SIDE, 7, EventPriority.SIDE, 0, 1, Table(EventId.ACTPROC_START));
            var other = Add(es, EventFactorType.SIDE, 8, EventPriority.SIDE, 0, 0, Table(EventId.ACTPROC_START));
            es.Container.SwapFactorsSideEffect(0, 1, 7);
            Assert.AreEqual(1, a.DependId);
            Assert.AreEqual(0, b.DependId);
            Assert.AreEqual(0, other.DependId);
        }

        // ------------------------------------------------------------------------------------------------------
        // Aufruf-Schleife
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void CallEventInvokesMatchingHandlersInListOrderWithTheirDependId()
        {
            var es = NewSystem();
            var log = new List<string>();
            Add(es, EventFactorType.ITEM, 1, EventPriority.ITEM, 0, 5, Table(EventId.TURN_END, (a, d) => log.Add("item" + d)));
            Add(es, EventFactorType.TOKUSEI, 2, EventPriority.TOKUSEI, 0, 6, Table(EventId.TURN_END, (a, d) => log.Add("tok" + d)));
            Add(es, EventFactorType.TOKUSEI, 3, EventPriority.TOKUSEI, 0, 7, Table(EventId.ACTPROC_END, (a, d) => log.Add("other")));
            Add(es, EventFactorType.WAZA, 4, EventPriority.WAZA, 0, 8, Table(EventId.TURN_END, (a, d) => log.Add("waza" + d)));
            es.CallEvent(EventId.TURN_END);
            CollectionAssert.AreEqual(new[] { "waza8", "tok6", "item5" }, log);
        }

        [Test]
        public void OnlyTheFirstTableEntryForAnEventRuns()
        {
            var es = NewSystem();
            var log = new List<string>();
            var table = new[]
            {
                new EventHandlerTable(EventId.TURN_END, (a, d) => log.Add("first")),
                new EventHandlerTable(EventId.TURN_END, (a, d) => log.Add("second")),
            };
            Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 0, table);
            es.CallEvent(EventId.TURN_END);
            CollectionAssert.AreEqual(new[] { "first" }, log);
        }

        [Test]
        public void HandlerCanRemoveItselfAndTheRemovalIsDeferredUntilItReturns()
        {
            var es = NewSystem();
            EventFactor self = null;
            bool existedInsideHandler = false;
            self = Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END, (a, d) =>
            {
                es.RemoveFactor(self);
                existedInsideHandler = self.Exists && self.RemoveReserve;
            }));
            es.CallEvent(EventId.TURN_END);
            Assert.IsTrue(existedInsideHandler, "waehrend des Handlers nur vorgemerkt");
            Assert.IsNull(es.Container.First);
            Assert.AreEqual(EventFactorContainer.FactorRegisterMax, es.Container.StoredCount);
        }

        [Test]
        public void RemovingALaterFactorDuringACallSkipsIt()
        {
            var es = NewSystem();
            var log = new List<string>();
            EventFactor second = null;
            Add(es, EventFactorType.WAZA, 1, EventPriority.WAZA, 0, 0, Table(EventId.TURN_END, (a, d) => { log.Add("a"); es.RemoveFactor(second); }));
            second = Add(es, EventFactorType.TOKUSEI, 2, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END, (a, d) => log.Add("b")));
            Add(es, EventFactorType.ITEM, 3, EventPriority.ITEM, 0, 0, Table(EventId.TURN_END, (a, d) => log.Add("c")));
            es.CallEvent(EventId.TURN_END);
            CollectionAssert.AreEqual(new[] { "a", "c" }, log);
        }

        [Test]
        public void SleepingFactorsAreSkippedUntilWoken()
        {
            var es = NewSystem();
            int calls = 0;
            Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 3, Table(EventId.TURN_END, (a, d) => calls++));
            es.SleepFactors(3, EventFactorType.TOKUSEI);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(0, calls);
            es.SleepFactors(3, EventFactorType.ITEM);
            es.WakeFactors(3, EventFactorType.ITEM);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(0, calls, "andere Art, bleibt schlafen");
            es.WakeFactors(3, EventFactorType.TOKUSEI);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls);
        }

        [Test]
        public void TargetTypeRestrictsTheCallAndTempItemEventNeedsTheFlag()
        {
            var es = NewSystem();
            var log = new List<string>();
            Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END, (a, d) => log.Add("tok")));
            Add(es, EventFactorType.ITEM, 2, EventPriority.ITEM, 0, 0, Table(EventId.TURN_END, (a, d) => log.Add("item")));
            es.CallEventTargetType(EventId.TURN_END, EventFactorType.ITEM);
            CollectionAssert.AreEqual(new[] { "item" }, log);

            log.Clear();
            var tmp = Add(es, EventFactorType.ITEM, 3, EventPriority.ITEM, 0, 0, Table(EventId.USE_ITEM_TMP, (a, d) => log.Add("tmp")));
            es.CallEvent(EventId.USE_ITEM_TMP);
            Assert.IsEmpty(log);
            tmp.SetTempItemFlag();
            es.CallEvent(EventId.USE_ITEM_TMP);
            CollectionAssert.AreEqual(new[] { "tmp" }, log);
        }

        [Test]
        public void ReentryIsBlockedUnlessTheFactorEnablesRecall()
        {
            var es = NewSystem();
            int depth = 0, maxDepth = 0, calls = 0;
            bool recall = false;
            EventFactor f = null;
            f = Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END, (a, d) =>
            {
                calls++;
                depth++;
                maxDepth = Math.Max(maxDepth, depth);
                if (calls == 1)
                {
                    if (recall) f.SetRecallEnable();
                    es.CallEvent(EventId.TURN_END);
                }
                depth--;
            }));
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls, "ohne Recall wird die Rekursion uebersprungen");
            recall = true;
            calls = 0;
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(2, calls);
            Assert.AreEqual(2, maxDepth);
            Assert.IsFalse(f.Calling);
            Assert.IsFalse(f.RecallEnable);
        }

        [Test]
        public void EventLevelOfALateFactorHidesItFromTheCallThatCreatedIt()
        {
            var es = NewSystem();
            var log = new List<string>();
            EventFactor added = null;
            Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 100, 0, Table(EventId.TURN_END, (a, d) =>
            {
                log.Add("creator");
                added = es.AddFactor(EventFactorType.ITEM, 2, EventPriority.ITEM, 0, 0,
                    Table(EventId.TURN_END, (x, y) => log.Add("late")), 1);
                Assert.AreEqual(1u, es.EventLevel);
                Assert.AreEqual(1u, added.EventLevel);
            }));
            es.CallEvent(EventId.TURN_END);
            CollectionAssert.AreEqual(new[] { "creator" }, log, "gleiche Tiefe: der neue Faktor reagiert nicht");
            Assert.AreEqual(0u, added.EventLevel, "nach dem aeusseren Aufruf wird die Stufe zurueckgesetzt");
            es.CallEvent(EventId.TURN_END);
            CollectionAssert.AreEqual(new[] { "creator", "creator", "late" }, log.Take(3));
        }

        [Test]
        public void NestedCallSeesItsOwnVariablesWhenTheHandlerPushesAFrame()
        {
            var es = NewSystem();
            es.SetValue(EventVarLabel.POWER, 5);
            int inner = -1;
            Add(es, EventFactorType.WAZA, 1, EventPriority.WAZA, 0, 0, Table(EventId.ACTPROC_START, (a, d) =>
            {
                a.System.VarPush();
                a.System.SetValue(EventVarLabel.POWER, 9);
                a.System.CallEvent(EventId.ACTPROC_END);
                a.System.VarPop();
            }));
            Add(es, EventFactorType.WAZA, 2, EventPriority.WAZA, 0, 0, Table(EventId.ACTPROC_END, (a, d) => inner = a.GetVar(EventVarLabel.POWER)));
            es.CallEvent(EventId.ACTPROC_START);
            Assert.AreEqual(9, inner);
            Assert.AreEqual(5, es.GetValue(EventVarLabel.POWER));
        }

        [Test]
        public void IsolateFactorsAreRemovedByRemoveIsolateFactors()
        {
            var es = NewSystem();
            var f = Add(es, EventFactorType.TOKUSEI, 1, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END));
            var keep = Add(es, EventFactorType.TOKUSEI, 2, EventPriority.TOKUSEI, 0, 0, Table(EventId.TURN_END));
            f.ConvertForIsolate();
            Assert.IsTrue(f.IsIsolateMode);
            es.RemoveIsolateFactors();
            Assert.IsFalse(f.Exists);
            Assert.AreSame(keep, es.Container.First);
        }

        // ------------------------------------------------------------------------------------------------------
        // Ueberspringen (checkHandlerSkip)
        // ------------------------------------------------------------------------------------------------------

        static BattleEventsTestEnv EnvWithPoke(out BattlePoke poke)
        {
            var env = new BattleEventsTestEnv();
            poke = new BattlePoke(1);
            env.AddPoke(poke);
            return env;
        }

        [Test]
        public void TokuseiHandlersAreSkippedByGastroAcidGasAndTransformOrGModeTables()
        {
            var env = EnvWithPoke(out var poke);
            var es = NewSystem(env);
            int calls = 0;
            Add(es, EventFactorType.TOKUSEI, 77, EventPriority.TOKUSEI, 0, 1, Table(EventId.TURN_END, (a, d) => calls++));
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls);
            poke.SetSick(WazaSickIds.IEKI, 1);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls, "Magensaeure");
            poke.SetSick(WazaSickIds.IEKI, 0);
            poke.TokuseiDisabledByGas = true;
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls, "Chemisches Gas");
            poke.TokuseiDisabledByGas = false;
            poke.IsTransformed = true;
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(2, calls, "verwandelt, aber nicht in der Auslassungstabelle");
            poke.SetSick(WazaSickIds.IEKI, 1);
            es.CallEventForce(EventId.TURN_END);
            Assert.AreEqual(3, calls, "CallEventForce prueft nichts");
        }

        [Test]
        public void ItemHandlersAreSkippedByMagicRoomEmbargoAndTheTurnFlagExceptOnEvolution()
        {
            var env = EnvWithPoke(out var poke);
            var es = NewSystem(env);
            int turnEnd = 0, evo = 0;
            es.AddFactor(EventFactorType.ITEM, 9, EventPriority.ITEM, 0, 1, new[]
            {
                new EventHandlerTable(EventId.TURN_END, (a, d) => turnEnd++),
                new EventHandlerTable(EventId.MEMBER_IN_EVO, (a, d) => evo++),
            }, 2);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, turnEnd);
            poke.SetSick(WazaSickIds.SASIOSAE, 1);
            es.CallEvent(EventId.TURN_END);
            es.CallEvent(EventId.MEMBER_IN_EVO);
            Assert.AreEqual(1, turnEnd, "Embargo sperrt");
            Assert.AreEqual(1, evo, "MEMBER_IN_EVO ist ausgenommen");
            poke.SetSick(WazaSickIds.SASIOSAE, 0);
            poke.SetTurnFlag(TurnFlags.ItemCantUse, true);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, turnEnd, "Zug-Flag 9 sperrt");
        }

        [Test]
        public void AnotherFactorsSkipHandlerCanVetoAHandler()
        {
            var env = EnvWithPoke(out _);
            var es = NewSystem(env);
            int calls = 0;
            Add(es, EventFactorType.TOKUSEI, 5, EventPriority.TOKUSEI, 0, 1, Table(EventId.TURN_END, (a, d) => calls++));
            var breaker = Add(es, EventFactorType.WAZA, 6, EventPriority.WAZA, 0, 2, Table(EventId.ACTPROC_END));
            breaker.AttachSkipCheckHandler(a => a.FactorType == EventFactorType.TOKUSEI && a.SubId == 5 && a.EventId == EventId.TURN_END);
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(0, calls);
            breaker.DetachSkipCheckHandler();
            es.CallEvent(EventId.TURN_END);
            Assert.AreEqual(1, calls);
        }

        // ------------------------------------------------------------------------------------------------------
        // Gegen die echten Funktionen (Orakel-Fixtures)
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void RegistrationOrderAndSeekMatchTheRealContainer()
        {
            var cases = Cases(Load("BattleEventsOrder.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 60);
            foreach (var c in cases)
            {
                var sc = new BattleEventsScenario(new BattleEventsTestEnv());
                foreach (var spec in (List<object>)c["adds"]) sc.AddFactor((Dictionary<string, object>)spec);
                foreach (var k in LongList(c["removes"])) sc.Es.RemoveFactor(sc.Added[(int)k]);
                string where = "Fall " + cases.IndexOf(c);
                var ids = LongList(c["ids"]);
                CollectionAssert.AreEqual(ids, sc.Added.Select(f => f == null ? -1L : f.InstanceId).ToList(), where + " ids");
                var expected = Matrix(c["order"]);
                var actual = sc.FactorList();
                Assert.AreEqual(expected.Count, actual.Count, where + " Anzahl");
                for (int i = 0; i < actual.Count; i++) CollectionAssert.AreEqual(expected[i], actual[i], where + " Faktor " + i);
                Assert.AreEqual(L(c, "stored"), sc.Es.Container.StoredCount, where + " Vorrat");
                foreach (var q in Cases(c, "seek"))
                {
                    var type = (EventFactorType)I(q, "type");
                    byte dep = (byte)I(q, "depend");
                    var container = sc.Es.Container;
                    var byType = new List<long>();
                    var first = container.SeekFactor(type);
                    Assert.AreEqual(L(q, "firstType"), first == null ? -1 : first.InstanceId, where + " SeekFactor(Typ)");
                    for (var f = first; f != null; f = container.GetNextFactor(f, true)) byType.Add(f.InstanceId);
                    CollectionAssert.AreEqual(LongList(q["byType"]), byType, where + " GetNext(beliebig)");
                    var byDep = new List<long>();
                    var firstDep = container.SeekFactor(type, dep);
                    Assert.AreEqual(L(q, "firstTypeDepend"), firstDep == null ? -1 : firstDep.InstanceId, where + " SeekFactor(Typ, dependID)");
                    for (var f = firstDep; f != null; f = container.GetNextFactor(f, false)) byDep.Add(f.InstanceId);
                    CollectionAssert.AreEqual(LongList(q["byTypeDepend"]), byDep, where + " GetNext(dependID)");
                }
            }
        }

        [Test]
        public void CallLoopWithRemovalsAdditionsRecallAndNestingMatchesTheRealSystem()
        {
            var cases = Cases(Load("BattleEventsCall.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 100);
            int invocations = 0;
            foreach (var c in cases)
            {
                string where = "Fall " + cases.IndexOf(c);
                var sc = new BattleEventsScenario(BattleEventsTestEnv.FromJson((Dictionary<string, object>)c["env"]));
                foreach (var spec in (List<object>)c["adds"]) sc.AddFactor((Dictionary<string, object>)spec);
                sc.Log.Clear();
                foreach (var step in (List<object>)c["steps"]) sc.Exec((List<object>)step);

                var expectedLog = Matrix(c["log"]);
                int common = Math.Min(expectedLog.Count, sc.Log.Count);
                for (int i = 0; i < common; i++)
                {
                    if (expectedLog[i].SequenceEqual(sc.Log[i])) continue;
                    string Show(IEnumerable<IEnumerable<long>> log) => string.Join(" ", log.Skip(Math.Max(0, i - 3)).Take(7).Select(e => "[" + string.Join(",", e) + "]"));
                    Assert.Fail($"{where} Protokoll {i}: erwartet {Show(expectedLog)} aber {Show(sc.Log)}");
                }
                Assert.AreEqual(expectedLog.Count, sc.Log.Count, where + " Anzahl der Aufrufe");
                invocations += expectedLog.Count;

                var expectedAfter = Matrix(c["after"]);
                var after = sc.FactorList();
                Assert.AreEqual(expectedAfter.Count, after.Count, where + " Faktoren danach");
                for (int i = 0; i < after.Count; i++) CollectionAssert.AreEqual(expectedAfter[i], after[i], where + " Faktor " + i);
                Assert.AreEqual(L(c, "stored"), sc.Es.Container.StoredCount, where + " Vorrat");
                Assert.AreEqual(L(c, "level"), sc.Es.EventLevel, where + " Tiefe");
                CollectionAssert.AreEqual(LongList(c["sp"]), sc.StackPointers(), where + " Stapelzeiger");
                var expectedVars = Matrix(c["vars"]);
                var vars = sc.VarSnapshot();
                Assert.AreEqual(expectedVars.Count, vars.Count, where + " Variablen");
                for (int i = 0; i < vars.Count; i++) CollectionAssert.AreEqual(expectedVars[i], vars[i], where + " Variable " + i);
            }
            Assert.GreaterOrEqual(invocations, 1500);
        }
    }
}
