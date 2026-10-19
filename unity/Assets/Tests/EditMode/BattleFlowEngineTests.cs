using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Battle.Events;
using Xnu.Battle.Flow;
using Xnu.PokePara;
using static Xnu.Tests.BattleFlowTestData;

namespace Xnu.Tests
{
    public class BattleFlowEngineTests
    {
        static BattleData Data;

        [OneTimeSetUp]
        public void Init() => Data = BattleFlowTestData.Create();

        static int Count(BattleEngine e, LogKind k) => e.Log.Count(x => x.Kind == k);

        static BattleEngine Duel(ulong seed, int pSpecies, int pLevel, int[] pMoves, int eSpecies, int eLevel, int[] eMoves, BattleCompetitor comp = BattleCompetitor.Wild)
            => Engine(Setup(Data, seed, Mon(Data, pSpecies, pLevel, pMoves), Mon(Data, eSpecies, eLevel, eMoves), comp));

        static BattleCommand F(int slot) => BattleCommand.Fight(slot);

        [Test]
        public void StartSendsOutBothLeadsAndWaitsForCommands()
        {
            var e = Duel(1, Mon2, 20, new[] { Tackle }, Mon1, 20, new[] { Tackle });
            Assert.AreEqual(BattlePhase.AwaitCommands, e.Phase);
            Assert.AreEqual(1, Count(e, LogKind.BattleStart));
            Assert.AreEqual(2, Count(e, LogKind.SendOut));
            Assert.AreEqual(e.Active(0).Poke.MaxHp, e.Active(0).Poke.Hp);
        }

        [Test]
        public void FasterPokemonActsFirstAndPriorityBeatsSpeed()
        {
            var e = Duel(2, Mon4, 30, new[] { Tackle, QuickAttack }, Mon3, 30, new[] { Tackle });
            e.Submit(F(0), F(0));
            var order = e.Log.First(x => x.Kind == LogKind.ActionOrder);
            Assert.AreEqual(e.Active(1).PokeId, order.Poke, "schnelleres Pokemon zuerst");
            var e2 = Duel(2, Mon4, 30, new[] { Tackle, QuickAttack }, Mon3, 30, new[] { Tackle });
            e2.Submit(F(1), F(0));
            var order2 = e2.Log.First(x => x.Kind == LogKind.ActionOrder);
            Assert.AreEqual(e2.Active(0).PokeId, order2.Poke, "Prioritaet +1 schlaegt Initiative");
            Assert.AreEqual(8u, ActPri.GetWazaPri((uint)order2.Value));
            Assert.AreEqual(1u, ActPri.GetOperationPri((uint)order2.Value));
        }

        [Test]
        public void SpeedTiesAreDecidedByTwoRandomDraws()
        {
            for (ulong seed = 1; seed <= 40; seed++)
            {
                var e = Duel(seed, Mon2, 25, new[] { Splash }, Mon2, 25, new[] { Splash });
                var rng = new BattleRandom(seed);
                bool r1 = rng.GetValue(2) != 0, r2 = rng.GetValue(2) != 0;
                e.Submit(F(0), F(0));
                var order = e.Log.First(x => x.Kind == LogKind.ActionOrder);
                int expectedFirst = r1 == r2 ? e.Active(0).PokeId : e.Active(1).PokeId;
                Assert.AreEqual(expectedFirst, order.Poke, "Seed " + seed);
            }
        }

        [Test]
        public void ParalysisHalvesAgility()
        {
            var e = Duel(3, Mon3, 30, new[] { Tackle }, Mon1, 30, new[] { Tackle });
            var mon = e.Active(0);
            uint normal = e.CalcAgility(mon);
            mon.AddSick(Sick.Paralysis, SickCont.MakePermanent(1));
            Assert.AreEqual(normal * 50 / 100, e.CalcAgility(mon));
            mon.Poke.SetRank(PokeValueId.AGILITY_RANK, 8);
            Assert.AreEqual(BattleMath.StatusRank(mon.Poke.Agility, 8) * 50 / 100, e.CalcAgility(mon));
        }

