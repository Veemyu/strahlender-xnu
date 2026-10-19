using System;
using System.Text;
using Xnu.Text;

namespace Xnu.UI
{
    public enum TextboxState
    {
        Closed,
        Opening,
        Typing,
        TimedWait,
        WaitKey,
        Scrolling,
        // Nachricht zu Ende, Fenster bleibt offen (Frage); Close() schließt es.
        Held,
        Closing,
    }

    // Ablauf des Nachrichtenfensters ohne Unity-Typen: öffnen, Schreibmaschine je Abschnitt, Ereignisse
    // (Zeilenumbruch, Wartezeit, Seite/Zeile scrollen, Rückruf, Ende), Tastenwarten, schließen.
    // Zeitwerte: MessageTimingConfig (Messwerte aus MsgWindowConfig). Verhalten nach Signaturen und Konfigwerten [A].
    public sealed class TextboxFlow
    {
        enum AfterKey { Close, ClearPage, ScrollLine }

        readonly ComposedMessage _message;
        readonly MessageSpeed _speed;
        readonly MessageTimingConfig _config;
        readonly StringBuilder _committed = new StringBuilder();

        int _index = -1;
        MessageTypewriter _typewriter;
        AfterKey _afterKey;
        float _stateTime;
        float _waitSeconds;
        int _keyFrames;

        // Öffnen und Schließen des Fensters in Sekunden (Dauer im Original nicht gelesen [A]).
        public float OpenDuration { get; set; } = 0.1f;
        public float CloseDuration { get; set; } = 0.1f;
        // Nach dem Ende nicht auf eine Taste warten, sondern offen bleiben (für Fragen mit Auswahl).
        public bool HoldOpenAtEnd { get; set; }

        public TextboxState State { get; private set; } = TextboxState.Closed;

        // Rückrufnummer eines CallBack-Ereignisses.
        public event Action<int> CallBack;

        public TextboxFlow(ComposedMessage message, MessageSpeed speed = MessageSpeed.Normal, MessageTimingConfig config = null)
        {
            _message = message ?? throw new ArgumentNullException(nameof(message));
            _speed = speed;
            _config = config ?? new MessageTimingConfig();
        }

        public bool IsClosed => State == TextboxState.Closed;
        public bool KeyIconVisible => State == TextboxState.WaitKey;
        public int SectionIndex => _index;

        // Bereits fertige Abschnitte der Seite plus der sichtbare Teil des laufenden Abschnitts (Rich-Text bleibt erhalten).
        public string DisplayText => State == TextboxState.Typing && _typewriter != null
            ? _committed + _typewriter.VisibleText
            : _committed.ToString();

        // Zeilen, die nach oben aus dem Fenster gescrollt sind (ScrollLine), und Fortschritt der laufenden Bewegung 0..1.
        public int ScrolledLines { get; private set; }
        public float ScrollProgress => State == TextboxState.Scrolling ? Clamp01(_stateTime / _config.ScrollTextDuration) : 0f;

        // Öffnungsgrad des Fensters 0..1 (Animation von Öffnen und Schließen).
        public float WindowProgress
        {
            get
            {
                switch (State)
                {
                    case TextboxState.Closed: return 0f;
                    case TextboxState.Opening: return OpenDuration <= 0 ? 1f : Clamp01(_stateTime / OpenDuration);
                    case TextboxState.Closing: return CloseDuration <= 0 ? 0f : 1f - Clamp01(_stateTime / CloseDuration);
                    default: return 1f;
                }
            }
        }

        public void Open()
        {
            if (State != TextboxState.Closed) throw new InvalidOperationException("Fenster ist schon offen");
            _index = -1;
            _committed.Clear();
            ScrolledLines = 0;
            Enter(TextboxState.Opening);
            if (OpenDuration <= 0) BeginNextSection();
        }

        void Enter(TextboxState s)
        {
            State = s;
            _stateTime = 0;
            _keyFrames = 0;
        }

