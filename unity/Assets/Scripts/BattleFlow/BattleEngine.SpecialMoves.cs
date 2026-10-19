using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using Xnu.Data;

namespace Xnu.Battle.Flow
{
    public sealed partial class BattleEngine
    {
        ushort _lastMoveAny;

        // Attacken der Kategorien 10-13, die ihre Wirkung ueber Handler (UNCATEGORIZE_WAZA 196, Seiteneffekte 197, ...) haben.
        // Rueckgabe false = nicht umgesetzt. Nummern wie WazaTable/Handler.Waza.
        bool ResolveSpecialMove(BattleMon att, BattleMon foe, MoveRecord rec, MoveInfo mi)
        {
            int no = rec.MoveNo;
            ushort moveNo = (ushort)no;
            bool foeTarget = rec.Target == 0 || rec.Target == 3 || rec.Target == 4 || rec.Target == 5 || rec.Target == 9;
            if (!IsSpecialSupported(no)) return false;
            if (foeTarget && IsProtectBlockable(no))
            {
                if (foe.Protected) { Add(LogKind.Protected, foe.PokeId, att.PokeId, moveNo); return true; }
                if (!CheckHit(att, foe, rec, mi)) { Add(LogKind.MoveMissed, att.PokeId, foe.PokeId, moveNo); return true; }
            }

            switch (no)
            {
                case 115: return Fx(att, SetSide(att, att.Side, SideEffect.Reflect, 5));
                case 113: return Fx(att, SetSide(att, att.Side, SideEffect.LightScreen, 5));
                case 694:
                    if (Weather.Weather != BattleWeather.Hail) return Fail(att, moveNo, FailCause.NothingHappened);
                    return Fx(att, SetSide(att, att.Side, SideEffect.AuroraVeil, 5));
                case 219: return Fx(att, SetSide(att, att.Side, SideEffect.Safeguard, 5));
                case 54: return Fx(att, SetSide(att, att.Side, SideEffect.Mist, 5));
                case 366: return Fx(att, SetSide(att, att.Side, SideEffect.Tailwind, 4));
                case 446: return Fx(att, SetSide(att, foe.Side, SideEffect.StealthRock, 0));
                case 191: return Fx(att, SetSide(att, foe.Side, SideEffect.Spikes, 0));
                case 390: return Fx(att, SetSide(att, foe.Side, SideEffect.ToxicSpikes, 0));
                case 564: return Fx(att, SetSide(att, foe.Side, SideEffect.StickyWeb, 0));
                case 433: StartTrickRoom(att); return true;
                case 114:    // Dunkelnebel: alle Statuswertaenderungen zuruecksetzen
                    ResetRanks(att); ResetRanks(foe); return true;
                case 174: return Curse(att, foe, moveNo);
                case 212: case 335:    // Fluchtverbot / Spinnennetz
                    return AddPlain(att, foe, Sick.MeanLook, SickCont.MakePermanent((uint)(att.PokeId & 0x1F)), moveNo);
                case 269:    // Verhoehner: 3 Runden (4, wenn das Ziel schon gehandelt hat)
                    if (foe.HasSick(11)) return Fail(att, moveNo, FailCause.NothingHappened);
                    foe.AddSick(11, SickCont.MakeTurn((uint)(att.PokeId & 0x1F), foe.Poke.GetTurnFlag(1) ? 4u : 3u));
                    Add(LogKind.SickAdded, foe.PokeId, att.PokeId, 11);
                    return true;
                case 116:    // Fokusenergie
                    if (att.CriticalBonus > 0) return Fail(att, moveNo, FailCause.NothingHappened);
                    att.CriticalBonus = 2;
                    return true;
                case 156: return Rest(att, moveNo);
                case 392:    // Wasserring
                    if (att.HasSick(36)) return Fail(att, moveNo, FailCause.NothingHappened);
                    att.AddSick(36, SickCont.MakePermanent((uint)(att.PokeId & 0x1F)));
                    Add(LogKind.SickAdded, att.PokeId, att.PokeId, 36);
                    return true;
                case 150: return true;    // Platscher: passiert nichts
                case 227:    // Zugabe
                    if (foe.LastMove == 0 || foe.HasSick(23) || foe.FindMove(foe.LastMove) >= BattleMon.MoveCount) return Fail(att, moveNo, FailCause.NothingHappened);
                    foe.AddSick(23, SickCont.MakeTurnParam((uint)(att.PokeId & 0x1F), 3, foe.LastMove));
                    Add(LogKind.SickAdded, foe.PokeId, att.PokeId, 23);
                    return true;
                case 50:     // Aussetzer
                    if (foe.LastMove == 0 || foe.HasSick(13) || foe.FindMove(foe.LastMove) >= BattleMon.MoveCount) return Fail(att, moveNo, FailCause.NothingHappened);
                    foe.AddSick(13, SickCont.MakeTurnParam((uint)(att.PokeId & 0x1F), 4, foe.LastMove));
                    Add(LogKind.SickAdded, foe.PokeId, att.PokeId, 13);
                    return true;
                case 383:    // Imitator: zuletzt benutzte Attacke
                {
                    var last = Data.GetMove(_lastMoveAny);
                    if (last == null || _lastMoveAny == 383 || last.Category == 13 && !IsSpecialSupported(last.MoveNo)) return Fail(att, moveNo, FailCause.NothingHappened);
                    ResolveMove(att, last, false);
                    return true;
                }
                case 254:    // Vorrat
                    if (att.Stockpile >= 3) return Fail(att, moveNo, FailCause.NothingHappened);
                    att.Stockpile++;
                    ChangeRank(att, 2, 1); ChangeRank(att, 4, 1);
                    return true;
                case 502: case 270: case 266: return Fail(att, moveNo, FailCause.NoTarget);    // Platztausch/Fremdhilfe/Spotlight: kein Partner im Einzelkampf
                case 388:    // Sorgenssamen: Faehigkeit des Ziels wird Insomnia (15)
                    if (foe.Poke.Tokusei == 15 || foe.Poke.Tokusei == 121 || foe.Poke.Tokusei == 125) return Fail(att, moveNo, FailCause.NothingHappened);
                    UnregisterAbility(foe); foe.Poke.Tokusei = 15; RegisterAbility(foe);
                    if (foe.PokeSick == Sick.Sleep) CureLogged(foe, Sick.Sleep);
                    return true;
                case 197: case 182: case 596: case 673: return Protect(att, moveNo, endure: false);
                case 203: return Protect(att, moveNo, endure: true);
                case 46: case 18: return ForceSwitch(att, foe, moveNo);
                case 375:    // Psychotausch
                    if (att.PokeSick == 0 || !CanInflict(foe, att.PokeSick)) return Fail(att, moveNo, FailCause.NothingHappened);
                    { int s = att.PokeSick; ulong cont = att.SickContents[s]; CureLogged(att, s); foe.AddSick(s, cont); Add(LogKind.SickAdded, foe.PokeId, att.PokeId, s); }
                    return true;
                case 248:    // Zukunftsschuss
                    if (Sides[foe.Side].FutureTurns > 0) return Fail(att, moveNo, FailCause.NothingHappened);
                    Sides[foe.Side].FutureTurns = 3; Sides[foe.Side].FutureMove = moveNo; Sides[foe.Side].FutureAttacker = att.PokeId;
                    return true;
                case 226: return BatonPass(att, moveNo);
                case 194:    // Abgangsbund
                    att.DestinyBond = true; return true;
                case 487:    // Aquaschauer: Ziel wird Wasser
                    foe.Poke.Type1 = foe.Poke.Type2 = (byte)PokeType.Water; foe.Poke.TypeEx = 18; return true;
                case 100:    // Teleport: nur gegen wilde Pokemon
                    if (!IsWild) return Fail(att, moveNo, FailCause.NothingHappened);
                    Finish(att.Side == PlayerSide ? BattleResult.Run : BattleResult.RunEnemy);
                    return true;
                case 199: case 170:    // Erkennen/Gedankenleser: naechste Attacke trifft sicher
                    att.AddSick(29, SickCont.MakeTurn((uint)(att.PokeId & 0x1F), 2)); return true;
                case 244:    // Egotrip... Psych Up: Statuswerte des Ziels kopieren
                    for (int r = 1; r <= BattlePoke.RankCount; r++) att.Poke.SetRank((PokeValueId)r, foe.Poke.GetRank((PokeValueId)r));
                    return true;
                case 384:    // Kraft-Tausch: Angriff und Sp.-Angriff tauschen
                    foreach (var r in new[] { PokeValueId.ATTACK_RANK, PokeValueId.SP_ATTACK_RANK })
                    { int a = att.Poke.GetRank(r), b = foe.Poke.GetRank(r); att.Poke.SetRank(r, b); foe.Poke.SetRank(r, a); }
                    return true;
                case 187:    // Bauchtrommel
                    if (att.Poke.Hp <= att.Poke.MaxHp / 2) return Fail(att, moveNo, FailCause.NothingHappened);
                    att.Poke.Hp = (ushort)(att.Poke.Hp - att.Poke.MaxHp / 2);
                    Add(LogKind.Recoil, att.PokeId, value: att.Poke.MaxHp / 2, value2: att.Poke.Hp);
                    ChangeRank(att, 1, 12);
                    return true;
                case 504:    // Panzerbruch
                    ChangeRank(att, 2, -1); ChangeRank(att, 4, -1); ChangeRank(att, 1, 2); ChangeRank(att, 3, 2); ChangeRank(att, 5, 2);
                    return true;
                case 220:    // Schmerzteiler
                {
                    int avg = (att.Poke.Hp + foe.Poke.Hp) / 2;
                    att.Poke.Hp = (ushort)Math.Min(att.Poke.MaxHp, avg); foe.Poke.Hp = (ushort)Math.Min(foe.Poke.MaxHp, avg);
                    Add(LogKind.Recover, att.PokeId, value: 0, value2: att.Poke.Hp); Add(LogKind.Recover, foe.PokeId, value: 0, value2: foe.Poke.Hp);
                    return true;
                }
                case 273:    // Wunschtraum
                    if (Sides[att.Side].WishTurns > 0) return Fail(att, moveNo, FailCause.NothingHappened);
                    Sides[att.Side].WishTurns = 2; Sides[att.Side].WishHeal = att.Poke.MaxHp / 2;
                    return true;
                case 215:    // Vitalglocke: Hauptzustaende der ganzen Party
                    foreach (var m in Parties[att.Side])
                        if (!m.IsFainted && m.PokeSick != 0) { int s = m.PokeSick; CureLogged(m, s); }
                    return true;
                case 432:    // Wirbelwind-Raeumer: Evasion -1, Hindernisse/Schirme beider Seiten weg
                    ChangeRank(foe, 7, -1, att);
                    for (int s = 0; s < 2; s++)
                        foreach (int e in new[] { SideEffect.Reflect, SideEffect.LightScreen, SideEffect.AuroraVeil, SideEffect.Safeguard, SideEffect.Mist, SideEffect.StealthRock, SideEffect.Spikes, SideEffect.ToxicSpikes, SideEffect.StickyWeb })
                            if (SideActive(s, e)) EndSide(s, e);
                    return true;
                case 367:    // Akupressur
                    ChangeRank(att, 1 + (int)Random.GetValue(7), 2); return true;
                case 180:    // Groll
                {
                    int slot = foe.FindMove(foe.LastMove);
                    if (slot >= BattleMon.MoveCount || foe.Pp[slot] == 0) return Fail(att, moveNo, FailCause.NothingHappened);
                    foe.Pp[slot] = (byte)Math.Max(0, foe.Pp[slot] - 4); return true;
                }
                case 271: case 415:    // Trickser/Wechseldich: Items tauschen
                {
                    if (att.Poke.Item == 0 && foe.Poke.Item == 0) return Fail(att, moveNo, FailCause.NothingHappened);
                    UnregisterItem(att); UnregisterItem(foe);
                    (att.Poke.Item, foe.Poke.Item) = (foe.Poke.Item, att.Poke.Item);
                    att.ChoiceLock = foe.ChoiceLock = 0;
                    RegisterItem(att); RegisterItem(foe);
                    return true;
                }
                case 393: att.Floating = true; return true;    // Magnetflug (Dauer: bis zum Auswechseln)
                case 262:    // Memento: Anwender faellt, Ziel -2 Angriff/Sp.-Angriff
                    ChangeRank(foe, 1, -2, att); ChangeRank(foe, 3, -2, att);
                    att.Poke.Hp = 0; Add(LogKind.Recoil, att.PokeId, value: 0, value2: 0); OnFaint(att);
                    return true;
                default: return false;
            }
        }

