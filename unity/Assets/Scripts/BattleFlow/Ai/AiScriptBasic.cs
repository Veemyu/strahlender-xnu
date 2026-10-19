using System;
using System.Collections.Generic;

namespace Xnu.Battle.Flow
{
    // BtlAiBasic (AI-Bit 1): Grundskript. Jede Attacke bekommt Abzuege fuer Fehlschlag-Gruende (Typ-/Faehigkeitsimmunitaet,
    // verschenkte Statuswirkung usw.). Der Aufbau folgt dem Original: main_proc -> fuenf Sonderpruefungen -> Calc_BasicDamage -> Calc_BasicAll
    // (Verteiler nach der KI-Nummer der Attacke, WAZADATA.AISeqNo). Nur ein Teil der BaciAI_Seq_*-Funktionen ist umgesetzt (siehe ImplementedSeq);
    // alle umgesetzten Funktionen sind gegen die echten ARM64-Funktionen geprueft (BattleAiScriptOracleTests).
    public sealed class AiScriptBasic : AiScriptBase
    {
        // Funktion -> Eintritt; alles, was das Orakel pruefen kann.
        readonly Dictionary<string, Func<long>> _entries;

        // KI-Nummer der Attacke -> Funktionsnummer (BaciAI_Seq_NNN), vom Orakel aus Calc_BasicAll gemessen (BattleAiDispatch.json).
        public static readonly Dictionary<int, int> SeqDispatch = new Dictionary<int, int>
        {
                [1] = 1, [7] = 7, [8] = 8, [10] = 10, [11] = 11, [12] = 12, [13] = 13, [14] = 14, [15] = 15, [16] = 16, [18] = 18, [19] = 19,
                [20] = 20, [21] = 21, [22] = 22, [23] = 23, [24] = 24, [25] = 25, [28] = 28, [32] = 32, [33] = 33, [35] = 35, [37] = 37, [38] = 38,
                [46] = 46, [47] = 47, [49] = 49, [50] = 10, [51] = 11, [52] = 12, [53] = 13, [54] = 14, [55] = 15, [56] = 16, [58] = 18, [59] = 19,
                [60] = 20, [61] = 21, [62] = 22, [63] = 23, [64] = 24, [65] = 65, [66] = 33, [67] = 67, [79] = 79, [84] = 84, [86] = 86, [90] = 90,
                [92] = 92, [94] = 94, [97] = 92, [102] = 102, [106] = 106, [107] = 107, [108] = 16, [109] = 109, [112] = 112, [113] = 113,
                [114] = 114, [115] = 115, [118] = 49, [120] = 120, [124] = 124, [127] = 127, [132] = 132, [133] = 132, [134] = 132, [136] = 136,
                [137] = 137, [142] = 142, [143] = 25, [148] = 148, [156] = 11, [157] = 132, [158] = 158, [160] = 160, [161] = 161, [162] = 161,
                [164] = 164, [165] = 165, [166] = 49, [167] = 167, [168] = 168, [172] = 172, [175] = 175, [176] = 176, [177] = 177, [178] = 178,
                [179] = 179, [181] = 181, [184] = 184, [187] = 1, [188] = 188, [191] = 191, [192] = 192, [193] = 193, [199] = 49, [205] = 205,
                [206] = 206, [208] = 208, [211] = 211, [212] = 212, [215] = 215, [216] = 216, [220] = 220, [222] = 222, [225] = 225, [227] = 227,
                [232] = 232, [233] = 233, [234] = 234, [236] = 236, [238] = 238, [239] = 239, [241] = 241, [242] = 242, [243] = 243, [244] = 244,
                [246] = 246, [247] = 247, [249] = 249, [251] = 251, [252] = 252, [258] = 258, [265] = 265, [266] = 266, [270] = 270, [277] = 10,
                [278] = 278, [281] = 281, [284] = 12, [285] = 285, [286] = 286, [290] = 13, [292] = 292, [294] = 294, [298] = 298, [299] = 299,
                [300] = 300, [307] = 307, [308] = 10, [309] = 309, [311] = 311, [312] = 10, [315] = 315, [316] = 10, [318] = 318, [320] = 320,
                [321] = 13, [322] = 10, [323] = 323, [327] = 10, [328] = 11, [338] = 338, [339] = 339, [340] = 340, [342] = 342, [343] = 18,
                [346] = 18, [349] = 349, [350] = 350, [351] = 351, [352] = 352, [354] = 354, [356] = 18, [357] = 21, [362] = 362, [363] = 363,
                [364] = 18, [365] = 13, [366] = 366, [368] = 368, [370] = 370, [375] = 375, [376] = 158, [381] = 32, [382] = 158, [386] = 309,
                [387] = 387, [388] = 388, [389] = 389, [391] = 391, [394] = 394, [397] = 397, [399] = 399, [406] = 406, [411] = 18, [419] = 419,
                [420] = 423, [425] = 425, [426] = 426, [428] = 428, [429] = 429, [431] = 431, [432] = 432, [434] = 434,
        };

