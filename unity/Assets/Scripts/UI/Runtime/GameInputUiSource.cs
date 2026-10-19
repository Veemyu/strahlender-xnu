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
            var moveX = 0;
            if (gi.WasPressedThisFrame(GameButton.DpadUp)) move = -1;
            else if (gi.WasPressedThisFrame(GameButton.DpadDown)) move = 1;
            if (gi.WasPressedThisFrame(GameButton.DpadLeft)) moveX = -1;
            else if (gi.WasPressedThisFrame(GameButton.DpadRight)) moveX = 1;
            var dir = gi.MoveDirection;
            if (dir != _lastDirection)
            {
                if (move == 0 && dir == Direction8.North) move = -1;
                else if (move == 0 && dir == Direction8.South) move = 1;
                if (moveX == 0 && dir == Direction8.West) moveX = -1;
                else if (moveX == 0 && dir == Direction8.East) moveX = 1;
            }
            _lastDirection = dir;

            return new UiInputState(
                gi.WasPressedThisFrame(GameButton.A), gi.WasPressedThisFrame(GameButton.B),
                gi.IsPressed(GameButton.A), gi.IsPressed(GameButton.B), move, moveX, gi.WasPressedThisFrame(GameButton.Plus));
        }
    }
}
