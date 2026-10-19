using UnityEngine;
using Xnu.Input;

namespace Xnu.UI
{
    // Übersetzt Xnu.Input (GameInput) in UiInputState: A bestätigt, B bricht ab, D-Pad/Stick rauf/runter bewegt den Cursor.
    public sealed class GameInputUiSource : IUiInputSource
    {
        Direction8 _lastDirection;

        public UiInputState Poll()
        {
            var gi = GameInput.Instance;
            if (gi == null) return UiInputState.None;

            var move = 0;
            if (gi.WasPressedThisFrame(GameButton.DpadUp)) move = -1;
            else if (gi.WasPressedThisFrame(GameButton.DpadDown)) move = 1;
            var dir = gi.MoveDirection;
            if (move == 0 && dir != _lastDirection)
            {
                if (dir == Direction8.North) move = -1;
                else if (dir == Direction8.South) move = 1;
            }
            _lastDirection = dir;

            return new UiInputState(
                gi.WasPressedThisFrame(GameButton.A), gi.WasPressedThisFrame(GameButton.B),
                gi.IsPressed(GameButton.A), gi.IsPressed(GameButton.B), move);
        }
    }
}
