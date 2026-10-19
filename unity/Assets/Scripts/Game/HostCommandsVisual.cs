using System;
using System.Collections.Generic;
using Xnu.EvScript;

namespace Xnu.Game
{
    public static partial class HostCommands
    {
        // Delegierte Befehle (Prüfstufe N: Name, Signatur und Aufrufliste des Handlers; die Wirkung läuft über IFieldHost.RunVisual).
        // Befehle, die im Original auf ein Ende warten (…_WAIT), sind Kind=Wait: der Host fragt RunVisual je Frame ab, bis es true liefert.
        // Jeder Aufruf erscheint beim ersten Mal im Ereignisprotokoll (GameEvHost.Events, nur mit Record).
        static void Vis(string list)
        {
            foreach (var item in list.Split(' '))
            {
                if (item.Length == 0) continue;
                var colon = item.IndexOf(':');
                var id = int.Parse(item.Substring(0, colon));
                var name = item.Substring(colon + 1);
                var wait = name.EndsWith("_WAIT") || name.Contains("_WAIT_");
                Reg(id, name, EN, wait ? KW : KF, (h, c) => h.Field.RunVisual(c));
            }
        }

        // Ohne Wirkung im Kern (Debug), ohne Darstellung.
        static void Quiet(int id, string name) => Reg(id, name, EN, KS, (h, c) => true);

        static void Shop(int id, string name, HostEvidence ev, ShopKind kind, bool useId, bool zoneName)
        {
            Reg(id, name, ev, KF, (h, c) =>
            {
                if (c.First)
                {
                    var zn = zoneName && c.Has(1) ? c.Str(1) : "";
                    var zid = zoneName ? h.Session.Data.ResolveZoneName(zn) : h.Session.ZoneId;
                    h.Session.OpenShop(kind, useId && c.Has(1) ? c.Int(1) : 0, zn, zid >= 0 ? zid : h.Session.ZoneId);
                }
                return h.Field.RunVisual(c);
            });
        }

