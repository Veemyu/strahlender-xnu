using System;
using System.Collections.Generic;

namespace Xnu.Battle.Flow
{
    // Die KI-Skripte des Originals (BtlAiBasic, BtlAiExpert, ...) fragen den Kampf nur ueber AI_CMD ab.
    public interface IAiHost
    {
        long Call(int cmd, long[] args);
    }

    // Befehlsnummern (Enum AICmd im Original), soweit die umgesetzten Skripte sie brauchen.
    public static class AiCmd
    {
        public const int IfRndUnder = 0, IfRndOver = 1, IfRndEqual = 2, IfnRndEqual = 3, IfHpUnder = 4, IfHpOver = 5, IfHpEqual = 6, IfnHpEqual = 7, IfPokeSick = 8,
            IfnPokeSick = 9, IfWazaSick = 10, IfnWazaSick = 11, IfDokudoku = 12, IfnDokudoku = 13, IfContFlg = 14, IfnContflg = 15, IfSideEff = 16,
            IfnSideeff = 17, GetHorobinoutaTurnMax = 18, GetHorobinoutaTurnNow = 19, GetKodawariWaza = 20, IfHaveDamageWaza = 21, IfnHaveDamageWaza = 22,
            CheckTurn = 23, CheckType = 24, CheckWazaUsable = 25, CheckDamageWaza = 26, CheckIryoku = 27, CompPower = 28, CheckLastWaza = 29, IfFirst = 30,
            CheckBenchCount = 31, CheckWazaSeqNo = 32, CheckTokusei = 33, CheckWazaAisyou = 34, GetWazaAisyou = 35, IfHaveWazaAisyouOver = 36,
            IfHaveWazaAisyouEqual = 37, IfBenchCond = 38, IfnBenchCond = 39, CheckWeather = 40, IfParaUnder = 41, IfParaOver = 42, IfParaEqual = 43,
            IfnParaEqual = 44, IfWazaHinshi = 45, IfnWazaHinshi = 46, IfHaveWaza = 47, IfnHaveWaza = 48, IfHaveWazaSeqno = 49, IfnHaveWazaSeqno = 50,
            Escape = 51, CheckSoubiItem = 52, CheckSoubiEquip = 53, CheckPokeSex = 54, CheckNekodamasi = 55, CheckTakuwaeru = 56, CheckBtlRule = 57,
            CheckBtlCompetitor = 58, CheckRecycleItem = 59, CheckWorkWazaType = 60, CheckWorkWazaPow = 61, CheckWorkWazaSeqNo = 62, CheckMamoruCount = 63,
            IfLevel = 64, IfChouhatsu = 65, IfnChouhatsu = 66, IfMikataAttack = 67, CheckHaveType = 68, CheckHaveTokusei = 69, IfAlreadyMoraibi = 70,
            IfHaveItem = 71, FldEffCheck = 72, CheckSideEffCount = 73, IfBenchHpDec = 74, IfBenchPpdec = 75, CheckNagetsukeruIryoku = 76, CheckPpRemain = 77,
            IfTotteoki = 78, CheckWazaKind = 79, CheckLastWazaKind = 80, CheckAgiRank = 81, CheckSlowstartTurn = 82, IfBenchDamageMax = 83, IfHaveBatsugun = 84,
            IfLastWazaDamageCheck = 85, CheckStatusUp = 86, CheckStatusDiff = 87, CheckStatus = 88, CompPowerWithPartner = 89, IfHinshi = 90, IfnHinshi = 91,
            GetTokusei = 92, IfMigawari = 93, CheckMonsNo = 94, CheckFormno = 95, IfCommonrndUnder = 96, IfCommonrndOver = 97, IfCommonrndEqual = 98,
            IfnCommonrndEqual = 99, IfMiraiyochi = 100, IfDmgPhysicUnder = 101, IfDmgPhysicOver = 102, IfDmgPhysicEqual = 103, IfAteKinomi = 104, IfTypeEx = 105,
            IfExistGround = 106, GetWeight = 107, IfMulti = 108, IfMegaEvolved = 109, IfCanMegaevolve = 110, IfWazahide = 111, GetMezameType = 112,
            IfSenarioTrainer = 113, GetMaxWazaPower = 114, CheckWazaNoEffectByTokusei = 115, GetLastDamagedWazaAtPrevTurn = 116, GetCurrentWazaNo = 117,
            GetCurrentItemNo = 118, IfZidandaPowerup = 119, GetClientKillCount = 120, GetWazaTarget = 121, IfHaveBatsugunCanBench = 122, IfG = 123,
            IfHaveKinomi = 124, IfGwallExist = 125, IfJk3Legend = 126, IfCanG = 127, IfGWazaUseTurn = 128, IfCanChagePoke = 129, Count = 130;
    }

    // Grundlage der Skriptklassen: Wertungsfeld p_Score (+0x14 im Original), Wechselfreigabe, Abfrage-Ruf.
    public abstract class AiScriptBase
    {
        protected static readonly long[] Empty = new long[0];

        public int Score;
        public int PokeChangeEnable;
        public IAiHost Host;
        public long MyClientId = 1;

        protected long Call(int cmd, long[] args) => Host.Call(cmd, args);

        protected long Call(int cmd, long a0) => Host.Call(cmd, new[] { a0 });

        protected long CurrentWaza() => Host.Call(AiCmd.GetCurrentWazaNo, Empty);

        // Befehl mit Argumentfeld der Laenge `len` (nicht gesetzte Plaetze 0), wie `new long[len]` im Original.
        protected long C(int cmd, int len, params long[] values) => Host.Call(cmd, A(len, values));

        // Zahlen-Argumentfeld fester Laenge wie im Original (Laenge zaehlt in der Aufruffolge mit).
        protected static long[] A(int length, params long[] values)
        {
            var a = new long[length];
            Array.Copy(values, a, values.Length);
            return a;
        }

        // Bereichspruefung der Form `x - basis < breite && Bitmaske >> (x - basis) & 1` (Wertebereich als vorzeichenlose Differenz).
        protected static bool InMask(long x, long basis, int width, ulong mask)
        {
            ulong d = unchecked((ulong)(x - basis));
            return d < (ulong)width && (mask >> (int)d & 1) != 0;
        }

        // Bitmaskenpruefung `(1 << (x & 0x3f)) & mask != 0` des Originals.
        protected static bool Bit(ulong x, ulong mask) => ((mask >> (int)(x & 0x3f)) & 1) != 0;

        protected static bool Bit32(ulong x, uint mask) => ((mask >> (int)(x & 0x1f)) & 1) != 0;

        // Ausfuehrbare Einsprungstellen (Name wie im Original) fuer das Orakel; liefert 0/1 oder den Rueckgabewert.
        public abstract long Run(string function);

        public abstract IEnumerable<string> Functions { get; }
    }
}
