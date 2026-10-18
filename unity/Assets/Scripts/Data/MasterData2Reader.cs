using System;
using System.Collections.Generic;
using System.IO;

namespace Xnu.Data
{
    // Liest die Teil-2-Tabellen aus den JSON-Dateien des Exporters (scripts/masterdata_export.py, Option --set extra).
    // Teil-1-Dateien (Trainer, Shops, Honigbäume, MapWarp, Entwicklung usw.) liegen im Basis-Export.
    // Dateiformat: {"class","namespace","assembly","bundle","instances":[{"name","data":{<Feld>:[Zeilen]}}]}.
    public sealed class MasterData2Reader
    {
        public const string TrainerPath = "dpr_masterdatas/TrainerTable.json";
        public const string ShopPath = "dpr_masterdatas/ShopTable.json";
        public const string HoneyTreePath = "dpr_masterdatas/HoneyTree.json";
        public const string MapWarpPath = "dpr_masterdatas/MapWarp.json";
        public const string EvolvePath = "pml_personal/EvolveTable.json";
        public const string LearnsetPath = "pml_personal/WazaOboeTable.json";
        public const string EggMovePath = "pml_personal/TamagoWazaTable.json";
        public const string GrowPath = "pml_personal/GrowTable.json";
        public const string FieldEncountPath = "gamesettings/FieldEncountTable.json";
        public const string CalendarPath = "gamesettings/CalenderEncTable.json";
        public const string MapInfoPath = "gamesettings/MapInfo.json";
        public const string ZoneTablePath = "gamesettings/ZoneTable.json";
        public const string AttributeBlockPath = "gamesettings/AttributeBlock.json";
        public const string AttributeMatrixPath = "gamesettings/AttributeMatrix.json";
        public const string MapAttributePath = "gamesettings/MapAttributeTable.json";
        public const string EventScriptPath = "ev_script/EvData.json";

        // Das Bundle enthält zwei Instanzen (zwei Editionen); Diamant ist "_d", Perl "_p".
        public const string DiamondEncounterInstance = "FieldEncountTable_d";

        readonly string _root;

        public MasterData2Reader(string rootDirectory)
        {
            _root = rootDirectory ?? throw new ArgumentNullException(nameof(rootDirectory));
        }

        public TrainerTables LoadTrainers() => ParseTrainers(Read(TrainerPath));
        public ShopTables LoadShops() => ParseShops(Read(ShopPath));
        public HoneyTreeTables LoadHoneyTrees() => ParseHoneyTrees(Read(HoneyTreePath));
        public List<MapWarpSet> LoadMapWarps() => ParseMapWarps(Read(MapWarpPath));
        public List<EvolutionListRecord> LoadEvolutionLists() => ParseEvolutionLists(Read(EvolvePath));
        public List<LearnsetRecord> LoadLearnsets() => ParseLearnsets(Read(LearnsetPath));
        public List<EggMoveRecord> LoadEggMoves() => ParseEggMoves(Read(EggMovePath));
        public List<GrowthCurveRecord> LoadGrowthCurves() => ParseGrowthCurves(Read(GrowPath));
        public FieldEncounterTables LoadFieldEncounters(string instanceName = DiamondEncounterInstance) =>
            ParseFieldEncounters(Read(FieldEncountPath), instanceName);
        public CalendarEncounterTables LoadCalendar() => ParseCalendar(Read(CalendarPath));
        public MapInfoTables LoadMapInfo() => ParseMapInfo(Read(MapInfoPath));
        public List<ZoneGridRecord> LoadZoneGrids() => ParseZoneGrids(Read(ZoneTablePath));
        public List<AttributeBlockRecord> LoadAttributeBlocks() => ParseAttributeBlocks(Read(AttributeBlockPath));
        public List<AttributeMatrixRecord> LoadAttributeMatrices() => ParseAttributeMatrices(Read(AttributeMatrixPath));
        public List<MapAttributeCodeRecord> LoadMapAttributeCodes() => ParseMapAttributeCodes(Read(MapAttributePath));
        public List<EventScriptFile> LoadEventScripts() => ParseEventScripts(Read(EventScriptPath));

