using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using Xnu.Data;

namespace Xnu.Battle.Flow
{
    // Spielzustand fuer die KI-Skripte: setzt die AI_CMD-Befehle (BattleAiCommand) auf der BattleEngine um (Einzelkampf).
    // AI-Seite: 0 = Verteidiger (Gegenueber), 1 = Angreifer (eigenes Pokemon), 2/3 = deren Partner (im Einzelkampf wie 0/1), 4 = Ersatzpokemon.
    // Stufen: [P] aus dem Pseudocode gelesen; [A] Annahme; nicht modellierte Zustaende liefern 0 ([N]).
    public sealed class AiWorld : IAiHost
    {
        readonly BattleEngine _e;
        readonly BattleRandom _rng;
        readonly BattleRandom _common;
        readonly HashSet<int> _opened = new HashSet<int>();
        int _logSeen;
        readonly Dictionary<int, HashSet<int>> _used = new Dictionary<int, HashSet<int>>();   // Attacken, die ein Pokemon im Kampf schon eingesetzt hat (CheckWazaStored)

        // Gemeinsamer Zufallswert der Runde (IF_COMMONRND_*, statisches Feld im Original) [A: einmal je Entscheidung gezogen].
        public ulong CommonRnd;

        public int Side;                 // Seite des KI-Pokemon
        public BattleMon Attacker;
        public BattleMon Defender;
        public BattleMon Bench;          // aktuelles Ersatzpokemon (Wechsel-KI)
        public int MoveSlot;
        public ushort MoveNo;
        public ushort ItemNo;

        public AiWorld(BattleEngine engine, ulong seed)
        {
            _e = engine;
            _rng = new BattleRandom(seed);
            _common = new BattleRandom(seed ^ 0x9E3779B97F4A7C15UL);   // [A] BTL_CLIENT-Zufall fuer IF_COMMONRND_* (eigene Folge, Seed unbekannt)
        }

        public BattleRandom Rng => _rng;

        public void Begin(int side)
        {
            Side = side;
            Attacker = _e.Active(side);
            Defender = _e.Active(1 - side);
            for (; _logSeen < _e.Log.Count; _logSeen++)
            {
                var l = _e.Log[_logSeen];
                if (l.Kind == LogKind.AbilityActivated && l.Poke >= 0) _opened.Add(l.Poke);
                if (l.Kind == LogKind.MoveUsed && l.Poke >= 0)
                {
                    if (!_used.TryGetValue(l.Poke, out var set)) _used[l.Poke] = set = new HashSet<int>();
                    set.Add(l.Id);
                }
            }
            CommonRnd = _common.GetValue(256);
        }

        BattleMon Bpp(long aiSide)
        {
            switch (aiSide)
            {
                case 0: case 2: return Defender;
                case 4: return Bench;
                default: return Attacker;
            }
        }

        MoveRecord Move(long no) => _e.Data.GetMove((int)no);

        static bool IsDamage(MoveRecord m) => m != null && m.DamageType != 0;

        int Pct4096(BattleMon m) => (int)(m.Poke.Hp * 100.0 / m.Poke.MaxHp * 4096);

        // [P] CheckTokuseiByAISide: Eigenes Pokemon sichtbar, beim Gegenueber nur Fangfaehigkeiten, offenbarte oder eine geratene Faehigkeit.
        long Tokusei(long aiSide)
        {
            var m = Bpp(aiSide);
            if (m == null) return 0;
            int ab = m.Poke.GetValue(PokeValueId.TOKUSEI);
            if (aiSide == 1 || aiSide == 3) return ab;
            if (ab == 23 || ab == 42 || ab == 71) return ab;
            if (_opened.Contains(m.PokeId)) return ab;
            var sp = m.Species;
            var cands = new List<int>();
            if (sp.Ability1 != 0) cands.Add(sp.Ability1);
            if (sp.Ability2 != 0) cands.Add(sp.Ability2);
            if (sp.Ability3 != 0) cands.Add(sp.Ability3);
            return cands.Count == 0 ? ab : cands[cands.Count == 1 ? 0 : (int)_rng.GetValue((ulong)cands.Count)];
        }

        int Affinity(BattleMon def, long moveNo)
        {
            var m = Move(moveNo);
            if (!IsDamage(m)) return AffinityId.Null;
            return TypeAffinity.CalcPair(m.Type, def.Poke.Type1, def.Poke.Type2, def.Poke.TypeEx, _e.Setup.Inverse);
        }