        static void InstallVisuals()
        {
            // Kampfturm (BTWR_*, BTOWER_*): Ablauf und Zustand laufen in der Turm-Oberfläche
            Vis("600:BTOWER_APP_CALL 945:BTOWER_APP_WAIT 1004:BTWR_TOOL_PUSH_NOW_LOCATION 1007:BTWR_TOOL_SET_PLAY_MODE 1008:BTWR_TOOL_SET_NOW_WIN 1009:BTWR_TOOL_SET_RANK 1011:BTWR_SUB_GET_NOW_ROUND 1012:BTWR_SUB_INC_ROUND 1014:BTWR_SUB_GET_RENSHOU_CNT 1015:BTWR_SUB_SET_SCORE 1017:BTWR_SUB_LOCAL_BTL_CALL 1018:BTWR_SUB_GET_PLAY_MODE 1021:BTWR_SUB_ADD_BATTLE_POINT 1022:BTWR_SUB_RENSHOU_RIBBON_SET 1024:BTWR_SUB_UPDATE_RANDOM 1031:BTWR_SUB_GET_RANK 1032:BTWR_SUB_RANK_DOWN_LOSE 1033:BTWR_SUB_RANK_DOWN_LOSE_RESET 1034:BTWR_SUB_ADD_LOSE 1199:BTWR_SUB_SELECT_POKE 1200:BTWR_SUB_GET_ENTRY_POKE 1206:BTWR_PLAYER_WIN_CHECK 1215:BTWR_SUB_ADD_BATTLE_POINT_MANUAL 1231:ADD_BTLTWR_CHALLENGE 1233:BTLTWR_CONTINUE_ROUND 68:TALKMSG_BTOWER_APPEAR 1229:GET_RECORD_TOWOR_WIN");
            // Wettbewerb
            Vis("368:CONTEST_PROC 389:CON_RECORD_DISP 889:CON_OPEN_POKE_SELECT_MENU 890:CON_OPEN_CAPSULE_SELECT_MENU 891:CON_OPEN_BOUTIQUE_SELECT_MENU 892:CON_WAIT_CONTEST_MENU 893:CON_MY_ENTRY_NO_WORD_SET 894:CON_BEST_PERFORMER_CHECK 895:CON_CATEGORY_RIBBON_NAME_SET 896:CON_HAVE_CONTEST_STAR_CHECK 897:CON_CONTEST_STAR_NAME_SET 898:CON_REWARD_NAME_SET 901:CON_CATEGORY_AND_RANK_SET 906:CON_CHECK_ENTRY_POKE 909:CON_RESET_PARAMETER 910:CON_SELECT_SINGLE_MODE 911:CON_SELECT_MULTI_MODE 931:CON_REWARD_SHOWMASTER_NAME_SET 932:CON_TWINKLE_STAR_NAME_SET 991:CON_OPEN_MATCHING_MENU 1060:CON_OPEN_RESUME_MATCHING_MENU 1178:CON_CATEGORY_NAME 1179:CON_RANK_NAME 724:TEMOTI_POKE_CONTEST_STATUS_GET");
            // Untergrund, Union, Netz, Gruppen, Pension, Safari, Naturpark, Begleiter, Pferd, Ballkapsel
            Vis("527:UG_SHOP_MENU_INIT 1133:TALK_UG_NPC 1139:GET_UG_NPC_TALK_COUNT 1140:RESET_UG_NPC_TALK_COUNT 1184:UG_LEAVE_HOYUTA 1208:AG_TRANSITION_HOYUTA 1068:UNION_PROC 1081:TALK_UNION_NPC 1078:SET_MATCHING_GROUP 1082:CHECK_ONLINE_ACCOUNT 1083:WAIT_CHECK_ONLINE_ACCOUNT 1232:CHECK_GMS_ONLINE_ACCOUNT 1234:GMS_END 272:WIFI_EARTH_SET_PROC 1084:LOCALKOUKAN_APPLY 992:OPEN_PASSWORD_SWKEYBOARD");
            Vis("845:GROUP_EXIST_CHECK 846:GROUP_ENTRY_CHECK 847:GROUP_NAME 848:GROUP_LEADER_NAME 849:GROUP_NAME_IN 850:GROUP_ENTRY 851:GROUP_MAKE");
            Vis("950:AZUKARIYA_EXIST_EGG 951:AZUKARIYA_STORED_COUNT 952:AZUKARIYA_SET_STORED_NAME 953:AZUKARIYA_STORE 954:AZUKARIYA_RESTORE 955:AZUKARIYA_LOVE_LEVEL 956:AZUKARIYA_GET_STORED_MONSNO 957:AZUKARIYA_GET_EGG 958:AZUKARIYA_DISCARD_EGG 959:AZUKARIYA_SET_STORED_INFO_STR 960:AZUKARIYA_GET_STORED_SEX 961:AZUKARIYA_OLDMAN_INIT 1090:AZUKARIYA_TAKE_OVER_POKE 1185:AZUKARIYA_STORE_UI");
            Vis("617:SAFARI_START 618:SAFARI_END 619:CALL_SAFARI_SCOPE 622:MOVE_SAFARI_TRAIN 623:CHECK_SAFARI_TRAIN 941:SAFARI_SCOPE_SEQUENCE 628:NATURAL_PARK_WALK_COUNT_CLEAR 888:NATURAL_PARK_GET_MONOHIROI_ITEM_NO 903:NATURAL_PARK_POKE_CREATE 904:NATURAL_PARK_POKE_KAISAN 905:NATURAL_PARK_POKE_SYUUGOU 907:NATURAL_PARK_POKE_SELECT_MENU");
            Vis("1045:TUREARUKI_POKEMON_TALK 1046:TUREARUKI_POKEMON_INDEX 1047:TUREARUKI_TAKE_ITEM 1075:TUREARUKI_POKE_CREATE 1076:TUREARUKI_POKE_DELETE 1096:LOAD_UMA_ANIME 1097:RELEASE_UMA_ANIME 1098:LOAD_UMA_ANIME_WAIT 1099:UMA_ANIME_PLAY 1100:UMA_ANIME_ATTACH 1137:UMA_IS_NULL 248:CUSTOM_BALL_EVENT_CALL 987:CUSTOM_BALL_NUM_ADD 1110:CUSTOM_BALL_TRAINER_PAGE 1111:CUSTOM_BALL_TRAINER_COPY_OPEN 1129:CUSTOM_BALL_TRAINER_PAGE_WAIT");
            // Zukan, Menüs, Oberflächen (Ergebnis-Work schreibt die Oberfläche)
            Vis("395:SHINOU_ZUKAN_SEE_NUM 398:ZENKOKU_ZUKAN_GET_NUM 585:ZUKAN_CHK_SHINOU 586:ZUKAN_CHK_NATIONAL 587:ZUKAN_RECONGNIZE_SHINOU 588:ZUKAN_RECONGNIZE_NATIONAL 1085:ZUKAN_TOUROKU 1086:ZUKAN_TOUROKU_WAIT 317:ANOON_SEE_NUM 1176:ALL_MONSNO 1177:ALL_MONS_OWN_CHK 1132:ENTRY_UWASA_ZUKAN 631:GET_NEWS_POKE_NO");
            Vis("1043:POKELIST_FORM_CHANGE_SET_PROC 1044:POKELIST_FORM_CHANGE_GET_RESULT 996:CALL_WAZA_OMOIDASHI_UI 997:CALL_WAZA_WASURE_UI 998:CALL_WAZA_OSHIE_UI 999:CHECK_WAZA_OSHIE 1000:CHECK_WAZA_OSHIE_ALL 1209:ADD_POKEMON_UI 1214:ADD_UNIQUE_POKEMON_UI 1188:USE_SPECIAL_ITEM 1195:USE_SUB_ATTRIBUTE 1080:USE_TANKENSET 967:USE_SPRAY 237:POKE_WINDOW_PUT 553:RANKING_VIEW 1061:BOX_SEAL_UI_WAIT 1121:PC_DENDOU_SET_PROC_OPEN_WAIT 915:IMAGE_CLIP_VIEW_CON_CHECK_PROC 1217:OPEN_BATTLE_WIN 1104:BADGE_GET 984:BOUKENNOOTO_TIPS_OPEN 1026:BOUKENNOOTO_TIPS_WAIT 1112:RECONGNIZE_TOKIKAKE 1113:RECONGNIZE_OPEN_WAIT 1134:TRAINING_OPEN 1135:TRAINING_OPEN_WAIT 1225:PLAY_REPORT_TRAINING 1221:SAVE_PLAYREPORT 1204:AUTO_SAVE_BACK_UP_ON 1027:SAVE_RENDOU_ENABLE 1063:OPEN_SPECIAL_WIN_LABEL 1064:WAIT_SPECIAL_WIN_LABEL 1224:OPEN_CUSTUM_WIN_FIXED 962:ADD_CUSTUM_WIN_LABEL_WORD_SET 963:OPEN_CUSTUM_WIN_WORD_SET 1164:AUTO_MSG 1165:AUTO_MSG_STOP 71:TALKMSG_SP");
            // Pokémon: Demo, Wettkampf, Sonderfälle der Feldschicht
            Vis("542:TAMAGO_DEMO 1167:ADD_WAZA 1175:ADD_MAROYAKA_POFFIN 730:POFIN_ADD_CHK 937:CHECK_POFIN 833:TEMOTI_ROTOMU_FORM_WAZA_CHG 832:ROTOMU_FORM_CHECK 1040:TEMOTI_ROTOMU_FORM_CHG_CHECK 1042:TEMOTI_ROTOMU_FORM_GET 697:PARTY_DEOKISISUFORM_CHANGE 698:CHECKMINOMUCHICOMP 662:ASHIATO_CHK 637:REMAIND_WAZA_COUNT 1187:POKE_LVUP_HOW_MANY 887:TALK_POKE_GET_TEMOTI_INDEX 1210:GET_FUREAI_SELECT_POKE_TEMOTI_NO 899:OBJ_ANIME_FUREAI 1115:FUREAI_TALK_START 635:ADD_MOVE_POKE 597:ITEMNO_TO_MONSNO 594:KASEKI_COUNT 598:KASEKI_ITEMNO 193:WAZA_ITEM_CHK 312:ITEM_WAZA_NAME 1158:PARTNER_NAME_SET 1166:GET_TAG_PATNER_ID 1203:ZONE_NAME_LABEL 1193:ZONE_NAME2 1122:GET_POKETCH_APP_ID 1205:GET_STATUE_NUM 1138:GET_IS_HAVE_SECRETBASE 1144:CHECK_SECRET_BASE_EXPANTION");
            // Karte, Zone, Fortbewegung, Feldobjekte, Arenen
            Vis("291:KABENOBORI 300:TAKINOBORI 301:SORAWOTOBU 1059:SORAWOTOBU_END 885:TAKIKUDARI 933:ANAWOHORU 934:ANANUKENOHIMO 1131:EMBANKMENT 1201:SET_GLOBALWATERFIELD 736:HIDENEFF_START 985:HIDENEFF_WAIT 989:WARP_PANEL_START 990:WARP_PANEL_END 785:HERO_MOVE_GRID_CENTER 835:TURN_HERO_TALK_OBJ 917:EV_ENTITY_PLAYER_MOVE_START 918:EV_ENTITY_PLAYER_MOVE_END 919:EV_ENTITY_PLAYER_MOVE_RESET 974:EVENT_ENTITY_CLIP_WAIT 1212:EVENT_ENTITY_CLIP_ATTACH_PLAYER 488:FREE_3D_ANIME 1136:CAMERA_CONTROLLER_IS_NULL 1149:SET_LIGHTINTENSITY 1190:FOV_OFFSET_RATE 719:C08R0801SCOPECAMERASET 1130:C08R0801SCOPECAMERA_SEQUENCE 1123:FADE_DUNGEON_OUT 1126:FADE_BUILDING_IN 1128:FADE_AREA_IN 977:TEMOTI_BALL_LOAD 978:TEMOTI_BALL_LOAD_WAIT 966:BTL_ENCSEQ_LOAD 988:CHANGE_FASHION_REQ 928:GET_COSTUME 971:GET_PLAYER_CAP 231:FINISH_MAP_PROC 287:COLOSSEUM_MAP_CHANGE_IN 1194:TALK_COLISEUM_NPC 665:CALL_SHIP_DEMO 1119:CALL_SHIP_DEMO_SEA_MAP 1120:SETUP_SHIP 1089:ENDING_DEMO 1077:AUTO_TANKEN_SET 1079:AUTO_TANKEN_SET_WAIT");
            Vis("515:PUSH_WATER_GYM_BUTTON 516:INIT_GHOST_GYM 517:MOVE_GHOST_GYM_LIFT 519:INIT_COMBAT_GYM 521:ROTATE_ELEC_GYM_GEAR 916:MOVE_COMBAT_GYM_WALL 689:INIT_FLD_LIFT 690:MOVE_FLD_LIFT 691:CHECK_FLD_LIFT 946:FLOOR_OPEN 947:FLOOR_CLOSE 1227:GET_WATER_GYM_WATER_LEVEL 1228:REGET_WATER_GYM_WATER_LEVEL 405:HONEY_TREE 406:GET_HONEY_TREE_STATE 407:HONEY_TREE_BTL_SET 494:GET_SEED_STATUS 495:GET_SEED_TYPE 498:GET_SEED_COUNT 500:SET_SEED_NUTS 501:SET_SEED_WATER 502:TAKE_SEED 583:NUTMIXER_CALL 589:URAYAMA_ENCOUNT_SET 590:URAYAMA_ENCOUNT_NO_CHK 634:START_GENERATE 333:GENERATE_INFO_GET 346:SEACRET_POKE_RETRY_CHECK 678:GET_KUJI_ATARI_NUM 679:KUJI_ATARI_CHK 680:KUJI_ATARI_INIT 716:LEVEL_JIJII_NO 720:LEVEL_JIJII_INIT 564:OOKISA_RECORD_CHK 565:OOKISA_RECORD_SET 566:OOKISA_TEMOTI_SET_BUF 567:OOKISA_KIROKU_SET_BUF 568:OOKISA_KURABE_INIT 1148:OOKISA_VALUE_SET_BUF 936:AMAIKAORI 938:AMAIMITU 1091:POKETORE_GET_CHARGE 1092:POKETORE_START 224:REVENGE_TRAINER_SEARCH 339:REVENGE_TRAINER_TALK_TYPE_GET 242:BTL_SEARCHER_EVENT_CALL");
            // Eingaben mit Oberfläche
            Vis("968:BIRTH_MOUNTH_INPUT 969:BIRTH_DAY_INPUT");
            // TV: Themenwerte im Weltzustand (leer, solange keine Sendung erzeugt wurde) [A], Rest an die Oberfläche
            Vis("659:TV_ENTRY_WATCH_HIDE_ITEM 660:TV_ENTRY_WATCH_CHANGE_NAME 682:TV_INTERVIEWER_CHECK 863:TV_INTERVIEW_ENTRY 864:TV_START 865:TV_END 866:TV_START_NUMBER 1156:TV_RED_GYARADOS_ON 1157:TV_RED_GYARADOS_OFF 1159:TV_MONITOR_SET 1160:TV_MONITOR_RESET 1202:TV_INTERVIEW_STR_WORD_SET");
            Reg(1146, "TV_TOPIC_INT_GET", EA, KS, (h, c) => { h.Session.World.TvInts.TryGetValue(c.Int(1), out var v); Res(c, 2, v); return true; });
            Reg(1145, "TV_TOPIC_BRANCH_GET", EA, KS, (h, c) => { h.Session.World.TvBranch.TryGetValue(c.Int(1), out var v); Res(c, 2, v); return true; });
            Reg(1147, "TV_TOPIC_STR_WORD_SET", EA, KS, (h, c) =>
            {
                if (Slot(c, out var s)) { h.Session.World.TvStrings.TryGetValue(c.Int(2), out var t); h.Session.Words.SetText(s, t ?? ""); }
                return true;
            });
            Reg(1211, "TV_TOPIC_STR_GENDER_WORD_SET", EA, KS, (h, c) =>
            {
                if (Slot(c, out var s)) { h.Session.World.TvStrings.TryGetValue(c.Int(2), out var t); h.Session.Words.SetText(s, t ?? ""); }
                return true;
            });

            // Ohne Wirkung (Debug)
            Quiet(782, "DEBUG_PRINT");
            // Version: LDVAL_VERSION lädt Work 0xEE je nach Kassette (Wert 10 = erstes Argument) [P], CASSET_VERSION_GET [A]
            Reg(840, "LDVAL_VERSION", EP, KS, (h, c) => { h.Session.Vars.SetWork(0xEE, h.Session.World.CassetteVersion == 10 ? c.Int(1) : c.Int(2)); return true; });
            Reg(1055, "CASSET_VERSION_GET", EA, KS, (h, c) => { Res(c, 1, h.Session.World.CassetteVersion); return true; });

            // Läden: Anfrage mit Angebot (ShopTables), Abrechnung im Kern (GameSession.Buy/Sell), Anzeige über RunVisual; DPR_SHOP_OPEN_WAIT schließt nach dem Ende
            Shop(912, "DPR_SHOP_OPEN", EP, ShopKind.Friendly, false, true);
            Shop(921, "SHOP_OPEN_FIXED", EP, ShopKind.Fixed, true, false);
            Shop(923, "SHOP_OPEN_BATTLE", EA, ShopKind.Battle, true, false);
            Shop(926, "SHOP_OPEN_SELL", EP, ShopKind.Sell, false, false);
            Shop(922, "SHOP_OPEN_SEAL", EN, ShopKind.Other, false, false);
            Shop(924, "SHOP_OPEN_FLOWER", EN, ShopKind.Other, false, false);
            Shop(925, "SHOP_OPEN_OTENKI", EN, ShopKind.Other, false, false);
            Shop(929, "SHOP_OPEN_BOUTIQUE_BUY", EN, ShopKind.Other, false, false);
            Shop(930, "SHOP_OPEN_BOUTIQUE_CHANGE", EN, ShopKind.Other, false, false);
            Shop(944, "SHOP_OPEN_PALPARK", EN, ShopKind.Other, false, false);
            Shop(1106, "TOBARI_4F_SHOP_OPEN", EN, ShopKind.Other, true, false);
            Reg(913, "DPR_SHOP_OPEN_WAIT", EA, KW, (h, c) =>
            {
                if (!h.Field.RunVisual(c)) return false;
                h.Session.CloseShop();
                return true;
            });

            // Pokécenter-Animation: Ball des n-ten Teammitglieds ohne Ei (GetGetBall), Löschen, Heileffekt [P]
            Reg(979, "POKECEN_PUT_BALL", EP, KF, (h, c) =>
            {
                if (c.First)
                {
                    var want = c.Int(1);
                    var n = 0;
                    for (var i = 0; i < h.Session.PartyCount; i++)
                    {
                        var p = Mon(h, i, -1);
                        if (p == null) continue;
                        if (n == want) { h.Session.World.PokecenterBalls.Add(p.Core.Ball); break; }
                        n++;
                    }
                }
                return h.Field.RunVisual(c);
            });
            Reg(980, "POKECEN_CLEAR_BALL", EP, KF, (h, c) => { if (c.First) h.Session.World.PokecenterBalls.Clear(); return h.Field.RunVisual(c); });
            Reg(663, "PC_RECOVER_ANM", EP, KF, (h, c) => { if (c.First) h.Session.World.HealEffectCalls++; return h.Field.RunVisual(c); });

            // Kamera [P]: EVENT_CAMERA_INDEX(Index) startet die Kamerafahrt (EventCamera.SetCameraData), END_WAIT wartet auf deren Ende (Flag der Kamera);
            // die Dauer steht in der Kameratabelle der Feldschicht und erscheint als HostEvent.DurationFrames.
            Reg(942, "EVENT_CAMERA_INDEX", EP, KF, (h, c) =>
            {
                if (c.First) { h.Session.World.CameraIndex = c.Int(1); h.Session.World.CameraBusy = true; }
                return h.Field.RunVisual(c);
            });
            Reg(943, "EVENT_CAMERA_END_WAIT", EP, KW, (h, c) =>
            {
                if (!h.Field.RunVisual(c)) return false;
                h.Session.World.CameraBusy = false;
                return true;
            });
            // Aus Scheibe 1 delegierte Befehle, deren zentraler Aufruf jetzt im Pseudocode gelesen ist (Überblendung weiß, Tür, Blick, Anim-Tempo, Effekte,
            // Objekt-Pause/Position/Richtung/Größe/Sichtbarkeit, Statisten, 3D-Wartebefehl): die Darstellung bleibt Sache der Feldschicht.
            Promote(new[] { 281, 282, 829, 830, 981, 982, 1102, 880, 881, 1052, 1053, 1054, 144, 142, 145, 163, 150, 504, 509, 1062, 1191, 1103, 1035, 816, 817, 818, 819, 487,
                1161, 1038, 1069, 1051, 1050, 949, 948, 973, 1192, 972, 814, 815, 1218, 983, 304, 1162, 323, 289 });
            // Speichern: der Kern zählt die Anfragen (AUTO_SAVE = FieldManager.AutoSave [P]); das Schreiben übernimmt die Oberfläche (SaveSlotService).
            Reg(1088, "AUTO_SAVE", EP, KF, (h, c) => { if (c.First) h.Session.World.SaveRequests++; return h.Field.RunVisual(c); });
            Reg(411, "REPORT_SAVE", EA, KF, (h, c) => { if (c.First) h.Session.World.SaveRequests++; return h.Field.RunVisual(c); });
        }

        static void Promote(int[] ids)
        {
            foreach (var id in ids)
                if (_t.TryGetValue(id, out var cmd)) cmd.Evidence = EP;
        }
    }
}
