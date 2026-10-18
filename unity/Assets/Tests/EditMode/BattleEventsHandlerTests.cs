using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using Xnu.Battle;
using Xnu.Battle.Events;
using static Xnu.Tests.BattleFixtures;

namespace Xnu.Tests
{
    // Handler (Faehigkeiten/Items), Registrierung und die Verdrahtung mit Schaden/Treffer aus Scheibe 1
    // (Spezifikation docs/kampf-spezifikation-2.md Abschnitte 5 und 7).
    public class BattleEventsHandlerTests
    {
        sealed class FixedRandom : IBattleRandom
        {
            readonly ulong _value;
            public int Draws;
            public FixedRandom(ulong value) => _value = value;
            public ulong GetValue(ulong max)
            {
                Draws++;
                return max == 0 ? _value : _value % max;
            }
        }

        static BattlePoke Poke(byte id, ushort attack = 100, ushort defence = 100, ushort spAttack = 100, ushort spDefence = 100,
            ushort agility = 100, byte type1 = 0, ushort tokusei = 0, ushort item = 0)
        {
            return new BattlePoke(id)
            {
                Attack = attack, Defence = defence, SpAttack = spAttack, SpDefence = spDefence, Agility = agility,
                Type1 = type1, Tokusei = tokusei, Item = item, Hp = 200, MaxHp = 200, Level = 50,
            };
        }

        static (EventSystem es, BattleEventsTestEnv env) World(params BattlePoke[] pokes)
        {
            var env = new BattleEventsTestEnv();
            foreach (var p in pokes) env.AddPoke(p);
            return (new EventSystem(env), env);
        }

        static void RegisterAll(EventSystem es, params BattlePoke[] pokes)
        {
            foreach (var p in pokes)
            {
                TokuseiHandlers.Add(es, p);
                ItemHandlers.Add(es, p);
            }
        }

        static readonly MoveInfo Tackle = new MoveInfo { WazaId = 33, Type = 0, DamageType = 1, Power = 60, HitPercent = 70 };

        // ------------------------------------------------------------------------------------------------------
        // Registrierung (Tokusei.Add/Remove/Swap, Item.Add/Remove)
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void TokuseiAddUsesTheAbilityNumberAndBaseSpeedAsPriorities()
        {
            var p = Poke(2, agility: 120, tokusei: TokuseiHandlers.Tikaramoti);
            var (es, _) = World(p);
            var f = TokuseiHandlers.Add(es, p);
            Assert.AreEqual(EventFactorType.TOKUSEI, f.FactorType);
            Assert.AreEqual(TokuseiHandlers.Tikaramoti, f.SubId);
            Assert.AreEqual(2, f.DependId);
            Assert.AreEqual(2, f.PokeId);
            Assert.AreEqual(1u, f.NumHandlers);
            Assert.AreEqual(0x2000000u | 120u, f.Priority);
            Assert.AreEqual(0u, f.EventLevel);
            Assert.AreEqual(EventId.ATTACKER_POWER, f.HandlerTable[0].EventId);
        }

        [Test]
        public void TokuseiWithoutHandlerRegistersNothing()
        {
            var p = Poke(0, tokusei: 22);
            var (es, _) = World(p);
            Assert.IsNull(TokuseiHandlers.Add(es, p));
            Assert.IsNull(es.Container.First);
        }

        [Test]
        public void FasterPokemonAreCalledFirstWithinTheSameMainPriority()
        {
            var slow = Poke(0, agility: 50, tokusei: TokuseiHandlers.Fukugan);
            var fast = Poke(1, agility: 150, tokusei: TokuseiHandlers.Fukugan);
            var (es, _) = World(slow, fast);
            TokuseiHandlers.Add(es, slow);
            TokuseiHandlers.Add(es, fast);
            Assert.AreEqual(1, es.Container.First.DependId);
            Assert.AreEqual(0, es.Container.First.Next.DependId);
            // Gleichstand: der zuerst registrierte kommt zuerst
            var twin = Poke(2, agility: 150, tokusei: TokuseiHandlers.Fukugan);
            Assert.IsNotNull(TokuseiHandlers.Add(es, twin));
            Assert.AreEqual(new byte[] { 1, 2, 0 }, new[] { es.Container.First.DependId, es.Container.First.Next.DependId, es.Container.First.Next.Next.DependId });
        }