        // Funktionen, die als Seq-Rumpf umgesetzt sind.
        public static readonly HashSet<int> ImplementedSeq = new HashSet<int> { 1, 7, 10, 11, 12, 13, 16, 18, 19, 20, 28, 32, 33, 35, 37, 47, 49, 65, 84, 92, 106, 109, 115, 132, 136, 148, 158, 160, 188, 211, 212, 225, 251 };

        readonly Dictionary<int, Action> _seq;

        public AiScriptBasic()
        {
            _seq = new Dictionary<int, Action>
            {
                [1] = Seq001, [7] = Seq007, [10] = Seq010, [11] = Seq011, [12] = Seq012, [13] = Seq013, [16] = Seq016, [18] = Seq018, [19] = Seq019, [20] = Seq020,
                [28] = Seq028, [32] = Seq032, [33] = Seq033, [35] = Seq035, [37] = Seq037, [47] = Seq047, [49] = Seq049, [65] = Seq065, [84] = Seq084,
                [92] = Seq092, [106] = Seq106, [109] = Seq109, [115] = Seq115,
                [132] = Seq132, [136] = Seq136, [148] = Seq148, [158] = Seq158, [160] = Seq160, [188] = Seq188, [211] = Seq211, [212] = Seq212, [225] = Seq225,
                [251] = Seq251,
            };
            _entries = new Dictionary<string, Func<long>>
            {
                ["main_proc"] = () => { MainProc(); return 0; },
                ["Basic_ConaHoushi"] = () => ConaHoushi() ? 1 : 0,
                ["Basic_Itazuragokoro"] = () => Itazuragokoro() ? 1 : 0,
                ["Basic_Sensei"] = () => Sensei() ? 1 : 0,
                ["Basic_Hayatenotubasa"] = () => Hayatenotubasa() ? 1 : 0,
                ["Basic_DaimaxNG"] = () => DaimaxNg() ? 1 : 0,
                ["Calc_BasicDamage"] = () => CalcBasicDamage() ? 1 : 0,
                ["BasicDmg_00_1"] = () => TypePenalty(0xc) ? 1 : 0,
                ["BasicDmg_00_2"] = () => TypePenalty(10) ? 1 : 0,
                ["BasicDmg_00_3"] = () => TypePenalty(9) ? 1 : 0,
                ["BasicDmg_00_4"] = () => BasicDmg4() ? 1 : 0,
                ["BasicDmg_00_5"] = () => BasicDmg5() ? 1 : 0,
                ["BasicDmg_00_7"] = () => TypePenalty(0xb) ? 1 : 0,
                ["Bouon_Check"] = () => BouonCheck() ? 1 : 0,
                ["Boudan_Check"] = () => BoudanCheck() ? 1 : 0,
            };
            foreach (var kv in _seq)
            {
                var body = kv.Value;
                _entries["BaciAI_Seq_" + kv.Key.ToString("000")] = () => { body(); return 0; };
            }
        }

        public override IEnumerable<string> Functions => _entries.Keys;

        public override long Run(string function) => _entries[function]();

        // Faehigkeiten, die Schutz vor Abwehr-Faehigkeiten haben (Mold Breaker, Teravolt, Turboblaze): Bits 0, 59, 60 ab 0x68.
        static bool IgnoresAbility(long ability) => InMask(ability, 0x68, 0x3d, 0x1800000000000001UL);

        long Abil(long side) => Call(AiCmd.CheckTokusei, A(1, side));

        long Type(long sel) => Call(AiCmd.CheckType, A(1, sel));

        // ------------------------------------------------------------------------------------------------------

