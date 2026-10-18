using System;
using System.Collections.Generic;
using System.IO;

namespace Xnu.Data
{
    // Liest die vom Exporter (scripts/masterdata_export.py) erzeugten JSON-Dateien.
    // Dateiformat: {"class","namespace","assembly","bundle","instances":[{"name","data":{<Feld>:[Zeilen]}}]}.
    public sealed class MasterDataReader
    {
        public const string PersonalPath = "pml_personal/PersonalTable.json";
        public const string WazaPath = "pml_personal/WazaTable.json";
        public const string ItemPath = "pml_personal/ItemTable.json";
        public const string EvolvePath = "pml_personal/EvolveTable.json";

        // Felder von SheetItem, die direkt auf Properties abgebildet werden; der Rest landet in Effects.
        static readonly HashSet<string> ItemMapped = new HashSet<string>
        {
            "no", "type", "iconid", "price", "bp_price", "eqp", "atc", "nage_atc", "sizen_atc", "sizen_type",
            "sort", "group", "group_id", "fld_pocket", "field_func", "battle_func", "flags0",
        };

        readonly string _root;

        public MasterDataReader(string rootDirectory)
        {
            _root = rootDirectory ?? throw new ArgumentNullException(nameof(rootDirectory));
        }

        public List<SpeciesRecord> LoadSpecies() => ParseSpecies(Read(PersonalPath));
        public List<MoveRecord> LoadMoves() => ParseMoves(Read(WazaPath));
        public List<ItemRecord> LoadItems() => ParseItems(Read(ItemPath));
        public List<MachineRecord> LoadMachines() => ParseMachines(Read(ItemPath));
        public List<EvolutionRecord> LoadEvolutions() => ParseEvolutions(Read(EvolvePath));

        // languageDirectory: z. B. "msg_english" (siehe Exporter, Option --messages).
        public List<MessageFile> LoadMessages(string languageDirectory) =>
            ParseMessages(Read(languageDirectory + "/MsbtData.json"));

        string Read(string relative)
        {
            var path = Path.Combine(_root, relative);
            if (!File.Exists(path)) throw new FileNotFoundException("Stammdaten-JSON fehlt (Exporter ausführen)", path);
            return File.ReadAllText(path, System.Text.Encoding.UTF8);
        }

        // --- Parser (öffentlich, damit Tests ohne Dateien auskommen) ---

        public static List<SpeciesRecord> ParseSpecies(string json)
        {
            var list = new List<SpeciesRecord>();
            foreach (var r in Rows(json, "PersonalTable", "Personal"))
            {
                list.Add(new SpeciesRecord
                {
                    IsValid = Bool(r, "valid_flag"),
                    Id = Int(r, "id"),
                    DexNo = Int(r, "monsno"),
                    FormIndex = Int(r, "form_index"),
                    FormCount = Int(r, "form_max"),
                    Color = Int(r, "color"),
                    ModelId = Int(r, "gra_no"),
                    BaseHp = Int(r, "basic_hp"),
                    BaseAttack = Int(r, "basic_atk"),
                    BaseDefense = Int(r, "basic_def"),
                    BaseSpeed = Int(r, "basic_agi"),
                    BaseSpAttack = Int(r, "basic_spatk"),
                    BaseSpDefense = Int(r, "basic_spdef"),
                    Type1 = Int(r, "type1"),
                    Type2 = Int(r, "type2"),
                    CatchRate = Int(r, "get_rate"),
                    Rank = Int(r, "rank"),
                    ExpValue = Int(r, "exp_value"),
                    HeldItem1 = Int(r, "item1"),
                    HeldItem2 = Int(r, "item2"),
                    HeldItem3 = Int(r, "item3"),
                    GenderRatio = Int(r, "sex"),
                    EggBirth = Int(r, "egg_birth"),
                    InitialFriendship = Int(r, "initial_friendship"),
                    EggGroup1 = Int(r, "egg_group1"),
                    EggGroup2 = Int(r, "egg_group2"),
                    GrowthCurve = Int(r, "grow"),
                    Ability1 = Int(r, "tokusei1"),
                    Ability2 = Int(r, "tokusei2"),
                    Ability3 = Int(r, "tokusei3"),
                    GiveExp = Int(r, "give_exp"),
                    Height = Int(r, "height"),
                    Weight = Int(r, "weight"),
                    RegionalDexNo = Int(r, "chihou_zukan_no"),
                    MachineMask1 = UInt(r, "machine1"),
                    MachineMask2 = UInt(r, "machine2"),
                    MachineMask3 = UInt(r, "machine3"),
                    MachineMask4 = UInt(r, "machine4"),
                    HiddenMachineMask = UInt(r, "hiden_machine"),
                    EggSpecies = Int(r, "egg_monsno"),
                    EggForm = Int(r, "egg_formno"),
                    EggFormHeldStone = Int(r, "egg_formno_kawarazunoishi"),
                    EggFormInheritHeldStone = Bool(r, "egg_form_inherit_kawarazunoishi"),
                });
            }
            return list;
        }

