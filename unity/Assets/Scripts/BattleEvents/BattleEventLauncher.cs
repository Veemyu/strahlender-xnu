using System;

namespace Xnu.Battle.Events
{
    // Die Teile der Attackendaten (WazaParam), die die Ereignisse als Variablen weitergeben.
    public sealed class MoveInfo
    {
        public ushort WazaId { get; set; }
        public byte Type { get; set; }

        // WazaDamageType: 0 keiner, 1 physisch, 2 speziell.
        public int DamageType { get; set; }
        public bool TouchFlag { get; set; }
        public int Priority { get; set; }

        // Grundkraft (WazaParam +0x30) und Genauigkeit (WAZADATA.GetHitPer) aus den Attackendaten.
        public ushort Power { get; set; }
        public uint HitPercent { get; set; }
    }

    // Aufruf-Code des Kampfes (EventLauncher, Spezifikation Abschnitt 4.4): schnuert je Rechenschritt einen Variablenrahmen,
    // ruft das Ereignis und liest die Ergebnisse. Die Ergebnisse speisen die Rechner aus Xnu.Battle (Schaden, Treffer).
    public sealed class BattleEventLauncher
    {
        readonly EventSystem _es;
        readonly IEventBattleEnv _env;

        public BattleEventLauncher(EventSystem es)
        {
            _es = es;
            _env = es.Env;
        }

        void PushPair(BattlePoke attacker, BattlePoke defender)
        {
            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, attacker.Id);
            _es.SetConstValue(EventVarLabel.POKEID_DEF, defender.Id);
        }

        // Event_getWazaPower @0x1e14e20: Grundkraft darf umgeschrieben werden (0x45), danach Verhaeltnis (0x46).
        public uint GetWazaPower(BattlePoke attacker, BattlePoke defender, MoveInfo move)
        {
            PushPair(attacker, defender);
            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetConstValue(EventVarLabel.WAZA_TYPE, move.Type);
            _es.SetConstValue(EventVarLabel.DAMAGE_TYPE, move.DamageType);
            _es.SetConstValue(EventVarLabel.WAZA_TOUCH_FLAG, move.TouchFlag ? 1 : 0);
            _es.SetRewriteOnceValue(EventVarLabel.TEMPT_TARGET_PRIORITY, 0);
            _es.SetRewriteOnceValue(EventVarLabel.TEMPT_TARGET_CAUSE, 0);
            _es.SetRewriteOnceValue(EventVarLabel.WAZA_POWER, move.Power);
            _es.CallEvent(EventId.WAZA_POWER_BASE);
            _es.SetMulValue(EventVarLabel.WAZA_POWER_RATIO, 0x1000, 0x29, 0x200000);
            _es.CallEvent(EventId.WAZA_POWER);
            uint power = (ushort)_es.GetValue(EventVarLabel.WAZA_POWER);
            uint ratio = (uint)_es.GetValue(EventVarLabel.WAZA_POWER_RATIO);
            _es.VarPop();
            return BattleMath.MulRatio(power, ratio);
        }

        // Event_getAttackPower @0x1e15010. Rahmen 1 bleibt bis zum Schluss offen; Ereignis 0x47 darf das Pokemon wechseln, dessen
        // Wert zaehlt, und das Ignorieren der Stufen erzwingen; in einem inneren Rahmen darf 0x49 die Wertart aendern; 0x4A
        // liefert das Verhaeltnis.
        public uint GetAttackPower(BattlePoke attacker, BattlePoke defender, MoveInfo move, bool critical, out bool ignoreBurn)
        {
            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, attacker.Id);
            _es.SetConstValue(EventVarLabel.POKEID_DEF, defender.Id);
            _es.SetValue(EventVarLabel.SWAP_POKEID, 0x1F);
            _es.SetValue(EventVarLabel.GEN_FLAG, 0);
            _es.CallEvent(EventId.ATTACKER_POWER_PREV);
            int ignoreRanks = _es.GetValue(EventVarLabel.GEN_FLAG);
            byte swap = (byte)_es.GetValue(EventVarLabel.SWAP_POKEID);
            var source = swap != 0x1F ? _env.GetPoke(swap) : attacker;

