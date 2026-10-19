using System;
using System.Collections.Generic;
using Xnu.Battle.Flow;
using Xnu.Data;
using Xnu.Text;

namespace Xnu.Game
{
    // Prüfstufen wie in den Spezifikationen: P = Handler-Pseudocode gelesen, A = Annahme (Name/Argumentform plus Teilbefund), N = nur Name und Aufrufliste.
    public enum HostEvidence
    {
        P,
        A,
        N,
    }

    public enum HostKind
    {
        State,      // ändert/liest Spielzustand (Work, Team, Beutel, Namenswörter, Kampfwunsch)
        Field,      // an IFieldHost delegiert (Darstellung, Objekte, Kamera, Überblendung)
        Wait,       // wartet auf Eingabe oder Feld
        Sound,      // bewusst ohne Wirkung (Regel "kein Sound")
    }

    public sealed class HostCommand
    {
        public int Id;
        public string Name;
        public HostEvidence Evidence;
        public HostKind Kind;
        internal Func<GameEvHost, EvScript.EvCommandCall, bool> Run;
    }

    // Tabelle der umgesetzten Host-Befehle (Kennung -> Handler). Alles, was hier fehlt, ist eine Lücke (GameEvHost.Gaps).
    public static class HostCommands
    {
        public static readonly Dictionary<int, HostCommand> Table = Build();

        static Dictionary<int, HostCommand> _t;

        static void Reg(int id, string name, HostEvidence ev, HostKind kind, Func<GameEvHost, EvScript.EvCommandCall, bool> run) =>
            _t[id] = new HostCommand { Id = id, Name = name, Evidence = ev, Kind = kind, Run = run };

        static void Visual(int id, string name) => Reg(id, name, HostEvidence.N, HostKind.Field, (h, c) => h.Field.RunVisual(c));

        static void Mute(int id, string name) => Reg(id, name, HostEvidence.A, HostKind.Sound, (h, c) => true);

        static string ObjName(EvScript.EvCommandCall c, int i) => c.Type(i) == (int)EventArgType.String ? c.Str(i) : "#" + c.Int(i);

        static bool Slot(EvScript.EvCommandCall c, out int slot)
        {
            slot = c.Int(1);
            return slot >= 0 && slot < TagWordBuffer.Size;
        }

