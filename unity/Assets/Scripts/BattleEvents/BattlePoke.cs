using System;

namespace Xnu.Battle.Events
{
    // BTL_POKEPARAM.ValueID (nur die Werte, die das Ereignissystem und die Handler brauchen).
    public enum PokeValueId
    {
        NULL = 0,
        ATTACK_RANK = 1,
        DEFENCE_RANK = 2,
        SP_ATTACK_RANK = 3,
        SP_DEFENCE_RANK = 4,
        AGILITY_RANK = 5,
        HIT_RATIO = 6,
        AVOID_RATIO = 7,
        ATTACK = 8,
        DEFENCE = 9,
        SP_ATTACK = 10,
        SP_DEFENCE = 11,
        AGILITY = 12,
        HP = 13,
        HP_BEFORE_G = 14,
        MAX_HP = 15,
        MAX_HP_BEFORE_G = 16,
        LEVEL = 17,
        TOKUSEI = 18,
        TOKUSEI_EFFECTIVE = 19,
        SEX = 20,
    }

    // Umgebung des Ereignissystems: alles, was der Aufruf-Code und die Handler ausserhalb des Faktor-Systems abfragen.
    public interface IEventBattleEnv
    {
        // POKECON.GetPokeParam(pokeId); null, wenn es das Pokemon nicht gibt.
        BattlePoke GetPoke(int pokeId);

        // FieldStatus.CheckEffect(effect) (0 Wetter, 1 Bereich der Ordnung, 2 Gravitation, ..., 5 Magieraum, ...).
        bool IsFieldEffectActive(int effect);

        // tables.CheckOmmitAfterHensin / CheckOmmitOnG: Faehigkeiten, die nach Verwandlung bzw. im G-Modus ausgesetzt sind.
        bool OmmitAfterTransform(ushort tokuseiId);
        bool OmmitOnGMode(ushort tokuseiId);

        // calc.ITEM_GetParam(item, 6): der "Angriffswert" des Items (Prozent), Eingabe aus den Spieldaten.
        int GetItemAttackValue(ushort itemId);
    }

    // Kampfwerte eines Pokemon (BTL_POKEPARAM, Spezifikation Abschnitt 6), beschraenkt auf die Teile, die das
    // Ereignissystem und die Handler der Scheibe 2 lesen: Kern-, Basis- und Stufenwerte, Typen, Item/Fahigkeit, Zustaende, Flags.
    public sealed class BattlePoke
    {
        public const int RankCount = 7;           // Angriff, Abwehr, Sp.-Angriff, Sp.-Abwehr, Initiative, Genauigkeit, Fluchtwert
        public const int NeutralRank = 6;         // Stufen liegen im Bereich 0..12 (6 = unveraendert)
        public const int SickCount = 64;
        public const int TurnFlagCount = 27;

        readonly byte[] _rank = { 6, 6, 6, 6, 6, 6, 6 };
        readonly byte[] _sickType = new byte[SickCount];
        readonly bool[] _turnFlags = new bool[TurnFlagCount];

        public BattlePoke(byte id) => Id = id;

        public byte Id { get; }
        public byte Level { get; set; } = 50;
        public ushort Hp { get; set; }
        public ushort MaxHp { get; set; }
        public ushort Item { get; set; }
        public ushort Tokusei { get; set; }

        // Typ-IDs wie PokeType (18 = kein Typ).
        public byte Type1 { get; set; } = 18;
        public byte Type2 { get; set; } = 18;
        public byte TypeEx { get; set; } = 18;

        // Berechnete Kampfwerte ohne Stufen (BASE_PARAM).
        public ushort Attack { get; set; }
        public ushort Defence { get; set; }
        public ushort SpAttack { get; set; }
        public ushort SpDefence { get; set; }
        public ushort Agility { get; set; }

        public bool IsGMode { get; set; }
        public bool IsTransformed { get; set; }

        // Faehigkeit durch das Feld "Chemisches Gas" wirkungslos (IsTokuseiDisabledByKagakuHenkaGas).
        public bool TokuseiDisabledByGas { get; set; }

        public int GetRank(PokeValueId id) => _rank[(int)id - 1];

        public void SetRank(PokeValueId id, int rank) => _rank[(int)id - 1] = (byte)rank;

        // BTL_POKEPARAM.CheckSick: ein Zustand ist aktiv, wenn die unteren 3 Bit seines Dauer-Typs ungleich 0 sind.
        public bool CheckSick(int sickId) => (_sickType[sickId] & 7) != 0;

