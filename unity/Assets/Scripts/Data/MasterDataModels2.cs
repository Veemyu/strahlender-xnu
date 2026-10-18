using System.Collections.Generic;

namespace Xnu.Data
{
    // Stammdaten Teil 2 (Trainer, Begegnungen, Zonen, Warps, Shops, Lern-/Entwicklungslisten, Event-Skripte).
    // Eigene Bezeichner; Quellen und Originalfeldnamen stehen in docs/masterdata.md (Abschnitt "Teil 2").
    // Reine POCOs ohne UnityEngine.

    public struct Vec2
    {
        public float X { get; set; }
        public float Y { get; set; }
    }

    public struct Vec3
    {
        public float X { get; set; }
        public float Y { get; set; }
        public float Z { get; set; }
    }

    public struct Vec4
    {
        public float X { get; set; }
        public float Y { get; set; }
        public float Z { get; set; }
        public float W { get; set; }
    }

    // --- 1. Trainer (XLSXContent.TrainerTable, Bundle Dpr/masterdatas) ---

    // Sheet TrainerType: Trainerklasse (Modell, Ball, Sprechchor-/Begegnungsschlüssel).
    public sealed class TrainerTypeRecord
    {
        public int TypeId { get; set; }                 // TrainerID
        public string Label { get; set; } = "";         // LabelTrType (Textlabel der Klasse)
        public int Sex { get; set; }
        public int Group { get; set; }
        public int BallId { get; set; }
        public string[] FieldEncountKeys { get; set; } = new string[0];   // FieldEncount
        public int[] BattleEffectIds { get; set; } = new int[0];          // BtlEffId
        public string EyeBgmEvent { get; set; } = "";   // EyeBgm (nur Bezeichner, Audio wird nicht angefasst)
        public string ModelId { get; set; } = "";
        public int Hand { get; set; }
        public int HoldBallHand { get; set; }
        public int HelpHand { get; set; }
        public int HelpHoldBallHand { get; set; }
        public float ThrowTime { get; set; }
        public float CaptureThrowTime { get; set; }
        public float LoseLoopTime { get; set; }
        public string TrainerEffect { get; set; } = "";
        public int Age { get; set; }
    }

    // Sheet TrainerData: Kampfdaten je Trainer. Die Trainer-ID ist der Zeilenindex (das Sheet hat kein ID-Feld).
    public sealed class TrainerRecord
    {
        public int Id { get; set; }
        public int TypeId { get; set; }                 // TypeID
        public int ColorId { get; set; }
        public int FightType { get; set; }              // 0 = Einzel (Vermutung nach Feldname; im Spiel nicht verifiziert)
        public int ArenaId { get; set; }                // -1 = Standard der Zone
        public int EffectId { get; set; }
        public int Gold { get; set; }                   // Preisgeld-Faktor
        public int[] UseItems { get; set; } = new int[4];   // UseItem1..4
        public bool HpRecoverFlag { get; set; }
        public int GiftItem { get; set; }
        public string NameLabel { get; set; } = "";
        public string MsgFieldPokeOne { get; set; } = "";
        public string MsgFieldBefore { get; set; } = "";
        public string MsgFieldRevenge { get; set; } = "";
        public string MsgFieldAfter { get; set; } = "";
        public string[] BattleMessages { get; set; } = new string[0];   // MsgBattle (Labels)
        public string[] BattleSequences { get; set; } = new string[0];  // SeqBattle
        public uint AiBits { get; set; }                // AIBit: KI-Typ als Bitmaske
        public TrainerPartyRecord Party { get; set; }   // aus Sheet TrainerPoke (gleiche ID)
    }

    // Ein Teamplatz (TrainerPoke, Feldgruppe P1..P6).
    public sealed class TrainerPokemonRecord
    {
        public int Slot { get; set; }                   // 1..6
        public int MonsNo { get; set; }
        public int FormNo { get; set; }
        public bool IsRare { get; set; }
        public int Level { get; set; }
        public int Sex { get; set; }
        public int Nature { get; set; }                 // Seikaku
        public int Ability { get; set; }                // Tokusei
        public int[] Moves { get; set; } = new int[4];  // Waza1..4
        public int HeldItem { get; set; }
        public int BallId { get; set; }
        public int SealTemplateId { get; set; }
        // Reihenfolge je: HP, Angriff, Verteidigung, Sp.-Angriff, Sp.-Verteidigung, Initiative
        public int[] Talents { get; set; } = new int[6];   // Talent* (Einzelwerte)
        public int[] Efforts { get; set; } = new int[6];   // Effort* (Fleißpunkte)
    }

