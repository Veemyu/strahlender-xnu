using System;
using System.Collections.Generic;
using Xnu.Battle;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.PokePara;

namespace Xnu.Tests
{
    // Synthetische Stammdaten (nur Zahlen, keine Spielinhalte) fuer die Ablauf-Tests.
    static class BattleFlowTestData
    {
        public const int Mon1 = 1;     // "Pflanze/Gift", mittel
        public const int Mon2 = 4;     // "Feuer", schnell
        public const int Mon3 = 25;    // "Elektro", sehr schnell
        public const int Mon4 = 95;    // "Gestein/Boden", langsam
        public const int Ghost = 92;   // "Geist"

        public const int Tackle = 33, QuickAttack = 98, Ember = 52, ThunderWave = 86, Sing = 47, Toxic = 92, Growl = 45, Recover = 105,
            RainDance = 240, SunnyDay = 241, Sandstorm = 201, Hail = 258, DoubleEdge = 38, GigaDrain = 202, FuryAttack = 31, DoubleKick = 24,
            Fissure = 90, SwordsDance = 14, Wrap = 35, ConfuseRay = 109, Flamethrower = 53, IceBeam = 58, Splash = 150, Struggle = 165, Pound = 1,
            Reflect = 115, StealthRock = 446, Spikes = 191, Protect = 197, TrickRoom = 433, Tailwind = 366;

        static SpeciesRecord Species(int id, int hp, int atk, int def, int spa, int spd, int spe, int t1, int t2, int giveExp, int evBits, int grow = 0)
            => new SpeciesRecord
            {
                IsValid = true, Id = id, DexNo = id, FormCount = 1, BaseHp = hp, BaseAttack = atk, BaseDefense = def, BaseSpAttack = spa, BaseSpDefense = spd,
                BaseSpeed = spe, Type1 = t1, Type2 = t2, GiveExp = giveExp, ExpValue = evBits, GrowthCurve = grow, GenderRatio = 127, Ability1 = 0, InitialFriendship = 70,
            };

        static MoveRecord Move(int no, int type, int cat, int dmgType, int power, int acc, int pp, int prio = 0)
            => new MoveRecord { MoveNo = no, IsValid = true, Type = type, Category = cat, DamageType = dmgType, Power = power, Accuracy = acc, BasePp = pp, Priority = prio };

