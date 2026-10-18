using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
using UnityEngine.InputSystem.Layouts;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.Utilities;
#if UNITY_EDITOR
using UnityEditor;
#endif

namespace Xnu.Input
{
    // Zustand des virtuellen Touch-Pads: ein Stick und die Tasten als Bitfeld.
    [StructLayout(LayoutKind.Explicit, Size = 12)]
    public struct XnuTouchPadState : IInputStateTypeInfo
    {
        public static FourCC Format => new FourCC('X', 'T', 'P', 'D');

        public FourCC format => Format;

        [FieldOffset(0)]
        [InputControl(layout = "Stick", format = "VEC2", sizeInBits = 64, displayName = "Stick")]
        public Vector2 stick;

        [FieldOffset(8)]
        [InputControl(name = "buttonA", layout = "Button", format = "BIT", bit = 0, displayName = "A")]
        [InputControl(name = "buttonB", layout = "Button", format = "BIT", bit = 1, displayName = "B")]
        [InputControl(name = "buttonX", layout = "Button", format = "BIT", bit = 2, displayName = "X")]
        [InputControl(name = "buttonY", layout = "Button", format = "BIT", bit = 3, displayName = "Y")]
        [InputControl(name = "buttonL", layout = "Button", format = "BIT", bit = 4, displayName = "L")]
        [InputControl(name = "buttonR", layout = "Button", format = "BIT", bit = 5, displayName = "R")]
        [InputControl(name = "buttonZL", layout = "Button", format = "BIT", bit = 6, displayName = "ZL")]
        [InputControl(name = "buttonZR", layout = "Button", format = "BIT", bit = 7, displayName = "ZR")]
        [InputControl(name = "buttonPlus", layout = "Button", format = "BIT", bit = 8, displayName = "+")]
        [InputControl(name = "buttonMinus", layout = "Button", format = "BIT", bit = 9, displayName = "-")]
        [InputControl(name = "dpadUp", layout = "Button", format = "BIT", bit = 10, displayName = "D-Pad Up")]
        [InputControl(name = "dpadDown", layout = "Button", format = "BIT", bit = 11, displayName = "D-Pad Down")]
        [InputControl(name = "dpadLeft", layout = "Button", format = "BIT", bit = 12, displayName = "D-Pad Left")]
        [InputControl(name = "dpadRight", layout = "Button", format = "BIT", bit = 13, displayName = "D-Pad Right")]
        public uint buttons;
    }

    // Eigener Gerätetyp für das Touch-Overlay. Bewusst KEIN Gamepad: OnScreenStick/OnScreenButton legen für
    // ihren Controlpfad ein virtuelles Gerät an; mit „<Gamepad>“ würde dieses in Gamepad.all auftauchen und
    // die Erkennung „Controller verbunden“ (und damit das Ausblenden des Overlays) verfälschen.
    [InputControlLayout(stateType = typeof(XnuTouchPadState), displayName = "Xnu Touch Pad")]
#if UNITY_EDITOR
    [InitializeOnLoad]
#endif
    public sealed class XnuTouchPad : InputDevice
    {
        public Vector2Control stick { get; private set; }
        public ButtonControl buttonA { get; private set; }

        static XnuTouchPad()
        {
            Register();
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void InitializeAtRuntime() => Register();

        public static void Register() => InputSystem.RegisterLayout<XnuTouchPad>();

        protected override void FinishSetup()
        {
            base.FinishSetup();
            stick = GetChildControl<Vector2Control>("stick");
            buttonA = GetChildControl<ButtonControl>("buttonA");
        }

        // Control-Pfade der Touch-Bindungen, gemeinsam genutzt von Actions und Overlay.
        public static string ButtonPath(GameButton b)
        {
            switch (b)
            {
                case GameButton.A: return "<XnuTouchPad>/buttonA";
                case GameButton.B: return "<XnuTouchPad>/buttonB";
                case GameButton.X: return "<XnuTouchPad>/buttonX";
                case GameButton.Y: return "<XnuTouchPad>/buttonY";
                case GameButton.L: return "<XnuTouchPad>/buttonL";
                case GameButton.R: return "<XnuTouchPad>/buttonR";
                case GameButton.ZL: return "<XnuTouchPad>/buttonZL";
                case GameButton.ZR: return "<XnuTouchPad>/buttonZR";
                case GameButton.Plus: return "<XnuTouchPad>/buttonPlus";
                case GameButton.Minus: return "<XnuTouchPad>/buttonMinus";
                case GameButton.DpadUp: return "<XnuTouchPad>/dpadUp";
                case GameButton.DpadDown: return "<XnuTouchPad>/dpadDown";
                case GameButton.DpadLeft: return "<XnuTouchPad>/dpadLeft";
                case GameButton.DpadRight: return "<XnuTouchPad>/dpadRight";
                default: return null; // Stick-Klicks gibt es auf dem Touch-Pad nicht.
            }
        }

        public const string StickPath = "<XnuTouchPad>/stick";
    }
}