        string Read(string relative)
        {
            var path = Path.Combine(_root, relative);
            if (!File.Exists(path)) throw new FileNotFoundException("Stammdaten-JSON fehlt (Exporter ausführen, ggf. --set extra)", path);
            return File.ReadAllText(path, System.Text.Encoding.UTF8);
        }

        // --- 1. Trainer ---

        public static TrainerTables ParseTrainers(string json)
        {
            var data = SingleData(json, "TrainerTable");
            var tables = new TrainerTables();

            foreach (var r in J.Array(data, "TrainerType"))
            {
                tables.Types.Add(new TrainerTypeRecord
                {
                    TypeId = J.Int(r, "TrainerID"),
                    Label = J.Str(r, "LabelTrType"),
                    Sex = J.Int(r, "Sex"),
                    Group = J.Int(r, "Group"),
                    BallId = J.Int(r, "BallId"),
                    FieldEncountKeys = J.StrArray(r, "FieldEncount"),
                    BattleEffectIds = J.IntArray(r, "BtlEffId"),
                    EyeBgmEvent = J.Str(r, "EyeBgm"),
                    ModelId = J.Str(r, "ModelID"),
                    Hand = J.Int(r, "Hand"),
                    HoldBallHand = J.Int(r, "HoldBallHand"),
                    HelpHand = J.Int(r, "HelpHand"),
                    HelpHoldBallHand = J.Int(r, "HelpHoldBallHand"),
                    ThrowTime = (float)J.Dbl(r, "ThrowTime"),
                    CaptureThrowTime = (float)J.Dbl(r, "CaptureThrowTime"),
                    LoseLoopTime = (float)J.Dbl(r, "LoseLoopTime"),
                    TrainerEffect = J.Str(r, "TrainerEffect"),
                    Age = J.Int(r, "Age"),
                });
            }

            var parties = new Dictionary<int, TrainerPartyRecord>();
            foreach (var r in J.Array(data, "TrainerPoke"))
            {
                var party = new TrainerPartyRecord { TrainerId = J.Int(r, "ID") };
                for (var slot = 1; slot <= 6; slot++)
                {
                    var p = "P" + slot;
                    var monsNo = J.Int(r, p + "MonsNo");
                    if (monsNo == 0) continue;
                    party.Members.Add(new TrainerPokemonRecord
                    {
                        Slot = slot,
                        MonsNo = monsNo,
                        FormNo = J.Int(r, p + "FormNo"),
                        IsRare = J.Bool(r, p + "IsRare"),
                        Level = J.Int(r, p + "Level"),
                        Sex = J.Int(r, p + "Sex"),
                        Nature = J.Int(r, p + "Seikaku"),
                        Ability = J.Int(r, p + "Tokusei"),
                        Moves = new[] { J.Int(r, p + "Waza1"), J.Int(r, p + "Waza2"), J.Int(r, p + "Waza3"), J.Int(r, p + "Waza4") },
                        HeldItem = J.Int(r, p + "Item"),
                        BallId = J.Int(r, p + "Ball"),
                        SealTemplateId = J.Int(r, p + "Seal"),
                        Talents = new[]
                        {
                            J.Int(r, p + "TalentHp"), J.Int(r, p + "TalentAtk"), J.Int(r, p + "TalentDef"),
                            J.Int(r, p + "TalentSpAtk"), J.Int(r, p + "TalentSpDef"), J.Int(r, p + "TalentAgi"),
                        },
                        Efforts = new[]
                        {
                            J.Int(r, p + "EffortHp"), J.Int(r, p + "EffortAtk"), J.Int(r, p + "EffortDef"),
                            J.Int(r, p + "EffortSpAtk"), J.Int(r, p + "EffortSpDef"), J.Int(r, p + "EffortAgi"),
                        },
                    });
                }
                parties[party.TrainerId] = party;
            }

            var id = 0;
            foreach (var r in J.Array(data, "TrainerData"))
            {
                var t = new TrainerRecord
                {
                    Id = id,
                    TypeId = J.Int(r, "TypeID"),
                    ColorId = J.Int(r, "ColorID"),
                    FightType = J.Int(r, "FightType"),
                    ArenaId = J.Int(r, "ArenaID"),
                    EffectId = J.Int(r, "EffectID"),
                    Gold = J.Int(r, "Gold"),
                    UseItems = new[] { J.Int(r, "UseItem1"), J.Int(r, "UseItem2"), J.Int(r, "UseItem3"), J.Int(r, "UseItem4") },
                    HpRecoverFlag = J.Bool(r, "HpRecoverFlag"),
                    GiftItem = J.Int(r, "GiftItem"),
                    NameLabel = J.Str(r, "NameLabel"),
                    MsgFieldPokeOne = J.Str(r, "MsgFieldPokeOne"),
                    MsgFieldBefore = J.Str(r, "MsgFieldBefore"),
                    MsgFieldRevenge = J.Str(r, "MsgFieldRevenge"),
                    MsgFieldAfter = J.Str(r, "MsgFieldAfter"),
                    BattleMessages = J.StrArray(r, "MsgBattle"),
                    BattleSequences = J.StrArray(r, "SeqBattle"),
                    AiBits = J.UInt(r, "AIBit"),
                };
                parties.TryGetValue(id, out var party);
                t.Party = party;
                tables.Trainers.Add(t);
                id++;
            }

            foreach (var r in J.Array(data, "TrainerRematch"))
            {
                tables.Rematches.Add(new TrainerRematchRecord
                {
                    BaseTrainerId = J.Int(r, "BaseTrainerID"),
                    RematchTrainerIds = new[]
                    {
                        J.Int(r, "Rematch_01"), J.Int(r, "Rematch_02"), J.Int(r, "Rematch_03"),
                        J.Int(r, "Rematch_04"), J.Int(r, "Rematch_05"),
                    },
                });
            }
            return tables;
        }

