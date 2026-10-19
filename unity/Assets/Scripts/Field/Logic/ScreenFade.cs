using System;

namespace Xnu.Field
{
    public enum FadePhase
    {
        Clear,   // Bild sichtbar
        Out,     // wird schwarz
        Black,   // schwarz, wartet auf Freigabe (Laden läuft)
        In,      // wird sichtbar
    }

    // Überblendung für Zonenwechsel: aus → schwarz halten (Laden) → ein. Dauern sind Annahmen
    // (Originalwerte nicht ermittelt); die Zustandsmaschine ist unabhängig von Unity.
    public sealed class ScreenFade
    {
        public float OutSeconds { get; set; } = 0.25f;
        public float InSeconds { get; set; } = 0.25f;

        float _t;

        public FadePhase Phase { get; private set; } = FadePhase.Clear;
        public bool Active => Phase != FadePhase.Clear;
        public bool IsBlack => Phase == FadePhase.Black;

        // 0 = durchsichtig, 1 = schwarz.
        public float Alpha
        {
            get
            {
                switch (Phase)
                {
                    case FadePhase.Out: return OutSeconds <= 0f ? 1f : Math.Min(1f, _t / OutSeconds);
                    case FadePhase.Black: return 1f;
                    case FadePhase.In: return InSeconds <= 0f ? 0f : 1f - Math.Min(1f, _t / InSeconds);
                    default: return 0f;
                }
            }
        }

        public void Begin()
        {
            _t = 0f;
            Phase = OutSeconds <= 0f ? FadePhase.Black : FadePhase.Out;
        }

        // Nach dem Laden: Einblenden beginnt.
        public void Release()
        {
            if (Phase != FadePhase.Black) return;
            _t = 0f;
            Phase = InSeconds <= 0f ? FadePhase.Clear : FadePhase.In;
        }

        public void Tick(float dt)
        {
            if (dt <= 0f) return;
            switch (Phase)
            {
                case FadePhase.Out:
                    _t += dt;
                    if (_t >= OutSeconds) { _t = 0f; Phase = FadePhase.Black; }
                    break;
                case FadePhase.In:
                    _t += dt;
                    if (_t >= InSeconds) { _t = 0f; Phase = FadePhase.Clear; }
                    break;
            }
        }
    }
}
