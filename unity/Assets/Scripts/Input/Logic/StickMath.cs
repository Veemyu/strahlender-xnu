using System;

namespace Xnu.Input
{
    // Zweidimensionaler Wert ohne UnityEngine-Abhängigkeit (die Logik bleibt rein testbar).
    public readonly struct Stick2 : IEquatable<Stick2>
    {
        public readonly float X, Y;

        public Stick2(float x, float y)
        {
            X = x; Y = y;
        }

        public static readonly Stick2 Zero = new Stick2(0f, 0f);

        public float Magnitude => (float)Math.Sqrt(X * X + Y * Y);

        public bool Equals(Stick2 o) => X == o.X && Y == o.Y;
        public override bool Equals(object obj) => obj is Stick2 o && Equals(o);
        public override int GetHashCode() => (X.GetHashCode() * 397) ^ Y.GetHashCode();
        public override string ToString() => $"({X:0.###}, {Y:0.###})";
    }

    public static class StickMath
    {
        public const float DefaultInnerDeadzone = 0.15f;
        public const float DefaultOuterDeadzone = 0.95f;

        // Kreisförmige Totzone mit Umskalierung: Beträge unter `inner` ergeben 0, Beträge ab `outer` ergeben 1;
        // dazwischen wird linear skaliert. Die Richtung bleibt erhalten (kein Achsen-Einrasten wie bei
        // einer quadratischen Totzone), der Ausgabebetrag ist nie größer als 1.
        public static Stick2 CircularDeadzone(float x, float y, float inner = DefaultInnerDeadzone, float outer = DefaultOuterDeadzone)
        {
            if (inner < 0f || inner >= 1f) throw new ArgumentOutOfRangeException(nameof(inner));
            if (outer <= inner || outer > 1f) throw new ArgumentOutOfRangeException(nameof(outer));
            if (float.IsNaN(x) || float.IsNaN(y)) return Stick2.Zero;

            var mag = (float)Math.Sqrt(x * x + y * y);
            if (mag <= inner) return Stick2.Zero;

            var scaled = Math.Min(1f, (mag - inner) / (outer - inner));
            var k = scaled / mag;
            return new Stick2(x * k, y * k);
        }

        public static Stick2 CircularDeadzone(Stick2 v, float inner = DefaultInnerDeadzone, float outer = DefaultOuterDeadzone)
            => CircularDeadzone(v.X, v.Y, inner, outer);

        // Begrenzt den Betrag auf 1 (Tastatur-Diagonalen, Maus-Deltas, Touch-Stick-Ränder).
        public static Stick2 ClampUnit(float x, float y)
        {
            if (float.IsNaN(x) || float.IsNaN(y)) return Stick2.Zero;
            var mag = (float)Math.Sqrt(x * x + y * y);
            if (mag <= 1f) return new Stick2(x, y);
            return new Stick2(x / mag, y / mag);
        }
    }
}
