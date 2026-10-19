using System;
using Xnu.Save;

namespace Xnu.EvScript
{
    // Ereignisvariablen: Arbeitswerte (Work), Flags, Systemflags und Trainer-Siegflags.
    // Im Original sind das PlayerWork.GetInt/GetBool/GetSytemFlag (FlagWork.*) und TrainerWork.*.
    public interface IEvVariables
    {
        int GetWork(int index);
        void SetWork(int index, int value);
        bool GetFlag(int index);
        void SetFlag(int index, bool value);
        bool GetSysFlag(int index);
        void SetSysFlag(int index, bool value);
        bool GetTrainerWin(int trainerId);
        void SetTrainerWin(int trainerId, bool value);
        // TrainerWork.GetBattleSearcher: Trainer sucht den Spieler noch (Sichtkampf offen).
        bool GetTrainerSearcher(int trainerId);
        void SetTrainerSearcher(int trainerId, bool value);
    }

    // Speicher-Variante (Tests, Mock-Läufe). Größen wie in PlayerWork.Initialization: 500 / 4000 / 1000 / 707.
    public sealed class EvMemoryVariables : IEvVariables
    {
        public const int WorkCount = 500;
        public const int FlagCount = 4000;
        public const int SysFlagCount = 1000;
        public const int TrainerCount = 707;

        public readonly int[] Work = new int[WorkCount];
        public readonly bool[] Flags = new bool[FlagCount];
        public readonly bool[] SysFlags = new bool[SysFlagCount];
        public readonly bool[] TrainerWin = new bool[TrainerCount];
        public readonly bool[] TrainerSearcher = new bool[TrainerCount];

        public int GetWork(int index) => Work[CheckWork(index)];
        public void SetWork(int index, int value) => Work[CheckWork(index)] = value;
        public bool GetFlag(int index) => Flags[Check(index, FlagCount, "Flag")];
        public void SetFlag(int index, bool value) => Flags[Check(index, FlagCount, "Flag")] = value;

        // PlayerWork.GetSytemFlag: die Indizes 0x326..0x329 sind immer gesetzt.
        public bool GetSysFlag(int index) => (uint)(index - 0x326) < 4u || SysFlags[Check(index, SysFlagCount, "Systemflag")];
        public void SetSysFlag(int index, bool value) => SysFlags[Check(index, SysFlagCount, "Systemflag")] = value;
        public bool GetTrainerWin(int id) => TrainerWin[Check(id, TrainerCount, "Trainer")];
        public void SetTrainerWin(int id, bool value) => TrainerWin[Check(id, TrainerCount, "Trainer")] = value;
        public bool GetTrainerSearcher(int id) => TrainerSearcher[Check(id, TrainerCount, "Trainer")];
        public void SetTrainerSearcher(int id, bool value) => TrainerSearcher[Check(id, TrainerCount, "Trainer")] = value;

        static int CheckWork(int index) => Check(index, WorkCount, "Work");

        static int Check(int index, int count, string what)
        {
            if ((uint)index >= (uint)count) throw new EvScriptException(what + "-Index außerhalb des Bereichs: " + index);
            return index;
        }
    }

    // SaveData-gestützte Variante: schreibt direkt in den Puffer (intValues, boolValues, systemFlags, tr_battleData).
    // Offsets und Elementgrößen nach docs/save-spec-entwurf.md (bool = 4 Byte je Element im Marshal-Abbild).
    // Annahme: tr_battleData hat 8 Byte je Trainer; das erste Feld ist das Siegflag, das zweite der Sichtkampf-Suchflag
    // (im Original ein ushort aus zwei Bytes: niedriges Byte = Sieg, hohes Byte = Suche).
    public sealed class EvSaveVariables : IEvVariables
    {
        const int WorkOffset = 0x4;
        const int FlagOffset = 0x7D4;
        const int SysFlagOffset = 0x4654;
        const int TrainerOffset = 0x7D3E0;
        const int TrainerStride = 8;

        readonly SaveData _save;

        public EvSaveVariables(SaveData save)
        {
            _save = save ?? throw new ArgumentNullException(nameof(save));
        }

        public int GetWork(int index) => ReadInt(WorkOffset + 4 * Check(index, EvMemoryVariables.WorkCount, "Work"));
        public void SetWork(int index, int value) => WriteInt(WorkOffset + 4 * Check(index, EvMemoryVariables.WorkCount, "Work"), value);
        public bool GetFlag(int index) => ReadInt(FlagOffset + 4 * Check(index, EvMemoryVariables.FlagCount, "Flag")) != 0;
        public void SetFlag(int index, bool value) => WriteInt(FlagOffset + 4 * Check(index, EvMemoryVariables.FlagCount, "Flag"), value ? 1 : 0);

        public bool GetSysFlag(int index) =>
            (uint)(index - 0x326) < 4u || ReadInt(SysFlagOffset + 4 * Check(index, EvMemoryVariables.SysFlagCount, "Systemflag")) != 0;

        public void SetSysFlag(int index, bool value) =>
            WriteInt(SysFlagOffset + 4 * Check(index, EvMemoryVariables.SysFlagCount, "Systemflag"), value ? 1 : 0);

        public bool GetTrainerWin(int id) => ReadInt(TrainerOffset + TrainerStride * Check(id, EvMemoryVariables.TrainerCount, "Trainer")) != 0;
        public void SetTrainerWin(int id, bool value) => WriteInt(TrainerOffset + TrainerStride * Check(id, EvMemoryVariables.TrainerCount, "Trainer"), value ? 1 : 0);
        public bool GetTrainerSearcher(int id) => ReadInt(TrainerOffset + 4 + TrainerStride * Check(id, EvMemoryVariables.TrainerCount, "Trainer")) != 0;
        public void SetTrainerSearcher(int id, bool value) => WriteInt(TrainerOffset + 4 + TrainerStride * Check(id, EvMemoryVariables.TrainerCount, "Trainer"), value ? 1 : 0);

        static int Check(int index, int count, string what)
        {
            if ((uint)index >= (uint)count) throw new EvScriptException(what + "-Index außerhalb des Bereichs: " + index);
            return index;
        }

        int ReadInt(int o)
        {
            var b = _save.Buffer;
            return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24);
        }

        void WriteInt(int o, int v)
        {
            var b = _save.Buffer;
            b[o] = (byte)v;
            b[o + 1] = (byte)(v >> 8);
            b[o + 2] = (byte)(v >> 16);
            b[o + 3] = (byte)(v >> 24);
        }
    }
}
