namespace Xnu.Field
{
    // Zellwert eines Attributblocks (Befund aus GameManager.GetAttribute):
    // roh < 1000: nur "Stop" (Code 0); sonst Code = roh / 1000 und Stop = roh % 1000.
    // Stop 128 sperrt die Zelle (Wand, Tresen); Code verweist auf MapAttributeTable (Zeile = Code).
    public readonly struct AttributeCell
    {
        public const int StopBlocked = 128;

        public readonly int Code;
        public readonly int Stop;

        public AttributeCell(int code, int stop) { Code = code; Stop = stop; }

        public bool IsBlocked => Stop == StopBlocked;

        public static AttributeCell Decode(int raw)
        {
            if (raw < 1000) return new AttributeCell(0, raw);
            return new AttributeCell(raw / 1000, raw % 1000);
        }

        public override string ToString() => "code " + Code + " stop " + Stop;
    }

    // Raw-Wert der zweiten Matrix (AttributeEx): rohHöhe * 1_000_000 + hoch * 1000 + tief.
    // Ist die Spielerhöhe + 100,5 (abgeschnitten) mindestens rohHöhe, gilt der mittlere Teil
    // (Brücke: Spieler steht darauf), sonst der untere (Spieler geht darunter). Befund: GameManager.HeightAttribute/IsHighAttribute.
    public static class ExAttribute
    {
        public static bool IsHigh(int raw, float height) => raw / 1000000 <= (int)(height + 100.5f);

        public static int HeightAttribute(int raw, float height)
        {
            if (IsHigh(raw, height)) raw /= 1000;
            return raw % 1000;
        }
    }
}