        void MainProc()
        {
            if (Call(AiCmd.CheckBtlRule, Empty) == 1 && Call(AiCmd.IfMikataAttack, Empty) != 0) return;
            if (ConaHoushi() || Itazuragokoro() || Sensei() || Hayatenotubasa() || DaimaxNg()) return;
            long waza = CurrentWaza();
            if (waza != 0x20 && waza != 0x5a)
            {
                if (Call(AiCmd.CheckDamageWaza, A(1, CurrentWaza())) == 0)
                {
                    CalcBasicAll();
                    return;
                }
            }
            if (CalcBasicDamage()) CalcBasicAll();
        }

        // Pulver-Attacken gegen Pflanzen-Typen und Hitzeschutz-Ueberzug.
        bool ConaHoushi()
        {
            long waza = CurrentWaza();
            if (waza < 0x93)
            {
                if (unchecked((uint)(waza - 0x4d)) > 2) return false;
            }
            else if (waza != 0x93 && waza != 600 && waza != 0x1dc) return false;
            long def = Abil(0);
            if (def == 0x8e)
            {
                long atk = Abil(1);
                if (!IgnoresAbility(atk))
                {
                    Score -= 10;
                    return true;
                }
            }
            if (Type(0) != 0xb && Type(2) != 0xb) return false;
            Score -= 10;
            return true;
        }

        // Gemeinsamer Schluss von Itazuragokoro/Sensei/Hayatenotubasa: Wirkung gegen Unlicht-Typ, Bodenlage, Faehigkeiten.
        bool PriorityBlockTail(long defAbility)
        {
            if (Type(0) != 0x10)
            {
                if (Type(2) != 0x10)
                {
                    if (Call(AiCmd.IfExistGround, A(1, 4)) != 0)
                    {
                        if (Type(0) != 2 && Type(2) != 2 && defAbility != 0x1a) goto penalty;
                    }
                    if (defAbility != 0xdb && defAbility != 0xd6) return false;
                }
            }
        penalty:
            Score -= 10;
            return true;
        }

        // Gemeinsamer Teil von Itazuragokoro/Hayatenotubasa fuer die Ziel-Pruefung der Attacke (Ziel-Art 0, 3, 4, 5, 8, 9).
        bool TargetsOpponent()
        {
            long t = Call(AiCmd.GetWazaTarget, Empty);
            return t <= 9 && ((0x339UL >> (int)t) & 1) != 0;
        }

        // Prankster (158): Statusattacken gegen Unlicht-Typen.
        bool Itazuragokoro()
        {
            long atk = Abil(1);
            long def = Abil(0);
            long kind = Call(AiCmd.CheckWazaKind, Empty);
            if (atk != 0x9e) return false;
            if (unchecked((ulong)(kind - 1)) < 2) return false;
            if (!TargetsOpponent()) return false;
            return PriorityBlockTail(def);
        }

        // Vorrang-Attacken (KI-Nummern 0x67, 0x9e, 0xdf, 0xf8, 0x168+...) gegen Unlicht/Boden-Lage.
        bool Sensei()
        {
            long def = Abil(0);
            long seq = Call(AiCmd.CheckWorkWazaSeqNo, Empty);
            if (seq < 0xf8)
            {
                if (seq != 0x67 && seq != 0x9e && seq != 0xdf) return false;
            }
            else if (!InMask(seq, 0x168, 0x1d, 0x10420011UL) && seq != 0xf8) return false;
            if (Call(AiCmd.IfExistGround, A(1, 4)) != 0)
            {
                if (Type(0) != 2 && Type(2) != 2 && def != 0x1a) goto penalty;
            }
            if (def != 0xdb && def != 0xd6) return false;
        penalty:
            Score -= 10;
            return true;
        }

        // Gale Wings (177) bei vollen KP: Flug-Attacke.
        bool Hayatenotubasa()
        {
            long atk = Abil(1);
            long def = Abil(0);
            if (atk != 0xb1) return false;
            if (Call(AiCmd.IfHpEqual, A(2, 1, 100)) == 0) return false;
            if (Call(AiCmd.CheckWorkWazaType, Empty) != 2) return false;
            if (!TargetsOpponent()) return false;
            if (Call(AiCmd.IfExistGround, A(1, 4)) != 0)
            {
                if (Type(0) != 2 && Type(2) != 2 && def != 0x1a) goto penalty;
            }
            if (def != 0xdb && def != 0xd6) return false;
        penalty:
            Score -= 10;
            return true;
        }

