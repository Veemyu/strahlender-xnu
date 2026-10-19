using System;
using System.Collections.Generic;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.Text;

namespace Xnu.Game
{
    // Alles, was der Spielkern an Stammdaten braucht. Die Standardimplementierung (GameData) nimmt fertig geladene Listen,
    // damit Tests mit synthetischen Daten und der lokale Lauf mit den echten Tabellen denselben Code benutzen.
    public interface IGameData
    {
        IBattleData Battle { get; }
        MessageBank Messages { get; }
        TrainerRecord GetTrainer(int trainerId);
        ZoneEncounterRecord GetEncounter(int zoneId);
        // TrainerID-Enum-Name ("LEADER3_01") -> Nummer; < 0 = unbekannt (Quelle: dump.cs, nicht im Repo).
        int ResolveTrainerName(string name);
        // ZoneID-Enum-Name -> Zonennummer; < 0 = unbekannt (Quelle: dump.cs, nicht im Repo).
        int ResolveZoneName(string name);
    }

    public sealed class GameData : IGameData
    {
        readonly Dictionary<int, TrainerRecord> _trainers = new Dictionary<int, TrainerRecord>();
        readonly Dictionary<int, ZoneEncounterRecord> _zones = new Dictionary<int, ZoneEncounterRecord>();
        readonly Dictionary<string, int> _trainerNames = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, int> _zoneNames = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        public IBattleData Battle { get; }
        public MessageBank Messages { get; }

        public GameData(IBattleData battle, MessageBank messages, IEnumerable<TrainerRecord> trainers = null,
            IEnumerable<ZoneEncounterRecord> encounters = null, IReadOnlyDictionary<string, int> trainerNames = null,
            IReadOnlyDictionary<string, int> zoneNames = null)
        {
            Battle = battle ?? throw new ArgumentNullException(nameof(battle));
            Messages = messages ?? new MessageBank();
            if (trainers != null) foreach (var t in trainers) _trainers[t.Id] = t;
            if (encounters != null) foreach (var z in encounters) _zones[z.ZoneId] = z;
            if (trainerNames != null) foreach (var kv in trainerNames) _trainerNames[kv.Key] = kv.Value;
            if (zoneNames != null) foreach (var kv in zoneNames) _zoneNames[kv.Key] = kv.Value;
        }

        public int TrainerCount => _trainers.Count;

        public TrainerRecord GetTrainer(int trainerId) => _trainers.TryGetValue(trainerId, out var t) ? t : null;

        public ZoneEncounterRecord GetEncounter(int zoneId) => _zones.TryGetValue(zoneId, out var z) ? z : null;

        public int ResolveTrainerName(string name) => name != null && _trainerNames.TryGetValue(name, out var id) ? id : -1;

        public int ResolveZoneName(string name) => name != null && _zoneNames.TryGetValue(name, out var id) ? id : -1;
    }
}
