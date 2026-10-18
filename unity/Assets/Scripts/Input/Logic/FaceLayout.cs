using System;

namespace Xnu.Input
{
    // Belegung der Gesichtstasten. Beide Varianten sind positionell, sie unterscheiden sich nur darin,
    // welche physische Position die Funktion „A“ (Bestätigen) trägt.
    public enum FaceLayout
    {
        // Standard, wie auf der Switch: A = Osten, B = Süden, X = Norden, Y = Westen.
        // Auf Switch-Pro/Joy-Con stimmen damit auch die Aufschriften; auf Xbox ist A = B-Taste (Osten),
        // auf PlayStation A = Kreis.
        NintendoPositional,

        // A = Süden, B = Osten, X = Westen, Y = Norden: Bestätigen auf der Xbox-A-/PlayStation-Kreuz-Taste.
        SouthConfirm,
    }

    // Physische Position einer Gesichtstaste, benannt wie im Input System (Gamepad.buttonSouth usw.).
    public enum FacePosition
    {
        South,
        East,
        West,
        North,
    }

    public static class FaceLayoutMap
    {
        public static FacePosition Position(FaceLayout layout, GameButton button)
        {
            switch (layout)
            {
                case FaceLayout.NintendoPositional:
                    switch (button)
                    {
                        case GameButton.A: return FacePosition.East;
                        case GameButton.B: return FacePosition.South;
                        case GameButton.X: return FacePosition.North;
                        case GameButton.Y: return FacePosition.West;
                    }
                    break;
                case FaceLayout.SouthConfirm:
                    switch (button)
                    {
                        case GameButton.A: return FacePosition.South;
                        case GameButton.B: return FacePosition.East;
                        case GameButton.X: return FacePosition.West;
                        case GameButton.Y: return FacePosition.North;
                    }
                    break;
                default:
                    throw new ArgumentOutOfRangeException(nameof(layout));
            }
            throw new ArgumentException("Keine Gesichtstaste: " + button, nameof(button));
        }

        public static GameButton Button(FaceLayout layout, FacePosition position)
        {
            for (var b = GameButton.A; b <= GameButton.Y; b++)
                if (Position(layout, b) == position) return b;
            throw new ArgumentOutOfRangeException(nameof(position));
        }

        public static string ControlName(FacePosition position)
        {
            switch (position)
            {
                case FacePosition.South: return "buttonSouth";
                case FacePosition.East: return "buttonEast";
                case FacePosition.West: return "buttonWest";
                case FacePosition.North: return "buttonNorth";
                default: throw new ArgumentOutOfRangeException(nameof(position));
            }
        }

        // Input-System-Pfad der Gamepad-Bindung für eine Gesichtstaste.
        public static string GamepadPath(FaceLayout layout, GameButton button)
            => "<Gamepad>/" + ControlName(Position(layout, button));
    }
}