    // Team eines Trainers; leere Plätze (MonsNo == 0) sind ausgelassen.
    public sealed class TrainerPartyRecord
    {
        public int TrainerId { get; set; }
        public List<TrainerPokemonRecord> Members { get; set; } = new List<TrainerPokemonRecord>();
    }

    public sealed class TrainerRematchRecord
    {
        public int BaseTrainerId { get; set; }
        public int[] RematchTrainerIds { get; set; } = new int[5];   // Rematch_01..05
    }

    public sealed class TrainerTables
    {
        public List<TrainerTypeRecord> Types { get; set; } = new List<TrainerTypeRecord>();
        public List<TrainerRecord> Trainers { get; set; } = new List<TrainerRecord>();
        public List<TrainerRematchRecord> Rematches { get; set; } = new List<TrainerRematchRecord>();
    }

    // --- 2. Begegnungen (XLSXContent.FieldEncountTable, Bundle Dpr/scriptableobjects/gamesettings) ---

    public struct EncounterSlot
    {
        public int MonsNo { get; set; }
        public int MinLevel { get; set; }
        public int MaxLevel { get; set; }
    }

    // Sheet "table": Wildpokémon je Zone. Slotanzahl je Liste ist fest (Gras 12, Zeit 2, Wasser/Angeln 5).
    // Rate = Gesamtrate je Art; die Slot-Wahrscheinlichkeiten stehen nicht in der Tabelle.
    public sealed class ZoneEncounterRecord
    {
        public int ZoneId { get; set; }
        public int GrassRate { get; set; }                 // encRate_gr
        public EncounterSlot[] Grass { get; set; }         // ground_mons
        public EncounterSlot[] Outbreak { get; set; }      // tairyo (Massenauftreten)
        public EncounterSlot[] Day { get; set; }
        public EncounterSlot[] Night { get; set; }
        public EncounterSlot[] SwayGrass { get; set; }     // swayGrass
        public int[] FormProbabilities { get; set; }       // FormProb
        public int[] Riddle { get; set; }                  // Nazo
        public int[] UnownTable { get; set; }              // AnnoonTable
        public EncounterSlot[] GbaRuby { get; set; }
        public EncounterSlot[] GbaSapphire { get; set; }   // gbaSapp
        public EncounterSlot[] GbaEmerald { get; set; }    // gbaEme
        public EncounterSlot[] GbaFireRed { get; set; }    // gbaFire
        public EncounterSlot[] GbaLeafGreen { get; set; }  // gbaLeaf
        public int WaterRate { get; set; }                 // encRate_wat
        public EncounterSlot[] Water { get; set; }         // water_mons (Surfen)
        public int OldRodRate { get; set; }                // encRate_turi_boro
        public EncounterSlot[] OldRod { get; set; }        // boro_mons
        public int GoodRodRate { get; set; }               // encRate_turi_ii
        public EncounterSlot[] GoodRod { get; set; }       // ii_mons
        public int SuperRodRate { get; set; }              // encRate_sugoi
        public EncounterSlot[] SuperRod { get; set; }      // sugoi_mons
    }

    // Sheet mistu: Honigbaum-Auftritte (Gesamtrate + drei Seltenheitsstufen).
    public sealed class HoneyEncounterRecord
    {
        public int Rate { get; set; }
        public int Normal { get; set; }
        public int Rare { get; set; }
        public int SuperRare { get; set; }
    }

    // Sheet honeytree: Anteile je Honigbaum-Art (Normal/Rare).
    public sealed class HoneyTreeEncounterRecord
    {
        public int Normal { get; set; }
        public int Rare { get; set; }
    }

    // Sheet mvpoke: Wandergraph (Zone -> mögliche Folgezonen).
    public sealed class RoamingZoneRecord
    {
        public int ZoneId { get; set; }
        public int NextCount { get; set; }
        public int[] NextZoneIds { get; set; } = new int[0];
    }

