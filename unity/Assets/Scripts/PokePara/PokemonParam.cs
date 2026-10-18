using System;
using System.Collections.Generic;
using Xnu.Battle;
using Xnu.Data;

namespace Xnu.PokePara
{
    // Pml.PokePara.PokemonParam: Kern (CoreParam) plus CalcData (Stufe und Statuswerte, 16 Byte). Das ist der 344-Byte-Slot
    // der Party und der PC-Boxen (SerializedPokemonFull).
    public sealed class PokemonParam
    {
        readonly byte[] _calc = new byte[PokeLayout.CalcSize];

        public PokemonParam() : this(new CoreParam())
        {
        }

        public PokemonParam(CoreParam core)
        {
            Core = core ?? throw new ArgumentNullException(nameof(core));
        }

        public CoreParam Core { get; }

        // Entschlüsselt einen 344-Byte-Slot. Sind die 16 CalcData-Byte im Spielstand alle 0 (leerer Slot oder Pokémon ohne
        // berechnete Werte), gilt HasCalcData = false; sonst werden sie wie der Kern mit personalRnd entschlüsselt.
        public static PokemonParam FromSlot(byte[] src, int offset = 0, bool markBadEggOnMismatch = false)
        {
            if (src == null) throw new ArgumentNullException(nameof(src));
            if (offset < 0 || offset + PokeLayout.SlotSize > src.Length) throw new ArgumentOutOfRangeException(nameof(offset));
            var core = CoreParam.FromEncoded(src, offset, markBadEggOnMismatch);
            var p = new PokemonParam(core);
            int any = 0;
            for (int i = 0; i < PokeLayout.CalcSize; i++) any |= src[offset + PokeLayout.CalcOffset + i];
            if (any != 0)
            {
                Buffer.BlockCopy(src, offset + PokeLayout.CalcOffset, p._calc, 0, PokeLayout.CalcSize);
                PokeEncoder.Decode(p._calc, 0, PokeLayout.CalcSize, core.PersonalRnd);
                p.HasCalcData = true;
            }
            return p;
        }

        // Leerer Slot: Seed 0, alle Felder 0, keine CalcData (so liegen unbelegte Boxplätze im Spielstand).
        public static PokemonParam CreateEmpty() => new PokemonParam();

        // Gibt es berechnete Werte (Stufe, Statuswerte)? Ohne sie steht im kodierten Slot 16-mal 0.
        public bool HasCalcData { get; private set; }

        public void ClearCalcData()
        {
            Array.Clear(_calc, 0, _calc.Length);
            HasCalcData = false;
        }

        public byte[] ToSlot(bool recomputeChecksum = true)
        {
            var slot = new byte[PokeLayout.SlotSize];
            EncodeTo(slot, 0, recomputeChecksum);
            return slot;
        }

        // Accessor.Serialize_FullData @0x25a4410 in umgekehrter Richtung: Kern und CalcData kodiert schreiben.
        public void EncodeTo(byte[] dst, int offset, bool recomputeChecksum = true)
        {
            if (dst == null) throw new ArgumentNullException(nameof(dst));
            if (offset < 0 || offset + PokeLayout.SlotSize > dst.Length) throw new ArgumentOutOfRangeException(nameof(offset));
            Core.EncodeTo(dst, offset, recomputeChecksum);
            if (HasCalcData)
            {
                Buffer.BlockCopy(_calc, 0, dst, offset + PokeLayout.CalcOffset, PokeLayout.CalcSize);
                PokeEncoder.Encode(dst, offset + PokeLayout.CalcOffset, PokeLayout.CalcSize, Core.PersonalRnd);
            }
            else
            {
                Array.Clear(dst, offset + PokeLayout.CalcOffset, PokeLayout.CalcSize);
            }
        }

        public PokemonParam Clone()
        {
            var p = new PokemonParam(Core.Clone()) { HasCalcData = HasCalcData };
            Buffer.BlockCopy(_calc, 0, p._calc, 0, _calc.Length);
            return p;
        }

        public bool ChecksumValid => Core.ChecksumValid;

        public byte[] CalcBytes() => (byte[])_calc.Clone();

        public void SetCalcBytes(byte[] plain)
        {
            if (plain == null || plain.Length != PokeLayout.CalcSize) throw new ArgumentException("CalcData hat 16 Byte", nameof(plain));
            Buffer.BlockCopy(plain, 0, _calc, 0, _calc.Length);
            HasCalcData = true;
        }

        ushort Calc16(int o) => (ushort)(_calc[o] | (_calc[o + 1] << 8));

        void SetCalc16(int o, ushort v)
        {
            HasCalcData = true;
            _calc[o] = (byte)v;
            _calc[o + 1] = (byte)(v >> 8);
        }

        void SetCalc8(int o, byte v)
        {
            HasCalcData = true;
            _calc[o] = v;
        }

        // ---- CalcData -----------------------------------------------------------------------------------------------

        public byte Level { get => _calc[PokeLayout.Calc.Level]; set => SetCalc8(PokeLayout.Calc.Level, value); }

        public ushort MaxHp { get => Calc16(PokeLayout.Calc.MaxHp); set => SetCalc16(PokeLayout.Calc.MaxHp, value); }

        public ushort Atk { get => Calc16(PokeLayout.Calc.Atk); set => SetCalc16(PokeLayout.Calc.Atk, value); }

        public ushort Def { get => Calc16(PokeLayout.Calc.Def); set => SetCalc16(PokeLayout.Calc.Def, value); }

        public ushort Speed { get => Calc16(PokeLayout.Calc.Speed); set => SetCalc16(PokeLayout.Calc.Speed, value); }

