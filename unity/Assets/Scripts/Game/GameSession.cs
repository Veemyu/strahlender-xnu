using System;
using System.Collections.Generic;
using Xnu.Battle;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.EvScript;
using Xnu.PokePara;
using Xnu.Save;
using Xnu.Text;

namespace Xnu.Game
{
    // Zustand einer Spielsitzung: Spielstand (SaveData), Ereignisvariablen (Work/Flags/Systemflags/Trainer, direkt im Save-Puffer),
    // Beutel, Geld, Team und die Laufzeitwerte, die das Original außerhalb von SaveData hält.
    public sealed class GameSession
    {
        public const int MaxItemCount = 999;
        public const int MaxMoney = 999999;
        public const int FirstBadgeFlag = 0x7C;
        public const int BadgeFlagCount = 8;

        public SaveData Save { get; }
        public EvSaveVariables Vars { get; }
        public IGameData Data { get; }
        public MessageLanguage Language { get; set; } = MessageLanguage.Deu;
        public TagWordBuffer Words { get; } = new TagWordBuffer();
        public BattleRandom Rng { get; private set; }

        public int ZoneId { get; set; }
        public int BeforeZoneId { get; set; }
        // SET_WARP_ID: Rücksetzzone nach einer Niederlage (FieldManager.ZoneChangeSetZenmetu); -1 = nicht gesetzt.
        public int WipeoutZone { get; set; } = -1;
        // PlayerWork.defaultPokeNo: Art des gewählten Starters (0 = noch keiner). [A: liegt hier, nicht im Save-Puffer]
        public int DefaultPokeNo { get; set; }
        // Die drei Starter der Startwahl (FIRST_POKE_SELECT_PROC) [A: aus den Fallunterscheidungen des Skripts d27r0101, nicht aus der Demo gelesen].
        public int[] StarterSpecies { get; set; } = { 387, 390, 393 };
        // Namen, die das Original anderswo hält (nicht in SaveData belegt).
        public string SupportName { get; set; } = "";
        // GameManager.currentPeriodOfDay (0 Morgen … 3 Nacht) [A: Zuordnung der Zahlen]; die Uhr liefert der Aufrufer.
        public int PeriodOfDay { get; set; }
        // ZukanWork: Landesdex freigeschaltet [A: Ort im Save nicht belegt, daher Sitzungswert].
        public bool NationalDex { get; set; }

        public GameSession(SaveData save, IGameData data, ulong seed = 1)
        {
            Save = save ?? throw new ArgumentNullException(nameof(save));
            Data = data ?? throw new ArgumentNullException(nameof(data));
            Vars = new EvSaveVariables(save);
            Rng = new BattleRandom(seed);
        }

        public ulong NextSeed() => Rng.GetValue(0);

        // ---- Geld, Beutel ----

        public int Money => Save.Money;

        // MoneyWork.Add: Ergebnis auf 0..999999 begrenzt.
        public void AddMoney(int delta)
        {
            var v = (long)Save.Money + delta;
            Save.Money = (int)Math.Max(0, Math.Min(MaxMoney, v));
        }

        public int GetItemCount(int itemNo) => itemNo <= 0 || itemNo >= SavePlayerLayout.ItemSlotCount ? 0 : Save.GetItemCount(itemNo);

        // ItemWork.IsAddItem: es passt, wenn der Bestand 999 nicht übersteigt.
        public bool CanAddItem(int itemNo, int count) =>
            itemNo > 0 && itemNo < SavePlayerLayout.ItemSlotCount && count > 0 && Save.GetItemCount(itemNo) + count <= MaxItemCount;

        public bool AddItem(int itemNo, int count)
        {
            if (!CanAddItem(itemNo, count)) return false;
            Save.SetItemCount(itemNo, Save.GetItemCount(itemNo) + count);
            return true;
        }

        public void SubItem(int itemNo, int count)
        {
            if (itemNo <= 0 || itemNo >= SavePlayerLayout.ItemSlotCount || count <= 0) return;
            Save.SetItemCount(itemNo, Math.Max(0, Save.GetItemCount(itemNo) - count));
        }

        // ---- Abzeichen ----

        public int BadgeCount
        {
            get
            {
                var n = 0;
                for (var i = 0; i < BadgeFlagCount; i++) if (Vars.GetSysFlag(FirstBadgeFlag + i)) n++;
                return n;
            }
        }

        // ---- Team ----

        public int PartyCount => Save.PartyCount();

        public PokemonParam GetPartyMember(int index) => Save.GetPartyMember(index);

        public List<PokemonParam> GetParty()
        {
            var list = new List<PokemonParam>();
            for (var i = 0; i < PartyCount; i++) list.Add(Save.GetPartyMember(i));
            return list;
        }

        // Pml.PokeParty.AddMember: false, wenn das Team voll ist (6). Die Ablage in der Box übernimmt das Original an anderer Stelle [offen].
        public bool AddPartyMember(PokemonParam p)
        {
            var list = GetParty();
            if (list.Count >= PokeLayout.PartyCapacity) return false;
            list.Add(p);
            Save.SetParty(list);
            return true;
        }

        // Neues Pokémon für den Spieler (ADD_POKEMON): Art und Stufe aus dem Skript, Zufallswerte aus dem Sitzungs-Zufall [A],
        // Herkunft (Trainer-ID, Name, Ort) wie poketool_poke_memo.SetFromCapture [P, nur Kopfzeile gelesen].
        public PokemonParam CreateOwnPokemon(int monsNo, int level, int heldItem, int form = 0)
        {
            var p = PokemonFactory.CreateWild(Data.Battle, monsNo, form, level, Rng);
            if (heldItem != 0) p.Core.HeldItem = (ushort)heldItem;
            p.Core.TrainerId = Save.TrainerId;
            p.Core.TrainerName = Save.PlayerName;
            return p;
        }

        // Pml.PokeParty.RecoverAll und BoxPokemonWork.RecoverAll (PC_KAIFUKU) [P]: KP voll, PP voll, Zustände weg.
        public void HealAll(bool includeBoxes = true)
        {
            var count = PartyCount;
            for (var i = 0; i < count; i++)
            {
                var p = Save.GetPartyMember(i);
                if (Heal(p)) Save.SetPartyMember(i, p);
            }
            if (!includeBoxes) return;
            var trays = Math.Min(Save.TrayMax(), PokeLayout.TrayCount);
            for (var t = 0; t < trays; t++)
                for (var pos = 0; pos < PokeLayout.TraySlots; pos++)
                {
                    var p = Save.GetBox(t, pos);
                    if (p.IsEmpty) continue;
                    if (Heal(p)) Save.SetBox(t, pos, p);
                }
        }

        bool Heal(PokemonParam p)
        {
            if (p.IsEmpty || p.Core.IsEgg) return false;
            var core = p.Core;
            if (!p.HasCalcData)
            {
                var species = Data.Battle.GetSpecies(core.SpeciesNo, core.FormNo);
                p.RecalculateCalcData(species, Data.Battle.GetGrowth(species.GrowthCurve));
            }
            core.CurrentHp = p.MaxHp;
            core.Sick = 0;
            for (var i = 0; i < 4; i++)
            {
                var mv = core.GetMove(i);
                if (mv == 0) continue;
                var rec = Data.Battle.GetMove(mv);
                if (rec != null) core.SetPp(i, (byte)PokemonParam.MaxPp(rec.BasePp, core.GetPpUps(i)));
            }
            return true;
        }
    }
}
