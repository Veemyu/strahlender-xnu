using System.Linq;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Battle.Flow;
using Xnu.PokePara;
using static Xnu.Tests.BattleFlowTestData;

namespace Xnu.Tests
{
    // Scheibe 5: Seiten-/Feldeffekte, Handler-Wirkungen (Faehigkeiten, Items), Geldformeln.
    public class BattleFlowEffectTests
    {
        static BattleData Data;

        [OneTimeSetUp]
        public void Init() => Data = BattleFlowTestData.Create();

        static int Count(BattleEngine e, LogKind k) => e.Log.Count(x => x.Kind == k);

        static BattleCommand F(int slot) => BattleCommand.Fight(slot);

        static PokemonParam Mon(int species, int level, int ability, int item, params int[] moves)
            => PokemonFactory.Create(Data, species, 0, level, 0, ability, moves, item, new[] { 15, 15, 15, 15, 15, 15 }, null, 0);

        static BattleEngine Engine(ulong seed, PokemonParam player, PokemonParam enemy, BattleCompetitor comp = BattleCompetitor.Wild)
            => BattleFlowTestData.Engine(Setup(Data, seed, player, enemy, comp));

        // Feste Gegner-Entscheidung, damit die Tests nicht vom KI-Zufall abhaengen.
        sealed class FixedBrain : IEnemyBrain
        {
            readonly int _slot;
            public FixedBrain(int slot) => _slot = slot;
            public BattleCommand Decide(BattleEngine engine, BattleMon actor, BattleMon foe) => BattleCommand.Fight(_slot);
            public int ChooseReplacement(BattleEngine engine) => engine.Parties[1].FindIndex(m => !m.IsFainted);
        }

        // Feste Abfolge von Attacken-Slots (zyklisch).
        sealed class ScriptBrain : IEnemyBrain
        {
            readonly int[] _slots;
            int _i;
            public ScriptBrain(params int[] slots) => _slots = slots;
            public BattleCommand Decide(BattleEngine engine, BattleMon actor, BattleMon foe) => BattleCommand.Fight(_slots[_i++ % _slots.Length]);
            public int ChooseReplacement(BattleEngine engine) => engine.Parties[1].FindIndex(m => !m.IsFainted);
        }

        static int TackleDamage(BattleEngine e) => e.Log.Where(x => x.Kind == LogKind.Damage && x.Poke == 0).Select(x => x.Value).Last();

        [Test]
        public void ReflectHalvesPhysicalDamage()
        {
            int Run(int firstMove)
            {
                var s = Setup(Data, 7, Mon(Mon1, 50, 0, 0, firstMove, Splash), Mon(Mon3, 50, 0, 0, Tackle, Splash));
                s.EnemyBrain = new ScriptBrain(1, 0);
                var e = BattleFlowTestData.Engine(s);
                e.Submit(F(0));
                if (firstMove == Reflect) Assert.AreEqual(1, Count(e, LogKind.SideEffectStart));
                e.Submit(F(1));
                return TackleDamage(e);
            }
            int normal = Run(Splash), halved = Run(Reflect);
            Assert.Greater(normal, 10);
            Assert.That(halved, Is.InRange(normal / 2 - 2, normal / 2 + 2));
        }

        [Test]
        public void ReflectEndsAfterFiveTurns()
        {
            var e = Engine(8, Mon(Mon4, 60, 0, 0, Reflect, Splash), Mon(Mon4, 60, 0, 0, Splash));
            e.Submit(F(0), F(0));
            for (int i = 0; i < 6 && e.Log.All(x => x.Kind != LogKind.SideEffectEnd); i++) e.Submit(F(1), F(0));
            var end = e.Log.First(x => x.Kind == LogKind.SideEffectEnd);
            Assert.AreEqual(SideEffect.Reflect, end.Id);
        }

        [Test]
        public void StealthRockHurtsSwitchInByTypeEffectiveness()
        {
            var s = Setup(Data, 3, Mon(Mon3, 30, 0, 0, Splash), Mon(Mon4, 30, 0, 0, StealthRock));
            s.PlayerParty.Add(Mon(Mon1, 30, 0, 0, Splash));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            Assert.AreEqual(SideEffect.StealthRock, e.Log.First(x => x.Kind == LogKind.SideEffectStart).Id);
            e.Submit(BattleCommand.Change(1));
            var hit = e.Log.First(x => x.Kind == LogKind.HazardDamage);
            Assert.AreEqual(SideEffect.StealthRock, hit.Id);
            Assert.AreEqual((int)FlowRules.QuotMaxHp(e.Parties[0][1].Poke.MaxHp, 8), hit.Value);   // Pflanze/Gift: neutral gegen Gestein
        }