        public static BattleData Create()
        {
            var species = new List<SpeciesRecord>
            {
                Species(Mon1, 45, 49, 49, 65, 65, 45, 11, 3, 64, 1 << 8),
                Species(Mon2, 39, 52, 43, 60, 50, 65, 9, 9, 62, 1 << 6),
                Species(Mon3, 35, 55, 40, 50, 50, 90, 12, 12, 112, 2 << 6),
                Species(Mon4, 35, 45, 160, 30, 45, 70, 5, 4, 70, 1 << 4),
                Species(Ghost, 30, 35, 30, 100, 35, 80, 7, 3, 95, 1 << 8),
            };
            var moves = new List<MoveRecord>
            {
                Move(Tackle, 0, 0, 1, 40, 100, 35),
                Move(Pound, 0, 0, 1, 40, 100, 35),
                Move(QuickAttack, 0, 0, 1, 40, 100, 30, 1),
                Move(Ember, 9, 4, 2, 40, 100, 25),
                Move(ThunderWave, 12, 1, 0, 0, 90, 20),
                Move(Sing, 0, 1, 0, 0, 55, 15),
                Move(Toxic, 3, 1, 0, 0, 90, 10),
                Move(Growl, 0, 2, 0, 0, 100, 40),
                Move(Recover, 0, 3, 0, 0, 101, 10),
                Move(RainDance, 10, 10, 0, 0, 101, 5),
                Move(SunnyDay, 9, 10, 0, 0, 101, 5),
                Move(Sandstorm, 5, 10, 0, 0, 101, 10),
                Move(Hail, 14, 10, 0, 0, 101, 10),
                Move(DoubleEdge, 0, 0, 1, 120, 100, 15),
                Move(GigaDrain, 11, 8, 2, 75, 100, 10),
                Move(FuryAttack, 0, 0, 1, 15, 85, 20),
                Move(DoubleKick, 1, 0, 1, 30, 100, 30),
                Move(Fissure, 4, 9, 1, 1, 30, 5),
                Move(SwordsDance, 0, 2, 0, 0, 101, 20),
                Move(Wrap, 0, 4, 1, 15, 90, 20),
                Move(ConfuseRay, 7, 1, 0, 0, 100, 10),
                Move(Flamethrower, 9, 4, 2, 90, 100, 15),
                Move(IceBeam, 14, 4, 2, 90, 100, 10),
                Move(Splash, 0, 13, 0, 0, 101, 40),
                Move(Struggle, 18, 0, 1, 50, 0, 1),
                Move(Reflect, 14 - 4, 11, 0, 0, 101, 20),
                Move(StealthRock, 5, 11, 0, 0, 101, 20),
                Move(Spikes, 4, 11, 0, 0, 101, 20),
                Move(Protect, 0, 12, 0, 0, 101, 10, 4),
                Move(TrickRoom, 14, 11, 0, 0, 101, 5, -7),
                Move(Tailwind, 2, 11, 0, 0, 101, 15),
            };
            Set(moves, Reflect, m => m.Target = 7);
            Set(moves, Protect, m => m.Target = 7);
            Set(moves, TrickRoom, m => m.Target = 10);
            Set(moves, Tailwind, m => m.Target = 7);
            Set(moves, ThunderWave, m => { m.StatusId = Sick.Paralysis; m.StatusContinuation = 1; });
            Set(moves, Sing, m => { m.StatusId = Sick.Sleep; m.StatusContinuation = 2; m.StatusTurnMin = 2; m.StatusTurnMax = 4; });
            Set(moves, Toxic, m => { m.StatusId = Sick.Poison; m.StatusContinuation = 1; m.StatusTurnMin = 15; m.StatusTurnMax = 15; });
            Set(moves, ConfuseRay, m => { m.StatusId = Sick.Confusion; m.StatusContinuation = 2; m.StatusTurnMin = 2; m.StatusTurnMax = 5; });
            Set(moves, Ember, m => { m.StatusId = Sick.Burn; m.StatusChance = 10; m.StatusContinuation = 1; });
            Set(moves, Flamethrower, m => { m.StatusId = Sick.Burn; m.StatusChance = 100; m.StatusContinuation = 1; });
            Set(moves, Wrap, m => { m.StatusId = Sick.Bind; m.StatusChance = 100; m.StatusContinuation = 4; m.StatusTurnMin = 5; m.StatusTurnMax = 5; });
            Set(moves, Growl, m => { m.Target = 5; m.StatStageTypes[0] = 1; m.StatStageValues[0] = -1; });
            Set(moves, SwordsDance, m => { m.Target = 7; m.StatStageTypes[0] = 1; m.StatStageValues[0] = 2; });
            Set(moves, Recover, m => { m.Target = 7; m.HpRecoverRatio = 50; });
            Set(moves, DoubleEdge, m => m.DamageRecoverRatio = -33);
            Set(moves, GigaDrain, m => m.DamageRecoverRatio = 50);
            Set(moves, FuryAttack, m => { m.HitCountMax = 5; m.HitCountMin = 2; });
            Set(moves, DoubleKick, m => { m.HitCountMax = 2; m.HitCountMin = 2; });
            Set(moves, RainDance, m => m.Target = 10);
            Set(moves, SunnyDay, m => m.Target = 10);
            Set(moves, Sandstorm, m => m.Target = 10);
            Set(moves, Hail, m => m.Target = 10);
            Set(moves, Splash, m => m.Target = 7);

            var items = new List<ItemRecord>
            {
                new ItemRecord { ItemNo = 17, Effects = { ["wk_prm_hp_rcv"] = 20 } },
                new ItemRecord { ItemNo = 18, Effects = { ["wk_prm_hp_rcv"] = 255 } },
            };
            var growth = new List<GrowthCurveRecord>();
            for (int curve = 0; curve < 6; curve++)
            {
                var exps = new int[101];
                for (int l = 1; l <= 100; l++) exps[l] = (int)Math.Max(0, GrowthRate.ExpForLevel(GrowthRate.CurveForRow(curve), l));
                growth.Add(new GrowthCurveRecord { ExpByLevel = exps });
            }
            return new BattleData(species, moves, items, growth);
        }

        static void Set(List<MoveRecord> moves, int no, Action<MoveRecord> change) => change(moves.Find(m => m.MoveNo == no));

        public static PokemonParam Mon(BattleData data, int species, int level, params int[] moves)
            => PokemonFactory.Create(data, species, 0, level, 0, 0, moves, 0, new[] { 15, 15, 15, 15, 15, 15 }, null, 0);

        public static BattleEngine Engine(BattleSetup setup)
        {
            var e = new BattleEngine(setup);
            e.Start();
            return e;
        }

        public static BattleSetup Setup(BattleData data, ulong seed, PokemonParam player, PokemonParam enemy, BattleCompetitor competitor = BattleCompetitor.Wild)
        {
            var s = new BattleSetup { Data = data, Seed = seed, Competitor = competitor };
            s.PlayerParty.Add(player);
            s.EnemyParty.Add(enemy);
            return s;
        }
    }
}
