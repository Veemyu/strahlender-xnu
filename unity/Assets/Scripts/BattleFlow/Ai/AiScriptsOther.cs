using System;
using System.Collections.Generic;

namespace Xnu.Battle.Flow
{
    // BtlAiAllowance (AI-Bit 16): kleines Zusatzskript. Bei Schadensattacken gegen einen Gegner mit Nekodamasi (CHECK_NEKODAMASI) +1,
    // sonst -1, wenn dessen KP niedrig sind und der Zufallswurf (220/256 bzw. 150/256) trifft.
    public sealed class AiScriptAllowance : AiScriptBase
    {
        public override IEnumerable<string> Functions => new[] { "main_proc" };

        public override long Run(string function)
        {
            if (Call(AiCmd.CheckDamageWaza, A(1, CurrentWaza())) == 0) return 0;
            if (Call(AiCmd.CheckNekodamasi, A(1, 1)) == 0)
            {
                Score += 1;
                return 0;
            }
            long[] roll;
            if (Call(AiCmd.IfHpUnder, A(2, 0, 0x14)) != 0) roll = A(1, 0xdc);
            else
            {
                if (Call(AiCmd.IfHpUnder, A(2, 0, 0x28)) == 0) return 0;
                roll = A(1, 0x96);
            }
            if (Call(AiCmd.IfRndUnder, roll) == 0) return 0;
            Score -= 1;
            return 0;
        }
    }

    // BtlAiStrong (AI-Bit 2): "starke" Zusatzwertung fuer Attacken, die im Einzelkampf wirken: Wirkungslos-Pruefungen (Strong_exception),
    // Resistenzbeeren des Gegners (Strong_KinomiCheck), Zuschlaege je nach KI-Nummer (Zufallswuerfe 0x80/0xe6) und sehr effektive Attacken.
    // Umgesetzt ist der Einzelkampf ohne G-Modus (CHECK_BTL_RULE = 0, IF_GWAZA_USE_TURN = 0); die Doppelkampf- und G-Zweige von main_proc
    // fehlen (der Orakel-Test legt die Welt auf diese beiden Antworten fest).
    public sealed class AiScriptStrong : AiScriptBase
    {
        static readonly string[] Names = { "main_proc", "Strong_exception", "Strong_KinomiCheck" };

        public override IEnumerable<string> Functions => Names;

        public override long Run(string function)
        {
            switch (function)
            {
                case "main_proc": MainProc(); return 0;
                case "Strong_exception": return Exception() ? 1 : 0;
                case "Strong_KinomiCheck": return KinomiCheck() ? 1 : 0;
            }
            return 0;
        }

        bool Rnd(long n) => Call(AiCmd.IfRndUnder, A(1, n)) != 0;

        long Abil(long side) => Call(AiCmd.CheckTokusei, A(1, side));

        static bool IgnoresAbility(long ability) => InMask(ability, 0x68, 0x3d, 0x1800000000000001UL);

        void MainProc()
        {
            long seq = Call(AiCmd.CheckWorkWazaSeqNo, Empty);
            long rule = Call(AiCmd.CheckBtlRule, Empty);
            if (rule == 1 && Call(AiCmd.IfMikataAttack, Empty) != 0) return;
            if (Call(AiCmd.IfGWazaUseTurn, Empty) != 0) return;       // G-Zweig nicht umgesetzt
            if (Call(AiCmd.IfWazaHinshi, A(1, 0)) != 0 && Call(AiCmd.IfMigawari, A(1, 0)) == 0)
            {
                if (rule == 1) return;                                 // Doppelkampf-Zweig nicht umgesetzt
                SinglesBonus(seq);
            }
            if (!Exception() && !KinomiCheck())
            {
                if (Call(AiCmd.CompPower, A(1, 0)) == 1) Score -= 1;
            }
            if (Call(AiCmd.CheckWazaAisyou, A(4, 1, 0, CurrentWaza(), 9)) == 0) return;
            if (!Rnd(0xb4)) return;
            Score += 2;
        }