        static readonly HashSet<int> SupportedSpecial = new HashSet<int>
        {
            115, 113, 694, 219, 54, 366, 446, 191, 390, 564, 433, 114, 174, 212, 335, 269, 116, 156, 392, 150, 227, 50, 383, 254, 502, 270, 266, 388,
            197, 182, 596, 673, 203, 46, 18, 375, 248, 226, 194, 487, 100, 199, 170, 244, 384, 187, 504, 220, 273, 215, 432, 367, 180, 271, 415, 393, 262,
        };

        public static bool IsSpecialSupported(int moveNo) => SupportedSpecial.Contains(moveNo);

        // Attacken, die ein Schutz abwehrt und deren Genauigkeit geprueft wird (nur Ziel-Attacken).
        static bool IsProtectBlockable(int no) => no == 212 || no == 335 || no == 269 || no == 227 || no == 50 || no == 388 || no == 375 || no == 248 || no == 487 ||
            no == 180 || no == 271 || no == 415 || no == 244 || no == 384 || no == 46 || no == 18 || no == 432;

        bool Fx(BattleMon att, bool ok) => ok ? true : Fail(att, 0, FailCause.NothingHappened);

        bool Fail(BattleMon att, ushort moveNo, int cause)
        {
            Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: cause);
            return true;
        }

