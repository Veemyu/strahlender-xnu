using System;
using Xnu.Save;

namespace Xnu.PokePara
{
    // Ergebnis von PokeSaveSlots.Verify: nur Zahlen.
    public readonly struct SlotReport
    {
        public int PartySlots { get; }
        public int BoxSlots { get; }
        public int NonEmptySlots { get; }
        public int ValidChecksums { get; }
        public int IdenticalAfterRoundTrip { get; }

        public SlotReport(int partySlots, int boxSlots, int nonEmptySlots, int validChecksums, int identicalAfterRoundTrip)
        {
            PartySlots = partySlots;
            BoxSlots = boxSlots;
            NonEmptySlots = nonEmptySlots;
            ValidChecksums = validChecksums;
            IdenticalAfterRoundTrip = identicalAfterRoundTrip;
        }

        public int TotalSlots => PartySlots + BoxSlots;
    }

    // Lesen und Schreiben der Pokémon-Slots in SaveData.bin (Party: playerParty, Boxen: boxTray; Version 0x34).
    // Nach Schreibzugriffen muss der Dateihash neu gesetzt werden (SaveWriter.FixHash).
    public static class PokeSaveSlots
    {
        static int PartyBase(byte[] save)
        {
            Require(save);
            SaveLayout.TryGetField("playerParty", out var f);
            return f.Offset;
        }

        static int TrayBase(byte[] save)
        {
            Require(save);
            SaveLayout.TryGetField("boxTray", out var f);
            return f.Offset;
        }

        static void Require(byte[] save)
        {
            if (save == null) throw new ArgumentNullException(nameof(save));
            SaveLayout.TryGetField("boxTray", out var tray);
            if (save.Length < tray.Offset + PokeLayout.TrayCount * PokeLayout.TrayStride)
                throw new SaveFormatException("Spielstand zu kurz für Party und Boxen: " + save.Length + " Byte");
        }

        static int BoxOffset(byte[] save, int tray, int pos)
        {
            if (tray < 0 || tray >= PokeLayout.TrayCount) throw new ArgumentOutOfRangeException(nameof(tray));
            if (pos < 0 || pos >= PokeLayout.TraySlots) throw new ArgumentOutOfRangeException(nameof(pos));
            return TrayBase(save) + tray * PokeLayout.TrayStride + pos * PokeLayout.SlotSize;
        }

        static int PartyOffset(byte[] save, int index)
        {
            if (index < 0 || index >= PokeLayout.PartyCapacity) throw new ArgumentOutOfRangeException(nameof(index));
            return PartyBase(save) + index * PokeLayout.SlotSize;
        }

        public static int PartyCount(byte[] save) => save[PartyBase(save) + PokeLayout.PartyMemberCountOffset];

        public static void SetPartyCount(byte[] save, int count)
        {
            if (count < 0 || count > PokeLayout.PartyCapacity) throw new ArgumentOutOfRangeException(nameof(count));
            save[PartyBase(save) + PokeLayout.PartyMemberCountOffset] = (byte)count;
        }

        public static int PartyMarkingIndex(byte[] save) => save[PartyBase(save) + PokeLayout.PartyMarkingIndexOffset];

        // Anzahl freigeschalteter Ablagen (SaveBoxData.trayMax; Lage 45 Byte vor dem Ende der Struktur, am echten Save bestätigt durch Wert 18).
        public static int TrayMax(byte[] save)
        {
            Require(save);
            SaveLayout.TryGetField("boxData", out var f);
            return save[f.Offset + PokeLayout.BoxDataSize - PokeLayout.BoxDataTrayMaxFromEnd];
        }

        public static PokemonParam ReadParty(byte[] save, int index, bool markBadEggOnMismatch = false) =>
            PokemonParam.FromSlot(save, PartyOffset(save, index), markBadEggOnMismatch);

        public static void WriteParty(byte[] save, int index, PokemonParam pokemon, bool recomputeChecksum = true)
        {
            if (pokemon == null) throw new ArgumentNullException(nameof(pokemon));
            pokemon.EncodeTo(save, PartyOffset(save, index), recomputeChecksum);
        }

        public static PokemonParam ReadBox(byte[] save, int tray, int pos, bool markBadEggOnMismatch = false) =>
            PokemonParam.FromSlot(save, BoxOffset(save, tray, pos), markBadEggOnMismatch);

        public static void WriteBox(byte[] save, int tray, int pos, PokemonParam pokemon, bool recomputeChecksum = true)
        {
            if (pokemon == null) throw new ArgumentNullException(nameof(pokemon));
            pokemon.EncodeTo(save, BoxOffset(save, tray, pos), recomputeChecksum);
        }

        // Liest alle Slots, entschlüsselt, kodiert neu (ohne die Prüfsumme zu ändern) und zählt. Der Spielstand bleibt unverändert;
        // Rückgabe zeigt, wie viele Slots nach Entschlüsseln+Verschlüsseln byte-identisch sind und wie viele Prüfsummen stimmen.
        public static SlotReport Verify(byte[] save)
        {
            Require(save);
            int nonEmpty = 0, valid = 0, identical = 0;
            var scratch = new byte[PokeLayout.SlotSize];
            void Check(int offset)
            {
                var p = PokemonParam.FromSlot(save, offset);
                if (!p.IsEmpty) nonEmpty++;
                if (p.ChecksumValid) valid++;
                p.EncodeTo(scratch, 0, false);
                bool same = true;
                for (int i = 0; i < PokeLayout.SlotSize && same; i++) same = scratch[i] == save[offset + i];
                if (same) identical++;
            }
            for (int i = 0; i < PokeLayout.PartyCapacity; i++) Check(PartyOffset(save, i));
            for (int t = 0; t < PokeLayout.TrayCount; t++)
                for (int s = 0; s < PokeLayout.TraySlots; s++)
                    Check(BoxOffset(save, t, s));
            return new SlotReport(PokeLayout.PartyCapacity, PokeLayout.TrayCount * PokeLayout.TraySlots, nonEmpty, valid, identical);
        }

        // Kopie des Spielstands, in der jeder Slot entschlüsselt und (mit neu berechneter Prüfsumme) wieder verschlüsselt wurde.
        // Bei gültigen Prüfsummen ist das Ergebnis byte-identisch zur Eingabe; den Dateihash fasst die Methode nicht an.
        public static byte[] RewriteAll(byte[] save)
        {
            Require(save);
            var copy = (byte[])save.Clone();
            for (int i = 0; i < PokeLayout.PartyCapacity; i++)
                PokemonParam.FromSlot(copy, PartyOffset(copy, i)).EncodeTo(copy, PartyOffset(copy, i));
            for (int t = 0; t < PokeLayout.TrayCount; t++)
                for (int s = 0; s < PokeLayout.TraySlots; s++)
                {
                    int o = BoxOffset(copy, t, s);
                    PokemonParam.FromSlot(copy, o).EncodeTo(copy, o);
                }
            return copy;
        }
    }
}
