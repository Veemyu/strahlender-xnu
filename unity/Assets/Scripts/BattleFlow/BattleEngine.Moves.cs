using System;
using System.Collections.Generic;
using Xnu.Battle.Events;
using Xnu.Data;

namespace Xnu.Battle.Flow
{
    public sealed partial class BattleEngine
    {
        public const ushort StruggleNo = 165;

        // Attackenkategorien (WazaCategory des Originals).
        static class Cat
        {
            public const int SimpleDamage = 0;
            public const int SimpleSick = 1;
            public const int SimpleEffect = 2;
            public const int SimpleRecover = 3;
            public const int DamageSick = 4;
            public const int EffectSick = 5;
            public const int DamageEffect = 6;
            public const int DamageEffectUser = 7;
            public const int Drain = 8;
            public const int Ichigeki = 9;
            public const int FieldEffect = 10;
        }

        // Wetter-Attacken: Attackennummer -> Wetter (BtlWeather). Dauer 5 Runden (Verlaengerung durch Items nicht angeschlossen).
        static readonly Dictionary<int, BattleWeather> WeatherMoves = new Dictionary<int, BattleWeather>
        {
            { 241, BattleWeather.Sun },
            { 240, BattleWeather.Rain },
            { 201, BattleWeather.Sandstorm },
            { 258, BattleWeather.Hail },
        };

        public const int DefaultWeatherTurns = 5;

        static MoveInfo MakeMoveInfo(MoveRecord rec) => new MoveInfo
        {
            WazaId = (ushort)rec.MoveNo,
            Type = (byte)rec.Type,
            DamageType = rec.DamageType,
            TouchFlag = (rec.Flags & 1) != 0,
            Priority = rec.Priority,
            Power = (ushort)rec.Power,
            HitPercent = (uint)rec.Accuracy,
        };

        // Ersatzdaten fuer Verzweifler, falls die Stammdaten ihn nicht enthalten (Normal, physisch, 50, Rueckstoss 1/4 der Max-KP).
        MoveRecord StruggleRecord() => Data.GetMove(StruggleNo) ?? new MoveRecord { MoveNo = StruggleNo, IsValid = true, Type = 18, DamageType = 1, Power = 50, Accuracy = 0, BasePp = 1, Target = 0 };

        void ExecuteFight(BattleMon att, int slot)
        {
            bool struggle = !AnyPp(att);
            ushort moveNo = struggle ? StruggleNo : att.Moves[slot];
            // Zugabe (Zustand 23) und Wahl-Items (Wahlband/-brille/-schal) erzwingen die gewaehlte Attacke.
            if (!struggle)
            {
                ushort forced = 0;
                if (att.HasSick(23)) forced = SickCont.GetParam(att.SickContents[23]);
                else if (att.ChoiceLock != 0) forced = att.ChoiceLock;
                int fs = forced != 0 ? att.FindMove(forced) : BattleMon.MoveCount;
                if (fs < BattleMon.MoveCount && att.Pp[fs] > 0) { slot = fs; moveNo = forced; }
            }
            var rec = struggle ? StruggleRecord() : Data.GetMove(moveNo);
            if (rec == null)
            {
                Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: FailCause.NotImplemented);
                return;
            }

            int cause = CheckFirstFail(att, rec);
            if (cause != 0)
            {
                Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: cause);
                if (cause == FailCause.Confusion) ConfusionSelfHit(att);
                return;
            }

            // Erst nach der ersten Pruefung werden PP abgezogen (Section_WazaExecStart.decrementPP).
            if (!struggle && att.Pp[slot] > 0) att.Pp[slot]--;
            att.LastMove = moveNo;
            _lastMoveAny = moveNo;
            if (!IsProtectMove(moveNo)) att.ProtectCount = 0;
            if (!struggle && IsChoiceItem(att.Poke.Item)) att.ChoiceLock = moveNo;
            att.DestinyBond = false;
            Add(LogKind.MoveUsed, att.PokeId, id: moveNo);