        bool AddPlain(BattleMon att, BattleMon foe, int sick, ulong cont, ushort moveNo)
        {
            if (foe.IsFainted || foe.HasSick(sick)) return Fail(att, moveNo, FailCause.NothingHappened);
            foe.AddSick(sick, cont);
            Add(LogKind.SickAdded, foe.PokeId, att.PokeId, sick);
            return true;
        }

        bool SideActive(int side, int effect)
        {
            var st = Sides[side];
            switch (effect)
            {
                case SideEffect.Reflect: return st.Reflect > 0;
                case SideEffect.LightScreen: return st.LightScreen > 0;
                case SideEffect.AuroraVeil: return st.AuroraVeil > 0;
                case SideEffect.Safeguard: return st.Safeguard > 0;
                case SideEffect.Mist: return st.Mist > 0;
                case SideEffect.StealthRock: return st.StealthRock;
                case SideEffect.Spikes: return st.Spikes > 0;
                case SideEffect.ToxicSpikes: return st.ToxicSpikes > 0;
                case SideEffect.StickyWeb: return st.StickyWeb;
                default: return false;
            }
        }

        void ResetRanks(BattleMon m)
        {
            for (int r = 1; r <= BattlePoke.RankCount; r++) m.Poke.SetRank((PokeValueId)r, BattlePoke.NeutralRank);
        }

