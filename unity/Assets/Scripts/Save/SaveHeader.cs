using System;

namespace Xnu.Save
{
    // Auswertbarer Kopf einer Save-Datei: Version (vorzeichenbehaftetes Int32 LE am Anfang) und Dateigröße.
    public readonly struct SaveHeader
    {
        public int Version { get; }
        public int Size { get; }

        public SaveHeader(int version, int size)
        {
            Version = version;
            Size = size;
        }
    }

    // Datei lässt sich nicht als Save einordnen (zu kurz, unbekannte Version, abgeschnitten).
    public sealed class SaveFormatException : Exception
    {
        public SaveFormatException(string message) : base(message) { }
    }
}
