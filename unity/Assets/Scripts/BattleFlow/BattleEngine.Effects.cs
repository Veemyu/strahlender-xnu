using System;
using System.Collections.Generic;
using Xnu.Battle.Events;

namespace Xnu.Battle.Flow
{
    // Restdauer der Seiteneffekte einer Seite (0 = aus) und Hindernisse.
    public sealed class SideState
    {
        public int Reflect, LightScreen, AuroraVeil, Safeguard, Mist, Tailwind;
        public bool StealthRock, StickyWeb;
        public int Spikes, ToxicSpikes;
        public int WishTurns, WishHeal;
        public int FutureTurns, FutureAttacker;
        public ushort FutureMove;
    }

    public sealed partial class BattleEngine
    {
        public SideState[] Sides { get; } = { new SideState(), new SideState() };
        public int TrickRoomTurns { get; private set; }

        readonly Dictionary<int, EventFactor> _sideFactors = new Dictionary<int, EventFactor>();
        EventFactor _trickRoomFactor;

        // Die Weather-Faehigkeiten und Items haben ihre Wirkung hier (Wirkungs-API der Sections: Schaden, Heilung, Statuswert, Zustand, Item-Verbrauch).
        static EventHandlerTable T(EventId e, EventHandlerDelegate h) => new EventHandlerTable(e, h);

        static EventHandlerTable[] Merge(EventHandlerTable[] original, EventHandlerTable[] extra)
        {
            if (extra == null || extra.Length == 0) return original;
            if (original == null || original.Length == 0) return extra;
            var list = new List<EventHandlerTable>(original);
            foreach (var e in extra)
            {
                bool dup = false;
                foreach (var o in original) if (o.EventId == e.EventId) dup = true;
                if (!dup) list.Add(e);
            }
            return list.ToArray();
        }

        void RegisterAbility(BattleMon mon)
        {
            ushort t = mon.Poke.Tokusei;
            var prio = EventPriority.TOKUSEI;
            var get = TokuseiHandlers.GetHandlerGetFunc(t);
            var table = get != null ? get(ref prio) : null;
            table = Merge(table, AbilityTable(mon, t));
            if (table == null || table.Length == 0) return;
            Events.AddFactor(EventFactorType.TOKUSEI, t, prio, (ushort)mon.Poke.GetValueBase(PokeValueId.AGILITY), mon.Poke.Id, table, (byte)table.Length);
        }

        void RegisterItem(BattleMon mon)
        {
            ushort item = mon.Poke.Item;
            if (item == 0) return;
            var table = ItemHandlers.GetTable(item);
            table = Merge(table, ItemTable(mon, item));
            if (table == null || table.Length == 0) return;
            Events.AddFactor(EventFactorType.ITEM, item, EventPriority.ITEM, (ushort)mon.Poke.GetValueBase(PokeValueId.AGILITY), mon.Poke.Id, table, (byte)table.Length);
        }

        void UnregisterAbility(BattleMon mon) => TokuseiHandlers.Remove(Events, mon.Poke);

        void UnregisterItem(BattleMon mon) => ItemHandlers.Remove(Events, mon.Poke);

        // Ein Handler gehoert dem Pokemon, wenn die Variable seine ID traegt.
        EventHandlerDelegate Own(EventVarLabel owner, Action<EventHandlerArgs, BattleMon> act) =>
            (a, me) => { if (a.GetVar(owner) == me) { var m = FindMon(me); if (m != null) act(a, m); } };

        // ------------------------------------------------------------------------------------------------------
        // Faehigkeiten
        // ------------------------------------------------------------------------------------------------------

        static bool BlocksIntimidate(ushort t) => t == 39 || t == 20 || t == 29 || t == 73 || t == 52 || t == 12;