        // --- 2. Begegnungen ---

        public static FieldEncounterTables ParseFieldEncounters(string json, string instanceName)
        {
            var root = J.Root(json, "FieldEncountTable");
            Dictionary<string, object> inst = null;
            foreach (var i in J.Array(root, "instances"))
            {
                if (J.Str(i, "name") == instanceName) { inst = i; break; }
            }
            if (inst == null) throw new FormatException("Instanz '" + instanceName + "' fehlt in FieldEncountTable");
            var data = J.Obj(inst, "data");
            var t = new FieldEncounterTables { InstanceName = instanceName };

            foreach (var r in J.Array(data, "table"))
            {
                t.Zones.Add(new ZoneEncounterRecord
                {
                    ZoneId = J.Int(r, "zoneID"),
                    GrassRate = J.Int(r, "encRate_gr"),
                    Grass = Slots(r, "ground_mons"),
                    Outbreak = Slots(r, "tairyo"),
                    Day = Slots(r, "day"),
                    Night = Slots(r, "night"),
                    SwayGrass = Slots(r, "swayGrass"),
                    FormProbabilities = J.IntArray(r, "FormProb"),
                    Riddle = J.IntArray(r, "Nazo"),
                    UnownTable = J.IntArray(r, "AnnoonTable"),
                    GbaRuby = Slots(r, "gbaRuby"),
                    GbaSapphire = Slots(r, "gbaSapp"),
                    GbaEmerald = Slots(r, "gbaEme"),
                    GbaFireRed = Slots(r, "gbaFire"),
                    GbaLeafGreen = Slots(r, "gbaLeaf"),
                    WaterRate = J.Int(r, "encRate_wat"),
                    Water = Slots(r, "water_mons"),
                    OldRodRate = J.Int(r, "encRate_turi_boro"),
                    OldRod = Slots(r, "boro_mons"),
                    GoodRodRate = J.Int(r, "encRate_turi_ii"),
                    GoodRod = Slots(r, "ii_mons"),
                    SuperRodRate = J.Int(r, "encRate_sugoi"),
                    SuperRod = Slots(r, "sugoi_mons"),
                });
            }
            foreach (var r in J.Array(data, "urayama")) t.UnderRoadMonsters.Add(J.Int(r, "monsNo"));
            foreach (var r in J.Array(data, "mistu"))
            {
                t.Honey.Add(new HoneyEncounterRecord
                {
                    Rate = J.Int(r, "Rate"), Normal = J.Int(r, "Normal"), Rare = J.Int(r, "Rare"), SuperRare = J.Int(r, "SuperRare"),
                });
            }
            foreach (var r in J.Array(data, "honeytree"))
                t.HoneyTrees.Add(new HoneyTreeEncounterRecord { Normal = J.Int(r, "Normal"), Rare = J.Int(r, "Rare") });
            foreach (var r in J.Array(data, "safari")) t.SafariMonsters.Add(J.Int(r, "MonsNo"));
            foreach (var r in J.Array(data, "mvpoke"))
            {
                t.Roaming.Add(new RoamingZoneRecord
                {
                    ZoneId = J.Int(r, "zoneID"), NextCount = J.Int(r, "nextCount"), NextZoneIds = J.IntArray(r, "nextZoneID"),
                });
            }
            foreach (var r in J.Array(data, "legendpoke"))
            {
                t.FixedEncounters.Add(new FixedEncounterRecord
                {
                    MonsNo = J.Int(r, "monsNo"),
                    FormNo = J.Int(r, "formNo"),
                    IsFixedEncounterSequence = J.Bool(r, "isFixedEncSeq"),
                    EncounterSequence = J.Str(r, "encSeq"),
                    IsFixedBgm = J.Bool(r, "isFixedBGM"),
                    BgmEvent = J.Str(r, "bgmEvent"),
                    IsFixedBattleBackground = J.Bool(r, "isFixedBtlBg"),
                    BattleBackground = J.Int(r, "btlBg"),
                    IsFixedSetupEffect = J.Bool(r, "isFixedSetupEffect"),
                    SetupEffect = J.Int(r, "setupEffect"),
                    Moves = new[] { J.Int(r, "waza1"), J.Int(r, "waza2"), J.Int(r, "waza3"), J.Int(r, "waza4") },
                });
            }
            foreach (var r in J.Array(data, "zui"))
                t.ZuiForms.Add(new ZuiFormRecord { ZoneId = J.Int(r, "zoneID"), Forms = J.BoolArray(r, "form") });
            return t;
        }

