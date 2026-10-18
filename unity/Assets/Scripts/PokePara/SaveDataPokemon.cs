using System;
using System.Collections.Generic;
using Xnu.Save;

namespace Xnu.PokePara
{
    // Party und PC-Boxen eines SaveData (Version 0x34) über PokeSaveSlots. Der Hash wird erst in SaveData.ToBytes/Seal gesetzt.
    public static class SaveDataPokemonExtensions
    {
        public static int PartyCount(this SaveData save) => PokeSaveSlots.PartyCount(save.Buffer);

        public static int TrayMax(this SaveData save) => PokeSaveSlots.TrayMax(save.Buffer);

        public static PokemonParam GetPartyMember(this SaveData save, int index) => PokeSaveSlots.ReadParty(save.Buffer, index);

        // Schreibt nur den Slot; die Anzahl bleibt unverändert (siehe SetParty).
        public static void SetPartyMember(this SaveData save, int index, PokemonParam pokemon) =>
            PokeSaveSlots.WriteParty(save.Buffer, index, pokemon);

        // Ersetzt die Party: members[0..n-1] belegt, übrige Slots als kodierte leere Slots, memberCount = n (1..6).
        public static void SetParty(this SaveData save, IReadOnlyList<PokemonParam> members)
        {
            if (members == null) throw new ArgumentNullException(nameof(members));
            if (members.Count < 1 || members.Count > PokeLayout.PartyCapacity)
                throw new ArgumentOutOfRangeException(nameof(members), "Party braucht 1..6 Mitglieder");
            for (var i = 0; i < PokeLayout.PartyCapacity; i++)
                PokeSaveSlots.WriteParty(save.Buffer, i, i < members.Count ? members[i] : PokemonParam.CreateEmpty());
            PokeSaveSlots.SetPartyCount(save.Buffer, members.Count);
        }

        public static PokemonParam GetBox(this SaveData save, int tray, int pos) => PokeSaveSlots.ReadBox(save.Buffer, tray, pos);

        public static void SetBox(this SaveData save, int tray, int pos, PokemonParam pokemon) =>
            PokeSaveSlots.WriteBox(save.Buffer, tray, pos, pokemon);

        public static void ClearBox(this SaveData save, int tray, int pos) =>
            PokeSaveSlots.WriteBox(save.Buffer, tray, pos, PokemonParam.CreateEmpty());

        // Zählt Slots und gültige Prüfsummen (nur Zahlen).
        public static SlotReport VerifySlots(this SaveData save) => PokeSaveSlots.Verify(save.Buffer);
    }
}