        // G-Attacken: im Basisspiel nie aktiv (IF_G liefert 0).
        bool DaimaxNg()
        {
            if (Call(AiCmd.IfG, A(1, 0)) == 0) return false;
            long w = CurrentWaza();
            bool hit;
            if (w < 0xe3)
                hit = InMask(w, 0xc, 0x38, 0x80004400100041UL) || InMask(w, 0x5a, 0x1e, 0x20001001UL);
            else if (w < 0x1bf)
                hit = InMask(w, 0xe3, 0x3f, 0x6c00000100000001UL) || w == 0x149;
            else
                hit = InMask(w, 0x1e4, 0x34, 0x8000000840001UL) || w == 0x2b1 || w == 0x1bf;
            if (!hit) return false;
            Score -= 10;
            return true;
        }

        // Typenimmunitaet / Abwehrfaehigkeit der Attacke: true = Wertung unveraendert fortfahren.
        bool CalcBasicDamage()
        {
            long atk = Abil(1);
            long def = Abil(0);
            long waza = CurrentWaza();
            if (Call(AiCmd.CheckWazaAisyou, A(4, 1, 0, waza, 0)) != 0)
            {
                long type = Type(4);
                if (def == 0x1a && type == 4 && IgnoresAbility(atk)) return true;
                long seq = Call(AiCmd.CheckWorkWazaSeqNo, Empty);
                if (seq != 0x87 && seq != 0xad && seq != 0xde)
                {
                    Score -= 10;
                    return false;
                }
                return true;
            }
            if (IgnoresAbility(atk)) return true;
            bool adjusted = false;
            if (def < 0x1b)
            {
                if (def < 0xc)
                {
                    if (def == 10) adjusted = TypePenalty(0xc);
                    else if (def == 0xb) adjusted = TypePenalty(10);
                }
                else if (def == 0x12) adjusted = TypePenalty(9);
                else if (def == 0x19) adjusted = BasicDmg4();
                else if (def == 0x1a) adjusted = BasicDmg5();
            }
            else if (def < 0x4f)
            {
                if (def == 0x1f || def == 0x4e) adjusted = TypePenalty(0xc);
            }
            else
            {
                if (def == 0x57 || def == 0x72) adjusted = TypePenalty(10);
                else if (def == 0x9d) adjusted = TypePenalty(0xb);
            }
            return !adjusted;
        }

        // BasicDmg_00_1/2/3/7: Typ der Attacke gleich `type` -> -12 (Absorb-Faehigkeiten).
        bool TypePenalty(long type)
        {
            if (Type(4) != type) return false;
            Score -= 0xc;
            return true;
        }

        // Wunderwache (25): nur Attacken, die nicht sehr effektiv sind, bekommen Abzug.
        bool BasicDmg4()
        {
            long waza = CurrentWaza();
            if (Call(AiCmd.CheckWazaAisyou, A(4, 1, 0, waza, 8)) != 0) return false;
            waza = CurrentWaza();
            if (Call(AiCmd.CheckWazaAisyou, A(4, 1, 0, waza, 9)) != 0) return false;
            Score -= 10;
            return true;
        }

        // Schwebe (26): Boden-Attacken, solange kein Schwerkraft-Feld (Feldeffekt 2) aktiv ist.
        bool BasicDmg5()
        {
            if (Type(4) != 4) return false;
            if (Call(AiCmd.FldEffCheck, A(1, 2)) != 0) return false;
            Score -= 10;
            return true;
        }

        // Soundproof (43): Schall-Attacken (Liste der Attacken-Nummern als Bitmasken).
        bool BouonCheck()
        {
            if (Abil(0) != 0x2b) return false;
            if (IgnoresAbility(Abil(1))) return false;
            long w = CurrentWaza();
            bool hit;
            if (w < 0x1c0)
            {
                if (w < 0xc3) hit = InMask(w, 0x2d, 0x3b, 0x40000000000000fUL) || w == 0xad;
                else if (w < 0x130) hit = w == 0xc3 || w == 0xfd;
                else hit = InMask(w, 0x130, 0x11, 0x18001UL) || w == 0x195;
            }
            else if (w < 0x298)
                hit = InMask(w, 0x223, 0x2c, 0x88018200101UL) || InMask(w, 0x1c0, 0x32, 0x3000000000001UL);
            else hit = w == 0x298 || w == 0x312 || w == 0x2b3;
            if (!hit) return false;
            Score -= 10;
            return true;
        }