        [Test]
        public void TokuseiRemoveAndSwapMoveFactorsBetweenPokemon()
        {
            var a = Poke(0, tokusei: TokuseiHandlers.Tikaramoti);
            var b = Poke(1, tokusei: TokuseiHandlers.Fukugan);
            var (es, _) = World(a, b);
            TokuseiHandlers.Add(es, a);
            TokuseiHandlers.Add(es, b);
            TokuseiHandlers.Remove(es, a);
            Assert.AreEqual(1, es.Container.SeekFactor(EventFactorType.TOKUSEI).DependId);
            Assert.IsNull(es.Container.SeekFactor(EventFactorType.TOKUSEI, 0));

            TokuseiHandlers.Add(es, a);
            (a.Tokusei, b.Tokusei) = (b.Tokusei, a.Tokusei);
            TokuseiHandlers.Swap(es, a, b);
            Assert.AreEqual(TokuseiHandlers.Fukugan, es.Container.SeekFactor(EventFactorType.TOKUSEI, 0).SubId);
            Assert.AreEqual(TokuseiHandlers.Tikaramoti, es.Container.SeekFactor(EventFactorType.TOKUSEI, 1).SubId);
        }

        [Test]
        public void TokuseiRemoveStopsAtFactorsWithWorkValue4()
        {
            var a = Poke(0, tokusei: TokuseiHandlers.Tikaramoti);
            var (es, _) = World(a);
            var f = TokuseiHandlers.Add(es, a);
            f.SetWorkValue(4, 1);
            TokuseiHandlers.Remove(es, a);
            Assert.IsTrue(f.Exists);
        }

        [Test]
        public void ItemAddUsesItemLevelAndItemPriority()
        {
            var p = Poke(1, agility: 80, item: ItemHandlers.InotiNoTama);
            var (es, _) = World(p);
            var f = ItemHandlers.Add(es, p);
            Assert.AreEqual(EventFactorType.ITEM, f.FactorType);
            Assert.AreEqual(ItemHandlers.InotiNoTama, f.SubId);
            Assert.AreEqual(0x1000000u | 80u, f.Priority);
            Assert.AreEqual(1, f.PokeId);
            Assert.IsNull(ItemHandlers.AddHandler(es, p, 1), "kein Handler fuer Item 1");
        }

        [Test]
        public void ItemRemoveKeepsFactorsWithWorkValue6()
        {
            var p = Poke(1, item: ItemHandlers.KoukakuLens);
            var (es, _) = World(p);
            var f = ItemHandlers.Add(es, p);
            f.SetWorkValue(6, 1);
            ItemHandlers.Remove(es, p);
            Assert.IsTrue(f.Exists);
            f.SetWorkValue(6, 0);
            ItemHandlers.Remove(es, p);
            Assert.IsFalse(f.Exists);
            Assert.IsNull(es.Container.First);
        }

        // ------------------------------------------------------------------------------------------------------
        // Einzelne Handler (handgerechnet aus dem Pseudocode)
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void ItemRatioFormulaConvertsPercentToFixedPoint()
        {
            Assert.AreEqual(0x1000, ItemHandlers.AttackValueToRatio(0));
            Assert.AreEqual(4505, ItemHandlers.AttackValueToRatio(10));   // 1,1
            Assert.AreEqual(5324, ItemHandlers.AttackValueToRatio(30));   // 1,3
            Assert.AreEqual(0x800, ItemHandlers.AttackValueToRatio(-50));
            Assert.AreEqual(0, ItemHandlers.AttackValueToRatio(-100));
        }

        [Test]
        public void ItemRatioMatchesTheRealFloatingPointCode()
        {
            var table = (List<object>)Load("BattleEventsHandlers.json")["itemRatios"];
            Assert.GreaterOrEqual(table.Count, 1000);
            foreach (var row in table)
            {
                var pair = LongList(row);
                Assert.AreEqual((int)pair[1], ItemHandlers.AttackValueToRatio((int)pair[0]), "Item-Wert " + pair[0]);
            }
        }

