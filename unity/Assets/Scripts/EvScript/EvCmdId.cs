namespace Xnu.EvScript
{
    // Befehlskennungen (EvCmdID.NAME, dump.cs), die der Interpreter selbst ausführt.
    // Alle Zuordnungen Kennung -> Handler stammen aus der Sprungtabelle von EvDataManager.RunEvCmd (Pseudocode, siehe docs/evscript-spezifikation.md).
    public static class EvCmdId
    {
        public const int Nop = 1;                 // Handler wie END
        public const int End = 3;
        public const int TimeWait = 4;
        public const int ChgCommonScr = 22;       // Handler wie CALL
        public const int ChgLocalScr = 23;        // Handler wie RET
        public const int Jump = 24;
        public const int Call = 28;
        public const int Ret = 29;
        public const int IfJump = 30;
        public const int IfCall = 31;
        public const int IfValJump = 32;
        public const int IfValCall = 33;
        public const int IfWkJump = 34;           // Handler wie IFVAL_JUMP
        public const int IfWkCall = 35;           // Handler wie IFVAL_CALL
        public const int Switch = 36;
        public const int CaseJump = 37;
        public const int FlagSet = 41;
        public const int ArriveFlagSet = 42;      // setzt ein Systemflag
        public const int FlagReset = 43;
        public const int IfFlagOnJump = 45;
        public const int IfFlagOffJump = 46;
        public const int IfFlagOnCall = 47;
        public const int IfFlagOffCall = 48;
        public const int FlagSetWk = 50;
        public const int TrainerFlagSet = 51;
        public const int TrainerFlagReset = 52;
        public const int TrainerFlagCheck = 53;
        public const int IfTrFlagOnJump = 54;
        public const int IfTrFlagOffJump = 55;
        public const int IfTrFlagOnCall = 56;
        public const int IfTrFlagOffCall = 57;
        public const int AddWk = 58;
        public const int CmpWk = 19;              // Vergleich zweier Arbeitswerte (setzt _cmp_flag)
        public const int CaseCancel = 38;         // Makro: Work 0xF2 gegen Work 0xF8, Sprung bei Gleichheit
        public const int WorkCaseCancel = 0xF8;
        public const int SubWk = 59;
        public const int LdVal = 60;
        public const int LdWk = 61;
        public const int LdWkVal = 62;
        public const int TalkMsg = 70;
        public const int TalkOpen = 80;
        public const int TalkClose = 81;
        public const int TalkCloseNoClear = 82;
        public const int TalkKeyWait = 83;        // gleicher Handler wie TALKMSG
        public const int EasyObjMsg = 84;
        public const int EasyMsg = 85;
        public const int YesNoWin = 96;
        public const int ObjAnime = 136;
        public const int ObjAnimeWait = 140;
        public const int EventStart = 155;
        public const int TalkEnd = 156;
        public const int EventEnd = 157;
        public const int TalkObjStart = 151;
        public const int TalkObjEnd = 153;
        public const int SpEventDataEnd = 168;    // Handler wie END
        public const int SceneChangeLabel = 169;  // Sprung auf ein Label
        public const int SceneChangeData = 170;
        public const int SceneChangeEnd = 171;    // Handler wie END
        public const int FlagChangeLabel = 172;
        public const int ObjChangeLabel = 173;
        public const int InitChangeLabel = 174;
        public const int AddGold = 175;
        public const int SubGold = 176;
        public const int CompGold = 177;
        public const int FldItemEvent = 187;
        public const int AddItem = 189;
        public const int SubItem = 190;
        public const int AddItemChk = 191;
        public const int ItemChk = 192;
        public const int MapChange = 285;
        public const int MapChangeNoneFade = 286;
        public const int TrainerBtlSet = 335;
        public const int TrainerMultiBtlSet = 336;
        public const int GetRnd = 555;
        public const int GetRndNext = 556;
        public const int AddCustumWinLabel = 821;
        public const int OpenCustumWin = 822;
        public const int SetSysFlag = 873;
        public const int ResetSysFlag = 874;
        public const int GetGold = 1207;

        // Arbeitswerte, die der Interpreter selbst belegt (Indizes von FlagWork.GetWork/SetWork).
        public const int WorkTalkWindow = 199;    // TALK_CLOSE setzt den Wert auf 0
        public const int WorkItemEventA = 0xF2;   // FLD_ITEM_EVENT: erster Parameter
        public const int WorkItemEventB = 0xF3;   // FLD_ITEM_EVENT: zweiter Parameter

        // Das Original verwirft Kennungen ausserhalb dieses Bereichs still (RunEvCmd liefert 1).
        public const int MaxDispatchId = 1234;
    }
}