        EventHandlerTable[] AbilityTable(BattleMon self, ushort t)
        {
            switch (t)
            {
                case 22:     // Bedroher: Angriff der Gegner -1 beim Eintreten (handler_Ikaku_MemberIn)
                    return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => Intimidate(m))) };
                case 2: return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => WeatherByAbility(m, BattleWeather.Rain))) };
                case 45: return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => WeatherByAbility(m, BattleWeather.Sandstorm))) };
                case 70: return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => WeatherByAbility(m, BattleWeather.Sun))) };
                case 117: return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => WeatherByAbility(m, BattleWeather.Hail))) };
                case 33: return SpeedInWeather(BattleWeather.Rain);
                case 34: return SpeedInWeather(BattleWeather.Sun);
                case 146: return Merge(SpeedInWeather(BattleWeather.Sandstorm), WeatherGuard(BattleWeather.Sandstorm));
                case 202: return SpeedInWeather(BattleWeather.Hail);
                case 8: case 159: return WeatherGuard(BattleWeather.Sandstorm);
                case 81: return WeatherGuard(BattleWeather.Hail);
                case 142: return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) => { if (a.GetVar(EventVarLabel.VOLUME) > 0) a.RewriteVar(EventVarLabel.FAIL_FLAG, 1); })) };
                case 98: return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) => { if (a.GetVar(EventVarLabel.VOLUME) > 0) a.RewriteVar(EventVarLabel.FAIL_FLAG, 1); })) };
                case 115: return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) => WeatherRecover(a, m, BattleWeather.Hail, 16))) };
                case 44: return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) => WeatherRecover(a, m, BattleWeather.Rain, 16))) };
                case 87:     // Trockenheit: Regen heilt, Sonne schadet
                    return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) =>
                    {
                        if (Weather.Weather == BattleWeather.Rain) WeatherRecover(a, m, BattleWeather.Rain, 8);
                        else if (Weather.Weather == BattleWeather.Sun) a.RewriteVar(EventVarLabel.VOLUME, (int)FlowRules.QuotMaxHp(m.Poke.MaxHp, 8));
                    })) };
                case 94: return new[] { T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) =>
                    { if (Weather.Weather == BattleWeather.Sun) a.RewriteVar(EventVarLabel.VOLUME, (int)FlowRules.QuotMaxHp(m.Poke.MaxHp, 8)); })) };
                case 61:     // Abgestreift: 30 % Heilung des Hauptzustands am Rundenende
                    return new[] { T(EventId.TURNCHECK_BEGIN, Own(EventVarLabel.POKEID, (a, m) =>
                    {
                        if (m.PokeSick != 0 && Random.IsOccurPercent(30)) { int s = m.PokeSick; Add(LogKind.AbilityActivated, m.PokeId, id: 61); CureLogged(m, s); }
                    })) };
                default: return null;
            }
        }

        EventHandlerTable[] SpeedInWeather(BattleWeather w) => new[]
        {
            T(EventId.CALC_AGILITY, Own(EventVarLabel.POKEID, (a, m) => { if (Weather.Weather == w) a.MulVar(EventVarLabel.RATIO, 0x2000); })),
        };

        EventHandlerTable[] WeatherGuard(BattleWeather w) => new[]
        {
            T(EventId.WEATHER_REACTION, Own(EventVarLabel.POKEID, (a, m) =>
            {
                if (a.GetVar(EventVarLabel.VOLUME) > 0 && a.GetVar(EventVarLabel.WEATHER) == (int)w) a.RewriteVar(EventVarLabel.FAIL_FLAG, 1);
            })),
        };

        void WeatherRecover(EventHandlerArgs a, BattleMon m, BattleWeather w, uint divisor)
        {
            if (a.GetVar(EventVarLabel.WEATHER) != (int)w || m.Poke.IsHpFull) return;
            Recover(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, divisor), LogKind.Recover);
        }

        void Intimidate(BattleMon user)
        {
            var foe = Active(1 - user.Side);
            if (foe.IsFainted) return;
            Add(LogKind.AbilityActivated, user.PokeId, foe.PokeId, 22);
            if (BlocksIntimidate((ushort)foe.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE)) || Sides[foe.Side].Mist > 0) return;
            ChangeRank(foe, 1, -1, user);
        }

        void WeatherByAbility(BattleMon user, BattleWeather w)
        {
            if (Weather.Weather == w) return;
            Weather.Weather = w;
            Weather.TurnMax = DefaultWeatherTurns;
            Weather.Counter = 0;
            Add(LogKind.AbilityActivated, user.PokeId, id: user.Poke.Tokusei);
            Add(LogKind.WeatherStart, user.PokeId, id: (int)w, value: DefaultWeatherTurns);
        }

        // ------------------------------------------------------------------------------------------------------
        // Items
        // ------------------------------------------------------------------------------------------------------

        EventHandlerTable[] ItemTable(BattleMon self, ushort item)
        {
            switch (item)
            {
                case 234:    // Resteverwertung: 1/16 am Rundenende (handler_Tabenokosi_Reaction, Ereignis 145)
                    return new[] { T(EventId.TURNCHECK_BEGIN, Own(EventVarLabel.POKEID, (a, m) =>
                    {
                        if (m.Poke.IsHpFull) return;
                        Add(LogKind.ItemActivated, m.PokeId, id: 234, value: (int)FlowRules.QuotMaxHp(m.Poke.MaxHp, 16));
                        Recover(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, 16), LogKind.Recover);
                    })) };
                case 281:    // Schlickschlecker
                    return new[] { T(EventId.TURNCHECK_BEGIN, Own(EventVarLabel.POKEID, (a, m) =>
                    {
                        if (m.Poke.IsMatchType((int)PokeType.Poison))
                        {
                            if (!m.Poke.IsHpFull) Recover(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, 16), LogKind.Recover);
                        }
                        else DirectDamage(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, 8), LogKind.SickDamage, 281);
                    })) };
                case 272:    // Toxik-Orb
                    return new[] { T(EventId.TURNCHECK_END, Own(EventVarLabel.POKEID, (a, m) =>
                    { if (CanInflict(m, Sick.Poison)) { m.AddSick(Sick.Poison, SickCont.MakeMoudokuCont((uint)m.PokeId)); Add(LogKind.SickAdded, m.PokeId, m.PokeId, Sick.Poison); } })) };
                case 273:    // Heiss-Orb
                    return new[] { T(EventId.TURNCHECK_END, Own(EventVarLabel.POKEID, (a, m) =>
                    { if (CanInflict(m, Sick.Burn)) { m.AddSick(Sick.Burn, SickCont.MakePermanent((uint)m.PokeId)); Add(LogKind.SickAdded, m.PokeId, m.PokeId, Sick.Burn); } })) };
                case 217:    // Spiegelkraft/Egoist-Klaue: Chance auf hohe Sonderprioritaet
                    return new[] { T(EventId.CHECK_SP_PRIORITY, Own(EventVarLabel.POKEID, (a, m) =>
                    {
                        int pct = Data.GetItem(217)?.HoldPower ?? 20;
                        if (Random.IsOccurPercent((uint)pct)) { a.RewriteVar(EventVarLabel.SP_PRIORITY, 2); Add(LogKind.ItemActivated, m.PokeId, id: 217); }
                    })) };
                case 287:    // Wahlschal: Initiative x1,5
                    return new[] { T(EventId.CALC_AGILITY, Own(EventVarLabel.POKEID, (a, m) => a.MulVar(EventVarLabel.RATIO, 0x1800))) };
                case 278:    // Eisenkugel: Initiative x0,5
                    return new[] { T(EventId.CALC_AGILITY, Own(EventVarLabel.POKEID, (a, m) => a.MulVar(EventVarLabel.RATIO, 0x800))) };
                case 155: case 158:   // Orangebeere / Sitrusbeere beim Eintreten
                    return new[] { T(EventId.MEMBER_IN, Own(EventVarLabel.POKEID, (a, m) => CheckBerry(m))) };
                default: return null;
            }
        }

        // CHECK_ITEM_REACTION (180): Heilbeeren, sobald die KP die Schwelle unterschreiten.
        void CheckBerry(BattleMon mon)
        {
            if (mon.IsFainted) return;
            ushort item = mon.Poke.Item;
            var rec = Data.GetItem(item);
            if (rec == null) return;
            uint heal;
            if (item == 158 && mon.Poke.Hp * 2 <= mon.Poke.MaxHp) heal = FlowRules.QuotMaxHp(mon.Poke.MaxHp, 4);
            else if (item == 155 && mon.Poke.Hp * 2 <= mon.Poke.MaxHp) heal = (uint)Math.Max(1, rec.HoldPower);
            else return;
            Add(LogKind.ItemActivated, mon.PokeId, id: item, value: (int)heal);
            ConsumeItem(mon);
            Recover(mon, heal, LogKind.Recover);
        }

        void ConsumeItem(BattleMon mon)
        {
            ushort item = mon.Poke.Item;
            UnregisterItem(mon);
            mon.Poke.Item = 0;
            mon.ItemConsumed = true;
            Add(LogKind.ItemConsumed, mon.PokeId, id: item);
        }

        // ------------------------------------------------------------------------------------------------------
        // Wirkungs-API (Common.Damage / RecoverHP / RankEffect / AddSick)
        // ------------------------------------------------------------------------------------------------------

        void Recover(BattleMon mon, uint amount, LogKind kind)
        {
            if (mon.IsFainted) return;
            uint heal = Math.Min(amount, (uint)(mon.Poke.MaxHp - mon.Poke.Hp));
            if (heal == 0) return;
            mon.Poke.Hp = (ushort)(mon.Poke.Hp + heal);
            Add(kind, mon.PokeId, value: (int)heal, value2: mon.Poke.Hp);
        }

        // Schaden ohne Angreifer (Hindernisse, Gegenstaende); Magic Guard (98) verhindert indirekten Schaden.
        void DirectDamage(BattleMon mon, uint amount, LogKind kind, int id)
        {
            if (mon.IsFainted || amount == 0) return;
            if (mon.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 98) return;
            amount = Math.Min(amount, mon.Poke.Hp);
            mon.Poke.Hp = (ushort)(mon.Poke.Hp - amount);
            Add(kind, mon.PokeId, id: id, value: (int)amount, value2: mon.Poke.Hp);
            if (mon.IsFainted) OnFaint(mon);
            else CheckBerry(mon);
        }

        bool IsFloating(BattleMon m) =>
            m.Poke.IsMatchType((int)PokeType.Flying) || m.Poke.GetValue(PokeValueId.TOKUSEI_EFFECTIVE) == 26 || m.Floating || m.Poke.Item == 541;

        // ------------------------------------------------------------------------------------------------------
        // Seiteneffekte und Hindernisse als SIDE-Faktoren (Handler.Side)
        // ------------------------------------------------------------------------------------------------------

        void AddSideFactor(int side, int effect, EventHandlerTable[] table)
        {
            int key = side * 100 + effect;
            if (_sideFactors.ContainsKey(key)) return;
            var f = Events.AddFactor(EventFactorType.SIDE, (ushort)effect, EventPriority.SIDE, 0, (byte)side, table, (byte)table.Length);
            if (f != null) _sideFactors[key] = f;
        }

        void RemoveSideFactor(int side, int effect)
        {
            int key = side * 100 + effect;
            if (_sideFactors.TryGetValue(key, out var f)) { Events.RemoveFactor(f); _sideFactors.Remove(key); }
        }

        // handler_side_Reflector/HikariNoKabe/AuroraVeil: Schaden gegen die Seite x0,5 (Einzelkampf), einmal je Schlag, nicht bei Volltreffer.
        EventHandlerTable[] WallTable(int kind) => new[]
        {
            T(EventId.WAZA_DMG_PROC3, (a, side) =>
            {
                if (a.GetVar(EventVarLabel.POKEID_DEF) / 6 != side) return;
                int dt = a.GetVar(EventVarLabel.DAMAGE_TYPE);
                if (kind != 3 && dt != kind) return;
                if (a.GetVar(EventVarLabel.CRITICAL_FLAG) != 0) return;
                var flag = dt == 1 ? EventVarLabel.WALL_EFFECT_FLAG_PHYSIC : EventVarLabel.WALL_EFFECT_FLAG_SPECIAL;
                if (a.GetVar(flag) != 0) return;
                a.MulVar(EventVarLabel.RATIO, 0x800);
                a.RewriteVar(flag, 1);
            }),
        };

        EventHandlerTable[] TailwindTable() => new[]
        {
            T(EventId.CALC_AGILITY, (a, side) => { if (a.GetVar(EventVarLabel.POKEID) / 6 == side) a.MulVar(EventVarLabel.RATIO, 0x2000); }),
        };

        // Eintritts-Hindernisse (Ereignis MEMBER_IN): handler_side_Makibisi / Dokubisi / StealthRock / NebaNebaNet.
        EventHandlerTable[] HazardTable(int effect) => new[]
        {
            T(EventId.MEMBER_IN, (a, side) =>
            {
                var m = FindMon(a.GetVar(EventVarLabel.POKEID));
                if (m == null || m.Side != side || m.IsFainted) return;
                var st = Sides[side];
                switch (effect)
                {
                    case SideEffect.Spikes:
                        if (!IsFloating(m) && st.Spikes > 0)
                            DirectDamage(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, st.Spikes == 3 ? 4u : st.Spikes == 2 ? 6u : 8u), LogKind.HazardDamage, effect);
                        break;
                    case SideEffect.ToxicSpikes:
                        if (IsFloating(m) || st.ToxicSpikes == 0) break;
                        if (m.Poke.IsMatchType((int)PokeType.Poison)) { st.ToxicSpikes = 0; RemoveSideFactor(side, effect); Add(LogKind.SideEffectEnd, id: effect, value: side); }
                        else if (CanInflict(m, Sick.Poison))
                        {
                            m.AddSick(Sick.Poison, st.ToxicSpikes >= 2 ? SickCont.MakeMoudokuCont(31) : SickCont.MakePermanent(31));
                            Add(LogKind.SickAdded, m.PokeId, id: Sick.Poison);
                        }
                        break;
                    case SideEffect.StealthRock:
                        if (st.StealthRock)
                        {
                            int aff = TypeAffinity.CalcPair((int)PokeType.Rock, m.Poke.Type1, m.Poke.Type2, m.Poke.TypeEx, Setup.Inverse);
                            uint div = aff >= 1 && aff <= 13 ? StealthRockDivisor[aff - 1] : 8u;
                            DirectDamage(m, FlowRules.QuotMaxHp(m.Poke.MaxHp, div), LogKind.HazardDamage, effect);
                        }
                        break;
                    case SideEffect.StickyWeb:
                        if (st.StickyWeb && !IsFloating(m)) ChangeRank(m, 5, -1, null);
                        break;
                }
            }),
        };

        // DAT_03e59d2c der Binaerdatei: Teiler der Max-KP je Typenwirkung 1..13.
        static readonly uint[] StealthRockDivisor = { 256, 256, 128, 64, 32, 16, 8, 4, 2, 1, 1, 1, 1 };

        bool SetSide(BattleMon user, int side, int effect, int turns)
        {
            var st = Sides[side];
            switch (effect)
            {
                case SideEffect.Reflect: if (st.Reflect > 0) return false; st.Reflect = turns; AddSideFactor(side, effect, WallTable(1)); break;
                case SideEffect.LightScreen: if (st.LightScreen > 0) return false; st.LightScreen = turns; AddSideFactor(side, effect, WallTable(2)); break;
                case SideEffect.AuroraVeil: if (st.AuroraVeil > 0) return false; st.AuroraVeil = turns; AddSideFactor(side, effect, WallTable(3)); break;
                case SideEffect.Safeguard: if (st.Safeguard > 0) return false; st.Safeguard = turns; break;
                case SideEffect.Mist: if (st.Mist > 0) return false; st.Mist = turns; break;
                case SideEffect.Tailwind: if (st.Tailwind > 0) return false; st.Tailwind = turns; AddSideFactor(side, effect, TailwindTable()); break;
                case SideEffect.StealthRock: if (st.StealthRock) return false; st.StealthRock = true; AddSideFactor(side, effect, HazardTable(effect)); break;
                case SideEffect.Spikes: if (st.Spikes >= 3) return false; st.Spikes++; AddSideFactor(side, effect, HazardTable(effect)); break;
                case SideEffect.ToxicSpikes: if (st.ToxicSpikes >= 2) return false; st.ToxicSpikes++; AddSideFactor(side, effect, HazardTable(effect)); break;
                case SideEffect.StickyWeb: if (st.StickyWeb) return false; st.StickyWeb = true; AddSideFactor(side, effect, HazardTable(effect)); break;
                default: return false;
            }
            Add(LogKind.SideEffectStart, user.PokeId, id: effect, value: side, value2: turns);
            return true;
        }

        void EndSide(int side, int effect)
        {
            var st = Sides[side];
            switch (effect)
            {
                case SideEffect.Reflect: st.Reflect = 0; break;
                case SideEffect.LightScreen: st.LightScreen = 0; break;
                case SideEffect.AuroraVeil: st.AuroraVeil = 0; break;
                case SideEffect.Safeguard: st.Safeguard = 0; break;
                case SideEffect.Mist: st.Mist = 0; break;
                case SideEffect.Tailwind: st.Tailwind = 0; break;
                case SideEffect.StealthRock: st.StealthRock = false; break;
                case SideEffect.Spikes: st.Spikes = 0; break;
                case SideEffect.ToxicSpikes: st.ToxicSpikes = 0; break;
                case SideEffect.StickyWeb: st.StickyWeb = false; break;
            }
            RemoveSideFactor(side, effect);
            Add(LogKind.SideEffectEnd, id: effect, value: side);
        }

        // Section_TurnCheck_Side: Restdauer der Seiteneffekte herunterzaehlen; bei 0 endet der Effekt.
        void TurnCheckSide()
        {
            for (int side = 0; side < 2; side++)
            {
                var st = Sides[side];
                if (st.Reflect > 0 && --st.Reflect == 0) EndSide(side, SideEffect.Reflect);
                if (st.LightScreen > 0 && --st.LightScreen == 0) EndSide(side, SideEffect.LightScreen);
                if (st.AuroraVeil > 0 && --st.AuroraVeil == 0) EndSide(side, SideEffect.AuroraVeil);
                if (st.Safeguard > 0 && --st.Safeguard == 0) EndSide(side, SideEffect.Safeguard);
                if (st.Mist > 0 && --st.Mist == 0) EndSide(side, SideEffect.Mist);
                if (st.Tailwind > 0 && --st.Tailwind == 0) EndSide(side, SideEffect.Tailwind);
            }
        }

        // Section_TurnCheck_Field: Bereich der Ordnung (Feldeffekt 1, handler_fld_TrickRoom: Ereignis 19 setzt TRICK_FLAG).
        void TurnCheckField()
        {
            if (TrickRoomTurns > 0 && --TrickRoomTurns == 0) EndTrickRoom();
        }

        void StartTrickRoom(BattleMon user)
        {
            if (TrickRoomTurns > 0) { EndTrickRoom(); return; }
            TrickRoomTurns = 5;
            _trickRoomFactor = Events.AddFactor(EventFactorType.FIELD, FieldEffectNo.TrickRoom, EventPriority.FIELD, 0, 0,
                new[] { T(EventId.CALC_AGILITY, (a, d) => a.RewriteVar(EventVarLabel.TRICK_FLAG, 1)) }, 1);
            Add(LogKind.FieldEffectStart, user.PokeId, id: FieldEffectNo.TrickRoom, value: 5);
        }

        void EndTrickRoom()
        {
            TrickRoomTurns = 0;
            if (_trickRoomFactor != null) Events.RemoveFactor(_trickRoomFactor);
            _trickRoomFactor = null;
            Add(LogKind.FieldEffectEnd, id: FieldEffectNo.TrickRoom);
        }

        // ------------------------------------------------------------------------------------------------------
        // Eintreten und Rundenende-Ereignisse (91-93)
        // ------------------------------------------------------------------------------------------------------

        // MEMBER_IN (108): Hindernisse (SIDE), Faehigkeiten (TOKUSEI), Items (ITEM) in der Reihenfolge ihrer Faktor-Prioritaeten.
        void CallMemberIn(BattleMon mon)
        {
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.CallEvent(EventId.MEMBER_IN);
            Events.VarPop();
        }

        // Section_TurnCheck_Event.Execute @0x2270580: erst ein allgemeiner Aufruf (ID 0x1f), dann je Pokemon in Initiative-Reihenfolge.
        void TurnCheckEvent(EventId id)
        {
            CallTurnCheck(0x1F, id);
            foreach (var mon in FrontByAgility())
            {
                if (mon.IsFainted) continue;
                if (id == EventId.TURNCHECK_BEGIN) ProcessPositionEffects(mon);
                if (mon.IsFainted) continue;
                CallTurnCheck(mon.PokeId, id);
                if (CheckShowdown()) return;
            }
        }

        void CallTurnCheck(int pokeId, EventId id)
        {
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, pokeId);
            Events.CallEvent(id);
            Events.VarPop();
        }

        // Positionseffekte (Wunschtraum, Zukunftsschuss) wirken in Ereignis 145 fuer das Pokemon auf der Position.
        void ProcessPositionEffects(BattleMon mon)
        {
            var st = Sides[mon.Side];
            if (st.WishTurns > 0 && --st.WishTurns == 0)
                Recover(mon, (uint)st.WishHeal, LogKind.Recover);
            if (st.FutureTurns > 0 && --st.FutureTurns == 0)
            {
                var attacker = FindMon(st.FutureAttacker);
                var rec = Data.GetMove(st.FutureMove);
                if (attacker != null && rec != null && !mon.IsFainted) FutureSightHit(attacker, mon, rec);
            }
        }

        // Event_CheckWeatherReaction @0x1e1c3d0: Wetterschaden mit Handler-Reaktion (Ereignis 155).
        uint WeatherReaction(BattleMon mon, BattleWeather weather, uint damage)
        {
            Events.VarPush();
            Events.SetConstValue(EventVarLabel.POKEID, mon.PokeId);
            Events.SetConstValue(EventVarLabel.WEATHER, (int)weather);
            Events.SetRewriteOnceValue(EventVarLabel.FAIL_FLAG, 0);
            Events.SetValue(EventVarLabel.VOLUME, (int)damage);
            Events.CallEvent(EventId.WEATHER_REACTION);
            uint volume = (uint)Events.GetValue(EventVarLabel.VOLUME);
            bool fail = (byte)Events.GetValue(EventVarLabel.FAIL_FLAG) != 0;
            Events.VarPop();
            return fail ? 0 : volume;
        }
    }
}
