using System.Collections.Generic;

namespace Xnu.Data
{
    // Pokémon-Grunddaten je Art/Form (Quelle: XLSXContent.PersonalTable.SheetPersonal, Bundle Pml/personal_masterdatas).
    // Eigene Bezeichner; die Originalfeldnamen stehen in docs/masterdata.md.
    public sealed class SpeciesRecord
    {
        public bool IsValid { get; set; }
        public int Id { get; set; }
        public int DexNo { get; set; }
        public int FormIndex { get; set; }
        public int FormCount { get; set; }
        public int Color { get; set; }
        public int ModelId { get; set; }
        public int BaseHp { get; set; }
        public int BaseAttack { get; set; }
        public int BaseDefense { get; set; }
        public int BaseSpeed { get; set; }
        public int BaseSpAttack { get; set; }
        public int BaseSpDefense { get; set; }
        public int Type1 { get; set; }
        public int Type2 { get; set; }
        public int CatchRate { get; set; }
        public int Rank { get; set; }
        public int ExpValue { get; set; }
        public int HeldItem1 { get; set; }
        public int HeldItem2 { get; set; }
        public int HeldItem3 { get; set; }
        public int GenderRatio { get; set; }
        public int EggBirth { get; set; }
        public int InitialFriendship { get; set; }
        public int EggGroup1 { get; set; }
        public int EggGroup2 { get; set; }
        public int GrowthCurve { get; set; }
        public int Ability1 { get; set; }
        public int Ability2 { get; set; }
        public int Ability3 { get; set; }
        public int GiveExp { get; set; }
        public int Height { get; set; }
        public int Weight { get; set; }
        public int RegionalDexNo { get; set; }
        public uint MachineMask1 { get; set; }
        public uint MachineMask2 { get; set; }
        public uint MachineMask3 { get; set; }
        public uint MachineMask4 { get; set; }
        public uint HiddenMachineMask { get; set; }
        public int EggSpecies { get; set; }
        public int EggForm { get; set; }
        public int EggFormHeldStone { get; set; }
        public bool EggFormInheritHeldStone { get; set; }
    }

    // Attacken (XLSXContent.WazaTable.SheetWaza).
    public sealed class MoveRecord
    {
        public int MoveNo { get; set; }
        public bool IsValid { get; set; }
        public int Type { get; set; }
        public int Category { get; set; }
        public int DamageType { get; set; }
        public int Power { get; set; }
        public int Accuracy { get; set; }
        public int BasePp { get; set; }
        public int Priority { get; set; }
        public int HitCountMax { get; set; }
        public int HitCountMin { get; set; }
        public int StatusId { get; set; }
        public int StatusChance { get; set; }
        public int StatusContinuation { get; set; }
        public int StatusTurnMin { get; set; }
        public int StatusTurnMax { get; set; }
        public int CriticalRank { get; set; }
        public int FlinchChance { get; set; }
        public int AiSeqNo { get; set; }
        public int DamageRecoverRatio { get; set; }
        public int HpRecoverRatio { get; set; }
        public int Target { get; set; }
        public int[] StatStageTypes { get; set; } = new int[3];
        public int[] StatStageValues { get; set; } = new int[3];
        public int[] StatStageChances { get; set; } = new int[3];
        public uint Flags { get; set; }
        public uint ContestMoveNo { get; set; }
    }

    // Items (XLSXContent.ItemTable.SheetItem); die vielen wk_*-Wirkungsbytes bleiben als Name->Wert erhalten.
    public sealed class ItemRecord
    {
        public int ItemNo { get; set; }
        public int Type { get; set; }
        public int IconId { get; set; }
        public int Price { get; set; }
        public int BpPrice { get; set; }
        public int HoldEffect { get; set; }
        public int HoldPower { get; set; }
        public int ThrowPower { get; set; }
        public int NaturalGiftPower { get; set; }
        public int NaturalGiftType { get; set; }
        public int Sort { get; set; }
        public int Group { get; set; }
        public int GroupId { get; set; }
        public int FieldPocket { get; set; }
        public int FieldFunc { get; set; }
        public int BattleFunc { get; set; }
        public uint Flags { get; set; }
        // Alle übrigen Wirkungsfelder (wk_*), Schlüssel = Originalfeldname.
        public Dictionary<string, int> Effects { get; set; } = new Dictionary<string, int>();
    }

    // Zuordnung Item -> Attacken-Maschine (XLSXContent.ItemTable.SheetWazaMachine).
    public sealed class MachineRecord
    {
        public int ItemNo { get; set; }
        public int MachineNo { get; set; }
        public int MoveNo { get; set; }
    }

    // Entwicklungsdaten je Art-ID (XLSXContent.EvolveTable.SheetEvolve); Parameter sind ein flaches Zahlenfeld.
    public sealed class EvolutionRecord
    {
        public int Id { get; set; }
        public int[] Values { get; set; } = new int[0];
    }

    public sealed class MessageWord
    {
        public int PatternId { get; set; }
        public int EventId { get; set; }
        public int TagIndex { get; set; }
        public float TagValue { get; set; }
        public string Text { get; set; } = "";
        public float Width { get; set; }
    }

    public sealed class MessageLabel
    {
        public int LabelIndex { get; set; }
        public int ArrayIndex { get; set; }
        public string Name { get; set; } = "";
        public List<MessageWord> Words { get; set; } = new List<MessageWord>();
    }

    // Eine Textdatei (Dpr.Message.MsbtData): Labels mit Wortlisten.
    public sealed class MessageFile
    {
        public string Name { get; set; } = "";
        public int Hash { get; set; }
        public int LangId { get; set; }
        public bool IsResident { get; set; }
        public bool IsKanji { get; set; }
        public List<MessageLabel> Labels { get; set; } = new List<MessageLabel>();
    }
}