        bool Usable(BattleMon m, int slot) => m.Moves[slot] != 0 && m.Pp[slot] > 0;

        bool SideEff(BattleMon m, int kind)
        {
            var s = _e.Sides[m.Side];
            switch (kind)
            {
                case 0: return s.Reflect > 0;
                case 1: return s.LightScreen > 0;
                case 2: return s.Safeguard > 0;
                case 3: return s.Mist > 0;
                case 4: return s.Tailwind > 0;
                case 6: return s.Spikes > 0;
                case 7: return s.ToxicSpikes > 0;
                case 8: return s.StealthRock;
                case 14: return s.StickyWeb;
                case 17: return s.AuroraVeil > 0;
                default: return false;
            }
        }

        int SideEffCount(BattleMon m, int kind)
        {
            var s = _e.Sides[m.Side];
            if (kind == 6) return s.Spikes;
            if (kind == 7) return s.ToxicSpikes;
            return SideEff(m, kind) ? 1 : 0;
        }

        // Schadenswert wie BattleSimulator.CalcDamage der KI: der echte Schadensrechner der Engine mit festem Zufallsfaktor 85 (kein Volltreffer).
        public int EstimateDamage(BattleMon atk, BattleMon def, long moveNo) => _e.EstimateDamageForAi(atk, def, (int)moveNo);

        static double RankFactor(int rank) => rank >= 6 ? (2 + (rank - 6)) / 2.0 : 2.0 / (2 + (6 - rank));

        long Agility(BattleMon m)
        {
            double v = m.Poke.Agility * RankFactor(m.Poke.GetRank(PokeValueId.AGILITY_RANK));
            if (m.PokeSick == Sick.Paralysis) v /= 2;
            return (long)v;
        }