    // Sheet legendpoke: feste Begegnungen (Sequenz-/BGM-/Hintergrundvorgaben, bis zu vier feste Attacken, -1 = keine).
    public sealed class FixedEncounterRecord
    {
        public int MonsNo { get; set; }
        public int FormNo { get; set; }
        public bool IsFixedEncounterSequence { get; set; }
        public string EncounterSequence { get; set; } = "";
        public bool IsFixedBgm { get; set; }
        public string BgmEvent { get; set; } = "";
        public bool IsFixedBattleBackground { get; set; }
        public int BattleBackground { get; set; }
        public bool IsFixedSetupEffect { get; set; }
        public int SetupEffect { get; set; }
        public int[] Moves { get; set; } = new int[4];
    }

    // Sheet zui: 28 Bool-Werte je Zone (Formenfreigabe, Anzahl passt zu den 28 Formen von Icognito/Unown).
    // Die Deutung ist eine Vermutung aus der Listenlänge; der Name "zui" selbst ist nicht geklärt.
    public sealed class ZuiFormRecord
    {
        public int ZoneId { get; set; }
        public bool[] Forms { get; set; } = new bool[0];
    }

    public sealed class FieldEncounterTables
    {
        public string InstanceName { get; set; } = "";     // z. B. FieldEncountTable_d / _p (zwei Editionen)
        public List<ZoneEncounterRecord> Zones { get; set; } = new List<ZoneEncounterRecord>();
        public List<int> UnderRoadMonsters { get; set; } = new List<int>();   // urayama
        public List<HoneyEncounterRecord> Honey { get; set; } = new List<HoneyEncounterRecord>();
        public List<HoneyTreeEncounterRecord> HoneyTrees { get; set; } = new List<HoneyTreeEncounterRecord>();
        public List<int> SafariMonsters { get; set; } = new List<int>();
        public List<RoamingZoneRecord> Roaming { get; set; } = new List<RoamingZoneRecord>();
        public List<FixedEncounterRecord> FixedEncounters { get; set; } = new List<FixedEncounterRecord>();
        public List<ZuiFormRecord> ZuiForms { get; set; } = new List<ZuiFormRecord>();
    }

    // Dpr/masterdatas HoneyTree: Standorte (Index) und Schüttel-Ergebnisse.
    public sealed class HoneyTreeSpotRecord
    {
        public int ZoneId { get; set; }
        public int StartFlag { get; set; }     // HoneyStartFlag (Systemflag)
        public Vec2 Position { get; set; }     // HoneyPosXZ
    }

    public sealed class HoneyTreeShakeRecord
    {
        public int Big { get; set; }
        public int Normal { get; set; }
        public int None { get; set; }
        public int Super { get; set; }
    }

    public sealed class HoneyTreeTables
    {
        public List<HoneyTreeSpotRecord> Spots { get; set; } = new List<HoneyTreeSpotRecord>();
        public List<HoneyTreeShakeRecord> Shakes { get; set; } = new List<HoneyTreeShakeRecord>();
    }

    // CalenderEncTable: Tagesdaten (Zusatzraten) und Wetter je Tag/Karte.
    public sealed class CalendarEncounterDayRecord
    {
        public int Month { get; set; }
        public int Day { get; set; }
        public int AddRate { get; set; }
        public int AddHatching { get; set; }
    }

    public sealed class CalendarWeatherRecord
    {
        public int Route212b { get; set; }
        public int Route213 { get; set; }
        public int Route216 { get; set; }
        public int Lake3 { get; set; }       // l3
        public int City9 { get; set; }       // c9
    }

    public sealed class CalendarEncounterTables
    {
        public List<CalendarEncounterDayRecord> Days { get; set; } = new List<CalendarEncounterDayRecord>();
        public List<CalendarWeatherRecord> Weather { get; set; } = new List<CalendarWeatherRecord>();
    }

    // --- 3. Zonen, Karten, Warps ---

