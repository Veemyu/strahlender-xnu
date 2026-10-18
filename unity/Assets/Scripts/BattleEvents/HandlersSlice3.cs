using System;
using System.Collections.Generic;
using L = Xnu.Battle.Events.EventVarLabel;

namespace Xnu.Battle.Events
{
    // Bausteine der Handler aus Scheibe 3 (Spezifikation 3, Abschnitt 3): fast alle Handler folgen dem Muster
    // "Besitzer-Variable gleich eigene Pokemon-ID, Bedingung, Variable multiplizieren oder umschreiben".
    static class HandlerKit
    {
        public static EventHandlerTable T(EventId e, EventHandlerDelegate h) => new EventHandlerTable(e, h);

        // Besitzer-Variable (POKEID, POKEID_ATK, POKEID_DEF) muss die eigene ID sein; danach optionale Bedingung und Wirkung.
        public static EventHandlerDelegate When(L owner, Func<EventHandlerArgs, byte, bool> cond, Action<EventHandlerArgs> act) =>
            (a, me) => { if (a.GetVar(owner) == me && (cond == null || cond(a, me))) act(a); };

        public static BattlePoke Me(EventHandlerArgs a, byte me) => a.Env.GetPoke(me);
        public static BattlePoke Foe(EventHandlerArgs a) => a.Env.GetPoke(a.GetVar(L.POKEID_DEF));
        public static bool IsRain(int w) => w == 2 || w == 5;
        public static bool IsShine(int w) => w == 1 || w == 6;
        public static bool Damage(EventHandlerArgs a, int kind) => a.GetVar(L.DAMAGE_TYPE) == kind;

        // MulEventVar-Kurzform und Rewrite mit Byte-Variable (Original: char-Variable; die Summe wird auf 8 Bit gekuerzt, ohne Vorzeichen).
        public static Action<EventHandlerArgs> Mul(L label, int ratio) => a => a.MulVar(label, ratio);
        public static Action<EventHandlerArgs> Set(L label, int value) => a => a.RewriteVar(label, value);
        public static Action<EventHandlerArgs> AddByte(L label, int delta) => a => a.RewriteVar(label, (byte)(a.GetVar(label) + delta));

        // Common.MulWazaBasePower: Attackenkraft (WAZA_POWER) mit einer ganzen Zahl multiplizieren.
        public static void MulBasePower(EventHandlerArgs a, int factor) => a.RewriteVar(L.WAZA_POWER, a.GetVar(L.WAZA_POWER) * factor);
    }