        public long Call(int cmd, long[] args)
        {
            long a0 = args.Length > 0 ? args[0] : 0;
            long a1 = args.Length > 1 ? args[1] : 0;
            long a2 = args.Length > 2 ? args[2] : 0;
            switch (cmd)
            {
                case AiCmd.IfRndUnder: return _rng.GetValue(256) < (ulong)a0 ? 1 : 0;                  // [P]
                case AiCmd.IfRndOver: return _rng.GetValue(256) > (ulong)a0 ? 1 : 0;                   // [A] Gegenstueck von IF_RND_UNDER
                case AiCmd.IfHpUnder: return (Pct4096(Bpp(a0)) >> 12) < a1 ? 1 : 0;                    // [P]
                case AiCmd.IfHpOver: return (Pct4096(Bpp(a0)) >> 12) > a1 ? 1 : 0;                     // [A]
                case AiCmd.IfHpEqual:                                                                  // [P] aufgerundet
                    {
                        int v = Pct4096(Bpp(a0));
                        int p = v >> 12;
                        if ((v & 0xfff) != 0) p++;
                        return a1 == p ? 1 : 0;
                    }
                case AiCmd.IfPokeSick: return Bpp(a0).PokeSick != 0 ? 1 : 0;                           // [P]
                case AiCmd.IfnPokeSick: return Bpp(a0).PokeSick == 0 ? 1 : 0;
                case AiCmd.IfWazaSick: return a1 >= 0 && a1 < Sick.Count && Bpp(a0).HasSick((int)a1) ? 1 : 0;   // [P]
                case AiCmd.IfnWazaSick: return a1 >= 0 && a1 < Sick.Count && Bpp(a0).HasSick((int)a1) ? 0 : 1;
                case AiCmd.IfContFlg: return 0;                                                        // [N]
                case AiCmd.IfSideEff:                                                                  // [P] Standard 0x16 = irgendein Effekt
                    {
                        long kind = args.Length < 2 ? 0x16 : a1;
                        var m = Bpp(a0);
                        if (kind == 0x16) { for (int k = 0; k < 18; k++) if (SideEff(m, k)) return 1; return 0; }
                        return SideEffCount(m, (int)kind) != 0 ? 1 : 0;
                    }
                case AiCmd.GetKodawariWaza: return Bpp(a0).ChoiceLock;                                 // [A]
                case AiCmd.CheckTurn: return _e.Turn;                                                  // [A]
                case AiCmd.CheckType: return TypeOf(a0);                                               // [P]
                case AiCmd.CheckDamageWaza: return IsDamage(Move(a0)) ? 1 : 0;                         // [P]
                case AiCmd.CompPower: return CompPower();                                              // [P] Schaden vereinfacht
                case AiCmd.CheckLastWaza: return Bpp(a0).LastMove;                                     // [A]
                case AiCmd.IfFirst:                                                                    // [P]
                    {
                        long x = Agility(Attacker), y = Agility(Defender);
                        return a0 == 2 ? (x == y ? 1 : 0) : a0 == 1 ? (x < y ? 1 : 0) : a0 == 0 ? (y < x ? 1 : 0) : 0;
                    }
                case AiCmd.CheckBenchCount:                                                            // [P] lebende Pokemon der Seite ausser dem Frontkaempfer
                    {
                        var m = Bpp(a0);
                        int n = 0;
                        foreach (var p in _e.Parties[m.Side]) if (p != _e.Active(m.Side) && !p.IsFainted) n++;
                        return n;
                    }
                case AiCmd.CheckTokusei: return Tokusei(a0);                                           // [P]
                case AiCmd.CheckWazaAisyou:                                                            // [P]
                    {
                        var atk = Bpp(a0);
                        var def = Bpp(a1);
                        if (atk == null || def == null || !IsDamage(Move(a2))) return 0;
                        int aff = Affinity(def, a2);
                        long want = args.Length > 3 ? args[3] : 0;
                        if (aff == AffinityId.Null) return 0;
                        if (want == 9) return aff > 8 ? 1 : 0;
                        if (want == 5) return aff < 6 ? 1 : 0;
                        return aff == want ? 1 : 0;
                    }
                case AiCmd.IfHaveWazaAisyouOver:                                                       // [P]
                    {
                        var atk = Bpp(a0);
                        var def = Bpp(a1);
                        for (int i = 0; i < BattleMon.MoveCount; i++)
                        {
                            if (!Usable(atk, i) || !IsDamage(Move(atk.Moves[i]))) continue;
                            int aff = Affinity(def, atk.Moves[i]);
                            if (aff != AffinityId.Null && aff > a2) return 1;
                        }
                        return 0;
                    }
                case 18: case 19: return 0;                                                            // [N] Abgesang nicht modelliert
                case 22: return AnyDamageMove(Attacker) ? 0 : 1;                                       // [P]
                case 21: return AnyDamageMove(Attacker) ? 1 : 0;
                case 35:                                                                               // [P] Wirkungs-ID oder 7 (normal)
                    {
                        var atk = Bpp(a0);
                        var def = Bpp(a1);
                        if (atk == null || def == null || !IsDamage(Move(a2))) return 7;
                        int aff = Affinity(def, a2);
                        return aff == AffinityId.Null ? 7 : aff;
                    }
                case 37:                                                                               // [P]
                    {
                        var atk = Bpp(a0);
                        var def = Bpp(a1);
                        for (int i = 0; i < BattleMon.MoveCount; i++)
                        {
                            if (!Usable(atk, i) || !IsDamage(Move(atk.Moves[i]))) continue;
                            int aff = Affinity(def, atk.Moves[i]);
                            if (aff != AffinityId.Null && aff == a2) return 1;
                        }
                        return 0;
                    }
                case 116: return Bpp(a0) == Attacker ? Defender.LastMove : Attacker.LastMove;           // [A] letzte Attacke des Gegenspielers
                case 122: return Call(AiCmd.IfHaveBatsugun, args);                                     // [P]
                case 129: return 1;                                                                    // [A] Wechsel erlaubt
                case AiCmd.IfnBenchCond: return BenchCond() ? 0 : 1;                                   // [A] Zustand unter den Ersatzpokemon
                case AiCmd.IfBenchCond: return BenchCond() ? 1 : 0;
                case AiCmd.CheckWeather: return (long)_e.Weather.Weather;                              // [P]
                case AiCmd.IfParaUnder: return PokeValue(Bpp(a0), a1) < a2 ? 1 : 0;                    // [P]
                case AiCmd.IfParaOver: return PokeValue(Bpp(a0), a1) > a2 ? 1 : 0;
                case AiCmd.IfParaEqual: return PokeValue(Bpp(a0), a1) == a2 ? 1 : 0;
                case AiCmd.IfWazaHinshi: return WazaKills() ? 1 : 0;                                   // [P] check_current_waza_hinsi: CalcDamage >= KP des Gegners
                case AiCmd.IfDokudoku: return Toxic(Bpp(a0)) ? 1 : 0;                                  // [P] Gift mit Moudoku-Zaehler (SICKCONT.IsMoudokuCont)
                case AiCmd.IfnDokudoku: return Toxic(Bpp(a0)) ? 0 : 1;
                case AiCmd.IfBenchPpdec: return BenchPpDec(a0) ? 1 : 0;                                // [P] ein Ersatzpokemon mit angebrauchten AP
                case AiCmd.IfZidandaPowerup: return 0;                                                 // [N] Fussabdruck-Zustand nicht modelliert
                case AiCmd.IfnWazaHinshi: return WazaKills() ? 0 : 1;
                case AiCmd.IfHinshi: return Bpp(a0).Poke.Hp == 0 ? 1 : 0;                              // [P]
                case AiCmd.IfnHinshi: return Bpp(a0).Poke.Hp == 0 ? 0 : 1;
                case AiCmd.IfHaveWaza: return HaveWaza(a0, a1, false) ? 1 : 0;                         // [P] eigene: alle Attacken; Gegenueber: schon eingesetzte
                case AiCmd.IfnHaveWaza: return HaveWaza(a0, a1, false) ? 0 : 1;
                case AiCmd.IfHaveWazaSeqno: return HaveWaza(a0, a1, true) ? 1 : 0;                     // [P]
                case AiCmd.IfnHaveWazaSeqno: return HaveWaza(a0, a1, true) ? 0 : 1;
                case AiCmd.IfCommonrndUnder: return CommonRnd < (ulong)a0 ? 1 : 0;                    // [P] Feld +8 des statischen Zufallswerts
                case AiCmd.IfCommonrndOver: return CommonRnd > (ulong)a0 ? 1 : 0;                      // [A]
                case AiCmd.IfCommonrndEqual: return CommonRnd == (ulong)a0 ? 1 : 0;                    // [A]
                case AiCmd.IfnCommonrndEqual: return CommonRnd == (ulong)a0 ? 0 : 1;
                case AiCmd.CheckAgiRank: return AgiRank(Bpp(a0));                                      // [A] CalcAgilityOrder: 0 = zuerst
                case AiCmd.CheckMamoruCount: return Bpp(a0).ProtectCount;                              // [P] Feld; hier die Engine-Zaehlung [A]
                case AiCmd.CheckLastWazaKind: return Move(Defender.LastMove)?.DamageType ?? 0;         // [P] letzte Attacke des Verteidigers
                case AiCmd.CheckStatus: return PokeValue(Bpp(a0), a1);                                 // [P] BTL_POKEPARAM.GetValue
                case AiCmd.IfDmgPhysicUnder: return PhysicVsSpecial(a0) < 0 ? 1 : 0;                   // [P] StatusRank(Angriff) < StatusRank(Sp.-Angriff)
                case AiCmd.IfDmgPhysicOver: return PhysicVsSpecial(a0) > 0 ? 1 : 0;
                case AiCmd.IfDmgPhysicEqual: return PhysicVsSpecial(a0) == 0 ? 1 : 0;
                case AiCmd.CheckIryoku: return Move(MoveNo)?.Power ?? 0;                               // [A]
                case AiCmd.IfBenchDamageMax: return 0;                                                 // [N]
                case AiCmd.CheckSlowstartTurn: return 0;                                               // [N]
                case AiCmd.GetMezameType: return 0;                                                    // [N] Erwachen-Kraft
                case AiCmd.IfWazahide: return 0;                                                       // [N] Tauchen/Fliegen o. ae.
                case AiCmd.IfAlreadyMoraibi: return 0;                                                 // [N]
                case AiCmd.CompPowerWithPartner: return 0;                                             // [N] Doppelkampf
                case AiCmd.CheckSoubiItem: return Bpp(a0).Poke.Item;                                   // [P]
                case AiCmd.CheckSoubiEquip: return _e.Data.GetItem(Bpp(a0).Poke.Item)?.HoldEffect ?? 0;  // [A]
                case AiCmd.CheckPokeSex: return Bpp(a0).Poke.Sex;                                      // [P]
                case AiCmd.CheckNekodamasi: return 0;                                                  // [N]
                case AiCmd.CheckTakuwaeru: return Bpp(a0).Stockpile;                                   // [A]
                case AiCmd.CheckBtlRule: return 0;                                                     // [P] 0 = Einzel
                case AiCmd.CheckRecycleItem: return 0;                                                 // [N]
                case AiCmd.CheckWorkWazaType: return Move(MoveNo)?.Type ?? 0;                          // [A]
                case AiCmd.CheckWorkWazaSeqNo:
                case AiCmd.CheckWazaSeqNo: return Move(MoveNo)?.AiSeqNo ?? 0;                          // [P]
                case AiCmd.IfLevel: return a0 == 2 ? (Attacker.Level == Defender.Level ? 1 : 0) : a0 == 0 ? (Defender.Level < Attacker.Level ? 1 : 0) : (Attacker.Level < Defender.Level ? 1 : 0);  // [P]
                case AiCmd.IfMikataAttack: return 0;                                                   // [P] Einzelkampf
                case AiCmd.IfHaveItem: return Bpp(a0).Poke.Item == a1 ? 1 : 0;                         // [P]
                case AiCmd.FldEffCheck: return a0 == 0 ? (_e.Weather.Active ? 1 : 0) : a0 == 1 ? (_e.TrickRoomTurns > 0 ? 1 : 0) : 0;   // [A]
                case AiCmd.CheckSideEffCount: return SideEffCount(Bpp(a0), (int)a1);                   // [P]
                case AiCmd.IfBenchHpDec: return BenchHpDec(a0) ? 1 : 0;                                // [P]
                case AiCmd.IfTotteoki: return 0;                                                       // [N]
                case AiCmd.CheckWazaKind: return Move(MoveNo)?.DamageType ?? 0;                        // [P]
                case AiCmd.IfHaveBatsugun:                                                             // [P]
                    {
                        var atk = Bpp(a0);
                        var def = Bpp(a1);
                        for (int i = 0; i < BattleMon.MoveCount; i++)
                            if (atk.Moves[i] != 0 && Affinity(def, atk.Moves[i]) > 7 && Affinity(def, atk.Moves[i]) != AffinityId.Null) return 1;
                        return 0;
                    }
                case AiCmd.CheckStatusUp:                                                              // [P] Summe der positiven Stufen
                    {
                        var m = Bpp(a0);
                        int sum = 0;
                        for (int r = 1; r <= 7; r++) { int v = m.Poke.GetRank((PokeValueId)r); if (v > 6) sum += v - 6; }
                        return sum;
                    }
                case AiCmd.IfMigawari: return 0;                                                       // [N] Delegator nicht modelliert
                case AiCmd.CheckMonsNo: return Bpp(a0).Poke.MonsNo;                                    // [P]
                case AiCmd.IfMiraiyochi: return _e.Sides[Bpp(a0).Side].FutureTurns > 0 ? 1 : 0;        // [A]
                case AiCmd.IfAteKinomi: return Bpp(a0).ItemConsumed ? 1 : 0;                           // [A]
                case AiCmd.IfTypeEx: return Bpp(a0).Poke.TypeEx == a1 ? 1 : 0;                         // [P]
                case AiCmd.IfExistGround: return 0;                                                    // [N] Gelaendeeffekte fehlen
                case AiCmd.GetWeight: return Bpp(a0).Species.Weight;                                   // [A]
                case AiCmd.IfMulti: return 0;
                case AiCmd.IfMegaEvolved: return 0;                                                    // [P]
                case AiCmd.IfSenarioTrainer: return _e.IsWild ? 0 : 1;                                 // [A]
                case AiCmd.GetMaxWazaPower: return MaxPower(Bpp(a0), Defender);                        // [A]
                case AiCmd.CheckWazaNoEffectByTokusei: return 0;                                       // [N]
                case AiCmd.GetCurrentWazaNo: return MoveNo;                                            // [P]
                case AiCmd.GetCurrentItemNo: return ItemNo;                                            // [P]
                case AiCmd.GetWazaTarget: return Move(MoveNo)?.Target ?? 0;                            // [A]
                case AiCmd.IfG: case AiCmd.IfCanG: case AiCmd.IfGWazaUseTurn: return 0;                // [P] kein G-Modus in BDSP
                case AiCmd.IfHaveKinomi: return (_e.Data.GetItem(Bpp(a0).Poke.Item)?.Type ?? -1) == 3 ? 1 : 0;   // [A]
                default: return 0;
            }
        }