        // Fluch: Geist-Typ opfert die Haelfte der KP und belegt das Ziel; sonst Initiative -1, Angriff/Abwehr +1.
        bool Curse(BattleMon att, BattleMon foe, ushort moveNo)
        {
            if (att.Poke.IsMatchType((int)PokeType.Ghost))
            {
                if (foe.HasSick(Sick.Curse)) return Fail(att, moveNo, FailCause.NothingHappened);
                uint cost = Math.Max(1u, (uint)att.Poke.MaxHp / 2);
                cost = Math.Min(cost, att.Poke.Hp);
                att.Poke.Hp = (ushort)(att.Poke.Hp - cost);
                Add(LogKind.Recoil, att.PokeId, value: (int)cost, value2: att.Poke.Hp);
                foe.AddSick(Sick.Curse, SickCont.MakePermanent((uint)(att.PokeId & 0x1F)));
                Add(LogKind.SickAdded, foe.PokeId, att.PokeId, Sick.Curse);
                if (att.IsFainted) OnFaint(att);
                return true;
            }
            ChangeRank(att, 5, -1); ChangeRank(att, 1, 1); ChangeRank(att, 2, 1);
            return true;
        }

        // Schlafmuetze (handler_Nemuru): volle KP, Zustaende weg, 3 Runden Schlaf.
        bool Rest(BattleMon att, ushort moveNo)
        {
            if (att.Poke.IsHpFull || att.PokeSick == Sick.Sleep) return Fail(att, moveNo, FailCause.NothingHappened);
            int s = att.PokeSick;
            if (s != 0) CureLogged(att, s);
            Recover(att, (uint)(att.Poke.MaxHp - att.Poke.Hp), LogKind.Recover);
            att.AddSick(Sick.Sleep, SickCont.MakeTurn((uint)(att.PokeId & 0x1F), 3));
            Add(LogKind.SickAdded, att.PokeId, att.PokeId, Sick.Sleep);
            return true;
        }

