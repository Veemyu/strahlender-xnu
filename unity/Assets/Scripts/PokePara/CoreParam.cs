using System;
using System.Text;

namespace Xnu.PokePara
{
    // Werte 0..5 wie PowerID des Originals (Pml.PokePara.PowerID): KP, Angriff, Verteidigung, Sp.-Angriff, Sp.-Verteidigung, Initiative.
    public enum StatId
    {
        Hp = 0,
        Atk = 1,
        Def = 2,
        SpAtk = 3,
        SpDef = 4,
        Speed = 5,
    }

    // Pml.PokePara.CoreParam: der 328-Byte-Kern eines Pokémon (Kopf + vier gemischte Blöcke) im Klartext.
    // Alle Zugriffe folgen den Accessor-Funktionen des Originals (docs/pokepara-spezifikation.md Abschnitt 4).
    public sealed class CoreParam
    {
        readonly byte[] _d = new byte[PokeLayout.CoreSize];

        public CoreParam()
        {
        }

        // Entschlüsselt einen 328-Byte-Kern aus src (Klartextkopf + kodierte Blöcke). Der Kopf bleibt unverändert, auch bei falscher
        // Prüfsumme; markBadEggOnMismatch setzt wie Accessor.DecodeAndCheckIllegalWrite @0x25a42f0 dann das Bad-Egg-Bit.
        public static CoreParam FromEncoded(byte[] src, int offset, bool markBadEggOnMismatch = false)
        {
            if (src == null) throw new ArgumentNullException(nameof(src));
            if (offset < 0 || offset + PokeLayout.CoreSize > src.Length) throw new ArgumentOutOfRangeException(nameof(offset));
            var core = new CoreParam();
            Buffer.BlockCopy(src, offset, core._d, 0, PokeLayout.CoreSize);
            PokeEncoder.Decode(core._d, PokeLayout.EncodedOffset, PokeLayout.EncodedLength, core.PersonalRnd);
            core.ChecksumValid = core.StoredChecksum == core.ComputeChecksum();
            if (!core.ChecksumValid && markBadEggOnMismatch) core.IsBadEgg = true;
            return core;
        }

        public static CoreParam FromPlain(byte[] plain, int offset = 0)
        {
            if (plain == null) throw new ArgumentNullException(nameof(plain));
            if (offset < 0 || offset + PokeLayout.CoreSize > plain.Length) throw new ArgumentOutOfRangeException(nameof(offset));
            var core = new CoreParam();
            Buffer.BlockCopy(plain, offset, core._d, 0, PokeLayout.CoreSize);
            core.ChecksumValid = core.StoredChecksum == core.ComputeChecksum();
            return core;
        }

        public CoreParam Clone()
        {
            var c = new CoreParam { ChecksumValid = ChecksumValid };
            Buffer.BlockCopy(_d, 0, c._d, 0, _d.Length);
            return c;
        }

        // Ergebnis der Prüfung beim Entschlüsseln (Klartext der vier Blöcke gegen die gespeicherte Prüfsumme).
        public bool ChecksumValid { get; private set; } = true;

        public byte[] ToPlain() => (byte[])_d.Clone();

        public ushort ComputeChecksum() => PokeEncoder.Checksum16(_d, PokeLayout.EncodedOffset, PokeLayout.EncodedLength);

        // Schreibt den kodierten Kern; recomputeChecksum entspricht Accessor.UpdateChecksumAndEncode @0x25a3f20 (Normalfall).
        public void EncodeTo(byte[] dst, int offset, bool recomputeChecksum = true)
        {
            if (dst == null) throw new ArgumentNullException(nameof(dst));
            if (offset < 0 || offset + PokeLayout.CoreSize > dst.Length) throw new ArgumentOutOfRangeException(nameof(offset));
            ushort checksum = recomputeChecksum ? ComputeChecksum() : StoredChecksum;
            Buffer.BlockCopy(_d, 0, dst, offset, PokeLayout.CoreSize);
            dst[offset + PokeLayout.ChecksumOffset] = (byte)checksum;
            dst[offset + PokeLayout.ChecksumOffset + 1] = (byte)(checksum >> 8);
            PokeEncoder.Encode(dst, offset + PokeLayout.EncodedOffset, PokeLayout.EncodedLength, PersonalRnd);
        }

