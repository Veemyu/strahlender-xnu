namespace Xnu.Battle
{
    // Xoroshiro128+ wie im Original (Spezifikation Abschnitt 4.1): Seed per splitmix-artiger Mischung, Schritt 24/16/37.
    public sealed class Xoroshiro128Plus
    {
        ulong _s0;
        ulong _s1;

        public Xoroshiro128Plus(ulong seed)
        {
            Seed(seed);
        }

        public ulong State0 => _s0;
        public ulong State1 => _s1;

        public void Seed(ulong seed)
        {
            ulong a = Mix(unchecked(seed + 0x9E3779B97F4A7C15UL));
            ulong b = Mix(unchecked(seed + 0x3C6EF372FE94F82AUL));
            if (a == 0 && b == 0) a = 1;
            _s0 = a;
            _s1 = b;
        }

        static ulong Mix(ulong z)
        {
            unchecked
            {
                z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                return z ^ (z >> 31);
            }
        }

        static ulong RotateLeft(ulong x, int k) => (x << k) | (x >> (64 - k));

        public ulong NextULong()
        {
            unchecked
            {
                ulong s0 = _s0;
                ulong s1 = _s1;
                ulong result = s0 + s1;
                ulong t = s1 ^ s0;
                _s0 = RotateLeft(s0, 24) ^ t ^ (t << 16);
                _s1 = RotateLeft(t, 37);
                return result;
            }
        }

        public uint NextUInt() => (uint)(NextULong() >> 32);
    }
}
