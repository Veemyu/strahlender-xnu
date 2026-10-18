using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.OnScreen;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace Xnu.Input
{
    // Hebt eine gedrückte Touch-Fläche optisch an.
    internal sealed class TouchPressVisual : MonoBehaviour, IPointerDownHandler, IPointerUpHandler
    {
        public Image Target;
        public Color Idle, Pressed;

        public void OnPointerDown(PointerEventData e) { if (Target != null) Target.color = Pressed; }
        public void OnPointerUp(PointerEventData e) { if (Target != null) Target.color = Idle; }
        private void OnDisable() { if (Target != null) Target.color = Idle; }
    }

    // Touch-Bedienung per uGUI, vollständig im Code aufgebaut. Schreibt über OnScreenStick/OnScreenButton
    // in das virtuelle Gerät XnuTouchPad; GameInput liest es wie jedes andere Gerät.
    // Sichtbar, wenn ein Touchscreen da ist und kein Gamepad verbunden ist (siehe TouchOverlayStateMachine).
    [DisallowMultipleComponent]
    public sealed class TouchOverlay : MonoBehaviour
    {
        public TouchOverlayMode Mode = TouchOverlayMode.Auto;

        [Tooltip("Gesamtdeckkraft des Overlays.")]
        [Range(0.2f, 1f)] public float Opacity = 1f;

        [Tooltip("Behandelt das Gerät in Auto auch ohne Touchscreen als berührungsfähig (Editor/Mac-Tests).")]
        public bool AssumeTouchscreen;

        [Tooltip("Verzögerung beim Einblenden nach dem Trennen des letzten Gamepads.")]
        public float ShowDelaySeconds = 0.75f;

        public int SortingOrder = 1000;

        public bool IsVisible => _machine != null && _machine.Visible;
        public RectTransform SafeAreaRoot => _safe;

        private static readonly Color Fill = new Color(0.08f, 0.09f, 0.12f, 0.45f);
        private static readonly Color FillPressed = new Color(0.92f, 0.93f, 0.97f, 0.70f);
        private static readonly Color Ring = new Color(0.08f, 0.09f, 0.12f, 0.25f);
        private static readonly Color Label = new Color(1f, 1f, 1f, 0.9f);

        private TouchOverlayStateMachine _machine;
        private GameObject _canvasGo;
        private RectTransform _safe;
        private RectTransform _knob;
        private Vector2 _knobStart;
        private Rect _lastSafe;
        private Vector2Int _lastScreen;
        private Font _font;

        private void Awake()
        {
            XnuTouchPad.Register();
            EnsureEventSystem();
            Build();

            _machine = new TouchOverlayStateMachine(ShowDelaySeconds);
            _machine.VisibilityChanged += OnVisibilityChanged;
            _machine.Initialize(Mode, TouchAvailable(), GameInput.ConnectedGamepadCount());
            _canvasGo.SetActive(_machine.Visible);
            ApplySafeArea(true);
        }

        private void OnDestroy()
        {
            if (_machine != null) _machine.VisibilityChanged -= OnVisibilityChanged;
            if (_canvasGo != null) Destroy(_canvasGo);
        }

        private void Update()
        {
            if (_machine.Mode != Mode) _machine.Mode = Mode;
            _machine.TouchAvailable = TouchAvailable();
            _machine.GamepadCount = GameInput.ConnectedGamepadCount();
            _machine.Tick(Time.unscaledDeltaTime);

            if (_canvasGo.activeSelf)
            {
                ApplySafeArea(false);
                _canvasGo.GetComponent<CanvasGroup>().alpha = Opacity;
            }
        }

        private bool TouchAvailable() => AssumeTouchscreen || Application.isMobilePlatform || Touchscreen.current != null;

        private void OnVisibilityChanged(bool visible)
        {
            if (_canvasGo == null) return;
            if (!visible && _knob != null) _knob.anchoredPosition = _knobStart;
            _canvasGo.SetActive(visible);
            if (visible) ApplySafeArea(true);
        }

        private void ApplySafeArea(bool force)
        {
            var sa = Screen.safeArea;
            var screen = new Vector2Int(Screen.width, Screen.height);
            if (!force && sa == _lastSafe && screen == _lastScreen) return;
            _lastSafe = sa;
            _lastScreen = screen;
            if (screen.x <= 0 || screen.y <= 0) return;

            _safe.anchorMin = new Vector2(sa.xMin / screen.x, sa.yMin / screen.y);
            _safe.anchorMax = new Vector2(sa.xMax / screen.x, sa.yMax / screen.y);
            _safe.offsetMin = _safe.offsetMax = Vector2.zero;
        }

        private static void EnsureEventSystem()
        {
            if (EventSystem.current != null || FindAnyObjectByType<EventSystem>() != null) return;
            new GameObject("EventSystem", typeof(EventSystem), typeof(InputSystemUIInputModule));
        }

        // ---- Aufbau ----

        private void Build()
        {
            _font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

            _canvasGo = new GameObject("TouchOverlayCanvas", typeof(RectTransform));
            _canvasGo.SetActive(false); // erst nach dem Aufbau aktivieren: OnScreen-Controls brauchen ihren Pfad vor OnEnable
            _canvasGo.transform.SetParent(transform, false);

            var canvas = _canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = SortingOrder;
            var scaler = _canvasGo.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920, 1080);
            scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            scaler.matchWidthOrHeight = 1f; // feste Höhe von 1080 Einheiten, die Breite folgt dem Bildschirm (4:3 und 16:9)
            _canvasGo.AddComponent<GraphicRaycaster>();
            _canvasGo.AddComponent<CanvasGroup>();

            var safeGo = Ui("SafeArea", _canvasGo.transform);
            _safe = (RectTransform)safeGo.transform;
            _safe.anchorMin = Vector2.zero;
            _safe.anchorMax = Vector2.one;
            _safe.offsetMin = _safe.offsetMax = Vector2.zero;

            BuildStick(new Vector2(0f, 0f), new Vector2(290f, 290f));
            BuildDpad(new Vector2(0f, 0f), new Vector2(290f, 660f));
            BuildFaceButtons(new Vector2(1f, 0f), new Vector2(-290f, 310f));
            BuildShoulders();
            BuildPlusMinus();
        }

        private void BuildStick(Vector2 anchor, Vector2 pos)
        {
            const float baseSize = 340f;
            var ring = Ui("StickBase", _safe);
            Place(ring, anchor, pos, new Vector2(baseSize, baseSize));
            var ringImg = ring.AddComponent<Image>();
            ringImg.sprite = TouchSprites.Circle;
            ringImg.color = Ring;
            ringImg.raycastTarget = false;

            var knob = Ui("StickKnob", _safe);
            var knobRt = Place(knob, anchor, pos, new Vector2(150f, 150f));
            var knobImg = knob.AddComponent<Image>();
            knobImg.sprite = TouchSprites.Circle;
            knobImg.color = Fill;
            knobImg.raycastTarget = false;

            // Große, unsichtbare Trefferfläche über dem ganzen Ring; Ereignisse laufen zum OnScreenStick am Knauf.
            var hit = Ui("HitArea", knob.transform);
            Place(hit, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(baseSize, baseSize));
            var hitImg = hit.AddComponent<Image>();
            hitImg.color = new Color(1f, 1f, 1f, 0f);

            var stick = knob.AddComponent<OnScreenStick>();
            stick.behaviour = OnScreenStick.Behaviour.RelativePositionWithStaticOrigin;
            stick.movementRange = 110f;
            stick.controlPath = XnuTouchPad.StickPath;

            var vis = knob.AddComponent<TouchPressVisual>();
            vis.Target = knobImg; vis.Idle = Fill; vis.Pressed = FillPressed;

            _knob = knobRt;
            _knobStart = knobRt.anchoredPosition;
        }

        private void BuildDpad(Vector2 anchor, Vector2 center)
        {
            const float size = 120f;
            AddRectButton("DpadUp", GameButton.DpadUp, anchor, center + new Vector2(0f, size), new Vector2(size, size), null, Triangle(0f));
            AddRectButton("DpadDown", GameButton.DpadDown, anchor, center + new Vector2(0f, -size), new Vector2(size, size), null, Triangle(180f));
            AddRectButton("DpadLeft", GameButton.DpadLeft, anchor, center + new Vector2(-size, 0f), new Vector2(size, size), null, Triangle(90f));
            AddRectButton("DpadRight", GameButton.DpadRight, anchor, center + new Vector2(size, 0f), new Vector2(size, size), null, Triangle(-90f));
            // Mitte nur als Optik, damit das Kreuz zusammenhängend wirkt.
            var mid = Ui("DpadCentre", _safe);
            Place(mid, anchor, center, new Vector2(size, size));
            var img = mid.AddComponent<Image>();
            img.sprite = TouchSprites.RoundRect;
            img.type = Image.Type.Sliced;
            img.color = Ring;
            img.raycastTarget = false;
        }

        private void BuildFaceButtons(Vector2 anchor, Vector2 center)
        {
            const float d = 130f, size = 150f;
            AddCircleButton("ButtonA", GameButton.A, "A", anchor, center + new Vector2(d, 0f), size);
            AddCircleButton("ButtonB", GameButton.B, "B", anchor, center + new Vector2(0f, -d), size);
            AddCircleButton("ButtonX", GameButton.X, "X", anchor, center + new Vector2(0f, d), size);
            AddCircleButton("ButtonY", GameButton.Y, "Y", anchor, center + new Vector2(-d, 0f), size);
        }

        private void BuildShoulders()
        {
            var size = new Vector2(220f, 110f);
            var tl = new Vector2(0f, 1f);
            var tr = new Vector2(1f, 1f);
            AddRectButton("ButtonZL", GameButton.ZL, tl, new Vector2(150f, -90f), size, "ZL", null);
            AddRectButton("ButtonL", GameButton.L, tl, new Vector2(385f, -90f), size, "L", null);
            AddRectButton("ButtonR", GameButton.R, tr, new Vector2(-385f, -90f), size, "R", null);
            AddRectButton("ButtonZR", GameButton.ZR, tr, new Vector2(-150f, -90f), size, "ZR", null);
        }

        private void BuildPlusMinus()
        {
            var size = new Vector2(140f, 100f);
            var top = new Vector2(0.5f, 1f);
            AddRectButton("ButtonMinus", GameButton.Minus, top, new Vector2(-120f, -85f), size, "-", null);
            AddRectButton("ButtonPlus", GameButton.Plus, top, new Vector2(120f, -85f), size, "+", null);
        }

        private void AddCircleButton(string name, GameButton button, string text, Vector2 anchor, Vector2 pos, float size)
        {
            var go = Ui(name, _safe);
            Place(go, anchor, pos, new Vector2(size, size));
            var img = go.AddComponent<Image>();
            img.sprite = TouchSprites.Circle;
            img.color = Fill;
            AddLabel(go.transform, text, 64);
            FinishButton(go, img, button);
        }

        private void AddRectButton(string name, GameButton button, Vector2 anchor, Vector2 pos, Vector2 size, string text, System.Action<Transform> decorate)
        {
            var go = Ui(name, _safe);
            Place(go, anchor, pos, size);
            var img = go.AddComponent<Image>();
            img.sprite = TouchSprites.RoundRect;
            img.type = Image.Type.Sliced;
            img.color = Fill;
            if (!string.IsNullOrEmpty(text)) AddLabel(go.transform, text, 52);
            decorate?.Invoke(go.transform);
            FinishButton(go, img, button);
        }

        private static System.Action<Transform> Triangle(float rotationZ)
        {
            return parent =>
            {
                var t = Ui("Arrow", parent);
                var rt = Place(t, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(56f, 56f));
                rt.localRotation = Quaternion.Euler(0f, 0f, rotationZ);
                var img = t.AddComponent<Image>();
                img.sprite = TouchSprites.Triangle;
                img.color = Label;
                img.raycastTarget = false;
            };
        }

        private static void FinishButton(GameObject go, Image img, GameButton button)
        {
            var osb = go.AddComponent<OnScreenButton>();
            osb.controlPath = XnuTouchPad.ButtonPath(button);
            var vis = go.AddComponent<TouchPressVisual>();
            vis.Target = img; vis.Idle = Fill; vis.Pressed = FillPressed;
        }

        private void AddLabel(Transform parent, string text, int fontSize)
        {
            if (string.IsNullOrEmpty(text)) return;
            var go = Ui("Label", parent);
            var rt = (RectTransform)go.transform;
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
            var t = go.AddComponent<Text>();
            t.font = _font;
            t.text = text;
            t.fontSize = fontSize;
            t.fontStyle = FontStyle.Bold;
            t.alignment = TextAnchor.MiddleCenter;
            t.color = Label;
            t.raycastTarget = false;
        }

        private static GameObject Ui(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return go;
        }

        private static RectTransform Place(GameObject go, Vector2 anchor, Vector2 pos, Vector2 size)
        {
            var rt = (RectTransform)go.transform;
            rt.anchorMin = rt.anchorMax = anchor;
            rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = pos;
            rt.sizeDelta = size;
            return rt;
        }
    }
}
