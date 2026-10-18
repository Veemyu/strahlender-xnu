using System;
using System.Collections.Generic;
using L = Xnu.Battle.Events.EventVarLabel;

namespace Xnu.Battle.Events
{
    // Attacken-Handler (Handler.Waza, Spezifikation 3, Abschnitt 5): nur Sondereffekte; Standardwirkungen
    // (Statuswerte, Zustaende, Prioritaet) stehen in der WazaTable und brauchen keinen Handler.
    public static class WazaHandlers
    {
        static readonly Dictionary<ushort, Func<EventHandlerTable[]>> Funcs = new Dictionary<ushort, Func<EventHandlerTable[]>>();

        // common-Tabelle von handler_AsaNoHizasi: Heilungsanteil je Wetter 1..6 (Sonne, Regen, Schnee, Sand, Starkregen, Extremsonne).
        static readonly int[] MorningSunRatio = { 0xAAC, 0x400, 0x400, 0x400, 0x400, 0xAAC };

        static WazaHandlers()
        {
            void Add(ushort no, params EventHandlerTable[] t) => Funcs[no] = () => t;
            var T = new Func<EventId, EventHandlerDelegate, EventHandlerTable>(HandlerKit.T);
            var When = new Func<L, Func<EventHandlerArgs, byte, bool>, Action<EventHandlerArgs>, EventHandlerDelegate>(HandlerKit.When);
            Action<EventHandlerArgs> Set(L l, int v) => HandlerKit.Set(l, v);

            Add(371, T(EventId.WAZA_POWER_BASE, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetTurnFlag(1), a => HandlerKit.MulBasePower(a, 2))));      // Sippegaesi
            Add(372, T(EventId.WAZA_POWER_BASE, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetTurnFlag(2), a => HandlerKit.MulBasePower(a, 2))));      // Dameosi
            foreach (ushort no in new ushort[] { 754, 755 })
                Add(no, T(EventId.WAZA_POWER_BASE, When(L.POKEID_ATK, (a, m) => !HandlerKit.Foe(a).GetTurnFlag(1), a => HandlerKit.MulBasePower(a, 2)))); // DengekiKutibasi
            Add(512, T(EventId.WAZA_POWER_BASE, When(L.POKEID_ATK, (a, m) => HandlerKit.Me(a, m).Item == 0, a => HandlerKit.MulBasePower(a, 2))));         // Acrobat
            Add(474, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).CheckSick(5), a => a.MulVar(L.WAZA_POWER_RATIO, 0x2000))));      // BenomShock
            Add(788, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => a.Env.IsFieldEffectActive(2), a => a.MulVar(L.WAZA_POWER_RATIO, 0x1800))));       // Newton
            Add(74, T(EventId.GET_RANKEFF_VALUE, When(L.POKEID_ATK, (a, m) => HandlerKit.IsShine(a.Env.GetLocalWeather(m)),
                a => { int v = a.GetVar(L.VOLUME); a.RewriteVar(L.VOLUME, v == 1 ? 2 : v); })));                                                          // Seityou
            foreach (ushort no in new ushort[] { 246, 702 })
                Add(no, T(EventId.GET_RANKEFF_VALUE, (a, m) =>                                                                                            // GensiNoTikara
                {
                    if (a.GetVar(L.POKEID_DEF) == m && a.GetVar(L.POKEID_ATK) == m) a.RewriteVar(L.STATUS_TYPE, 10);
                }));
            Add(599, T(EventId.GET_RANKEFF_VALUE, When(L.POKEID_ATK, (a, m) => !HandlerKit.Foe(a).CheckSick(5), Set(L.STATUS_TYPE, 0))));                  // BenomTrap
            foreach (ushort no in new ushort[] { 602, 674 })
                Add(no, T(EventId.GET_RANKEFF_VALUE, When(L.POKEID_ATK, (a, m) => (uint)(HandlerKit.Foe(a).GetValue(PokeValueId.TOKUSEI_EFFECTIVE) - 0x39) > 1, Set(L.STATUS_TYPE, 0)))); // ZibaSousa
            Add(86, T(EventId.CHECK_AFFINITY_ENABLE, When(L.POKEID_ATK, null, Set(L.GEN_FLAG, 1))));                                                      // Denjiha
            foreach (ushort no in new ushort[] { 473, 540, 548 })
                Add(no, T(EventId.DEFENDER_GUARD_PREV, When(L.POKEID_ATK, (a, m) => a.GetVar(L.VID) == 0xB, a => a.RewriteVar(L.VID_SWAP_CNT, a.GetVar(L.VID_SWAP_CNT) + 1)))); // PsycoShock
            Add(776, T(EventId.ATTACKER_POWER_VID, When(L.POKEID_ATK, null, Set(L.VID, 9))));                                                             // BodyPress
            Add(213, T(EventId.NOEFFECT_CHECK_L2, (a, m) =>                                                                                               // Meromero
            {
                if (a.GetVar(L.POKEID_ATK) != m) return;
                int sa = (sbyte)HandlerKit.Me(a, m).GetValue(PokeValueId.SEX), sd = (sbyte)HandlerKit.Foe(a).GetValue(PokeValueId.SEX);
                if (sa == sd || sa == 2 || sd == 2) a.RewriteVar(L.NOEFFECT_FLAG, 1);
            }));
            foreach (ushort no in new ushort[] { 234, 235, 236 })
                Add(no, T(EventId.RECOVER_HP_RATIO, When(L.POKEID_ATK, null, a =>                                                                         // AsaNoHizasi
                {
                    int w = a.Env.GetLocalWeather(a.GetVar(L.POKEID_ATK));
                    a.RewriteVar(L.RATIO, (byte)(w - 1) < 6 ? MorningSunRatio[w - 1] : 0x800);
                })));
            Add(659, T(EventId.RECOVER_HP_RATIO, When(L.POKEID_ATK, null, a => a.RewriteVar(L.RATIO, a.Env.GetLocalWeather(a.GetVar(L.POKEID_ATK)) == 4 ? 0xAAC : 0x800)))); // Sunaatume
            foreach (ushort no in new ushort[] { 46, 18 })
                Add(no, T(EventId.PUSHOUT_EFFECT_NO, When(L.POKEID_ATK, null, a => a.RewriteVar(L.EFFECT_NO, a.MyFactor.SubId == 0x2E ? 0x5E : 0x5F))));  // Hoeru
            Add(59, T(EventId.CALC_HIT_CANCEL, When(L.POKEID_ATK, (a, m) => a.Env.GetWeather() == 3, Set(L.GEN_FLAG, 1))));                               // Fubuki
            foreach (ushort no in new ushort[] { 101, 69 })
                Add(no, T(EventId.WAZA_DMG_PROC1, When(L.POKEID_ATK, null, a =>                                                                           // TikyuuNage
                {
                    a.RewriteVar(L.FIX_DAMAGE, HandlerKit.Me(a, (byte)a.GetVar(L.POKEID_ATK)).GetValue(PokeValueId.LEVEL));
                    a.RewriteVar(L.FIX_DAMAGE_FLAG, 1);
                })));
            foreach (ushort no in new ushort[] { 162, 717 })
                Add(no, T(EventId.WAZA_DMG_PROC1, When(L.POKEID_ATK, null, a =>                                                                           // IkariNoMaeba
                {
                    uint half = ((uint)HandlerKit.Foe(a).GetValue(PokeValueId.HP_BEFORE_G) >> 1) & 0x7FFF;
                    a.RewriteVar(L.FIX_DAMAGE, half == 0 ? 1 : (int)half);
                    a.RewriteVar(L.FIX_DAMAGE_FLAG, 1);
                })));
            Add(492, T(EventId.ATTACKER_POWER_PREV, When(L.POKEID_ATK, null, a => a.RewriteVar(L.SWAP_POKEID, a.GetVar(L.POKEID_DEF)))));                 // Ikasama
            foreach (ushort no in new ushort[] { 206, 610 })
                Add(no, T(EventId.KORAERU_CHECK, When(L.POKEID_ATK, (a, m) => a.GetVar(L.GEN_FLAG) != 0, Set(L.KORAERU_CAUSE, 2))));                      // Mineuti
            var freezeDry = When(L.POKEID_ATK, (a, m) => a.GetVar(L.POKE_TYPE) == 10, Set(L.TYPEAFF, 8));
            Add(573, T(EventId.CHECK_AFFINITY, freezeDry), T(EventId.CHECK_AFFINITY_ONLY_ATTACKER, freezeDry));                                         // FreezDry
            Add(329, T(EventId.WAZA_HIT_RATIO_ICHIGEKI, When(L.POKEID_ATK, (a, m) => !HandlerKit.Me(a, m).IsMatchType(14), Set(L.HIT_PER, 0x14))));         // ZettaiReido
            foreach (ushort no in new ushort[] { 744, 781, 782 })
                Add(no, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).IsGMode, a => a.MulVar(L.RATIO, 0x2000))));              // DaiMaxHou
            foreach (ushort no in new ushort[] { 533, 663 })
                Add(no, T(EventId.DEFENDER_GUARD_PREV, When(L.POKEID_ATK, null, Set(L.GEN_FLAG, 1))), T(EventId.WAZA_HIT_RANK, When(L.POKEID_ATK, null, Set(L.FLAT_FLAG, 1)))); // NasiKuzusi
            Add(745, T(EventId.CHECK_TEMPT_TARGET_ENABLE, When(L.POKEID, null, Set(L.ENABLE_FLAG, 0))), T(EventId.CHECK_AIM_TARGET_ENABLE, When(L.POKEID, null, Set(L.CAN_AIM_TARGET, 1)))); // NeraiUti

            // Doppelschaden gegen Ziele in der Schutzphase (Dauerflag des Ziels); checkHide hebt das Ausweichen auf
            EventHandlerTable Hide(int hide) => T(EventId.CHECK_POKE_HIDE, When(L.POKEID_ATK, (a, m) => a.GetVar(L.POKE_HIDE) == hide, Set(L.AVOID_FLAG, 0)));
            Add(89, Hide(5), T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetContFlag(5), a => a.MulVar(L.RATIO, 0x2000))));              // Jisin
            foreach (ushort no in new ushort[] { 16, 239 })
                Add(no, Hide(3), T(EventId.WAZA_POWER_BASE, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetContFlag(3), a => HandlerKit.MulBasePower(a, 2))));    // Tatumaki
            Add(57, Hide(4), T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetContFlag(4), a => a.MulVar(L.RATIO, 0x2000))));              // Naminori
            foreach (ushort no in new ushort[] { 23, 34, 407 })
                Add(no, T(EventId.CALC_HIT_CANCEL, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetContFlag(8), Set(L.GEN_FLAG, 1))),
                    T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetContFlag(8), a => a.MulVar(L.RATIO, 0x2000))));                      // Fumituke
        }

        public static bool IsImplemented(ushort waza) => Funcs.ContainsKey(waza);

        public static int ImplementedCount => Funcs.Count;

        public static EventHandlerTable[] GetTable(ushort waza) => Funcs.TryGetValue(waza, out var f) ? f() : null;

        // Waza.Add: Faktor WAZA, Hauptprioritaet WAZA, Unterprioritaet vom Aufrufer, dependID = Pokemon-ID.
        public static EventFactor Add(EventSystem es, ushort waza, byte pokeId, uint subPriority)
        {
            var table = GetTable(waza);
            if (table == null) return null;
            return es.AddFactor(EventFactorType.WAZA, waza, EventPriority.WAZA, subPriority, pokeId, table, (byte)table.Length);
        }
    }
}
