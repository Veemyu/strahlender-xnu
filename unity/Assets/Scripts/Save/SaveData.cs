using System;
using System.Text;

namespace Xnu.Save
{
    // Ein Eintrag aus saveItem[] (nativ 16 Byte).
    public readonly struct SaveItemEntry
    {
        public int Count { get; }
        public bool VanishNew { get; }
        public bool Favorite { get; }
        public bool ShowWazaName { get; }
        public ushort SortNumber { get; }

        public SaveItemEntry(int count, bool vanishNew, bool favorite, bool showWazaName, ushort sortNumber)
        {
            Count = count;
            VanishNew = vanishNew;
            Favorite = favorite;
            ShowWazaName = showWazaName;
            SortNumber = sortNumber;
        }
    }

    // Veränderbarer Spielstand (Version 0x34) auf dem Marshal-Abbild. Änderungen betreffen nur die jeweils benannten Bytes;
    // der Hash wird erst in ToBytes/Seal neu berechnet. Pokémon-Zugriff: Erweiterungen in Xnu.PokePara (SaveDataPokemonExtensions).
    public sealed class SaveData
    {
        readonly byte[] _buf;

        SaveData(byte[] buf)
        {
            _buf = buf;
        }

        // Kopiert data. Prüft Version (nur 0x34 ist bearbeitbar), Größe und – wenn verifyHash – den MD5.
        public static SaveData FromBytes(byte[] data, bool verifyHash = true)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            var header = SaveValidator.ReadHeader(data);
            if (header.Version != SaveLayout.CurrentVersion)
                throw new SaveFormatException(string.Format(
                    "Version 0x{0:X} nicht bearbeitbar (nur 0x{1:X})", (uint)header.Version, SaveLayout.CurrentVersion));
            if (data.Length != SaveLayout.TotalSize)
                throw new SaveFormatException(string.Format(
                    "Größe {0} statt {1} (0x{1:X})", data.Length, SaveLayout.TotalSize));
            if (verifyHash && SaveValidator.VerifyHash(data) != true)
                throw new SaveFormatException("MD5 stimmt nicht");
            return new SaveData((byte[])data.Clone());
        }

        public static bool TryFromBytes(byte[] data, out SaveData save, bool verifyHash = true)
        {
            try
            {
                save = FromBytes(data, verifyHash);
                return true;
            }
            catch (SaveFormatException)
            {
                save = null;
                return false;
            }
        }

        public int Version => ReadInt32(SaveLayout.VersionOffset);

        // Direkter Zugriff auf das Abbild (für Erweiterungen wie PokeSaveSlots); der Hash ist dann ggf. veraltet.
        public byte[] Buffer => _buf;

        public bool IsHashValid => SaveValidator.VerifyHash(_buf) == true;

        // Setzt den Hash im Abbild neu.
        public void Seal()
        {
            var hash = SaveValidator.ComputeHash(_buf, SaveLayout.CurrentVersion);
            System.Buffer.BlockCopy(hash, 0, _buf, SaveLayout.HashOffset, SaveLayout.HashLength);
        }

        // Kopie des Abbilds mit frisch berechnetem Hash; das Objekt bleibt unverändert.
        public byte[] ToBytes() => SaveWriter.FixHash(_buf);

        public SaveData Clone() => new SaveData((byte[])_buf.Clone());

        // ---- Spieler-Basisdaten (PLAYER_DATA) ----

        public string PlayerName
        {
            get => ReadName(SavePlayerLayout.PlayerDataOffset + SavePlayerLayout.NameOffset, SavePlayerLayout.NameChars);
            set => WriteName(SavePlayerLayout.PlayerDataOffset + SavePlayerLayout.NameOffset, SavePlayerLayout.NameChars,
                SavePlayerLayout.MaxNameLength, value);
        }

        public uint TrainerId
        {
            get => (uint)ReadInt32(PlayerAt(SavePlayerLayout.TrainerIdOffset));
            set => WriteInt32(PlayerAt(SavePlayerLayout.TrainerIdOffset), (int)value);
        }

        // Geld in 0..999999 (MoneyWork.MAX_MOENY).
        public int Money
        {
            get => ReadInt32(PlayerAt(SavePlayerLayout.MoneyOffset));
            set
            {
                if (value < 0 || value > SavePlayerLayout.MaxMoney)
                    throw new ArgumentOutOfRangeException(nameof(value), "Geld muss in 0..999999 liegen");
                WriteInt32(PlayerAt(SavePlayerLayout.MoneyOffset), value);
            }
        }

        // MYSTATUS.sex als Rohwert (bool im Original; Zuordnung zu Geschlecht nicht belegt).
        public int SexRaw
        {
            get => ReadInt32(PlayerAt(SavePlayerLayout.SexOffset));
            set
            {
                if (value != 0 && value != 1) throw new ArgumentOutOfRangeException(nameof(value));
                WriteInt32(PlayerAt(SavePlayerLayout.SexOffset), value);
            }
        }