        // Einzelkampf-Zweig: Zuschlaege nach der KI-Nummer der Attacke (Zufallswurf 0x80 bzw. 0xe6).
        void SinglesBonus(long seq)
        {
            bool hit;
            if (seq < 0xaa) hit = (seq != 7 && seq != 0x94) ? Rnd(0xe6) : Rnd(0x80);
            else hit = (seq == 0xf8 || seq == 0xaa) ? Rnd(0x80) : Rnd(0xe6);
            if (hit) Score += 3;
            if (seq == 0x168 || seq == 0x67)
            {
                if (Rnd(0xe6)) Score += 5;
                return;
            }
            if (seq == 0x155 && Rnd(0xe6)) Score += 4;
        }

        // Wirkt die Attacke vermutlich nicht (Faehigkeit des Gegners unklar), obwohl sie Schaden macht? true = ja.
        bool Exception()
        {
            long type = Call(AiCmd.CheckType, A(1, 4));
            long mons = Call(AiCmd.CheckMonsNo, A(1, 0));
            long a = Abil(0), b = Abil(0), c = Abil(0), d = Abil(0);
            if (Call(AiCmd.CheckDamageWaza, A(1, CurrentWaza())) == 0) return false;
            if (a == b && b == c && c == d) return false;
            if (type == 4) return mons == 0x1b5;
            if (type != 0xe && type != 9) return false;
            if (mons < 0x128)
            {
                if (InMask(mons, 0xb7, 0x3b, 0x400006000000003UL) || InMask(mons, 0x56, 0x3a, 0x200000000000003UL)) return true;
            }
            else if (InMask(mons, 0x145, 0x29, 0x1c000000003UL) || InMask(mons, 0x1b0, 0x2a, 0x20000004001UL) || unchecked((ulong)(mons - 0x128)) < 3) return true;
            return type == 9 && mons == 0x1b5;
        }

        static readonly int[] BerryByType =
        {
            200, 0xbd, 0xc0, 0xbe, 0, 0xc3, 0xc2, 0xc4, 199, 0xb8, 0xb9, 0xbb, 0xba, 0xc1, 0xbc, 0xc5, 0xc6, 0x2ae,
        };

        // Haelt der Gegner die Resistenzbeere gegen den Typ der Attacke? true = ja (bei Boden zaehlt eine Wertung -3).
        bool KinomiCheck()
        {
            long type = Call(AiCmd.CheckType, A(1, 4));
            if (type < 0 || type >= BerryByType.Length) return false;
            if (type != 4) return Call(AiCmd.IfHaveItem, A(2, 0, BerryByType[type])) != 0;
            if (Call(AiCmd.IfHaveItem, A(2, 0, 0xbf)) != 0) return true;
            if (Call(AiCmd.FldEffCheck, A(1, 2)) != 0) return false;
            if (IgnoresAbility(Abil(1))) return false;
            if (Abil(0) != 0x1a)
            {
                if (Call(AiCmd.CheckType, A(1, 0)) != 2 && Call(AiCmd.CheckType, A(1, 2)) != 2) return false;
            }
            Score -= 3;
            return true;
        }
    }

    // BtlAiItem (AI-Bit 32): Wertung der Item-Verwendung nach Item-Nummer (GET_CURRENT_ITEMNO). Heiltraenke 17/24/25/26 -> itemAI_001,
    // Top-Genesung 23 -> itemAI_023, Vollheilung 27 -> itemAI_027, X-Items 57/58/61/62 -> itemAI_057, 59 -> itemAI_059.
    // Die Wertungen sind Zusatzpunkte zur Item-Grundwertung 100 (AiItemJudge).
    public sealed class AiScriptItem : AiScriptBase
    {
        static readonly string[] Names = { "main", "itemAI_001", "itemAI_023", "itemAI_027", "itemAI_057", "itemAI_059" };

        public override IEnumerable<string> Functions => Names;

        public override long Run(string function)
        {
            switch (function)
            {
                case "main": Main(); break;
                case "itemAI_001": Potion(); break;
                case "itemAI_023": FullRestore(); break;
                case "itemAI_027": FullHeal(); break;
                case "itemAI_057": case "itemAI_059": StatItem(); break;
            }
            return 0;
        }

        void Main()
        {
            long item = Call(AiCmd.GetCurrentItemNo, Empty) & 0xffff;
            switch (item)
            {
                case 0x11: case 0x18: case 0x19: case 0x1a: Potion(); break;
                case 0x17: FullRestore(); break;
                case 0x1b: FullHeal(); break;
                case 0x39: case 0x3a: case 0x3d: case 0x3e: case 0x3b: StatItem(); break;
            }
        }