        // Bulletproof (171): Ball-/Bomben-Attacken.
        bool BoudanCheck()
        {
            if (Abil(0) != 0xab) return false;
            if (IgnoresAbility(Abil(1))) return false;
            long w = CurrentWaza();
            bool hit;
            if (w < 0x137)
                hit = InMask(w, 0x8c, 0x35, 0x15000000000001UL) || InMask(w, 0xf7, 0x37, 0x42000000000001UL) || w == 0x79;
            else
                hit = InMask(w, 0x18c, 0x30, 0x880040018041UL) || InMask(w, 0x137, 0x32, 0x2000000100001UL)
                    || InMask(w, 0x1e6, 0x3c, 0x800000000000021UL);
            if (!hit) return false;
            Score -= 10;
            return true;
        }

        // Calc_BasicAll: Bouon/Boudan, dann Verteiler nach der KI-Nummer der Attacke.
        void CalcBasicAll()
        {
            if (BouonCheck() || BoudanCheck()) return;
            long seq = Call(AiCmd.CheckWorkWazaSeqNo, Empty);
            if (!SeqDispatch.TryGetValue((int)seq, out int fn)) return;
            if (_seq.TryGetValue(fn, out var body)) body();
        }

        // ------------------------------------------------------------------------------------------------------
        // BaciAI_Seq_NNN
        // ------------------------------------------------------------------------------------------------------

        // Explosion/Finale: keine Wirkung gegen Typ, Feuchtigkeit (6) beim Gegner, sonst Abzug je nach Ersatzpokemon.
        void Seq007()
        {
            if (Call(AiCmd.CheckWazaAisyou, A(4, 1, 0, CurrentWaza(), 0)) == 0)
            {
                if (Abil(1) != 0x68 && Abil(0) == 6)
                {
                    Score -= 10;
                    return;
                }
                if (Call(AiCmd.CheckBtlRule, Empty) != 0) return;
                if (Call(AiCmd.CheckBenchCount, A(1, 1)) != 0) return;
                if (Call(AiCmd.CheckBenchCount, A(1, 0)) == 0)
                {
                    Score -= 1;
                    return;
                }
            }
            Score -= 10;
        }

        // Statuswert-Senker (Seq 18..20): Gegenwert schon auf Minimum, Schutz-Faehigkeiten, Delegator, Heiligtum/Nebel, Pflanzen-Typ gegen Puder usw.
        // Gemeinsamer Anfang: Abzug bei Minimalstufe und bei Verwirrungs-Faehigkeiten.
        void StatDropHead(long side, long stat, int abilityPenalty)
        {
            if (Call(AiCmd.IfParaEqual, A(3, side, stat)) != 0) Score -= 10;
            long d0 = Abil(0);
            if (d0 == 0xac || d0 == 0x80) Score -= abilityPenalty;
        }

        // Pruefung der Gegner-Faehigkeit 0xa6 (Pflanzen-Typ): true = Abzug (-10) und Ende.
        bool GrassGuard(long def)
        {
            if (Type(0) == 0xb) return def == 0xa6;
            long t2 = Type(2);
            return def == 0xa6 && t2 == 0xb;
        }

        // Nachsatz: im Doppelkampf (CHECK_BTL_RULE == 1) zaehlt auch die Faehigkeit 0xa6 des Partners.
        void StatDropTail()
        {
            if (Call(AiCmd.CheckBtlRule, Empty) != 1) return;
            if (Call(AiCmd.CheckTokusei, A(1, 2)) != 0xa6) return;
            Score -= 10;
        }

        // Delegator (-10 und Ende) bzw. Schleier; true = beendet.
        bool StatDropSubstitute(long atk)
        {
            if (atk == 0x97) return false;
            if (Call(AiCmd.IfMigawari, A(1, 0)) != 0) { Score -= 10; return true; }
            if (Call(AiCmd.IfSideEff, A(2, 0, 3)) != 0) Score -= 10;
            return IgnoresAbility(atk);
        }

