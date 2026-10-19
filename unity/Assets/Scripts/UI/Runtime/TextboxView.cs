using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Xnu.Text;

namespace Xnu.UI
{
    // Meldungsfenster: baut seine uGUI-Objekte selbst (Canvas 1280x720, Breitenabgleich), zeigt eine ComposedMessage mit
    // Schreibmaschine (0,06/0,03/0,01 s je Zeichen), Rich-Text, Weiter-Symbol und Ja/Nein-Auswahl. Der Ablauf liegt in TextboxFlow.
    [DisallowMultipleComponent]
    public sealed class TextboxView : MonoBehaviour
    {
        // Maße in Referenzpixeln [A] (die Originalmaße stecken in nicht gelesenen Daten; Rahmenhöhe 144 aus den Sprites).
        public const float WindowMarginX = 40f;
        public const float WindowBottom = 24f;
        public const float TextInsetX = 100f;
        public const float TextInsetTop = 26f;
        public const float TextInsetBottom = 22f;
        public const float FontSize = 36f;
        // Weiter-Symbol: Hub 8 px, 210 Grad je Sekunde (iconMoveDist, addAngleSec).
        const float IconMoveDist = 8f;
        const float IconAngleSec = 210f;
        public const int SortingOrder = UiCanvasFactory.SortingWindow + 50;

        [SerializeField] Camera targetCamera;
        [SerializeField] MessageSpeed speed = MessageSpeed.Normal;
        [SerializeField, Range(1, 24)] int frameStyle = 1;
        [SerializeField] bool useOriginalSkin = true;
        [SerializeField] TMP_FontAsset font;

        Canvas _canvas;
        RectTransform _window;
        Image _frame;
        RectTransform _textRect;
        TextMeshProUGUI _text;
        Image _icon;
        RectTransform _iconRect;
        string _lastText;
        ChoiceMenuModel _choice;
        Action<int> _choiceDone;
        GameObject _choicePanel;
        TextMeshProUGUI[] _choiceRows;
        TextMeshProUGUI _choiceCursor;
        Action _pendingQuestion;

        public IUiInputSource InputSource { get; set; }
        public TextboxFlow Flow { get; private set; }
        public TextboxSkin Skin { get; private set; }
        public string SkinNote { get; private set; } = "";
        public bool IsBuilt => _canvas != null;
        public bool IsOpen => Flow != null && !Flow.IsClosed;
        public bool IsChoosing => _choice != null && !_choice.IsDone;
        public Canvas Canvas => _canvas;
        public Camera TargetCamera => targetCamera;
        public RectTransform Window => _window;
        public TextMeshProUGUI Text => _text;
        public MessageSpeed Speed { get => speed; set => speed = value; }
        public event Action Closed;

        void Awake() => EnsureBuilt();

        public void Configure(Camera camera, int style, bool original, MessageSpeed messageSpeed)
        {
            targetCamera = camera;
            frameStyle = Mathf.Clamp(style, 1, 24);
            useOriginalSkin = original;
            speed = messageSpeed;
        }

        public void EnsureBuilt()
        {
            if (_canvas != null) return;
            var note = "";
            Skin = useOriginalSkin ? TextboxSkin.LoadOriginalOrPlaceholder(frameStyle, out note) : TextboxSkin.Placeholder();
            SkinNote = useOriginalSkin ? note : "Platzhalter (abgeschaltet)";

            _canvas = UiCanvasFactory.Create("TextboxCanvas", targetCamera, SortingOrder, transform);

            var winGo = new GameObject("Window", typeof(RectTransform), typeof(Image));
            _window = (RectTransform)winGo.transform;
            _window.SetParent(_canvas.transform, false);
            _window.anchorMin = new Vector2(0f, 0f);
            _window.anchorMax = new Vector2(1f, 0f);
            _window.pivot = new Vector2(0.5f, 0f);
            _window.offsetMin = new Vector2(WindowMarginX, WindowBottom);
            _window.offsetMax = new Vector2(-WindowMarginX, WindowBottom + Skin.FrameHeight);
            _frame = winGo.GetComponent<Image>();
            _frame.sprite = Skin.Frame;
            _frame.type = Image.Type.Sliced;
            _frame.raycastTarget = false;

            var maskGo = new GameObject("TextMask", typeof(RectTransform), typeof(RectMask2D));
            var maskRect = (RectTransform)maskGo.transform;
            maskRect.SetParent(_window, false);
            maskRect.anchorMin = Vector2.zero;
            maskRect.anchorMax = Vector2.one;
            maskRect.offsetMin = new Vector2(TextInsetX, TextInsetBottom);
            maskRect.offsetMax = new Vector2(-TextInsetX, -TextInsetTop);

            var textGo = new GameObject("Text", typeof(RectTransform));
            _textRect = (RectTransform)textGo.transform;
            _textRect.SetParent(maskRect, false);
            _textRect.anchorMin = new Vector2(0f, 1f);
            _textRect.anchorMax = new Vector2(1f, 1f);
            _textRect.pivot = new Vector2(0.5f, 1f);
            _textRect.sizeDelta = new Vector2(0f, 600f);
            _textRect.anchoredPosition = Vector2.zero;
            _text = textGo.AddComponent<TextMeshProUGUI>();
            StyleText(_text, TextAlignmentOptions.TopLeft);

            var iconGo = new GameObject("KeyIcon", typeof(RectTransform), typeof(Image));
            _iconRect = (RectTransform)iconGo.transform;
            _iconRect.SetParent(_window, false);
            _iconRect.anchorMin = _iconRect.anchorMax = new Vector2(1f, 0f);
            _iconRect.pivot = new Vector2(0.5f, 0.5f);
            _iconRect.sizeDelta = new Vector2(34f, 30f);
            _iconRect.anchoredPosition = new Vector2(-TextInsetX + 8f, 34f);
            _icon = iconGo.GetComponent<Image>();
            _icon.sprite = Skin.KeyIcon;
            _icon.raycastTarget = false;
            _icon.preserveAspect = true;

            _window.gameObject.SetActive(false);
        }