        bool Rnd(long n) => Call(AiCmd.IfRndUnder, A(1, n)) != 0;

        bool HpUnder(long pct) => Call(AiCmd.IfHpUnder, A(2, 1, pct)) != 0;

        bool HasBench() => Call(AiCmd.CheckBenchCount, A(1, 1)) != 0;

        // Hauptzustaende (2, 3, 5, 1, 4), Verwirrung (6) und IF_DOKUDOKU: irgendein Zustand beim eigenen Pokemon.
        bool AnySick()
        {
            foreach (long sick in new long[] { 2, 3, 5, 1, 4, 6 })
                if (Call(AiCmd.IfWazaSick, A(2, 1, sick)) != 0) return true;
            return Call(12, A(1, 1)) != 0;
        }

        // Trank: unter 20 % KP +10 (bzw. +2), unter 40 % je nach Zufall, sonst -20.
        void Potion()
        {
            if (!HpUnder(0x14))
            {
                Under40Potion();
                return;
            }
            if (HasBench())
            {
                if (!Rnd(0x80))
                {
                    if (Rnd(0xaa)) { Score += 2; return; }
                    Under40Potion();
                    return;
                }
            }
            Score += 10;
        }

        void Under40Potion()
        {
            if (HpUnder(0x28))
            {
                if (!HasBench() && Rnd(0x80)) { Score += 10; return; }
                if (Rnd(0x46)) { Score += 10; return; }
                if (Rnd(0x46)) { Score += 1; return; }
            }
            Score -= 20;
        }

        void FullRestore()
        {
            if (!HpUnder(0x14))
            {
                Under40Full();
                return;
            }
            if (HasBench())
            {
                if (AnySick() && Rnd(0xf0)) { Score += 10; return; }
                if (!Rnd(0x80))
                {
                    if (Rnd(0xaa)) { Score += 2; return; }
                    Under40Full();
                    return;
                }
            }
            Score += 10;
        }

        void Under40Full()
        {
            if (HpUnder(0x28))
            {
                if (!HasBench() && Rnd(0x80)) { Score += 10; return; }
                if (AnySick() && Rnd(200)) { Score += 10; return; }
                if (Rnd(100)) { Score += 10; return; }
                if (Rnd(100)) { Score += 1; return; }
            }
            Score -= 20;
        }

        void FullHeal()
        {
            if (AnySick())
            {
                if (HasBench())
                {
                    if (!Rnd(0x96))
                    {
                        Score += Rnd(0x96) ? 2 : -20;
                        return;
                    }
                }
                Score += 10;
                return;
            }
            Score -= 20;
        }

        void StatItem() => Score += Rnd(200) ? 2 : -20;
    }

    // BtlAiPokeChange (AI-Bit 64): Wertung eines Ersatzpokemons (AI-Seite 4) gegen das aktive Gegenueber. Gruende fuer einen Wechsel:
    // Abgesang laeuft aus, Wunderwache beim Gegner, Gegner ohne Wirkung, Wahlitem mit schlechter Typenlage, Natura-Kur, bessere Typenlage.
    // Ergebnis: Score = Grundwertung + 1 oder + 20 und PokeChangeEnable = 1; ohne Grund bleibt die Wechselfreigabe aus.
    public sealed class AiScriptPokeChange : AiScriptBase
    {
        static readonly string[] Names =
        {
            "main", "IsHorobinoutaLastTurn", "CanHusiginamamoriBreak", "CalcBaseScore", "CanAisyou0BaiBreak", "CanKodawariBadAisyouBreak",
            "CanNoEffectPrevDamageByTokusei", "CanRepairSickBySizenkaihuku", "CanAisyouMakeBetter",
        };

        public override IEnumerable<string> Functions => Names;

        public override long Run(string function)
        {
            switch (function)
            {
                case "main": Main(); return 0;
                case "IsHorobinoutaLastTurn": return IsHorobinoutaLastTurn() ? 1 : 0;
                case "CanHusiginamamoriBreak": return CanHusiginamamoriBreak() ? 1 : 0;
                case "CalcBaseScore": return CalcBaseScore();
                case "CanAisyou0BaiBreak": return CanAisyou0BaiBreak() ? 1 : 0;
                case "CanKodawariBadAisyouBreak": return CanKodawariBadAisyouBreak() ? 1 : 0;
                case "CanNoEffectPrevDamageByTokusei": return CanNoEffectPrevDamageByTokusei() ? 1 : 0;
                case "CanRepairSickBySizenkaihuku": return CanRepairSickBySizenkaihuku() ? 1 : 0;
                case "CanAisyouMakeBetter": return CanAisyouMakeBetter() ? 1 : 0;
            }
            return 0;
        }