        [Test]
        public void HugePowerDoublesPhysicalAttackOnlyForItsOwner()
        {
            var me = Poke(0, attack: 100, spAttack: 100, tokusei: TokuseiHandlers.Tikaramoti);
            var other = Poke(1);
            var (es, _) = World(me, other);
            RegisterAll(es, me, other);
            var launcher = new BattleEventLauncher(es);
            Assert.AreEqual(200u, launcher.GetAttackPower(me, other, Tackle, false, out _));
            Assert.AreEqual(100u, launcher.GetAttackPower(other, me, Tackle, false, out _), "fremder Angriff");
            var special = new MoveInfo { WazaId = 1, Type = 0, DamageType = 2, Power = 60, HitPercent = 100 };
            Assert.AreEqual(100u, launcher.GetAttackPower(me, other, special, false, out _), "nur physisch");
        }

        [Test]
        public void ThickFatHalvesFireAndIceAgainstItsOwner()
        {
            var me = Poke(0, tokusei: TokuseiHandlers.AtuiSibou);
            var foe = Poke(1, attack: 100, spAttack: 100);
            var (es, _) = World(me, foe);
            RegisterAll(es, me, foe);
            var launcher = new BattleEventLauncher(es);
            foreach (var (type, expected) in new[] { ((byte)9, 50u), ((byte)14, 50u), ((byte)10, 100u), ((byte)0, 100u) })
            {
                var move = new MoveInfo { WazaId = 52, Type = type, DamageType = 2, Power = 40, HitPercent = 100 };
                Assert.AreEqual(expected, launcher.GetAttackPower(foe, me, move, false, out _), "Typ " + type);
            }
            Assert.AreEqual(100u, launcher.GetAttackPower(me, foe, new MoveInfo { Type = 9, DamageType = 2 }, false, out _), "Dickes Fell schuetzt nur den Besitzer");
        }

        [Test]
        public void TechnicianBoostsWeakMovesOnly()
        {
            var me = Poke(0, tokusei: TokuseiHandlers.Tekunisyan);
            var foe = Poke(1);
            var (es, _) = World(me, foe);
            RegisterAll(es, me, foe);
            var launcher = new BattleEventLauncher(es);
            foreach (var (power, expected) in new[] { (40, 60u), (60, 90u), (61, 61u), (100, 100u), (1, 1u) })
            {
                var move = new MoveInfo { WazaId = 1, Type = 0, DamageType = 1, Power = (ushort)power, HitPercent = 100 };
                Assert.AreEqual(expected, launcher.GetWazaPower(me, foe, move), "Kraft " + power);
            }
        }

        [Test]
        public void ChoiceBandBoostsPhysicalAttackUnlessInGMode()
        {
            var me = Poke(0, attack: 100, item: ItemHandlers.KodawariHachimaki);
            var foe = Poke(1);
            var (es, _) = World(me, foe);
            RegisterAll(es, me, foe);
            var launcher = new BattleEventLauncher(es);
            Assert.AreEqual(150u, launcher.GetAttackPower(me, foe, Tackle, false, out _));
            me.IsGMode = true;
            Assert.AreEqual(100u, launcher.GetAttackPower(me, foe, Tackle, false, out _));
        }

        [Test]
        public void ItemHandlersAreSilencedByMagicRoomAndEmbargo()
        {
            var me = Poke(0, attack: 100, item: ItemHandlers.KodawariHachimaki);
            var foe = Poke(1);
            var (es, _) = World(me, foe);
            RegisterAll(es, me, foe);
            var launcher = new BattleEventLauncher(es);
            me.SetSick(WazaSickIds.SASIOSAE, 1);
            Assert.AreEqual(100u, launcher.GetAttackPower(me, foe, Tackle, false, out _));
            me.SetSick(WazaSickIds.SASIOSAE, 0);
            Assert.AreEqual(150u, launcher.GetAttackPower(me, foe, Tackle, false, out _));
        }