    public static partial class TokuseiHandlers
    {
        static void RegisterSlice3(Dictionary<ushort, HandlerGetFunc> d)
        {
            void Add(ushort no, params EventHandlerTable[] t) => d[no] = (ref EventPriority p) => t;
            var T = new Func<EventId, EventHandlerDelegate, EventHandlerTable>(HandlerKit.T);
            var When = new Func<L, Func<EventHandlerArgs, byte, bool>, Action<EventHandlerArgs>, EventHandlerDelegate>(HandlerKit.When);
            Action<EventHandlerArgs> Mul(L l, int r) => HandlerKit.Mul(l, r);
            Action<EventHandlerArgs> Set(L l, int v) => HandlerKit.Set(l, v);
            bool Weather(EventHandlerArgs a, int w) => a.Env.GetWeather() == w;

            // Stoerfaktor: Besitzer-Pokemon im Angriff, Wirkung auf den Anhaengsel-Wert
            Add(1, T(EventId.WAZA_SHRINK_PER, When(L.POKEID_ATK, (a, m) => (sbyte)a.GetVar(L.ADD_DEFAULT_PER) == 0, Set(L.ADD_PER, 10))));              // Akusyuu
            Add(4, T(EventId.CRITICAL_CHECK, When(L.POKEID_DEF, null, Set(L.FAIL_FLAG, 1))));                                                        // KabutoArmor
            Add(75, T(EventId.CRITICAL_CHECK, When(L.POKEID_DEF, null, Set(L.FAIL_FLAG, 1))));                                                       // KabutoArmor
            Add(8, T(EventId.WAZA_HIT_RATIO, When(L.POKEID_DEF, (a, m) => Weather(a, 4), Mul(L.RATIO, 0xCCD))));                                       // Sunagakure (ohne Wetter-Reaktion 155)
            Add(81, T(EventId.WAZA_HIT_RATIO, When(L.POKEID_DEF, (a, m) => Weather(a, 3), Mul(L.RATIO, 0xCCD))));                                      // Yukigakure (ohne 155)
            EventHandlerDelegate tennoMegumi = When(L.POKEID_ATK, null, a => a.RewriteVar(L.ADD_PER, (int)(((uint)a.GetVar(L.ADD_PER) & 0x7FFF) << 1)));
            Add(32, T(EventId.ADD_SICK, tennoMegumi), T(EventId.ADD_RANK_TARGET, tennoMegumi), T(EventId.SP_ADDITIONAL_PER, tennoMegumi),
                T(EventId.WAZA_SHRINK_PER, When(L.POKEID_ATK, null, Set(L.CRITICAL_FLAG, 1))));                                                    // TennoMegumi
            Add(33, T(EventId.CALC_AGILITY, When(L.POKEID, (a, m) => HandlerKit.IsRain(a.Env.GetLocalWeather(m)), Mul(L.RATIO, 0x2000))));              // Suisui
            Add(34, T(EventId.CALC_AGILITY, When(L.POKEID, (a, m) => HandlerKit.IsShine(a.Env.GetLocalWeather(m)), Mul(L.RATIO, 0x2000))));            // Youryokuso
            Add(146, T(EventId.CALC_AGILITY, When(L.POKEID, (a, m) => Weather(a, 4), Mul(L.RATIO, 0x2000))));                                          // Sunakaki (ohne 155)
            Add(202, T(EventId.CALC_AGILITY, When(L.POKEID, (a, m) => Weather(a, 3), Mul(L.RATIO, 0x2000))));                                          // Yukikaki
            Add(37, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Damage(a, 1), Mul(L.RATIO, 0x2000))));                           // Tikaramoti (Kraftkoloss)
            Add(74, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Damage(a, 1), Mul(L.RATIO, 0x2000))));                           // Tikaramoti (Rohkraft)
            Add(69, T(EventId.CALC_KICKBACK, When(L.POKEID_ATK, null, Set(L.FAIL_FLAG, 1))));                                                         // Isiatama
            Add(77, T(EventId.WAZA_HIT_RATIO, When(L.POKEID_DEF, (a, m) => HandlerKit.Me(a, m).CheckSick(6), Mul(L.RATIO, 0x800))));                   // Tidoriasi
            Add(79, T(EventId.WAZA_POWER, (a, m) =>                                                                                                    // Tousousin
            {
                if (a.GetVar(L.POKEID_ATK) != m) return;
                int sa = (sbyte)HandlerKit.Me(a, m).GetValue(PokeValueId.SEX), sd = (sbyte)HandlerKit.Foe(a).GetValue(PokeValueId.SEX);
                if (sa != 2 && sd != 2) a.MulVar(L.WAZA_POWER_RATIO, sa == sd ? 0x1400 : 0xC00);
            }));
            Add(86, T(EventId.RANKVALUE_CHANGE, When(L.POKEID, (a, m) => a.GetVar(L.STATUS_TYPE) != 9, a => a.RewriteVar(L.VOLUME, a.GetVar(L.VOLUME) << 1)))); // Tanjun
            Add(126, T(EventId.RANKVALUE_CHANGE, When(L.POKEID, (a, m) => a.GetVar(L.STATUS_TYPE) != 9, a => a.RewriteVar(L.VOLUME, -a.GetVar(L.VOLUME))))); // Amanojaku
            Add(89, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => a.Env.WazaHasFlag((ushort)a.GetVar(L.WAZAID), 7), Mul(L.WAZA_POWER_RATIO, 0x1333)))); // TetunoKobusi
            Add(91, T(EventId.TYPEMATCH_RATIO, When(L.POKEID, (a, m) => a.GetVar(L.TYPEMATCH_FLAG) != 0, Set(L.RATIO, 0x2000))));                      // Tekiouryoku
            Add(92, T(EventId.WAZA_HIT_COUNT, When(L.POKEID_ATK, null, Set(L.GEN_FLAG, 1))));                                                         // SkillLink
            Add(97, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => a.GetVar(L.CRITICAL_FLAG) != 0, Mul(L.RATIO, 0x1800))));                   // Sniper
            Add(98, T(EventId.SIMPLE_DAMAGE_ENABLE, When(L.POKEID_DEF, null, Set(L.GEN_FLAG, 0))));                                                   // MagicGuard
            Add(105, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, null, HandlerKit.AddByte(L.CRITICAL_RANK, 1))));                                    // Kyouun
            Add(132, T(EventId.WAZA_DMG_PROC3, (a, m) =>                                                                                               // FriendGuard (NakamaIsiki)
            {
                int def = a.GetVar(L.POKEID_DEF);
                if ((def & 0xFF) != m && a.Env.IsFriend(m, def)) a.MulVar(L.RATIO, 0xC00);
            }));
            Add(134, T(EventId.WEIGHT_RATIO, When(L.POKEID, null, Mul(L.RATIO, 0x2000))));                                                            // HeavyMetal
            Add(135, T(EventId.WEIGHT_RATIO, When(L.POKEID, null, Mul(L.RATIO, 0x800))));                                                             // LightMetal
            Add(136, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_DEF, (a, m) => HandlerKit.Me(a, m).IsHpFull, Mul(L.RATIO, 0x800))));                      // MultiScale
            Add(231, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_DEF, (a, m) => HandlerKit.Me(a, m).IsHpFull, Mul(L.RATIO, 0x800))));                      // MultiScale
            Add(137, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Me(a, m).CheckSick(5) && HandlerKit.Damage(a, 1), Mul(L.WAZA_POWER_RATIO, 0x1800)))); // Dokubousou
            Add(138, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Me(a, m).CheckSick(4) && HandlerKit.Damage(a, 2), Mul(L.WAZA_POWER_RATIO, 0x1800)))); // Netubousou
            Add(147, T(EventId.WAZA_HIT_RATIO, When(L.POKEID_DEF, (a, m) => HandlerKit.Damage(a, 0) && (uint)a.GetVar(L.HIT_PER) > 0x32, Set(L.HIT_PER, 0x32)))); // MilacreSkin
            Add(162, T(EventId.WAZA_HIT_RATIO, (a, m) => { if (a.Env.IsFriend(m, a.GetVar(L.POKEID_ATK))) a.MulVar(L.RATIO, 0x119A); }));            // GoodLuck
            Add(169, T(EventId.DEFENDER_GUARD, When(L.POKEID_DEF, (a, m) => HandlerKit.Damage(a, 1), Mul(L.RATIO, 0x2000))));                         // FurCoat
            Add(181, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => a.GetVar(L.WAZA_TOUCH_FLAG) != 0, Mul(L.WAZA_POWER_RATIO, 0x14CD))));         // KataiTume
            Add(177, T(EventId.GET_WAZA_PRI, When(L.POKEID_ATK, (a, m) => HandlerKit.Me(a, m).IsHpFull && a.GetVar(L.WAZA_TYPE) == 2, a => a.RewriteVar(L.WAZA_PRI, a.GetVar(L.WAZA_PRI) + 1)))); // HayateNoTsubasa
            Add(200, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => a.GetVar(L.WAZA_TYPE) == 8, Mul(L.RATIO, 0x1800))));                     // Haganetukai
            Add(252, T(EventId.WAZA_POWER, (a, m) => { if (a.Env.IsFriend(m, a.GetVar(L.POKEID_ATK)) && a.GetVar(L.WAZA_TYPE) == 8) a.MulVar(L.WAZA_POWER_RATIO, 0x1800); })); // HaganeNoSeisin
            Add(204, T(EventId.WAZA_PARAM, When(L.POKEID, (a, m) => a.Env.WazaHasFlag((ushort)a.GetVar(L.WAZAID), 8), Set(L.WAZA_TYPE, 10))));         // UruoiVoice
            Add(205, T(EventId.GET_WAZA_PRI, When(L.POKEID_ATK, (a, m) => a.Env.WazaHasFlag((ushort)a.GetVar(L.WAZAID), 0xC), a => a.RewriteVar(L.WAZA_PRI, a.GetVar(L.WAZA_PRI) + 3)))); // HealingShift
            Add(196, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).CheckSick(5), Set(L.CRITICAL_RANK, 3))));               // Hitodenasi
            Add(203, T(EventId.WAZA_PARAM, When(L.POKEID, null, Set(L.WAZA_TOUCH_FLAG, 0))));                                                         // Enkaku
            Add(218, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_DEF, null, a =>                                                                           // MohuMohu
            {
                if (a.GetVar(L.WAZA_TOUCH_FLAG) != 0) a.MulVar(L.RATIO, 0x800);
                if ((sbyte)a.GetVar(L.WAZA_TYPE) == 9) a.MulVar(L.RATIO, 0x2000);
            })));
            Add(246, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_DEF, (a, m) => HandlerKit.Damage(a, 2), Mul(L.RATIO, 0x800))));                           // KooriNoRinpun
            Add(217, T(EventId.WAZA_POWER, (a, m) =>                                                                                                   // Battery
            {
                int atk = a.GetVar(L.POKEID_ATK);
                if ((atk & 0xFF) != m && a.Env.IsFriend(m, atk) && HandlerKit.Damage(a, 2)) a.MulVar(L.WAZA_POWER_RATIO, 0x14CD);
            }));
            Add(249, T(EventId.WAZA_POWER, (a, m) =>                                                                                                   // PowerSpot
            {
                int atk = a.GetVar(L.POKEID_ATK);
                if ((atk & 0xFF) != m && a.Env.IsFriend(m, atk)) a.MulVar(L.WAZA_POWER_RATIO, 0x14CD);
            }));
            Add(212, T(EventId.CHECK_ADDSICK_FAIL_STD_SKIP, (a, m) =>                                                                                  // Husyoku (Vergleich als Vorzeichenbyte)
            {
                if ((sbyte)a.GetVar(L.POKEID_ATK) == (sbyte)m && a.GetVar(L.SICKID) == 5) a.RewriteVar(L.GEN_FLAG, 1);
            }));
            Add(198, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetTurnFlag(0x12), Mul(L.RATIO, 0x2000))));              // Harikomi
            Add(233, T(EventId.WAZA_DMG_PROC3, When(L.POKEID_ATK, (a, m) => a.GetVar(L.TYPEAFF) > 7, Mul(L.RATIO, 0x1400))));                          // BrainPrism
            Add(247, T(EventId.CHECK_KINOMI_EFFECT_UP, When(L.POKEID, null, a => { a.RewriteVar(L.KINOMI_EFFECT_UP, 1); a.RewriteVar(L.TOKUSEI_WINDOW_DISPLAY, 1); }))); // Jukusei
            Add(239, T(EventId.CHECK_TEMPT_TARGET_ENABLE, When(L.POKEID, null, Set(L.ENABLE_FLAG, 0))), T(EventId.CHECK_AIM_TARGET_ENABLE, When(L.POKEID, null, Set(L.CAN_AIM_TARGET, 1)))); // ScrewObire
            Add(242, T(EventId.CHECK_TEMPT_TARGET_ENABLE, When(L.POKEID, null, Set(L.ENABLE_FLAG, 0))), T(EventId.CHECK_AIM_TARGET_ENABLE, When(L.POKEID, null, Set(L.CAN_AIM_TARGET, 1)))); // ScrewObire
        }
    }

    public static partial class ItemHandlers
    {
        static void RegisterSlice3(Dictionary<ushort, ItemGetFunc> d)
        {
            void Add(ushort no, params EventHandlerTable[] t) => d[no] = () => t;
            var T = new Func<EventId, EventHandlerDelegate, EventHandlerTable>(HandlerKit.T);
            var When = new Func<L, Func<EventHandlerArgs, byte, bool>, Action<EventHandlerArgs>, EventHandlerDelegate>(HandlerKit.When);
            Action<EventHandlerArgs> Set(L l, int v) => HandlerKit.Set(l, v);
            Action<EventHandlerArgs> Ratio(L l) => a => a.MulVar(l, ItemRatio(a));
            bool Monster(EventHandlerArgs a, byte m, int mons) => HandlerKit.Me(a, m).MonsNo == mons;
            bool Plain(EventHandlerArgs a, byte m) => HandlerKit.Me(a, m).MonsNo == 0x84 && !HandlerKit.Me(a, m).IsTransformed;

            // Typ-Verstaerker (common_PowerUpSpecificType): Attackentyp gleich Typ -> Kraftverhaeltnis gemaess Item-Wert
            foreach (var (no, type) in new (ushort, int)[]
            {
                (222, 6), (237, 4), (238, 5), (239, 11), (240, 16), (241, 1), (242, 12), (233, 8), (243, 10), (244, 2), (246, 14), (247, 7),
                (248, 13), (249, 9), (250, 15), (251, 0), (314, 13), (315, 5), (317, 10), (254, 10), (318, 11), (298, 9), (299, 10), (300, 12),
                (301, 11), (302, 14), (303, 1), (304, 3), (305, 4), (306, 2), (307, 13), (308, 6), (309, 5), (310, 7), (311, 15), (312, 16),
                (313, 8), (644, 17),
            })
            {
                int t = type;
                Add(no, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => (sbyte)a.GetVar(L.WAZA_TYPE) == (sbyte)t, Ratio(L.WAZA_POWER_RATIO))));
            }

            // Wetter-Steine (common_WazaWeatherTurnUp): Wetter gleich -> Dauer = Item-Wert
            foreach (var (no, weather) in new (ushort, int)[] { (284, 1), (285, 2), (282, 3), (283, 4) })
            {
                int w = weather;
                Add(no, T(EventId.WAZA_WEATHER_TURNCNT, When(L.POKEID_ATK, (a, m) => (a.GetVar(L.WEATHER) & 0xFF) == w,
                    a => a.RewriteVar(L.TURN_COUNT, a.Env.GetItemAttackValue(a.MyFactor.SubId)))));
            }

            Add(296, T(EventId.CALC_DRAIN, (a, m) => { if (a.GetVar(L.POKEID_ATK) == m) a.MulVar(L.RATIO, ItemRatio(a)); }));                          // OokinaNekko (Vergleich ohne Wirkung im Original-Rumpf)
            Add(232, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, null, HandlerKit.AddByte(L.CRITICAL_RANK, 1))));                                    // PintLens
            Add(326, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, null, HandlerKit.AddByte(L.CRITICAL_RANK, 1))));                                    // PintLens
            Add(266, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => HandlerKit.Damage(a, 1), Ratio(L.WAZA_POWER_RATIO))));                          // ChikaraNoHachimaki
            Add(276, T(EventId.WAZA_HIT_RATIO, When(L.POKEID_ATK, (a, m) => HandlerKit.Foe(a).GetTurnFlag(1), Ratio(L.RATIO))));                       // FocusLens
            Add(213, T(EventId.WAZA_HIT_RATIO, (a, m) => a.MulVar(L.RATIO, InverseRatio(a, false))));                                                  // HikarinoKona
            Add(255, T(EventId.WAZA_HIT_RATIO, (a, m) => a.MulVar(L.RATIO, InverseRatio(a, true))));                                                   // NonkiNoOkou
            Add(226, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => Monster(a, m, 0x16E) && HandlerKit.Damage(a, 2), a => a.MulVar(L.RATIO, 0x2000)))); // SinkaiNoKiba
            Add(227, T(EventId.DEFENDER_GUARD, When(L.POKEID_DEF, (a, m) => Monster(a, m, 0x16E) && HandlerKit.Damage(a, 2), a => a.MulVar(L.RATIO, 0x2000)))); // SinkaiNoUroko
            Add(258, T(EventId.ATTACKER_POWER, When(L.POKEID_ATK, (a, m) => (HandlerKit.Me(a, m).MonsNo & 0xFFFE) == 0x68 && HandlerKit.Damage(a, 1), a => a.MulVar(L.RATIO, 0x2000)))); // FutoiHone
            Add(257, T(EventId.DEFENDER_GUARD, When(L.POKEID_DEF, (a, m) => Plain(a, m) && HandlerKit.Damage(a, 1), a => a.MulVar(L.RATIO, 0x2000))));  // MetalPowder
            Add(274, T(EventId.CALC_AGILITY, When(L.POKEID, (a, m) => Plain(a, m), a => a.MulVar(L.RATIO, 0x2000))));                                  // SpeedPowder
            Add(259, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, (a, m) => Monster(a, m, 0x53), HandlerKit.AddByte(L.CRITICAL_RANK, 2))));           // Naganegi
            Add(256, T(EventId.CRITICAL_CHECK, When(L.POKEID_ATK, (a, m) => Monster(a, m, 0x71), HandlerKit.AddByte(L.CRITICAL_RANK, 2))));           // LuckyPunch
            Add(225, T(EventId.WAZA_POWER, When(L.POKEID_ATK, (a, m) => (HandlerKit.Me(a, m).MonsNo & 0xFFFE) == 0x17C && ((byte)a.GetVar(L.WAZA_TYPE) | 2) == 0xF,
                a => a.MulVar(L.WAZA_POWER_RATIO, 0x1333))));                                                                                         // KokoroNoSizuku
            Add(215, T(EventId.CALC_AGILITY, When(L.POKEID, null, a => a.MulVar(L.RATIO, 0x800))));                                                    // KyouseiGipusu
            foreach (ushort no in new ushort[] { 289, 290, 291, 292, 293, 294 })
                Add(no, T(EventId.CALC_AGILITY, When(L.POKEID, null, a => a.MulVar(L.RATIO, 0x800))));                                                 // PowerXXX (Kraftband u. a.)
            Add(539, T(EventId.WEIGHT_RATIO, When(L.POKEID, null, a => a.MulVar(L.RATIO, 0x800))));                                                    // Karuisi
            Add(543, T(EventId.CHECK_AFFINITY, When(L.POKEID_DEF, null, Set(L.FLAT_FLAG, 1))));                                                        // NerainoMato
            Add(640, T(EventId.DEFENDER_GUARD, When(L.POKEID_DEF, (a, m) => HandlerKit.Damage(a, 2), a => a.MulVar(L.RATIO, 0x1800))));               // totugekiChokki
            Add(1123, T(EventId.WEATHER_LOCAL_CHECK, When(L.POKEID, (a, m) =>                                                                          // BannouGasa
            {
                uint w = (uint)a.GetVar(L.WEATHER);
                return (w & 0xFF) < 7 && ((1 << (int)(w & 0x1F)) & 0x66) != 0;
            }, Set(L.FAIL_FLAG, 1))));
            Add(879, T(EventId.CHANGE_GROUND_BEFORE, When(L.POKEID, null, HandlerKit.AddByte(L.TURN_COUNT, 3))));                                     // GroundCoat
        }

        // Handler HikarinoKona/NonkiNoOkou: Verhaeltnis (100 - Item-Wert) gleitkomma-gerundet; Nonki mit 16-Bit-Wert und Rundung +0,5 nur bei Wert != 0.
        static int InverseRatio(EventHandlerArgs a, bool wordForm)
        {
            int p = a.Env.GetItemAttackValue(a.MyFactor.SubId);
            if (wordForm)
            {
                ushort v = (ushort)(100 - p);
                float round = v != 0 ? 0.5f : -0.5f;
                return (int)((float)v * 4096.0f + round) / 100;
            }
            float f = (float)(100 - p);
            float rounding = f <= 0.0f ? -0.5f : 0.5f;
            return (int)(f * 4096.0f + rounding) / 100;
        }
    }
}
