namespace Xnu.UI
{
    // Eingabezustand eines Bildes für die UI-Logik (Bestätigen = A, Abbrechen = B; keine Unity-Typen).
    public readonly struct UiInputState
    {
        public readonly bool ConfirmPressed;
        public readonly bool CancelPressed;
        public readonly bool ConfirmHeld;
        public readonly bool CancelHeld;
        // -1 = nach oben, +1 = nach unten, nur im Bild der Flanke (Wiederholung noch nicht umgesetzt).
        public readonly int MoveY;
        // -1 = nach links, +1 = nach rechts (Flanke).
        public readonly int MoveX;
        // Plus-Taste (Menü öffnen/schließen) im Bild der Flanke.
        public readonly bool MenuPressed;

        public UiInputState(bool confirmPressed, bool cancelPressed, bool confirmHeld, bool cancelHeld, int moveY = 0, int moveX = 0, bool menuPressed = false)
        {
            ConfirmPressed = confirmPressed;
            CancelPressed = cancelPressed;
            ConfirmHeld = confirmHeld;
            CancelHeld = cancelHeld;
            MoveY = moveY;
            MoveX = moveX;
            MenuPressed = menuPressed;
        }

        public static UiInputState None => default;
        public bool AnyHeld => ConfirmHeld || CancelHeld;
        public bool AnyPressed => ConfirmPressed || CancelPressed;
    }

    public interface IUiInputSource
    {
        UiInputState Poll();
    }

    // Verknüpft zwei Quellen (ODER bei Tasten, die erste Bewegung gewinnt).
    public sealed class MergedUiInput : IUiInputSource
    {
        readonly IUiInputSource _a, _b;

        public MergedUiInput(IUiInputSource a, IUiInputSource b)
        {
            _a = a;
            _b = b;
        }

        public UiInputState Poll()
        {
            var x = _a.Poll();
            var y = _b.Poll();
            return new UiInputState(x.ConfirmPressed || y.ConfirmPressed, x.CancelPressed || y.CancelPressed,
                x.ConfirmHeld || y.ConfirmHeld, x.CancelHeld || y.CancelHeld, x.MoveY != 0 ? x.MoveY : y.MoveY,
                x.MoveX != 0 ? x.MoveX : y.MoveX, x.MenuPressed || y.MenuPressed);
        }
    }

    // Eingabe von Hand (Tests, Skriptsteuerung): Tasten werden für genau ein Poll() gemeldet.
    public sealed class ManualUiInput : IUiInputSource
    {
        bool _confirm, _cancel, _held, _heldCancel, _menu;
        int _moveY, _moveX;

        public void PressConfirm() => _confirm = true;
        public void PressCancel() => _cancel = true;
        public void PressMenu() => _menu = true;
        public void MoveUp() => _moveY = -1;
        public void MoveDown() => _moveY = 1;
        public void MoveLeft() => _moveX = -1;
        public void MoveRight() => _moveX = 1;
        public void HoldConfirm(bool held) => _held = held;
        public void HoldCancel(bool held) => _heldCancel = held;

        public UiInputState Poll()
        {
            var s = new UiInputState(_confirm, _cancel, _held || _confirm, _heldCancel || _cancel, _moveY, _moveX, _menu);
            _confirm = _cancel = _menu = false;
            _moveY = _moveX = 0;
            return s;
        }
    }
}