        void StyleText(TextMeshProUGUI t, TextAlignmentOptions align)
        {
            if (font != null) t.font = font;
            t.fontSize = FontSize;
            t.color = new Color(0.12f, 0.12f, 0.16f, 1f);
            t.alignment = align;
            t.textWrappingMode = TextWrappingModes.Normal;
            t.overflowMode = TextOverflowModes.Overflow;
            t.richText = true;
            t.raycastTarget = false;
        }

        public TextboxFlow Show(string plainText, Action onClosed = null) => Show(PlainMessage.Parse(plainText), onClosed);

        public TextboxFlow Show(MsbtLabel label, TagWordBuffer buffer = null, Action onClosed = null) =>
            Show(new MessageComposer().Compose(label, buffer), onClosed);

        public TextboxFlow Show(ComposedMessage message, Action onClosed = null, bool holdOpenAtEnd = false)
        {
            EnsureBuilt();
            if (IsOpen) throw new InvalidOperationException("Es läuft schon eine Nachricht");
            var flow = new TextboxFlow(message, speed) { HoldOpenAtEnd = holdOpenAtEnd };
            flow.Open();
            Flow = flow;
            _lastText = null;
            if (onClosed != null) Closed += OnceClosed;
            _window.gameObject.SetActive(true);
            Apply();
            return flow;

            void OnceClosed()
            {
                Closed -= OnceClosed;
                onClosed();
            }
        }

        void Update()
        {
            if (!IsBuilt) return;
            var input = (InputSource ?? (InputSource = new GameInputUiSource())).Poll();
            Tick(Time.deltaTime, input);
        }

        // Frage: Nachricht, danach bleibt das Fenster offen und die Auswahl erscheint; nach der Wahl schließt das Fenster.
        public TextboxFlow Ask(string plainText, string[] options, int cancelIndex, Action<int> onAnswer)
        {
            var flow = Show(PlainMessage.Parse(plainText), null, true);
            _pendingQuestion = () => Choose(options, cancelIndex, answer =>
            {
                if (Flow != null && Flow.State == TextboxState.Held) Flow.Close();
                onAnswer?.Invoke(answer);
            });
            return flow;
        }

        // Ein Schritt von Hand (Update ruft das mit echter Eingabe; Tests und Skripte mit eigenem Zustand).
        public void Tick(float deltaSeconds, UiInputState input)
        {
            if (_choice != null && !_choice.IsDone)
            {
                _choice.Update(input);
                ApplyChoice();
                if (_choice.IsDone) FinishChoice();
                return;
            }
            if (Flow == null) return;
            var wasOpen = !Flow.IsClosed;
            Flow.Update(deltaSeconds, input);
            if (Flow.State == TextboxState.Held && _pendingQuestion != null)
            {
                var start = _pendingQuestion;
                _pendingQuestion = null;
                start();
            }
            Apply();
            if (wasOpen && Flow.IsClosed)
            {
                _window.gameObject.SetActive(false);
                Closed?.Invoke();
            }
        }