        static EncounterSlot[] Slots(Dictionary<string, object> row, string key)
        {
            var rows = J.Array(row, key);
            var slots = new EncounterSlot[rows.Count];
            for (var i = 0; i < slots.Length; i++)
                slots[i] = new EncounterSlot { MonsNo = J.Int(rows[i], "monsNo"), MinLevel = J.Int(rows[i], "minlv"), MaxLevel = J.Int(rows[i], "maxlv") };
            return slots;
        }

        public static HoneyTreeTables ParseHoneyTrees(string json)
        {
            var data = SingleData(json, "HoneyTree");
            var t = new HoneyTreeTables();
            foreach (var r in J.Array(data, "HoneyTreeIndex"))
                t.Spots.Add(new HoneyTreeSpotRecord { ZoneId = J.Int(r, "ZoneID"), StartFlag = J.Int(r, "HoneyStartFlag"), Position = J.V2(r, "HoneyPosXZ") });
            foreach (var r in J.Array(data, "HoneyTreeShake"))
                t.Shakes.Add(new HoneyTreeShakeRecord { Big = J.Int(r, "Big"), Normal = J.Int(r, "Normal"), None = J.Int(r, "None"), Super = J.Int(r, "Super") });
            return t;
        }

        public static CalendarEncounterTables ParseCalendar(string json)
        {
            var data = SingleData(json, "CalenderEncTable");
            var t = new CalendarEncounterTables();
            foreach (var r in J.Array(data, "data"))
                t.Days.Add(new CalendarEncounterDayRecord { Month = J.Int(r, "month"), Day = J.Int(r, "day"), AddRate = J.Int(r, "add_rate"), AddHatching = J.Int(r, "add_hatching") });
            foreach (var r in J.Array(data, "weather"))
                t.Weather.Add(new CalendarWeatherRecord { Route212b = J.Int(r, "r212b"), Route213 = J.Int(r, "r213"), Route216 = J.Int(r, "r216"), Lake3 = J.Int(r, "l3"), City9 = J.Int(r, "c9") });
            return t;
        }

