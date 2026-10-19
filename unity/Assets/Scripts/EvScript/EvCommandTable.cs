using System;
using System.Collections.Generic;

namespace Xnu.EvScript
{
    public enum EvCmdKind
    {
        Core,   // vom Interpreter selbst ausgeführt (Semantik aus dem Pseudocode)
        NoOp,   // laut Sprungtabelle des Originals ohne Wirkung (RunEvCmd liefert sofort 1)
        Host,   // an IEvHost.ExecuteCommand delegiert
    }

    // Einordnung aller Befehlskennungen. Die NoOp-Menge stammt aus der Sprungtabelle von EvDataManager.RunEvCmd
    // (Tabelle bei 0x3EDAB7C, Index = Kennung - 1; 484 von 1234 Einträgen führen direkt auf den Rücksprung mit Ergebnis 1).
    public static class EvCommandTable
    {
        const string NoOpRanges =
            "2,5-18,20-21,25-27,39-40,63-67,69,72-75,78-79,94-95,97-108,117,119,123-127,131-135,137-139,141,143,148-149,160,162,164,166-167,178-186,188,196-214,220,223,225-230,232-235,238-241,243-246,251-254,257-258,260-261,265-266,268-271,277,279-280,288,296-297,305,321,329-331,340,342-345,347,349-367,369-379,381-388,390-394,399-400,408-409,412-416,421-443,470-477,481-486,491-493,496-497,499,508,511-512,514,518,520,526,528-541,546,551-552,559-562,569-570,573,575-582,584,591-593,595-596,601-611,613-616,620-621,627,629-630,632-633,636,638-650,652,661,666-669,673-677,681,684-688,692-695,699-701,703-704,706-709,712-715,718,721,723,725-729,732-733,735,737-746,748-758,760-761,763-764,766-779,783,786-789,792-811,825-828,837-838,842-844,852-862,867-871,876,883,900,902,908,927,964-965,976,1002,1006,1010,1016,1019-1020,1023,1025,1030,1048,1116,1142,1155";

        static readonly HashSet<int> NoOp = ParseRanges(NoOpRanges);

        static readonly HashSet<int> Core = new HashSet<int>
        {
            EvCmdId.Nop, EvCmdId.End, EvCmdId.TimeWait, EvCmdId.ChgCommonScr, EvCmdId.ChgLocalScr, EvCmdId.Jump, EvCmdId.Call, EvCmdId.Ret,
            EvCmdId.IfJump, EvCmdId.IfCall, EvCmdId.IfValJump, EvCmdId.IfValCall, EvCmdId.IfWkJump, EvCmdId.IfWkCall, EvCmdId.Switch, EvCmdId.CaseJump,
            EvCmdId.FlagSet, EvCmdId.ArriveFlagSet, EvCmdId.FlagReset, EvCmdId.IfFlagOnJump, EvCmdId.IfFlagOffJump, EvCmdId.IfFlagOnCall,
            EvCmdId.IfFlagOffCall, EvCmdId.FlagSetWk, EvCmdId.TrainerFlagSet, EvCmdId.TrainerFlagReset, EvCmdId.TrainerFlagCheck,
            EvCmdId.IfTrFlagOnJump, EvCmdId.IfTrFlagOffJump, EvCmdId.IfTrFlagOnCall, EvCmdId.IfTrFlagOffCall,
            EvCmdId.AddWk, EvCmdId.SubWk, EvCmdId.CmpWk, EvCmdId.CaseCancel, EvCmdId.LdVal, EvCmdId.LdWk, EvCmdId.LdWkVal,
            EvCmdId.TalkMsg, EvCmdId.TalkClose, EvCmdId.TalkCloseNoClear, EvCmdId.TalkKeyWait, EvCmdId.EasyObjMsg, EvCmdId.EasyMsg, EvCmdId.YesNoWin,
            EvCmdId.ObjAnime, EvCmdId.ObjAnimeWait, EvCmdId.SpEventDataEnd, EvCmdId.SceneChangeLabel, EvCmdId.SceneChangeData,
            EvCmdId.SceneChangeEnd, EvCmdId.FlagChangeLabel, EvCmdId.ObjChangeLabel, EvCmdId.InitChangeLabel,
            EvCmdId.AddGold, EvCmdId.SubGold, EvCmdId.CompGold, EvCmdId.FldItemEvent, EvCmdId.AddItem, EvCmdId.SubItem, EvCmdId.AddItemChk, EvCmdId.ItemChk,
            EvCmdId.MapChange, EvCmdId.MapChangeNoneFade, EvCmdId.TrainerBtlSet, EvCmdId.GetRnd, EvCmdId.GetRndNext,
            EvCmdId.AddCustumWinLabel, EvCmdId.OpenCustumWin, EvCmdId.SetSysFlag, EvCmdId.ResetSysFlag, EvCmdId.GetGold,
        };

        public static int NoOpCount => NoOp.Count;
        public static int CoreCount => Core.Count;

        // Kennungen <= 0 oder > 1234 verwirft das Original ohne Wirkung (RunEvCmd: id - 1 >= 0x4D2 -> 1); das gilt auch für -1 (Platzhalter).
        public static bool IsOutOfRange(int id) => id <= 0 || id > EvCmdId.MaxDispatchId;

        public static EvCmdKind Classify(int id)
        {
            if (IsOutOfRange(id) || NoOp.Contains(id)) return EvCmdKind.NoOp;
            return Core.Contains(id) ? EvCmdKind.Core : EvCmdKind.Host;
        }

        public static IEnumerable<int> CoreIds => Core;

        static HashSet<int> ParseRanges(string s)
        {
            var set = new HashSet<int>();
            foreach (var part in s.Split(','))
            {
                var dash = part.IndexOf('-');
                if (dash < 0) { set.Add(int.Parse(part)); continue; }
                var a = int.Parse(part.Substring(0, dash));
                var b = int.Parse(part.Substring(dash + 1));
                for (var i = a; i <= b; i++) set.Add(i);
            }
            return set;
        }
    }
}
