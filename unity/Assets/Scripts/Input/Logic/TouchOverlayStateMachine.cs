using System;

namespace Xnu.Input
{
    public enum TouchOverlayMode
    {
        // Sichtbar, wenn ein Touchscreen vorhanden ist und kein Gamepad verbunden ist.
        Auto,
        AlwaysVisible,
        AlwaysHidden,
    }

    // Entscheidet, ob das Touch-Overlay sichtbar ist. Ohne Unity-Abhängigkeit; Zeit kommt über Tick(dt).
    // Verbinden eines Gamepads blendet sofort aus. Nach dem Trennen wird erst nach `ShowDelaySeconds`
    // eingeblendet, damit kurze Funkaussetzer (Bluetooth) das Overlay nicht aufblitzen lassen.
    public sealed class TouchOverlayStateMachine
    {
        private TouchOverlayMode _mode;
        private int _gamepads;
        private bool _touchAvailable;
        private float _pendingShow;
        private bool _initialised;

        public float ShowDelaySeconds { get; }
        public bool Visible { get; private set; }

        public event Action<bool> VisibilityChanged;

        public TouchOverlayStateMachine(float showDelaySeconds = 0.75f, TouchOverlayMode mode = TouchOverlayMode.Auto)
        {
            if (showDelaySeconds < 0f) throw new ArgumentOutOfRangeException(nameof(showDelaySeconds));
            ShowDelaySeconds = showDelaySeconds;
            _mode = mode;
        }

        public TouchOverlayMode Mode
        {
            get => _mode;
            set { _mode = value; Evaluate(0f); }
        }

        public int GamepadCount
        {
            get => _gamepads;
            set { _gamepads = Math.Max(0, value); Evaluate(0f); }
        }

        public bool TouchAvailable
        {
            get => _touchAvailable;
            set { _touchAvailable = value; Evaluate(0f); }
        }

        // Setzt den Anfangszustand; die erste Auswertung blendet ohne Verzögerung ein.
        public void Initialize(TouchOverlayMode mode, bool touchAvailable, int gamepadCount)
        {
            _mode = mode;
            _touchAvailable = touchAvailable;
            _gamepads = Math.Max(0, gamepadCount);
            _initialised = false;
            Evaluate(0f);
        }

        public void Tick(float deltaSeconds) => Evaluate(Math.Max(0f, deltaSeconds));

        private bool Wanted()
        {
            switch (_mode)
            {
                case TouchOverlayMode.AlwaysVisible: return true;
                case TouchOverlayMode.AlwaysHidden: return false;
                default: return _touchAvailable && _gamepads == 0;
            }
        }

        private void Evaluate(float dt)
        {
            var wanted = Wanted();

            if (!wanted)
            {
                _pendingShow = 0f;
                SetVisible(false);
                _initialised = true;
                return;
            }

            if (Visible) { _pendingShow = 0f; return; }

            // Erste Auswertung und feste Modi ohne Verzögerung; nur der Auto-Wechsel nach Trennen wartet.
            if (!_initialised || _mode == TouchOverlayMode.AlwaysVisible)
            {
                _initialised = true;
                SetVisible(true);
                return;
            }

            _pendingShow += dt;
            if (_pendingShow >= ShowDelaySeconds)
            {
                _pendingShow = 0f;
                SetVisible(true);
            }
        }

        private void SetVisible(bool v)
        {
            if (Visible == v) return;
            Visible = v;
            VisibilityChanged?.Invoke(v);
        }
    }
}
