namespace Xnu.Input
{
    // Logische Tasten im Stil des Switch-Controllers. A/B/X/Y sind die Funktionen, nicht die Position.
    public enum GameButton
    {
        A,
        B,
        X,
        Y,
        L,
        R,
        ZL,
        ZR,
        Plus,
        Minus,
        StickL,
        StickR,
        DpadUp,
        DpadDown,
        DpadLeft,
        DpadRight,
    }

    public static class GameButtons
    {
        public const int Count = 16;

        public static bool IsFace(GameButton b) => b <= GameButton.Y;
    }
}