        void Apply()
        {
            if (Flow == null || _text == null) return;
            var text = Flow.DisplayText;
            if (!string.Equals(text, _lastText, StringComparison.Ordinal))
            {
                _text.text = text;
                _text.ForceMeshUpdate();
                _lastText = text;
            }

            var lineHeight = _text.textInfo != null && _text.textInfo.lineCount > 0 ? _text.textInfo.lineInfo[0].lineHeight : FontSize * 1.2f;
            _textRect.anchoredPosition = new Vector2(0f, lineHeight * (Flow.ScrolledLines + Flow.ScrollProgress));

            var p = Flow.WindowProgress;
            _window.localScale = new Vector3(1f, Mathf.Max(0.001f, p), 1f);
            _icon.enabled = Flow.KeyIconVisible;
            if (Flow.KeyIconVisible)
                _iconRect.anchoredPosition = new Vector2(-TextInsetX + 8f, 34f + Mathf.Sin(Time.unscaledTime * IconAngleSec * Mathf.Deg2Rad) * IconMoveDist);
        }

        // Auswahl neben dem Fenster (z. B. Ja/Nein). Abbrechen wählt cancelIndex (< 0: Abbrechen wirkungslos).
        public ChoiceMenuModel Choose(string[] options, int cancelIndex, Action<int> onDone)
        {
            EnsureBuilt();
            if (options == null || options.Length == 0) throw new ArgumentException("Keine Einträge", nameof(options));
            _choice = new ChoiceMenuModel(options.Length, cancelIndex);
            _choiceDone = onDone;
            BuildChoicePanel(options);
            ApplyChoice();
            return _choice;
        }

        void BuildChoicePanel(string[] options)
        {
            if (_choicePanel != null) Dispose(_choicePanel);
            const float rowHeight = 56f;
            _choicePanel = new GameObject("ChoicePanel", typeof(RectTransform), typeof(Image));
            var rect = (RectTransform)_choicePanel.transform;
            rect.SetParent(_canvas.transform, false);
            rect.anchorMin = rect.anchorMax = new Vector2(1f, 0f);
            rect.pivot = new Vector2(1f, 0f);
            var h = options.Length * rowHeight + 40f;
            rect.sizeDelta = new Vector2(300f, h);
            rect.anchoredPosition = new Vector2(-WindowMarginX, WindowBottom + Skin.FrameHeight + 10f);
            var img = _choicePanel.GetComponent<Image>();
            img.sprite = TextboxSkin.Placeholder().Frame;
            img.type = Image.Type.Sliced;
            img.raycastTarget = false;

            _choiceRows = new TextMeshProUGUI[options.Length];
            for (var i = 0; i < options.Length; i++)
            {
                var row = new GameObject("Row" + i, typeof(RectTransform));
                var rr = (RectTransform)row.transform;
                rr.SetParent(rect, false);
                rr.anchorMin = new Vector2(0f, 1f);
                rr.anchorMax = new Vector2(1f, 1f);
                rr.pivot = new Vector2(0.5f, 1f);
                rr.sizeDelta = new Vector2(-90f, rowHeight);
                rr.anchoredPosition = new Vector2(20f, -20f - i * rowHeight);
                var t = row.AddComponent<TextMeshProUGUI>();
                StyleText(t, TextAlignmentOptions.MidlineLeft);
                t.text = options[i];
                _choiceRows[i] = t;
            }

            var cur = new GameObject("Cursor", typeof(RectTransform));
            var cr = (RectTransform)cur.transform;
            cr.SetParent(rect, false);
            cr.anchorMin = new Vector2(0f, 1f);
            cr.anchorMax = new Vector2(0f, 1f);
            cr.pivot = new Vector2(0.5f, 1f);
            cr.sizeDelta = new Vector2(40f, rowHeight);
            _choiceCursor = cur.AddComponent<TextMeshProUGUI>();
            StyleText(_choiceCursor, TextAlignmentOptions.Midline);
            _choiceCursor.text = ">";
        }

        void ApplyChoice()
        {
            if (_choice == null || _choiceCursor == null) return;
            var rr = (RectTransform)_choiceCursor.transform;
            rr.anchoredPosition = new Vector2(34f, -20f - _choice.Cursor * 56f);
        }

        void FinishChoice()
        {
            var result = _choice.Result;
            var done = _choiceDone;
            _choiceDone = null;
            if (_choicePanel != null) Dispose(_choicePanel);
            _choicePanel = null;
            done?.Invoke(result);
        }

        static void Dispose(GameObject go)
        {
            if (Application.isPlaying) Destroy(go);
            else DestroyImmediate(go);
        }

        void OnDestroy()
        {
            if (_canvas != null) Dispose(_canvas.gameObject);
        }
    }
}