        [Test]
        public void DamageIsTheCalculatorResultWithTheOriginalDrawOrder()
        {
            for (ulong seed = 10; seed < 30; seed++)
            {
                var e = Duel(seed, Mon2, 30, new[] { Tackle }, Mon1, 30, new[] { Splash });
                var att = e.Active(0).Poke;
                var def = e.Active(1).Poke;
                int hpBefore = def.Hp;
                var rng = new BattleRandom(seed);
                bool hit = rng.GetValue(100) < 100;
                Assert.IsTrue(hit);
                bool crit = rng.GetValue(24) == 0;
                var input = new DamageInput
                {
                    Power = 40, Attack = att.Attack, Defense = def.Defence, Level = 30, Weather = BattleWeather.None, MoveType = 0,
                    Category = DamageCategory.Physical, IsCritical = crit, Affinity = AffinityId.Normal, StabRatio = 0x1000,
                };
                uint expected = DamageCalculator.ClampToHp(DamageCalculator.Calc(input, rng).Damage, (uint)hpBefore);
                e.Submit(F(0), F(0));
                var dmg = e.Log.First(x => x.Kind == LogKind.Damage);
                Assert.AreEqual((int)expected, dmg.Value, "Seed " + seed);
                Assert.AreEqual(hpBefore - (int)expected, def.Hp);
                Assert.AreEqual(crit, Count(e, LogKind.Critical) == 1);
            }
        }

        [Test]
        public void TypeEffectivenessAndStabAreApplied()
        {
            var e = Duel(5, Mon2, 30, new[] { Ember }, Mon1, 30, new[] { Splash });     // Feuer gegen Pflanze/Gift: x2, STAB 1,5
            e.Submit(F(0), F(0));
            Assert.AreEqual(AffinityId.Double, e.Log.First(x => x.Kind == LogKind.Effectiveness).Value);
            var e2 = Duel(5, Mon3, 30, new[] { Tackle }, Ghost, 30, new[] { Splash });   // Normal gegen Geist: wirkungslos
            e2.Submit(F(0), F(0));
            Assert.AreEqual(1, Count(e2, LogKind.NoEffect));
            Assert.AreEqual(0, Count(e2, LogKind.Damage));
        }

        [Test]
        public void MissedAccuracyChecksUseOneDraw()
        {
            int misses = 0, hits = 0;
            for (ulong seed = 1; seed <= 300; seed++)
            {
                var e = Duel(seed, Mon3, 30, new[] { FuryAttack }, Mon4, 30, new[] { Splash });
                e.Submit(F(0), F(0));
                if (Count(e, LogKind.MoveMissed) == 1) misses++; else hits++;
            }
            Assert.That(misses / 300.0, Is.InRange(0.08, 0.22));   // 85 % Genauigkeit
        }

        [Test]
        public void MultiHitMovesHitTwoToFiveTimes()
        {
            var counts = new HashSet<int>();
            for (ulong seed = 1; seed <= 200; seed++)
            {
                var e = Duel(seed, Mon3, 40, new[] { FuryAttack, DoubleKick }, Mon4, 40, new[] { Splash });
                e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 9999;
                e.Submit(F(0), F(0));
                var hc = e.Log.FirstOrDefault(x => x.Kind == LogKind.HitCount);
                if (Count(e, LogKind.MoveMissed) == 0) counts.Add(hc?.Value ?? 1);
                var e2 = Duel(seed, Mon3, 40, new[] { FuryAttack, DoubleKick }, Mon4, 40, new[] { Splash });
                e2.Active(1).Poke.MaxHp = e2.Active(1).Poke.Hp = 9999;
                e2.Submit(F(1), F(0));
                if (Count(e2, LogKind.MoveMissed) == 0) Assert.AreEqual(2, e2.Log.First(x => x.Kind == LogKind.HitCount).Value);
            }
            CollectionAssert.IsSupersetOf(counts, new[] { 2, 3, 4, 5 });
        }

