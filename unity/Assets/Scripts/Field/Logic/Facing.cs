namespace Xnu.Field
{
    // Blickrichtungen in den Stammdaten. Locator-Zahl (MapInfo.Locators[i].z) und Rotation (PlaceData) sind
    // Viertelschritte im Raster-/Weltsystem von FieldCoords: 0 = oben (+gy), 1 = rechts (gx - 1), 2 = unten, 3 = links.
    // Belegt an Zone 425 (Locator 0 = Tür, z 2 = in den Raum hinein) und Zone 422 (Locator 0, z 0 = von der Haustür weg).
    public static class Facing
    {
        public static MoveDir FromQuarter(int quarter)
        {
            switch (((quarter % 4) + 4) % 4)
            {
                case 0: return MoveDir.Up;
                case 1: return MoveDir.Right;
                case 2: return MoveDir.Down;
                default: return MoveDir.Left;
            }
        }

        // PlaceData.Rotation in Grad (0, 90, 180, 270); gleiche Reihenfolge wie die Viertel.
        public static MoveDir FromDegrees(int degrees) => FromQuarter(degrees / 90);

        public static int ToQuarter(this MoveDir d)
        {
            switch (d)
            {
                case MoveDir.Right: return 1;
                case MoveDir.Down: return 2;
                case MoveDir.Left: return 3;
                default: return 0;
            }
        }

        public static MoveDir Opposite(this MoveDir d)
        {
            switch (d)
            {
                case MoveDir.Up: return MoveDir.Down;
                case MoveDir.Down: return MoveDir.Up;
                case MoveDir.Left: return MoveDir.Right;
                case MoveDir.Right: return MoveDir.Left;
                default: return MoveDir.None;
            }
        }
    }
}