        // handler_Mamoru_ExeCheck: Zaehler > 0: Zug GetRand(3^Zaehler) != 0 -> Fehlschlag; Anwender als Letzter -> Fehlschlag [P: Tabelle 3er-Potenzen].
        bool Protect(BattleMon att, ushort moveNo, bool endure)
        {
            bool fail = false;
            if (att.ProtectCount > 0)
            {
                ulong n = 1;
                for (int i = 0; i < Math.Min(att.ProtectCount, 5); i++) n *= 3;
                fail = Random.GetValue(n) != 0;
            }
            else if (Active(1 - att.Side).Poke.GetTurnFlag(0)) fail = true;    // CheckPokeOrderLast
            if (fail) { att.ProtectCount = 0; return Fail(att, moveNo, FailCause.NothingHappened); }
            att.ProtectCount++;
            if (endure) att.Enduring = true; else att.Protected = true;
            return true;
        }

        // Brüller/Wirbelwind: Ziel wird gegen ein zufaelliges anderes Pokemon getauscht; ein wildes Ziel flieht (Kampf endet).
        bool ForceSwitch(BattleMon att, BattleMon foe, ushort moveNo)
        {
            if (foe.IsFainted) return Fail(att, moveNo, FailCause.NothingHappened);
            var candidates = new List<int>();
            for (int i = 0; i < Parties[foe.Side].Count; i++)
                if (!Parties[foe.Side][i].IsFainted && i != _active[foe.Side]) candidates.Add(i);
            if (IsWild && foe.Side == EnemySide)
            {
                Add(LogKind.Forced, foe.PokeId, att.PokeId, moveNo);
                Finish(BattleResult.RunEnemy);
                return true;
            }
            if (candidates.Count == 0) return Fail(att, moveNo, FailCause.NothingHappened);
            int pick = candidates[(int)Random.GetValue((ulong)candidates.Count)];
            Add(LogKind.Forced, foe.PokeId, att.PokeId, moveNo);
            SwapIn(foe.Side, pick, replacement: false);
            return true;
        }

        // Stafette: Statuswerte, Fokusenergie und Bindungs-/Fluchtverbot-Zustaende gehen an das neue Pokemon.
        bool BatonPass(BattleMon att, ushort moveNo)
        {
            int idx = att.Side == EnemySide ? _brain.ChooseReplacement(this) : Parties[PlayerSide].FindIndex(m => !m.IsFainted && m != att);
            if (idx < 0 || Parties[att.Side][idx] == att || Parties[att.Side][idx].IsFainted)
            {
                idx = Parties[att.Side].FindIndex(m => !m.IsFainted && m != att);
                if (idx < 0) return Fail(att, moveNo, FailCause.NothingHappened);
            }
            var ranks = new int[BattlePoke.RankCount + 1];
            for (int r = 1; r <= BattlePoke.RankCount; r++) ranks[r] = att.Poke.GetRank((PokeValueId)r);
            int crit = att.CriticalBonus;
            SwapIn(att.Side, idx, replacement: false);
            var m2 = Active(att.Side);
            for (int r = 1; r <= BattlePoke.RankCount; r++) m2.Poke.SetRank((PokeValueId)r, ranks[r]);
            m2.CriticalBonus = crit;
            return true;
        }

        // handler_pos_DelayAttack: Schaden mit den aktuellen Werten des Anwenders gegen das Pokemon auf der Position; ohne Treffer-/Volltrefferpruefung.
        void FutureSightHit(BattleMon att, BattleMon target, MoveRecord rec)
        {
            var mi = MakeMoveInfo(rec);
            int aff = TypeAffinity.CalcPair(rec.Type, target.Poke.Type1, target.Poke.Type2, target.Poke.TypeEx, Setup.Inverse);
            if (aff == AffinityId.Zero) { Add(LogKind.NoEffect, target.PokeId, att.PokeId, rec.MoveNo); return; }
            var input = Launcher.BuildDamageInput(att.Poke, target.Poke, mi, false, aff, Weather.Weather, false);
            uint dmg = DamageCalculator.ClampToHp(DamageCalculator.Calc(input, Random).Damage, target.Poke.Hp);
            target.Poke.Hp = (ushort)(target.Poke.Hp - dmg);
            Add(LogKind.Damage, target.PokeId, att.PokeId, rec.MoveNo, (int)dmg, target.Poke.Hp);
            if (target.IsFainted) OnFaint(target);
        }
    }
}