        public static List<MoveRecord> ParseMoves(string json)
        {
            var list = new List<MoveRecord>();
            foreach (var r in Rows(json, "WazaTable", "Waza"))
            {
                list.Add(new MoveRecord
                {
                    MoveNo = Int(r, "wazaNo"),
                    IsValid = Bool(r, "isValid"),
                    Type = Int(r, "type"),
                    Category = Int(r, "category"),
                    DamageType = Int(r, "damageType"),
                    Power = Int(r, "power"),
                    Accuracy = Int(r, "hitPer"),
                    BasePp = Int(r, "basePP"),
                    Priority = Int(r, "priority"),
                    HitCountMax = Int(r, "hitCountMax"),
                    HitCountMin = Int(r, "hitCountMin"),
                    StatusId = Int(r, "sickID"),
                    StatusChance = Int(r, "sickPer"),
                    StatusContinuation = Int(r, "sickCont"),
                    StatusTurnMin = Int(r, "sickTurnMin"),
                    StatusTurnMax = Int(r, "sickTurnMax"),
                    CriticalRank = Int(r, "criticalRank"),
                    FlinchChance = Int(r, "shrinkPer"),
                    AiSeqNo = Int(r, "aiSeqNo"),
                    DamageRecoverRatio = Int(r, "damageRecoverRatio"),
                    HpRecoverRatio = Int(r, "hpRecoverRatio"),
                    Target = Int(r, "target"),
                    StatStageTypes = new[] { Int(r, "rankEffType1"), Int(r, "rankEffType2"), Int(r, "rankEffType3") },
                    StatStageValues = new[] { Int(r, "rankEffValue1"), Int(r, "rankEffValue2"), Int(r, "rankEffValue3") },
                    StatStageChances = new[] { Int(r, "rankEffPer1"), Int(r, "rankEffPer2"), Int(r, "rankEffPer3") },
                    Flags = UInt(r, "flags"),
                    ContestMoveNo = UInt(r, "contestWazaNo"),
                });
            }
            return list;
        }

        public static List<ItemRecord> ParseItems(string json)
        {
            var list = new List<ItemRecord>();
            foreach (var r in Rows(json, "ItemTable", "Item"))
            {
                var item = new ItemRecord
                {
                    ItemNo = Int(r, "no"),
                    Type = Int(r, "type"),
                    IconId = Int(r, "iconid"),
                    Price = Int(r, "price"),
                    BpPrice = Int(r, "bp_price"),
                    HoldEffect = Int(r, "eqp"),
                    HoldPower = Int(r, "atc"),
                    ThrowPower = Int(r, "nage_atc"),
                    NaturalGiftPower = Int(r, "sizen_atc"),
                    NaturalGiftType = Int(r, "sizen_type"),
                    Sort = Int(r, "sort"),
                    Group = Int(r, "group"),
                    GroupId = Int(r, "group_id"),
                    FieldPocket = Int(r, "fld_pocket"),
                    FieldFunc = Int(r, "field_func"),
                    BattleFunc = Int(r, "battle_func"),
                    Flags = UInt(r, "flags0"),
                };
                foreach (var kv in r)
                {
                    if (!ItemMapped.Contains(kv.Key) && kv.Value != null) item.Effects[kv.Key] = Convert.ToInt32(kv.Value);
                }
                list.Add(item);
            }
            return list;
        }

