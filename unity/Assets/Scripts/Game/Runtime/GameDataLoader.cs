using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Field;
using Xnu.Text;

namespace Xnu.Game.Unity
{
    // Alles, was der Spielkern aus den lokalen Stammdaten braucht (Ordner <GameData>/masterdata, nie im Repo).
    public sealed class GameBundle
    {
        public GameData Data;
        public EvScriptBook Book;
        public int Trainers, Zones, TextFiles, ScriptFiles, TrainerNames, ZoneNames;
        public double Seconds;

        public override string ToString() =>
            "Stammdaten: " + Trainers + " Trainer, " + Zones + " Zonen mit Begegnungen, " + TextFiles + " Textdateien, " + ScriptFiles + " Skriptdateien, "
            + Book.LabelCount + " Labels, " + TrainerNames + " Trainernamen, " + ZoneNames + " Zonennamen (" + Seconds.ToString("F1") + " s)";
    }

    public static class GameDataLoader
    {
        public const string MessageFile = "msg_german/MsbtData.json";

        public static GameBundle Load(string masterDirectory)
        {
            var sw = Stopwatch.StartNew();
            var r1 = new MasterDataReader(masterDirectory);
            var r2 = new MasterData2Reader(masterDirectory);
            var battle = new BattleData(r1.LoadSpecies(), r1.LoadMoves(), r1.LoadItems(), r2.LoadGrowthCurves(), r2.LoadLearnsets());
            var trainers = r2.LoadTrainers().Trainers;
            var zones = r2.LoadFieldEncounters().Zones;
            var files = r2.LoadEventScripts();
            var book = EvScriptBook.FromFiles(files);

            var bank = new MessageBank();
            var textFiles = 0;
            foreach (var rel in new[] { MessageFile, "msg_common/MsbtData.json" })
            {
                var msgPath = Path.Combine(masterDirectory, rel);
                if (!File.Exists(msgPath)) continue;
                foreach (var f in MsbtJsonReader.Parse(File.ReadAllText(msgPath)))
                {
                    try { bank.Add(f); textFiles++; } catch (ArgumentException) { }
                }
            }

            var trainerNames = new Dictionary<string, int>();
            var zoneNames = new Dictionary<string, int>();
            var namePath = Path.Combine(masterDirectory, ZoneNames.RelativePath);
            if (File.Exists(namePath))
            {
                var json = File.ReadAllText(namePath);
                foreach (var kv in ZoneNames.Parse(json)) zoneNames[kv.Key] = kv.Value;
                ReadEnum(json, "TrainerID", trainerNames);
            }

            var data = new GameData(battle, bank, trainers, zones, trainerNames, zoneNames);
            sw.Stop();
            return new GameBundle
            {
                Data = data, Book = book, Trainers = data.TrainerCount, Zones = zones.Count, TextFiles = textFiles, ScriptFiles = files.Count,
                TrainerNames = trainerNames.Count, ZoneNames = zoneNames.Count, Seconds = sw.Elapsed.TotalSeconds,
            };
        }

        // Liest ein Namensobjekt {"Name": Zahl} unter dem Schlüssel (Ausgabe von scripts/field_zone_names.py).
        public static void ReadEnum(string json, string key, Dictionary<string, int> into)
        {
            if (!(MiniJson.Parse(json) is Dictionary<string, object> root) || !root.TryGetValue(key, out var v) || !(v is Dictionary<string, object> map)) return;
            foreach (var kv in map) into[kv.Key] = Convert.ToInt32(kv.Value, System.Globalization.CultureInfo.InvariantCulture);
        }
    }

    // Namen und Meldungen des Kampfs aus der lokalen Meldungsbank (Spiel-Implementierung von IBattleTexts).
    public sealed class GameBattleTexts : IBattleTexts
    {
        readonly IGameData _data;
        readonly MessageLanguage _language;
        readonly MessageComposer _composer = new MessageComposer();

        public GameBattleTexts(IGameData data, MessageLanguage language)
        {
            _data = data;
            _language = language;
        }

        string Get(string msbt, string label, TagWordBuffer words = null)
        {
            if (!_data.Messages.TryGetLabel(msbt, label, _language, out var l)) return null;
            return _composer.Compose(l, words ?? new TagWordBuffer()).FlatText;
        }

        public string Species(int monsNo) => Get("ss_monsname", "MONSNAME_" + monsNo.ToString("000"));
        public string Move(int moveNo) => Get("ss_wazaname", "WAZANAME_" + moveNo.ToString("000"));
        public string Item(int itemNo) => Get("ss_itemname", "ITEMNAME_" + itemNo.ToString("000"));

        public string Label(string msbt, string label, params string[] words)
        {
            var buffer = new TagWordBuffer();
            for (var i = 0; i < words.Length && i < TagWordBuffer.Size; i++) buffer.SetText(i, words[i]);
            return Get(msbt, label, buffer);
        }
    }
}
