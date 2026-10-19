using System;
using Xnu.Battle;
using Xnu.Data;

namespace Xnu.Game
{
    // Wildbegegnungen. Belegt: die Tabelle je Zone (FieldEncountTable: Raten und Slots mit Art und Stufenspanne, docs/masterdata.md).
    // NICHT belegt [A]: die Auswahlwahrscheinlichkeit je Slot und die Schrittprüfung (Encount/EncountTools sind nicht dekompiliert).
    // Die Gewichte sind die aus den Vorgängerspielen bekannten Reihen; sobald der Pseudocode gelesen ist, genügt es, SlotWeights zu ersetzen.
    public static class EncounterService
    {
        public static readonly int[] GrassWeights = { 20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1 };
        public static readonly int[] WaterWeights = { 60, 30, 5, 4, 1 };
        public static readonly int[] OldRodWeights = { 60, 30, 5, 4, 1 };
        public static readonly int[] GoodRodWeights = { 40, 40, 15, 4, 1 };
        public static readonly int[] SuperRodWeights = { 40, 30, 15, 10, 5 };

        public static int[] WeightsFor(EncounterKind kind)
        {
            switch (kind)
            {
                case EncounterKind.Water: return WaterWeights;
                case EncounterKind.OldRod: return OldRodWeights;
                case EncounterKind.GoodRod: return GoodRodWeights;
                case EncounterKind.SuperRod: return SuperRodWeights;
                default: return GrassWeights;
            }
        }

        public static EncounterSlot[] SlotsFor(ZoneEncounterRecord z, EncounterKind kind)
        {
            switch (kind)
            {
                case EncounterKind.Water: return z.Water;
                case EncounterKind.OldRod: return z.OldRod;
                case EncounterKind.GoodRod: return z.GoodRod;
                case EncounterKind.SuperRod: return z.SuperRod;
                default: return z.Grass;
            }
        }

        public static int RateFor(ZoneEncounterRecord z, EncounterKind kind)
        {
            switch (kind)
            {
                case EncounterKind.Water: return z.WaterRate;
                case EncounterKind.OldRod: return z.OldRodRate;
                case EncounterKind.GoodRod: return z.GoodRodRate;
                case EncounterKind.SuperRod: return z.SuperRodRate;
                default: return z.GrassRate;
            }
        }

        // Wählt den Slot nach Gewicht (Summe der Gewichte der vorhandenen Slots).
        public static int PickSlot(int[] weights, int slotCount, IBattleRandom rng)
        {
            var n = Math.Min(weights.Length, slotCount);
            var total = 0;
            for (var i = 0; i < n; i++) total += weights[i];
            if (total <= 0) return -1;
            var r = (int)rng.GetValue((ulong)total);
            for (var i = 0; i < n; i++)
            {
                if (r < weights[i]) return i;
                r -= weights[i];
            }
            return n - 1;
        }

        // Würfelt eine Begegnung. force = true überspringt die Schrittprüfung (Angel, Ereignis). Rückgabe null: keine Begegnung.
        public static BattleRequest Roll(IGameData data, int zoneId, EncounterKind kind, IBattleRandom rng, bool force = false)
        {
            var zone = data.GetEncounter(zoneId);
            if (zone == null) return null;
            var slots = SlotsFor(zone, kind);
            if (slots == null || slots.Length == 0) return null;
            var rate = RateFor(zone, kind);
            if (!force && (rate <= 0 || (int)rng.GetValue(100) >= rate)) return null;
            var idx = PickSlot(WeightsFor(kind), slots.Length, rng);
            if (idx < 0) return null;
            var slot = slots[idx];
            if (slot.MonsNo <= 0) return null;
            var span = Math.Max(0, slot.MaxLevel - slot.MinLevel);
            var level = slot.MinLevel + (span == 0 ? 0 : (int)rng.GetValue((ulong)(span + 1)));
            return BattleRequest.Wild(slot.MonsNo, Math.Max(1, level));
        }
    }
}