        static bool Toxic(BattleMon m) => m.PokeSick == Sick.Poison && SickCont.IsMoudokuCont(m.SickContents[Sick.Poison]);

        bool BenchPpDec(long a0)
        {
            var m = Bpp(a0);
            foreach (var p in _e.Parties[m.Side])
            {
                if (p == _e.Active(m.Side) || p.IsFainted) continue;
                for (int i = 0; i < BattleMon.MoveCount; i++) if (p.Moves[i] != 0 && p.Pp[i] != p.MaxPp[i]) return true;
            }
            return false;
        }

        // IF_WAZA_HINSHI: die aktuelle Attacke des Angreifers (CalcDamage, fester Zufallsfaktor) besiegt den Verteidiger.
        bool WazaKills() => Defender != null && Attacker != null && EstimateDamage(Attacker, Defender, MoveNo) >= Defender.Poke.Hp;

        // check_have_waza / check_have_waza_seqno: eigene Seite (AI-Seite 1/3) prueft alle Attacken, das Gegenueber nur schon eingesetzte (CheckWazaStored).
        bool HaveWaza(long aiSide, long value, bool bySeqNo)
        {
            var m = Bpp(aiSide);
            if (m == null || m.Poke.Hp == 0) return false;
            bool own = aiSide == 1 || aiSide == 3;
            _used.TryGetValue(m.PokeId, out var known);
            for (int i = 0; i < BattleMon.MoveCount; i++)
            {
                int no = m.Moves[i];
                if (no == 0 || (!own && (known == null || !known.Contains(no)))) continue;
                if (bySeqNo ? (Move(no)?.AiSeqNo ?? 0) == value : no == value) return true;
            }
            return false;
        }