        public static List<MachineRecord> ParseMachines(string json)
        {
            var list = new List<MachineRecord>();
            foreach (var r in Rows(json, "ItemTable", "WazaMachine"))
                list.Add(new MachineRecord { ItemNo = Int(r, "itemNo"), MachineNo = Int(r, "machineNo"), MoveNo = Int(r, "wazaNo") });
            return list;
        }

        public static List<EvolutionRecord> ParseEvolutions(string json)
        {
            var list = new List<EvolutionRecord>();
            foreach (var r in Rows(json, "EvolveTable", "Evolve"))
                list.Add(new EvolutionRecord { Id = Int(r, "id"), Values = IntArray(r, "ar") });
            return list;
        }

        public static List<MessageFile> ParseMessages(string json)
        {
            var files = new List<MessageFile>();
            foreach (var inst in Instances(Root(json, "MsbtData")))
            {
                var data = Obj(inst, "data");
                var file = new MessageFile
                {
                    Name = Str(inst, "name"),
                    Hash = Int(data, "hash"),
                    LangId = Int(data, "langID"),
                    IsResident = Bool(data, "isResident"),
                    IsKanji = Bool(data, "isKanji"),
                };
                foreach (var l in Array(data, "labelDataArray"))
                {
                    var label = new MessageLabel
                    {
                        LabelIndex = Int(l, "labelIndex"),
                        ArrayIndex = Int(l, "arrayIndex"),
                        Name = Str(l, "labelName"),
                    };
                    foreach (var w in Array(l, "wordDataArray"))
                    {
                        label.Words.Add(new MessageWord
                        {
                            PatternId = Int(w, "patternID"),
                            EventId = Int(w, "eventID"),
                            TagIndex = Int(w, "tagIndex"),
                            TagValue = (float)Dbl(w, "tagValue"),
                            Text = Str(w, "str"),
                            Width = (float)Dbl(w, "strWidth"),
                        });
                    }
                    file.Labels.Add(label);
                }
                files.Add(file);
            }
            return files;
        }

        // --- JSON-Helfer ---

        static Dictionary<string, object> Root(string json, string expectedClass)
        {
            var root = MiniJson.Parse(json) as Dictionary<string, object>;
            if (root == null) throw new FormatException("Wurzel ist kein JSON-Objekt");
            var cls = Str(root, "class");
            if (cls != expectedClass) throw new FormatException("Klasse '" + cls + "' statt '" + expectedClass + "'");
            return root;
        }

        static List<Dictionary<string, object>> Instances(Dictionary<string, object> root) => Array(root, "instances");

        // Zeilen eines Sheets einer einzelnen Tabelle (genau eine Instanz erwartet).
        static List<Dictionary<string, object>> Rows(string json, string expectedClass, string sheet)
        {
            var instances = Instances(Root(json, expectedClass));
            if (instances.Count != 1) throw new FormatException(expectedClass + ": genau eine Instanz erwartet, gefunden " + instances.Count);
            return Array(Obj(instances[0], "data"), sheet);
        }

        static Dictionary<string, object> Obj(Dictionary<string, object> d, string key)
        {
            if (d.TryGetValue(key, out var v) && v is Dictionary<string, object> o) return o;
            throw new FormatException("Objekt '" + key + "' fehlt");
        }

        static List<Dictionary<string, object>> Array(Dictionary<string, object> d, string key)
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

        static int Int(Dictionary<string, object> d, string key) => Convert.ToInt32(Field(d, key));
        static uint UInt(Dictionary<string, object> d, string key) => Convert.ToUInt32(Field(d, key));
        static double Dbl(Dictionary<string, object> d, string key) => Convert.ToDouble(Field(d, key));

        static bool Bool(Dictionary<string, object> d, string key)
        {
            var v = Field(d, key);
            return v is bool b ? b : Convert.ToInt64(v) != 0;
        }

        static string Str(Dictionary<string, object> d, string key) =>
            Field(d, key) as string ?? throw new FormatException("Feld '" + key + "' ist kein String");

        static int[] IntArray(Dictionary<string, object> d, string key)
        {
            if (!(Field(d, key) is List<object> list)) throw new FormatException("Feld '" + key + "' ist keine Liste");
            var arr = new int[list.Count];
            for (var i = 0; i < arr.Length; i++) arr[i] = Convert.ToInt32(list[i]);
            return arr;
        }
    }
}
