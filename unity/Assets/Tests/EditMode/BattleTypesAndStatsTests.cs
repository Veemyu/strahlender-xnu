using System.Collections.Generic;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Data;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Tabellen, Typenwirkung, Wesen und Statuswerte gegen die Orakel-Fixtures (echte Funktionen in Unicorn) und handgerechnete Beispiele.
    public class BattleTypesAndStatsTests
    {
        static Dictionary<string, object> _tables;
        static Dictionary<string, object> Tables => _tables ??= Load("BattleTables.json");

        [Test]
        public void TypeChartMatchesBinaryTable()
        {
            var rows = Matrix(Tables["typeChart"]);
            Assert.AreEqual(TypeAffinity.TypeCount, rows.Count);
            for (int a = 0; a < rows.Count; a++)
            {
                Assert.AreEqual(TypeAffinity.TypeCount, rows[a].Count);
                for (int d = 0; d < rows[a].Count; d++)
                    Assert.AreEqual(rows[a][d], TypeAffinity.RawEntry(a, d), $"Zeile {a}, Spalte {d}");
            }
        }

        [Test]
        public void NatureTableMatchesBinaryTable()
        {
            var rows = Matrix(Tables["natureTable"]);
            Assert.AreEqual(Nature.Count, rows.Count);
            for (int n = 0; n < rows.Count; n++)
                for (int p = 1; p <= 5; p++)
                    Assert.AreEqual(rows[n][p - 1], Nature.Modifier(n, p), $"Wesen {n}, Kraft {p}");
        }

        [Test]
        public void RankAndHitFractionsMatchBinaryTables()
        {
            var rank = Matrix(Tables["statusRankNumDen"]);
            var hit = Matrix(Tables["hitRankNumDen"]);
            Assert.AreEqual(BattleMath.StageCount, rank.Count);
            for (int i = 0; i < rank.Count; i++)
            {
                Assert.AreEqual(((int)rank[i][0], (int)rank[i][1]), BattleMath.RankFraction(i));
                Assert.AreEqual(((int)hit[i][0], (int)hit[i][1]), BattleMath.HitFraction(i));
            }
        }

        [Test]
        public void CriticalTableMatchesBinaryTable()
        {
            var crit = LongList(Tables["criticalTable"]);
            for (int stage = 0; stage < crit.Count; stage++)
                Assert.AreEqual((int)crit[stage], CriticalHit.Denominator(stage, 1));
            Assert.AreEqual(new long[] { 24, 8, 2, 1 }, crit.ToArray());
        }

        [Test]
        public void CalcAffinityMatchesOracle()
        {
            var cases = Cases(Load("BattleTypes.json"), "calcAffinity");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
                Assert.AreEqual(I(c, "out"), TypeAffinity.Calc(I(c, "waza"), I(c, "poke"), B(c, "inverse")), $"waza {I(c, "waza")} poke {I(c, "poke")} inv {I(c, "inverse")}");
        }

        [Test]
        public void MulAffinityMatchesOracle()
        {
            var cases = Cases(Load("BattleTypes.json"), "mulAffinity");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
                Assert.AreEqual(I(c, "out"), TypeAffinity.Mul(I(c, "a"), I(c, "b")), $"a {I(c, "a")} b {I(c, "b")}");
        }

        [Test]
        public void TypeEffectivenessHandExamples()
        {
            Assert.AreEqual(AffinityId.Double, TypeAffinity.Calc((int)PokeType.Fire, (int)PokeType.Grass, false));
            Assert.AreEqual(AffinityId.Half, TypeAffinity.Calc((int)PokeType.Fire, (int)PokeType.Water, false));
            Assert.AreEqual(AffinityId.Zero, TypeAffinity.Calc((int)PokeType.Ground, (int)PokeType.Flying, false));
            Assert.AreEqual(AffinityId.Double, TypeAffinity.Calc((int)PokeType.Ground, (int)PokeType.Flying, true), "umgekehrt: 0 wird 2");
            Assert.AreEqual(AffinityId.Half, TypeAffinity.Calc((int)PokeType.Fire, (int)PokeType.Grass, true));
            Assert.AreEqual(AffinityId.Normal, TypeAffinity.Calc((int)PokeType.None, (int)PokeType.Grass, false));
            Assert.AreEqual(AffinityId.Normal, TypeAffinity.Calc((int)PokeType.Fire, (int)PokeType.None, true));
            // Feuer gegen Pflanze/Eis: 2 * 2 = 4
            Assert.AreEqual(AffinityId.Quadruple, TypeAffinity.CalcPair((int)PokeType.Fire, (int)PokeType.Grass, (int)PokeType.Ice, (int)PokeType.None, false));
            // Wasser gegen reines Wasser (Typ 2 = Typ 1): nur einmal gezaehlt; die Pml-Variante ohne Duplikatpruefung quadriert.
            Assert.AreEqual(AffinityId.Half, TypeAffinity.CalcPair((int)PokeType.Water, (int)PokeType.Water, (int)PokeType.Water, (int)PokeType.None, false));
            Assert.AreEqual(AffinityId.Quarter, TypeAffinity.CalcDual((int)PokeType.Water, (int)PokeType.Water, (int)PokeType.Water, false));
            // Pflanze gegen Feuer/Flug/Kaefer (drei Typen): 1/2 * 1/2 * 1/2 = 1/8
            Assert.AreEqual(4, TypeAffinity.CalcPair((int)PokeType.Grass, (int)PokeType.Fire, (int)PokeType.Flying, (int)PokeType.Bug, false));
            Assert.AreEqual(AffinityId.Zero, TypeAffinity.CalcPair((int)PokeType.Normal, (int)PokeType.Normal, (int)PokeType.Ghost, (int)PokeType.None, false));
            Assert.AreEqual(3, TypeAffinity.ConvAbout(AffinityId.Half));
            Assert.AreEqual(2, TypeAffinity.ConvAbout(AffinityId.Double));
            Assert.AreEqual(1, TypeAffinity.ConvAbout(AffinityId.Normal));
            Assert.AreEqual(0, TypeAffinity.ConvAbout(AffinityId.Zero));
        }

        [Test]
        public void TypeAffinityRejectsOutOfRangeValues()
        {
            Assert.Throws<System.ArgumentOutOfRangeException>(() => TypeAffinity.Calc(19, 0, false));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => TypeAffinity.Calc(0, 20, false));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => TypeAffinity.Mul(14, 7));
            Assert.Throws<System.ArgumentOutOfRangeException>(() => Nature.Modifier(25, 1));
        }

        [Test]
        public void MaxHpMatchesOracle()
        {
            var cases = Cases(Load("BattleStats.json"), "calcMaxHp");
            Assert.GreaterOrEqual(cases.Count, 50);
            foreach (var c in cases)
                Assert.AreEqual(I(c, "out"), StatCalculator.CalcMaxHp(I(c, "monsno"), I(c, "level"), I(c, "base"), I(c, "iv"), I(c, "ev")), c.ToString());
        }

        [Test]
        public void OtherStatsMatchOracle()
        {
            var root = Load("BattleStats.json");
            var map = new (string key, PowerId id)[]
            {
                ("calcAtk", PowerId.Attack), ("calcDef", PowerId.Defense), ("calcSpAtk", PowerId.SpAttack),
                ("calcSpDef", PowerId.SpDefense), ("calcAgi", PowerId.Speed),
            };
            foreach (var (key, id) in map)
            {
                var cases = Cases(root, key);
                Assert.GreaterOrEqual(cases.Count, 50, key);
                foreach (var c in cases)
                    Assert.AreEqual(I(c, "out"), StatCalculator.CalcStat(id, I(c, "level"), I(c, "base"), I(c, "iv"), I(c, "ev"), I(c, "nature")), $"{key} nature {I(c, "nature")}");
            }
        }

        [Test]
        public void NatureCorrectionAndTransformMatchOracle()
        {
            var root = Load("BattleStats.json");
            var corr = Cases(root, "correctedPower");
            Assert.GreaterOrEqual(corr.Count, 50);
            foreach (var c in corr)
                Assert.AreEqual(I(c, "out"), (int)(Nature.Correct(U32(c, "value"), I(c, "nature"), I(c, "powerId")) & 0xFFFF), $"value {I(c, "value")} nature {I(c, "nature")} id {I(c, "powerId")}");
            var trans = Cases(root, "powerTransform");
            Assert.GreaterOrEqual(trans.Count, 50);
            foreach (var c in trans)
                Assert.AreEqual(I(c, "out"), Nature.Modifier(I(c, "nature"), I(c, "powerId")));
        }

        [Test]
        public void StatHandExamples()
        {
            // Level 50, Basis 100, IV 31, EV 252: (200 + 31 + 63) * 50 / 100 = 147
            Assert.AreEqual(207, StatCalculator.CalcMaxHp(1, 50, 100, 31, 252));
            Assert.AreEqual(152, StatCalculator.CalcAttack(50, 100, 31, 252, 0));
            Assert.AreEqual(167, StatCalculator.CalcAttack(50, 100, 31, 252, 3), "Hart (+Angriff): 152 * 110 / 100 = 167");
            Assert.AreEqual(136, StatCalculator.CalcAttack(50, 100, 31, 252, 5), "Kuehn (-Angriff): 152 * 90 / 100 = 136");
            Assert.AreEqual(1, StatCalculator.CalcMaxHp(StatCalculator.FixedHpSpecies, 100, 1, 31, 252));
            // EV-Bruchteil wird abgeschnitten: 255 -> 63
            Assert.AreEqual(StatCalculator.CalcMaxHp(1, 50, 100, 31, 252), StatCalculator.CalcMaxHp(1, 50, 100, 31, 255));
            // Die Maske 0xfffe wickelt das Produkt ab Wert 596 (x110 >= 65536) um: 700 * 110 = 77000 -> 11464 -> 114
            Assert.AreEqual(114u, Nature.Correct(700, 1, 1));
            Assert.AreEqual(700u, Nature.Correct(700, 0, 1));
            Assert.AreEqual(700u, Nature.Correct(700, 3, 0), "Kraft-ID 0 hat keine Wesenswirkung");
        }

        [Test]
        public void StatsFromSpeciesRecord()
        {
            var species = new SpeciesRecord { Id = 25, BaseHp = 100, BaseAttack = 100, BaseDefense = 100, BaseSpAttack = 100, BaseSpDefense = 100, BaseSpeed = 100 };
            var iv = new StatSpread { Hp = 31, Attack = 31, Defense = 31, SpAttack = 31, SpDefense = 31, Speed = 31 };
            var ev = new StatSpread { Hp = 252, Attack = 252, Defense = 252, SpAttack = 252, SpDefense = 252, Speed = 252 };
            var stats = StatCalculator.Calc(species, 50, iv, ev, 0);
            Assert.AreEqual(207, stats.Hp);
            Assert.AreEqual(152, stats.Speed);
            Assert.AreEqual(152, stats.SpDefense);
        }
    }
}