        // ---- Rohzugriff ---------------------------------------------------------------------------------------------

        int At(CoreBlock block, int field) => PokeEncoder.BlockOffset(PersonalRnd, block) + field;

        byte U8(CoreBlock b, int f) => _d[At(b, f)];

        void SetU8(CoreBlock b, int f, byte v) => _d[At(b, f)] = v;

        ushort U16(CoreBlock b, int f)
        {
            int o = At(b, f);
            return (ushort)(_d[o] | (_d[o + 1] << 8));
        }

        void SetU16(CoreBlock b, int f, ushort v)
        {
            int o = At(b, f);
            _d[o] = (byte)v;
            _d[o + 1] = (byte)(v >> 8);
        }

        uint U32(CoreBlock b, int f)
        {
            int o = At(b, f);
            return (uint)(_d[o] | (_d[o + 1] << 8) | (_d[o + 2] << 16) | (_d[o + 3] << 24));
        }

        void SetU32(CoreBlock b, int f, uint v)
        {
            int o = At(b, f);
            _d[o] = (byte)v;
            _d[o + 1] = (byte)(v >> 8);
            _d[o + 2] = (byte)(v >> 16);
            _d[o + 3] = (byte)(v >> 24);
        }

        bool Bit8(CoreBlock b, int f, int bit) => (U8(b, f) >> bit & 1) != 0;

        void SetBit8(CoreBlock b, int f, int bit, bool v)
        {
            byte x = U8(b, f);
            SetU8(b, f, (byte)(v ? x | (1 << bit) : x & ~(1 << bit)));
        }

        bool Bit16(CoreBlock b, int f, int bit) => (U16(b, f) >> bit & 1) != 0;

        void SetBit16(CoreBlock b, int f, int bit, bool v)
        {
            ushort x = U16(b, f);
            SetU16(b, f, (ushort)(v ? x | (1 << bit) : x & ~(1 << bit)));
        }

        static void CheckIndex(int index, int count)
        {
            if (index < 0 || index >= count) throw new ArgumentOutOfRangeException(nameof(index));
        }

        string ReadName(CoreBlock b, int f)
        {
            var sb = new StringBuilder();
            int o = At(b, f);
            for (int i = 0; i < PokeLayout.NameChars; i++)
            {
                ushort c = (ushort)(_d[o + 2 * i] | (_d[o + 2 * i + 1] << 8));
                if (c == 0) break;
                sb.Append((char)c);
            }
            return sb.ToString();
        }

        // Accessor.SetNickName @0x25aa1e0 und SetOyaName: höchstens 12 Zeichen, Abschluss und Rest 0.
        void WriteName(CoreBlock b, int f, string value)
        {
            int o = At(b, f);
            int n = 0;
            if (value != null)
            {
                while (n < PokeLayout.MaxNameLength && n < value.Length && value[n] != '\0') n++;
            }
            for (int i = 0; i < PokeLayout.NameChars; i++)
            {
                ushort c = i < n ? value[i] : (ushort)0;
                _d[o + 2 * i] = (byte)c;
                _d[o + 2 * i + 1] = (byte)(c >> 8);
            }
        }

        // ---- Kopf ---------------------------------------------------------------------------------------------------

        public uint PersonalRnd
        {
            get => (uint)(_d[0] | (_d[1] << 8) | (_d[2] << 16) | (_d[3] << 24));
            // Reiner Schreibzugriff wie Accessor.SetPersonalRnd @0x25a85a0: die Blöcke werden NICHT umsortiert, mit geändertem Seed
            // ändert sich also die logische Zuordnung. Zum Umsetzen eines vorhandenen Exemplars dient ReseedPreservingBlocks.
            set
            {
                _d[0] = (byte)value;
                _d[1] = (byte)(value >> 8);
                _d[2] = (byte)(value >> 16);
                _d[3] = (byte)(value >> 24);
            }
        }

