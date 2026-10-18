namespace Xnu.Battle
{
    // Eingaben der Trefferpruefung (Spezifikation Abschnitt 6). Genauigkeit nach Handler-Ereignissen, Stufen im 0..12-System
    // (6 = neutral), Handler-Faktor (Variable 0x38 nach dem Ereignis; Start 0x1000) werden von aussen geliefert.
    public sealed class HitInput
    {
        // Attackengenauigkeit nach Event_getHitPer (Prozent; 0 = trifft nie, wenn die Pruefung laeuft).
        public uint HitPercent { get; set; }

        public int AccuracyStage { get; set; } = 6;
        public int EvasionStage { get; set; } = 6;

        // Handler duerfen die Fluchtstufe ignorieren lassen.
        public bool IgnoreEvasion { get; set; }

        // Ziel hat den Zustand "Foresight" (WAZASICK_MIYABURU): positive Fluchtstufen zaehlen nicht.
        public bool TargetIdentified { get; set; }

        // Handler-Faktor aus Ereignis 0x3F (x/4096).
        public int HandlerRatio { get; set; } = 0x1000;

        // Zug-Flag 0xE des Angreifers: Faktor zusaetzlich x0x1333.
        public bool AttackerTurnBoost { get; set; }

        // Automatische Treffer (kein Zufallszug): CheckMustHit, Demo-Fang, IsCalcHitCancel, Ziel unter Telekinese (Zustand 0x21).
        public bool MustHit { get; set; }
        public bool IsDemoCapture { get; set; }
        public bool CancelsHitCheck { get; set; }
        public bool TargetTelekinesis { get; set; }

        // Freundschaft des Ziels ist 255 und die Zuneigung ist aktiv (Spieler-Pokemon in Wild-/Trainerkaempfen).
        public bool TargetMaxFriendship { get; set; }
    }

    public struct HitResult
    {
        public bool Hit;
        public bool FriendshipEvaded;

        // Endgueltige Trefferwahrscheinlichkeit in Prozent (0 bei automatischem Treffer).
        public uint Percent;

        public bool UsedRandom;
    }

    public static class AccuracyCalculator
    {
        const int HandlerMin = 0x29;
        const int HandlerMax = 0x20000;

        // Stufen-Faktor ohne Zufall; liefert die Wahrscheinlichkeit nach Schritt 7.
        public static uint Percent(HitInput input, out bool friendshipEvaded)
        {
            int ratio = input.HandlerRatio;
            if (input.AttackerTurnBoost) ratio = BattleMath.EventVarMul(ratio, 0x1333, HandlerMin, HandlerMax);

            int evaTerm = input.IgnoreEvasion || (input.TargetIdentified && input.EvasionStage > 6) ? -6 : -input.EvasionStage;
            int idx = BattleMath.RoundValue(evaTerm + input.AccuracyStage + 6, 0, 12);

            uint p = BattleMath.HitPercentByStage(input.HitPercent, idx);
            p = BattleMath.MulRatio(p, (uint)ratio);
            if (p > 99) p = 100;

            friendshipEvaded = false;
            if (input.TargetMaxFriendship)
            {
                p = p > 10 ? p - 10 : 0;
                friendshipEvaded = true;
            }
            return p;
        }

        // Event_CheckHit: automatische Treffer ziehen keinen Zufall; sonst genau ein Zug GetValue(100).
        public static HitResult Check(HitInput input, IBattleRandom random)
        {
            if (input.MustHit || input.IsDemoCapture || input.CancelsHitCheck || input.TargetTelekinesis)
                return new HitResult { Hit = true };

            uint p = Percent(input, out bool evaded);
            uint roll = (uint)random.GetValue(100);
            return new HitResult
            {
                Hit = (roll & 0xFF) < (p & 0xFF),
                FriendshipEvaded = evaded,
                Percent = p,
                UsedRandom = true,
            };
        }
    }
}
