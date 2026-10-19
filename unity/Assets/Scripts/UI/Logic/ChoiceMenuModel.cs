using System;

namespace Xnu.UI
{
    // Auswahlmenü (z. B. Ja/Nein) ohne Unity-Typen: Cursor mit Umlauf, Bestätigen wählt, Abbrechen wählt den Abbruch-Eintrag.
    public sealed class ChoiceMenuModel
    {
        public int Count { get; }
        public int CancelIndex { get; }
        public bool Wrap { get; }
        public int Cursor { get; private set; }
        public bool IsDone { get; private set; }
        public bool WasCancelled { get; private set; }
        // Gewählter Eintrag; bei Abbruch der Abbruch-Eintrag.
        public int Result { get; private set; } = -1;

        // cancelIndex < 0: Abbrechen wird ignoriert.
        public ChoiceMenuModel(int count, int cancelIndex = -1, int initial = 0, bool wrap = true)
        {
            if (count <= 0) throw new ArgumentOutOfRangeException(nameof(count));
            if (initial < 0 || initial >= count) throw new ArgumentOutOfRangeException(nameof(initial));
            if (cancelIndex >= count) throw new ArgumentOutOfRangeException(nameof(cancelIndex));
            Count = count;
            CancelIndex = cancelIndex;
            Cursor = initial;
            Wrap = wrap;
        }

        public void Update(UiInputState input)
        {
            if (IsDone) return;
            if (input.MoveY != 0) Move(input.MoveY);
            if (input.ConfirmPressed)
            {
                Result = Cursor;
                IsDone = true;
            }
            else if (input.CancelPressed && CancelIndex >= 0)
            {
                Cursor = CancelIndex;
                Result = CancelIndex;
                WasCancelled = true;
                IsDone = true;
            }
        }

        void Move(int dy)
        {
            var next = Cursor + (dy > 0 ? 1 : -1);
            if (next < 0) next = Wrap ? Count - 1 : 0;
            else if (next >= Count) next = Wrap ? 0 : Count - 1;
            Cursor = next;
        }
    }
}