        public void SetSick(int sickId, byte contType) => _sickType[sickId] = contType;

        public bool GetTurnFlag(int flag) => _turnFlags[flag];

        public void SetTurnFlag(int flag, bool value) => _turnFlags[flag] = value;

        // Basiswert ohne Stufen (GetValue_Base); Treffer-/Fluchtstufen liefern 6.
        public int GetValueBase(PokeValueId id)
        {
            switch (id)
            {
                case PokeValueId.HIT_RATIO:
                case PokeValueId.AVOID_RATIO:
                    return NeutralRank;
                case PokeValueId.ATTACK: return Attack;
                case PokeValueId.DEFENCE: return Defence;
                case PokeValueId.SP_ATTACK: return SpAttack;
                case PokeValueId.SP_DEFENCE: return SpDefence;
                case PokeValueId.AGILITY: return Agility;
                default: return GetValue(id);
            }
        }

        // Wert mit Stufen (GetValue): 1..7 Stufen, 8..12 Kampfwerte nach calc.StatusRank.
        public int GetValue(PokeValueId id)
        {
            switch (id)
            {
                case PokeValueId.ATTACK_RANK:
                case PokeValueId.DEFENCE_RANK:
                case PokeValueId.SP_ATTACK_RANK:
                case PokeValueId.SP_DEFENCE_RANK:
                case PokeValueId.AGILITY_RANK:
                case PokeValueId.HIT_RATIO:
                case PokeValueId.AVOID_RATIO:
                    return _rank[(int)id - 1];
                case PokeValueId.ATTACK: return Ranked(Attack, 0);
                case PokeValueId.DEFENCE: return Ranked(Defence, 1);
                case PokeValueId.SP_ATTACK: return Ranked(SpAttack, 2);
                case PokeValueId.SP_DEFENCE: return Ranked(SpDefence, 3);
                case PokeValueId.AGILITY: return Ranked(Agility, 4);
                case PokeValueId.HP:
                case PokeValueId.HP_BEFORE_G:
                    return Hp;
                case PokeValueId.MAX_HP:
                case PokeValueId.MAX_HP_BEFORE_G:
                    return MaxHp;
                case PokeValueId.LEVEL: return Level;
                case PokeValueId.TOKUSEI: return Tokusei;
                case PokeValueId.TOKUSEI_EFFECTIVE:
                    return CheckSick(WazaSickIds.IEKI) || TokuseiDisabledByGas ? 0 : Tokusei;
                default: return 0;
            }
        }

        // GetValue_Critical: bei einem Volltreffer zaehlen negative Angriffs- und positive Abwehrstufen nicht.
        public int GetValueCritical(PokeValueId id)
        {
            switch (id)
            {
                case PokeValueId.ATTACK:
                case PokeValueId.SP_ATTACK:
                    return _rank[id == PokeValueId.ATTACK ? 0 : 2] > 5 ? GetValue(id) : GetValueBase(id);
                case PokeValueId.DEFENCE:
                case PokeValueId.SP_DEFENCE:
                    return _rank[id == PokeValueId.DEFENCE ? 1 : 3] < 7 ? GetValue(id) : GetValueBase(id);
                default:
                    return GetValue(id);
            }
        }

        // IsMatchType: Typ 18 passt nie; sonst Typ 1, Typ 2 oder Zusatztyp.
        public bool IsMatchType(int type) => type != 18 && (Type1 == type || Type2 == type || TypeEx == type);

        int Ranked(ushort value, int rankIndex) => (int)(BattleMath.StatusRank(value, _rank[rankIndex]) & 0xFFFF);
    }

    // WazaSick-IDs, die das Ereignissystem selbst prueft.
    public static class WazaSickIds
    {
        public const int IEKI = 16;         // Faehigkeit ausser Kraft (Magensaeure)
        public const int MIYABURU = 17;     // Erkennen / Fuchsauge
        public const int SASIOSAE = 19;     // Item gesperrt (Embargo)
        public const int TELEKINESIS = 33;
    }

    public static class TurnFlags
    {
        public const int ItemCantUse = 9;
        public const int HitRatioUp = 14;
    }

    public static class FieldEffects
    {
        public const int Weather = 0;
        public const int TrickRoom = 1;
        public const int Gravity = 2;
        public const int WonderRoom = 4;
        public const int MagicRoom = 5;
    }
}
