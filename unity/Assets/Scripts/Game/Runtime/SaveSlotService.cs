using System;
using System.IO;
using Xnu.Field;
using Xnu.Save;

namespace Xnu.Game.Unity
{
    // Ort des Spielers im Spielstand (PLAYER_SAVE_DATA.TownMapLocation, Native-Layout: bool = 4 Byte) [A: dass SetPlayerPosData hierhin schreibt, ist nur aus dem Strukturnamen erschlossen].
    public readonly struct SavedPosition
    {
        public readonly int Zone;
        public readonly int GridX, GridY;
        public readonly int Direction;
        public readonly bool Valid;

        public SavedPosition(int zone, int gx, int gy, int dir, bool valid) { Zone = zone; GridX = gx; GridY = gy; Direction = dir; Valid = valid; }

        // Feldlage im Puffer: player_save_data bei 0x8FB04, TownMapLocation bei +0x54 (zone int, x/y/z float, dir int).
        public const int PlayerSaveDataOffset = 0x8FB04;
        public const int LocationOffset = PlayerSaveDataOffset + 0x54;
        public const int ZoneIdOffset = 0x5634;

        public static SavedPosition Read(SaveData save)
        {
            var b = save.Buffer;
            var zone = BitConverter.ToInt32(b, ZoneIdOffset);
            var locZone = BitConverter.ToInt32(b, LocationOffset);
            var x = BitConverter.ToSingle(b, LocationOffset + 4);
            var z = BitConverter.ToSingle(b, LocationOffset + 12);
            var dir = BitConverter.ToInt32(b, LocationOffset + 16);
            var ok = locZone == zone && !float.IsNaN(x) && !float.IsNaN(z) && Math.Abs(x) < 4000f && Math.Abs(z) < 4000f && (x != 0f || z != 0f);
            return new SavedPosition(zone, FieldCoords.GridX(x), FieldCoords.GridY(z), dir, ok);
        }

        // Schreibt Zone und Ort (Welt-Koordinaten wie im Original: x = -gx, z = gy) in den Puffer; die Höhe bleibt.
        public static void Write(SaveData save, int zone, int gx, int gy, MoveDir facing)
        {
            var b = save.Buffer;
            Put(b, ZoneIdOffset, zone);
            Put(b, LocationOffset, zone);
            Put(b, LocationOffset + 4, FieldCoords.WorldX(gx));
            Put(b, LocationOffset + 12, FieldCoords.WorldZ(gy));
            Put(b, LocationOffset + 16, (int)facing);
        }

        static void Put(byte[] b, int offset, int v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);
        static void Put(byte[] b, int offset, float v) => Buffer.BlockCopy(BitConverter.GetBytes(v), 0, b, offset, 4);

        public static MoveDir ToFacing(int direction) => direction >= 1 && direction <= 4 ? (MoveDir)direction : MoveDir.Down;
    }

    // Spielstand-Ablage des Players: eigener Slot im Save-Ordner der App (SaveStore), Backup vor jedem Überschreiben.
    // Der echte Spielstand (Ryujinx-Ordner o. Ä.) wird nur gelesen (Import beim ersten „Weiter“), nie beschrieben.
    public sealed class SaveSlotService
    {
        public const string SlotName = "main";
        public SaveStore Store { get; }
        public string ImportSource { get; }
        public string Note { get; private set; } = "";
        public int Writes { get; private set; }
        public string LastBackup { get; private set; } = "";

        public SaveSlotService(string root, string importSource)
        {
            Store = new SaveStore(root);
            ImportSource = importSource;
        }

        public bool HasSlot
        {
            get
            {
                foreach (var s in Store.ListSlots()) if (s == SlotName) return true;
                return false;
            }
        }

        // Es gibt etwas zum Weiterspielen: eigener Slot oder importierbare Quelle.
        public bool CanContinue => HasSlot || (!string.IsNullOrEmpty(ImportSource) && (Directory.Exists(ImportSource) || File.Exists(ImportSource)));

        public SaveData Load()
        {
            if (!HasSlot)
            {
                if (string.IsNullOrEmpty(ImportSource)) throw new FileNotFoundException("Kein Spielstand und keine Importquelle");
                var r = Store.Import(ImportSource, SlotName);
                Note = "Spielstand aus " + Path.GetFileName(Path.GetDirectoryName(ImportSource.TrimEnd('/', '\\'))) + " importiert (" + r.Bytes + " Byte, Quelle nur gelesen)";
            }
            else Note = "Spielstand aus dem eigenen Slot";
            return Store.Load(SlotName);
        }

        // Speichern: Hash neu, atomar schreiben, vorherigen Stand ins Backup-Verzeichnis des Slots.
        public SaveWriteResult Write(SaveData save)
        {
            var r = Store.Write(SlotName, save, true);
            Writes++;
            LastBackup = r.BackupPath ?? "";
            return r;
        }
    }
}