        void Seq018()
        {
            StatDropHead(0, 1, 0xc);
            long atk = Abil(1);
            if (StatDropSubstitute(atk)) return;
            long def = Abil(0);
            if (InMask(def, 0x1d, 0x2d, 0x100000800001UL)) Score -= 10;
            else if (def == 0x7e || def == 0x9c) Score -= 0xc;
            else if (GrassGuard(def)) { Score -= 10; return; }
            StatDropTail();
        }

        void Seq019()
        {
            StatDropHead(1, 2, 0xc);
            long atk = Abil(1);
            if (StatDropSubstitute(atk)) return;
            long def = Abil(0);
            if (def < 0x7e)
            {
                if (def != 0x1d && def != 0x49) { if (GrassGuard(def)) { Score -= 10; return; } }
                else Score -= 10;
            }
            else if (def == 0x7e || def == 0x9c) Score -= 0xc;
            else if (def == 0x91) Score -= 10;
            else if (GrassGuard(def)) { Score -= 10; return; }
            StatDropTail();
        }

        void Seq020()
        {
            StatDropHead(1, 5, 8);
            long atk = Abil(1);
            if (StatDropSubstitute(atk)) return;
            long def = Abil(0);
            if (def < 0x7e) { if (def == 0x1d || def == 0x49) { Score -= 10; return; } }
            else if (def == 0x7e || def == 0x9c) { Score -= 0xc; return; }
            if (Type(0) != 0xb && Type(2) != 0xb) return;
            if (def != 0xa6)
            {
                if (Call(AiCmd.CheckBtlRule, Empty) != 1) return;
                if (Call(AiCmd.CheckTokusei, A(1, 2)) != 0xa6) return;
            }
            Score -= 10;
        }

        // Schlafen/Gift usw. nur bei Gegner ohne Zustand: Hauptzustand, Heiligtum (Seiteneffekt 2), Delegator, Boden-Lage, Faehigkeiten (Seq001).
        void Seq001()
        {
            if (Call(AiCmd.IfPokeSick, A(1, 0)) != 0 || Call(AiCmd.IfSideEff, A(2, 0, 2)) != 0) { Score -= 10; return; }
            long atk = Abil(1);
            long sub = Call(AiCmd.IfMigawari, A(1, 0));
            if (atk != 0x97 && sub != 0) { Score -= 10; return; }
            long def = Abil(0);
            long t1 = Type(0);
            long t2 = Type(2);
            long gr3 = Call(AiCmd.IfExistGround, A(1, 3));
            if (t2 != 2 && t1 != 2 && def != 0x1a && gr3 != 0) { Score -= 10; return; }
            long gr2 = Call(AiCmd.IfExistGround, A(1, 2));
            if (t2 != 2 && t1 != 2 && def != 0x1a && gr2 != 0) { Score -= 10; return; }
            long rule = Call(AiCmd.CheckBtlRule, Empty);
            if (IgnoresAbility(atk)) return;
            if (def != 0xf && def != 0x9c && def != 0x48)
            {
                if (t1 == 0xb || t2 == 0xb)
                {
                    if (def != 0xa6)
                    {
                        if (rule != 1) return;
                        if (Call(AiCmd.CheckTokusei, A(1, 2)) != 0xa6) return;
                    }
                }
                else if (def == 0xc5)
                {
                    if (Call(AiCmd.IfHpOver, A(2, 0, 0x33)) == 0) return;
                }
                else if (def != 0xaf)
                {
                    if (rule != 1) return;
                    if (Call(AiCmd.CheckTokusei, A(1, 2)) != 0xaf) return;
                }
            }
            Score -= 10;
        }

        // Statuswert-Attacken (Seq 10..13, 211, 212): Faehigkeit 0x7e (-12) oder Stufe schon auf Maximum (-10).
        void StatMaxPenalty(long stat)
        {
            if (Abil(1) == 0x7e) { Score -= 0xc; return; }
            if (Call(AiCmd.IfParaEqual, A(3, 1, stat, 12)) == 0) return;
            Score -= 10;
        }

        void Seq010() => StatMaxPenalty(1);

        void Seq011() => StatMaxPenalty(2);

        void Seq013() => StatMaxPenalty(3);

        void Seq212() => StatMaxPenalty(1);

