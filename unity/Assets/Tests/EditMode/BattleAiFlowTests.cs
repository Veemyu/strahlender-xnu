using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle.Flow;

namespace Xnu.Tests
{
    // Trainer-KI (Scheibe 6) mit den synthetischen Stammdaten der Ablauf-Tests.
    public class BattleAiFlowTests
    {
        static BattleEngine Engine(BattleData data, ulong seed, uint bits, int[] items, params int[] enemyMoves)
        {
            var s = BattleFlowTestData.Setup(data, seed, BattleFlowTestData.Mon(data, BattleFlowTestData.Ghost, 30, BattleFlowTestData.Pound),
                BattleFlowTestData.Mon(data, BattleFlowTestData.Mon1, 30, enemyMoves), BattleCompetitor.Trainer);
            s.EnemyAi = new TrainerAi(bits, seed, items);
            s.EnemyItems = items;
            return BattleFlowTestData.Engine(s);
        }

        [Test]
        public void ImmuneMoveGetsPenaltyAndIsAvoided()
        {
            var data = BattleFlowTestData.Create();
            for (ulong seed = 1; seed <= 20; seed++)
            {
                var e = Engine(data, seed, AiBit.Basic, null, BattleFlowTestData.Tackle, BattleFlowTestData.Ember);
                var r = new TrainerAi(AiBit.Basic, seed).Decide(e, BattleEngine.EnemySide);
                Assert.AreEqual(AiActionKind.Move, r.Action);
                Assert.AreEqual(1, r.MoveSlot, "Normal-Attacke gegen Geist-Typ ist wirkungslos und wird gemieden (Seed " + seed + ")");
                Assert.AreEqual(90, r.Scores[0]);
                Assert.AreEqual(100, r.Scores[1]);
            }
        }

        [Test]
        public void EqualScoresChooseAtRandom()
        {
            var data = BattleFlowTestData.Create();
            var seen = new HashSet<int>();
            for (ulong seed = 1; seed <= 40; seed++)
            {
                var e = Engine(data, seed, AiBit.Basic, null, BattleFlowTestData.Ember, BattleFlowTestData.Flamethrower);
                seen.Add(new TrainerAi(AiBit.Basic, seed).Decide(e, BattleEngine.EnemySide).MoveSlot);
            }
            CollectionAssert.AreEquivalent(new[] { 0, 1 }, seen);
        }

        [Test]
        public void DecisionIsReproducible()
        {
            var data = BattleFlowTestData.Create();
            var a = new TrainerAi(AiBit.Basic, 7);
            var b = new TrainerAi(AiBit.Basic, 7);
            var ea = Engine(data, 7, AiBit.Basic, null, BattleFlowTestData.Ember, BattleFlowTestData.Flamethrower);
            var eb = Engine(data, 7, AiBit.Basic, null, BattleFlowTestData.Ember, BattleFlowTestData.Flamethrower);
            for (int i = 0; i < 10; i++) Assert.AreEqual(a.Decide(ea, 1).MoveSlot, b.Decide(eb, 1).MoveSlot);
        }

        [Test]
        public void LowHpTrainerHealsWithItem()
        {
            var data = BattleFlowTestData.Create();
            var e = Engine(data, 3, AiBit.Basic | AiBit.Item, new[] { 17, 0, 0, 0 }, BattleFlowTestData.Ember);
            e.Active(1).Poke.Hp = 4;
            var brain = new BattleAiBrain(new TrainerAi(AiBit.Basic | AiBit.Item, 3, new[] { 17, 0, 0, 0 }));
            var cmd = brain.Decide(e, e.Active(1), e.Active(0));
            Assert.AreEqual(CommandKind.Item, cmd.Kind);
            Assert.AreEqual(17, cmd.ItemId);
            e.Submit(BattleCommand.Fight(0), cmd);
            Assert.IsTrue(e.Log.Any(l => l.Kind == LogKind.ItemUsed && l.Poke / 6 == 1 && l.Id == 17));
        }

        [Test]
        public void HighHpTrainerKeepsItem()
        {
            var data = BattleFlowTestData.Create();
            var e = Engine(data, 3, AiBit.Basic | AiBit.Item, new[] { 17, 0, 0, 0 }, BattleFlowTestData.Ember);
            var r = new TrainerAi(AiBit.Basic | AiBit.Item, 3, new[] { 17, 0, 0, 0 }).Decide(e, 1);
            Assert.AreEqual(AiActionKind.Move, r.Action);
        }

        [Test]
        public void EngineRunsWholeBattleWithAi()
        {
            var data = BattleFlowTestData.Create();
            var e = Engine(data, 11, AiBit.Basic | AiBit.Strong, null, BattleFlowTestData.Ember, BattleFlowTestData.Tackle);
            int guard = 0;
            while (e.Phase != BattlePhase.Finished && guard++ < 300)
            {
                if (e.Phase == BattlePhase.AwaitReplacement) e.SubmitReplacement(e.Parties[0].FindIndex(m => !m.IsFainted));
                else e.Submit(BattleCommand.Fight(0));
            }
            Assert.AreEqual(BattlePhase.Finished, e.Phase);
        }

        // Scheibe 7: Expert und Double laufen im Ablauf mit (alle sieben AIBit-Skripte), reproduzierbar und ohne Ausnahme.
        [Test]
        public void EngineRunsWholeBattleWithAllScripts()
        {
            var data = BattleFlowTestData.Create();
            const uint all = AiBit.Basic | AiBit.Strong | AiBit.Expert | AiBit.Double | AiBit.Allowance | AiBit.Item | AiBit.PokeChange;
            var turns = new int[2];
            for (int run = 0; run < 2; run++)
            {
                var e = Engine(data, 21, all, null, BattleFlowTestData.Ember, BattleFlowTestData.Flamethrower, BattleFlowTestData.Tackle);
                int guard = 0;
                while (e.Phase != BattlePhase.Finished && guard++ < 300)
                {
                    if (e.Phase == BattlePhase.AwaitReplacement) e.SubmitReplacement(e.Parties[0].FindIndex(m => !m.IsFainted));
                    else e.Submit(BattleCommand.Fight(0));
                }
                Assert.AreEqual(BattlePhase.Finished, e.Phase);
                turns[run] = e.Turn;
            }
            Assert.AreEqual(turns[0], turns[1]);
            if (AiGenerated.Available("AiScriptExpert") && AiGenerated.Available("AiScriptDouble"))
                Assert.AreEqual(0, new TrainerAi(all, 1).UnimplementedScriptBits);
        }

        [Test]
        public void TrainerWithoutBitsGetsNoAi() => Assert.IsNull(TrainerAi.ForTrainer(0, 1, null));

        [Test]
        public void WithoutAiTheRandomEnemyStaysDefault()
        {
            var data = BattleFlowTestData.Create();
            var s = BattleFlowTestData.Setup(data, 5, BattleFlowTestData.Mon(data, BattleFlowTestData.Ghost, 30, BattleFlowTestData.Pound),
                BattleFlowTestData.Mon(data, BattleFlowTestData.Mon1, 30, BattleFlowTestData.Tackle, BattleFlowTestData.Ember), BattleCompetitor.Trainer);
            Assert.IsNull(s.EnemyAi);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(BattleCommand.Fight(0));
            Assert.AreEqual(1, e.Turn);
        }
    }
}
