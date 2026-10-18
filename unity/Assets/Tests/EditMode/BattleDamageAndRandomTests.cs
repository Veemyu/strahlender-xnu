using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Zufallsquelle, Hilfsfunktionen, Schaden, Treffer und Volltreffer gegen die Orakel-Fixtures.
    public class BattleDamageAndRandomTests
    {
        // Liefert vorgegebene Werte (modulo max) und zaehlt die Zuege.
        sealed class ScriptedRandom : IBattleRandom
        {
            readonly Queue<ulong> _values;
            public int Draws;

            public ScriptedRandom(params ulong[] values) => _values = new Queue<ulong>(values);

            public ulong GetValue(ulong max)
            {
                Draws++;
                ulong v = _values.Dequeue();
                return max == 0 ? v : v % max;
            }
        }

        [Test]
        public void XoroshiroSeedAndStreamsMatchOracle()
        {
            var streams = Cases(Load("BattleRng.json"), "streams");
            Assert.GreaterOrEqual(streams.Count, 50);
            foreach (var c in streams)
            {
                var rng = new Xoroshiro128Plus(U64(c, "seed"));
                Assert.AreEqual(U64(c, "state0"), rng.State0, "Seed " + c["seed"]);
                Assert.AreEqual(U64(c, "state1"), rng.State1, "Seed " + c["seed"]);
                var ulongs = (List<object>)c["nextULong"];
                for (int i = 0; i < ulongs.Count; i++)
                    Assert.AreEqual(ulong.Parse((string)ulongs[i]), rng.NextULong(), $"Seed {c["seed"]}, Zug {i}");
                var uints = LongList(c["nextUInt"]);
                for (int i = 0; i < uints.Count; i++)
                    Assert.AreEqual((uint)uints[i], rng.NextUInt(), $"Seed {c["seed"]}, UInt {i}");
            }
        }

        [Test]
        public void BoundedValuesMatchOracle()
        {
            foreach (var c in Cases(Load("BattleRng.json"), "bounded"))
            {
                var rng = new BattleRandom(U64(c, "seed"));
                foreach (var d in (List<object>)c["draws"])
                {
                    var draw = (Dictionary<string, object>)d;
                    Assert.AreEqual(U64(draw, "out"), rng.GetValue(U64(draw, "max")), $"Seed {c["seed"]}, max {draw["max"]}");
                }
            }
        }

        [Test]
        public void ZeroSeedIsExpandedAndNeverStuckAtZero()
        {
            var rng = new Xoroshiro128Plus(0);
            Assert.AreNotEqual(0UL, rng.State0 | rng.State1);
            Assert.AreEqual(0xFFFFFFFF80000000UL, BattleRandom.SeedFromInt(int.MinValue));
            Assert.AreEqual(5UL, BattleRandom.SeedFromInt(5));
        }

        [Test]
        public void RandomHelpersMatchOracle()
        {
            var root = Load("BattleRngUse.json");
            var occur = Cases(root, "isOccurPer");
            var range = Cases(root, "randRange");
            var multi = Cases(root, "hitCountStd");
            var crit = Cases(root, "checkCritical");
            Assert.GreaterOrEqual(occur.Count, 50);
            Assert.GreaterOrEqual(range.Count, 50);
            Assert.GreaterOrEqual(multi.Count, 50);
            Assert.GreaterOrEqual(crit.Count, 50);
            foreach (var c in occur)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                Assert.AreEqual(B(c, "out"), rng.IsOccurPercent(U32(c, "percent")));
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
            }
            foreach (var c in range)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                Assert.AreEqual(U32(c, "out"), rng.RandRange(U32(c, "a"), U32(c, "b")));
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
            }
            foreach (var c in multi)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                Assert.AreEqual(I(c, "out"), rng.HitCountStandard(I(c, "wazaHitCount")));
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong(), "Zugzahl: nur Typ 5 zieht");
            }
            foreach (var c in crit)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                Assert.AreEqual(B(c, "out"), CriticalHit.RollStage(I(c, "rank"), I(c, "divisor"), rng));
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong());
            }
        }

        [Test]
        public void FixedPointHelpersMatchOracle()
        {
            var root = Load("BattleCalc.json");
            var damageBase = Cases(root, "damageBase");
            var aff = Cases(root, "affDamage");
            var mul = Cases(root, "mulRatio");
            var mulOver = Cases(root, "mulRatioOverZero");
            var mulInt = Cases(root, "mulRatioInt");
            var weather = Cases(root, "weatherRatio");
            var rank = Cases(root, "statusRank");
            var hit = Cases(root, "hitPer");
            var round = Cases(root, "roundValue");
            foreach (var list in new[] { damageBase, aff, mul, mulOver, mulInt, weather, rank, hit, round })
                Assert.GreaterOrEqual(list.Count, 50);

            foreach (var c in damageBase)
                Assert.AreEqual(U32(c, "out"), BattleMath.DamageBase(U32(c, "power"), U32(c, "atk"), U32(c, "level"), U32(c, "def")), c.ToString());
            foreach (var c in aff)
                Assert.AreEqual(U32(c, "out"), BattleMath.AffDamage(U32(c, "raw"), I(c, "aff")), $"raw {c["raw"]} aff {c["aff"]}");
            foreach (var c in mul)
                Assert.AreEqual(U32(c, "out"), BattleMath.MulRatio(U32(c, "a"), U32(c, "b")), $"a {c["a"]} b {c["b"]}");
            foreach (var c in mulOver)
                Assert.AreEqual(U32(c, "out"), BattleMath.MulRatioOverZero(U32(c, "a"), U32(c, "b")), $"a {c["a"]} b {c["b"]}");
            foreach (var c in mulInt)
                Assert.AreEqual(U32(c, "out"), BattleMath.MulRatioInt(U32(c, "a"), U32(c, "b")), $"a {c["a"]} b {c["b"]}");
            foreach (var c in weather)
                Assert.AreEqual(U32(c, "out"), BattleMath.WeatherDamageRatio(I(c, "weather"), I(c, "type")), $"weather {c["weather"]} type {c["type"]}");
            foreach (var c in rank)
                Assert.AreEqual(U32(c, "out"), BattleMath.StatusRank(U32(c, "value"), I(c, "rank")), $"value {c["value"]} rank {c["rank"]}");
            foreach (var c in hit)
                Assert.AreEqual(U32(c, "out"), BattleMath.HitPercentByStage(U32(c, "hitPer"), I(c, "rank")), $"hitPer {c["hitPer"]} rank {c["rank"]}");
            foreach (var c in round)
                Assert.AreEqual(I(c, "out"), BattleMath.RoundValue(I(c, "value"), I(c, "lo"), I(c, "hi")), c.ToString());
        }

        [Test]
        public void EventVarMulRoundsHalfUpAndClamps()
        {
            Assert.AreEqual(0x1800, BattleMath.EventVarMul(0x1000, 0x1800, 0x29, 0x20000));
            // 3 * 0x800 = 0x1800 -> 1.5 wird bei "halb nach oben" zu 2; MulRatio rundet dagegen halb nach unten (1).
            Assert.AreEqual(2, BattleMath.EventVarMul(3, 0x800, 0, 0));
            Assert.AreEqual(1u, BattleMath.MulRatio(3, 0x800));
            Assert.AreEqual(0x29, BattleMath.EventVarMul(0x1000, 1, 0x29, 0x20000), "untere Grenze");
            Assert.AreEqual(0x20000, BattleMath.EventVarMul(0x1000, 0x7FFFFF, 0x29, 0x20000), "obere Grenze");
            Assert.AreEqual(0, BattleMath.EventVarMul(0x1000, 0, 0, 0), "ohne Grenzen keine Klemmung");
        }

        static DamageInput FromFixture(Dictionary<string, object> c)
        {
            return new DamageInput
            {
                Power = U32(c, "power"),
                Attack = U32(c, "attack"),
                Defense = U32(c, "defense"),
                Level = U32(c, "level"),
                TargetRatio = U32(c, "targetRatio"),
                Weather = (BattleWeather)I(c, "weather"),
                MoveType = I(c, "wazaType"),
                Category = B(c, "physical") ? DamageCategory.Physical : DamageCategory.Special,
                IsCritical = B(c, "critical"),
                FixedRoll = B(c, "fixedRoll"),
                Affinity = I(c, "typeAff"),
                StabRatio = U32(c, "stab"),
                AttackerBurned = B(c, "burned"),
                IgnoreBurn = B(c, "ignoreBurn"),
                FinalRatio = U32(c, "finalRatio"),
            };
        }

        [Test]
        public void DamageMatchesEventCalcDamageOracle()
        {
            var cases = Cases(Load("BattleDamage.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
            {
                var rng = new BattleRandom(U64(c, "seed"));
                var result = DamageCalculator.Calc(FromFixture(c), rng);
                Assert.AreEqual(I(c, "out"), (int)result.Damage, c.ToString());
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong(), "Anzahl der Zufallszuege: " + c);
            }
        }

        [Test]
        public void DamageHandExamples()
        {
            // Level 50, Kraft 80, Angriff 150, Abwehr 100: (150*80*22)/100 = 2640; /50 = 52; +2 = 54.
            var input = new DamageInput { Power = 80, Attack = 150, Defense = 100, Level = 50, FixedRoll = true, MoveType = (int)PokeType.Normal };
            var rng = new ScriptedRandom();
            Assert.AreEqual(45, DamageCalculator.Calc(input, rng).Damage, "54 * 85 / 100 = 45");
            Assert.AreEqual(0, rng.Draws, "fester Faktor zieht keinen Zufall");

            input.StabRatio = 0x1800;
            Assert.AreEqual(67, DamageCalculator.Calc(input, rng).Damage, "45 * 1,5 = 67,5: exakt 0x800 rundet abwaerts");
            input.Affinity = AffinityId.Double;
            Assert.AreEqual(134, DamageCalculator.Calc(input, rng).Damage);

            // Zufallsfaktor 100 - Zug: Zug 0 -> 100; Zug 15 -> 85.
            var rolled = new DamageInput { Power = 80, Attack = 150, Defense = 100, Level = 50 };
            var r0 = new ScriptedRandom(0);
            var res0 = DamageCalculator.Calc(rolled, r0);
            Assert.AreEqual(54, res0.Damage);
            Assert.AreEqual(100u, res0.Roll);
            Assert.AreEqual(1, r0.Draws);
            var r15 = new ScriptedRandom(15);
            Assert.AreEqual(85u, DamageCalculator.Calc(rolled, r15).Roll);
            Assert.AreEqual(45, DamageCalculator.Calc(new DamageInput { Power = 80, Attack = 150, Defense = 100, Level = 50 }, new ScriptedRandom(31)).Damage, "Zug 31 -> 31 % 16 = 15 -> Faktor 85");

            // Volltreffer: 54 * 15 / 10 = 81, nicht ueber MulRatio.
            rolled.IsCritical = true;
            Assert.AreEqual(81, DamageCalculator.Calc(rolled, new ScriptedRandom(0)).Damage);
            rolled.IsCritical = false;

            // Wetter: Feuerattacke bei Sonne x1,5 vor dem Zufallsfaktor: 54 -> 81.
            rolled.MoveType = (int)PokeType.Fire;
            rolled.Weather = BattleWeather.Sun;
            Assert.AreEqual(81, DamageCalculator.Calc(rolled, new ScriptedRandom(0)).Damage);
            rolled.Weather = BattleWeather.Rain;
            Assert.AreEqual(27, DamageCalculator.Calc(rolled, new ScriptedRandom(0)).Damage, "Regen x0,5: 54 * 0x800 >> 12 = 27");

            // Brand halbiert nur physische Treffer, es sei denn der Handler ignoriert die Brand-Wirkung.
            var burn = new DamageInput { Power = 80, Attack = 150, Defense = 100, Level = 50, FixedRoll = true, AttackerBurned = true, Category = DamageCategory.Physical };
            Assert.AreEqual(22, DamageCalculator.Calc(burn, rng).Damage, "45 * 50 / 100 = 22");
            burn.IgnoreBurn = true;
            Assert.AreEqual(45, DamageCalculator.Calc(burn, rng).Damage);
            burn.IgnoreBurn = false;
            burn.Category = DamageCategory.Special;
            Assert.AreEqual(45, DamageCalculator.Calc(burn, rng).Damage);

            // Mindestschaden 1 (hier sogar bei Wirkung 1/4: 1 * 85 / 100 = 0 -> 1).
            var tiny = new DamageInput { Power = 1, Attack = 1, Defense = 999, Level = 1, FixedRoll = true, Affinity = AffinityId.Quarter };
            Assert.AreEqual(1, DamageCalculator.Calc(tiny, rng).Damage);
            Assert.AreEqual(2u, BattleMath.DamageBase(1, 1, 1, 999), "Grundschaden 2: der Quotient ist 0, dazu kommt +2");

            // Typ 18 (kein Typ) bekommt kein STAB-Verhaeltnis.
            var noType = new DamageInput { Power = 80, Attack = 150, Defense = 100, Level = 50, FixedRoll = true, MoveType = (int)PokeType.None, StabRatio = 0x1800 };
            Assert.AreEqual(45, DamageCalculator.Calc(noType, rng).Damage);

            Assert.AreEqual(7u, DamageCalculator.ClampToHp(10, 7));
            Assert.AreEqual(10u, DamageCalculator.ClampToHp(10, 70));
        }

        [Test]
        public void DefenseZeroGivesBaseDamageTwo()
        {
            Assert.AreEqual(2u, BattleMath.DamageBase(100, 100, 100, 0));
        }

        [Test]
        public void HitMatchesEventCheckHitOracle()
        {
            var cases = Cases(Load("BattleHit.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
            {
                var input = new HitInput
                {
                    HitPercent = U32(c, "hitPer"),
                    AccuracyStage = I(c, "accAfter"),
                    EvasionStage = I(c, "evaAfter"),
                    IgnoreEvasion = B(c, "ignoreEva"),
                    TargetIdentified = B(c, "foresight"),
                    HandlerRatio = BattleMath.EventVarMul(0x1000, I(c, "accRatio"), 0x29, 0x20000),
                    AttackerTurnBoost = B(c, "turnFlag14"),
                    MustHit = B(c, "mustHit"),
                    IsDemoCapture = I(c, "competitor") == 4,
                    CancelsHitCheck = B(c, "hitCancel"),
                    TargetTelekinesis = B(c, "autoHitSick"),
                    TargetMaxFriendship = I(c, "friendship") == 255,
                };
                var rng = new BattleRandom(U64(c, "seed"));
                var result = AccuracyCalculator.Check(input, rng);
                Assert.AreEqual(B(c, "hit"), result.Hit, c.ToString());
                Assert.AreEqual(B(c, "friendshipFlag"), result.FriendshipEvaded, c.ToString());
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong(), "Anzahl der Zufallszuege: " + c);
            }
        }

        [Test]
        public void HitHandExamples()
        {
            var input = new HitInput { HitPercent = 100, AccuracyStage = 6, EvasionStage = 6 };
            Assert.AreEqual(100u, AccuracyCalculator.Percent(input, out _));
            input.AccuracyStage = 0; // Stufe -6: 6/18
            Assert.AreEqual(33u, AccuracyCalculator.Percent(input, out _));
            input.TargetMaxFriendship = true;
            Assert.AreEqual(23u, AccuracyCalculator.Percent(input, out bool evaded));
            Assert.IsTrue(evaded);
            Assert.IsTrue(AccuracyCalculator.Check(input, new ScriptedRandom(22)).Hit, "22 < 23");
            Assert.IsFalse(AccuracyCalculator.Check(input, new ScriptedRandom(23)).Hit, "23 < 23 gilt nicht");
            Assert.IsFalse(AccuracyCalculator.Check(input, new ScriptedRandom(123)).Hit, "123 % 100 = 23");

            // Fluchtstufe +6 (Index 12) senkt die Genauigkeit auf 6/18; Ignorieren oder Foresight bei positiver Flucht hebt das auf.
            var evasive = new HitInput { HitPercent = 90, AccuracyStage = 6, EvasionStage = 12 };
            Assert.AreEqual(30u, AccuracyCalculator.Percent(evasive, out _));
            evasive.TargetIdentified = true;
            Assert.AreEqual(90u, AccuracyCalculator.Percent(evasive, out _));
            evasive.TargetIdentified = false;
            evasive.IgnoreEvasion = true;
            Assert.AreEqual(90u, AccuracyCalculator.Percent(evasive, out _));
            // Der Foresight-Zustand hebt nur positive Fluchtstufen auf; eine negative Fluchtstufe (Index < 6) bleibt als Bonus.
            var easy = new HitInput { HitPercent = 60, AccuracyStage = 6, EvasionStage = 0, TargetIdentified = true };
            Assert.AreEqual(100u, AccuracyCalculator.Percent(easy, out _), "Index 12: 18/6 * 60 = 180, gedeckelt auf 100");

            // Automatische Treffer ziehen keinen Zufall.
            var rng = new ScriptedRandom();
            foreach (var auto in new[]
            {
                new HitInput { MustHit = true }, new HitInput { IsDemoCapture = true }, new HitInput { CancelsHitCheck = true }, new HitInput { TargetTelekinesis = true },
            })
            {
                Assert.IsTrue(AccuracyCalculator.Check(auto, rng).Hit);
            }
            Assert.AreEqual(0, rng.Draws);

            // Genauigkeit 0 trifft nie (die Pruefung muss vorher ueber IsAlwaysHit abgefangen werden).
            Assert.IsFalse(AccuracyCalculator.Check(new HitInput { HitPercent = 0 }, new ScriptedRandom(0)).Hit);
            // Zug-Flag des Angreifers: x0x1333 (etwa 1,2): 50 * 1.2 = 60 (MulRatio(50, 0x1333) = 60).
            Assert.AreEqual(60u, AccuracyCalculator.Percent(new HitInput { HitPercent = 50, AttackerTurnBoost = true }, out _));
        }

        [Test]
        public void CriticalMatchesEventCheckCriticalOracle()
        {
            var cases = Cases(Load("BattleCrit.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
            {
                var input = new CriticalInput
                {
                    MoveStage = I(c, "wazaRank"),
                    AttackerStage = I(c, "pokeRank"),
                    StageAfterHandlers = I(c, "rankAfter"),
                    Forbidden = B(c, "forbid"),
                    IsDemoCapture = I(c, "competitor") == 4,
                    AttackerMaxFriendship = I(c, "friendship") == 255,
                };
                var rng = new BattleRandom(U64(c, "seed"));
                var result = CriticalHit.Check(input, rng);
                Assert.AreEqual(B(c, "critical"), result.Critical, c.ToString());
                Assert.AreEqual(B(c, "friendshipFlag"), result.FriendshipBonus, c.ToString());
                Assert.AreEqual(U64(c, "nextRand"), rng.Engine.NextULong(), "Anzahl der Zufallszuege: " + c);
            }
        }

        [Test]
        public void CriticalHandExamples()
        {
            // Stufe 0 = 1/24: nur Zug 0 trifft; Stufe 3 = 1/1; Zuneigung halbiert den Nenner.
            Assert.IsTrue(CriticalHit.Check(new CriticalInput(), new ScriptedRandom(24)).Critical);
            Assert.IsFalse(CriticalHit.Check(new CriticalInput(), new ScriptedRandom(1)).Critical);
            Assert.IsTrue(CriticalHit.Check(new CriticalInput { AttackerStage = 3 }, new ScriptedRandom(99)).Critical);
            Assert.IsTrue(CriticalHit.Check(new CriticalInput { AttackerStage = 2, MoveStage = 2 }, new ScriptedRandom(99)).Critical, "Stufe 4 wird auf 3 gedeckelt");
            Assert.AreEqual(12, CriticalHit.Denominator(0, 2));
            Assert.AreEqual(1, CriticalHit.Denominator(3, 2), "1 / 2 = 0 wird auf 1 angehoben");
            var friendly = CriticalHit.Check(new CriticalInput { AttackerMaxFriendship = true }, new ScriptedRandom(12));
            Assert.IsTrue(friendly.Critical);
            Assert.IsTrue(friendly.FriendshipBonus);

            var rng = new ScriptedRandom();
            Assert.IsTrue(CriticalHit.Check(new CriticalInput { MoveStage = CriticalHit.AlwaysStage }, rng).Critical);
            Assert.IsFalse(CriticalHit.Check(new CriticalInput { MoveStage = CriticalHit.AlwaysStage, IsDemoCapture = true }, rng).Critical);
            Assert.IsFalse(CriticalHit.Check(new CriticalInput { Forbidden = true, MoveStage = CriticalHit.AlwaysStage }, rng).Critical);
            Assert.IsFalse(CriticalHit.Check(new CriticalInput { IsDemoCapture = true }, rng).Critical);
            Assert.AreEqual(0, rng.Draws);
        }
    }
}