    // MapInfo.SheetZoneData (658 Zonen, Index = Zeile). Verweise auf Attributdaten sind Objektnamen.
    public sealed class ZoneInfoRecord
    {
        public string DebugCaption { get; set; } = "";   // Caption (interner Name)
        public string AreaNameLabel { get; set; } = "";  // MSLabel
        public string PokePlaceNameLabel { get; set; } = "";
        public string FlyingPlaceNameLabel { get; set; } = "";
        public int MapType { get; set; }
        public bool IsField { get; set; }
        public int LandmarkType { get; set; }
        public Vec2 MiniMapOffset { get; set; }
        public bool CanUseBicycle { get; set; }          // Bicycle
        public bool CanEscape { get; set; }              // Escape
        public bool CanFly { get; set; }                 // Fly
        public bool BattleSearcher { get; set; }
        public bool WalkWithPartner { get; set; }        // TureAruki
        public bool KuruKuru { get; set; }
        public bool Fall { get; set; }
        public int[] BattleBackgrounds { get; set; } = new int[0];   // BattleBg (ArenaID)
        public int ZoneId { get; set; }
        public int AreaId { get; set; }
        public string ZoneGridName { get; set; } = "";   // ZoneGrid -> Name der ZoneTable-Instanz ("" = keine)
        public string AttributeName { get; set; } = "";  // Attribute -> AttributeMatrix
        public string AttributeExName { get; set; } = "";
        public string SubAttributeName { get; set; } = "";
        public string SubAttributeExName { get; set; } = "";
        public string[] Bgm { get; set; } = new string[0];            // Ereignisnamen (nur Bezeichner)
        public string EnvironmentalSound { get; set; } = "";
        public int Weather { get; set; }
        public string RenderSettingsName { get; set; } = "";
        public bool ReflectionCamera { get; set; }
        public bool FixedTime { get; set; }
        public string AssetBundleName { get; set; } = "";   // Kartenbundle relativ zu Environments/, "" = keins
        public bool RoomPanCamera { get; set; }
        public Vec4[] Locators { get; set; } = new Vec4[0];
        public bool Reload { get; set; }
    }

    // MapInfo.SheetCamera (je Area).
    public sealed class ZoneCameraRecord
    {
        public int AreaId { get; set; }                  // ariaID
        public float Pitch { get; set; }
        public float Fov { get; set; }
        public float TargetRange { get; set; }
        public float PanDistance { get; set; }
        public float PanPitch { get; set; }
        public float PanFov { get; set; }
        public bool PanPosUseFlag { get; set; }
        public float PanMinPosY { get; set; }
        public float PanMaxPosY { get; set; }
        public float PanMinPosZ { get; set; }
        public float PanMaxPosZ { get; set; }
        public float DefocusStart { get; set; }
        public float DefocusEnd { get; set; }
        public float Distance { get; set; }
    }

    public sealed class MapInfoTables
    {
        public List<ZoneInfoRecord> Zones { get; set; } = new List<ZoneInfoRecord>();
        public List<ZoneCameraRecord> Cameras { get; set; } = new List<ZoneCameraRecord>();
    }

    // XLSXContent.ZoneTable: Raster aus Zonen-IDs (-1 = leer), zeilenweise mit Breite Width.
    public sealed class ZoneGridRecord
    {
        public string Name { get; set; } = "";           // z. B. Instanzname der Welt/des Safari-Gebiets
        public int Width { get; set; }
        public int[] ZoneIds { get; set; } = new int[0];
        public int Height => Width > 0 ? ZoneIds.Length / Width : 0;
        public int ZoneAt(int column, int row) => ZoneIds[row * Width + column];
    }

    // XLSXContent.AttributeBlock: 32 x 32 Attributwerte (Begehbarkeit/Gelände-Codes) je Block.
    public sealed class AttributeBlockRecord
    {
        public string Name { get; set; } = "";
        public int Width { get; set; }
        public int[] Attributes { get; set; } = new int[0];
        public int Height => Width > 0 ? Attributes.Length / Width : 0;
        public int At(int column, int row) => Attributes[row * Width + column];
    }

    // XLSXContent.AttributeMatrix: Blockraster einer Karte (Blocknamen, "" = leer), zeilenweise mit Breite Width.
    public sealed class AttributeMatrixRecord
    {
        public string Name { get; set; } = "";
        public int Width { get; set; }
        public string[] BlockNames { get; set; } = new string[0];
    }

    // MapAttributeTable.SheetData: Bedeutung eines Attributcodes (Eintritt, Wasser, Begegnung).
    public sealed class MapAttributeCodeRecord
    {
        public int Code { get; set; }
        public int Attribute { get; set; }
        public bool Entry { get; set; }
        public bool Water { get; set; }
        public bool Encounter { get; set; }
        public string FieldEncounterKey { get; set; } = "";   // FieldEncount
    }