        // CalcAgilityOrder: 0 = handelt zuerst (hoehere Initiative); bei Gleichstand 0 fuer das eigene Pokemon [A].
        long AgiRank(BattleMon m)
        {
            var other = m == Attacker ? Defender : Attacker;
            return Agility(m) >= Agility(other) ? 0 : 1;
        }

        // StatusRank(Angriff) gegen StatusRank(Sp.-Angriff) mit Stufenfaktor: < 0, 0, > 0.
        int PhysicVsSpecial(long aiSide)
        {
            var m = Bpp(aiSide);
            double a = m.Poke.Attack * RankFactor(m.Poke.GetRank(PokeValueId.ATTACK_RANK));
            double s = m.Poke.SpAttack * RankFactor(m.Poke.GetRank(PokeValueId.SP_ATTACK_RANK));
            return (int)a < (int)s ? -1 : (int)a > (int)s ? 1 : 0;
        }

        bool AnyDamageMove(BattleMon m)
        {
            for (int i = 0; i < BattleMon.MoveCount; i++) if (m.Moves[i] != 0 && (Move(m.Moves[i])?.Power ?? 0) != 0) return true;
            return false;
        }

        long PokeValue(BattleMon m, long id)
        {
            if (id >= 0 && id <= 20) return m.Poke.GetValue((PokeValueId)id);
            return 0;
        }

