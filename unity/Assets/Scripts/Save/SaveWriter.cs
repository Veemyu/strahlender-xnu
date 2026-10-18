using System;

namespace Xnu.Save
{
    public static class SaveWriter
    {
        // Liefert eine Kopie von data mit korrektem Hash; die Eingabe bleibt unverändert.
        public static byte[] FixHash(byte[] data)
        {
            var version = SaveValidator.ReadHeader(data).Version;
            if (version < SaveLayout.LaunchVersion)
                throw new SaveFormatException(string.Format(
                    "Version unter 0x{0:X} hat keinen Hash", SaveLayout.LaunchVersion));
            var hash = SaveValidator.ComputeHash(data, version);
            var copy = (byte[])data.Clone();
            Buffer.BlockCopy(hash, 0, copy, SaveLayout.HashOffset, SaveLayout.HashLength);
            return copy;
        }
    }
}