        void Seq012()
        {
            if (Abil(1) == 0x7e) { Score -= 0xc; return; }
            if (Call(AiCmd.IfParaEqual, A(3, 1, 5, 12)) == 0)
            {
                if (Call(AiCmd.FldEffCheck, A(1, 1)) == 0) return;
                Score -= 5;
                return;
            }
            Score -= 10;
        }

        void Seq016()
        {
            if (Abil(1) == 0x7e) { Score -= 0xc; return; }
            if (Abil(0) == 99 || Abil(1) == 99 || Call(AiCmd.IfParaEqual, A(3, 1, 7, 12)) != 0)
            {
                Score -= 10;
                return;
            }
        }

        void Seq211()
        {
            if (Abil(1) == 0x7e) { Score -= 0xc; return; }
            if (Call(AiCmd.IfParaEqual, A(3, 1, 3, 12)) == 0 && Call(AiCmd.IfParaEqual, A(3, 1, 4, 12)) == 0) return;
            Score -= 10;
        }

        void Seq028()
        {
            if (Call(AiCmd.CheckBenchCount, A(1, 0)) == 0) Score -= 10;
            long def = Abil(0);
            long atk = Abil(1);
            if (!IgnoresAbility(atk) && (def == 0x9c || def == 0x15)) Score -= 10;
        }

        void Seq035() { if (Call(AiCmd.IfSideEff, A(2, 1, 1)) != 0) Score -= 10; }

        void Seq037()
        {
            if (Call(AiCmd.IfWazaSick, A(2, 1, 0xf)) != 0) { Score -= 10; return; }
            long atk = Abil(1);
            long t1 = Type(1);
            long t2 = Type(3);
            long gr3 = Call(AiCmd.IfExistGround, A(1, 3));
            if (gr3 == 0)
            {
                long gr2 = Call(AiCmd.IfExistGround, A(1, 2));
                if (t2 != 2 && t1 != 2 && atk != 0x1a && gr2 != 0) { Score -= 10; return; }
            }
            else if (atk != 0x1a && t1 != 2 && t2 != 2) { Score -= 10; return; }
            Seq032();
        }

        void Seq047() { if (Call(AiCmd.IfContFlg, A(2, 1, 9)) != 0) Score -= 10; }

        void Seq092() { if (Call(AiCmd.IfnWazaSick, A(2, 1, 2)) != 0) Score -= 10; }

        void Seq132() => Seq032();

        void Seq032() { if (Call(AiCmd.IfHpEqual, A(2, 1, 100)) != 0) Score -= 8; }

        void Seq251() { if (Call(AiCmd.IfWazaSick, A(2, 1, 0x24)) != 0) Score -= 10; }

        // Wetter-Attacken: Abzug, wenn schon passendes Wetter herrscht (Regen/Starkregen/Extremsonne/Windboeen bzw. ab Sandsturm).
        void Seq136()
        {
            long w = Call(AiCmd.CheckWeather, Empty);
            if (w < 8 && ((0xe4UL >> (int)w) & 1) != 0) Score -= 8;
        }

        void Seq115()
        {
            long w = Call(AiCmd.CheckWeather, Empty);
            if (((ulong)w & 0xfffffffffffffffcUL) == 4) Score -= 8;
        }

        void Seq148() { if (Call(AiCmd.IfMiraiyochi, A(1, 0)) != 0) Score -= 10; }

        void Seq158() { if (Call(AiCmd.CheckNekodamasi, A(1, 1)) != 0) Score -= 10; }

        void Seq160()
        {
            if (Abil(1) == 0x7e) { Score -= 0xc; return; }
            if (Call(AiCmd.CheckTakuwaeru, A(1, 1)) != 3) return;
            Score -= 10;
        }

        void Seq188()
        {
            long atk = Abil(1);
            long def = Abil(0);
            long item = Call(AiCmd.CheckSoubiItem, A(1, 0));
            if (item == 0 || (!IgnoresAbility(atk) && def == 0x3c)) Score -= 10;
            long sub = Call(AiCmd.IfMigawari, A(1, 0));
            if (atk != 0x97 && sub != 0) Score -= 10;
        }

        void Seq225()
        {
            if (Call(AiCmd.IfSideEff, A(2, 1, 4)) != 0) { Score -= 10; return; }
            if (Call(AiCmd.FldEffCheck, A(1, 1)) == 0) return;
            Score -= 8;
        }

        void Seq065()
        {
            if (Call(AiCmd.IfSideEff, A(2, 1)) != 0) Score -= 10;
        }

