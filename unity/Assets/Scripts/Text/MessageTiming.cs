using System;

namespace Xnu.Text
{
    // Zeitwerte des Nachrichtenfensters (Dpr.MsgWindow.MsgWindowConfig). Die Standardwerte sind die Zahlen aus den
    // serialisierten Daten des Originals (resources.assets); nur diese Zahlen, keine Inhalte.
    public sealed class MessageTimingConfig
    {
        // Sekunden je Zeichen für Slow, Normal, Fast.
        public float[] SecondsPerChar { get; set; } = { 0.06f, 0.03f, 0.01f };
        // Beschleunigung bei gehaltener Taste (fastForwardMagnification).
        public float FastForward { get; set; } = 5f;
        // Dauer des Hochscrollens einer Zeile (scrollTextDuration), Sekunden.
        public float ScrollTextDuration { get; set; } = 0.15f;
        // Wartezeit nach dem Ende der Nachricht in Bildern (waitAfterFinishMsgFrame).
        public int WaitAfterFinishFrames { get; set; } = 4;

        public float SecondsFor(MessageSpeed speed)
        {
            var i = (int)speed;
            if (i < 0 || i >= SecondsPerChar.Length) throw new ArgumentOutOfRangeException(nameof(speed));
            return SecondsPerChar[i];
        }
    }

    // Schreibmaschineneffekt für einen Abschnitt: wie viele Zeichen sind nach der verstrichenen Zeit sichtbar.
    // Annahme [A]: Das erste Zeichen erscheint nach einem vollen Zeichenintervall, danach eines je Intervall.
    public sealed class MessageTypewriter
    {
        readonly string _text;
        readonly float _secondsPerChar;
        readonly float _fastForward;
        float _elapsed;
        int _total;

        public MessageTypewriter(ComposedLine line, MessageSpeed speed, MessageTimingConfig config = null)
        {
            if (line == null) throw new ArgumentNullException(nameof(line));
            config = config ?? new MessageTimingConfig();
            _text = line.Text;
            _secondsPerChar = config.SecondsFor(speed);
            _fastForward = config.FastForward;
            _total = RichText.CountGlyphs(_text);
        }

        public int TotalGlyphs => _total;

        public int VisibleGlyphs
        {
            get
            {
                if (_secondsPerChar <= 0) return _total;
                var n = (int)(_elapsed / _secondsPerChar + 1e-4f);
                return n > _total ? _total : n;
            }
        }

        public bool IsComplete => VisibleGlyphs >= _total;

        public string VisibleText => RichText.TakeGlyphs(_text, VisibleGlyphs);

        public void Advance(float deltaSeconds, bool fastForward = false)
        {
            if (deltaSeconds < 0) throw new ArgumentOutOfRangeException(nameof(deltaSeconds));
            _elapsed += fastForward ? deltaSeconds * _fastForward : deltaSeconds;
        }

        public void Finish() => _elapsed = _secondsPerChar * _total + 1f;
    }
}