        // --- 3. Zonen, Karten, Warps ---

        public static MapInfoTables ParseMapInfo(string json)
        {
            var data = SingleData(json, "MapInfo");
            var t = new MapInfoTables();
            foreach (var r in J.Array(data, "ZoneData"))
            {
                var locators = new List<Vec4>();
                foreach (var l in J.Array(r, "Locators"))
                    locators.Add(new Vec4 { X = (float)J.Dbl(l, "x"), Y = (float)J.Dbl(l, "y"), Z = (float)J.Dbl(l, "z"), W = (float)J.Dbl(l, "w") });
                t.Zones.Add(new ZoneInfoRecord
                {
                    DebugCaption = J.Str(r, "Caption"),
                    AreaNameLabel = J.Str(r, "MSLabel"),
                    PokePlaceNameLabel = J.Str(r, "PokePlaceName"),
                    FlyingPlaceNameLabel = J.Str(r, "FlyingPlaceName"),
                    MapType = J.Int(r, "MapType"),
                    IsField = J.Bool(r, "IsField"),
                    LandmarkType = J.Int(r, "LandmarkType"),
                    MiniMapOffset = J.V2(r, "MiniMapOffset"),
                    CanUseBicycle = J.Bool(r, "Bicycle"),
                    CanEscape = J.Bool(r, "Escape"),
                    CanFly = J.Bool(r, "Fly"),
                    BattleSearcher = J.Bool(r, "BattleSearcher"),
                    WalkWithPartner = J.Bool(r, "TureAruki"),
                    KuruKuru = J.Bool(r, "KuruKuru"),
                    Fall = J.Bool(r, "Fall"),
                    BattleBackgrounds = J.IntArray(r, "BattleBg"),
                    ZoneId = J.Int(r, "ZoneID"),
                    AreaId = J.Int(r, "AreaID"),
                    ZoneGridName = J.PptrName(r, "ZoneGrid"),
                    AttributeName = J.PptrName(r, "Attribute"),
                    AttributeExName = J.PptrName(r, "AttributeEx"),
                    SubAttributeName = J.PptrName(r, "SubAttribute"),
                    SubAttributeExName = J.PptrName(r, "SubAttributeEx"),
                    Bgm = J.StrArray(r, "BGM"),
                    EnvironmentalSound = J.Str(r, "EnvironmentalSound"),
                    Weather = J.Int(r, "Weather"),
                    RenderSettingsName = J.PptrName(r, "RenderSettings"),
                    ReflectionCamera = J.Bool(r, "ReflectionCamera"),
                    FixedTime = J.Bool(r, "FixedTime"),
                    AssetBundleName = J.Str(r, "AssetBundleName"),
                    RoomPanCamera = J.Bool(r, "RoomPanCamera"),
                    Locators = locators.ToArray(),
                    Reload = J.Bool(r, "Reload"),
                });
            }
            foreach (var r in J.Array(data, "Camera"))
            {
                t.Cameras.Add(new ZoneCameraRecord
                {
                    AreaId = J.Int(r, "ariaID"),
                    Pitch = (float)J.Dbl(r, "pitch"),
                    Fov = (float)J.Dbl(r, "fov"),
                    TargetRange = (float)J.Dbl(r, "targetRange"),
                    PanDistance = (float)J.Dbl(r, "panDistance"),
                    PanPitch = (float)J.Dbl(r, "panPitch"),
                    PanFov = (float)J.Dbl(r, "panFov"),
                    PanPosUseFlag = J.Bool(r, "panpos_useflag"),
                    PanMinPosY = (float)J.Dbl(r, "panMinposY"),
                    PanMaxPosY = (float)J.Dbl(r, "panMaxposY"),
                    PanMinPosZ = (float)J.Dbl(r, "panMinposZ"),
                    PanMaxPosZ = (float)J.Dbl(r, "panMaxposZ"),
                    DefocusStart = (float)J.Dbl(r, "defocusStart"),
                    DefocusEnd = (float)J.Dbl(r, "defocusEnd"),
                    Distance = (float)J.Dbl(r, "distance"),
                });
            }
            return t;
        }

