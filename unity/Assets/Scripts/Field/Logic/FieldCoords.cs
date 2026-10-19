namespace Xnu.Field
{
    // Koordinaten des Feldes (Befund aus FieldObjectEntity.get_gridPosition / set_gridPosition):
    // Rasterzelle (gx, gy) <-> Weltposition (x, z): gx = (int)(0.5 - x), gy = (int)(z + 0.5), d. h. x = -gx, z = gy.
    // Eine Zelle ist 1 Einheit groß, die Zellmitte liegt auf ganzzahligen Weltkoordinaten. Y ist die Höhe.
    // Attribut-Blöcke und Zonenraster sind 32 x 32 Zellen groß (Block = gx >> 5, gy >> 5).
    public static class FieldCoords
    {
        public const int BlockSize = 32;

        public static float WorldX(int gx) => -gx;
        public static float WorldZ(int gy) => gy;

        // (int)-Umwandlung wie im Original (Abschneiden Richtung 0).
        public static int GridX(float worldX) => (int)(0.5f - worldX);
        public static int GridY(float worldZ) => (int)(worldZ + 0.5f);

        public static int BlockOf(int g) => g >> 5;
        public static int CellInBlock(int g) => g & (BlockSize - 1);

        // Ursprung (Weltposition der Ecke) eines Blocks: Container der Feldkarte liegen bei (-32 * Spalte, 0, 32 * Zeile).
        public static float BlockOriginX(int blockColumn) => -BlockSize * blockColumn;
        public static float BlockOriginZ(int blockRow) => BlockSize * blockRow;

        public static int BlockColumnOfOriginX(float originX) => (int)System.Math.Round(-originX / BlockSize);
        public static int BlockRowOfOriginZ(float originZ) => (int)System.Math.Round(originZ / BlockSize);
    }
}