        [Test]
        public void HandlersAgreeWithTheRealFunctionsInsideTheRealEventSystem()
        {
            var cases = Cases(Load("BattleEventsHandlers.json"), "cases");
            Assert.GreaterOrEqual(cases.Count, 700);
            int called = 0;
            foreach (var c in cases)
            {
                string where = "Fall " + cases.IndexOf(c) + " " + c["handler"];
                var env = BattleEventsTestEnv.FromJson((Dictionary<string, object>)c["env"]);
                var sc = new BattleEventsScenario(env);
                var spec = (Dictionary<string, object>)((List<object>)c["adds"])[0];
                var type = (EventFactorType)Convert.ToInt32(spec["type"]);
                ushort sub = Convert.ToUInt16(spec["subID"]);
                byte depend = Convert.ToByte(spec["dependID"]);
                EventHandlerTable[] original;
                if (type == EventFactorType.TOKUSEI)
                {
                    var pri = EventPriority.TOKUSEI;
                    original = TokuseiHandlers.GetHandlerGetFunc(sub)(ref pri);
                }
                else original = ItemHandlers.GetTable(sub);
                Assert.IsNotNull(original, where);
                var logged = original.Select(t => new EventHandlerTable(t.EventId, (args, d) =>
                {
                    sc.Log.Add(new long[] { (long)t.EventId, args.MyFactor.InstanceId, d, sc.Es.EventLevel });
                    t.Handler(args, d);
                })).ToArray();
                var pri2 = (EventPriority)Convert.ToInt32(spec["mainPri"]);
                uint subPri = Convert.ToUInt32(spec["subPri"]);
                sc.Es.AddFactor(type, sub, pri2, subPri, depend, logged, (byte)logged.Length);
                foreach (var step in (List<object>)c["steps"]) sc.Exec((List<object>)step);

                var expected = Matrix(c["log"]);
                Assert.AreEqual(expected.Count, sc.Log.Count, where + " Anzahl");
                for (int i = 0; i < expected.Count; i++) CollectionAssert.AreEqual(expected[i], sc.Log[i], where + " Eintrag " + i);
                if (expected.Any(e => e[0] >= 0)) called++;
            }
            Assert.GreaterOrEqual(called, 600, "die meisten Faelle muessen den Handler wirklich aufrufen");
        }

        // ------------------------------------------------------------------------------------------------------
        // Verdrahtung mit Treffer und Schaden aus Scheibe 1
        // ------------------------------------------------------------------------------------------------------

        [Test]
        public void HitInputWithoutHandlersCarriesTheBaseValues()
        {
            var a = Poke(0);
            var d = Poke(1);
            var (es, _) = World(a, d);
            var input = new BattleEventLauncher(es).BuildHitInput(a, d, Tackle);
            Assert.AreEqual(70u, input.HitPercent);
            Assert.AreEqual(6, input.AccuracyStage);
            Assert.AreEqual(6, input.EvasionStage);
            Assert.IsFalse(input.IgnoreEvasion);
            Assert.AreEqual(0x1000, input.HandlerRatio);
            Assert.AreEqual(70u, AccuracyCalculator.Percent(input, out _));
        }

        [Test]
        public void CompoundEyesAndWideLensRaiseTheAccuracy()
        {
            var eyes = Poke(0, tokusei: TokuseiHandlers.Fukugan);
            var lens = Poke(2, item: ItemHandlers.KoukakuLens);
            var both = Poke(3, tokusei: TokuseiHandlers.Fukugan, item: ItemHandlers.KoukakuLens);
            var d = Poke(1);
            var (es, env) = World(eyes, lens, both, d);
            env.ItemAttackValue = 10;
            RegisterAll(es, eyes, lens, both, d);
            var launcher = new BattleEventLauncher(es);
            // 70 * 0x14CD / 4096 = 91,0 ; 70 * 4505 / 4096 = 76,99 -> 77 (Rest 4054 > 0x800 rundet auf) ; beide: Verhaeltnis 5856 -> 100
            Assert.AreEqual(91u, launcher.BuildHitInput(eyes, d, Tackle).HitPercent);
            Assert.AreEqual(77u, launcher.BuildHitInput(lens, d, Tackle).HitPercent);
            Assert.AreEqual(100u, launcher.BuildHitInput(both, d, Tackle).HitPercent);
            Assert.AreEqual(70u, launcher.BuildHitInput(d, eyes, Tackle).HitPercent, "nur der Besitzer profitiert");
            Assert.AreEqual(91u, AccuracyCalculator.Percent(launcher.BuildHitInput(eyes, d, Tackle), out _));
        }