        public static List<ZoneGridRecord> ParseZoneGrids(string json)
        {
            var list = new List<ZoneGridRecord>();
            foreach (var inst in J.Array(J.Root(json, "ZoneTable"), "instances"))
            {
                var data = J.Obj(inst, "data");
                list.Add(new ZoneGridRecord { Name = J.Str(inst, "name"), Width = J.Int(data, "Width"), ZoneIds = J.IntArray(data, "ZoneIDs") });
            }
            return list;
        }

        public static List<AttributeBlockRecord> ParseAttributeBlocks(string json)
        {
            var list = new List<AttributeBlockRecord>();
            foreach (var inst in J.Array(J.Root(json, "AttributeBlock"), "instances"))
            {
                var data = J.Obj(inst, "data");
                list.Add(new AttributeBlockRecord { Name = J.Str(inst, "name"), Width = J.Int(data, "Width"), Attributes = J.IntArray(data, "Attributes") });
            }
            return list;
        }

        public static List<AttributeMatrixRecord> ParseAttributeMatrices(string json)
        {
            var list = new List<AttributeMatrixRecord>();
            foreach (var inst in J.Array(J.Root(json, "AttributeMatrix"), "instances"))
            {
                var data = J.Obj(inst, "data");
                var blocks = J.Array(data, "AttributeBlocks");
                var names = new string[blocks.Count];
                for (var i = 0; i < names.Length; i++) names[i] = J.PptrNameOf(blocks[i]);
                list.Add(new AttributeMatrixRecord { Name = J.Str(inst, "name"), Width = J.Int(data, "Width"), BlockNames = names });
            }
            return list;
        }

        public static List<MapAttributeCodeRecord> ParseMapAttributeCodes(string json)
        {
            var list = new List<MapAttributeCodeRecord>();
            foreach (var r in J.Array(SingleData(json, "MapAttributeTable"), "Data"))
            {
                list.Add(new MapAttributeCodeRecord
                {
                    Code = J.Int(r, "Code"), Attribute = J.Int(r, "Attribute"), Entry = J.Bool(r, "Entry"),
                    Water = J.Bool(r, "Water"), Encounter = J.Bool(r, "Encount"), FieldEncounterKey = J.Str(r, "FieldEncount"),
                });
            }
            return list;
        }

        public static List<MapWarpSet> ParseMapWarps(string json)
        {
            var sets = new List<MapWarpSet>();
            foreach (var inst in J.Array(J.Root(json, "MapWarp"), "instances"))
            {
                var set = new MapWarpSet { Name = J.Str(inst, "name") };
                foreach (var r in J.Array(J.Obj(inst, "data"), "Data"))
                {
                    set.Warps.Add(new MapWarpRecord
                    {
                        Position = J.V3(r, "Position"),
                        GroupId = J.Int(r, "GruopID"),
                        Size = J.V2(r, "Size"),
                        WarpZone = J.Int(r, "WarpZone"),
                        WarpIndex = J.Int(r, "WarpIndex"),
                        InputDirection = J.Int(r, "InputDir"),
                        FlagIndex = J.Int(r, "FlagIndex"),
                        ScriptLabel = J.Int(r, "ScriptLabel"),
                        ExitLabel = J.Int(r, "ExitLabel"),
                        ConnectionName = J.Str(r, "ConnectionName"),
                    });
                }
                sets.Add(set);
            }
            return sets;
        }

        // --- 4. Shops ---

        public static ShopTables ParseShops(string json)
        {
            var data = SingleData(json, "ShopTable");
            var t = new ShopTables();
            foreach (var r in J.Array(data, "FS"))
                t.FriendlyShop.Add(new ShopEntryRecord { ItemNo = J.Int(r, "ItemNo"), BadgeNum = J.Int(r, "BadgeNum"), ZoneId = J.Int(r, "ZoneID") });
            foreach (var r in J.Array(data, "FixedShop"))
                t.FixedShop.Add(new ShopEntryRecord { ItemNo = J.Int(r, "ItemNo"), ShopId = J.Int(r, "ShopID") });
            foreach (var r in J.Array(data, "BPShop"))
                t.BpShop.Add(new ShopEntryRecord { ItemNo = J.Int(r, "ItemNo"), ShopId = J.Int(r, "NPCID") });
            return t;
        }