        public void Update(float deltaSeconds, UiInputState input)
        {
            if (deltaSeconds < 0) throw new ArgumentOutOfRangeException(nameof(deltaSeconds));
            switch (State)
            {
                case TextboxState.Opening:
                    _stateTime += deltaSeconds;
                    if (_stateTime >= OpenDuration) BeginNextSection();
                    break;

                case TextboxState.Typing:
                    // Taste halten beschleunigt (fastForwardMagnification), ein einzelner Druck überspringt nichts.
                    _typewriter.Advance(deltaSeconds, input.AnyHeld);
                    if (_typewriter.IsComplete) CompleteSection();
                    break;

                case TextboxState.TimedWait:
                    _stateTime += deltaSeconds;
                    if (_stateTime >= _waitSeconds) BeginNextSection();
                    break;

                case TextboxState.WaitKey:
                    // Nach dem Ende einer Nachricht ignoriert das Fenster einige Bilder lang Eingaben (waitAfterFinishMsgFrame).
                    _keyFrames++;
                    if (_keyFrames > _config.WaitAfterFinishFrames && input.AnyPressed) KeyAccepted();
                    break;

                case TextboxState.Scrolling:
                    _stateTime += deltaSeconds;
                    if (_stateTime >= _config.ScrollTextDuration)
                    {
                        ScrolledLines++;
                        BeginNextSection();
                    }
                    break;

                case TextboxState.Closing:
                    _stateTime += deltaSeconds;
                    if (_stateTime >= CloseDuration) State = TextboxState.Closed;
                    break;
            }
        }

        void BeginNextSection()
        {
            _index++;
            if (_index >= _message.Lines.Count)
            {
                Enter(TextboxState.Closing);
                return;
            }
            _typewriter = new MessageTypewriter(_message.Lines[_index], _speed, _config);
            Enter(TextboxState.Typing);
            if (_typewriter.IsComplete) CompleteSection();
        }

        void CompleteSection()
        {
            var line = _message.Lines[_index];
            _committed.Append(line.Text);
            switch (line.EndEvent)
            {
                case MessageEvent.NewLine:
                    _committed.Append('\n');
                    BeginNextSection();
                    break;
                case MessageEvent.Wait:
                    _waitSeconds = line.EventValue;
                    if (_waitSeconds <= 0) BeginNextSection();
                    else Enter(TextboxState.TimedWait);
                    break;
                case MessageEvent.ScrollPage:
                    _afterKey = AfterKey.ClearPage;
                    Enter(TextboxState.WaitKey);
                    break;
                case MessageEvent.ScrollLine:
                    _committed.Append('\n');
                    _afterKey = AfterKey.ScrollLine;
                    Enter(TextboxState.WaitKey);
                    break;
                case MessageEvent.CallBack:
                    CallBack?.Invoke((int)line.EventValue);
                    BeginNextSection();
                    break;
                case MessageEvent.End:
                    _afterKey = AfterKey.Close;
                    Enter(HoldOpenAtEnd ? TextboxState.Held : TextboxState.WaitKey);
                    break;
                default:
                    BeginNextSection();
                    break;
            }
        }

        public void Close()
        {
            if (State != TextboxState.Held) throw new InvalidOperationException("Close nur im Zustand Held");
            Enter(TextboxState.Closing);
            if (CloseDuration <= 0) State = TextboxState.Closed;
        }

        void KeyAccepted()
        {
            switch (_afterKey)
            {
                case AfterKey.Close:
                    Enter(TextboxState.Closing);
                    if (CloseDuration <= 0) State = TextboxState.Closed;
                    break;
                case AfterKey.ClearPage:
                    _committed.Clear();
                    ScrolledLines = 0;
                    BeginNextSection();
                    break;
                case AfterKey.ScrollLine:
                    Enter(TextboxState.Scrolling);
                    break;
            }
        }

        static float Clamp01(float v) => v < 0 ? 0 : v > 1 ? 1 : v;
    }
}