        [Test]
        public void DrainRecoilAndRecoverFollowTheMoveData()
        {
            var e = Duel(7, Mon3, 40, new[] { GigaDrain, DoubleEdge, Recover }, Mon4, 40, new[] { Splash });
            var att = e.Active(0).Poke;
            att.Hp = (ushort)(att.MaxHp / 2);
            int before = att.Hp;
            e.Submit(F(0), F(0));
            var dmg = e.Log.First(x => x.Kind == LogKind.Damage).Value;
            var drain = e.Log.First(x => x.Kind == LogKind.Drain);
            Assert.AreEqual(Math.Min(Math.Max(1, dmg * 50 / 100), att.MaxHp - before), drain.Value);

            var e2 = Duel(7, Mon3, 40, new[] { DoubleEdge }, Mon4, 40, new[] { Splash });
            e2.Active(1).Poke.MaxHp = e2.Active(1).Poke.Hp = 9999;
            e2.Submit(F(0), F(0));
            int dealt = e2.Log.First(x => x.Kind == LogKind.Damage).Value;
            Assert.AreEqual(Math.Max(1, dealt * 33 / 100), e2.Log.First(x => x.Kind == LogKind.Recoil).Value);

            var e3 = Duel(7, Mon3, 40, new[] { Recover }, Mon4, 40, new[] { Splash });
            e3.Active(0).Poke.Hp = 10;
            e3.Submit(F(0), F(0));
            Assert.AreEqual(Math.Min(e3.Active(0).Poke.MaxHp / 2, e3.Active(0).Poke.MaxHp - 10), e3.Log.First(x => x.Kind == LogKind.Recover).Value);
            var e4 = Duel(7, Mon3, 40, new[] { Recover }, Mon4, 40, new[] { Splash });
            e4.Submit(F(0), F(0));
            Assert.AreEqual(FailCause.NothingHappened, e4.Log.First(x => x.Kind == LogKind.MoveFailed && x.Poke == e4.Active(0).PokeId).Value);
        }

        [Test]
        public void StatChangesStopAtTheStageLimits()
        {
            var e = Duel(8, Mon3, 40, new[] { Growl, SwordsDance }, Mon4, 40, new[] { Splash });
            for (int i = 0; i < 7; i++) e.Submit(F(0), F(0));
            Assert.AreEqual(0, e.Active(1).Poke.GetRank(PokeValueId.ATTACK_RANK));
            Assert.AreEqual(6, Count(e, LogKind.StatChange));
            Assert.AreEqual(1, Count(e, LogKind.StatChangeBlocked));
            for (int i = 0; i < 4; i++) e.Submit(F(1), F(0));
            Assert.AreEqual(12, e.Active(0).Poke.GetRank(PokeValueId.ATTACK_RANK));
        }

        [Test]
        public void BurnHalvesPhysicalDamageAndHurtsAtTurnEnd()
        {
            var e = Duel(9, Mon3, 40, new[] { Tackle }, Mon4, 40, new[] { Splash });
            e.Active(0).AddSick(Sick.Burn, SickCont.MakePermanent(1));
            e.Submit(F(0), F(0));
            var d = e.Log.First(x => x.Kind == LogKind.SickDamage);
            Assert.AreEqual(Sick.Burn, d.Id);
            Assert.AreEqual(Math.Max(1, e.Active(0).Poke.MaxHp / 16), d.Value);
            Assert.AreEqual(e.Active(0).PokeId, d.Poke);
        }

        [Test]
        public void PoisonAndToxicDamageGrowPerTurn()
        {
            var e = Duel(11, Mon3, 50, new[] { Splash }, Mon4, 50, new[] { Splash });
            e.Active(0).AddSick(Sick.Poison, SickCont.MakePermanent(1));
            e.Active(1).AddSick(Sick.Poison, SickCont.MakeMoudokuCont(0));
            e.Active(0).Poke.MaxHp = e.Active(0).Poke.Hp = 160;
            e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 160;
            for (int t = 1; t <= 3; t++) e.Submit(F(0), F(0));
            var normal = e.Log.Where(x => x.Kind == LogKind.SickDamage && x.Poke == e.Active(0).PokeId).Select(x => x.Value).ToArray();
            var toxic = e.Log.Where(x => x.Kind == LogKind.SickDamage && x.Poke == e.Active(1).PokeId).Select(x => x.Value).ToArray();
            CollectionAssert.AreEqual(new[] { 20, 20, 20 }, normal);
            CollectionAssert.AreEqual(new[] { 10, 20, 30 }, toxic);
        }

