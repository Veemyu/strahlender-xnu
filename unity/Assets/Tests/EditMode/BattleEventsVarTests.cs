using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle.Events;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Ereignis-Variablen (EventVar, Stapel, Rahmen) gegen die echten Funktionen (Orakel-Fixture BattleEventsVar.json)
    // und handgerechnete Beispiele (Spezifikation docs/kampf-spezifikation-2.md Abschnitt 2).
    public class BattleEventsVarTests
    {
        static EventSystem NewSystem()
        {
            var es = new EventSystem(new BattleEventsTestEnv());
            es.VarPush();
            return es;
        }

        [Test]
        public void SetValueIsAlwaysRewritableAndMissingLabelsReadAsZero()
        {
            var es = NewSystem();
            es.SetValue(EventVarLabel.POWER, 77);
            Assert.AreEqual(77, es.GetValue(EventVarLabel.POWER));
            Assert.IsTrue(es.RewriteValue(EventVarLabel.POWER, 5));
            Assert.IsTrue(es.RewriteValue(EventVarLabel.POWER, 6));
            Assert.AreEqual(6, es.GetValue(EventVarLabel.POWER));
            Assert.AreEqual(0, es.GetValue(EventVarLabel.DAMAGE));
            Assert.IsFalse(es.TryGetValue(EventVarLabel.DAMAGE, out int missing));
            Assert.AreEqual(0, missing);
            Assert.IsTrue(es.TryGetValue(EventVarLabel.POWER, out int found));
            Assert.AreEqual(6, found);
        }

        [Test]
        public void RewriteOnceAllowsExactlyOneRewriteUntilRecovered()
        {
            var es = NewSystem();
            es.SetRewriteOnceValue(EventVarLabel.WAZA_POWER, 40);
            Assert.IsTrue(es.RewriteValue(EventVarLabel.WAZA_POWER, 50));
            Assert.IsFalse(es.RewriteValue(EventVarLabel.WAZA_POWER, 60));
            Assert.AreEqual(50, es.GetValue(EventVarLabel.WAZA_POWER));
            es.RecoverRewriteOncePermission(EventVarLabel.WAZA_POWER);
            Assert.IsTrue(es.RewriteValue(EventVarLabel.WAZA_POWER, 70));
            Assert.AreEqual(70, es.GetValue(EventVarLabel.WAZA_POWER));
        }

        [Test]
        public void ConstValuesCannotBeRewrittenOrMultiplied()
        {
            var es = NewSystem();
            es.SetConstValue(EventVarLabel.POKEID_ATK, 3);
            Assert.IsFalse(es.RewriteValue(EventVarLabel.POKEID_ATK, 9));
            es.MulValue(EventVarLabel.POKEID_ATK, 0x2000);
            Assert.AreEqual(3, es.GetValue(EventVarLabel.POKEID_ATK));
        }

        [Test]
        public void MulValueAppliesRatioWithHalfUpRoundingAndLimits()
        {
            var es = NewSystem();
            // 0x1000 * 0x14CD: (4096 * 5325 + 2048) >> 12 = 5325 (Handler-Verhaeltnis wird ohne Verlust gespeichert)
            es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x29, 0x20000);
            es.MulValue(EventVarLabel.RATIO, 0x14CD);
            Assert.AreEqual(0x14CD, es.GetValue(EventVarLabel.RATIO));
            // 5325 * 0x1800 = 32716800 (= 7987,5 * 4096); + 0x800 rundet "halb nach oben" auf 7988
            es.MulValue(EventVarLabel.RATIO, 0x1800);
            Assert.AreEqual(7988, es.GetValue(EventVarLabel.RATIO));
            // Untergrenze 0x29 greift, Obergrenze 0x20000 greift
            es.MulValue(EventVarLabel.RATIO, 0);
            Assert.AreEqual(0x29, es.GetValue(EventVarLabel.RATIO));
            es.SetMulValue(EventVarLabel.RATIO, 0x10000, 0x29, 0x20000);
            es.MulValue(EventVarLabel.RATIO, 0x10000);
            Assert.AreEqual(0x20000, es.GetValue(EventVarLabel.RATIO));
            // ohne Grenzen (beide 0) wird nicht geklemmt, negative Verhaeltnisse sind erlaubt
            es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0, 0);
            es.MulValue(EventVarLabel.RATIO, -0x1000);
            Assert.AreEqual(-0x1000, es.GetValue(EventVarLabel.RATIO));
        }

        [Test]
        public void MulValueIsIgnoredForNonMulVariables()
        {
            var es = NewSystem();
            es.SetValue(EventVarLabel.POWER, 100);
            es.MulValue(EventVarLabel.POWER, 0x2000);
            Assert.AreEqual(100, es.GetValue(EventVarLabel.POWER));
            es.SetRewriteOnceValue(EventVarLabel.DAMAGE, 100);
            es.MulValue(EventVarLabel.DAMAGE, 0x2000);
            Assert.AreEqual(100, es.GetValue(EventVarLabel.DAMAGE));
        }

        [Test]
        public void FramesAreIsolatedAndVariablesOfOuterFramesAreInvisibleInside()
        {
            var es = NewSystem();
            es.SetValue(EventVarLabel.POWER, 11);
            es.VarPush();
            Assert.AreEqual(0, es.GetValue(EventVarLabel.POWER));
            es.SetValue(EventVarLabel.POWER, 22);
            Assert.AreEqual(22, es.GetValue(EventVarLabel.POWER));
            es.VarPop();
            // zurueck im aeusseren Rahmen: Wert 11, der innere Slot ist wieder frei
            Assert.AreEqual(11, es.GetValue(EventVarLabel.POWER));
        }

        [Test]
        public void StackPointerAndSeparatorFollowPushAndPop()
        {
            var stack = new EventVarStack();
            Assert.IsTrue(stack.IsEmpty);
            stack.Push();
            Assert.AreEqual(1u, stack.StackPointer);
            Assert.AreEqual(1, stack.Slot(0).Label, "Trennzeichen im ersten Slot");
            var v = stack.GetNewPoint(5);
            v.Label = 5;
            stack.Push();
            // Slot 0 Trennzeichen, Slot 1 Variable, Slot 2 Trennzeichen; Zeiger hinter dem zweiten Trennzeichen
            Assert.AreEqual(3u, stack.StackPointer);
            Assert.AreEqual(1, stack.Slot(2).Label);
            stack.Pop();
            // zurueck hinter das erste Trennzeichen; die Variable des aeusseren Rahmens bleibt
            Assert.AreEqual(1u, stack.StackPointer);
            Assert.AreEqual(5, stack.Slot(1).Label);
            Assert.AreEqual(0, stack.Slot(2).Label);
            stack.Pop();
            Assert.AreEqual(0u, stack.StackPointer);
            Assert.AreEqual(0, stack.Slot(0).Label);
            Assert.AreEqual(0, stack.Slot(1).Label);
        }

        [Test]
        public void CheckStackClearedEmptiesAllFrames()
        {
            var es = NewSystem();
            es.SetValue(EventVarLabel.POWER, 1);
            es.VarPush();
            es.SetValue(EventVarLabel.GUARD, 2);
            es.VarCheckStackCleared();
            Assert.IsTrue(es.VarStack.IsEmpty);
            Assert.AreEqual(0u, es.VarSetStack.StackPointer);
            Assert.AreEqual(0, es.GetValue(EventVarLabel.POWER));
        }

        [Test]
        public void VariablesWithoutFrameThrowInsteadOfCorrupting()
        {
            var es = new EventSystem(new BattleEventsTestEnv());
            Assert.Throws<System.InvalidOperationException>(() => es.SetValue(EventVarLabel.POWER, 1));
            Assert.Throws<System.InvalidOperationException>(() => es.GetValue(EventVarLabel.POWER));
        }

        [Test]
        public void WorkObjectReplacesTheNumericValue()
        {
            var es = NewSystem();
            var work = new int[3];
            es.SetWorkObject(EventVarLabel.WORK_ADRS, work);
            Assert.AreSame(work, es.GetWorkObject(EventVarLabel.WORK_ADRS));
            Assert.AreEqual(0, es.GetValue(EventVarLabel.WORK_ADRS));
            es.SetValue(EventVarLabel.WORK_ADRS, 4);
            Assert.IsNull(es.GetWorkObject(EventVarLabel.WORK_ADRS));
        }

        [Test]
        public void LabelsOutsideTheSetAreStoredInTheStackButNeverVisible()
        {
            var es = NewSystem();
            es.SetValue((ushort)200, 5);
            Assert.AreEqual(0, es.GetValue((ushort)200));
            es.SetValue(EventVarLabel.POWER, 9);
            Assert.AreEqual(9, es.GetValue(EventVarLabel.POWER));
        }

        [Test]
        public void EventVarOperationsMatchTheRealFunctionsOnRandomSequences()
        {
            var cases = Cases(Load("BattleEventsVar.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 60);
            int ops = 0;
            foreach (var c in cases)
            {
                var scenario = new BattleEventsScenario(new BattleEventsTestEnv());
                var es = scenario.Es;
                var opList = (List<object>)c["ops"];
                var outs = (List<object>)c["out"];
                Assert.AreEqual(opList.Count, outs.Count);
                for (int i = 0; i < opList.Count; i++)
                {
                    var op = (List<object>)opList[i];
                    var expected = LongList(outs[i]);
                    string name = (string)op[0];
                    long ret = 0;
                    long[] retPair = null;
                    switch (name)
                    {
                        case "get": ret = es.GetValue((ushort)I(op, 1)); break;
                        case "getif":
                            bool found = es.TryGetValue((ushort)I(op, 1), out int value);
                            retPair = new long[] { found ? 1 : 0, value };
                            break;
                        case "rewrite": ret = es.RewriteValue((ushort)I(op, 1), unchecked((int)L(op, 2))) ? 1 : 0; break;
                        default: scenario.Exec(op); break;
                    }
                    var sp = scenario.StackPointers();
                    var actual = retPair != null
                        ? new List<long> { retPair[0], retPair[1], sp[0], sp[1] }
                        : new List<long> { ret, sp[0], sp[1] };
                    CollectionAssert.AreEqual(expected, actual, $"Fall {cases.IndexOf(c)}, Operation {i}: {name}");
                    ops++;
                }
                var snap = scenario.VarSnapshot();
                var expectedSlots = Matrix(c["slots"]);
                Assert.AreEqual(expectedSlots.Count, snap.Count, "belegte Slots");
                for (int i = 0; i < snap.Count; i++) CollectionAssert.AreEqual(expectedSlots[i], snap[i], $"Slot {i}");
            }
            Assert.GreaterOrEqual(ops, 1500);
        }

        static int I(List<object> op, int i) => System.Convert.ToInt32(op[i]);
        static long L(List<object> op, int i) => System.Convert.ToInt64(op[i]);
    }
}
