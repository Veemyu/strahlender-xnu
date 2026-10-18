using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Erfahrung, Wachstumsraten, Level und Wetterschaden.
    public class BattleExpTests
    {
        [Test]
        public void AdjustLevelMatchesOracle()
        {
            var cases = Cases(Load("BattleExp.json"), "adjustLevel");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
                Assert.AreEqual(I(c, "out"), ExpCalculator.AdjustLevel(U32(c, "exp"), U32(c, "receiverLevel"), U32(c, "foeLevel")), c.ToString());
        }

        [Test]
        public void BaseAndShareExpMatchOracle()
        {
            var root = Load("BattleExp.json");
            var baseCases = Cases(root, "baseExp");
            var share = Cases(root, "shareExp");
            Assert.GreaterOrEqual(baseCases.Count, 50);
            Assert.GreaterOrEqual(share.Count, 50);
            foreach (var c in baseCases)
                Assert.AreEqual(U32(c, "out"), ExpCalculator.BaseExp(U32(c, "level"), U32(c, "baseExp")), c.ToString());
            foreach (var c in share)
                Assert.AreEqual(U32(c, "out"), ExpCalculator.ShareExp(U32(c, "exp")), c.ToString());
        }

        [Test]
        public void CalcExpMatchesOracle()
        {
            var cases = Cases(Load("BattleExp.json"), "calcExp");
            Assert.GreaterOrEqual(cases.Count, 50);
            int nonZero = 0;
            foreach (var c in cases)
            {
                var input = new ExpInput
                {
                    LevelCap = U32(c, "levelCap"),
                    FoeBaseExp = U32(c, "foeBaseExp"),
                    FoeLevel = U32(c, "foeLevel"),
                    ReceiverLevel = U32(c, "receiverLevel"),
                    Friendship = U32(c, "friendship"),
                    PlayerLanguage = U32(c, "playerLanguage"),
                    ReceiverLanguage = U32(c, "receiverLanguage"),
                    Participated = B(c, "participated"),
                    HasExpShare = B(c, "expShare"),
                    HasLuckyEgg = B(c, "luckyEgg"),
                    EvolutionCanceled = B(c, "evoCancel"),
                    IsOwnPokemon = B(c, "isMyPoke"),
                };
                var result = ExpCalculator.Calc(input);
                Assert.AreEqual(U32(c, "out"), result.Exp, c.ToString());
                Assert.AreEqual(B(c, "byExpShare"), result.ByExpShare, c.ToString());
                Assert.AreEqual(B(c, "hasBonus"), result.HasBonus, c.ToString());
                if (result.Exp > 0) nonZero++;
            }
            Assert.Greater(nonZero, 50, "Fixtures muessen echte Erfahrungswerte enthalten");
        }

        [Test]
        public void ExpHandExamples()
        {
            // Level 50 gegen Level 50: ((2*50+10)/(50+50+10))^2.5 = 1; Basis 50 * 100 / 5 = 1000; +1 durch die Formel.
            var input = new ExpInput { FoeBaseExp = 100, FoeLevel = 50, ReceiverLevel = 50, Participated = true, IsOwnPokemon = true };
            var r = ExpCalculator.Calc(input);
            Assert.AreEqual(1001u, r.Exp);
            Assert.IsFalse(r.ByExpShare);
            Assert.IsFalse(r.HasBonus);

            // Fremdes Pokemon, gleiche Sprache: x1,5 (1001 * 6144 / 4096 = 1501,5: exakt 0x800 rundet abwaerts).
            input.IsOwnPokemon = false;
            input.PlayerLanguage = input.ReceiverLanguage = 9;
            r = ExpCalculator.Calc(input);
            Assert.AreEqual(1501u, r.Exp);
            Assert.IsTrue(r.HasBonus);
            input.ReceiverLanguage = 1;
            Assert.AreEqual(BattleMath.MulRatio(1001, 0x1B33), ExpCalculator.Calc(input).Exp, "andere Sprache: ca. x1,7");

            // Nur Erfahrungs-Teiler: Haelfte (500), dann +1.
            var share = new ExpInput { FoeBaseExp = 100, FoeLevel = 50, ReceiverLevel = 50, HasExpShare = true, IsOwnPokemon = true };
            r = ExpCalculator.Calc(share);
            Assert.AreEqual(501u, r.Exp);
            Assert.IsTrue(r.ByExpShare);

            // Weder gekaempft noch Teiler: nichts.
            Assert.AreEqual(0u, ExpCalculator.Calc(new ExpInput { FoeBaseExp = 100, FoeLevel = 50, ReceiverLevel = 50, IsOwnPokemon = true }).Exp);

            // Bonus-Reihenfolge: Gluecks-Ei, Entwicklungs-Bonus, Freundschaft ueber 219, jeweils einzeln gerundet.
            var bonus = new ExpInput { FoeBaseExp = 100, FoeLevel = 50, ReceiverLevel = 50, Participated = true, IsOwnPokemon = true, HasLuckyEgg = true, EvolutionCanceled = true, Friendship = 220 };
            uint expected = BattleMath.MulRatio(BattleMath.MulRatio(BattleMath.MulRatio(1001, 0x1800), 0x1333), 0x1333);
            Assert.AreEqual(expected, ExpCalculator.Calc(bonus).Exp);
            bonus.Friendship = 219;
            Assert.AreEqual(BattleMath.MulRatio(BattleMath.MulRatio(1001, 0x1800), 0x1333), ExpCalculator.Calc(bonus).Exp, "219 reicht nicht");

            // Level-Deckel: ein Gegner ueber dem Deckel zaehlt nur mit dem Deckel-Level.
            var capped = new ExpInput { LevelCap = 20, FoeBaseExp = 100, FoeLevel = 80, ReceiverLevel = 20, Participated = true, IsOwnPokemon = true };
            Assert.AreEqual(401u, ExpCalculator.Calc(capped).Exp, "20 * 100 / 5 = 400, Ausgleich 1:1, +1");
        }

        [Test]
        public void SmallLevelRatiosAndMinimumBaseExp()
        {
            Assert.AreEqual(1u, ExpCalculator.BaseExp(1, 4), "unter 5 wird auf 1 angehoben");
            Assert.AreEqual(1u, ExpCalculator.BaseExp(5, 1));
            Assert.AreEqual(2u, ExpCalculator.BaseExp(5, 2));
            Assert.AreEqual(1u, ExpCalculator.ShareExp(0));
            Assert.AreEqual(1u, ExpCalculator.ShareExp(1));
            Assert.AreEqual(5u, ExpCalculator.ShareExp(11));
            // Ein hoeherer Empfaenger-Level verringert den Ertrag, ein niedrigerer erhoeht ihn.
            Assert.Less(ExpCalculator.AdjustLevel(1000, 90, 10), ExpCalculator.AdjustLevel(1000, 10, 10));
            Assert.Greater(ExpCalculator.AdjustLevel(1000, 5, 60), 1000);
        }

        [Test]
        public void GrowthFormulasAndLevelLookup()
        {
            Assert.AreEqual(125000L, GrowthRate.ExpForLevel(0, 50));
            Assert.AreEqual(1000000L, GrowthRate.ExpForLevel(0, 100));
            Assert.AreEqual(600000L, GrowthRate.ExpForLevel(1, 100));
            Assert.AreEqual(1640000L, GrowthRate.ExpForLevel(2, 100));
            Assert.AreEqual(1059860L, GrowthRate.ExpForLevel(3, 100));
            Assert.AreEqual(800000L, GrowthRate.ExpForLevel(4, 100));
            Assert.AreEqual(1250000L, GrowthRate.ExpForLevel(5, 100));
            Assert.AreEqual(9L, GrowthRate.ExpForLevel(3, 2));
            Assert.AreEqual(0L, GrowthRate.ExpForLevel(3, 1), "mittel-langsam ist bei Level 1 negativ und wird auf 0 gesetzt");
            Assert.AreEqual(0, GrowthRate.CurveForRow(6));
            Assert.AreEqual(0, GrowthRate.CurveForRow(7));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => GrowthRate.CurveForRow(8));

            var exps = new uint[101];
            for (int lv = 1; lv <= 100; lv++) exps[lv] = (uint)GrowthRate.ExpForLevel(0, lv);
            Assert.AreEqual(1, GrowthRate.LevelFromExp(exps, 0));
            Assert.AreEqual(1, GrowthRate.LevelFromExp(exps, 7));
            Assert.AreEqual(2, GrowthRate.LevelFromExp(exps, 8));
            Assert.AreEqual(2, GrowthRate.LevelFromExp(exps, 26));
            Assert.AreEqual(3, GrowthRate.LevelFromExp(exps, 27));
            Assert.AreEqual(99, GrowthRate.LevelFromExp(exps, 999999));
            Assert.AreEqual(100, GrowthRate.LevelFromExp(exps, 1000000));
            Assert.AreEqual(100, GrowthRate.LevelFromExp(exps, uint.MaxValue));
            Assert.AreEqual(1000000u, GrowthRate.MinExp(exps, 100));
            Assert.AreEqual(1000000u, GrowthRate.MinExp(exps, 150), "Level ueber 100 wird auf 100 gesetzt");
            Assert.AreEqual(8u, GrowthRate.MinExp(exps, 2));
        }

        [Test]
        public void LevelFromExpIsInverseOfExpForLevelForAllCurves()
        {
            for (int curve = 0; curve <= 5; curve++)
            {
                var exps = new uint[101];
                for (int lv = 1; lv <= 100; lv++) exps[lv] = (uint)GrowthRate.ExpForLevel(curve, lv);
                for (int lv = 2; lv <= 100; lv++)
                {
                    Assert.AreEqual(lv, GrowthRate.LevelFromExp(exps, exps[lv]), $"Kurve {curve}, Level {lv}");
                    if (exps[lv] > exps[lv - 1])
                        Assert.AreEqual(lv - 1, GrowthRate.LevelFromExp(exps, exps[lv] - 1), $"Kurve {curve}, Level {lv}");
                }
            }
        }

        [Test]
        public void WeatherChipDamage()
        {
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.None, 160, false, false, false, false));
            Assert.AreEqual(10u, WeatherChip.Damage(BattleWeather.Sandstorm, 160, false, false, false, false));
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.Sandstorm, 160, false, true, false, false));
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.Sandstorm, 160, false, false, true, false));
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.Sandstorm, 160, false, false, false, true));
            Assert.AreEqual(10u, WeatherChip.Damage(BattleWeather.Hail, 160, false, true, true, true), "Hagel trifft Gestein/Stahl/Boden");
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.Hail, 160, true, false, false, false));
            Assert.AreEqual(1u, WeatherChip.Damage(BattleWeather.Hail, 10, false, false, false, false), "mindestens 1");
            Assert.AreEqual(0u, WeatherChip.Damage(BattleWeather.Rain, 160, false, false, false, false));
        }
    }
}
