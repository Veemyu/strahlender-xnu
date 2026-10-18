using System;

namespace Xnu.Input
{
    public enum Direction8
    {
        None,
        North,
        NorthEast,
        East,
        SouthEast,
        South,
        SouthWest,
        West,
        NorthWest,
    }

    public static class DirectionMath
    {
        // Sektor 0 = Osten, gegen den Uhrzeigersinn in 45°-Schritten (y nach oben).
        private static readonly Direction8[] BySector =
        {
            Direction8.East, Direction8.NorthEast, Direction8.North, Direction8.NorthWest,
            Direction8.West, Direction8.SouthWest, Direction8.South, Direction8.SouthEast,
        };

        public static (int X, int Y) Step(Direction8 d)
        {
            switch (d)
            {
                case Direction8.North: return (0, 1);
                case Direction8.NorthEast: return (1, 1);
                case Direction8.East: return (1, 0);
                case Direction8.SouthEast: return (1, -1);
                case Direction8.South: return (0, -1);
                case Direction8.SouthWest: return (-1, -1);
                case Direction8.West: return (-1, 0);
                case Direction8.NorthWest: return (-1, 1);
                default: return (0, 0);
            }
        }

        public static bool IsDiagonal(Direction8 d)
            => d == Direction8.NorthEast || d == Direction8.SouthEast || d == Direction8.SouthWest || d == Direction8.NorthWest;

        // Reduziert eine Diagonale auf die dominante Achse; bei exakt gleichem Betrag gewinnt die Vertikale.
        public static Direction8 ToFourWay(float x, float y)
        {
            if (x == 0f && y == 0f) return Direction8.None;
            if (Math.Abs(y) >= Math.Abs(x)) return y > 0f ? Direction8.North : Direction8.South;
            return x > 0f ? Direction8.East : Direction8.West;
        }

        // Zustandslose Quantisierung (ohne Hysterese) für einmalige Abfragen.
        public static Direction8 Quantize(float x, float y, float threshold = 0.5f, bool diagonals = true)
        {
            var q = new Direction8Quantizer(threshold, threshold, 0f, diagonals);
            return q.Update(x, y);
        }

        internal static float AngleDegrees(float x, float y)
        {
            var a = (float)(Math.Atan2(y, x) * 180.0 / Math.PI);
            return a < 0f ? a + 360f : a;
        }

        internal static Direction8 FromSector(int sector8) => BySector[((sector8 % 8) + 8) % 8];
    }

    // Wandelt einen Analogstick in 8 (oder 4) Richtungen für Gitterbewegung. Mit Hysterese: Eine einmal
    // gewählte Richtung bleibt, bis der Stick ein Stück über die Sektorgrenze hinaus ist, und der Stick
    // muss zum Loslassen weiter zurück als zum Auslösen – das verhindert Flackern an den Grenzen.
    public sealed class Direction8Quantizer
    {
        private readonly float _enter, _exit, _hysteresisDeg;
        private readonly bool _diagonals;

        public Direction8 Current { get; private set; }

        public Direction8Quantizer(float enterThreshold = 0.5f, float exitThreshold = 0.35f, float hysteresisDegrees = 8f, bool diagonals = true)
        {
            if (enterThreshold <= 0f || enterThreshold > 1f) throw new ArgumentOutOfRangeException(nameof(enterThreshold));
            if (exitThreshold <= 0f || exitThreshold > enterThreshold) throw new ArgumentOutOfRangeException(nameof(exitThreshold));
            if (hysteresisDegrees < 0f || hysteresisDegrees >= 22.5f) throw new ArgumentOutOfRangeException(nameof(hysteresisDegrees));
            _enter = enterThreshold;
            _exit = exitThreshold;
            _hysteresisDeg = hysteresisDegrees;
            _diagonals = diagonals;
        }

        public void Reset() => Current = Direction8.None;

        public Direction8 Update(float x, float y)
        {
            var mag = (float)Math.Sqrt(x * x + y * y);
            if (float.IsNaN(mag) || mag < (Current == Direction8.None ? _enter : _exit))
            {
                Current = Direction8.None;
                return Current;
            }

            var angle = DirectionMath.AngleDegrees(x, y);
            var sectorWidth = _diagonals ? 45f : 90f;

            if (Current != Direction8.None)
            {
                var centre = CentreAngle(Current);
                if (AngularDistance(angle, centre) <= sectorWidth * 0.5f + _hysteresisDeg) return Current;
            }

            var sector = (int)Math.Round(angle / sectorWidth) % (_diagonals ? 8 : 4);
            Current = DirectionMath.FromSector(_diagonals ? sector : sector * 2);
            return Current;
        }

        private static float CentreAngle(Direction8 d)
        {
            switch (d)
            {
                case Direction8.East: return 0f;
                case Direction8.NorthEast: return 45f;
                case Direction8.North: return 90f;
                case Direction8.NorthWest: return 135f;
                case Direction8.West: return 180f;
                case Direction8.SouthWest: return 225f;
                case Direction8.South: return 270f;
                default: return 315f;
            }
        }

        private static float AngularDistance(float a, float b)
        {
            var d = Math.Abs(a - b) % 360f;
            return d > 180f ? 360f - d : d;
        }
    }
}
