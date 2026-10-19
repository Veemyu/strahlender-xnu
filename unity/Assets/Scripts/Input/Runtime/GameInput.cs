using System;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Xnu.Input
{
    // Einstiegspunkt für Eingaben im Spiel. Kapselt das Input System hinter Switch-artigen Aktionen
    // (Move, Look, A/B/X/Y, L/R/ZL/ZR, Plus/Minus, Stick-Klicks, D-Pad). Spielcode liest nur hier.
    // Läuft früh in der Frame-Reihenfolge, damit alle Update()-Methoden denselben Stand sehen.
    [DefaultExecutionOrder(-100)]
    [DisallowMultipleComponent]
    public sealed class GameInput : MonoBehaviour
    {
        public static GameInput Instance { get; private set; }

        [SerializeField] private FaceLayout faceLayout = FaceLayout.NintendoPositional;
        [SerializeField, Range(0f, 0.5f)] private float innerDeadzone = StickMath.DefaultInnerDeadzone;
        [SerializeField, Range(0.5f, 1f)] private float outerDeadzone = StickMath.DefaultOuterDeadzone;

        private InputActionAsset _asset;
        private InputAction _move, _look;
        private readonly InputAction[] _buttons = new InputAction[GameButtons.Count];
        private readonly Direction8Quantizer _quantizer = new Direction8Quantizer();

        public event Action<FaceLayout> FaceLayoutChanged;

        public Vector2 Move { get; private set; }
        public Vector2 Look { get; private set; }

        // Linker Stick/D-Pad/WASD/Touch-Stick auf 8 Richtungen quantisiert (Gitterbewegung).
        public Direction8 MoveDirection { get; private set; }

        public InputActionAsset Asset => _asset;

        public FaceLayout FaceLayout
        {
            get => faceLayout;
            set
            {
                if (faceLayout == value && _asset != null) return;
                faceLayout = value;
                if (isActiveAndEnabled) Rebuild();
                FaceLayoutChanged?.Invoke(faceLayout);
            }
        }

        // Wahr, wenn ein echtes (vom System gemeldetes) Gamepad verbunden ist; virtuelle Geräte zählen nicht.
        public static int ConnectedGamepadCount()
        {
            var n = 0;
            var all = Gamepad.all;
            for (var i = 0; i < all.Count; i++)
                if (all[i].native) n++;
            return n;
        }

        public bool GamepadConnected => ConnectedGamepadCount() > 0;

        public bool IsPressed(GameButton b) => (Override != null && Override.IsHeld(b)) || (_buttons[(int)b] != null && _buttons[(int)b].IsPressed());
        public bool WasPressedThisFrame(GameButton b) => (Override != null && Override.WasPressed(b)) || (_buttons[(int)b] != null && _buttons[(int)b].WasPressedThisFrame());
        public bool WasReleasedThisFrame(GameButton b) => _buttons[(int)b] != null && _buttons[(int)b].WasReleasedThisFrame();

        // Skript-/Testeingabe (null = nur echte Geräte). Bewegung: Override.Move ersetzt den Stick, solange es nicht null ist.
        public InputOverride Override { get; set; }

        // Skripteingabe sofort in Move übernehmen (der Treiber tickt die Logik außerhalb von Update).
        public void ApplyOverrideNow()
        {
            if (Override != null && Override.Enabled) Move = Override.Move;
        }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(this);
                return;
            }
            Instance = this;
            XnuTouchPad.Register();
        }

        private void OnEnable()
        {
            if (Instance != this) return;
            Rebuild();
        }

        private void OnDisable()
        {
            if (Instance != this) return;
            Teardown();
            Move = Look = Vector2.zero;
            MoveDirection = Direction8.None;
            _quantizer.Reset();
        }

        private void OnDestroy()
        {
            if (Instance == this) Instance = null;
        }

        private void Update()
        {
            if (_asset == null) return;

            var m = Process(_move);
            var l = Process(_look);
            if (Override != null && Override.Enabled) m = new Stick2(Override.Move.x, Override.Move.y);
            Move = new Vector2(m.X, m.Y);
            Look = new Vector2(l.X, l.Y);
            MoveDirection = _quantizer.Update(m.X, m.Y);
        }

        private Stick2 Process(InputAction a)
        {
            var raw = a.ReadValue<Vector2>();
            var clamped = StickMath.ClampUnit(raw.x, raw.y);
            return StickMath.CircularDeadzone(clamped, innerDeadzone, outerDeadzone);
        }

        private void Rebuild()
        {
            Teardown();
            _asset = GameInputAssetFactory.Create(faceLayout);
            var map = _asset.FindActionMap(GameInputAssetFactory.MapName, true);
            _move = map.FindAction(GameInputAssetFactory.ActionMove, true);
            _look = map.FindAction(GameInputAssetFactory.ActionLook, true);
            for (var i = 0; i < GameButtons.Count; i++)
                _buttons[i] = map.FindAction(GameInputAssetFactory.ActionName((GameButton)i), true);
            _asset.Enable();
        }

        private void Teardown()
        {
            if (_asset == null) return;
            _asset.Disable();
            if (Application.isPlaying) Destroy(_asset);
            else DestroyImmediate(_asset);
            _asset = null;
            _move = _look = null;
            Array.Clear(_buttons, 0, _buttons.Length);
        }
    }
}