        [Test]
        public void HitInputReadsStagesAndFlagsFromTheEventFrame()
        {
            var a = Poke(0);
            var d = Poke(1);
            a.SetRank(PokeValueId.HIT_RATIO, 8);
            d.SetRank(PokeValueId.AVOID_RATIO, 9);
            d.SetSick(WazaSickIds.MIYABURU, 1);
            a.SetTurnFlag(TurnFlags.HitRatioUp, true);
            var (es, _) = World(a, d);
            var input = new BattleEventLauncher(es).BuildHitInput(a, d, Tackle);
            Assert.AreEqual(8, input.AccuracyStage);
            Assert.AreEqual(9, input.EvasionStage);
            Assert.IsTrue(input.TargetIdentified);
            Assert.IsTrue(input.AttackerTurnBoost);
        }

        [Test]
        public void DamageInputCollectsPowerAttackGuardStabAndFinalRatio()
        {
            var a = Poke(0, attack: 100, tokusei: TokuseiHandlers.Tikaramoti);
            var d = Poke(1, defence: 100);
            var (es, _) = World(a, d);
            RegisterAll(es, a, d);
            var input = new BattleEventLauncher(es).BuildDamageInput(a, d, Tackle, false, AffinityId.Normal, BattleWeather.None, false);
            Assert.AreEqual(60u, input.Power);
            Assert.AreEqual(200u, input.Attack, "Kraftkoloss");
            Assert.AreEqual(100u, input.Defense);
            Assert.AreEqual(50u, input.Level);
            Assert.AreEqual(0x1800u, input.StabRatio, "Normal-Attacke eines Normal-Pokemon");
            Assert.IsNotNull(input.FinalRatioFunc);
            Assert.AreEqual(0x1000u, input.FinalRatioFunc(100));
        }

        [Test]
        public void EventDrivenDamageEqualsTheHandCalculatedInputs()
        {
            var a = Poke(0, attack: 100, tokusei: TokuseiHandlers.Tikaramoti, item: ItemHandlers.InotiNoTama);
            var d = Poke(1, defence: 100);
            var (es, env) = World(a, d);
            env.ItemAttackValue = 30;
            RegisterAll(es, a, d);
            var viaEvents = new BattleEventLauncher(es).BuildDamageInput(a, d, Tackle, false, AffinityId.Normal, BattleWeather.None, false);
            var manual = new DamageInput
            {
                Power = 60, Attack = 200, Defense = 100, Level = 50, MoveType = 0, Category = DamageCategory.Physical,
                StabRatio = 0x1800, Affinity = AffinityId.Normal, FinalRatio = 5324,
            };
            foreach (ulong roll in new ulong[] { 0, 5, 15 })
            {
                var r1 = DamageCalculator.Calc(viaEvents, new FixedRandom(roll));
                var r2 = DamageCalculator.Calc(manual, new FixedRandom(roll));
                Assert.AreEqual(r2.Damage, r1.Damage, "Zufall " + roll);
                Assert.AreEqual(r2.Roll, r1.Roll);
            }
            // ohne Lebensorb waere der Schaden kleiner
            var plain = new DamageInput
            {
                Power = 60, Attack = 200, Defense = 100, Level = 50, MoveType = 0, Category = DamageCategory.Physical,
                StabRatio = 0x1800, Affinity = AffinityId.Normal,
            };
            Assert.Greater(DamageCalculator.Calc(viaEvents, new FixedRandom(0)).Damage, DamageCalculator.Calc(plain, new FixedRandom(0)).Damage);
        }