        public ushort SpAtk { get => Calc16(PokeLayout.Calc.SpAtk); set => SetCalc16(PokeLayout.Calc.SpAtk, value); }

        public ushort SpDef { get => Calc16(PokeLayout.Calc.SpDef); set => SetCalc16(PokeLayout.Calc.SpDef, value); }

        public byte GState { get => _calc[PokeLayout.Calc.GState]; set => SetCalc8(PokeLayout.Calc.GState, value); }

        // ---- Berechnete Werte ---------------------------------------------------------------------------------------

        public bool IsEmpty => Core.IsEmpty;

        // Farbvariante (Shiny) nach CalcTool.IsRareColor @0x25ad790: Trainer-ID und Farbzufall werden zu einem 16-Bit-Wert verrechnet.
        public static bool IsRareColor(uint trainerId, uint colorRnd)
        {
            return ((trainerId & 0xFFF0) ^ (trainerId >> 16) ^ (colorRnd >> 16) ^ (colorRnd & 0xFFF0)) < 0x10;
        }

        public bool IsRare => IsRareColor(Core.TrainerId, Core.ColorRnd);

        // CalcTool.CalcLevel @0x25ad0e0: größtes Level 1..100 mit exps[Level] <= Erfahrung (exps: 101 Einträge der Wachstumszeile).
        public int LevelFromExp(IReadOnlyList<uint> exps) => GrowthRate.LevelFromExp(exps, Core.Exp);

        // Attacken-Maximum-PP: Grund-PP plus 20 % je PP-Plus (höchstens 3), CoreParam.GetWazaMaxPP @0x21480c0.
        public static int MaxPp(int basePp, int ppUps)
        {
            if (ppUps > 2) ppUps = 3;
            uint basePpU = (uint)basePp & 0xFF;
            return (int)((((uint)ppUps * basePpU * 5 & 0x3FFF) << 2) / 100 + basePpU & 0xFF);
        }

        public StatSpread GetEffectiveIvs() => new StatSpread
        {
            Hp = (int)Core.GetEffectiveIv(StatId.Hp),
            Attack = (int)Core.GetEffectiveIv(StatId.Atk),
            Defense = (int)Core.GetEffectiveIv(StatId.Def),
            SpAttack = (int)Core.GetEffectiveIv(StatId.SpAtk),
            SpDefense = (int)Core.GetEffectiveIv(StatId.SpDef),
            Speed = (int)Core.GetEffectiveIv(StatId.Speed),
        };

        public StatSpread GetEvs() => new StatSpread
        {
            Hp = Core.GetEv(StatId.Hp),
            Attack = Core.GetEv(StatId.Atk),
            Defense = Core.GetEv(StatId.Def),
            SpAttack = Core.GetEv(StatId.SpAtk),
            SpDefense = Core.GetEv(StatId.SpDef),
            Speed = Core.GetEv(StatId.Speed),
        };

        // Statuswerte aus Stammdaten, IV/EV, Stufe und Wesen (CoreParam.Calc*_NotG, Formeln in Xnu.Battle.StatCalculator).
        public BattleStats CalcStats(SpeciesRecord species, int level)
        {
            if (species == null) throw new ArgumentNullException(nameof(species));
            var iv = GetEffectiveIvs();
            var ev = GetEvs();
            int nature = Core.NatureAdjust;
            return new BattleStats
            {
                Hp = StatCalculator.CalcMaxHp(Core.SpeciesNo, level, species.BaseHp, iv.Hp, ev.Hp),
                Attack = StatCalculator.CalcAttack(level, species.BaseAttack, iv.Attack, ev.Attack, nature),
                Defense = StatCalculator.CalcDefense(level, species.BaseDefense, iv.Defense, ev.Defense, nature),
                SpAttack = StatCalculator.CalcSpAttack(level, species.BaseSpAttack, iv.SpAttack, ev.SpAttack, nature),
                SpDefense = StatCalculator.CalcSpDefense(level, species.BaseSpDefense, iv.SpDefense, ev.SpDefense, nature),
                Speed = StatCalculator.CalcSpeed(level, species.BaseSpeed, iv.Speed, ev.Speed, nature),
            };
        }

        // CoreParam.UpdateCalcDatas @0x2144010: Stufe aus der Erfahrung, Statuswerte neu, aktuelle KP um die Änderung der Max-KP
        // verschoben und auf die neuen Max-KP begrenzt. Ist die Kampfunfähigkeit (KP 0) zu erhalten, bleiben die KP unverändert.
        public void RecalculateCalcData(SpeciesRecord species, IReadOnlyList<uint> exps, bool keepFainted = false)
        {
            int level = LevelFromExp(exps);
            Level = (byte)level;
            uint oldMax = MaxHp;
            uint hp = Core.CurrentHp;
            var stats = CalcStats(species, level);
            MaxHp = stats.Hp;
            if (hp != 0 || !keepFainted)
            {
                uint newMax = stats.Hp;
                uint result = newMax;
                if (hp <= newMax) result = hp;
                if (oldMax <= newMax) result = unchecked(hp - oldMax + newMax);
                Core.CurrentHp = unchecked((ushort)result);
            }
            Atk = stats.Attack;
            Def = stats.Defense;
            SpAtk = stats.SpAttack;
            SpDef = stats.SpDefense;
            Speed = stats.Speed;
        }

        // Erfahrungsgrenze der aktuellen/nächsten Stufe (GrowTable.GetMinExp, Stufe über 100 wird auf 100 gesetzt).
        public static uint ExpForLevel(IReadOnlyList<uint> exps, int level) => GrowthRate.MinExp(exps, level);
    }
}
