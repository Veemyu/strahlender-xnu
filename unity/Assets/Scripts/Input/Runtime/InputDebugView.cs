using System.Text;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Xnu.Input
{
    // Kleine Diagnoseanzeige für Hardwaretests: zeigt Geräte, Achsen und gedrückte Tasten.
    // F2 (Tastatur) wechselt die Gesichtstasten-Belegung, F3 den Touch-Overlay-Modus.
    [DisallowMultipleComponent]
    public sealed class InputDebugView : MonoBehaviour
    {
        public GameInput Input;
        public TouchOverlay Overlay;

        private readonly StringBuilder _sb = new StringBuilder(512);
        private GUIStyle _style;

        private void Update()
        {
            var kb = Keyboard.current;
            if (kb == null) return;
            if (Input != null && kb.f2Key.wasPressedThisFrame)
                Input.FaceLayout = Input.FaceLayout == FaceLayout.NintendoPositional ? FaceLayout.SouthConfirm : FaceLayout.NintendoPositional;
            if (Overlay != null && kb.f3Key.wasPressedThisFrame)
                Overlay.Mode = (TouchOverlayMode)(((int)Overlay.Mode + 1) % 3);
        }

        private void OnGUI()
        {
            if (Input == null) Input = GameInput.Instance;
            if (Input == null) return;

            if (_style == null)
                _style = new GUIStyle(GUI.skin.label) { fontSize = 26, normal = { textColor = Color.white }, richText = false };

            var s = Screen.height / 1080f;
            GUI.matrix = Matrix4x4.Scale(new Vector3(s, s, 1f));

            _sb.Clear();
            _sb.Append("Layout: ").Append(Input.FaceLayout).Append("  (F2)\n");
            _sb.Append("Gamepads: ").Append(GameInput.ConnectedGamepadCount());
            if (Overlay != null) _sb.Append("   Overlay: ").Append(Overlay.Mode).Append(Overlay.IsVisible ? " sichtbar" : " aus").Append("  (F3)");
            _sb.Append('\n');
            var all = Gamepad.all;
            for (var i = 0; i < all.Count; i++)
                if (all[i].native) _sb.Append("  ").Append(all[i].displayName).Append(" [").Append(all[i].layout).Append("]\n");
            _sb.Append("Move ").Append(Input.Move.ToString("0.00")).Append("  Dir ").Append(Input.MoveDirection).Append('\n');
            _sb.Append("Look ").Append(Input.Look.ToString("0.00")).Append('\n');
            _sb.Append("Tasten:");
            for (var b = GameButton.A; b <= GameButton.DpadRight; b++)
                if (Input.IsPressed(b)) _sb.Append(' ').Append(b);

            GUI.Label(new Rect(520f, 170f, 900f, 420f), _sb.ToString(), _style);
        }
    }
}
