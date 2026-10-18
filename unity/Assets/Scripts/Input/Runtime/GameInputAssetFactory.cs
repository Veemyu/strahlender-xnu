using System;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Xnu.Input
{
    // Baut das InputActionAsset vollständig im Code (diffbar, kein binäres Editor-Asset).
    // Die Gesichtstasten des Gamepads hängen vom FaceLayout ab; Tastatur und Touch sind fest belegt.
    public static class GameInputAssetFactory
    {
        public const string MapName = "Game";
        public const string ActionMove = "Move";
        public const string ActionLook = "Look";

        public const string SchemeGamepad = "Gamepad";
        public const string SchemeKeyboardMouse = "KeyboardMouse";
        public const string SchemeTouch = "Touch";

        public static string ActionName(GameButton b) => b.ToString();

        public static InputActionAsset Create(FaceLayout layout)
        {
            var asset = ScriptableObject.CreateInstance<InputActionAsset>();
            asset.name = "XnuGameInput";

            asset.AddControlScheme(SchemeGamepad).WithRequiredDevice("<Gamepad>");
            asset.AddControlScheme(SchemeKeyboardMouse).WithRequiredDevice("<Keyboard>").WithOptionalDevice("<Mouse>");
            asset.AddControlScheme(SchemeTouch).WithRequiredDevice("<XnuTouchPad>");

            var map = asset.AddActionMap(MapName);

            var move = map.AddAction(ActionMove, InputActionType.Value, expectedControlLayout: "Vector2");
            move.AddBinding("<Gamepad>/leftStick", groups: SchemeGamepad);
            move.AddBinding("<Gamepad>/dpad", groups: SchemeGamepad);
            AddWasd(move, "<Keyboard>/w", "<Keyboard>/s", "<Keyboard>/a", "<Keyboard>/d");
            AddWasd(move, "<Keyboard>/upArrow", "<Keyboard>/downArrow", "<Keyboard>/leftArrow", "<Keyboard>/rightArrow");
            move.AddBinding(XnuTouchPad.StickPath, groups: SchemeTouch);

            var look = map.AddAction(ActionLook, InputActionType.Value, expectedControlLayout: "Vector2");
            look.AddBinding("<Gamepad>/rightStick", groups: SchemeGamepad);
            AddWasd(look, "<Keyboard>/t", "<Keyboard>/g", "<Keyboard>/f", "<Keyboard>/h");
            // Maus: Delta nur bei gedrückter rechter Taste, grob auf Stick-Größe skaliert.
            look.AddCompositeBinding("OneModifier")
                .With("Modifier", "<Mouse>/rightButton", SchemeKeyboardMouse)
                .With("Binding", "<Mouse>/delta", SchemeKeyboardMouse, "scaleVector2(x=0.05,y=0.05)");

            for (var b = GameButton.A; b <= GameButton.DpadRight; b++)
            {
                var action = map.AddAction(ActionName(b), InputActionType.Button);
                AddGamepad(action, b, layout);
                AddKeyboard(action, b);
                var touch = XnuTouchPad.ButtonPath(b);
                if (touch != null) action.AddBinding(touch, groups: SchemeTouch);
            }

            return asset;
        }

        private static void AddWasd(InputAction action, string up, string down, string left, string right)
        {
            action.AddCompositeBinding("2DVector(mode=0)")
                .With("Up", up, SchemeKeyboardMouse)
                .With("Down", down, SchemeKeyboardMouse)
                .With("Left", left, SchemeKeyboardMouse)
                .With("Right", right, SchemeKeyboardMouse);
        }

        private static void AddGamepad(InputAction action, GameButton b, FaceLayout layout)
        {
            string path;
            switch (b)
            {
                case GameButton.A:
                case GameButton.B:
                case GameButton.X:
                case GameButton.Y: path = FaceLayoutMap.GamepadPath(layout, b); break;
                case GameButton.L: path = "<Gamepad>/leftShoulder"; break;
                case GameButton.R: path = "<Gamepad>/rightShoulder"; break;
                case GameButton.ZL: path = "<Gamepad>/leftTrigger"; break;
                case GameButton.ZR: path = "<Gamepad>/rightTrigger"; break;
                case GameButton.Plus: path = "<Gamepad>/start"; break;
                case GameButton.Minus: path = "<Gamepad>/select"; break;
                case GameButton.StickL: path = "<Gamepad>/leftStickPress"; break;
                case GameButton.StickR: path = "<Gamepad>/rightStickPress"; break;
                case GameButton.DpadUp: path = "<Gamepad>/dpad/up"; break;
                case GameButton.DpadDown: path = "<Gamepad>/dpad/down"; break;
                case GameButton.DpadLeft: path = "<Gamepad>/dpad/left"; break;
                case GameButton.DpadRight: path = "<Gamepad>/dpad/right"; break;
                default: throw new ArgumentOutOfRangeException(nameof(b));
            }
            action.AddBinding(path, groups: SchemeGamepad);
        }

        // Tastatur (Mac): rechte Hand als Diamant (I/J/K/L = X/Y/B/A), Schultertasten links.
        private static void AddKeyboard(InputAction action, GameButton b)
        {
            switch (b)
            {
                case GameButton.A: Keys(action, "<Keyboard>/l", "<Keyboard>/enter", "<Keyboard>/space"); break;
                case GameButton.B: Keys(action, "<Keyboard>/k", "<Keyboard>/backspace"); break;
                case GameButton.X: Keys(action, "<Keyboard>/i"); break;
                case GameButton.Y: Keys(action, "<Keyboard>/j"); break;
                case GameButton.L: Keys(action, "<Keyboard>/q"); break;
                case GameButton.R: Keys(action, "<Keyboard>/e"); break;
                case GameButton.ZL: Keys(action, "<Keyboard>/1"); break;
                case GameButton.ZR: Keys(action, "<Keyboard>/3"); break;
                case GameButton.Plus: Keys(action, "<Keyboard>/tab"); break;
                case GameButton.Minus: Keys(action, "<Keyboard>/m"); break;
                case GameButton.StickL: Keys(action, "<Keyboard>/v"); break;
                case GameButton.StickR: Keys(action, "<Keyboard>/b"); break;
                case GameButton.DpadUp: Keys(action, "<Keyboard>/upArrow"); break;
                case GameButton.DpadDown: Keys(action, "<Keyboard>/downArrow"); break;
                case GameButton.DpadLeft: Keys(action, "<Keyboard>/leftArrow"); break;
                case GameButton.DpadRight: Keys(action, "<Keyboard>/rightArrow"); break;
            }
        }

        private static void Keys(InputAction action, params string[] paths)
        {
            foreach (var p in paths) action.AddBinding(p, groups: SchemeKeyboardMouse);
        }
    }
}