        [Test]
        public void SpikesStackAndDamageGrowsWithLayers()
        {
            var s = Setup(Data, 4, Mon(Mon3, 30, 0, 0, Splash), Mon(Mon4, 30, 0, 0, Spikes));
            s.PlayerParty.Add(Mon(Mon1, 30, 0, 0, Splash));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            e.Submit(F(0));
            Assert.AreEqual(2, Count(e, LogKind.SideEffectStart));
            e.Submit(BattleCommand.Change(1));
            var hit = e.Log.First(x => x.Kind == LogKind.HazardDamage);
            Assert.AreEqual((int)FlowRules.QuotMaxHp(e.Parties[0][1].Poke.MaxHp, 6), hit.Value);
        }

        [Test]
        public void ProtectBlocksTheAttack()
        {
            var s = Setup(Data, 5, Mon(Mon4, 30, 0, 0, Protect), Mon(Mon3, 30, 0, 0, Tackle));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            Assert.AreEqual(1, Count(e, LogKind.Protected));
            Assert.AreEqual(0, e.Log.Count(x => x.Kind == LogKind.Damage));
        }

        [Test]
        public void TrickRoomReversesTheOrder()
        {
            var s = Setup(Data, 6, Mon(Mon4, 30, 0, 0, TrickRoom, Splash), Mon(Mon3, 30, 0, 0, Splash));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            Assert.AreEqual(1, Count(e, LogKind.FieldEffectStart));
            e.Submit(F(1));
            var order = e.Log.Last(x => x.Kind == LogKind.ActionOrder);
            Assert.AreEqual(e.Active(0).PokeId, order.Poke, "langsam zuerst");
        }

        [Test]
        public void IntimidateLowersTheFoeAttackOnEntry()
        {
            var e = Engine(9, Mon(Mon2, 30, 22, 0, Splash), Mon(Mon1, 30, 0, 0, Splash));
            Assert.AreEqual(1, e.Log.Count(x => x.Kind == LogKind.AbilityActivated && x.Id == 22));
            var drop = e.Log.First(x => x.Kind == LogKind.StatChange);
            Assert.AreEqual(e.Active(1).PokeId, drop.Poke);
            Assert.AreEqual(-1, drop.Value);
        }

        [Test]
        public void DrizzleStartsRainOnEntry()
        {
            var e = Engine(10, Mon(Mon2, 30, 2, 0, Splash), Mon(Mon1, 30, 0, 0, Splash));
            Assert.AreEqual(BattleWeather.Rain, e.Weather.Weather);
        }

        [Test]
        public void LeftoversHealOneSixteenthAtTurnEnd()
        {
            var s = Setup(Data, 11, Mon(Mon1, 40, 0, 234, Splash), Mon(Mon3, 70, 0, 0, Tackle));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            int dmg = TackleDamage(e);
            var heal = e.Log.First(x => x.Kind == LogKind.Recover && x.Poke == 0);
            int sixteenth = (int)FlowRules.QuotMaxHp(e.Active(0).Poke.MaxHp, 16);
            Assert.Greater(dmg, sixteenth);
            Assert.AreEqual(sixteenth, heal.Value);
        }

        [Test]
        public void ChoiceItemLocksTheFirstMove()
        {
            var s = Setup(Data, 12, Mon(Mon4, 40, 0, 220, Tackle, Splash), Mon(Mon4, 40, 0, 0, Splash));
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            e.Submit(F(0));
            e.Submit(F(1));
            Assert.AreEqual(2, e.Log.Count(x => x.Kind == LogKind.MoveUsed && x.Poke == 0 && x.Id == Tackle));
        }

        [Test]
        public void TrainerWinPaysGoldTimesLevelTimesFour()
        {
            var s = Setup(Data, 13, Mon(Mon3, 60, 0, 0, DoubleEdge), Mon(Mon1, 5, 0, 0, Splash), BattleCompetitor.Trainer);
            s.TrainerGold = 0x1234;
            s.EnemyBrain = new FixedBrain(0);
            var e = BattleFlowTestData.Engine(s);
            for (int i = 0; i < 5 && e.Phase != BattlePhase.Finished; i++) e.Submit(F(0));
            Assert.AreEqual(BattleResult.Win, e.Result);
            Assert.AreEqual(0x34 * 5 * 4, e.PrizeMoney);
            Assert.AreEqual(1, Count(e, LogKind.PrizeMoney));
        }

        [Test]
        public void WildWinPaysNoMoney()
        {
            var e = Engine(14, Mon(Mon3, 60, 0, 0, DoubleEdge), Mon(Mon1, 5, 0, 0, Splash));
            for (int i = 0; i < 5 && e.Phase != BattlePhase.Finished; i++) e.Submit(F(0), F(0));
            Assert.AreEqual(0, e.PrizeMoney);
        }

        [Test]
        public void PenaltyFormulaIsCappedByMoney()
        {
            Assert.AreEqual(50 * 6 * 4, PrizeFormula.Win(6, 50));
            Assert.AreEqual(100u, PrizeFormula.Penalty(50, 2, 100));
            Assert.AreEqual(50u * 6 * 4, PrizeFormula.Penalty(50, 2, 100000));
        }
    }
}