        public byte BadgeRaw
        {
            get => _buf[PlayerAt(SavePlayerLayout.BadgeOffset)];
            set => _buf[PlayerAt(SavePlayerLayout.BadgeOffset)] = value;
        }

        public int PlayHours
        {
            get => ReadUInt16(PlayerAt(SavePlayerLayout.PlayHoursOffset));
            set
            {
                if (value < 0 || value > ushort.MaxValue) throw new ArgumentOutOfRangeException(nameof(value));
                WriteUInt16(PlayerAt(SavePlayerLayout.PlayHoursOffset), value);
            }
        }

        public int PlayMinutes
        {
            get => _buf[PlayerAt(SavePlayerLayout.PlayMinutesOffset)];
            set
            {
                if (value < 0 || value > 59) throw new ArgumentOutOfRangeException(nameof(value));
                _buf[PlayerAt(SavePlayerLayout.PlayMinutesOffset)] = (byte)value;
            }
        }

        public int PlaySeconds
        {
            get => _buf[PlayerAt(SavePlayerLayout.PlaySecondsOffset)];
            set
            {
                if (value < 0 || value > 59) throw new ArgumentOutOfRangeException(nameof(value));
                _buf[PlayerAt(SavePlayerLayout.PlaySecondsOffset)] = (byte)value;
            }
        }

        public string RivalName
        {
            get => ReadName(SavePlayerLayout.RivalNameOffset, SavePlayerLayout.RivalNameChars);
            set => WriteName(SavePlayerLayout.RivalNameOffset, SavePlayerLayout.RivalNameChars,
                SavePlayerLayout.MaxNameLength, value);
        }

        // ---- Items (saveItem[3000], Index = Item-Nummer) ----

        public SaveItemEntry GetItem(int itemNo)
        {
            var o = ItemAt(itemNo);
            return new SaveItemEntry(
                ReadInt32(o + SavePlayerLayout.ItemCountOffset),
                _buf[o + SavePlayerLayout.ItemVanishNewOffset] != 0,
                _buf[o + SavePlayerLayout.ItemFavoriteOffset] != 0,
                _buf[o + SavePlayerLayout.ItemShowWazaNameOffset] != 0,
                (ushort)ReadUInt16(o + SavePlayerLayout.ItemSortNumberOffset));
        }

        public int GetItemCount(int itemNo) => ReadInt32(ItemAt(itemNo) + SavePlayerLayout.ItemCountOffset);

        // Ändert nur das Count-Feld des Eintrags (0..999, ItemInfo.ItemMaxCount).
        public void SetItemCount(int itemNo, int count)
        {
            if (count < 0 || count > SavePlayerLayout.ItemMaxCount)
                throw new ArgumentOutOfRangeException(nameof(count), "Anzahl muss in 0..999 liegen");
            WriteInt32(ItemAt(itemNo) + SavePlayerLayout.ItemCountOffset, count);
        }

        // ---- Hilfen ----

        static int PlayerAt(int rel) => SavePlayerLayout.PlayerDataOffset + rel;

        static int ItemAt(int itemNo)
        {
            if (itemNo < 0 || itemNo >= SavePlayerLayout.ItemSlotCount) throw new ArgumentOutOfRangeException(nameof(itemNo));
            SaveLayout.TryGetField("saveItem", out var f);
            return f.Offset + itemNo * SavePlayerLayout.ItemStride;
        }

        string ReadName(int offset, int chars)
        {
            var sb = new StringBuilder(chars);
            for (var i = 0; i < chars; i++)
            {
                var c = ReadUInt16(offset + 2 * i);
                if (c == 0) break;
                sb.Append((char)c);
            }
            return sb.ToString();
        }

        // Schreibt Zeichen + NUL und füllt den Rest des Felds mit 0.
        void WriteName(int offset, int chars, int maxLength, string value)
        {
            if (value == null) throw new ArgumentNullException(nameof(value));
            if (value.Length > maxLength)
                throw new ArgumentException("Name länger als " + maxLength + " Zeichen", nameof(value));
            if (value.IndexOf('\0') >= 0) throw new ArgumentException("Name enthält NUL", nameof(value));
            for (var i = 0; i < chars; i++)
                WriteUInt16(offset + 2 * i, i < value.Length ? value[i] : 0);
        }

        int ReadInt32(int o) => _buf[o] | (_buf[o + 1] << 8) | (_buf[o + 2] << 16) | (_buf[o + 3] << 24);

        int ReadUInt16(int o) => _buf[o] | (_buf[o + 1] << 8);

        void WriteInt32(int o, int v)
        {
            _buf[o] = (byte)v;
            _buf[o + 1] = (byte)(v >> 8);
            _buf[o + 2] = (byte)(v >> 16);
            _buf[o + 3] = (byte)(v >> 24);
        }

        void WriteUInt16(int o, int v)
        {
            _buf[o] = (byte)v;
            _buf[o + 1] = (byte)(v >> 8);
        }
    }
}