        // Setzt einen neuen Seed und ordnet die Blöcke so um, dass alle Felder erhalten bleiben.
        public void ReseedPreservingBlocks(uint newRnd)
        {
            var copy = new byte[PokeLayout.EncodedLength];
            for (int b = 0; b < PokeLayout.BlockCount; b++)
            {
                int from = PokeEncoder.BlockOffset(PersonalRnd, (CoreBlock)b);
                int to = PokeEncoder.BlockOffset(newRnd, (CoreBlock)b) - PokeLayout.HeaderSize;
                Buffer.BlockCopy(_d, from, copy, to, PokeLayout.BlockSize);
            }
            Buffer.BlockCopy(copy, 0, _d, PokeLayout.EncodedOffset, copy.Length);
            PersonalRnd = newRnd;
        }

        public ushort StoredChecksum
        {
            get => (ushort)(_d[PokeLayout.ChecksumOffset] | (_d[PokeLayout.ChecksumOffset + 1] << 8));
            set
            {
                _d[PokeLayout.ChecksumOffset] = (byte)value;
                _d[PokeLayout.ChecksumOffset + 1] = (byte)(value >> 8);
            }
        }

        public ushort HeaderFlags
        {
            get => (ushort)(_d[PokeLayout.HeaderFlagsOffset] | (_d[PokeLayout.HeaderFlagsOffset + 1] << 8));
            set
            {
                _d[PokeLayout.HeaderFlagsOffset] = (byte)value;
                _d[PokeLayout.HeaderFlagsOffset + 1] = (byte)(value >> 8);
            }
        }

        // Kopfbit 2 (fuseiTamagoFlag, "Bad Egg"): das Spiel liefert bei gesetztem Bit Ersatzdaten statt der Blöcke.
        public bool IsBadEgg
        {
            get => (HeaderFlags & 4) != 0;
            set => HeaderFlags = (ushort)(value ? HeaderFlags | 4 : HeaderFlags & ~4);
        }

        // ---- Block A ------------------------------------------------------------------------------------------------

        public ushort SpeciesNo { get => U16(CoreBlock.A, PokeLayout.A.SpeciesNo); set => SetU16(CoreBlock.A, PokeLayout.A.SpeciesNo, value); }

        public bool IsEmpty => SpeciesNo == 0;

        public ushort HeldItem { get => U16(CoreBlock.A, PokeLayout.A.HeldItem); set => SetU16(CoreBlock.A, PokeLayout.A.HeldItem, value); }

        public uint TrainerId { get => U32(CoreBlock.A, PokeLayout.A.TrainerId); set => SetU32(CoreBlock.A, PokeLayout.A.TrainerId, value); }

        public uint Exp { get => U32(CoreBlock.A, PokeLayout.A.Exp); set => SetU32(CoreBlock.A, PokeLayout.A.Exp, value); }

        public ushort Ability { get => U16(CoreBlock.A, PokeLayout.A.Ability); set => SetU16(CoreBlock.A, PokeLayout.A.Ability, value); }