        bool Rnd(long n) => Call(AiCmd.IfRndUnder, A(1, n)) != 0;

        long Abil(long side) => Call(AiCmd.CheckTokusei, A(1, side));

        void Main()
        {
            int add;
            if (IsHorobinoutaLastTurn() || CanHusiginamamoriBreak() || CanAisyou0BaiBreak())
            {
                add = Finish(220);
            }
            else if (CanKodawariBadAisyouBreak())
            {
                add = CalcBaseScore() + 0x14;
                Score += add;
                PokeChangeEnable = 1;
                return;
            }
            else if (CanNoEffectPrevDamageByTokusei()) add = Finish(220);
            else if (CanRepairSickBySizenkaihuku() || CanAisyouMakeBetter()) add = Finish(180);
            else return;
            Score += add;
            PokeChangeEnable = 1;
        }

        // Zufallswurf, dann Grundwertung: +1 bei Misserfolg, +20 bei Erfolg.
        int Finish(long roll)
        {
            bool hit = Rnd(roll);
            return CalcBaseScore() + (hit ? 0x14 : 1);
        }

        // -30, wenn das Ersatzpokemon nicht gefahrlos wechseln darf (Szenario-Trainer); dazu Staffel nach der staerksten Attacke des Ersatzes.
        int CalcBaseScore()
        {
            int baseScore;
            if (Call(AiCmd.IfSenarioTrainer, Empty) == 0) baseScore = 0;
            else
            {
                Call(AiCmd.CheckMonsNo, A(1, 4));
                if (Call(AiCmd.IfCanG, A(1, 4)) == 0 && Call(129, A(1, 4)) != 0) baseScore = 0;
                else baseScore = -30;
            }
            long power = Call(AiCmd.GetMaxWazaPower, A(1, 4));
            if (power > 0xef) return baseScore | 4;
            if (power < 200) return power < 0xa0 ? baseScore : baseScore + 2;
            return baseScore + 3;
        }

        bool IsHorobinoutaLastTurn()
        {
            if (Call(AiCmd.IfnWazaSick, A(2, 1, 0x14)) != 0) return false;
            long max = Call(18, A(1, 1));
            long now = Call(19, A(1, 1));
            return now + 1 == max;
        }

        bool CanHusiginamamoriBreak()
        {
            foreach (long side in new long[] { 0, 2 })
            {
                if (Abil(side) != 0x19) continue;
                if (Call(AiCmd.IfHaveBatsugun, A(2, 1, side)) != 0) continue;
                if (Call(122, A(2, 4, side)) != 1) continue;
                if (Rnd(200)) return true;
            }
            return false;
        }

        bool IsAisyou0Bai(long a, long b, long waza)
        {
            if (Call(AiCmd.CheckWazaAisyou, A(4, a, b, waza & 0xffff)) != 0) return true;
            return Call(AiCmd.CheckWazaNoEffectByTokusei, A(2, b, waza & 0xffff)) != 0;
        }

        bool CanAisyou0BaiBreak()
        {
            if (Call(AiCmd.IfHaveWazaAisyouOver, A(3, 1)) != 0) return false;
            if (Call(AiCmd.IfHaveWazaAisyouOver, A(3, 1, 2)) != 0) return false;
            if (Call(22, Empty) != 0) return false;
            if (Call(AiCmd.IfHaveWazaAisyouOver, A(3, 4, 0, 7)) == 0 && Call(AiCmd.IfHaveWazaAisyouOver, A(3, 4, 2, 7)) == 0)
            {
                if (Call(37, A(3, 4, 0, 7)) == 0 && Call(37, A(3, 4, 2, 7)) == 0) return false;
                return Rnd(0x80);
            }
            return Rnd(200);
        }