            int vid = move.DamageType != 2 ? (int)PokeValueId.ATTACK : (int)PokeValueId.SP_ATTACK;
            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, source.Id);
            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetRewriteOnceValue(EventVarLabel.VID, vid);
            _es.CallEvent(EventId.ATTACKER_POWER_VID);
            vid = _es.GetValue(EventVarLabel.VID);
            _es.VarPop();

            var valueId = (PokeValueId)vid;
            int stat;
            if (ignoreRanks == 0)
            {
                bool useBase = false;
                if (critical)
                {
                    int rankIndex = valueId == PokeValueId.ATTACK ? 1 : valueId == PokeValueId.DEFENCE ? 2 : valueId == PokeValueId.SP_ATTACK ? 3 : valueId == PokeValueId.SP_DEFENCE ? 4 : 0;
                    if (rankIndex != 0 && source.GetValue((PokeValueId)rankIndex) < 6) useBase = true;
                }
                stat = useBase ? source.GetValueBase(valueId) : source.GetValue(valueId);
            }
            else stat = source.GetValueBase(valueId);

            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetConstValue(EventVarLabel.WAZA_TYPE, move.Type);
            _es.SetConstValue(EventVarLabel.DAMAGE_TYPE, move.DamageType);
            _es.SetValue(EventVarLabel.POWER, (ushort)stat);
            _es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x19A, 0x20000);
            _es.SetRewriteOnceValue(EventVarLabel.DISABLE_YAKEDO_FLAG, 0);
            _es.CallEvent(EventId.ATTACKER_POWER);
            uint power = (ushort)_es.GetValue(EventVarLabel.POWER);
            uint ratio = (uint)_es.GetValue(EventVarLabel.RATIO);
            ignoreBurn = _es.GetValue(EventVarLabel.DISABLE_YAKEDO_FLAG) != 0;
            _es.VarPop();
            return BattleMath.MulRatio(power, ratio);
        }

        // Event_getDefenderGuard @0x1e153d0 (Sandsturm: Gestein-Ziel bekommt x1,5 auf die Sp.-Abwehr).
        public uint GetDefenderGuard(BattlePoke attacker, BattlePoke defender, MoveInfo move, bool critical, BattleWeather weather)
        {
            int damageType = move.DamageType;
            int vidDefault = damageType != 2 ? (int)PokeValueId.DEFENCE : (int)PokeValueId.SP_DEFENCE;
            int vidSwapped = damageType != 2 ? (int)PokeValueId.SP_DEFENCE : (int)PokeValueId.DEFENCE;
            int typeSwapped = damageType != 2 ? 2 : 1;

            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, attacker.Id);
            _es.SetConstValue(EventVarLabel.POKEID_DEF, defender.Id);
            _es.SetConstValue(EventVarLabel.VID, vidDefault);
            _es.SetValue(EventVarLabel.VID_SWAP_CNT, 0);
            _es.SetRewriteOnceValue(EventVarLabel.GEN_FLAG, 0);
            _es.CallEvent(EventId.DEFENDER_GUARD_PREV);
            int ignoreRanks = _es.GetValue(EventVarLabel.GEN_FLAG);
            bool swapped = (_es.GetValue(EventVarLabel.VID_SWAP_CNT) & 1) != 0;
            _es.VarPop();

            int vid = swapped ? vidSwapped : vidDefault;
            int effectiveDamageType = swapped ? typeSwapped : damageType;
            var valueId = (PokeValueId)vid;
            int stat;
            if (ignoreRanks != 0) stat = defender.GetValueBase(valueId);
            else if (!critical) stat = defender.GetValue(valueId);
            else stat = defender.GetValueCritical(valueId);
            if (weather == BattleWeather.Sandstorm && defender.IsMatchType((int)PokeType.Rock) && vid == (int)PokeValueId.SP_DEFENCE)
                stat = (ushort)BattleMath.MulRatio((uint)stat, 0x1800);

            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, attacker.Id);
            _es.SetConstValue(EventVarLabel.POKEID_DEF, defender.Id);
            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetConstValue(EventVarLabel.WAZA_TYPE, move.Type);
            _es.SetConstValue(EventVarLabel.DAMAGE_TYPE, effectiveDamageType);
            _es.SetValue(EventVarLabel.GUARD, (ushort)stat);
            _es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x19A, 0x20000);
            _es.CallEvent(EventId.DEFENDER_GUARD);
            uint guard = (ushort)_es.GetValue(EventVarLabel.GUARD);
            uint ratio = (uint)_es.GetValue(EventVarLabel.RATIO);
            _es.VarPop();
            return BattleMath.MulRatio(guard, ratio);
        }

        // Event_CalcTypeMatchRatio @0x1e15740: Standard 0x1800 bei passendem Typ, sonst 0x1000; Handler duerfen es aendern.
        public uint CalcTypeMatchRatio(BattlePoke attacker, int moveType)
        {
            bool match = attacker.IsMatchType(moveType);
            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID, attacker.Id);
            _es.SetRewriteOnceValue(EventVarLabel.GEN_FLAG, match ? 1 : 0);
            _es.CallEvent(EventId.TYPEMATCH_CHECK);
            int matched = _es.GetValue(EventVarLabel.GEN_FLAG);
            _es.SetConstValue(EventVarLabel.KINOMI_FLAG, matched != 0 ? 1 : 0);
            _es.SetValue(EventVarLabel.RATIO, matched != 0 ? 0x1800 : 0x1000);
            _es.CallEvent(EventId.TYPEMATCH_RATIO);
            uint ratio = (uint)_es.GetValue(EventVarLabel.RATIO);
            _es.VarPop();
            return ratio;
        }

        // Event_getHitPer @0x1e16a30 (Ereignis 0x40 fuer normale Attacken): Genauigkeit x Handler-Verhaeltnis.
        public uint GetHitPer(EventId eventId, BattlePoke attacker, BattlePoke defender, MoveInfo move)
        {
            _es.VarPush();
            _es.SetConstValue(EventVarLabel.POKEID_ATK, attacker.Id);
            _es.SetConstValue(EventVarLabel.POKEID_DEF, defender.Id);
            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetConstValue(EventVarLabel.DAMAGE_TYPE, move.DamageType);
            _es.SetRewriteOnceValue(EventVarLabel.HIT_PER, (ushort)move.HitPercent);
            _es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x19A, 0x20000);
            _es.CallEvent(eventId);
            uint hit = (uint)_es.GetValue(EventVarLabel.HIT_PER);
            uint ratio = (uint)_es.GetValue(EventVarLabel.RATIO);
            _es.VarPop();
            return BattleMath.MulRatio(hit, ratio);
        }

        // Teil von Event_CheckHit @0x1e19350 hinter den Sofort-Treffern: Genauigkeit nach Ereignis 0x40, Stufen und Verhaeltnis nach 0x3F.
        public HitInput BuildHitInput(BattlePoke attacker, BattlePoke defender, MoveInfo move)
        {
            uint percent = GetHitPer(EventId.WAZA_HIT_RATIO, attacker, defender, move);
            PushPair(attacker, defender);
            _es.SetRewriteOnceValue(EventVarLabel.FLAT_FLAG, 0);
            _es.SetValue(EventVarLabel.HIT_RANK, attacker.GetValue(PokeValueId.HIT_RATIO));
            _es.SetValue(EventVarLabel.AVOID_RANK, defender.GetValue(PokeValueId.AVOID_RATIO));
            _es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x29, 0x20000);
            _es.CallEvent(EventId.WAZA_HIT_RANK);
            int acc = (sbyte)_es.GetValue(EventVarLabel.HIT_RANK);
            int eva = (sbyte)_es.GetValue(EventVarLabel.AVOID_RANK);
            int flat = _es.GetValue(EventVarLabel.FLAT_FLAG);
            int ratio = _es.GetValue(EventVarLabel.RATIO);
            _es.VarPop();
            return new HitInput
            {
                HitPercent = percent,
                AccuracyStage = acc,
                EvasionStage = eva,
                IgnoreEvasion = flat != 0,
                TargetIdentified = defender.CheckSick(WazaSickIds.MIYABURU),
                HandlerRatio = ratio,
                AttackerTurnBoost = attacker.GetTurnFlag(TurnFlags.HitRatioUp),
                TargetTelekinesis = defender.CheckSick(WazaSickIds.TELEKINESIS),
            };
        }

        // Endfaktor der Schadensstufe (Ereignis 0x5A, Variable 0x38 ab 0x1000, Grenzen [0x29, 0x20000]).
        public uint GetFinalDamageRatio(BattlePoke attacker, BattlePoke defender, MoveInfo move, int affinityId, bool critical, bool migawari, uint damageBefore)
        {
            PushPair(attacker, defender);
            _es.SetConstValue(EventVarLabel.TYPEAFF, affinityId);
            _es.SetConstValue(EventVarLabel.CRITICAL_FLAG, critical ? 1 : 0);
            _es.SetConstValue(EventVarLabel.WAZA_TYPE, move.Type);
            _es.SetConstValue(EventVarLabel.WAZAID, move.WazaId);
            _es.SetConstValue(EventVarLabel.WAZA_TOUCH_FLAG, move.TouchFlag ? 1 : 0);
            _es.SetConstValue(EventVarLabel.DAMAGE_TYPE, move.DamageType);
            _es.SetConstValue(EventVarLabel.WAZA_PRI, move.Priority);
            _es.SetConstValue(EventVarLabel.MIGAWARI_FLAG, migawari ? 1 : 0);
            _es.SetMulValue(EventVarLabel.RATIO, 0x1000, 0x29, 0x20000);
            _es.SetValue(EventVarLabel.DAMAGE, (int)damageBefore);
            _es.SetRewriteOnceValue(EventVarLabel.WALL_EFFECT_FLAG_PHYSIC, 0);
            _es.SetRewriteOnceValue(EventVarLabel.WALL_EFFECT_FLAG_SPECIAL, 0);
            _es.CallEvent(EventId.WAZA_DMG_PROC3);
            uint ratio = (uint)_es.GetValue(EventVarLabel.RATIO);
            _es.VarPop();
            return ratio;
        }

        // Alle Eingaben der Schadensformel aus dem Ereignissystem (Kraft, Angriff, Abwehr, STAB, Endfaktor).
        public DamageInput BuildDamageInput(BattlePoke attacker, BattlePoke defender, MoveInfo move, bool critical, int affinityId,
            BattleWeather weather, bool attackerBurned, bool migawari = false, uint targetRatio = 0x1000)
        {
            uint power = GetWazaPower(attacker, defender, move);
            uint attack = GetAttackPower(attacker, defender, move, critical, out bool ignoreBurn);
            uint defense = GetDefenderGuard(attacker, defender, move, critical, weather);
            uint stab = CalcTypeMatchRatio(attacker, move.Type);
            return new DamageInput
            {
                Power = power,
                Attack = attack,
                Defense = defense,
                Level = attacker.Level,
                TargetRatio = targetRatio,
                Weather = weather,
                MoveType = move.Type,
                Category = (DamageCategory)move.DamageType,
                IsCritical = critical,
                Affinity = affinityId,
                StabRatio = stab,
                AttackerBurned = attackerBurned,
                IgnoreBurn = ignoreBurn,
                FinalRatioFunc = dmg => GetFinalDamageRatio(attacker, defender, move, affinityId, critical, migawari, dmg),
            };
        }
    }
}