        long TypeOf(long sel)
        {
            switch (sel)
            {
                case 0: return Defender.Poke.Type1;
                case 1: return Attacker.Poke.Type1;
                case 2: return Defender.Poke.Type2;
                case 3: return Attacker.Poke.Type2;
                case 4: return Move(MoveNo)?.Type ?? 18;
                default: return 18;
            }
        }

        // COMP_POWER: 0 = kein Schaden, 1 = eine andere eigene Attacke macht mehr, 2 = diese ist die staerkste.
        long CompPower()
        {
            int cur = EstimateDamage(Attacker, Defender, MoveNo);
            if (cur == 0) return 0;
            for (int i = 0; i < BattleMon.MoveCount; i++)
            {
                if (i == MoveSlot || Attacker.Moves[i] == 0) continue;
                if (EstimateDamage(Attacker, Defender, Attacker.Moves[i]) > cur) return 1;
            }
            return 2;
        }

        long MaxPower(BattleMon atk, BattleMon def)
        {
            int best = 0;
            for (int i = 0; i < BattleMon.MoveCount; i++)
                if (atk.Moves[i] != 0) best = Math.Max(best, EstimateDamage(atk, def, atk.Moves[i]));
            return best;
        }

        bool BenchCond()
        {
            foreach (var p in _e.Parties[Attacker.Side]) if (p != _e.Active(Attacker.Side) && !p.IsFainted && p.PokeSick != 0) return true;
            return false;
        }

        bool BenchHpDec(long a0)
        {
            var m = Bpp(a0);
            foreach (var p in _e.Parties[m.Side])
                if (p != _e.Active(m.Side) && p.Poke.Hp != 0 && p.Poke.Hp < p.Poke.MaxHp) return true;
            return false;
        }
    }
}