        bool CanKodawariBadAisyouBreak()
        {
            long waza = Call(AiCmd.GetKodawariWaza, A(1, 1));
            if ((int)waza == 0) return false;
            long roll;
            if (Call(AiCmd.CheckDamageWaza, A(1, waza & 0xffff)) == 0) roll = 0xaa;
            else
            {
                if (!IsAisyou0Bai(1, 0, waza)) return false;
                if (!IsAisyou0Bai(1, 2, waza)) return false;
                if (Call(AiCmd.IfHaveWazaAisyouOver, A(3, 4, 0, 7)) != 0 || Call(AiCmd.IfHaveWazaAisyouOver, A(3, 4, 2, 7)) != 0) roll = 0xaa;
                else if (Call(37, A(3, 4, 0, 7)) != 0 || Call(37, A(3, 4, 2, 7)) != 0) roll = 0x80;
                else roll = 0;
            }
            return Rnd(roll);
        }

        bool CanNoEffectPrevDamageByTokusei()
        {
            if (Call(AiCmd.IfSenarioTrainer, Empty) != 0 && Call(AiCmd.IfCanG, A(1, 4)) != 0) return false;
            bool hit = Call(AiCmd.IfHaveBatsugun, A(2, 1)) != 0 || Call(AiCmd.IfHaveBatsugun, A(2, 1, 2)) != 0;
            if (hit && Rnd(0x55)) return false;
            long last = Call(AiCmd.CheckLastWaza, A(1, 0));
            if (Call(AiCmd.CheckWazaNoEffectByTokusei, A(2, 4, last)) == 0) return false;
            return Rnd(0x80);
        }

        bool CanRepairSickBySizenkaihuku()
        {
            if (Call(AiCmd.IfSenarioTrainer, Empty) != 0 && Call(AiCmd.IfCanG, A(1, 4)) != 0) return false;
            if (Abil(1) != 0x1e) return false;
            if (Call(AiCmd.IfnWazaSick, A(2, 1, 2)) != 0 && Call(AiCmd.IfnWazaSick, A(2, 1, 3)) != 0) return false;
            if (Call(AiCmd.IfHpUnder, A(2, 1, 0x32)) != 0) return false;
            long last = Call(AiCmd.CheckLastWaza, A(1, 0));
            if (last == 0) return Rnd(0x80);
            return Call(35, A(3, 0, 4, last)) < 7;
        }

        bool CanAisyouMakeBetter()
        {
            if (Call(AiCmd.IfHaveBatsugun, A(2, 1)) != 0 && Rnd(0xe6)) return false;
            if (Call(AiCmd.CheckStatusUp, A(1, 1)) > 3) return false;
            if (Call(AiCmd.IfSenarioTrainer, Empty) != 0 && Call(AiCmd.IfCanG, A(1, 4)) != 0) return false;
            if (Call(122, A(2, 4)) == 0) return false;
            long last = Call(116, A(1, 1));
            if (last == 0) return false;
            long aff = Call(35, A(3, 0, 4, last));
            if (aff == 0) return Rnd(0x80);
            if (aff > 6) return false;
            return Rnd(0x55);
        }
    }

    // AiPokeChangeJudge (Einzelkampf): jedes einsatzbereite Ersatzpokemon startet mit 100, das Wechsel-Skript addiert; gewaehlt wird unter den
    // freigegebenen (PokeChangeEnable) das mit der hoechsten Wertung, bei Gleichstand zufaellig. Kein freigegebenes Pokemon: kein Wechsel.
    public sealed class AiPokeChangeJudge
    {
        readonly BattleEngine _engine;
        readonly AiWorld _world;

        public AiPokeChangeJudge(BattleEngine engine, AiWorld world)
        {
            _engine = engine;
            _world = world;
        }

        public int? Judge(BattleMon mon, AiScriptPokeChange script, TrainerAi ai, out int index)
        {
            index = -1;
            if (script == null) return null;
            var party = _engine.Parties[mon.Side];
            var best = new List<int>();
            int bestScore = 0;
            for (int i = 0; i < party.Count; i++)
            {
                if (party[i] == mon || party[i].IsFainted) continue;
                _world.Bench = party[i];
                int score = TrainerAi.StartScore + ai.RunScript(6, mon, -1, 0, 0);
                if (!ai.LastEnable) continue;
                if (best.Count == 0 || score > bestScore) { bestScore = score; best.Clear(); best.Add(i); }
                else if (score == bestScore) best.Add(i);
            }
            _world.Bench = null;
            if (best.Count == 0) return null;
            index = best.Count == 1 ? best[0] : best[(int)_world.Rng.GetValue((ulong)best.Count)];
            return bestScore;
        }
    }
}
