namespace Xnu.Field
{
    public enum BlockReason
    {
        None,
        Stop,           // Stop-Wert 128 (Wand, Tresen, Möbel)
        NoEntry,        // Code nicht betretbar (MapAttributeTable.Entry = 0)
        Water,          // Wasserzelle, Spieler läuft
        Land,           // Landzelle, Spieler schwimmt
        Ledge,          // Absprungkante (Takeoff), zu Fuß nicht betretbar
        BicycleNoEntry, // Fahrrad auf Gras/Schnee/Sumpf
        Bridge,         // Brücke von oben, quer zur Brückenrichtung
    }

    public readonly struct EnterResult
    {
        public readonly bool CanEnter;
        public readonly BlockReason Reason;
        public EnterResult(bool canEnter, BlockReason reason) { CanEnter = canEnter; Reason = reason; }
    }

    // Betretbarkeit einer Zelle nach FieldPlayerEntity.CanEntryAttribute (Parameter: Höhe, Zelle, Fahrrad, Schwimmen).
    // Die Brücken-Zweige folgen dem dekompilierten Ablauf; die Namen der Codes stammen aus AttributeID.
    public sealed class FieldCollision
    {
        readonly AttributeLayer _main;
        readonly AttributeLayer _ex;
        readonly AttributeCodeTable _table;

        // outsideBlocked: Zellen ohne Block gelten als gesperrt (Abweichung vom Original, schützt vor dem Verlassen der Karte).
        public bool OutsideBlocked { get; set; } = true;

        public FieldCollision(AttributeLayer main, AttributeLayer ex, AttributeCodeTable table)
        {
            _main = main ?? throw new System.ArgumentNullException(nameof(main));
            _ex = ex;
            _table = table ?? throw new System.ArgumentNullException(nameof(table));
        }

        public AttributeLayer Main => _main;

        public AttributeCell CellAt(int gx, int gy) => _main.Get(gx, gy);

        public EnterResult CanEnter(int gx, int gy, float height, bool bicycle, bool swim)
        {
            if (OutsideBlocked && !_main.HasBlockAt(gx, gy)) return new EnterResult(false, BlockReason.NoEntry);

            var cell = _main.Get(gx, gy);
            if (cell.IsBlocked) return new EnterResult(false, BlockReason.Stop);
            if (!_table.TryGet(cell.Code, out var e) || !e.CanEnter) return new EnterResult(false, BlockReason.NoEntry);

            if (AttributeCodes.IsBridge(cell.Code))
            {
                var exRaw = _ex != null ? _ex.GetRaw(gx, gy) : 0;
                if (!ExAttribute.IsHigh(exRaw, height))
                {
                    if (e.Water && swim) return new EnterResult(true, BlockReason.None);   // unter der Brücke schwimmen
                }
                else if (e.Water)
                {
                    if (!swim) return new EnterResult(true, BlockReason.None);             // über das Wasser gehen
                }
                else if (!bicycle && (AttributeCodes.IsBridgeVertical(cell.Code) || AttributeCodes.IsBridgeHorizontal(cell.Code)))
                {
                    return new EnterResult(false, BlockReason.Bridge);
                }
            }

            if (bicycle && AttributeCodes.IsBicycleNoEntry(e.Attribute))
                return new EnterResult(false, BlockReason.BicycleNoEntry);
            if (!bicycle && (e.Attribute == AttributeCodes.TakeOffLeft || e.Attribute == AttributeCodes.TakeOffRight))
                return new EnterResult(false, BlockReason.Ledge);

            // Ergebnis: Schwimmer nur auf Wasser, Läufer nur auf Land.
            if (swim != e.Water) return new EnterResult(false, e.Water ? BlockReason.Water : BlockReason.Land);
            return new EnterResult(true, BlockReason.None);
        }
    }
}
