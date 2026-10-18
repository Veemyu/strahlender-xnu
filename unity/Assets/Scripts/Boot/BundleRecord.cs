using System;

namespace Xnu.Boot
{
    // 128-Bit-Hash eines Bundles, als vier uint (wie im Katalog gespeichert).
    public readonly struct BundleHash : IEquatable<BundleHash>
    {
        public readonly uint U0, U1, U2, U3;

        public BundleHash(uint u0, uint u1, uint u2, uint u3) { U0 = u0; U1 = u1; U2 = u2; U3 = u3; }

        public bool IsValid => (U0 | U1 | U2 | U3) != 0;

        static uint Swap(uint x) => (x >> 24) | ((x >> 8) & 0xFF00u) | ((x << 8) & 0xFF0000u) | (x << 24);

        // 32 Hex-Zeichen in Byte-Reihenfolge (wie Unitys Hash128.ToString()).
        public override string ToString() =>
            Swap(U0).ToString("x8") + Swap(U1).ToString("x8") + Swap(U2).ToString("x8") + Swap(U3).ToString("x8");

        public bool Equals(BundleHash o) => U0 == o.U0 && U1 == o.U1 && U2 == o.U2 && U3 == o.U3;
        public override bool Equals(object obj) => obj is BundleHash h && Equals(h);
        public override int GetHashCode() => unchecked((int)(U0 ^ (U1 * 31) ^ (U2 * 131) ^ (U3 * 1031)));
    }

    // Ein Eintrag des Bundle-Katalogs. Datei liegt unter <AssetAssistant>/<Project>/<Name>.
    public sealed class BundleRecord
    {
        public string Project;
        public string Name;
        public BundleHash Hash;
        public long LastWriteTimeRaw;
        public bool IsStreamedScene;
        public string[] Dependencies = Array.Empty<string>();
        public string[] AssetPaths = Array.Empty<string>();
        public long Size;

        // Eindeutiger Schlüssel: "Projekt/Name" (entspricht dem relativen Dateipfad).
        public string FullName => string.IsNullOrEmpty(Project) ? Name : Project + "/" + Name;

        public override string ToString() => FullName;
    }
}
