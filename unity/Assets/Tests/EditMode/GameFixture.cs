using System;
using System.Collections.Generic;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.Game;
using Xnu.PokePara;
using Xnu.Save;
using Xnu.Text;

namespace Xnu.Tests
{
    // Synthetische Welt für die Spielkern-Tests: erfundene Arten/Attacken (BattleFlowTestData), erfundene Texte, leerer Save mit einem Teammitglied.
    static class GameFixture
    {
        public const int Starter0 = BattleFlowTestData.Mon1, Starter1 = BattleFlowTestData.Mon2, Starter2 = BattleFlowTestData.Mon3;

        public static BattleData Battle { get; } = BattleFlowTestData.Create();

        public static SaveData NewSave(int partyLevel = 30, int money = 1000)
        {
            var buf = SaveTestSupport.NewSave(7);
            // Variablenbereiche (Work, Flags, Systemflags, Rivale) und Beutel auf null: das Grundrauschen der Hilfsfunktion soll nichts vortäuschen.
            Array.Clear(buf, 0x4, 0x55F4 - 0x4);
            Array.Clear(buf, 0x7D3E0, 8 * EvMemoryVariables.TrainerCount);
            SaveLayout.TryGetField("saveItem", out var items);
            Array.Clear(buf, items.Offset, SavePlayerLayout.ItemSlotCount * SavePlayerLayout.ItemStride);
            var save = SaveData.FromBytes(SaveWriter.FixHash(buf));
            save.PlayerName = "Tester";
            save.RivalName = "Rivale";
            save.Money = money;
            save.SexRaw = 0;
            save.SetParty(new List<PokemonParam> { BattleFlowTestData.Mon(Battle, BattleFlowTestData.Mon1, partyLevel, BattleFlowTestData.Tackle) });
            return save;
        }

        public static MessageBank Messages()
        {
            var bank = new MessageBank();
            var file = new MsbtFile { Name = "german_dp_scenario3", LanguageId = 5 };
            file.Labels.Add(Label(0, "two_pages", Str("Seite eins", MessageEvent.ScrollPage), Str("Seite zwei", MessageEvent.End)));
            file.Labels.Add(Label(1, "hello_name", Str("Hallo ", MessageEvent.None), Tag(0), Str("!", MessageEvent.End)));
            file.Labels[1].Tags = new[] { new MsbtTag { Index = 0, Pattern = TagPattern.Word, GroupId = TagGroup.Name } };
            file.Labels.Add(Label(2, "opt_a", Str("A", MessageEvent.End)));
            file.Labels.Add(Label(3, "opt_b", Str("B", MessageEvent.End)));
            bank.Add(file);
            var items = new MsbtFile { Name = "german_ss_itemname", LanguageId = 5 };
            items.Labels.Add(Label(17, "ITEMNAME_017", Str("Trank", MessageEvent.End)));
            bank.Add(items);
            return bank;
        }

        static MsbtLabel Label(int index, string name, params MsbtWord[] words) => new MsbtLabel { LabelIndex = index, ArrayIndex = index, Name = name, Words = words };

        static MsbtWord Str(string text, MessageEvent ev) => new MsbtWord { Pattern = WordPattern.Str, Text = text, Event = ev };

        static MsbtWord Tag(int tagIndex) => new MsbtWord { Pattern = WordPattern.WordTag, TagIndex = tagIndex };

        public static TrainerRecord Trainer(int id, int monsNo, int level, int gold = 30)
        {
            var party = new TrainerPartyRecord { TrainerId = id };
            party.Members.Add(new TrainerPokemonRecord { Slot = 1, MonsNo = monsNo, Level = level, Moves = new[] { BattleFlowTestData.Tackle, 0, 0, 0 } });
            return new TrainerRecord { Id = id, Gold = gold, Party = party };
        }

        public static GameData Data(IEnumerable<TrainerRecord> trainers = null, IEnumerable<ZoneEncounterRecord> zones = null) =>
            new GameData(Battle, Messages(), trainers, zones,
                new Dictionary<string, int> { ["RIVAL_01"] = 5, ["WEAK_01"] = 6 },
                new Dictionary<string, int> { ["T01R0201"] = 425, ["D27R0101"] = 600 });

        public sealed class World
        {
            public GameSession Session;
            public NullFieldHost Field;
            public GameLoop Loop;
            public AutoPlayer Player = new AutoPlayer();
        }

        public static World NewWorld(EvB.FileBuilder script, int partyLevel = 30, int money = 1000, IEnumerable<TrainerRecord> trainers = null,
            IEnumerable<ZoneEncounterRecord> zones = null)
        {
            var save = NewSave(partyLevel, money);
            var session = new GameSession(save, Data(trainers, zones), 42);
            var field = new NullFieldHost();
            var loop = new GameLoop(session, EvB.Book(script), field) { Record = true };
            return new World { Session = session, Field = field, Loop = loop };
        }

        public static int Run(World w, int maxTicks = 3000) => w.Player.Run(w.Loop, l => l.State == GameState.Field && l.EventsStarted > 0 && !l.Interpreter.IsRunning, maxTicks);
    }
}
