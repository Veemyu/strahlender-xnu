using System;
using System.Collections.Generic;
using Xnu.EvScript;
using Xnu.PokePara;

namespace Xnu.Game
{
    // Spielkern Scheibe 2: weitere Host-Befehle. Prüfstufen: P = Handler-Pseudocode gelesen (Ghidra-Export, EvDataManager),
    // A = Annahme (Argumentform oder Teilbefund), N = nur Name/Signatur, Wirkung an die Feldschicht delegiert.
    // Argumente werden ab 1 gezählt (c.Int(1) ist das erste Argument nach der Kennung); Ergebnisse gehen in Arbeitswerte (Res).
    public static partial class HostCommands
    {
        static partial void InstallMore(Dictionary<int, HostCommand> t)
        {
            InstallParty();
            InstallBag();
            InstallFlagsTime();
            InstallNames();
            InstallFieldState();
            InstallBattle();
            InstallDialog();
            InstallVisuals();
        }

        const HostEvidence EP = HostEvidence.P, EA = HostEvidence.A, EN = HostEvidence.N;
        const HostKind KS = HostKind.State, KF = HostKind.Field, KW = HostKind.Wait;

        // Teammitglied (tray < 0) oder Boxpokémon; null bei leer/Ei, wenn eggOk false ist.
        static PokemonParam Mon(GameEvHost h, int pos, int tray, bool eggOk = false)
        {
            var p = h.Session.GetMon(pos, tray);
            if (p == null || p.IsEmpty) return null;
            if (!eggOk && p.Core.IsEgg) return null;
            return p;
        }

        static int LevelOf(GameEvHost h, PokemonParam p)
        {
            if (!p.HasCalcData)
            {
                var sp = h.Session.Data.Battle.GetSpecies(p.Core.SpeciesNo, p.Core.FormNo);
                p.RecalculateCalcData(sp, h.Session.Data.Battle.GetGrowth(sp.GrowthCurve));
            }
            return p.Level;
        }

        static int OptInt(EvCommandCall c, int i, int def) => c.Has(i) ? c.Int(i) : def;

        static void Res(EvCommandCall c, int argIndex, int value)
        {
            if (c.Has(argIndex)) c.SetWork(argIndex, value);
        }

