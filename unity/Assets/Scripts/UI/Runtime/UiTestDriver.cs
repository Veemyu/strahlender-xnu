using TMPro;
using UnityEngine;

namespace Xnu.UI
{
    // Testszene UiTest: spielt erfundene Meldungen nacheinander ab (Zeilen, Rich-Text, Scrollen, Seiten, Frage).
    // Eingabe: A/L/Enter/Leertaste bestätigt, B/K/Rücktaste bricht ab, halten beschleunigt, Pfeiltasten wählen.
    // Keine Spieldaten, kein Ton.
    [DisallowMultipleComponent]
    public sealed class UiTestDriver : MonoBehaviour
    {
        [SerializeField] TextboxView textbox;
        [SerializeField] float pauseBetweenMessages = 0.6f;
        // > 0: Bestätigung automatisch nach so vielen Sekunden im Tastenwarten (für Aufnahmen).
        [SerializeField] float autoConfirmAfter;
        [SerializeField] bool autoStart = true;

        static readonly string[] Demo =
        {
            "Willkommen im Testfenster.\nDies ist eine erfundene Meldung.",
            "Das ist <color=#c02020>rot</color>, <size=44>groß</size> und normal.\nZweite Zeile des Tests.\vNach dem Scrollen steht hier eine dritte Zeile.",
            "Erste Seite des Tests.\fZweite Seite folgt nach dem Weiter-Symbol.",
        };

        readonly ManualUiInput _manual = new ManualUiInput();
        TextMeshProUGUI _status;
        int _next;
        float _pause;
        float _keyWait;
        string _lastAnswer = "-";
        bool _running;

        public TextboxView Textbox => textbox;
        public string LastAnswer => _lastAnswer;
        public int MessagesFinished { get; private set; }

        void Start()
        {
            if (textbox == null) textbox = GetComponentInChildren<TextboxView>();
            if (textbox == null) textbox = gameObject.AddComponent<TextboxView>();
            textbox.EnsureBuilt();
            textbox.InputSource = new MergedUiInput(new GameInputUiSource(), _manual);
            BuildStatus();
            _running = autoStart;
        }

        public void InjectConfirm() => _manual.PressConfirm();
        public void InjectCancel() => _manual.PressCancel();
        public void InjectDown() => _manual.MoveDown();
        public void InjectUp() => _manual.MoveUp();
        public void Pause(bool paused) => _running = !paused;

        void BuildStatus()
        {
            var canvas = UiCanvasFactory.Create("StatusCanvas", textbox.TargetCamera, 10, transform);
            var go = new GameObject("Status", typeof(RectTransform));
            var rt = (RectTransform)go.transform;
            rt.SetParent(canvas.transform, false);
            rt.anchorMin = new Vector2(0f, 1f);
            rt.anchorMax = new Vector2(1f, 1f);
            rt.pivot = new Vector2(0f, 1f);
            rt.sizeDelta = new Vector2(-40f, 150f);
            rt.anchoredPosition = new Vector2(20f, -16f);
            _status = go.AddComponent<TextMeshProUGUI>();
            _status.fontSize = 24f;
            _status.color = Color.white;
            _status.alignment = TextAlignmentOptions.TopLeft;
            _status.raycastTarget = false;
        }

        void Update()
        {
            if (textbox == null) return;
            var flow = textbox.Flow;

            if (autoConfirmAfter > 0 && flow != null && flow.State == TextboxState.WaitKey)
            {
                _keyWait += Time.deltaTime;
                if (_keyWait >= autoConfirmAfter) { _manual.PressConfirm(); _keyWait = 0; }
            }
            else _keyWait = 0;

            if (_running && !textbox.IsOpen && !textbox.IsChoosing)
            {
                _pause += Time.deltaTime;
                if (_pause >= pauseBetweenMessages) StartNext();
            }
            else _pause = 0;

            if (_status != null)
            {
                _status.text = "UiTest (erfundene Texte)  |  A/L/Enter weiter, B/K zurück, halten = schneller, Pfeile wählen\n"
                    + "Zustand: " + (flow == null ? "-" : flow.State.ToString()) + "  |  Abschnitt: " + (flow == null ? "-" : flow.SectionIndex.ToString())
                    + "  |  Auswahl: " + (textbox.IsChoosing ? "offen" : "-") + "  |  letzte Antwort: " + _lastAnswer
                    + "\nSkin: " + textbox.SkinNote + "  |  Meldungen fertig: " + MessagesFinished;
            }
        }

        void StartNext()
        {
            _pause = 0;
            var idx = _next % (Demo.Length + 1);
            _next++;
            if (idx < Demo.Length)
                textbox.Show(Demo[idx], () => MessagesFinished++);
            else
                textbox.Ask("Gefällt dir dieses Fenster?", new[] { "Ja", "Nein" }, 1, a =>
                {
                    _lastAnswer = a == 0 ? "Ja" : "Nein";
                    MessagesFinished++;
                });
        }
    }
}
