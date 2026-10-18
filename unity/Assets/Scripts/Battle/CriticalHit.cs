using System;

namespace Xnu.Battle
{
    // Eingaben der Volltrefferpruefung (Spezifikation Abschnitt 7).
    public sealed class CriticalInput
    {
        // Volltrefferstufe der Attacke aus den Attackendaten (0..2; 6 = immer Volltreffer).
        public int MoveStage { get; set; }

        // Volltrefferstufe des Angreifers (BTL_POKEPARAM.GetCriticalRank, 0..3).
        public int AttackerStage { get; set; }

        // Stufe nach den Handlern (Ereignis 0x43); null = Handler aendern nichts.
        public int? StageAfterHandlers { get; set; }

        // Handler verbietet Volltreffer.
        public bool Forbidden { get; set; }

        public bool IsDemoCapture { get; set; }

        // Freundschaft des Angreifers ist 255 und die Zuneigung ist aktiv: Teiler 2 und Bonus-Flag.
        public bool AttackerMaxFriendship { get; set; }
    }

    public struct CriticalResult
    {
        public bool Critical;
        public bool FriendshipBonus;
        public bool UsedRandom;
    }

    public static class CriticalHit
    {
        public const int AlwaysStage = 6;

        // 1/24, 1/8, 1/2, 1/1 fuer die Stufen 0..3.
        static readonly byte[] Table = { 24, 8, 2, 1 };

        public static int Denominator(int stage, int divisor)
        {
            int n = Table[Math.Min(stage, 3)] / divisor;
            return n == 0 ? 1 : n;
        }

        // calc.CheckCritical: Volltreffer, wenn GetValue(Nenner) == 0 (ein Zufallszug).
        public static bool RollStage(int stage, int divisor, IBattleRandom random)
        {
            return random.GetValue((ulong)Denominator(stage, divisor)) == 0;
        }

        // Event_CheckCritical; genau ein Zufallszug, ausser bei Verbot, garantiertem Volltreffer oder Demo-Fang.
        public static CriticalResult Check(CriticalInput input, IBattleRandom random)
        {
            int stage = input.MoveStage == AlwaysStage ? AlwaysStage : input.AttackerStage + input.MoveStage;
            if (input.StageAfterHandlers.HasValue) stage = input.StageAfterHandlers.Value;
            stage = Math.Min(stage, 3);

            if (input.Forbidden) return default;
            if (input.MoveStage == AlwaysStage) return new CriticalResult { Critical = !input.IsDemoCapture };
            if (input.IsDemoCapture) return default;

            int divisor = input.AttackerMaxFriendship ? 2 : 1;
            bool crit = RollStage(stage, divisor, random);
            return new CriticalResult { Critical = crit, FriendshipBonus = crit && input.AttackerMaxFriendship, UsedRandom = true };
        }
    }
}
