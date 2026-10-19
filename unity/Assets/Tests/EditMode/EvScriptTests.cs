using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Save;

namespace Xnu.Tests
{
    // Baut erfundene Skripte (keine Spieldaten). Argumente: W = Work, F = Float, S = String, FL = Flag, SF = Systemflag.
    static class EvB
    {
        public static EventArgument W(int i) => new EventArgument { Type = 2, Data = i };
        public static EventArgument F(float v) => new EventArgument { Type = 1, Data = BitConverter.ToInt32(BitConverter.GetBytes(v), 0) };
        public static EventArgument FL(int i) => new EventArgument { Type = 3, Data = i };
        public static EventArgument SF(int i) => new EventArgument { Type = 4, Data = i };

        public sealed class FileBuilder
        {
            public readonly EventScriptFile File = new EventScriptFile { Name = "test" };

            public EventArgument S(string s)
            {
                var i = File.Strings.IndexOf(s);
                if (i < 0) { File.Strings.Add(s); i = File.Strings.Count - 1; }
                return new EventArgument { Type = 5, Data = i };
            }

            public FileBuilder Script(string label, params EventCommand[] cmds)
            {
                var s = new EventScript { Label = label };
                s.Commands.AddRange(cmds);
                File.Scripts.Add(s);
                return this;
            }
        }

        public static EventCommand C(int id, params EventArgument[] args)
        {
            var c = new EventCommand();
            c.Args.Add(new EventArgument { Type = 0, Data = id });
            c.Args.AddRange(args);
            return c;
        }

        public static EvScriptBook Book(FileBuilder b) => EvScriptBook.FromFiles(new[] { b.File });
    }

    public class EvScriptTests
    {
        static EvB.FileBuilder NewFile() => new EvB.FileBuilder();

        static EvInterpreter Run(EvB.FileBuilder b, string label, out EvMemoryVariables v, out EvMockHost host, int waitPolls = 0)
        {
            v = new EvMemoryVariables();
            host = new EvMockHost { WaitPolls = waitPolls };
            var it = new EvInterpreter(EvB.Book(b), v, host);
            Assert.IsTrue(it.Start(label));
            return it;
        }

        static EvStatus RunToEnd(EvInterpreter it, int maxUpdates = 100)
        {
            var st = EvStatus.Waiting;
            for (var i = 0; i < maxUpdates && st == EvStatus.Waiting; i++) st = it.Update(1f / 30f);
            return st;
        }

        [Test]
        public void TableIsConsistent()
        {
            Assert.AreEqual(484, EvCommandTable.NoOpCount);
            foreach (var id in EvCommandTable.CoreIds) Assert.AreEqual(EvCmdKind.Core, EvCommandTable.Classify(id), "id " + id);
            Assert.AreEqual(EvCmdKind.NoOp, EvCommandTable.Classify(-1));
            Assert.AreEqual(EvCmdKind.NoOp, EvCommandTable.Classify(0));
            Assert.AreEqual(EvCmdKind.NoOp, EvCommandTable.Classify(1235));
            Assert.AreEqual(EvCmdKind.NoOp, EvCommandTable.Classify(78));   // LAST_KEYWAIT ist im Original ohne Wirkung
            Assert.AreEqual(EvCmdKind.Host, EvCommandTable.Classify(1052));
            Assert.AreEqual(EvCmdKind.Core, EvCommandTable.Classify(EvCmdId.TalkMsg));
        }

