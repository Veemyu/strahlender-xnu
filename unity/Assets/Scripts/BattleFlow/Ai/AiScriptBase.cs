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
        public const int IfRndUnder = 0, IfRndOver = 1, IfHpUnder = 4, IfHpOver = 5, IfHpEqual = 6, IfPokeSick = 8, IfnPokeSick = 9, IfWazaSick = 10, IfnWazaSick = 11,
            IfContFlg = 14, IfSideEff = 16, GetKodawariWaza = 20, IfHaveDamageWaza = 21, CheckTurn = 23, CheckType = 24, CheckWazaUsable = 25, CheckDamageWaza = 26,
            CompPower = 28, CheckLastWaza = 29, IfFirst = 30, CheckBenchCount = 31, CheckWazaSeqNo = 32, CheckTokusei = 33, CheckWazaAisyou = 34,
            IfHaveWazaAisyouOver = 36, IfBenchCond = 38, IfnBenchCond = 39, CheckWeather = 40, IfParaUnder = 41, IfParaOver = 42, IfParaEqual = 43, IfWazaHinshi = 45,
            CheckSoubiItem = 52, CheckSoubiEquip = 53, CheckPokeSex = 54, CheckNekodamasi = 55, CheckTakuwaeru = 56, CheckBtlRule = 57, CheckRecycleItem = 59,
            CheckWorkWazaType = 60, CheckWorkWazaPow = 61, CheckWorkWazaSeqNo = 62, IfLevel = 64, IfMikataAttack = 67, IfHaveItem = 71, FldEffCheck = 72,
            CheckSideEffCount = 73, IfBenchHpDec = 74, IfTotteoki = 78, CheckWazaKind = 79, IfHaveBatsugun = 84, CheckStatusUp = 86, IfMigawari = 93, CheckMonsNo = 94,
            IfMiraiyochi = 100, IfAteKinomi = 104, IfTypeEx = 105, IfExistGround = 106, GetWeight = 107, IfMulti = 108, IfMegaEvolved = 109, IfSenarioTrainer = 113,
            GetMaxWazaPower = 114, CheckWazaNoEffectByTokusei = 115, GetCurrentWazaNo = 117, GetCurrentItemNo = 118, GetWazaTarget = 121, IfG = 123, IfHaveKinomi = 124,
            IfCanG = 127, IfGWazaUseTurn = 128, Count = 130;
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

        // Ausfuehrbare Einsprungstellen (Name wie im Original) fuer das Orakel; liefert 0/1 oder den Rueckgabewert.
        public abstract long Run(string function);

        public abstract IEnumerable<string> Functions { get; }
    }
}
