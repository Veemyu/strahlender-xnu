using System;
using System.Collections.Generic;
using Xnu.PokePara;

namespace Xnu.Game
{
    // Erweiterung Spielkern Scheibe 2: Weltzustand, Uhr, Zugriff auf Team/Box nach Skriptart (tray -1 = Team, sonst Box).
    public sealed partial class GameSession
    {
        public WorldState World { get; } = new WorldState();

        // Zählung wie GET_POKE_COUNT/2/3 (EvDataManager, [P]): alle / ohne Eier / ohne Eier und nicht kampfunfähig.
        public int PartyCountNoEgg()
        {
            var n = 0;
            for (var i = 0; i < PartyCount; i++)
            {
                var p = Save.GetPartyMember(i);
                if (!p.IsEmpty && !p.Core.IsEgg) n++;
            }
            return n;
        }

        public int PartyCountAlive()
        {
            var n = 0;
            for (var i = 0; i < PartyCount; i++)
            {
                var p = Save.GetPartyMember(i);
                if (!p.IsEmpty && !p.Core.IsEgg && p.Core.CurrentHp != 0) n++;
            }
            return n;
        }

        // EvDataManager.GetPokemonParam(tray, pos): tray >= 0 -> Box, sonst Team. null = außerhalb.
        public PokemonParam GetMon(int pos, int tray)
        {
            if (pos < 0) return null;
            if (tray >= 0)
            {
                if (tray >= PokeLayout.TrayCount || pos >= PokeLayout.TraySlots) return null;
                return Save.GetBox(tray, pos);
            }
            return pos < PartyCount ? Save.GetPartyMember(pos) : null;
        }

        public void SetMon(int pos, int tray, PokemonParam p)
        {
            if (tray >= 0) Save.SetBox(tray, pos, p); else Save.SetPartyMember(pos, p);
        }

        // Freie Boxplätze (BoxPokemonWork.GetSpaceCountAll): leere Slots in den freigeschalteten Boxen.
        public int BoxSpaceCount()
        {
            var n = 0;
            var trays = Math.Min(Save.TrayMax(), PokeLayout.TrayCount);
            for (var t = 0; t < trays; t++)
                for (var pos = 0; pos < PokeLayout.TraySlots; pos++)
                    if (Save.GetBox(t, pos).IsEmpty) n++;
            return n;
        }

        // Uhr -> Arbeitswert 0x1A2 und Tageszeit. Die Zahl ist (Wochentag+1)·10^8 + (Monat·100+Tag)·10^4 + Stunde·100 + Minute;
        // gelesen wird nur Wochentag (CHK_WEEK) und Stunde (GET_NOW_HOUR) [P], der Mittelteil ist Annahme [A].
        public void UpdateClock()
        {
            var t = World.Clock();
            var dow = (int)t.DayOfWeek;
            var v = (dow + 1) * 100000000 + (t.Month * 100 + t.Day) * 10000 + t.Hour * 100 + t.Minute;
            Vars.SetWork(WorldState.ClockWork, v);
            PeriodOfDay = PeriodForHour(t.Hour);
        }

        // 0 Morgen 4-9, 1 Tag 10-16, 2 Abend 17-19, 3 Nacht 20-3 [A: Zuordnung wie in den Vorgängerspielen].
        public static int PeriodForHour(int hour)
        {
            if (hour >= 4 && hour < 10) return 0;
            if (hour >= 10 && hour < 17) return 1;
            if (hour >= 17 && hour < 20) return 2;
            return 3;
        }

        // Rivale/Begleiter wählen die Art, die gegen die Wahl des Spielers gewinnt bzw. die übrige [A: aus dem Startersystem der Vorgänger].
        public int RivalPokeNo => World.RivalPokeNo != 0 ? World.RivalPokeNo : StarterCounter(DefaultPokeNo, 1);

        public int SupportPokeNo => World.SupportPokeNo != 0 ? World.SupportPokeNo : StarterCounter(DefaultPokeNo, 2);

        int StarterCounter(int own, int step)
        {
            var s = StarterSpecies;
            for (var i = 0; i < s.Length; i++)
                if (s[i] == own) return s[(i + step) % s.Length];
            return s.Length > 0 ? s[0] : 0;
        }
    }
}