        [Test]
        public void LoadsAndCalculates()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(5)), EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(3)),
                EvB.C(EvCmdId.SubWk, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.LdWk, EvB.W(2), EvB.W(1)), EvB.C(EvCmdId.End));
            var it = Run(b, "a", out var v, out var host);
            Assert.AreEqual(EvStatus.Ended, it.Update(0.03f));
            Assert.AreEqual(7, v.GetWork(1));
            Assert.AreEqual(7, v.GetWork(2));
            Assert.AreEqual(1, host.EventEndCount);
            Assert.AreEqual(EvStatus.Idle, it.Update(0.03f));
        }

        [Test]
        public void FloatArgumentsTruncateTowardsZero()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(2.9f)), EvB.C(EvCmdId.LdVal, EvB.W(2), EvB.F(-2.9f)));
            Run(b, "a", out var v, out _).Update(0f);
            Assert.AreEqual(2, v.GetWork(1));
            Assert.AreEqual(-2, v.GetWork(2));
        }

        [Test]
        public void ScriptEndWithoutEndCommandEndsEvent()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)));
            var it = Run(b, "a", out _, out var host);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(1, host.EventEndCount);
        }

        [TestCase("EQ", 3, 3, true)]
        [TestCase("EQ", 3, 4, false)]
        [TestCase("NE", 3, 4, true)]
        [TestCase("GT", 4, 3, true)]
        [TestCase("GT", 3, 3, false)]
        [TestCase("GE", 3, 3, true)]
        [TestCase("LT", 2, 3, true)]
        [TestCase("LT", 3, 3, false)]
        [TestCase("LE", 3, 3, true)]
        [TestCase("LE", 4, 3, false)]
        public void IfValJumpComparators(string op, int a, int c, bool jumps)
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(a)),
                EvB.C(EvCmdId.IfValJump, EvB.W(1), b.S(op), EvB.F(c), b.S("t")),
                EvB.C(EvCmdId.LdVal, EvB.W(9), EvB.F(1)), EvB.C(EvCmdId.End));
            b.Script("t", EvB.C(EvCmdId.LdVal, EvB.W(9), EvB.F(2)), EvB.C(EvCmdId.End));
            var it = Run(b, "a", out var v, out _);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(jumps ? 2 : 1, v.GetWork(9));
        }

        [Test]
        public void SwitchAndCaseJump()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(4), EvB.F(2)), EvB.C(EvCmdId.Switch, EvB.W(4)),
                EvB.C(EvCmdId.CaseJump, EvB.F(1), b.S("c1")), EvB.C(EvCmdId.CaseJump, EvB.F(2), b.S("c2")),
                EvB.C(EvCmdId.LdVal, EvB.W(9), EvB.F(99)), EvB.C(EvCmdId.End));
            b.Script("c1", EvB.C(EvCmdId.LdVal, EvB.W(9), EvB.F(10)), EvB.C(EvCmdId.End));
            b.Script("c2", EvB.C(EvCmdId.LdVal, EvB.W(9), EvB.F(20)), EvB.C(EvCmdId.End));
            Run(b, "a", out var v, out _).Update(0f);
            Assert.AreEqual(20, v.GetWork(9));
        }

        [Test]
        public void CallReturnsToNextCommandAndNests()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.Call, b.S("f")), EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(100)), EvB.C(EvCmdId.End));
            b.Script("f", EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.Call, b.S("g")),
                EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(10)), EvB.C(EvCmdId.Ret));
            b.Script("g", EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(1000)), EvB.C(EvCmdId.Ret));
            var it = Run(b, "a", out var v, out _);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(1111, v.GetWork(1));
        }

        [Test]
        public void RetOnEmptyStackEndsAndMissingLabelIsIgnored()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.Jump, b.S("fehlt")), EvB.C(EvCmdId.Call, b.S("fehlt")), EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)),
                EvB.C(EvCmdId.Ret), EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(2)));
            var it = Run(b, "a", out var v, out var host);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(1, v.GetWork(1));
            Assert.AreEqual(2, it.Stats.MissingLabels);
            Assert.AreEqual(1, host.EventEndCount);
        }

        [Test]
        public void LabelsAreCaseInsensitiveAndFirstFileWins()
        {
            var f1 = NewFile();
            f1.Script("Ev_X", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)));
            var f2 = NewFile();
            f2.Script("ev_x", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(2)));
            var book = EvScriptBook.FromFiles(new[] { f1.File, f2.File });
            Assert.AreEqual(1, book.DuplicateLabelCount);
            var v = new EvMemoryVariables();
            var it = new EvInterpreter(book, v, new EvMockHost());
            Assert.IsTrue(it.Start("EV_X"));
            it.Update(0f);
            Assert.AreEqual(1, v.GetWork(1));
            Assert.IsFalse(it.Start("nicht da"));
        }

        [Test]
        public void FlagsAndSystemFlags()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.FlagSet, EvB.FL(10)), EvB.C(EvCmdId.ArriveFlagSet, EvB.SF(5)),
                EvB.C(EvCmdId.IfFlagOnJump, EvB.FL(10), b.S("on")), EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.End));
            b.Script("on", EvB.C(EvCmdId.IfFlagOffJump, EvB.SF(5), b.S("bad")), EvB.C(EvCmdId.IfFlagOffJump, EvB.FL(11), b.S("off")),
                EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(3)), EvB.C(EvCmdId.End));
            b.Script("off", EvB.C(EvCmdId.FlagReset, EvB.FL(10)), EvB.C(EvCmdId.SetSysFlag, EvB.SF(6)), EvB.C(EvCmdId.ResetSysFlag, EvB.SF(5)),
                EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(2)));
            b.Script("bad", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(-1)));
            var it = Run(b, "a", out var v, out _);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(2, v.GetWork(1));
            Assert.IsFalse(v.GetFlag(10));
            Assert.IsTrue(v.GetSysFlag(6));
            Assert.IsFalse(v.GetSysFlag(5));
        }

        [Test]
        public void InvalidFlagIndexNeverJumpsOnButJumpsOff()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.FlagSet, EvB.FL(-1)), EvB.C(EvCmdId.IfFlagOnJump, EvB.FL(4000), b.S("x")),
                EvB.C(EvCmdId.IfFlagOffJump, EvB.FL(4000), b.S("y")), EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)));
            b.Script("x", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(5)));
            b.Script("y", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(7)));
            Run(b, "a", out var v, out _).Update(0f);
            Assert.AreEqual(7, v.GetWork(1));
        }

        [Test]
        public void BadgeCountFollowsSystemFlags()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.SetSysFlag, EvB.SF(0x7C)), EvB.C(EvCmdId.SetSysFlag, EvB.SF(0x83)), EvB.C(EvCmdId.SetSysFlag, EvB.SF(0x84)));
            Run(b, "a", out _, out var host).Update(0f);
            Assert.AreEqual(2, host.BadgeCount);
        }

        [Test]
        public void TalkWaitsOneFrameAndSplitsLabel()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.TalkMsg, b.S("datei%label_1")), EvB.C(EvCmdId.TalkClose), EvB.C(EvCmdId.End));
            var it = Run(b, "a", out var v, out var host, waitPolls: 2);
            v.SetWork(EvCmdId.WorkTalkWindow, 5);
            Assert.AreEqual(EvStatus.Waiting, it.Update(0.03f));
            Assert.AreEqual("talk datei%label_1", host.Log.Single());
            Assert.AreEqual(EvStatus.Waiting, it.Update(0.03f));
            Assert.AreEqual(EvStatus.Waiting, it.Update(0.03f));
            Assert.AreEqual(EvStatus.Ended, it.Update(0.03f));
            Assert.AreEqual(0, v.GetWork(EvCmdId.WorkTalkWindow));
            CollectionAssert.AreEqual(new[] { "talk datei%label_1", "talkclose", "end" }, host.Log);
        }

        [Test]
        public void EasyObjMsgRunsStagesInOrderEachCostingAFrame()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.EasyObjMsg, b.S("d%l")), EvB.C(EvCmdId.End));
            var it = Run(b, "a", out _, out var host);
            var updates = 0;
            while (it.Update(0.03f) == EvStatus.Waiting && updates < 20) updates++;
            CollectionAssert.AreEqual(new[] { "host " + EvCmdId.TalkObjStart, "talk d%l", "talkclose", "host " + EvCmdId.TalkObjEnd, "end" }, host.Log);
            Assert.GreaterOrEqual(updates, 4);
        }

        [Test]
        public void YesNoAndCustomWindowWriteWork()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.YesNoWin, EvB.W(7)),
                EvB.C(EvCmdId.AddCustumWinLabel, b.S("dp%eins"), EvB.F(10)), EvB.C(EvCmdId.AddCustumWinLabel, b.S("dp%zwei")),
                EvB.C(EvCmdId.AddCustumWinLabel, b.S("dp%drei"), EvB.F(30)), EvB.C(EvCmdId.OpenCustumWin, EvB.W(8)), EvB.C(EvCmdId.End));
            var v = new EvMemoryVariables();
            var host = new EvMockHost { YesNoAnswer = 1, CustomAnswer = 1 };
            var it = new EvInterpreter(EvB.Book(b), v, host);
            it.Start("a");
            Assert.AreEqual(EvStatus.Ended, RunToEnd(it));
            Assert.AreEqual(1, v.GetWork(7));
            Assert.AreEqual(1, v.GetWork(8));       // zweiter Eintrag ohne Rückgabewert: Position 1
            Assert.Contains("custom dp 3", host.Log);

            host.CustomAnswer = 2;
            it.Start("a");
            RunToEnd(it);
            Assert.AreEqual(30, v.GetWork(8));
        }

        [Test]
        public void TimeWaitCountsFramesAndWritesFlagWork()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.TimeWait, EvB.F(3), EvB.W(5)), EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)));
            var it = Run(b, "a", out var v, out _);
            var n = 0;
            while (it.Update(1f / 30f) == EvStatus.Waiting)
            {
                Assert.AreEqual(1, v.GetWork(5));
                n++;
                Assert.Less(n, 50);
            }
            Assert.That(n, Is.InRange(3, 4));
            Assert.AreEqual(0, v.GetWork(5));
            Assert.AreEqual(1, v.GetWork(1));
        }

        [Test]
        public void ItemsAndMoney()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.AddItem, EvB.F(17), EvB.F(5), EvB.W(3)), EvB.C(EvCmdId.ItemChk, EvB.F(17), EvB.F(5), EvB.W(4)),
                EvB.C(EvCmdId.ItemChk, EvB.F(17), EvB.F(6), EvB.W(5)), EvB.C(EvCmdId.SubItem, EvB.F(17), EvB.F(2), EvB.W(6)),
                EvB.C(EvCmdId.AddItemChk, EvB.F(17), EvB.F(997), EvB.W(7)), EvB.C(EvCmdId.AddItemChk, EvB.F(17), EvB.F(996), EvB.W(8)),
                EvB.C(EvCmdId.SubGold, EvB.F(5000)), EvB.C(EvCmdId.CompGold, EvB.W(9), EvB.F(1)), EvB.C(EvCmdId.AddGold, EvB.F(2000000)),
                EvB.C(EvCmdId.GetGold, EvB.W(10)));
            Run(b, "a", out var v, out var host).Update(0f);
            Assert.AreEqual(1, v.GetWork(3));
            Assert.AreEqual(1, v.GetWork(4));
            Assert.AreEqual(0, v.GetWork(5));
            Assert.AreEqual(1, v.GetWork(6));
            Assert.AreEqual(3, host.GetItemCount(17));
            Assert.AreEqual(0, v.GetWork(7));
            Assert.AreEqual(1, v.GetWork(8));
            Assert.AreEqual(0, v.GetWork(9));       // Geld 0 nach SUB_GOLD (begrenzt), 1 <= 0 ist falsch
            Assert.AreEqual(999999, v.GetWork(10));
        }

        [Test]
        public void TrainerBattleResolvesNameWaitsAndFlagsWork()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.IfTrFlagOnJump, b.S("T_ONE"), b.S("done")),
                EvB.C(EvCmdId.TrainerBtlSet, b.S("T_ONE"), EvB.F(0)), EvB.C(EvCmdId.TrainerFlagSet, b.S("T_ONE")),
                EvB.C(EvCmdId.Jump, b.S("a")));
            b.Script("done", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.End));
            var v = new EvMemoryVariables();
            var host = new EvMockHost { WaitPolls = 2 };
            host.TrainerIds["T_ONE"] = 42;
            var it = new EvInterpreter(EvB.Book(b), v, host);
            it.Start("a");
            Assert.AreEqual(EvStatus.Ended, RunToEnd(it));
            Assert.AreEqual(1, v.GetWork(1));
            Assert.IsTrue(v.GetTrainerWin(42));
            CollectionAssert.Contains(host.Log, "battle 42,0");
        }

        [Test]
        public void TrainerFlagCheckSetsCompareFlagForIfJump()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.TrainerFlagCheck, EvB.F(3)), EvB.C(EvCmdId.IfJump, b.S("EQ"), b.S("win")),
                EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.End));
            b.Script("win", EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(2)));
            var v = new EvMemoryVariables();
            var it = new EvInterpreter(EvB.Book(b), v, new EvMockHost());
            it.Start("a");
            it.Update(0f);
            Assert.AreEqual(1, v.GetWork(1));
            v.SetTrainerWin(3, true);
            it.Start("a");
            it.Update(0f);
            Assert.AreEqual(2, v.GetWork(1));
        }

        [Test]
        public void MapChangeAndObjectAnimation()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.ObjAnime, b.S("NPC1"), b.S("anim_a")), EvB.C(EvCmdId.ObjAnimeWait), EvB.C(EvCmdId.MapChange, b.S("ZONE_X"), EvB.F(2)),
                EvB.C(EvCmdId.End));
            b.Script("anim_a", EvB.C(773, EvB.F(1)), EvB.C(774, EvB.F(1)), EvB.C(777));
            var it = Run(b, "a", out _, out var host, waitPolls: 1);
            Assert.AreEqual(EvStatus.Ended, RunToEnd(it));
            CollectionAssert.AreEqual(new[] { "anim NPC1 anim_a 3", "map ZONE_X 2", "end" }, host.Log);
        }

        [Test]
        public void RandomWritesWork()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.GetRnd, EvB.W(1), EvB.F(5)));
            Run(b, "a", out var v, out _).Update(0f);
            Assert.That(v.GetWork(1), Is.InRange(0, 4));
        }

        [Test]
        public void FldItemEventSetsWorksAndJumps()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.FldItemEvent, EvB.F(40), EvB.F(2)));
            b.Script(EvInterpreter.FldItemLabel, EvB.C(EvCmdId.LdVal, EvB.W(1), EvB.F(9)));
            Run(b, "a", out var v, out _).Update(0f);
            Assert.AreEqual(40, v.GetWork(EvCmdId.WorkItemEventA));
            Assert.AreEqual(2, v.GetWork(EvCmdId.WorkItemEventB));
            Assert.AreEqual(9, v.GetWork(1));
        }

        [Test]
        public void HostCommandsAreDelegatedAndNoOpsSkipped()
        {
            var b = NewFile();
            b.Script("a", EvB.C(78), EvB.C(777), EvB.C(-1), EvB.C(5000), EvB.C(1052, EvB.F(1)), EvB.C(EvCmdId.End));
            var it = Run(b, "a", out _, out var host, waitPolls: 2);
            Assert.AreEqual(EvStatus.Ended, RunToEnd(it));
            Assert.AreEqual(3, host.HostCommandCalls);
            Assert.AreEqual(4, it.Stats.NoOpCommands);
            Assert.AreEqual(1, it.Stats.HostCommands);
            Assert.AreEqual(1, it.Stats.HostIds[1052]);
        }

        [Test]
        public void EndlessLoopIsCutAtStepLimit()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.AddWk, EvB.W(1), EvB.F(1)), EvB.C(EvCmdId.Jump, b.S("a")));
            var it = Run(b, "a", out var v, out var host);
            Assert.AreEqual(EvStatus.Ended, it.Update(0f));
            Assert.AreEqual(2500, v.GetWork(1));
            Assert.AreEqual(1, host.EventEndCount);
        }

        [Test]
        public void MissingArgumentsAreReportedAsError()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(1)));
            var it = Run(b, "a", out _, out _);
            Assert.AreEqual(EvStatus.Error, it.Update(0f));
            Assert.AreEqual(EvCmdId.LdVal, it.LastErrorCommandId);
            Assert.IsFalse(it.IsRunning);
        }

        [Test]
        public void OutOfRangeWorkIsAnError()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(500), EvB.F(1)));
            Assert.AreEqual(EvStatus.Error, Run(b, "a", out _, out _).Update(0f));
        }

        [Test]
        public void AbortStopsWithoutEventEnd()
        {
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.TalkMsg, b.S("x%y")));
            var it = Run(b, "a", out _, out var host, waitPolls: 5);
            Assert.AreEqual(EvStatus.Waiting, it.Update(0f));
            it.Abort();
            Assert.AreEqual(EvStatus.Idle, it.Update(0f));
            Assert.AreEqual(0, host.EventEndCount);
        }

        static byte[] BlankSave()
        {
            var buf = new byte[SaveLayout.TotalSize];
            buf[0] = SaveLayout.CurrentVersion;
            return SaveWriter.FixHash(buf);
        }

        [Test]
        public void SaveBackedVariablesReadAndWriteTheSaveBuffer()
        {
            var save = SaveData.FromBytes(BlankSave());
            var v = new EvSaveVariables(save);
            v.SetWork(3, -7);
            v.SetFlag(1500, true);
            v.SetSysFlag(0x7C, true);
            v.SetTrainerWin(706, true);
            Assert.AreEqual(-7, v.GetWork(3));
            Assert.IsTrue(v.GetFlag(1500));
            Assert.IsFalse(v.GetFlag(1501));
            Assert.IsTrue(v.GetSysFlag(0x7C));
            Assert.IsTrue(v.GetSysFlag(0x327));    // immer gesetzt
            Assert.IsTrue(v.GetTrainerWin(706));
            Assert.IsFalse(v.GetTrainerWin(705));
            Assert.AreEqual(0xF9, save.Buffer[0x4 + 12]);
            Assert.AreEqual(1, save.Buffer[0x7D4 + 4 * 1500]);
            Assert.Throws<EvScriptException>(() => v.GetWork(500));
            Assert.Throws<EvScriptException>(() => v.GetFlag(4000));
        }

        [Test]
        public void InterpreterRunsOnSaveVariables()
        {
            var save = SaveData.FromBytes(BlankSave());
            var b = NewFile();
            b.Script("a", EvB.C(EvCmdId.LdVal, EvB.W(2), EvB.F(41)), EvB.C(EvCmdId.AddWk, EvB.W(2), EvB.F(1)), EvB.C(EvCmdId.FlagSet, EvB.FL(77)));
            var it = new EvInterpreter(EvB.Book(b), new EvSaveVariables(save), new EvMockHost());
            it.Start("a");
            it.Update(0f);
            var v = new EvSaveVariables(save);
            Assert.AreEqual(42, v.GetWork(2));
            Assert.IsTrue(v.GetFlag(77));
        }
    }
}
