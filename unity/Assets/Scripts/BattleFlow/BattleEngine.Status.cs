using System;
using System.Collections.Generic;
using Xnu.Battle.Events;

namespace Xnu.Battle.Flow
{
    public sealed partial class BattleEngine
    {
        // ------------------------------------------------------------------------------------------------------
        // Rundenende (Section_TurnCheck): Wetter -> Zustaende. Ereignisse 145-147, Seiten- und Feldeffekte sind nicht angeschlossen.
        // ------------------------------------------------------------------------------------------------------

        void TurnCheck()
        {
            TurnCheckWeather();
            if (CheckShowdown()) return;
            TurnCheckEvent(EventId.TURNCHECK_BEGIN);       // Ereignis 0x91: Resteverwertung, Wunschtraum, Zukunftsschuss, Abgestreift ...
            if (Phase == BattlePhase.Finished) return;
            TurnCheckSick();
            if (CheckShowdown()) return;
            TurnCheckSide();
            TurnCheckField();
            TurnCheckEvent(EventId.TURNCHECK_END);         // Ereignis 0x92: Toxik-/Heiss-Orb
            if (Phase == BattlePhase.Finished) return;
            TurnCheckEvent(EventId.TURNCHECK_DONE);        // Ereignis 0x93
            if (Phase == BattlePhase.Finished) return;
            CheckShowdown();
        }

        List<BattleMon> FrontByAgility()
        {
            var list = new List<BattleMon>();
            foreach (int side in new[] { PlayerSide, EnemySide })
                if (!Active(side).IsFainted) list.Add(Active(side));
            // Section_GetFrontPokeSetByAgilityOrder + SortByAgility: Gleichstand zieht GetRand(2).
            FlowRules.SortByAgility(list, m => CalcAgility(m), Random);
            return list;
        }

        // ServerCommandExecutor.TurnCheckWeather / FieldStatus.TurnCheckWeather @0x19fa950.
        void TurnCheckWeather()
        {
            if (!Weather.Active) return;
            if (Weather.TurnMax != WeatherState.Permanent)
            {
                Weather.Counter++;
                if (Weather.Counter >= Weather.TurnMax)
                {
                    var ended = Weather.Weather;
                    Weather.Weather = BattleWeather.None;
                    Weather.Counter = 0;
                    Add(LogKind.WeatherEnd, id: (int)ended);
                    return;
                }
            }
            foreach (var mon in FrontByAgility())
            {
                if (mon.IsFainted) continue;
                var p = mon.Poke;
                uint dmg = WeatherChip.Damage(Weather.Weather, p.MaxHp, p.IsMatchType((int)PokeType.Ice), p.IsMatchType((int)PokeType.Rock),
                    p.IsMatchType((int)PokeType.Steel), p.IsMatchType((int)PokeType.Ground));
                dmg = WeatherReaction(mon, Weather.Weather, dmg);       // Ereignis 155: Faehigkeiten heilen, verhindern oder verstaerken
                if (dmg == 0 || mon.IsFainted) continue;
                dmg = Math.Min(dmg, p.Hp);
                p.Hp = (ushort)(p.Hp - dmg);
                Add(LogKind.WeatherDamage, mon.PokeId, id: (int)Weather.Weather, value: (int)dmg, value2: p.Hp);
                if (mon.IsFainted) OnFaint(mon);
            }
        }

        // Section_TurnCheck_Sick.Execute @0x2270720: Reihenfolge der Zustaende nach tables.GetTurnCheckWazaSickByOrder, je Zustand alle Pokemon in Initiative-Reihenfolge.
        void TurnCheckSick()
        {
            var order = FrontByAgility();
            foreach (int sickId in FlowRules.TurnCheckSickOrder)
            {
                foreach (var mon in order)
                {
                    if (mon.IsFainted || Active(mon.Side) != mon) continue;
                    bool active = FlowRules.WazaSickTurnCheck(sickId, ref mon.SickContents[sickId], ref mon.SickCounters[sickId], out bool cured, out ulong before);
                    if (!active) continue;
                    if (cured)
                    {
                        mon.CureSick(sickId);
                        Add(LogKind.SickCured, mon.PokeId, id: sickId);
                        continue;
                    }
                    SickDamage(mon, sickId);
                }
                if (!HasAlive(PlayerSide) || !HasAlive(EnemySide)) return;
            }
        }

        // Section_TurnCheck_Sick.sickDamage @0x22716b0 / cont_Bind.
        void SickDamage(BattleMon mon, int sickId)
        {
            if (sickId == 36) { Recover(mon, FlowRules.QuotMaxHp(mon.Poke.MaxHp, 16), LogKind.Recover); return; }       // Wasserring (cont_AquaRing)
            uint dmg;
            if (sickId == Sick.Bind) dmg = FlowRules.QuotMaxHp(mon.Poke.MaxHp, 8);
            else dmg = FlowRules.CalcSickDamage(sickId, mon.SickContents[sickId], mon.SickCounters[sickId], mon.Poke.MaxHp,
                (ushort)mon.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE), mon.SickContents[Sick.Sleep]);
            if (dmg == 0) return;
            dmg = Math.Min(dmg, mon.Poke.Hp);
            mon.Poke.Hp = (ushort)(mon.Poke.Hp - dmg);
            Add(LogKind.SickDamage, mon.PokeId, id: sickId, value: (int)dmg, value2: mon.Poke.Hp);
            if (mon.IsFainted) OnFaint(mon);
        }
    }
}