        // --- 5. Lern- und Entwicklungslisten ---

        public static List<EvolutionListRecord> ParseEvolutionLists(string json)
        {
            var list = new List<EvolutionListRecord>();
            foreach (var r in J.Array(SingleData(json, "EvolveTable"), "Evolve"))
            {
                var rec = new EvolutionListRecord { Id = J.Int(r, "id") };
                var ar = J.IntArray(r, "ar");
                if (ar.Length % 5 != 0) throw new FormatException("EvolveTable.ar: Länge " + ar.Length + " ist kein Vielfaches von 5");
                for (var i = 0; i < ar.Length; i += 5)
                    rec.Steps.Add(new EvolutionStepRecord { Method = ar[i], Parameter = ar[i + 1], TargetSpecies = ar[i + 2], TargetForm = ar[i + 3], Level = ar[i + 4] });
                list.Add(rec);
            }
            return list;
        }

        public static List<LearnsetRecord> ParseLearnsets(string json)
        {
            var list = new List<LearnsetRecord>();
            foreach (var r in J.Array(SingleData(json, "WazaOboeTable"), "WazaOboe"))
            {
                var rec = new LearnsetRecord { Id = J.Int(r, "id") };
                var ar = J.IntArray(r, "ar");
                if (ar.Length % 2 != 0) throw new FormatException("WazaOboeTable.ar: ungerade Länge " + ar.Length);
                for (var i = 0; i < ar.Length; i += 2) rec.Moves.Add(new LevelMove { Level = ar[i], MoveNo = ar[i + 1] });
                list.Add(rec);
            }
            return list;
        }

        public static List<EggMoveRecord> ParseEggMoves(string json)
        {
            var list = new List<EggMoveRecord>();
            foreach (var r in J.Array(SingleData(json, "TamagoWazaTable"), "Data"))
                list.Add(new EggMoveRecord { No = J.Int(r, "no"), FormNo = J.Int(r, "formNo"), MoveNos = J.IntArray(r, "wazaNo") });
            return list;
        }

        public static List<GrowthCurveRecord> ParseGrowthCurves(string json)
        {
            var list = new List<GrowthCurveRecord>();
            foreach (var r in J.Array(SingleData(json, "GrowTable"), "Data"))
                list.Add(new GrowthCurveRecord { ExpByLevel = J.IntArray(r, "exps") });
            return list;
        }

        // --- 6. Event-Skripte ---

        public static List<EventScriptFile> ParseEventScripts(string json)
        {
            var files = new List<EventScriptFile>();
            foreach (var inst in J.Array(J.Root(json, "EvData"), "instances"))
            {
                var data = J.Obj(inst, "data");
                var file = new EventScriptFile { Name = J.Str(inst, "name") };
                foreach (var s in J.Array(data, "Scripts"))
                {
                    var script = new EventScript { Label = J.Str(s, "Label") };
                    foreach (var c in J.Array(s, "Commands"))
                    {
                        var cmd = new EventCommand();
                        foreach (var a in J.Array(c, "Arg"))
                            cmd.Args.Add(new EventArgument { Type = J.Int(a, "argType"), Data = J.Int(a, "data") });
                        script.Commands.Add(cmd);
                    }
                    file.Scripts.Add(script);
                }
                foreach (var s in J.StrArray(data, "StrList")) file.Strings.Add(s);
                files.Add(file);
            }
            return files;
        }

        // Daten der einzigen Instanz einer Tabellenklasse.
        static Dictionary<string, object> SingleData(string json, string expectedClass)
        {
            var instances = J.Array(J.Root(json, expectedClass), "instances");
            if (instances.Count != 1) throw new FormatException(expectedClass + ": genau eine Instanz erwartet, gefunden " + instances.Count);
            return J.Obj(instances[0], "data");
        }