        // Schlafattacke (Seq033): Wetter/Fähigkeiten des Gegners (Insomnia 0x11, Blattschutz bei Sonne, Wetterfest...), Gift-/Stahl-Typen, Boden-Lage.
        void Seq033()
        {
            long t1 = Type(0);
            long t2 = Type(2);
            long def = Abil(0);
            long atk = Abil(1);
            long weather = Call(AiCmd.CheckWeather, Empty);
            if (def == 0x5a) { Score -= 0xc; return; }
            long sub = Call(AiCmd.IfMigawari, A(1, 0));
            if (atk != 0x97 && sub != 0) { Score -= 10; return; }
            if (!IgnoresAbility(atk))
            {
                if (def == 0xc5) { if (Call(AiCmd.IfHpOver, A(2, 0, 0x33)) != 0) { Score -= 10; return; } }
                else if (def == 0x9c) { Score -= 0xc; return; }
                else if (def == 0x11 || (def == 0x66 && weather == 1)) { Score -= 10; return; }
                if (Type(0) == 0xb || Type(2) == 0xb)
                {
                    if (def != 0xa6 && Call(AiCmd.CheckBtlRule, Empty) == 1 && Call(AiCmd.CheckTokusei, A(1, 2)) == 0xa6) { Score -= 10; return; }
                }
            }
            if (t1 == 3 || t1 == 8 || t2 == 3 || t2 == 8) { Score -= 10; return; }
            if (def != 0x62 && Call(AiCmd.IfPokeSick, A(1, 0)) == 0)
            {
                long ground = Call(AiCmd.IfExistGround, A(1, 2));
                if ((t2 == 2 || t1 == 2 || def == 0x1a || ground == 0) && Call(AiCmd.IfSideEff, A(2, 0, 2)) == 0) return;
            }
            Score -= 10;
        }

        void Seq084()
        {
            long atk = Abil(1);
            long def = Abil(0);
            long t1 = Type(0);
            long t2 = Type(2);
            if (Call(AiCmd.IfWazaSick, A(2, 0, 0x12)) == 0)
            {
                if (t1 == 0xb || t2 == 0xb) Score -= 10;
                else if (!IgnoresAbility(atk))
                {
                    if (def == 0x62) Score -= 10;
                    else if (def == 0x9c) Score -= 0xc;
                }
            }
            else Score -= 8;
            long sub = Call(AiCmd.IfMigawari, A(1, 0));
            if (atk != 0x97 && sub != 0) Score -= 10;
        }

        void Seq106()
        {
            long atk = Abil(1);
            long def = Abil(0);
            if (Call(AiCmd.IfWazaSick, A(2, 0, 0x16)) != 0) Score -= 10;
            if (Type(0) == 7 || Type(2) == 7) Score -= 10;
            else if (!IgnoresAbility(atk) && def == 0x9c) { Score -= 0xc; return; }
            long sub = Call(AiCmd.IfMigawari, A(1, 0));
            if (atk == 0x97 || sub == 0) return;
            Score -= 10;
        }

        void Seq109()
        {
            long t1 = Type(1);
            long t2 = Type(3);
            if (t1 == 7 || t2 == 7)
            {
                if (Call(AiCmd.IfWazaSick, A(2, 0, 10)) == 0) return;
            }
            else
            {
                if (Abil(1) == 0x7e) { Score -= 0xc; return; }
                if (Call(AiCmd.IfParaEqual, A(3, 1, 1, 12)) == 0)
                {
                    if (Call(AiCmd.IfParaEqual, A(3, 1, 2, 12)) == 0) return;
                }
            }
            Score -= 10;
        }

        void Seq049()
        {
            long atk = Abil(1);
            long def = Abil(0);
            if (Call(AiCmd.IfSideEff, A(2, 0, 2)) == 0)
            {
                if (Call(AiCmd.IfWazaSick, A(2, 0, 6)) != 0) Score -= 8;
            }
            else Score -= 10;
            if (Call(AiCmd.IfMigawari, A(1, 0)) == 0)
            {
                if (IgnoresAbility(atk)) return;
                if (def == 0x9c)
                {
                    Score -= 0xc;
                    return;
                }
                if (def != 0x14) return;
            }
            else if (atk == 0x97) return;
            Score -= 10;
        }
    }
}
