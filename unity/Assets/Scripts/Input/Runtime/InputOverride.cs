using UnityEngine;

namespace Xnu.Input
{
    // Ersatz-Eingabe für Skriptläufe und Tests (Datei "-xnuInputScript"): wirkt zusätzlich zu den echten Geräten.
    // Der Treiber setzt die Werte je Logikschritt; Pressed gilt für genau einen Schritt (ClearPressed).
    public sealed class InputOverride
    {
        public Vector2 Move;
        // Solange wahr, ersetzt Move den Stick (auch bei null); der Treiber setzt es, solange ein Skript läuft.
        public bool Enabled;
        readonly bool[] _held = new bool[GameButtons.Count];
        readonly bool[] _pressed = new bool[GameButtons.Count];

        public void Hold(GameButton b, bool held) => _held[(int)b] = held;
        public void Press(GameButton b) { _pressed[(int)b] = true; _held[(int)b] = true; }
        public bool IsHeld(GameButton b) => _held[(int)b];
        public bool WasPressed(GameButton b) => _pressed[(int)b];

        public void ClearPressed()
        {
            System.Array.Clear(_pressed, 0, _pressed.Length);
        }

        public void Reset()
        {
            Move = Vector2.zero;
            System.Array.Clear(_held, 0, _held.Length);
            System.Array.Clear(_pressed, 0, _pressed.Length);
        }
    }
}