        // JSON-Helfer (eigene Kopie, damit MasterDataReader unverändert bleibt).
        static class J
        {
            public static Dictionary<string, object> Root(string json, string expectedClass)
            {
                var root = MiniJson.Parse(json) as Dictionary<string, object>;
                if (root == null) throw new FormatException("Wurzel ist kein JSON-Objekt");
                var cls = Str(root, "class");
                if (cls != expectedClass) throw new FormatException("Klasse '" + cls + "' statt '" + expectedClass + "'");
                return root;
            }

            public static Dictionary<string, object> Obj(Dictionary<string, object> d, string key)
            {
                if (d.TryGetValue(key, out var v) && v is Dictionary<string, object> o) return o;
                throw new FormatException("Objekt '" + key + "' fehlt");
            }

            public static List<Dictionary<string, object>> Array(Dictionary<string, object> d, string key)
            {
                if (!d.TryGetValue(key, out var v) || !(v is List<object> list)) throw new FormatException("Liste '" + key + "' fehlt");
                var result = new List<Dictionary<string, object>>(list.Count);
                foreach (var e in list)
                {
                    if (!(e is Dictionary<string, object> row)) throw new FormatException("Listeneintrag in '" + key + "' ist kein Objekt");
                    result.Add(row);
                }
                return result;
            }

            static object Field(Dictionary<string, object> d, string key)
            {
                if (d.TryGetValue(key, out var v) && v != null) return v;
                throw new FormatException("Feld '" + key + "' fehlt");
            }

            public static int Int(Dictionary<string, object> d, string key) => Convert.ToInt32(Field(d, key));
            public static uint UInt(Dictionary<string, object> d, string key) => Convert.ToUInt32(Field(d, key));
            public static double Dbl(Dictionary<string, object> d, string key) => Convert.ToDouble(Field(d, key));

            public static bool Bool(Dictionary<string, object> d, string key)
            {
                var v = Field(d, key);
                return v is bool b ? b : Convert.ToInt64(v) != 0;
            }

            public static string Str(Dictionary<string, object> d, string key) =>
                Field(d, key) as string ?? throw new FormatException("Feld '" + key + "' ist kein String");

            static List<object> Items(Dictionary<string, object> d, string key) =>
                Field(d, key) as List<object> ?? throw new FormatException("Feld '" + key + "' ist keine Liste");

            public static int[] IntArray(Dictionary<string, object> d, string key)
            {
                var list = Items(d, key);
                var arr = new int[list.Count];
                for (var i = 0; i < arr.Length; i++) arr[i] = Convert.ToInt32(list[i]);
                return arr;
            }

            public static bool[] BoolArray(Dictionary<string, object> d, string key)
            {
                var list = Items(d, key);
                var arr = new bool[list.Count];
                for (var i = 0; i < arr.Length; i++) arr[i] = list[i] is bool b ? b : Convert.ToInt64(list[i]) != 0;
                return arr;
            }

            public static string[] StrArray(Dictionary<string, object> d, string key)
            {
                var list = Items(d, key);
                var arr = new string[list.Count];
                for (var i = 0; i < arr.Length; i++) arr[i] = list[i] as string ?? throw new FormatException("Eintrag in '" + key + "' ist kein String");
                return arr;
            }

            public static Vec2 V2(Dictionary<string, object> d, string key)
            {
                var o = Obj(d, key);
                return new Vec2 { X = (float)Dbl(o, "x"), Y = (float)Dbl(o, "y") };
            }

            public static Vec3 V3(Dictionary<string, object> d, string key)
            {
                var o = Obj(d, key);
                return new Vec3 { X = (float)Dbl(o, "x"), Y = (float)Dbl(o, "y"), Z = (float)Dbl(o, "z") };
            }

            // PPtr-Feld: {"m_FileID","m_PathID"[,"target_class","target_name"]}; "" wenn nicht aufgelöst/leer.
            public static string PptrName(Dictionary<string, object> d, string key) => PptrNameOf(Obj(d, key));

            public static string PptrNameOf(Dictionary<string, object> pptr) =>
                pptr.TryGetValue("target_name", out var v) && v is string s ? s : "";
        }
    }
}
