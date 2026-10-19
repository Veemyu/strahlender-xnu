namespace Xnu.Field
{
    // Bildschirmrichtungen der Feldkamera (Yaw 0): oben = +Z (gy + 1), rechts = +X (gx - 1).
    public enum MoveDir
    {
        None,
        Up,
        Right,
        Down,
        Left,
    }

    public static class MoveDirExt
    {
        // Rasterschritt (gx, gy).
        public static (int Dx, int Dy) GridDelta(this MoveDir d)
        {
            switch (d)
            {
                case MoveDir.Up: return (0, 1);
                case MoveDir.Right: return (-1, 0);
                case MoveDir.Down: return (0, -1);
                case MoveDir.Left: return (1, 0);
                default: return (0, 0);
            }
        }

        // Blickrichtung als Gierwinkel in Grad um die Y-Achse (0 = +Z, 90 = +X).
        public static float YawDegrees(this MoveDir d)
        {
            switch (d)
            {
                case MoveDir.Right: return 90f;
                case MoveDir.Down: return 180f;
                case MoveDir.Left: return 270f;
                default: return 0f;
            }
        }
    }

    // Eingabe auf vier Richtungen: Befund aus FieldPlayerEntity.LimitedCrossInput – die größere Achse gewinnt,
    // bei Gleichstand die horizontale (|y| <= |x|).
    public static class FieldInputMath
    {
        public static MoveDir LimitToFourWay(float x, float y, float deadzone = 0f)
        {
            var ax = System.Math.Abs(x);
            var ay = System.Math.Abs(y);
            if (ax <= deadzone && ay <= deadzone) return MoveDir.None;
            if (ay <= ax) return x >= 0f ? MoveDir.Right : MoveDir.Left;
            return y >= 0f ? MoveDir.Up : MoveDir.Down;
        }
    }
}