        public bool Ability1Flag { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 0); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 0, value); }

        public bool Ability2Flag { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 1); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 1, value); }

        public bool Ability3Flag { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 2); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 2, value); }

        public bool IsFavorite { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 3); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 3, value); }

        public bool SpecialGFlag { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 4); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 4, value); }

        public bool DebugEditFlag { get => Bit16(CoreBlock.A, PokeLayout.A.FlagsA, 5); set => SetBit16(CoreBlock.A, PokeLayout.A.FlagsA, 5, value); }

        public ushort BoxMark { get => U16(CoreBlock.A, PokeLayout.A.BoxMark); set => SetU16(CoreBlock.A, PokeLayout.A.BoxMark, value); }

        // Zufallswert für Farbvariante (Shiny-Berechnung).
        public uint ColorRnd { get => U32(CoreBlock.A, PokeLayout.A.ColorRnd); set => SetU32(CoreBlock.A, PokeLayout.A.ColorRnd, value); }

        public byte Nature { get => U8(CoreBlock.A, PokeLayout.A.Nature); set => SetU8(CoreBlock.A, PokeLayout.A.Nature, value); }

        // Wesen für die Statuswerte (seikakuHosei); stimmt vom Spielbeginn an mit Nature überein, Minze o. Ä. ändert nur dieses Feld.
        public byte NatureAdjust { get => U8(CoreBlock.A, PokeLayout.A.NatureAdjust); set => SetU8(CoreBlock.A, PokeLayout.A.NatureAdjust, value); }

        public bool IsEventPokemon { get => Bit8(CoreBlock.A, PokeLayout.A.FlagsB, 0); set => SetBit8(CoreBlock.A, PokeLayout.A.FlagsB, 0, value); }

        public bool OfficialBattleEnabled { get => Bit8(CoreBlock.A, PokeLayout.A.FlagsB, 1); set => SetBit8(CoreBlock.A, PokeLayout.A.FlagsB, 1, value); }

        // 0 männlich, 1 weiblich, 2 geschlechtslos (zwei Bit).
        public byte Sex
        {
            get => (byte)(U8(CoreBlock.A, PokeLayout.A.FlagsB) >> 2 & 3);
            set => SetU8(CoreBlock.A, PokeLayout.A.FlagsB, (byte)(U8(CoreBlock.A, PokeLayout.A.FlagsB) & 0xF3 | (value & 3) << 2));
        }

        public ushort FormNo { get => U16(CoreBlock.A, PokeLayout.A.FormNo); set => SetU16(CoreBlock.A, PokeLayout.A.FormNo, value); }

        static int EvOffset(StatId stat)
        {
            switch (stat)
            {
                case StatId.Hp: return PokeLayout.A.EvHp;
                case StatId.Atk: return PokeLayout.A.EvAtk;
                case StatId.Def: return PokeLayout.A.EvDef;
                case StatId.SpAtk: return PokeLayout.A.EvSpAtk;
                case StatId.SpDef: return PokeLayout.A.EvSpDef;
                case StatId.Speed: return PokeLayout.A.EvSpeed;
                default: throw new ArgumentOutOfRangeException(nameof(stat));
            }
        }

        public byte GetEv(StatId stat) => U8(CoreBlock.A, EvOffset(stat));

        public void SetEv(StatId stat, byte value) => SetU8(CoreBlock.A, EvOffset(stat), value);

        // Wettbewerbswerte 0..5: Style, Beautiful, Cute, Clever, Strong, Fur.
        public byte GetContestStat(int index)
        {
            CheckIndex(index, 6);
            return U8(CoreBlock.A, PokeLayout.A.Style + index);
        }

        public void SetContestStat(int index, byte value)
        {
            CheckIndex(index, 6);
            SetU8(CoreBlock.A, PokeLayout.A.Style + index, value);
        }

        public byte Pokerus { get => U8(CoreBlock.A, PokeLayout.A.Pokerus); set => SetU8(CoreBlock.A, PokeLayout.A.Pokerus, value); }

        static int RibbonField(int index, out int bit)
        {
            if (index < 0 || index >= 128) throw new ArgumentOutOfRangeException(nameof(index));
            bit = index & 31;
            switch (index >> 5)
            {
                case 0: return PokeLayout.A.RibbonA;
                case 1: return PokeLayout.A.RibbonB;
                case 2: return PokeLayout.A.RibbonC;
                default: return PokeLayout.A.RibbonD;
            }
        }

        // Band 0..127 (Accessor.HaveRibbon @0x25a5b40: vier 32-Bit-Wörter A, B, C, D).
        public bool HasRibbon(int index)
        {
            int f = RibbonField(index, out int bit);
            return (U32(CoreBlock.A, f) >> bit & 1) != 0;
        }

        public void SetRibbon(int index, bool value)
        {
            int f = RibbonField(index, out int bit);
            uint x = U32(CoreBlock.A, f);
            SetU32(CoreBlock.A, f, value ? x | (1u << bit) : x & ~(1u << bit));
        }

        // Accessor.RemoveAllRibbon @0x25ac250: alle vier Bandwörter und beide Sammelband-Zähler auf 0.
        public void RemoveAllRibbons()
        {
            SetU32(CoreBlock.A, PokeLayout.A.RibbonA, 0);
            SetU32(CoreBlock.A, PokeLayout.A.RibbonB, 0);
            SetU32(CoreBlock.A, PokeLayout.A.RibbonC, 0);
            SetU32(CoreBlock.A, PokeLayout.A.RibbonD, 0);
            SetU8(CoreBlock.A, PokeLayout.A.LumpingRibbonA, 0);
            SetU8(CoreBlock.A, PokeLayout.A.LumpingRibbonB, 0);
        }

        // Sammelband-Zähler 0 und 1.
        public byte GetLumpingRibbon(int index)
        {
            CheckIndex(index, 2);
            return U8(CoreBlock.A, PokeLayout.A.LumpingRibbonA + index);
        }

        public void SetLumpingRibbon(int index, byte value)
        {
            CheckIndex(index, 2);
            SetU8(CoreBlock.A, PokeLayout.A.LumpingRibbonA + index, value);
        }

        public byte CampFriendship { get => U8(CoreBlock.A, PokeLayout.A.CampFriendship); set => SetU8(CoreBlock.A, PokeLayout.A.CampFriendship, value); }

        public byte TalentHeight { get => U8(CoreBlock.A, PokeLayout.A.TalentHeight); set => SetU8(CoreBlock.A, PokeLayout.A.TalentHeight, value); }

        public byte TalentWeight { get => U8(CoreBlock.A, PokeLayout.A.TalentWeight); set => SetU8(CoreBlock.A, PokeLayout.A.TalentWeight, value); }

        public bool DprIllegalFlag { get => Bit8(CoreBlock.A, PokeLayout.A.FlagsD, 0); set => SetBit8(CoreBlock.A, PokeLayout.A.FlagsD, 0, value); }

        // ---- Block B ------------------------------------------------------------------------------------------------

        public string Nickname { get => ReadName(CoreBlock.B, PokeLayout.B.Nickname); set => WriteName(CoreBlock.B, PokeLayout.B.Nickname, value); }

        public ushort GetMove(int slot)
        {
            CheckIndex(slot, 4);
            return U16(CoreBlock.B, PokeLayout.B.Moves + 2 * slot);
        }

        public void SetMove(int slot, ushort move)
        {
            CheckIndex(slot, 4);
            SetU16(CoreBlock.B, PokeLayout.B.Moves + 2 * slot, move);
        }

        public byte GetPp(int slot)
        {
            CheckIndex(slot, 4);
            return U8(CoreBlock.B, PokeLayout.B.Pp + slot);
        }

        public void SetPp(int slot, byte value)
        {
            CheckIndex(slot, 4);
            SetU8(CoreBlock.B, PokeLayout.B.Pp + slot, value);
        }

        public byte GetPpUps(int slot)
        {
            CheckIndex(slot, 4);
            return U8(CoreBlock.B, PokeLayout.B.PpUps + slot);
        }

        public void SetPpUps(int slot, byte value)
        {
            CheckIndex(slot, 4);
            SetU8(CoreBlock.B, PokeLayout.B.PpUps + slot, value);
        }

        public ushort GetEggMove(int slot)
        {
            CheckIndex(slot, 4);
            return U16(CoreBlock.B, PokeLayout.B.EggMoves + 2 * slot);
        }

        public void SetEggMove(int slot, ushort move)
        {
            CheckIndex(slot, 4);
            SetU16(CoreBlock.B, PokeLayout.B.EggMoves + 2 * slot, move);
        }

        public ushort CurrentHp { get => U16(CoreBlock.B, PokeLayout.B.Hp); set => SetU16(CoreBlock.B, PokeLayout.B.Hp, value); }

        public uint IvBits { get => U32(CoreBlock.B, PokeLayout.B.IvBits); set => SetU32(CoreBlock.B, PokeLayout.B.IvBits, value); }

        // Lage der 5-Bit-IV-Felder im Wort IvBits: KP 0, Angriff 5, Verteidigung 10, Initiative 15, Sp.-Angriff 20, Sp.-Verteidigung 25.
        public static int IvShift(StatId stat)
        {
            switch (stat)
            {
                case StatId.Hp: return 0;
                case StatId.Atk: return 5;
                case StatId.Def: return 10;
                case StatId.Speed: return 15;
                case StatId.SpAtk: return 20;
                case StatId.SpDef: return 25;
                default: throw new ArgumentOutOfRangeException(nameof(stat));
            }
        }

        // Gespeicherter IV (0..31), ohne Trainingsflag.
        public uint GetNativeIv(StatId stat) => IvBits >> IvShift(stat) & 0x1F;

        public void SetNativeIv(StatId stat, uint value)
        {
            int s = IvShift(stat);
            IvBits = IvBits & ~(0x1Fu << s) | (value & 0x1F) << s;
        }

        // Für Statuswerte maßgeblicher IV: gesetztes Trainingsflag (Bit = StatId) zählt als 31 (CoreParam.GetTalentPower @0x2144610).
        public uint GetEffectiveIv(StatId stat) => (TrainingFlags >> (int)stat & 1) != 0 ? 31u : GetNativeIv(stat);

        public bool IsEgg { get => (IvBits >> 30 & 1) != 0; set => IvBits = value ? IvBits | 1u << 30 : IvBits & ~(1u << 30); }

        public bool HasNickname { get => (IvBits >> 31 & 1) != 0; set => IvBits = value ? IvBits | 1u << 31 : IvBits & ~(1u << 31); }

        public byte EffortG { get => U8(CoreBlock.B, PokeLayout.B.EffortG); set => SetU8(CoreBlock.B, PokeLayout.B.EffortG, value); }

        public uint Sick { get => U32(CoreBlock.B, PokeLayout.B.Sick); set => SetU32(CoreBlock.B, PokeLayout.B.Sick, value); }

        public uint Palma { get => U32(CoreBlock.B, PokeLayout.B.Palma); set => SetU32(CoreBlock.B, PokeLayout.B.Palma, value); }

        // ---- Block C ------------------------------------------------------------------------------------------------

        public string PastParentsName { get => ReadName(CoreBlock.C, PokeLayout.C.PastParentsName); set => WriteName(CoreBlock.C, PokeLayout.C.PastParentsName, value); }

        public byte PastParentsSex { get => U8(CoreBlock.C, PokeLayout.C.PastParentsSex); set => SetU8(CoreBlock.C, PokeLayout.C.PastParentsSex, value); }

        public byte PastParentsLang { get => U8(CoreBlock.C, PokeLayout.C.PastParentsLang); set => SetU8(CoreBlock.C, PokeLayout.C.PastParentsLang, value); }

        // Ungleich 0: das Pokémon gehört einem anderen Trainer als dem Erstbesitzer; Friendship liest dann OthersFriendship.
        public bool OwnedByOthers
        {
            get => U8(CoreBlock.C, PokeLayout.C.OwnedByOthers) != 0;
            set => SetU8(CoreBlock.C, PokeLayout.C.OwnedByOthers, (byte)(value ? 1 : 0));
        }

        public ushort OthersFriendshipTrainerId { get => U16(CoreBlock.C, PokeLayout.C.OthersFriendshipTrainerId); set => SetU16(CoreBlock.C, PokeLayout.C.OthersFriendshipTrainerId, value); }

        public byte OthersFriendship { get => U8(CoreBlock.C, PokeLayout.C.OthersFriendship); set => SetU8(CoreBlock.C, PokeLayout.C.OthersFriendship, value); }

        public byte OthersMemoriesLevel { get => U8(CoreBlock.C, PokeLayout.C.OthersMemoriesLevel); set => SetU8(CoreBlock.C, PokeLayout.C.OthersMemoriesLevel, value); }

        public byte OthersMemoriesCode { get => U8(CoreBlock.C, PokeLayout.C.OthersMemoriesCode); set => SetU8(CoreBlock.C, PokeLayout.C.OthersMemoriesCode, value); }

        public byte OthersMemoriesFeel { get => U8(CoreBlock.C, PokeLayout.C.OthersMemoriesFeel); set => SetU8(CoreBlock.C, PokeLayout.C.OthersMemoriesFeel, value); }

        public ushort OthersMemoriesData { get => U16(CoreBlock.C, PokeLayout.C.OthersMemoriesData); set => SetU16(CoreBlock.C, PokeLayout.C.OthersMemoriesData, value); }

        // Bitfeld 0..111 (14 Byte).
        public bool GetPokeJobFlag(int index)
        {
            CheckIndex(index, 0x70);
            return (U8(CoreBlock.C, PokeLayout.C.PokeJob + (index >> 3)) >> (index & 7) & 1) != 0;
        }

        public void SetPokeJobFlag(int index, bool value)
        {
            CheckIndex(index, 0x70);
            SetBit8(CoreBlock.C, PokeLayout.C.PokeJob + (index >> 3), index & 7, value);
        }

        public void ClearPokeJobFlags()
        {
            for (int i = 0; i < 14; i++) SetU8(CoreBlock.C, PokeLayout.C.PokeJob + i, 0);
        }

        public byte Enjoy { get => U8(CoreBlock.C, PokeLayout.C.Enjoy); set => SetU8(CoreBlock.C, PokeLayout.C.Enjoy, value); }

        public byte NadeNadeValue { get => U8(CoreBlock.C, PokeLayout.C.NadeNade); set => SetU8(CoreBlock.C, PokeLayout.C.NadeNade, value); }

        public byte CassetteVersion { get => U8(CoreBlock.C, PokeLayout.C.CassetteVersion); set => SetU8(CoreBlock.C, PokeLayout.C.CassetteVersion, value); }

        public byte BattleRomMark { get => U8(CoreBlock.C, PokeLayout.C.BattleRomMark); set => SetU8(CoreBlock.C, PokeLayout.C.BattleRomMark, value); }

        public byte LangId { get => U8(CoreBlock.C, PokeLayout.C.LangId); set => SetU8(CoreBlock.C, PokeLayout.C.LangId, value); }

        public uint MultiWork { get => U32(CoreBlock.C, PokeLayout.C.MultiWork); set => SetU32(CoreBlock.C, PokeLayout.C.MultiWork, value); }

        public byte EquipRibbon { get => U8(CoreBlock.C, PokeLayout.C.EquipRibbon); set => SetU8(CoreBlock.C, PokeLayout.C.EquipRibbon, value); }

        // ---- Block D ------------------------------------------------------------------------------------------------

        public string TrainerName { get => ReadName(CoreBlock.D, PokeLayout.D.TrainerName); set => WriteName(CoreBlock.D, PokeLayout.D.TrainerName, value); }

        // Freundschaft zum Erstbesitzer (Accessor.GetOriginalFriendship).
        public byte OriginalFriendship { get => U8(CoreBlock.D, PokeLayout.D.Friendship); set => SetU8(CoreBlock.D, PokeLayout.D.Friendship, value); }

        // Wirksame Freundschaft: beim Fremdbesitzer OthersFriendship, sonst OriginalFriendship (Accessor.GetFriendship @0x25a5030).
        public byte Friendship
        {
            get => OwnedByOthers ? OthersFriendship : OriginalFriendship;
            set
            {
                if (OwnedByOthers) OthersFriendship = value;
                else OriginalFriendship = value;
            }
        }

        public byte MemoriesLevel { get => U8(CoreBlock.D, PokeLayout.D.MemoriesLevel); set => SetU8(CoreBlock.D, PokeLayout.D.MemoriesLevel, value); }

        public byte MemoriesCode { get => U8(CoreBlock.D, PokeLayout.D.MemoriesCode); set => SetU8(CoreBlock.D, PokeLayout.D.MemoriesCode, value); }

        public ushort MemoriesData { get => U16(CoreBlock.D, PokeLayout.D.MemoriesData); set => SetU16(CoreBlock.D, PokeLayout.D.MemoriesData, value); }

        public byte MemoriesFeel { get => U8(CoreBlock.D, PokeLayout.D.MemoriesFeel); set => SetU8(CoreBlock.D, PokeLayout.D.MemoriesFeel, value); }

        public byte EggYear { get => U8(CoreBlock.D, PokeLayout.D.EggYear); set => SetU8(CoreBlock.D, PokeLayout.D.EggYear, value); }

        public byte EggMonth { get => U8(CoreBlock.D, PokeLayout.D.EggMonth); set => SetU8(CoreBlock.D, PokeLayout.D.EggMonth, value); }

        public byte EggDay { get => U8(CoreBlock.D, PokeLayout.D.EggDay); set => SetU8(CoreBlock.D, PokeLayout.D.EggDay, value); }

        public byte MetYear { get => U8(CoreBlock.D, PokeLayout.D.MetYear); set => SetU8(CoreBlock.D, PokeLayout.D.MetYear, value); }

        public byte MetMonth { get => U8(CoreBlock.D, PokeLayout.D.MetMonth); set => SetU8(CoreBlock.D, PokeLayout.D.MetMonth, value); }

        public byte MetDay { get => U8(CoreBlock.D, PokeLayout.D.MetDay); set => SetU8(CoreBlock.D, PokeLayout.D.MetDay, value); }

        public ushort EggPlace { get => U16(CoreBlock.D, PokeLayout.D.EggPlace); set => SetU16(CoreBlock.D, PokeLayout.D.EggPlace, value); }

        public ushort MetPlace { get => U16(CoreBlock.D, PokeLayout.D.MetPlace); set => SetU16(CoreBlock.D, PokeLayout.D.MetPlace, value); }

        public byte Ball { get => U8(CoreBlock.D, PokeLayout.D.Ball); set => SetU8(CoreBlock.D, PokeLayout.D.Ball, value); }

        // Stufe beim Fang (7 Bit).
        public byte MetLevel
        {
            get => (byte)(U8(CoreBlock.D, PokeLayout.D.LevelAndSex) & 0x7F);
            set => SetU8(CoreBlock.D, PokeLayout.D.LevelAndSex, (byte)(U8(CoreBlock.D, PokeLayout.D.LevelAndSex) & 0x80 | value & 0x7F));
        }

        // Geschlecht des Trainers (Bit 7 von LevelAndSex).
        public byte TrainerSex
        {
            get => (byte)(U8(CoreBlock.D, PokeLayout.D.LevelAndSex) >> 7);
            set => SetU8(CoreBlock.D, PokeLayout.D.LevelAndSex, (byte)(U8(CoreBlock.D, PokeLayout.D.LevelAndSex) & 0x7F | value << 7));
        }

        // Bit i (i = StatId) gesetzt: der IV dieses Werts zählt als 31.
        public byte TrainingFlags { get => U8(CoreBlock.D, PokeLayout.D.TrainingFlags); set => SetU8(CoreBlock.D, PokeLayout.D.TrainingFlags, value); }

        // Attacken-Lernbits 0..111 (14 Byte).
        public bool GetMoveRecordFlag(int index)
        {
            CheckIndex(index, 0x70);
            return (U8(CoreBlock.D, PokeLayout.D.MoveRecord + (index >> 3)) >> (index & 7) & 1) != 0;
        }

        public void SetMoveRecordFlag(int index, bool value)
        {
            CheckIndex(index, 0x70);
            SetBit8(CoreBlock.D, PokeLayout.D.MoveRecord + (index >> 3), index & 7, value);
        }

        public void ClearMoveRecordFlags()
        {
            for (int i = 0; i < 14; i++) SetU8(CoreBlock.D, PokeLayout.D.MoveRecord + i, 0);
        }

        public ulong BankUniqueId
        {
            get
            {
                ulong v = 0;
                int o = At(CoreBlock.D, PokeLayout.D.BankUniqueId);
                for (int i = 7; i >= 0; i--) v = v << 8 | _d[o + i];
                return v;
            }
            set
            {
                int o = At(CoreBlock.D, PokeLayout.D.BankUniqueId);
                for (int i = 0; i < 8; i++) _d[o + i] = (byte)(value >> (8 * i));
            }
        }

        public void ClearBankUniqueId() => BankUniqueId = 0;
    }
}