        static Dictionary<int, HostCommand> Build()
        {
            _t = new Dictionary<int, HostCommand>();
            const HostEvidence P = HostEvidence.P, A = HostEvidence.A;
            const HostKind S = HostKind.State, F = HostKind.Field, W = HostKind.Wait;

            // ---- Namenswörter (MessageWordSetHelper.Set*Word(slot, …)) ----
            Reg(306, "PLAYER_NAME", P, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.Session.Save.PlayerName); return true; });
            Reg(307, "RIVAL_NAME", P, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.Session.Save.RivalName); return true; });
            Reg(308, "SUPPORT_NAME", A, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.Session.SupportName); return true; });
            Reg(309, "POKEMON_NAME", A, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.SpeciesNameText(c.Int(2))); return true; });
            Reg(310, "ITEM_NAME", P, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.ItemNameText(c.Int(2))); return true; });
            Reg(314, "NUMBER_NAME", P, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetNumber(s, c.Int(2)); return true; });
            Reg(318, "NICK_NAME", A, S, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var i = c.Int(2);
                var name = "";
                if (i >= 0 && i < h.Session.PartyCount)
                {
                    var p = h.Session.GetPartyMember(i);
                    name = p.Core.HasNickname ? p.Core.Nickname : h.SpeciesNameText(p.Core.SpeciesNo);
                }
                h.Session.Words.SetText(s, name);
                return true;
            });

            // ---- Abfragen (Work-Ergebnis) ----
            Reg(479, "GET_MY_SEX", P, S, (h, c) => { c.SetWork(1, h.Session.Save.SexRaw ^ 1); return true; });
            Reg(448, "SYS_FLAG_BADGE_GET", P, S, (h, c) => { c.SetWork(2, h.Session.Vars.GetSysFlag(c.Raw(1)) ? 1 : 0); return true; });
            Reg(450, "SYS_FLAG_BADGE_COUNT", P, S, (h, c) => { c.SetWork(1, h.Session.BadgeCount); return true; });
            Reg(290, "GET_NOW_ZONE_ID", P, S, (h, c) => { c.SetWork(1, h.Session.ZoneId); return true; });
            Reg(289, "GET_BEFORE_ZONE_ID", A, S, (h, c) => { c.SetWork(1, h.Session.BeforeZoneId); return true; });
            Reg(554, "GET_TIME_ZONE", P, S, (h, c) => { c.SetWork(1, h.Session.PeriodOfDay); return true; });
            Reg(522, "GET_POKE_COUNT", P, S, (h, c) => { c.SetWork(1, h.Session.PartyCount); return true; });
            // 523: nur aus der Pokécenter-Animation erschlossen (Schleife zählt Bälle bis zu diesem Wert) [A]: Anzahl der Teammitglieder.
            Reg(523, "GET_POKE_COUNT_ANIM", A, S, (h, c) => { c.SetWork(1, h.Session.PartyCount); return true; });
            Reg(326, "FIRST_POKE_NO_GET", P, S, (h, c) => { c.SetWork(1, h.Session.DefaultPokeNo); return true; });
            Reg(563, "TEMOTI_POKE_CHK", P, S, (h, c) =>
            {
                // Ergebnis 1, wenn ein Teammitglied (kein Ei, nicht leer) die Art hat.
                var mons = c.Int(2);
                var found = 0;
                for (var i = 0; i < h.Session.PartyCount && found == 0; i++)
                {
                    var p = h.Session.GetPartyMember(i);
                    if (!p.IsEmpty && !p.Core.IsEgg && p.Core.SpeciesNo == mons) found = 1;
                }
                c.SetWork(1, found);
                return true;
            });
            Reg(543, "TEMOTI_MONSNO", A, S, (h, c) =>
            {
                var i = c.Int(1);
                c.SetWork(2, i >= 0 && i < h.Session.PartyCount ? h.Session.GetPartyMember(i).Core.SpeciesNo : 0);
                return true;
            });
            Reg(194, "GET_POCKET_NO", P, S, (h, c) =>
            {
                var rec = h.Session.Data.Battle.GetItem(c.Int(1));
                c.SetWork(2, rec == null ? 0 : rec.FieldPocket);
                return true;
            });
            Reg(1162, "GET_ITEM_COUNT", A, S, (h, c) => { c.SetWork(2, h.Session.GetItemCount(c.Int(1))); return true; });

            // ---- Team, Heilung ----
            Reg(480, "PC_KAIFUKU", P, S, (h, c) => { h.Session.HealAll(); return true; });
            Reg(218, "ADD_POKEMON", P, S, (h, c) =>
            {
                // Art, Stufe, Item (0 = keins), Ergebnis-Work (1 = ins Team aufgenommen), optional Anzahl perfekter Werte (ungenutzt [A]).
                var p = h.Session.CreateOwnPokemon(c.Int(1), c.Int(2), c.Int(3));
                c.SetWork(4, h.Session.AddPartyMember(p) ? 1 : 0);
                return true;
            });
            Reg(259, "FIRST_POKE_SELECT_PROC", P, W, (h, c) => h.WaitStarter(c));

            // ---- Kampf ----
            Reg(401, "WILD_BTL_SET", P, S, (h, c) => WildBattle(h, c, false));
            Reg(402, "SP_WILD_BTL_SET", P, S, (h, c) => WildBattle(h, c, false));
            Reg(403, "FIRST_BTL_SET", P, S, (h, c) => WildBattle(h, c, true));
            Reg(478, "SET_WARP_ID", P, S, (h, c) => { h.Session.WipeoutZone = c.Int(1); return true; });

            // ---- Ereignisrahmen (Objekte anhalten, Eingabe sperren) ----
            Reg(155, "EVENT_START", P, F, (h, c) => { h.Field.SetEventMode(true); return true; });
            Reg(154, "TALK_START", P, F, (h, c) => { h.Field.SetEventMode(true); return true; });
            Reg(151, "TALK_OBJ_START", P, F, (h, c) => { h.Field.SetEventMode(true); h.Field.TurnToTalkPartner(true); return true; });
            Reg(152, "TALK_OBJ_START_TURN_NOT", P, F, (h, c) => { h.Field.SetEventMode(true); h.Field.TurnToTalkPartner(false); return true; });
            Reg(153, "TALK_OBJ_END", P, F, (h, c) => { h.Field.SetEventMode(false); return true; });
            Reg(156, "TALK_END", P, F, (h, c) => { h.Field.SetEventMode(false); return true; });
            Reg(157, "EVENT_END", P, F, (h, c) => { h.Field.SetEventMode(false); return true; });

            // ---- Objekte, Spieler ----
            Reg(146, "OBJ_ADD", P, F, (h, c) => { h.Field.SetObjectVisible(ObjName(c, 1), true); return true; });
            Reg(147, "OBJ_DEL", P, F, (h, c) => { h.Field.SetObjectVisible(ObjName(c, 1), false); return true; });
            Reg(549, "OBJ_VISIBLE", A, F, (h, c) => { h.Field.SetObjectVisible(ObjName(c, 1), true); return true; });
            Reg(550, "OBJ_INVISIBLE", A, F, (h, c) => { h.Field.SetObjectVisible(ObjName(c, 1), false); return true; });
            Reg(503, "SXY_POS_CHANGE", A, F, (h, c) => { h.Field.SetObjectGrid(ObjName(c, 1), c.Int(2), c.Int(3), c.Has(4) ? c.Int(4) : -1); return true; });
            Reg(507, "SXY_EXIT_POS_CHANGE", A, F, (h, c) => { h.Field.SetObjectGrid(ObjName(c, 1), c.Int(2), c.Int(3), c.Has(4) ? c.Int(4) : -1); return true; });
            Reg(506, "SXY_DIR_CHANGE", A, F, (h, c) => { h.Field.SetObjectGrid(ObjName(c, 1), int.MinValue, int.MinValue, c.Int(2)); return true; });
            Reg(158, "PLAYER_POS_GET", P, F, (h, c) =>
            {
                h.Field.GetPlayerGrid(out var x, out var z, out _);
                c.SetWork(1, x);
                c.SetWork(2, z);
                return true;
            });
            Reg(161, "PLAYER_DIR_GET", P, F, (h, c) =>
            {
                h.Field.GetPlayerGrid(out _, out _, out var d);
                c.SetWork(1, d);
                return true;
            });

            // ---- Überblendung ----
            Reg(283, "BLACK_OUT", P, F, (h, c) => { h.Field.Fade(false, false, h.FadeSpeed); return true; });
            Reg(284, "BLACK_IN", P, F, (h, c) => { h.Field.Fade(false, true, h.FadeSpeed); return true; });
            Reg(281, "WHITE_OUT", A, F, (h, c) => { h.Field.Fade(true, false, h.FadeSpeed); return true; });
            Reg(282, "WHITE_IN", A, F, (h, c) => { h.Field.Fade(true, true, h.FadeSpeed); return true; });
            Reg(836, "FADE_SPEED", P, F, (h, c) => { h.FadeSpeed = c.Int(1); return true; });
            Reg(784, "FADE_WAIT", P, W, (h, c) => h.Field.FadeIsDone());

            // ---- Tafeln, Warten auf Taste ----
            Reg(92, "EASY_BOARD_MSG", HostEvidence.N, W, (h, c) => h.TalkOnce(c));
            Reg(93, "EASY_INFOBOARD_MSG", HostEvidence.N, W, (h, c) => h.TalkOnce(c));
            Reg(76, "AB_KEYWAIT", HostEvidence.N, W, (h, c) => h.WaitConfirm(c));

            // ---- Darstellung (Feldschicht): Kamera, Effekte, Türen, Blick, Statisten ----
            Visual(942, "EVENT_CAMERA_INDEX"); Visual(943, "EVENT_CAMERA_END_WAIT"); Visual(875, "CAMERA_SET_COS_ANGLE"); Visual(814, "CAMERA_TARGET_HERO");
            Visual(815, "CAMERA_TARGET_DUMMY"); Visual(972, "CAMERA_SHAKE"); Visual(1038, "CAMERA_CONTROLLER_PLAY"); Visual(1069, "CAMERA_CONTROLLER_WAIT");
            Visual(1049, "RELEASE_CAMERA_CONTROLLER"); Visual(1036, "LOAD_CAMERA_CONTROLLER"); Visual(1037, "LOAD_WAIT_CAMERA_CONTROLLER");
            Visual(1039, "CAMERA_CONTROLLER_END"); Visual(1173, "DOF_CHANGE_TARGET_POS"); Visual(1174, "DOF_RESET_TARGET_POS"); Visual(1107, "DOF_FAR_DEPTH");
            Visual(1052, "CALL_EFFECT"); Visual(1053, "STOP_EFFECT"); Visual(1054, "RELEASE_EFFECT"); Visual(1058, "CALL_EFFECT_OBJ"); Visual(1161, "EFF_SCALE");
            Visual(829, "HIT_DOOR_ANIME"); Visual(830, "HIT_DOOR_ANIME_WAIT"); Visual(831, "SET_DOOR_OBJ"); Visual(839, "DOOR_FORCE_ANIME_END"); Visual(879, "DOOR_ENABLE_SET");
            Visual(489, "SEQ_OPEN_DOOR"); Visual(490, "SEQ_CLOSE_DOOR");
            Visual(981, "CHARA_LOOK_LOCK"); Visual(982, "CHARA_LOOK_RELEASE"); Visual(1102, "OBJ_ANIME_SPEED"); Visual(1143, "SET_FORCE_BLINK");
            Visual(880, "AC_ANIM_LOCK"); Visual(881, "AC_ANIM_RELEASE");
            Visual(816, "DUMMY_ANIME"); Visual(817, "DUMMY_ANIME_WAIT"); Visual(818, "DUMMY_SET_POS"); Visual(819, "DUMMY_SET_POS_HERO");
            Visual(144, "OBJ_PAUSE"); Visual(142, "OBJ_PAUSE_ALL"); Visual(145, "OBJ_PAUSE_CLEAR"); Visual(163, "MOVE_CODE_CHANGE"); Visual(824, "INVISIBLE_OBJ_PROP");
            Visual(1035, "SET_VISIBILITY"); Visual(1103, "OBJ_SCALE"); Visual(1062, "OBJ_POS_CHANGE_WORLD"); Visual(1191, "OBJ_DIR_CHANGE_WORLD");
            Visual(1192, "OBJ_POS_CHANGE_WORLD_FIND"); Visual(504, "OBJ_POS_CHANGE"); Visual(509, "OBJ_DIR_CHANGE"); Visual(150, "TURN_HERO_SITE");
            Visual(983, "TALK_OBJ_START_LOOK_NONE"); Visual(1051, "FIND_BG_DISABLE"); Visual(1050, "FIND_BG_ENABLE"); Visual(973, "EVENT_ENTITY_CLIP_PLAY");
            Visual(948, "MONEY_OPEN"); Visual(949, "MONEY_CLOSE"); Visual(487, "WAIT_3D_ANIME");
            // Menü-/Oberflächenschicht (Läden, Listen, Beutel, Box, Speichern, Pokécenter-Animation): Ergebnis-Work schreibt die Oberfläche über den Aufruf.
            Visual(912, "DPR_SHOP_OPEN"); Visual(913, "DPR_SHOP_OPEN_WAIT"); Visual(921, "SHOP_OPEN_FIXED"); Visual(922, "SHOP_OPEN_SEAL"); Visual(923, "SHOP_OPEN_BATTLE");
            Visual(924, "SHOP_OPEN_FLOWER"); Visual(925, "SHOP_OPEN_OTENKI"); Visual(926, "SHOP_OPEN_SELL"); Visual(929, "SHOP_OPEN_BOUTIQUE_BUY"); Visual(930, "SHOP_OPEN_BOUTIQUE_CHANGE");
            Visual(944, "SHOP_OPEN_PALPARK"); Visual(1106, "TOBARI_4F_SHOP_OPEN");
            Visual(264, "POKELIST_SET_PROC"); Visual(267, "POKELIST_GET_RESULT"); Visual(262, "BAG_SET_PROC_KINOMI"); Visual(263, "BAG_GET_RESULT"); Visual(250, "BOX_SET_PROC");
            Visual(255, "DENDOU_SET_PROC"); Visual(256, "PC_DENDOU_SET_PROC"); Visual(249, "TMAP_BG_SET_PROC"); Visual(247, "IMAGE_CLIP_VIEW_CON_SET_PROC");
            Visual(1088, "AUTO_SAVE"); Visual(411, "REPORT_SAVE"); Visual(410, "REPORT_SAVE_CHECK"); Visual(1108, "DISPLAY_MESSAGE"); Visual(1109, "DISPLAY_MESSAGE_CLOSE");
            Visual(304, "CUTIN"); Visual(1218, "OJIGI"); Visual(979, "POKECEN_PUT_BALL"); Visual(980, "POKECEN_CLEAR_BALL"); Visual(663, "PC_RECOVER_ANM"); Visual(664, "ELEVATOR_ANM");
            Visual(273, "EYE_TRAINER_MOVE_SET"); Visual(274, "EYE_TRAINER_MOVE_CHECK"); Visual(882, "SET_OFFSET"); Visual(939, "WARP_START_ANIMATION"); Visual(940, "WARP_END_ANIMATION");
            Visual(294, "BICYCLE_REQ"); Visual(295, "BICYCLE_REQ_NON_BGM"); Visual(1088, "AUTO_SAVE");

            // ---- Partner (Systemflag 2), Zukan ----
            Reg(454, "SYS_FLAG_PAIR_SET", P, S, (h, c) => { h.Session.Vars.SetSysFlag(2, true); return true; });
            Reg(455, "SYS_FLAG_PAIR_RESET", P, S, (h, c) => { h.Session.Vars.SetSysFlag(2, false); h.Field.RunVisual(c); return true; });
            Reg(453, "SYS_FLAG_PAIR_GET", P, S, (h, c) => { c.SetWork(1, h.Session.Vars.GetSysFlag(2) ? 1 : 0); return true; });
            Reg(651, "ZENKOKU_ZUKAN_FLAG", A, S, (h, c) =>
            {
                // Modus 1: Landesdex freischalten, Modus 2: Zustand in Work (Zukan-Daten liegen in der Sitzung, Ort im Save nicht belegt).
                var mode = c.Int(1);
                if (mode == 1) h.Session.NationalDex = true;
                else if (mode == 2 && c.Has(2)) c.SetWork(2, h.Session.NationalDex ? 1 : 0);
                return true;
            });
            Reg(323, "FIRST_POKEMON_NAME", A, S, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.SpeciesNameText(h.Session.DefaultPokeNo)); return true; });

            // ---- Ton: bewusst ohne Wirkung (Regel "kein Sound") ----
            Mute(109, "SE_PLAY"); Mute(110, "SE_STOP"); Mute(111, "SE_WAIT"); Mute(112, "VOICE_PLAY"); Mute(113, "VOICE_WAIT");
            Mute(115, "ME_PLAY"); Mute(116, "ME_WAIT"); Mute(118, "BGM_PLAY"); Mute(121, "BGM_NOW_MAP_PLAY"); Mute(122, "BGM_SPECIAL_SET");
            Mute(128, "PLAYER_FIELD_DEMO_BGM_PLAY"); Mute(130, "CTRL_BGM_FLAG_RESET"); Mute(341, "TRAINER_BGM_SET"); Mute(1163, "PLAY_EMO_SE");
            Mute(1198, "RESET_SAVEBGM"); Mute(1117, "PLAY_FUREAI_VOICE_NAKAYOSHIRANK");

            return _t;
        }

        static bool WildBattle(GameEvHost h, EvScript.EvCommandCall c, bool tutorial)
        {
            if (c.First)
            {
                var req = BattleRequest.Wild(c.Int(1), c.Int(2));
                req.Tutorial = tutorial;
                req.FromEvent = true;
                h.RequestBattle(req);
                return false;
            }
            return h.BattleIsDone();
        }

        // Zählung für docs/spielkern-1.md und die Tests.
        public static int Count(HostEvidence? evidence = null, HostKind? kind = null)
        {
            var n = 0;
            foreach (var c in Table.Values)
                if ((evidence == null || c.Evidence == evidence) && (kind == null || c.Kind == kind)) n++;
            return n;
        }
    }
}