        [Test]
        public void ExpertBeltOnlyBoostsSuperEffectiveHits()
        {
            var a = Poke(0, item: ItemHandlers.TatuzinNoObi);
            var d = Poke(1);
            var (es, env) = World(a, d);
            env.ItemAttackValue = 20;
            RegisterAll(es, a, d);
            var launcher = new BattleEventLauncher(es);
            Assert.AreEqual(0x1000u, launcher.GetFinalDamageRatio(a, d, Tackle, AffinityId.Normal, false, false, 100));
            Assert.AreEqual(0x1000u, launcher.GetFinalDamageRatio(a, d, Tackle, 6, false, false, 100));
            Assert.AreEqual((uint)ItemHandlers.AttackValueToRatio(20), launcher.GetFinalDamageRatio(a, d, Tackle, 8, false, false, 100));
        }

        [Test]
        public void SpecialMovesGetWisdomGlassesPowerRatio()
        {
            var a = Poke(0, item: ItemHandlers.MonosiriMegane);
            var d = Poke(1);
            var (es, env) = World(a, d);
            env.ItemAttackValue = 10;
            RegisterAll(es, a, d);
            var launcher = new BattleEventLauncher(es);
            var special = new MoveInfo { WazaId = 1, Type = 0, DamageType = 2, Power = 80, HitPercent = 100 };
            // 80 * 4505 = 360400 -> 87,98 -> 88
            Assert.AreEqual(88u, launcher.GetWazaPower(a, d, special));
            Assert.AreEqual(80u, launcher.GetWazaPower(a, d, new MoveInfo { WazaId = 1, Type = 0, DamageType = 1, Power = 80 }));
        }

        [Test]
        public void AttackerWithCriticalHitIgnoresNegativeAttackStagesAndTargetIgnoresPositiveGuardStages()
        {
            var a = Poke(0, attack: 100);
            var d = Poke(1, defence: 100);
            a.SetRank(PokeValueId.ATTACK_RANK, 3);       // -3 Stufen
            d.SetRank(PokeValueId.DEFENCE_RANK, 9);      // +3 Stufen
            var (es, _) = World(a, d);
            var launcher = new BattleEventLauncher(es);
            // Stufe -3: 2/5 -> 40 ; Stufe +3: 5/2 -> 250
            Assert.AreEqual(40u, launcher.GetAttackPower(a, d, Tackle, false, out _));
            Assert.AreEqual(100u, launcher.GetAttackPower(a, d, Tackle, true, out _));
            Assert.AreEqual(250u, launcher.GetDefenderGuard(a, d, Tackle, false, BattleWeather.None));
            Assert.AreEqual(100u, launcher.GetDefenderGuard(a, d, Tackle, true, BattleWeather.None));
        }

        [Test]
        public void SandstormBoostsSpecialGuardOfRockTypesOnly()
        {
            var a = Poke(0);
            var rock = Poke(1, spDefence: 100, type1: (byte)PokeType.Rock);
            var plain = Poke(2, spDefence: 100);
            var (es, _) = World(a, rock, plain);
            var launcher = new BattleEventLauncher(es);
            var special = new MoveInfo { WazaId = 1, Type = 0, DamageType = 2, Power = 60 };
            Assert.AreEqual(150u, launcher.GetDefenderGuard(a, rock, special, false, BattleWeather.Sandstorm));
            Assert.AreEqual(100u, launcher.GetDefenderGuard(a, rock, special, false, BattleWeather.None));
            Assert.AreEqual(100u, launcher.GetDefenderGuard(a, plain, special, false, BattleWeather.Sandstorm));
            Assert.AreEqual(100u, launcher.GetDefenderGuard(a, rock, Tackle, false, BattleWeather.Sandstorm), "physisch: keine Wirkung");
        }

        [Test]
        public void LauncherLeavesNoFrameBehind()
        {
            var a = Poke(0, tokusei: TokuseiHandlers.Tikaramoti);
            var d = Poke(1);
            var (es, _) = World(a, d);
            RegisterAll(es, a, d);
            var launcher = new BattleEventLauncher(es);
            launcher.BuildDamageInput(a, d, Tackle, true, AffinityId.Normal, BattleWeather.None, false).FinalRatioFunc(10);
            launcher.BuildHitInput(a, d, Tackle);
            Assert.IsTrue(es.VarStack.IsEmpty);
            Assert.AreEqual(0u, es.VarSetStack.StackPointer);
            Assert.AreEqual(0u, es.EventLevel);
        }
    }
}