            var factor = WazaHandlers.Add(Events, moveNo, att.Poke.Id, (uint)att.Poke.GetValueBase(PokeValueId.AGILITY));
            try
            {
                ResolveMove(att, rec, struggle);
            }
            finally
            {
                if (factor != null) Events.RemoveFactor(factor);
            }
        }

        // Section_WazaExec_CheckFail_1st.checkFail @0x227ee20: Reihenfolge Schlaf, Frost, Zurueckschrecken, Verwirrung, Paralyse, Bezauberung.
        int CheckFirstFail(BattleMon att, MoveRecord rec)
        {
            if (att.PokeSick == Sick.Sleep &&
                FlowRules.CheckSleepWakeUp(att.SickContents[Sick.Sleep], ref att.SickCounters[Sick.Sleep], (ushort)att.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE)))
                CureLogged(att, Sick.Sleep);
            if (att.PokeSick == Sick.Sleep) return FailCause.Sleep;

            if (att.PokeSick == Sick.Freeze)
            {
                bool melt = (rec.Flags >> 10 & 1) != 0;
                if (melt || Random.IsOccurPercent(20)) CureLogged(att, Sick.Freeze);
            }
            if (att.PokeSick == Sick.Freeze) return FailCause.Freeze;

            if (att.Poke.GetTurnFlag(TurnFlagShrink)) return FailCause.Flinch;

            // Aussetzer (13): die gesperrte Attacke; Verhoehner (11): Status-Attacken gesperrt (CheckFail_1st: Ursachen 9 und 10).
            if (att.HasSick(13) && SickCont.GetParam(att.SickContents[13]) == rec.MoveNo) return FailCause.Disabled;
            if (att.HasSick(11) && rec.DamageType == 0 && rec.Category != 0 && rec.Power == 0) return FailCause.Taunted;

            if (att.HasSick(Sick.Confusion))
            {
                if (FlowRules.CheckConfusionWakeUp(att.SickContents[Sick.Confusion], ref att.SickCounters[Sick.Confusion])) CureLogged(att, Sick.Confusion);
                else if (Random.IsOccurPercent(33)) return FailCause.Confusion;
            }

            if (att.PokeSick == Sick.Paralysis && Random.IsOccurPercent(25)) return FailCause.Paralysis;
            if (att.HasSick(Sick.Infatuation) && Random.IsOccurPercent(50)) return FailCause.Infatuation;
            return 0;
        }

        public const int TurnFlagShrink = 4;

        // Section_ConfDamage.calcDamage @0x22b56a0: Kraft 40, eigener Angriff/Abwehr mit Stufen, ein Zug GetRand(16), Mindestschaden 1.
        void ConfusionSelfHit(BattleMon mon)
        {
            uint atk = (uint)mon.Poke.GetValue(PokeValueId.ATTACK);
            uint def = (uint)mon.Poke.GetValue(PokeValueId.DEFENCE);
            uint level = (uint)mon.Poke.GetValue(PokeValueId.LEVEL);
            uint dmg = FlowRules.ConfusionDamage(atk, def, level, Random);
            dmg = Math.Min(dmg & 0xFFFF, mon.Poke.Hp);
            mon.Poke.Hp = (ushort)(mon.Poke.Hp - dmg);
            Add(LogKind.ConfusionDamage, mon.PokeId, value: (int)dmg, value2: mon.Poke.Hp);
            if (mon.IsFainted) OnFaint(mon);
        }

        void CureLogged(BattleMon mon, int sickId)
        {
            mon.CureSick(sickId);
            Add(LogKind.SickCured, mon.PokeId, id: sickId);
        }

        bool IsAlwaysHit(MoveRecord rec) => rec.Accuracy == 0 || rec.Accuracy > 100;

        static bool TargetsUser(MoveRecord rec) => rec.Target == 7 || rec.Target == 6 || rec.Target == 12;

        void ResolveMove(BattleMon att, MoveRecord rec, bool struggle)
        {
            var foe = Active(1 - att.Side);
            var mi = MakeMoveInfo(rec);
            ushort moveNo = (ushort)rec.MoveNo;

            switch (rec.Category)
            {
                case Cat.FieldEffect:
                    if (WeatherMoves.TryGetValue(rec.MoveNo, out var weather)) ChangeWeather(att, moveNo, weather, DefaultWeatherTurns);
                    else if (!ResolveSpecialMove(att, foe, rec, mi)) Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: FailCause.NotImplemented);
                    return;
                case Cat.SimpleRecover:
                    ResolveRecover(att, rec);
                    return;
                case Cat.SimpleEffect:
                case Cat.SimpleSick:
                case Cat.EffectSick:
                    ResolveStatusMove(att, foe, rec, mi);
                    return;
                case Cat.Ichigeki:
                    ResolveOhko(att, foe, rec, mi);
                    return;
                case Cat.SimpleDamage:
                case Cat.DamageSick:
                case Cat.DamageEffect:
                case Cat.DamageEffectUser:
                case Cat.Drain:
                    ResolveDamageMove(att, foe, rec, mi, struggle);
                    return;
                default:
                    if (!ResolveSpecialMove(att, foe, rec, mi)) Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: FailCause.NotImplemented);
                    return;
            }
        }

        static bool IsProtectMove(ushort no) => no == 197 || no == 182 || no == 596 || no == 673 || no == 203;

        static bool IsChoiceItem(ushort item) => item == 220 || item == 297 || item == 287;

        // Treffer: Handler (Ereignisse 62-64), Stufen, ein Zug. Immunitaet wird vorher geprueft.
        bool CheckHit(BattleMon att, BattleMon foe, MoveRecord rec, MoveInfo mi)
        {
            if (att.HasSick(29)) { CureSick(att, 29); return true; }          // Erkennen/Gedankenleser
            if (att.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 99 || foe.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 99) return true;   // Tuerschloss-Faehigkeit (Keine Abwehr)
            if (IsAlwaysHit(rec)) return true;
            var input = Launcher.BuildHitInput(att.Poke, foe.Poke, mi);
            return AccuracyCalculator.Check(input, Random).Hit;
        }

        void CureSick(BattleMon m, int id) => m.CureSick(id);

        void ResolveDamageMove(BattleMon att, BattleMon foe, MoveRecord rec, MoveInfo mi, bool struggle)
        {
            ushort moveNo = (ushort)rec.MoveNo;
            if (foe.Protected)
            {
                Add(LogKind.Protected, foe.PokeId, att.PokeId, moveNo);
                return;
            }
            int aff = struggle ? AffinityId.Normal : TypeAffinity.CalcPair(rec.Type, foe.Poke.Type1, foe.Poke.Type2, foe.Poke.TypeEx, Setup.Inverse);
            bool groundImmune = rec.Type == (int)PokeType.Ground && !struggle && (foe.Floating || foe.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 26);   // Schwebe / Magnetflug
            if (aff == AffinityId.Zero || groundImmune)
            {
                Add(LogKind.NoEffect, foe.PokeId, att.PokeId, moveNo);
                return;
            }
            int hits = rec.HitCountMax >= 2 ? Random.HitCountStandard(rec.HitCountMax) : 1;
            if (hits < 1) hits = 1;
            if (!CheckHit(att, foe, rec, mi))
            {
                Add(LogKind.MoveMissed, att.PokeId, foe.PokeId, moveNo);
                return;
            }

            int landed = 0;
            uint total = 0;
            for (int h = 0; h < hits && !foe.IsFainted; h++)
            {
                var crit = CriticalHit.Check(new CriticalInput { MoveStage = rec.CriticalRank, AttackerStage = Math.Min(3, att.CriticalBonus) }, Random);
                var input = Launcher.BuildDamageInput(att.Poke, foe.Poke, mi, crit.Critical, aff, Weather.Weather, att.PokeSick == Sick.Burn);
                uint dmg = DamageCalculator.ClampToHp(DamageCalculator.Calc(input, Random).Damage, foe.Poke.Hp);
                dmg = SurviveCheck(foe, dmg);
                foe.Poke.Hp = (ushort)(foe.Poke.Hp - dmg);
                landed++;
                total += dmg;
                if (h == 0 && aff != AffinityId.Normal) Add(LogKind.Effectiveness, foe.PokeId, att.PokeId, moveNo, aff);
                if (crit.Critical) Add(LogKind.Critical, foe.PokeId, att.PokeId, moveNo);
                Add(LogKind.Damage, foe.PokeId, att.PokeId, moveNo, (int)dmg, foe.Poke.Hp);
                if (foe.IsFainted) OnFaint(foe);
            }
            if (landed > 1) Add(LogKind.HitCount, att.PokeId, foe.PokeId, moveNo, landed);
            if (!foe.IsFainted) CheckBerry(foe);
            if (foe.IsFainted && foe.DestinyBond && !att.IsFainted) { att.Poke.Hp = 0; Add(LogKind.Damage, att.PokeId, foe.PokeId, moveNo, 0, 0); OnFaint(att); }

            // Verzweifler: Rueckstoss 1/4 der Max-KP; sonst Entzug (positiv) bzw. Rueckstoss (negativ, Steinschaedel verhindert ihn) in Prozent des Schadens.
            if (struggle)
                ApplyRecoil(att, FlowRules.QuotMaxHp(att.Poke.MaxHp, 4));
            else if (rec.DamageRecoverRatio > 0)
            {
                uint drain = Math.Max(1u, total * (uint)rec.DamageRecoverRatio / 100);
                if (att.Poke.Item == 296) drain = BattleMath.MulRatio(drain, 5324);     // Grosse Wurzel
                ApplyDrain(att, foe, drain);
            }
            else if (rec.DamageRecoverRatio < 0 && att.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) != 69)
                ApplyRecoil(att, Math.Max(1u, total * (uint)(-rec.DamageRecoverRatio) / 100));

            // Kontaktfaehigkeiten des Ziels (Statik 9, Giftdorn 38, Flammkoerper 49): 30 % (WAZA_DMG_REACTION).
            if (mi.TouchFlag && total > 0 && !foe.IsFainted && !att.IsFainted)
            {
                ushort ft = (ushort)foe.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE);
                int s = ft == 9 ? Sick.Paralysis : ft == 38 ? Sick.Poison : ft == 49 ? Sick.Burn : 0;
                if (s != 0 && Random.IsOccurPercent(30) && CanInflict(att, s, foe))
                {
                    att.AddSick(s, SickCont.MakePermanent((uint)(foe.PokeId & 0x1F)));
                    Add(LogKind.AbilityActivated, foe.PokeId, att.PokeId, ft);
                    Add(LogKind.SickAdded, att.PokeId, foe.PokeId, s);
                }
            }
            // Item-Wirkungen nach dem Schlag: Lebens-Orb (Rueckstoss 1/10), Muschelglocke (1/8 des Schadens).
            if (total > 0 && !att.IsFainted)
            {
                if (att.Poke.Item == 270) { Add(LogKind.ItemActivated, att.PokeId, id: 270); ApplyRecoil(att, FlowRules.QuotMaxHp(att.Poke.MaxHp, 10)); }
                else if (att.Poke.Item == 253) Recover(att, Math.Max(1u, total / 8), LogKind.Recover);
            }

            // Zusatzwirkungen (WazaAdditionalEffect): Zurueckschrecken, Entzug, Zustand/Statuswert des Ziels, Statuswert des Anwenders.
            if (!foe.IsFainted && rec.FlinchChance > 0 && !foe.Poke.GetTurnFlag(0))
                if (rec.FlinchChance >= 100 || Random.IsOccurPercent((uint)rec.FlinchChance)) foe.Poke.SetTurnFlag(TurnFlagShrink, true);
            if (!foe.IsFainted && rec.Category == Cat.DamageSick && rec.StatusId != 0)
                if (RollChance(rec.StatusChance)) TryInflict(att, foe, rec, rec.StatusId, notifyFailure: false);
            if (!foe.IsFainted && rec.Category == Cat.DamageEffect) ApplyRankEffects(att, foe, rec, onUser: false);
            if (!att.IsFainted && rec.Category == Cat.DamageEffectUser) ApplyRankEffects(att, foe, rec, onUser: true);
        }

        // Wahrscheinlichkeit der Zusatzwirkung; 0 und >= 100 gelten als sicher (kein Zug).
        bool RollChance(int percent)
        {
            if (percent <= 0 || percent >= 100) return true;
            return Random.IsOccurPercent((uint)percent);
        }

        void ApplyRecoil(BattleMon att, uint amount)
        {
            if (att.IsFainted) return;
            amount = Math.Min(amount, att.Poke.Hp);
            att.Poke.Hp = (ushort)(att.Poke.Hp - amount);
            Add(LogKind.Recoil, att.PokeId, value: (int)amount, value2: att.Poke.Hp);
            if (att.IsFainted) OnFaint(att);
        }

        void ApplyDrain(BattleMon att, BattleMon foe, uint amount)
        {
            if (att.IsFainted || att.Poke.IsHpFull) return;
            uint room = (uint)(att.Poke.MaxHp - att.Poke.Hp);
            uint heal = Math.Min(amount, room);
            att.Poke.Hp = (ushort)(att.Poke.Hp + heal);
            Add(LogKind.Drain, att.PokeId, foe.PokeId, value: (int)heal, value2: att.Poke.Hp);
        }

        void ResolveOhko(BattleMon att, BattleMon foe, MoveRecord rec, MoveInfo mi)
        {
            ushort moveNo = (ushort)rec.MoveNo;
            int aff = TypeAffinity.CalcPair(rec.Type, foe.Poke.Type1, foe.Poke.Type2, foe.Poke.TypeEx, Setup.Inverse);
            if (aff == AffinityId.Zero || att.Level < foe.Level || foe.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 5)    // Robustheit (5) blockt K.-o.-Attacken
            {
                Add(LogKind.NoEffect, foe.PokeId, att.PokeId, moveNo);
                return;
            }
            // Gen-8-Regel [P]: Treffer = 30 + (Stufe Anwender - Stufe Ziel) Prozent.
            uint percent = (uint)(rec.Accuracy + att.Level - foe.Level);
            if (!(Random.GetValue(100) < percent))
            {
                Add(LogKind.MoveMissed, att.PokeId, foe.PokeId, moveNo);
                return;
            }
            uint dmg = foe.Poke.Hp;
            foe.Poke.Hp = 0;
            Add(LogKind.Damage, foe.PokeId, att.PokeId, moveNo, (int)dmg, 0);
            OnFaint(foe);
        }

        void ResolveRecover(BattleMon att, MoveRecord rec)
        {
            ushort moveNo = (ushort)rec.MoveNo;
            if (att.Poke.IsHpFull || rec.HpRecoverRatio <= 0)
            {
                Add(LogKind.MoveFailed, att.PokeId, id: moveNo, value: FailCause.NothingHappened);
                return;
            }
            uint amount = Math.Max(1u, (uint)att.Poke.MaxHp * (uint)rec.HpRecoverRatio / 100);
            uint heal = Math.Min(amount, (uint)(att.Poke.MaxHp - att.Poke.Hp));
            att.Poke.Hp = (ushort)(att.Poke.Hp + heal);
            Add(LogKind.Recover, att.PokeId, value: (int)heal, value2: att.Poke.Hp);
        }

        // Status-Attacken (Statuswerte und/oder Zustand), gegen den Gegner oder den Anwender.
        void ResolveStatusMove(BattleMon att, BattleMon foe, MoveRecord rec, MoveInfo mi)
        {
            ushort moveNo = (ushort)rec.MoveNo;
            bool self = TargetsUser(rec);
            var target = self ? att : foe;
            if (!self)
            {
                // Donnerwelle & Co.: Typenimmunitaet gegen Paralyse-Attacken (Gen 6+).
                if (rec.StatusId == Sick.Paralysis && rec.Type != 18 &&
                    TypeAffinity.CalcPair(rec.Type, foe.Poke.Type1, foe.Poke.Type2, foe.Poke.TypeEx, Setup.Inverse) == AffinityId.Zero)
                {
                    Add(LogKind.NoEffect, foe.PokeId, att.PokeId, moveNo);
                    return;
                }
                if (!CheckHit(att, foe, rec, mi))
                {
                    Add(LogKind.MoveMissed, att.PokeId, foe.PokeId, moveNo);
                    return;
                }
            }

            if (rec.Category != Cat.SimpleSick) ApplyRankEffects(att, foe, rec, onUser: self);
            if (rec.Category != Cat.SimpleEffect && rec.StatusId != 0 && !target.IsFainted)
                if (RollChance(rec.StatusChance)) TryInflict(att, target, rec, rec.StatusId, notifyFailure: true);
        }

        // Statuswert-Aenderungen der Attacke (bis zu drei Eintraege, je mit eigener Wahrscheinlichkeit).
        void ApplyRankEffects(BattleMon att, BattleMon foe, MoveRecord rec, bool onUser)
        {
            var target = onUser ? att : foe;
            for (int i = 0; i < 3; i++)
            {
                int stat = rec.StatStageTypes[i];
                int delta = rec.StatStageValues[i];
                if (stat <= 0 || delta == 0) continue;
                if (target.IsFainted) return;
                if (!RollChance(rec.StatStageChances[i])) continue;
                ChangeRank(target, stat, delta, att);
            }
        }

        // 1 Angriff .. 7 Fluchtwert; Stufen liegen im Bereich 0..12 (6 = neutral).
        public void ChangeRank(BattleMon mon, int stat, int delta, BattleMon source = null)
        {
            if (stat < 1 || stat > BattlePoke.RankCount) return;
            // Senkungen durch den Gegner: Weisser Nebel (Seiteneffekt 3), Klärkörper 29, Weißrauch 73, Scherenmacht 52 (Angriff), Adlerauge 51 (Genauigkeit).
            if (delta < 0 && source != null && source.Side != mon.Side)
            {
                ushort ab = (ushort)mon.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE);
                if (Sides[mon.Side].Mist > 0 || ab == 29 || ab == 73 || ab == 52 && stat == 1 || ab == 51 && stat == 6)
                {
                    Add(LogKind.StatChangeBlocked, mon.PokeId, id: stat, value: -1);
                    return;
                }
            }
            var id = (PokeValueId)stat;
            int cur = mon.Poke.GetRank(id);
            int next = Math.Max(0, Math.Min(12, cur + delta));
            if (next == cur)
            {
                Add(LogKind.StatChangeBlocked, mon.PokeId, id: stat, value: delta > 0 ? 1 : -1);
                return;
            }
            mon.Poke.SetRank(id, next);
            Add(LogKind.StatChange, mon.PokeId, id: stat, value: next - cur, value2: next);
        }

        // Section_AddSickCheckFail.checkFail_byBasicRules @0x21dc0a0 (Auswahl): bereits aktiv, Hauptzustand vorhanden, Typenimmunitaeten, Sonne verhindert Frost.
        bool CanInflict(BattleMon target, int sickId, BattleMon cause = null)
        {
            if (target.IsFainted || target.HasSick(sickId)) return false;
            if (sickId < Sick.Confusion && target.PokeSick != 0) return false;
            // Heiligtum (Seiteneffekt 2): schuetzt vor Hauptzustaenden und Verwirrung (IsBasicSickID), ausser eigene Zustaende.
            if (cause != null && cause.Side != target.Side && Sides[target.Side].Safeguard > 0 && sickId >= Sick.Paralysis && sickId <= Sick.Confusion) return false;
            ushort ab = (ushort)target.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE);
            switch (sickId)
            {
                case Sick.Sleep: if (ab == 15 || ab == 72) return false; break;
                case Sick.Paralysis: if (ab == 7) return false; break;
                case Sick.Poison: if (ab == 17) return false; break;
                case Sick.Burn: if (ab == 41) return false; break;
                case Sick.Freeze: if (ab == 40) return false; break;
                case Sick.Confusion: if (ab == 20) return false; break;
            }
            var p = target.Poke;
            bool Has(PokeType t) => p.IsMatchType((int)t);
            switch (sickId)
            {
                case Sick.Freeze:
                    if (Weather.Weather == BattleWeather.Sun || Weather.Weather == BattleWeather.HarshSun) return false;
                    if (Has(PokeType.Ice)) return false;
                    break;
                case Sick.Paralysis:
                    if (Has(PokeType.Electric)) return false;
                    break;
                case Sick.Burn:
                    if (Has(PokeType.Fire)) return false;
                    break;
                case Sick.Poison:
                    if (Has(PokeType.Poison) || Has(PokeType.Steel)) return false;
                    break;
            }
            return true;
        }

        // calc.MakeDefaultPokeSickCont / Attackendaten: Dauerart und Rundenzahl.
        ulong MakeSickCont(BattleMon cause, MoveRecord rec, int sickId)
        {
            uint causeId = (uint)(cause.PokeId & 0x1F);
            if (sickId == Sick.Sleep) return FlowRules.MakeDefaultSickCont(sickId, causeId, false, Random);
            if (sickId == Sick.Poison && rec.StatusTurnMin == 15 && rec.StatusTurnMax == 15) return SickCont.MakeMoudokuCont(causeId);
            switch (rec.StatusContinuation)
            {
                case SickCont.TypeTurn:
                    return SickCont.MakeTurn(causeId, Random.RandRange((uint)rec.StatusTurnMin, (uint)Math.Max(rec.StatusTurnMin, rec.StatusTurnMax)));
                case SickCont.TypePokeTurn:
                    return SickCont.MakePokeTurn(causeId, causeId, Random.RandRange((uint)rec.StatusTurnMin, (uint)Math.Max(rec.StatusTurnMin, rec.StatusTurnMax)));
                default:
                    return FlowRules.MakeDefaultSickCont(sickId, causeId, false, Random);
            }
        }

        bool TryInflict(BattleMon cause, BattleMon target, MoveRecord rec, int sickId, bool notifyFailure)
        {
            if (sickId == Sick.Infatuation && !(cause.Poke.Sex < 2 && target.Poke.Sex < 2 && cause.Poke.Sex != target.Poke.Sex))
            {
                if (notifyFailure) Add(LogKind.SickFailed, target.PokeId, id: sickId);
                return false;
            }
            if (sickId <= 0 || sickId >= Sick.Count || !CanInflict(target, sickId, cause))
            {
                if (notifyFailure) Add(LogKind.SickFailed, target.PokeId, id: sickId);
                return false;
            }
            target.AddSick(sickId, MakeSickCont(cause, rec, sickId));
            Add(LogKind.SickAdded, target.PokeId, cause.PokeId, sickId);
            // Synchro (28): Paralyse, Brand und Gift gehen auf den Verursacher zurueck.
            if (target.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 28 && cause != target && (sickId == Sick.Paralysis || sickId == Sick.Burn || sickId == Sick.Poison)
                && CanInflict(cause, sickId))
            {
                cause.AddSick(sickId, SickCont.MakePermanent((uint)(target.PokeId & 0x1F)));
                Add(LogKind.AbilityActivated, target.PokeId, cause.PokeId, 28);
                Add(LogKind.SickAdded, cause.PokeId, target.PokeId, sickId);
            }
            return true;
        }

        // Section_ChangeWeather: gleiches Wetter schlaegt fehl; Dauer 5 Runden.
        void ChangeWeather(BattleMon cause, ushort moveNo, BattleWeather weather, int turns)
        {
            if (Weather.Weather == weather)
            {
                Add(LogKind.MoveFailed, cause.PokeId, id: moveNo, value: FailCause.NothingHappened);
                return;
            }
            Weather.Weather = weather;
            Weather.TurnMax = turns;
            Weather.Counter = 0;
            Add(LogKind.WeatherStart, cause.PokeId, id: (int)weather, value: turns);
        }
    }
}