        [Test]
        public void SleepLastsOneToThreeActionsAndWakesUp()
        {
            for (ulong seed = 1; seed <= 60; seed++)
            {
                var e = Duel(seed, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
                e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 9999;
                var rng = new BattleRandom(seed);
                var cont = FlowRules.MakeDefaultSickCont(Sick.Sleep, 1, false, rng);
                int turns = SickCont.GetTurnMax(cont);
                Assert.That(turns, Is.InRange(2, 4));
                e.Active(0).AddSick(Sick.Sleep, cont);
                int asleep = 0;
                for (int t = 0; t < 6 && Count(e, LogKind.SickCured) == 0; t++)
                {
                    e.Submit(F(0), F(0));
                    if (e.Log.Any(x => x.Kind == LogKind.MoveFailed && x.Value == FailCause.Sleep && x.Turn == e.Turn)) asleep++;
                }
                Assert.AreEqual(turns - 1, asleep, "Seed " + seed);
                Assert.AreEqual(1, Count(e, LogKind.SickCured));
                Assert.IsFalse(e.Active(0).HasSick(Sick.Sleep));
            }
        }

        [Test]
        public void FullParalysisAboutOneQuarterAndFreezeThawsOneFifth()
        {
            int para = 0, thaw = 0;
            const int n = 600;
            for (ulong seed = 1; seed <= n; seed++)
            {
                var e = Duel(seed, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
                e.Active(0).AddSick(Sick.Paralysis, SickCont.MakePermanent(1));
                e.Submit(F(0), F(0));
                if (e.Log.Any(x => x.Kind == LogKind.MoveFailed && x.Value == FailCause.Paralysis)) para++;
                var f = Duel(seed, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
                f.Active(0).AddSick(Sick.Freeze, SickCont.MakePermanent(1));
                f.Submit(F(0), F(0));
                if (f.Log.Any(x => x.Kind == LogKind.SickCured)) thaw++;
            }
            Assert.That(para / (double)n, Is.InRange(0.19, 0.31));
            Assert.That(thaw / (double)n, Is.InRange(0.14, 0.26));
        }

        [Test]
        public void ConfusionEndsAndCanHurtTheUser()
        {
            int selfHits = 0;
            for (ulong seed = 1; seed <= 200; seed++)
            {
                var e = Duel(seed, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
                e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 9999;
                e.Active(0).AddSick(Sick.Confusion, SickCont.MakeTurn(1, 3));
                for (int t = 0; t < 3; t++) e.Submit(F(0), F(0));
                Assert.AreEqual(1, Count(e, LogKind.SickCured), "Seed " + seed);
                selfHits += Count(e, LogKind.ConfusionDamage);
            }
            Assert.That(selfHits / 400.0, Is.InRange(0.2, 0.46));   // 2 Pruefungen je Lauf mit 33 %
        }

        [Test]
        public void StatusMovesInflictConditionsWithTheTypeRules()
        {
            var e = Duel(12, Mon3, 30, new[] { ThunderWave, Sing, Toxic }, Mon4, 30, new[] { Splash });
            e.Submit(F(0), F(0));        // Elektro gegen Boden: wirkungslos
            Assert.AreEqual(1, Count(e, LogKind.NoEffect));
            var f = Duel(12, Mon2, 30, new[] { ThunderWave, Toxic, ConfuseRay }, Mon1, 30, new[] { Splash });
            f.Submit(F(0), F(0));        // Paralyse gegen Pflanze/Gift moeglich (Treffer 90 %)
            for (ulong s = 1; s < 50 && f.Active(1).PokeSick == 0; s++) f = Duel(s, Mon2, 30, new[] { ThunderWave }, Mon1, 30, new[] { Splash }).Also(x => x.Submit(F(0), F(0)));
            Assert.AreEqual(Sick.Paralysis, f.Active(1).PokeSick);
            var g = Duel(1, Mon2, 30, new[] { Toxic }, Mon1, 30, new[] { Splash });
            g.Submit(F(0), F(0));        // Gift gegen Gift: wirkungslos fuer Zustand
            Assert.AreEqual(0, g.Active(1).PokeSick);
        }

        [Test]
        public void WeatherLastsFiveTurnsAndSandstormHurtsOnlyVulnerableTypes()
        {
            var e = Duel(13, Mon1, 40, new[] { Sandstorm, Splash }, Mon4, 40, new[] { Splash });
            e.Submit(F(0), F(0));
            Assert.AreEqual(BattleWeather.Sandstorm, e.Weather.Weather);
            for (int i = 0; i < 4; i++) e.Submit(F(1), F(0));
            Assert.AreEqual(BattleWeather.None, e.Weather.Weather);
            Assert.AreEqual(1, Count(e, LogKind.WeatherEnd));
            var hurt = e.Log.Where(x => x.Kind == LogKind.WeatherDamage).ToList();
            Assert.AreEqual(4, hurt.Count);                     // Runde 1-4, in der 5. endet das Wetter
            Assert.IsTrue(hurt.All(h => h.Poke == e.Active(0).PokeId));
            Assert.AreEqual(Math.Max(1, e.Active(0).Poke.MaxHp / 16), hurt[0].Value);

            var r = Duel(13, Mon2, 40, new[] { RainDance, Ember }, Mon1, 40, new[] { Splash });
            r.Submit(F(0), F(0));
            Assert.AreEqual(BattleWeather.Rain, r.Weather.Weather);
            r.Submit(F(0), F(0));
            Assert.AreEqual(1, r.Log.Count(x => x.Kind == LogKind.MoveFailed && x.Value == FailCause.NothingHappened));    // gleiches Wetter
        }

        [Test]
        public void WeatherChangesDamageOfFireMoves()
        {
            int dry = 0, rain = 0, sun = 0;
            for (int w = 0; w < 3; w++)
            {
                var e = Duel(21, Mon2, 40, new[] { Flamethrower }, Mon4, 40, new[] { Splash });
                e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 9999;
                if (w == 1) e.Active(0).Poke.Hp = e.Active(0).Poke.Hp;
                switch (w)
                {
                    case 1: SetWeather(e, BattleWeather.Rain); break;
                    case 2: SetWeather(e, BattleWeather.Sun); break;
                }
                e.Submit(F(0), F(0));
                int d = e.Log.First(x => x.Kind == LogKind.Damage).Value;
                if (w == 0) dry = d; else if (w == 1) rain = d; else sun = d;
            }
            Assert.Less(rain, dry);
            Assert.Greater(sun, dry);
        }

        static void SetWeather(BattleEngine e, BattleWeather w)
        {
            e.Weather.Weather = w;
            e.Weather.TurnMax = 5;
        }

        [Test]
        public void SwitchingHasPriorityAndTheFoeHitsTheNewPokemon()
        {
            var s = Setup(Data, 14, Mon(Data, Mon4, 30, Tackle), Mon(Data, Mon3, 30, Tackle));
            s.PlayerParty.Add(Mon(Data, Mon1, 30, Tackle));
            var e = Engine(s);
            e.Submit(BattleCommand.Change(1), F(0));
            Assert.AreEqual(1, e.ActiveIndex(0));
            var order = e.Log.First(x => x.Kind == LogKind.ActionOrder);
            Assert.AreEqual(e.Parties[0][0].PokeId, order.Poke);
            Assert.AreEqual(e.Parties[0][1].PokeId, e.Log.First(x => x.Kind == LogKind.Damage).Poke);
            Assert.AreEqual(1, Count(e, LogKind.Switch));
            Assert.AreEqual(6, e.Parties[0][1].Poke.GetRank(PokeValueId.ATTACK_RANK));
        }

        [Test]
        public void RunSucceedsAgainstSlowerFoesAndRollsAgainstFasterOnes()
        {
            var fast = Duel(15, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Tackle });
            fast.Submit(BattleCommand.Run(), F(0));
            Assert.AreEqual(BattleResult.Run, fast.Result);
            Assert.AreEqual(BattlePhase.Finished, fast.Phase);
            Assert.AreEqual(0, Count(fast, LogKind.Damage), "Flucht (Aktionsart 6) kommt vor dem Angriff");

            int ok = 0, fail = 0;
            for (ulong seed = 1; seed <= 200; seed++)
            {
                var e = Duel(seed, Mon4, 30, new[] { Splash }, Mon3, 30, new[] { Splash });
                e.Submit(BattleCommand.Run(), F(0));
                if (e.Result == BattleResult.Run) ok++;
                else { fail++; Assert.AreEqual(1, e.EscapeTries); Assert.AreEqual(BattlePhase.AwaitCommands, e.Phase); }
            }
            Assert.Greater(ok, 20);
            Assert.Greater(fail, 20);
        }

        [Test]
        public void EscapeOddsRiseWithEveryFailedTry()
        {
            var e = Duel(5, Mon4, 30, new[] { Splash }, Mon3, 30, new[] { Splash });
            e.Active(1).Poke.MaxHp = 999;
            int tries = 0;
            while (e.Phase == BattlePhase.AwaitCommands && tries < 20)
            {
                e.Submit(BattleCommand.Run(), F(0));
                tries++;
            }
            Assert.AreEqual(BattleResult.Run, e.Result);
            Assert.AreEqual(tries - 1, e.EscapeTries);
        }

        [Test]
        public void TrappedPokemonCannotEscapeAndTrainersCannotBeFled()
        {
            var e = Duel(16, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
            e.Active(0).AddSick(Sick.Bind, SickCont.MakePokeTurn(6, 6, 5));
            e.Submit(BattleCommand.Run(), F(0));
            Assert.AreEqual(BattlePhase.AwaitCommands, e.Phase);
            Assert.AreEqual(1, Count(e, LogKind.RunFailed));
            var t = Duel(16, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash }, BattleCompetitor.Trainer);
            Assert.Throws<ArgumentException>(() => t.Submit(BattleCommand.Run(), F(0)));
        }

        [Test]
        public void KnockOutGivesExperienceEffortAndLevelsUp()
        {
            var e = Duel(17, Mon3, 30, new[] { Tackle }, Mon1, 20, new[] { Splash });
            var mon = e.Active(0);
            e.Active(1).Poke.Hp = 1;
            uint startExp = mon.Exp;
            mon.Exp = GrowthRate.MinExp(Data.GetGrowth(mon.GrowthRow), 31) - 1;
            e.Submit(F(0), F(0));
            Assert.AreEqual(BattleResult.Win, e.Result);
            Assert.AreEqual(1, Count(e, LogKind.Faint));
            var input = new ExpInput { FoeBaseExp = 64, FoeLevel = 20, ReceiverLevel = 30, Friendship = 70, PlayerLanguage = 1, ReceiverLanguage = 1, Participated = true, IsOwnPokemon = true };
            uint expected = ExpCalculator.Calc(input).Exp;
            var gained = e.Log.First(x => x.Kind == LogKind.ExpGained);
            Assert.AreEqual((int)expected, gained.Value);
            Assert.AreEqual(31, mon.Level);
            Assert.AreEqual(1, Count(e, LogKind.LevelUp));
            var ev = e.Log.First(x => x.Kind == LogKind.EvGained);
            Assert.AreEqual((int)StatId.SpAtk, ev.Id);
            Assert.AreEqual(1, mon.Source.Core.GetEv(StatId.SpAtk));
            Assert.AreEqual(mon.Exp, mon.Source.Core.Exp, "Ergebnis wird in die Quelldaten zurueckgeschrieben");
            Assert.AreEqual(31, mon.Source.Level);
        }

        [Test]
        public void ExpShareGivesHalfToBenchedPokemonAndMachoBraceDoublesEffort()
        {
            var s = Setup(Data, 18, Mon(Data, Mon3, 30, Tackle), Mon(Data, Mon1, 20, Splash));
            s.PlayerParty.Add(Mon(Data, Mon4, 30, Tackle));
            s.HasExpShare = true;
            s.PlayerParty[0].Core.HeldItem = BattleEngine.MachoBraceItem;
            var e = Engine(s);
            e.Active(1).Poke.Hp = 1;
            e.Submit(F(0), F(0));
            var gains = e.Log.Where(x => x.Kind == LogKind.ExpGained).ToList();
            Assert.AreEqual(2, gains.Count);
            Assert.Greater(gains[0].Value, gains[1].Value);
            var evs = e.Log.Where(x => x.Kind == LogKind.EvGained && x.Poke == e.Parties[0][0].PokeId).ToList();
            Assert.AreEqual(2, evs[0].Value);
        }

        [Test]
        public void FaintedLeadAsksForAReplacementAndTrainerSendsTheNextOne()
        {
            var s = Setup(Data, 19, Mon(Data, Mon4, 20, Tackle), Mon(Data, Mon3, 40, Tackle), BattleCompetitor.Trainer);
            s.PlayerParty.Add(Mon(Data, Mon1, 20, Tackle));
            s.EnemyParty.Add(Mon(Data, Mon2, 20, Tackle));
            var e = Engine(s);
            e.Active(0).Poke.Hp = 1;
            e.Submit(F(0), F(0));
            Assert.AreEqual(BattlePhase.AwaitReplacement, e.Phase);
            Assert.Throws<InvalidOperationException>(() => e.Submit(F(0), F(0)));
            e.SubmitReplacement(1);
            Assert.AreEqual(BattlePhase.AwaitCommands, e.Phase);
            Assert.AreEqual(1, e.ActiveIndex(0));
            Assert.AreEqual(1, Count(e, LogKind.TurnEnd));
            e.Active(1).Poke.Hp = 1;
            e.Submit(F(0), F(0));
            Assert.AreEqual(1, e.ActiveIndex(1), "Trainer schickt das naechste Pokemon");
            Assert.AreEqual(BattlePhase.AwaitCommands, e.Phase);
        }

        [Test]
        public void ItemsHealAndAreConsumed()
        {
            var s = Setup(Data, 20, Mon(Data, Mon4, 30, Tackle), Mon(Data, Mon1, 20, Splash));
            s.Bag[17] = 2;
            s.Bag[18] = 1;
            var e = Engine(s);
            e.Active(0).Poke.Hp = 5;
            e.Submit(BattleCommand.Item(17), F(0));
            Assert.AreEqual(25, e.Active(0).Poke.Hp);
            Assert.AreEqual(1, e.Bag[17]);
            Assert.AreEqual(1, Count(e, LogKind.ItemUsed));
            Assert.Throws<ArgumentException>(() => e.Submit(BattleCommand.Item(99), F(0)));
        }

        [Test]
        public void StruggleIsUsedWithoutPpAndHurtsTheUser()
        {
            var e = Duel(22, Mon3, 40, new[] { Tackle }, Mon4, 40, new[] { Splash });
            for (int i = 0; i < 4; i++) e.Active(0).Pp[i] = 0;
            e.Active(1).Poke.MaxHp = e.Active(1).Poke.Hp = 9999;
            e.Submit(F(0), F(0));
            Assert.AreEqual(StruggleNo, e.Log.First(x => x.Kind == LogKind.MoveUsed).Id);
            Assert.AreEqual(Math.Max(1, e.Active(0).Poke.MaxHp / 4), e.Log.First(x => x.Kind == LogKind.Recoil).Value);
        }

        const int StruggleNo = 165;

        [Test]
        public void PpIsDeductedOnlyAfterTheFirstCheck()
        {
            var e = Duel(23, Mon3, 30, new[] { Tackle }, Mon4, 30, new[] { Splash });
            e.Active(0).AddSick(Sick.Sleep, SickCont.MakeTurn(1, 4));
            int pp = e.Active(0).Pp[0];
            e.Submit(F(0), F(0));
            Assert.AreEqual(pp, e.Active(0).Pp[0], "Schlaf: keine PP verbraucht");
            e.Active(0).CureSick(Sick.Sleep);
            e.Submit(F(0), F(0));
            Assert.AreEqual(pp - 1, e.Active(0).Pp[0]);
        }

        [Test]
        public void IdenticalSeedsGiveIdenticalLogsAndDifferentSeedsDiffer()
        {
            string Play(ulong seed)
            {
                var e = Duel(seed, Mon3, 30, new[] { Tackle, Ember, Sing }, Mon1, 30, new[] { Tackle, Growl, Toxic });
                for (int i = 0; i < 40 && e.Phase != BattlePhase.Finished; i++)
                {
                    if (e.Phase == BattlePhase.AwaitReplacement) e.SubmitReplacement(0);
                    else e.Submit(F(i % 3));
                }
                return string.Join("\n", e.Log.Select(x => x.ToString()));
            }
            Assert.AreEqual(Play(7), Play(7));
            Assert.AreNotEqual(Play(7), Play(8));
        }

        [Test]
        public void RandomBattlesAlwaysFinishWithConsistentState()
        {
            var species = new[] { Mon1, Mon2, Mon3, Mon4, Ghost };
            var moveSets = new[] { new[] { Tackle, Ember, Growl, Recover }, new[] { Sing, ThunderWave, DoubleEdge, FuryAttack }, new[] { Toxic, Sandstorm, GigaDrain, Wrap }, new[] { RainDance, Flamethrower, IceBeam, ConfuseRay } };
            var rnd = new Random(1234);
            int finished = 0;
            for (int seed = 1; seed <= 120; seed++)
            {
                var s = new BattleSetup { Data = Data, Seed = (ulong)seed, Competitor = seed % 2 == 0 ? BattleCompetitor.Trainer : BattleCompetitor.Wild, HasExpShare = seed % 3 == 0 };
                int np = 1 + rnd.Next(3), ne = 1 + rnd.Next(3);
                for (int i = 0; i < np; i++) s.PlayerParty.Add(Mon(Data, species[rnd.Next(5)], 15 + rnd.Next(25), moveSets[rnd.Next(4)]));
                for (int i = 0; i < ne; i++) s.EnemyParty.Add(Mon(Data, species[rnd.Next(5)], 15 + rnd.Next(25), moveSets[rnd.Next(4)]));
                var e = Engine(s);
                int turns = 0;
                while (e.Phase != BattlePhase.Finished && turns++ < 400)
                {
                    if (e.Phase == BattlePhase.AwaitReplacement)
                    {
                        int idx = e.Parties[0].FindIndex(m => !m.IsFainted);
                        e.SubmitReplacement(idx);
                        continue;
                    }
                    var usable = Enumerable.Range(0, 4).Where(i => e.Active(0).Moves[i] != 0 && e.Active(0).Pp[i] > 0).ToList();
                    var cmd = F(usable.Count == 0 ? 0 : usable[rnd.Next(usable.Count)]);
                    if (rnd.Next(10) == 0 && e.IsWild) cmd = BattleCommand.Run();
                    if (rnd.Next(12) == 0)
                    {
                        int idx = e.Parties[0].FindIndex(m => !m.IsFainted && m != e.Active(0));
                        if (idx >= 0) cmd = BattleCommand.Change(idx);
                    }
                    e.Submit(cmd);
                    foreach (var side in e.Parties)
                        foreach (var m in side)
                        {
                            Assert.LessOrEqual(m.Poke.Hp, m.Poke.MaxHp);
                            for (int r = 1; r <= BattlePoke.RankCount; r++) Assert.That(m.Poke.GetRank((PokeValueId)r), Is.InRange(0, 12));
                            foreach (var pp in m.Pp) Assert.LessOrEqual(pp, 80);
                        }
                }
                Assert.AreEqual(BattlePhase.Finished, e.Phase, "Seed " + seed);
                Assert.AreEqual(1, Count(e, LogKind.BattleEnd));
                if (e.Result == BattleResult.Win) Assert.IsFalse(e.HasAlive(1));
                if (e.Result == BattleResult.Lose) Assert.IsFalse(e.HasAlive(0));
                finished++;
            }
            Assert.AreEqual(120, finished);
        }
    }

    static class BattleFlowTestExtensions
    {
        public static T Also<T>(this T value, Action<T> action)
        {
            action(value);
            return value;
        }
    }
}