    // XLSXContent.MapWarp (eine Instanz je Karte; Name z. B. "MapWarp_<Karte>").
    public sealed class MapWarpRecord
    {
        public Vec3 Position { get; set; }
        public int GroupId { get; set; }                 // GruopID (Tippfehler im Original)
        public Vec2 Size { get; set; }
        public int WarpZone { get; set; }
        public int WarpIndex { get; set; }
        public int InputDirection { get; set; }
        public int FlagIndex { get; set; }
        public int ScriptLabel { get; set; }
        public int ExitLabel { get; set; }
        public string ConnectionName { get; set; } = "";
    }

    public sealed class MapWarpSet
    {
        public string Name { get; set; } = "";
        public List<MapWarpRecord> Warps { get; set; } = new List<MapWarpRecord>();
    }

    // --- 4. Shops (XLSXContent.ShopTable) ---

    public sealed class ShopEntryRecord
    {
        public int ItemNo { get; set; }
        public int ShopId { get; set; }                  // FixedShop.ShopID, BPShop.NPCID, FS: 0
        public int BadgeNum { get; set; }                // nur FS
        public int ZoneId { get; set; }                  // nur FS (-1 = überall)
    }

    public sealed class ShopTables
    {
        public List<ShopEntryRecord> FriendlyShop { get; set; } = new List<ShopEntryRecord>();   // FS
        public List<ShopEntryRecord> FixedShop { get; set; } = new List<ShopEntryRecord>();
        public List<ShopEntryRecord> BpShop { get; set; } = new List<ShopEntryRecord>();
    }

    // --- 5. Lern- und Entwicklungslisten ---

    // EvolveTable.ar: Gruppen zu je fünf Zahlen (Methode, Parameter, Zielart, Zielform, Stufe).
    public sealed class EvolutionStepRecord
    {
        public int Method { get; set; }
        public int Parameter { get; set; }
        public int TargetSpecies { get; set; }
        public int TargetForm { get; set; }
        public int Level { get; set; }
    }

    public sealed class EvolutionListRecord
    {
        public int Id { get; set; }                      // Zeile in PersonalTable
        public List<EvolutionStepRecord> Steps { get; set; } = new List<EvolutionStepRecord>();
    }

    public struct LevelMove
    {
        public int Level { get; set; }
        public int MoveNo { get; set; }
    }

    // WazaOboeTable.ar: Paare (Stufe, Attacke).
    public sealed class LearnsetRecord
    {
        public int Id { get; set; }
        public List<LevelMove> Moves { get; set; } = new List<LevelMove>();
    }

    // TamagoWazaTable.Data: Eiattacken je Art/Form.
    public sealed class EggMoveRecord
    {
        public int No { get; set; }
        public int FormNo { get; set; }
        public int[] MoveNos { get; set; } = new int[0];
    }

    // GrowTable.Data: Erfahrungspunkte je Stufe (Index = Stufe) je Wachstumskurve.
    public sealed class GrowthCurveRecord
    {
        public int[] ExpByLevel { get; set; } = new int[0];
    }

    // --- 6. Event-Skripte (EvData, Bundle Dpr/ev_script) ---
    // Nur Struktur: ein Befehl ist eine Liste typisierter Zahlenargumente. Es wird nichts interpretiert.

    public enum EventArgType
    {
        Command = 0,
        Float = 1,
        Work = 2,
        Flag = 3,
        SysFlag = 4,
        String = 5,
    }

    public struct EventArgument
    {
        public int Type { get; set; }                    // EventArgType (Rohwert, andere Werte bleiben erhalten)
        public int Data { get; set; }
        // Float-Argumente speichern die Bits des float-Werts in Data.
        public float AsFloat() => System.BitConverter.ToSingle(System.BitConverter.GetBytes(Data), 0);
    }

    public sealed class EventCommand
    {
        public List<EventArgument> Args { get; set; } = new List<EventArgument>();
    }

    public sealed class EventScript
    {
        public string Label { get; set; } = "";
        public List<EventCommand> Commands { get; set; } = new List<EventCommand>();
    }

    // Eine EvData-Instanz (eine Karte/ein Ereignisbereich): Skripte plus Stringtabelle (Index aus String-Argumenten).
    public sealed class EventScriptFile
    {
        public string Name { get; set; } = "";
        public List<EventScript> Scripts { get; set; } = new List<EventScript>();
        public List<string> Strings { get; set; } = new List<string>();
    }
}