        // ---- Team: Abfragen und Änderungen (Party-Zugriff, Boxen) ----
        static void InstallParty()
        {
            // 480 PC_KAIFUKU: Team und Boxen heilen [P, Scheibe 1]; zusätzlich merkt sich der Kern die Zone als Rücksetzzone (ZenmetuZone) [A]
            Reg(480, "PC_KAIFUKU", EP, KS, (h, c) =>
            {
                h.Session.HealAll();
                h.Session.World.LastHealZone = h.Session.ZoneId;
                return true;
            });
            // 523 GET_POKE_COUNT2: Anzahl der Teammitglieder ohne Ei [P] (EvCmdGetPokeCount2: Schleife über das Team, zählt IsEgg == false).
            // Korrigiert Scheibe 1: 523 war als "Teamgröße" angenommen; die Teamgröße liefert 522.
            Reg(523, "GET_POKE_COUNT2", EP, KS, (h, c) => { Res(c, 1, h.Session.PartyCountNoEgg()); return true; });
            // 524 GET_POKE_COUNT3: nicht leer, kein Ei, KP ≠ 0 [P]; 525/1213 gleiche Zählung [A] (gleiches Schleifenmuster).
            Reg(524, "GET_POKE_COUNT3", EP, KS, (h, c) => { Res(c, 1, h.Session.PartyCountAlive()); return true; });
            Reg(525, "GET_POKE_COUNT4", EA, KS, (h, c) => { Res(c, 1, h.Session.PartyCountAlive()); return true; });
            Reg(1213, "GET_POKE_COUNT5", EA, KS, (h, c) => { Res(c, 1, h.Session.PartyCountAlive()); return true; });
            // 348 2VS2_BATTLE_CHECK: Ergebnis 1, wenn mindestens zwei kampffähige Mitglieder (kein Ei, KP ≠ 0) im Team sind [A].
            Reg(348, "2VS2_BATTLE_CHECK", EA, KS, (h, c) => { Res(c, 1, h.Session.PartyCountAlive() >= 2 ? 1 : 0); return true; });
            // 696 PARTY_MONSNO_CHECK(Art, Ergebnis): 1, wenn ein Teammitglied (kein Ei) die Art hat [P].
            Reg(696, "PARTY_MONSNO_CHECK", EP, KS, (h, c) =>
            {
                var mons = c.Int(1);
                var found = 0;
                for (var i = 0; i < h.Session.PartyCount && found == 0; i++)
                {
                    var p = Mon(h, i, -1);
                    if (p != null && p.Core.SpeciesNo == mons) found = 1;
                }
                Res(c, 2, found);
                return true;
            });
            // 221 CHK_POKE_WAZA(Ergebnis, Attacke, Position, Box): Teammitglied/Boxpokémon (kein Ei) kennt die Attacke [P].
            Reg(221, "CHK_POKE_WAZA", EP, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 3, 0), OptInt(c, 4, -1));
                var waza = c.Int(2);
                var r = 0;
                if (p != null) for (var i = 0; i < 4; i++) if (waza != 0 && p.Core.GetMove(i) == waza) r = 1;
                Res(c, 1, r);
                return true;
            });
            // 571 WAZA_COUNT(Ergebnis, Position, Box): Anzahl bekannter Attacken (0 bei Ei/leer) [P].
            Reg(571, "WAZA_COUNT", EP, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 2, 0), OptInt(c, 3, -1));
                var n = 0;
                if (p != null) for (var i = 0; i < 4; i++) if (p.Core.GetMove(i) != 0) n++;
                Res(c, 1, n);
                return true;
            });
            // 572 WAZA_DEL(Position, Attackenplatz, Box): RemoveWaza + CloseUpWazaPos (Lücken schließen), danach Box/Team aktualisieren [P].
            Reg(572, "WAZA_DEL", EP, KS, (h, c) =>
            {
                var pos = c.Int(1);
                var tray = OptInt(c, 3, -1);
                var p = Mon(h, pos, tray);
                var slot = c.Int(2);
                if (p == null || slot < 0 || slot > 3) return true;
                var moves = new List<(ushort mv, byte pp, byte ups)>();
                for (var i = 0; i < 4; i++)
                    if (i != slot && p.Core.GetMove(i) != 0) moves.Add((p.Core.GetMove(i), p.Core.GetPp(i), p.Core.GetPpUps(i)));
                for (var i = 0; i < 4; i++)
                {
                    if (i < moves.Count) { p.Core.SetMove(i, moves[i].mv); p.Core.SetPp(i, moves[i].pp); p.Core.SetPpUps(i, moves[i].ups); }
                    else { p.Core.SetMove(i, 0); p.Core.SetPp(i, 0); p.Core.SetPpUps(i, 0); }
                }
                h.Session.SetMon(pos, tray, p);
                return true;
            });
            // 557 GET_NATSUKI(Ergebnis, Position, Box): Freundschaftswert (0 bei Ei/leer) [P]; 558 ADD_NATSUKI(Position, Wert[, Box]) [P].
            Reg(557, "GET_NATSUKI", EP, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 2, 0), OptInt(c, 3, -1));
                Res(c, 1, p == null ? 0 : p.Core.Friendship);
                return true;
            });
            Reg(558, "ADD_NATSUKI", EP, KS, (h, c) =>
            {
                var pos = c.Int(1);
                var tray = OptInt(c, 3, -1);
                var p = Mon(h, pos, tray);
                if (p == null) return true;
                p.Core.Friendship = (byte)Math.Max(0, Math.Min(255, p.Core.Friendship + c.Int(2)));
                h.Session.SetMon(pos, tray, p);
                return true;
            });
            // Stufe, Wesen, Form, Fleißpunkte, Typen: Abfragen mit Work-Ergebnis [P für die Aufrufkette, Argumentreihenfolge A]
            Reg(599, "POKE_LEVEL_CHK", EA, KS, (h, c) => { var p = Mon(h, OptInt(c, 2, 0), -1); Res(c, 1, p == null ? 0 : LevelOf(h, p)); return true; });
            Reg(717, "POKE_LEVEL_GET", EP, KS, (h, c) => { var p = Mon(h, OptInt(c, 2, 0), -1); Res(c, 1, p == null ? 0 : LevelOf(h, p)); return true; });
            Reg(625, "GET_POKE_SEIKAKU", EP, KS, (h, c) => { var p = Mon(h, OptInt(c, 2, 0), -1); Res(c, 1, p == null ? 0 : p.Core.Nature); return true; });
            Reg(626, "CHK_POKE_SEIKAKU_ALL", EA, KS, (h, c) =>
            {
                var want = c.Int(2);
                var found = -1;
                for (var i = 0; i < h.Session.PartyCount && found < 0; i++)
                {
                    var p = Mon(h, i, -1);
                    if (p != null && p.Core.Nature == want) found = i;
                }
                Res(c, 1, found);
                return true;
            });
            Reg(217, "UNKNOWN_FORM_GET", EA, KS, (h, c) => { var p = Mon(h, OptInt(c, 1, 0), OptInt(c, 2, -1)); Res(c, 3, p == null ? 0 : p.Core.FormNo); return true; });
            Reg(657, "CHK_PRMEXP", EP, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 2, 0), -1);
                var sum = 0;
                if (p != null) for (var s = 0; s < 6; s++) sum += p.Core.GetEv((StatId)s);
                Res(c, 1, sum);
                return true;
            });
            Reg(672, "TEMOTI_POKE_TYPE", EA, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 3, 0), -1);
                var sp = p == null ? null : h.Session.Data.Battle.GetSpecies(p.Core.SpeciesNo, p.Core.FormNo);
                Res(c, 1, sp == null ? 0 : sp.Type1);
                Res(c, 2, sp == null ? 0 : sp.Type2);
                return true;
            });
            Reg(654, "CHK_RIBBON", EP, KS, (h, c) =>
            {
                var p = Mon(h, OptInt(c, 2, 0), -1);
                Res(c, 1, p != null && c.Int(3) >= 0 && c.Int(3) < 128 && p.Core.HasRibbon(c.Int(3)) ? 1 : 0);
                return true;
            });
            Reg(655, "SET_RIBBON", EP, KS, (h, c) =>
            {
                var pos = c.Int(1);
                var p = Mon(h, pos, -1);
                if (p == null || c.Int(2) < 0 || c.Int(2) >= 128) return true;
                p.Core.SetRibbon(c.Int(2), true);
                h.Session.SetMon(pos, -1, p);
                return true;
            });
            // 671 FRONT_POKEMON(Ergebnis): Platz des ersten Teammitglieds ohne Ei [A]
            Reg(671, "FRONT_POKEMON", EA, KS, (h, c) =>
            {
                var r = 0;
                for (var i = 0; i < h.Session.PartyCount; i++)
                    if (Mon(h, i, -1) != null) { r = i; break; }
                Res(c, 1, r);
                return true;
            });
            Reg(545, "CHK_TEMOTI_POKERUS", EA, KS, (h, c) =>
            {
                var r = 0;
                for (var i = 0; i < h.Session.PartyCount; i++)
                {
                    var p = Mon(h, i, -1, true);
                    if (p != null && p.Core.Pokerus != 0) r = 1;
                }
                Res(c, 1, r);
                return true;
            });
            // 543 TEMOTI_MONSNO(Position, Ergebnis): Art des Teammitglieds, 0 bei Ei/leer/außerhalb [P] (Scheibe 1 hatte Eier nicht ausgenommen)
            Reg(543, "TEMOTI_MONSNO", EP, KS, (h, c) =>
            {
                var p = Mon(h, c.Int(1), -1);
                Res(c, 2, p == null ? 0 : p.Core.SpeciesNo);
                return true;
            });
            // 683 COUNT_MONSBOX_SPACE(Ergebnis): 1, wenn kein Boxplatz mehr frei ist (GetSpaceCountAll < 1) [P]
            Reg(683, "COUNT_MONSBOX_SPACE", EP, KS, (h, c) => { Res(c, 1, h.Session.BoxSpaceCount() < 1 ? 1 : 0); return true; });
            // 995 TEMOTI_BOX_MONSNO(Position, Box, Ergebnis): Art des Pokémon (0 bei Ei/leer) [P]; 1001 TEMOTI_BOX_POKEMON_NAME(Slot, Position, Box) [P, Name A]
            Reg(995, "TEMOTI_BOX_MONSNO", EP, KS, (h, c) =>
            {
                var p = Mon(h, c.Int(1), OptInt(c, 2, -1));
                Res(c, 3, p == null ? 0 : p.Core.SpeciesNo);
                return true;
            });
            Reg(1001, "TEMOTI_BOX_POKEMON_NAME", EA, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var p = Mon(h, OptInt(c, 2, 0), OptInt(c, 3, -1), true);
                h.Session.Words.SetText(s, p == null ? "" : p.Core.HasNickname ? p.Core.Nickname : h.SpeciesNameText(p.Core.SpeciesNo));
                return true;
            });
            // 994 TEMOTI_BOX_POKE_CHK(Ergebnis, Art): 1, wenn die Art im Team oder in einer Box liegt [P]
            Reg(994, "TEMOTI_BOX_POKE_CHK", EP, KS, (h, c) =>
            {
                var mons = c.Int(2);
                var found = 0;
                for (var i = 0; i < h.Session.PartyCount && found == 0; i++)
                {
                    var p = h.Session.GetMon(i, -1);
                    if (p != null && !p.IsEmpty && p.Core.SpeciesNo == mons) found = 1;
                }
                var trays = System.Math.Min(h.Session.Save.TrayMax(), PokeLayout.TrayCount);
                for (var t = 0; t < trays && found == 0; t++)
                    for (var pos = 0; pos < PokeLayout.TraySlots && found == 0; pos++)
                    {
                        var p = h.Session.GetMon(pos, t);
                        if (p != null && !p.IsEmpty && p.Core.SpeciesNo == mons) found = 1;
                    }
                Res(c, 1, found);
                return true;
            });
            // 1141 TEMOTI_POKE_CHK_GET_POS(Ergebnis, Art): erster Platz einer Art im Team (ohne Ei), sonst -1 [P]
            Reg(1141, "TEMOTI_POKE_CHK_GET_POS", EP, KS, (h, c) =>
            {
                var r = -1;
                for (var i = 0; i < h.Session.PartyCount && r < 0; i++)
                {
                    var p = Mon(h, i, -1);
                    if (p != null && p.Core.SpeciesNo == c.Int(2)) r = i;
                }
                Res(c, 1, r);
                return true;
            });
            // 1041 TEMOTI_POKE_CHK_NUM(Ergebnis, Art): Anzahl der Mitglieder dieser Art (ohne Ei); Art 0: 1, wenn zwei Mitglieder dieselbe Art haben [P]
            Reg(1041, "TEMOTI_POKE_CHK_NUM", EP, KS, (h, c) =>
            {
                var mons = c.Int(2);
                var count = 0;
                var seen = new HashSet<int>();
                var dup = 0;
                for (var i = 0; i < h.Session.PartyCount; i++)
                {
                    var p = Mon(h, i, -1);
                    if (p == null) continue;
                    if (p.Core.SpeciesNo == mons) count++;
                    if (!seen.Add(p.Core.SpeciesNo)) dup = 1;
                }
                Res(c, 1, mons != 0 ? count : dup);
                return true;
            });
            // 1171 GET_FORM(Ergebnis): Fortbewegungsform 1 = Fahrrad, 2 = Surfen, 0 = zu Fuß [P]
            Reg(1171, "GET_FORM", EP, KS, (h, c) => { Res(c, 1, h.Session.World.Bicycle ? 1 : h.Session.World.Swimming ? 2 : 0); return true; });
            // 653 CHK_RIBBON_COUNT_ALL(Ergebnis): Zahl der Bänder (0–99), die mindestens ein Teammitglied (ohne Ei) besitzt [P]
            Reg(653, "CHK_RIBBON_COUNT_ALL", EP, KS, (h, c) =>
            {
                var n = 0;
                for (var r = 0; r < 100; r++)
                    for (var i = 0; i < h.Session.PartyCount; i++)
                    {
                        var p = Mon(h, i, -1);
                        if (p != null && p.Core.HasRibbon(r)) { n++; break; }
                    }
                Res(c, 1, n);
                return true;
            });
            // 762 DAME_TAMAGO_CHK_ALL(Ergebnis): 1, wenn ein Teammitglied ein fehlerhaftes Ei ist (IsEgg im Fehlermodus) [A]
            Reg(762, "DAME_TAMAGO_CHK_ALL", EA, KS, (h, c) =>
            {
                var r = 0;
                for (var i = 0; i < h.Session.PartyCount; i++)
                {
                    var p = h.Session.GetMon(i, -1);
                    if (p != null && !p.IsEmpty && p.Core.IsBadEgg) r = 1;
                }
                Res(c, 1, r);
                return true;
            });
            // 1197 POKE_LEVEL_GET_ALL(Position, Box, Ergebnis): Stufe, 0 bei Ei/leer [P]
            Reg(1197, "POKE_LEVEL_GET_ALL", EP, KS, (h, c) =>
            {
                var p = Mon(h, c.Int(1), OptInt(c, 2, -1));
                Res(c, 3, p == null ? 0 : LevelOf(h, p));
                return true;
            });
            // 1230 TEMOTI_PER_RND(Position, Ergebnis): Persönlichkeitswert (PersonalRnd) des Teammitglieds, 0 außerhalb [P]
            Reg(1230, "TEMOTI_PER_RND", EP, KS, (h, c) =>
            {
                var p = h.Session.GetMon(c.Int(1), -1);
                Res(c, 2, p == null || p.IsEmpty ? 0 : (int)p.Core.PersonalRnd);
                return true;
            });
            // 1216 POKE_TARENT_POW_MAX(Position, Box, Ergebnis): 1, wenn die Summe der sechs Talentwerte 186 ist (alle 31) [P]
            Reg(1216, "POKE_TARENT_POW_MAX", EP, KS, (h, c) =>
            {
                var p = Mon(h, c.Int(1), OptInt(c, 2, -1));
                var sum = 0;
                if (p != null) for (var s = 0; s < 6; s++) sum += (int)p.Core.GetNativeIv((StatId)s);
                Res(c, 3, sum == 0xBA ? 1 : 0);
                return true;
            });
            // 219 ADD_TAMAGO(Art, …): Ei der Art (Stufe 1, Ball 4) ins Team; der Dialog drumherum steckt im Skript [A]
            Reg(219, "ADD_TAMAGO", EA, KS, (h, c) =>
            {
                var p = h.Session.CreateOwnPokemon(c.Int(1), 1, 0);
                p.Core.IsEgg = true;
                p.Core.Ball = 4;
                h.Session.AddPartyMember(p);
                return true;
            });
        }

        // ---- Beutel, Geld, Rekorde ----
        const int SavePocketItems = 3000;

        static void InstallBag()
        {
            // 195 CHECK_POCKET(Tasche, Ergebnis): 1, wenn die Tasche mindestens ein Item enthält (GetItemInfosByCategory.count > 0) [P]
            Reg(195, "CHECK_POCKET", EP, KS, (h, c) =>
            {
                var pocket = c.Int(1);
                var any = 0;
                for (var i = 1; i < SavePocketItems && any == 0; i++)
                {
                    if (h.Session.GetItemCount(i) <= 0) continue;
                    var rec = h.Session.Data.Battle.GetItem(i);
                    if (rec != null && rec.FieldPocket == pocket) any = 1;
                }
                Res(c, 2, any);
                return true;
            });
            Reg(747, "AUSU_ITEM_CHECK", EP, KS, (h, c) => { Res(c, 2, (uint)(c.Int(1) - 0x12A) < 0x10u ? 1 : 0); return true; });
            // CB_ITEM_*: Ball-Aufkleber (BallDecoWork.AddSealCount/GetSealCount) [P]
            Reg(216, "CB_ITEM_NUM_ADD", EP, KS, (h, c) =>
            {
                var id = c.Int(1);
                h.Session.World.BallSeals.TryGetValue(id, out var n);
                h.Session.World.BallSeals[id] = Math.Max(0, n + c.Int(2));
                return true;
            });
            Reg(215, "CB_ITEM_NUM_GET", EP, KS, (h, c) => { h.Session.World.BallSeals.TryGetValue(c.Int(1), out var n); Res(c, 2, n); return true; });
            // Untergrund-Items (Eigenspeicher): Name aus dp_underground_name [A]
            Reg(1105, "ADD_UG_ITEM", EA, KS, (h, c) =>
            {
                var id = c.Int(1);
                h.Session.World.UndergroundItems.TryGetValue(id, out var n);
                h.Session.World.UndergroundItems[id] = n + Math.Max(1, OptInt(c, 2, 1));
                return true;
            });
            Reg(1189, "GET_BP", EA, KS, (h, c) => { Res(c, 1, h.Session.World.BattlePoints); return true; });
            Reg(612, "RECORD_INC", EP, KS, (h, c) => { h.Session.World.RecordAdd(c.Int(1), 1); return true; });
            Reg(236, "DENDOU_NUM_GET", EP, KS, (h, c) => { Res(c, 1, h.Session.World.RecordGet(1)); return true; });
        }

        // ---- Flags, Systemflags, Arbeitswerte, Zeit ----
        static void InstallFlagsTime()
        {
            // Poketch: Flag 0xCB, Apps im Weltzustand [P Aufruf, A: App-Nummern]
            Reg(417, "GET_POKETCH", EP, KS, (h, c) => { h.Session.Vars.SetFlag(WorldState.PoketchFlag, true); return true; });
            Reg(418, "GET_POKETCH_FLAG", EP, KS, (h, c) => { Res(c, 1, h.Session.Vars.GetFlag(WorldState.PoketchFlag) ? 1 : 0); return true; });
            Reg(419, "POKETCH_ADD", EP, KS, (h, c) => { h.Session.World.PoketchApps.Add(c.Int(1)); return true; });
            Reg(420, "POKETCH_CHECK", EP, KS, (h, c) => { Res(c, 2, h.Session.World.PoketchApps.Contains(c.Int(1)) ? 1 : 0); return true; });
            // Systemflags und Spielzustand [P]
            Reg(445, "SYS_FLAG_ZUKAN_SET", EP, KS, (h, c) => { h.Session.Vars.SetFlag(WorldState.ZukanFlag, true); return true; });
            Reg(447, "SYS_FLAG_SHOES_SET", EP, KS, (h, c) => { h.Session.Vars.SetFlag(WorldState.ShoesFlag, true); return true; });
            Reg(449, "SYS_FLAG_BADGE_SET", EP, KS, (h, c) => { h.Session.Vars.SetSysFlag(c.Raw(1), true); return true; });
            Reg(452, "SYS_FLAG_BAG_SET", EP, KS, (h, c) => { h.Session.Vars.SetSysFlag(1, true); return true; });
            Reg(456, "SYS_FLAG_ONE_STEP_GET", EP, KS, (h, c) => { Res(c, 1, h.Session.Vars.GetSysFlag(6) ? 1 : 0); return true; });
            Reg(459, "SYS_FLAG_GAME_CLEAR_GET", EP, KS, (h, c) => { Res(c, 1, h.Session.Vars.GetSysFlag(5) ? 1 : 0); return true; });
            Reg(461, "SYS_FLAG_KAIRIKI_SET", EP, KS, (h, c) => { h.Session.Vars.SetSysFlag(3, true); return true; });
            Reg(463, "SYS_FLAG_KAIRIKI_GET", EP, KS, (h, c) => { Res(c, 1, h.Session.Vars.GetSysFlag(3) ? 1 : 0); return true; });
            Reg(464, "SYS_FLAG_FLASH_SET", EP, KS, (h, c) => { h.Session.World.FlashActive = true; return true; });
            Reg(467, "SYS_FLAG_KIRIBARAI_SET", EP, KS, (h, c) => { h.Session.World.MistCleared = true; return true; });
            Reg(510, "RETURN_SCRIPT_WK_SET", EP, KS, (h, c) => { h.Session.Vars.SetWork(WorldState.ReturnScriptWork, c.Int(1)); return true; });
            // Zeit: CHK_WEEK/GET_NOW_HOUR lesen Arbeitswert 0x1A2 [P]; hier wird er vorher aus der Uhr aktualisiert
            Reg(658, "CHK_WEEK", EP, KS, (h, c) => { h.Session.UpdateClock(); Res(c, 1, h.Session.Vars.GetWork(WorldState.ClockWork) / 100000000 - 1); return true; });
            Reg(702, "GET_NOW_HOUR", EP, KS, (h, c) => { h.Session.UpdateClock(); Res(c, 1, h.Session.Vars.GetWork(WorldState.ClockWork) % 10000 / 100); return true; });
            // 316 BIRTH_DAY_CHECK(Monat, Tag, Ergebnis): Uhr stimmt mit Datum überein [A] (Original prüft Jahr/Schaltjahr/Monat/Tag der Systemuhr)
            Reg(316, "BIRTH_DAY_CHECK", EA, KS, (h, c) =>
            {
                var t = h.Session.World.Clock();
                Res(c, 3, t.Month == c.Int(1) && t.Day == c.Int(2) ? 1 : 0);
                return true;
            });
            Reg(670, "PM_VERSION_GET", EA, KS, (h, c) => { Res(c, 1, h.Session.World.CassetteVersion); return true; });
            // 734 GET_RANDOM_HIT(Wahrscheinlichkeit %, Ergebnis): Random(0,100) < Wert [P]
            Reg(734, "GET_RANDOM_HIT", EP, KS, (h, c) => { Res(c, 2, h.RandomRange(100) < c.Int(1) ? 1 : 0); return true; });
            Reg(722, "REGULAR_CHECK", EA, KS, (h, c) => { Res(c, 1, h.Session.World.RecordGet(2) > 4 ? 1 : 0); return true; });
            Reg(731, "IS_HAIHU_EVENT_ENABLE", EA, KS, (h, c) => { Res(c, 2, h.Session.World.RecordGet(3) != 0 ? 1 : 0); return true; });
            Reg(765, "GET_TRCARD_RANK", EA, KS, (h, c) => { Res(c, 1, h.Session.World.RecordGet(4)); return true; });
        }

        // ---- Namenswörter aus Textlabels (MessageWordSetHelper.Set*Word) ----
        static void Name(int id, string name, HostEvidence ev, string file, string prefix, int valueArg = 2, int digits = 3)
        {
            Reg(id, name, ev, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var n = c.Int(valueArg);
                h.WordFromLabel(s, file, prefix + (digits == 0 ? n.ToString() : n.ToString(new string('0', digits))));
                return true;
            });
        }

        static void InstallNames()
        {
            // Der Aufruf (Set*Word(slot, wert)) ist gelesen [P]; die Label-Namen folgen den Dateien (ss_wazaname WAZANAME_nnn usw.) [A]
            Name(313, "WAZA_NAME", EP, "ss_wazaname", "WAZANAME_");
            Name(311, "POCKET_NAME", EA, "ss_bag_pocket", "SS_bag_pocket_");
            Name(327, "NUTS_NAME", EA, "ss_nuts_name", "NUTS_NAME_");
            Name(328, "SEIKAKU_NAME", EP, "ss_seikaku", "SEIKAKU_");
            Name(656, "RIBBON_NAME", EA, "ss_ribbon", "RIBBON_NAME_");
            Name(1180, "POKE_TYPE_NAME", EA, "ss_typename", "TYPENAME_");
            Name(1181, "POFFIN_NAME", EA, "dlp_poffin_name", "DLP_POFFIN_NAME_");
            Name(1182, "DRESS_NAME", EA, "ss_fld_dressup_item_name", "SS_fld_dressup_item_name_");
            Name(759, "SEAL_NAME", EA, "dp_stickers_name", "DP_STICKERS_NAME_");
            Name(970, "SPEAKERS_NAME", EA, "dlp_speakers_name", "DLP_SPEAKERS_NAME_");
            Name(1095, "PARK_ITEM_NAME", EA, "dlp_park_name", "DLP_PARK_NAME_");
            Name(1114, "UG_ITEM_NAME", EA, "dp_underground_name", "UNDERGROUND_NAME_");
            Name(319, "POKETCH_NAME", EA, "dp_poketch", "DP_poketch_", 2, 2);
            Name(322, "POKEMON_NAME_EXTRA", EP, "ss_monsname", "MONSNAME_");
            // 320 TR_TYPE_NAME: Trainerart des Trainers (TrainerRecord.TypeId) -> Label der Arten [A]
            Reg(320, "TR_TYPE_NAME", EA, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var tr = h.Session.Data.GetTrainer(c.Int(2));
                h.WordFromLabel(s, "dp_trainers_type", "DP_Trainers_Type_" + (tr == null ? "TR_NONE" : "TR_" + tr.TypeId.ToString("000")));
                return true;
            });
            // 324/325: Arten von Rivale/Begleiter (PlayerWork.rivalPokeNo/supportPokeNo) [P], Herleitung aus der Startwahl [A]
            Reg(324, "RIVAL_POKEMON_NAME", EP, KS, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.SpeciesNameText(h.Session.RivalPokeNo)); return true; });
            Reg(325, "SUPPORT_POKEMON_NAME", EP, KS, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.SpeciesNameText(h.Session.SupportPokeNo)); return true; });
            // 574 TEMOTI_WAZA_NAME(Slot, Position, Attackenplatz): Name einer Attacke des Teammitglieds [P]
            Reg(574, "TEMOTI_WAZA_NAME", EP, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var p = Mon(h, c.Int(2), -1);
                var mv = p == null ? 0 : p.Core.GetMove(Math.Max(0, Math.Min(3, c.Int(3))));
                h.WordFromLabel(s, "ss_wazaname", "WAZANAME_" + mv.ToString("000"));
                return true;
            });
            // 1172 NICK_NAME_ALL(Slot, Position, Box): Spitzname/Artname aus Team oder Box [P]
            Reg(1172, "NICK_NAME_ALL", EP, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var p = Mon(h, c.Int(2), OptInt(c, 3, -1), true);
                h.Session.Words.SetText(s, p == null ? "" : p.Core.HasNickname ? p.Core.Nickname : h.SpeciesNameText(p.Core.SpeciesNo));
                return true;
            });
            Reg(711, "MONUMENT_NAME", EA, KS, (h, c) => { if (Slot(c, out var s)) h.Session.Words.SetText(s, h.Session.World.MonumentName); return true; });
            // 315 NUMBER_NAME_EX(Slot, Zahl, Art, Stellen): Art 2 = Zahl mit führenden Nullen als Text, sonst Zahlenwort [P]
            Reg(315, "NUMBER_NAME_EX", EP, KS, (h, c) =>
            {
                if (!Slot(c, out var s)) return true;
                var n = c.Int(2);
                if (OptInt(c, 3, 0) == 2) h.Session.Words.SetText(s, n.ToString(new string('0', Math.Max(1, OptInt(c, 4, 1)))));
                else h.Session.Words.SetNumber(s, n);
                return true;
            });
        }

        static void GridChange(GameEvHost h, EvCommandCall c)
        {
            var n = ObjName(c, 1);
            var x = c.Int(2);
            var z = c.Int(3);
            h.Session.World.ObjectGrid[n] = new[] { x, z };
            h.Field.SetObjectGrid(n, x, z, c.Has(4) ? c.Int(4) : -1);
        }

        // ---- Fortbewegung, Objekte, Warp ----
        static void InstallFieldState()
        {
            // 293 BICYCLE_CHECK(Ergebnis) = PlayerWork.IsFormBicycle [P]; 294/295 BICYCLE_REQ(1 = auf, sonst ab) [A]; 1093 Farbe [A]
            Reg(293, "BICYCLE_CHECK", EP, KS, (h, c) => { Res(c, 1, h.Session.World.Bicycle ? 1 : 0); return true; });
            Reg(294, "BICYCLE_REQ", EA, KF, (h, c) => { if (c.First) h.Session.World.Bicycle = c.Int(1) == 1; return h.Field.RunVisual(c); });
            Reg(295, "BICYCLE_REQ_NON_BGM", EA, KF, (h, c) => { if (c.First) h.Session.World.Bicycle = c.Int(1) == 1; return h.Field.RunVisual(c); });
            Reg(1093, "BICYCLE_COLOR_SET", EP, KS, (h, c) => { h.Session.World.BicycleColor = c.Int(1); return true; });
            // 292 NAMINORI: FieldPlayerEntity.ChangeSwim(1) [P], 884 NAMINORI_END beendet [A]; die Bewegung selbst macht die Feldschicht
            Reg(292, "NAMINORI", EP, KF, (h, c) => { if (c.First) { h.Session.World.Swimming = true; h.Session.World.Bicycle = false; } return h.Field.RunVisual(c); });
            Reg(884, "NAMINORI_END", EA, KF, (h, c) => { if (c.First) h.Session.World.Swimming = false; return h.Field.RunVisual(c); });
            Reg(302, "HIDEN_FLASH", EP, KF, (h, c) => { if (c.First) h.Session.World.FlashActive = true; return h.Field.RunVisual(c); });
            Reg(303, "HIDEN_KIRIBARAI", EP, KF, (h, c) => { if (c.First) h.Session.World.MistCleared = true; return h.Field.RunVisual(c); });
            Reg(1219, "DARKNESS_TEMPORARILY_OFF", EN, KF, (h, c) => { if (c.First) h.Session.World.Darkness = false; return h.Field.RunVisual(c); });
            Reg(1220, "DARKNESS_TEMPORARILY_ON", EN, KF, (h, c) => { if (c.First) h.Session.World.Darkness = true; return h.Field.RunVisual(c); });
            Reg(624, "PLAYER_HEGIHT_VALID", EP, KS, (h, c) => { h.Session.World.HeightValid = c.Int(1) != 0; return true; });
            // Objekte: Bewegungscode, Partner [P]
            Reg(505, "SXY_MV_CHANGE", EP, KF, (h, c) =>
            {
                if (c.First) h.Session.World.ObjectMoveCode[ObjName(c, 1)] = c.Int(2);
                return h.Field.RunVisual(c);
            });
            Reg(165, "PAIR_OBJID_SET", EP, KF, (h, c) =>
            {
                if (c.First) h.Session.World.PartnerObject = ObjName(c, 1);
                return h.Field.RunVisual(c);
            });
            // Sichtbarkeit nach Name mit Weltzustand (Work-Flags der Objekte bleiben im Skript)
            Reg(146, "OBJ_ADD", EP, KF, (h, c) => { h.Session.World.ObjectVisible[ObjName(c, 1)] = true; h.Field.SetObjectVisible(ObjName(c, 1), true); return true; });
            Reg(147, "OBJ_DEL", EP, KF, (h, c) => { h.Session.World.ObjectVisible[ObjName(c, 1)] = false; h.Field.SetObjectVisible(ObjName(c, 1), false); return true; });
            Reg(549, "OBJ_VISIBLE", EP, KF, (h, c) => { h.Session.World.ObjectVisible[ObjName(c, 1)] = true; h.Field.SetObjectVisible(ObjName(c, 1), true); return true; });
            Reg(550, "OBJ_INVISIBLE", EP, KF, (h, c) => { h.Session.World.ObjectVisible[ObjName(c, 1)] = false; h.Field.SetObjectVisible(ObjName(c, 1), false); return true; });
            // Warp und Karte
            // 503 SXY_POS_CHANGE(Objekt, x, z): Gitterposition setzen (set_gridPosition + set_gridPositionDirect) und im Weltzustand merken [P]
            Reg(503, "SXY_POS_CHANGE", EP, KF, (h, c) => { GridChange(h, c); return true; });
            // 506 SXY_DIR_CHANGE(Objekt, Richtung): SetYawAngleDirect(Richtung + 0x168) [P] – Slice 1 ruft dafür SetObjectGrid mit x/z = int.MinValue
            // 507 SXY_EXIT_POS_CHANGE(Ausgang, x, z): neue Gitterposition des Ausgangs (Warp-Index) – kein Objektname (Daten: drei Zahlen, 470 ×) [P]
            Reg(507, "SXY_EXIT_POS_CHANGE", EP, KF, (h, c) =>
            {
                if (c.First) h.Session.World.ExitPositions[c.Int(1)] = new[] { c.Int(2), c.Int(3) };
                return h.Field.RunVisual(c);
            });
            // 813 GET_REL_POS_HERO(Objekt, Ergebnis): Lage des Spielers zum Objekt im Zehnerblock (7 8 9 / 4 5 6 / 1 2 3, Objekt = 5), 0 = nicht benachbart [P];
            // Die Objektposition kennt der Kern nur nach einem Setzen per Skript; sonst entscheidet die Feldschicht (Ergebnis-Work über RunVisual).
            Reg(813, "GET_REL_POS_HERO", EP, KF, (h, c) =>
            {
                if (!h.Session.World.ObjectGrid.TryGetValue(ObjName(c, 1), out var g) || !h.Field.GetPlayerGrid(out var hx, out var hz, out _)) return h.Field.RunVisual(c);
                var dz = hz - g[1];
                var dx = hx - g[0];
                var code = 0;
                if (System.Math.Abs(dx) <= 1 && System.Math.Abs(dz) <= 1) code = 5 + dx + 3 * (-dz);
                Res(c, 2, code);
                return true;
            });
            Reg(1186, "SET_TELEPORT_ID", EP, KS, (h, c) => { h.Session.World.TeleportZone = c.Int(1); h.Session.World.TeleportLocator = OptInt(c, 2, 0); return true; });
            Reg(914, "DOOR_TRANSITION_ZONE_SET", EP, KS, (h, c) =>
            {
                h.Session.World.DoorZoneFrom = c.Str(1);
                h.Session.World.DoorZoneTo = c.Str(2);
                h.Emit(c, "DOOR_TRANSITION_ZONE_SET", 0);
                return true;
            });
            Reg(935, "TELEPORT", EA, KF, (h, c) =>
            {
                if (c.First && h.Session.World.TeleportZone >= 0)
                {
                    h.Session.BeforeZoneId = h.Session.ZoneId;
                    h.Session.ZoneId = h.Session.World.TeleportZone;
                    h.Field.ChangeZone(h.Session.ZoneId, h.Session.World.TeleportLocator, true);
                    return false;
                }
                return h.Field.ChangeZoneIsDone();
            });
        }

        // ---- Trainer und Kampf ----
        static void InstallBattle()
        {
            // 334 TRAINER_ID_GET(Ergebnis): erster Sichttrainer [P]; 276 EYE_TRAINER_ID_GET(Index, Ergebnis) [P]; 275 Typ [A]
            Reg(334, "TRAINER_ID_GET", EP, KS, (h, c) => { if (h.Session.World.EyeTrainerIds.Count > 0) Res(c, 1, h.Session.World.EyeTrainerIds[0]); return true; });
            Reg(276, "EYE_TRAINER_ID_GET", EP, KS, (h, c) =>
            {
                var i = c.Int(1);
                var ids = h.Session.World.EyeTrainerIds;
                if (c.Has(2) && i >= 0 && i < ids.Count) c.SetWork(2, ids[i]);
                return true;
            });
            Reg(275, "EYE_TRAINER_TYPE_GET", EA, KS, (h, c) =>
            {
                var t = h.Session.World.EyeTrainerTypes;
                Res(c, 1, t.Count > 0 ? t[0] : 0);
                return true;
            });
            // 338 TRAINER_TALK_TYPE_GET(a, b, c): Einzeltrainer (FightType 0): 0/2/0, sonst 3/5/6; ohne Sichttrainer unverändert [P]
            Reg(338, "TRAINER_TALK_TYPE_GET", EP, KS, (h, c) =>
            {
                var ids = h.Session.World.EyeTrainerIds;
                if (ids.Count == 0) return true;
                var tr = h.Session.Data.GetTrainer(ids[0]);
                if (tr == null) return true;
                var single = tr.FightType == 0;
                Res(c, 1, single ? 0 : 3);
                Res(c, 2, single ? 2 : 5);
                Res(c, 3, single ? 0 : 6);
                return true;
            });
            // 337 TRAINER_MSG_SET(Trainer, Art): Text aus dem Trainerdatensatz (Art 0/3/7 vor dem Kampf, 2/5/9 danach, 6 ein Pokémon, 17–19 Revanche) [P]
            Reg(337, "TRAINER_MSG_SET", EP, KW, (h, c) =>
            {
                if (c.First)
                {
                    var tr = h.Session.Data.GetTrainer(c.Int(1));
                    var kind = c.Int(2);
                    var label = tr == null ? "" : TrainerMessageLabel(tr, kind);
                    var pct = label.IndexOf('%');
                    h.TalkBegin(new EvTalkRequest { Msbt = pct < 0 ? "dp_trainer_msg" : label.Substring(0, pct), Label = pct < 0 ? label : label.Substring(pct + 1) });
                    return false;
                }
                if (!h.Dialog.IsFinished) return false;
                h.TalkClose(true);
                return true;
            });
            // 336 TRAINER_MULTI_BTL_SET(Trainer1, Trainer2): Doppelkampf-Anfrage [A], wartet wie TRAINER_BTL_SET
            Reg(336, "TRAINER_MULTI_BTL_SET", EA, KS, (h, c) =>
            {
                if (c.First)
                {
                    h.StartTrainerBattle(c.Int(1), c.Has(2) ? c.Int(2) : 0);
                    return false;
                }
                return h.BattleIsDone();
            });
            // 404 CAPTURE_BTL_SET: Fangvorführung gegen Art 399 Stufe 2 [P: EventWildBattle(399, 2, 1, …)]
            Reg(404, "CAPTURE_BTL_SET", EP, KS, (h, c) =>
            {
                if (c.First)
                {
                    var req = BattleRequest.Wild(399, 2);
                    req.FromEvent = true;
                    h.RequestBattle(req);
                    return false;
                }
                return h.BattleIsDone();
            });
            Reg(1223, "RESET_STOP_EYE_ENCOUNT", EN, KS, (h, c) => true);
            Reg(1222, "SET_STOP_EYE_ENCOUNT", EN, KS, (h, c) => true);
        }

        static string TrainerMessageLabel(Xnu.Data.TrainerRecord tr, int kind)
        {
            switch (kind)
            {
                case 0: case 3: case 7: return tr.MsgFieldBefore ?? "";
                case 2: case 5: case 9: return tr.MsgFieldAfter ?? "";
                case 6: return tr.MsgFieldPokeOne ?? "";
                case 0x11: case 0x12: case 0x13: return tr.MsgFieldRevenge ?? "";
                default: return "";
            }
        }

        // ---- Dialog, Menüs, Eingabe ----
        static void InstallDialog()
        {
            // 80 TALK_OPEN: Work 199 = 1 (nur wenn Zeilenzustand und beide Texte gesetzt sind, im Kern ohne Fensterparameter immer) [P teilweise]
            Reg(80, "TALK_OPEN", EP, KS, (h, c) => { h.Session.Vars.SetWork(EvCmdId.WorkTalkWindow, 1); return true; });
            // 114 EASY_VOICE_MSG("datei%label", "Stimme"): wie EASY_MSG mit Objekt-Start/-Ende; die Stimme ist Ton und entfällt [P]
            Reg(114, "EASY_VOICE_MSG", EP, KW, (h, c) =>
            {
                if (c.First) { h.Field.SetEventMode(true); h.Field.TurnToTalkPartner(true); }
                if (!h.TalkOnce(c)) return false;
                h.Field.SetEventMode(false);
                return true;
            });
            // Tafeln: BOARD_REQ öffnet (Text), BOARD_REQ_WAIT wartet auf das Fenster, BOARD_END_WAIT auf A/B/X [N]
            Reg(88, "BOARD_REQ", EN, KW, (h, c) => h.TalkOnce(c));
            Reg(89, "BOARD_REQ_WAIT", EN, KW, (h, c) => true);
            Reg(91, "BOARD_END_WAIT", EN, KW, (h, c) => { if (h.Input.Confirm || h.Input.Cancel) { Res(c, 1, 1); return true; } return false; });
            Reg(77, "AB_KEY_TIME_WAIT", EP, KW, (h, c) =>
            {
                // wartet auf A/B oder bis die Zeit (Frames/30 s) abgelaufen ist; ohne Zeitangabe nur Taste [P]
                if (h.Input.Confirm || h.Input.Cancel) return true;
                return c.Has(1) && c.Type(1) != 5 && c.Int(1) > 0 && c.Phase >= c.Int(1);
            });
            // Namenseingabe: Text über GameInput.Text, Confirm ohne Text behält den Namen [A]
            Reg(278, "NAMEIN_POKE", EA, KW, (h, c) =>
            {
                if (h.Input.Text == null && !h.Input.Confirm && !h.Input.Cancel) return false;
                var changed = 0;
                var pos = c.Int(1);
                var tray = OptInt(c, 2, -1);
                var p = Mon(h, pos, tray, true);
                if (p != null && h.Input.Text != null)
                {
                    p.Core.Nickname = h.Input.Text;
                    p.Core.HasNickname = h.Input.Text.Length > 0;
                    h.Session.SetMon(pos, tray, p);
                    changed = 1;
                }
                Res(c, 3, changed);
                return true;
            });
            Reg(710, "NAMEIN_MONUMENT", EA, KW, (h, c) =>
            {
                if (h.Input.Text == null && !h.Input.Confirm && !h.Input.Cancel) return false;
                if (h.Input.Text != null) h.Session.World.MonumentName = h.Input.Text;
                Res(c, 1, h.Input.Text != null ? 1 : 0);
                return true;
            });
        }
    }
}
