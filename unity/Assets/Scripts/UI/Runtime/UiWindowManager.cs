using System;
using System.Collections.Generic;
using UnityEngine;

namespace Xnu.UI
{
    // Daten für die Original-Fenster (Spielstand, Namen). Implementierung im Spielkern (Xnu.Game.Unity).
    public interface IUiGameData : IUiNumberLabelSource
    {
        IReadOnlyList<PartyRow> PartyRows();
        IReadOnlyList<BagPocket> BagPockets();
        int Money { get; }
    }

    public enum UiScreen { None, Main, Party, Bag, Choice, Notice }

    // Verwaltet die Original-Fenster als Stapel: Hauptmenü → Party/Beutel → Auswahl/Hinweis. Eingabe kommt je Logikschritt von außen.
    // Kann ein Fenster nicht gebaut werden (Spieldaten oder Stubs fehlen), meldet IsAvailable false und der Aufrufer nimmt die eigenen Fenster.
    public sealed class UiWindowManager : MonoBehaviour
    {
        Camera _camera;
        IUiGameData _data;
        XMenuView _main;
        PartyView _party;
        BagView _bag;
        ChoiceView _choice;
        NoticeView _notice;
        Action<int> _choiceDone;
        Action _noticeDone;
        Action _closed;
        bool _saveAsked;

        public UiScreen Screen { get; private set; }
        public bool IsOpen => Screen != UiScreen.None;
        // false, wenn ein Original-Fenster nicht gebaut werden konnte (Rückfall auf die eigenen Fenster).
        public bool IsAvailable { get; private set; } = true;
        public string LastError { get; private set; } = "";
        public int WindowsOpened { get; private set; }
        public int PartyRowsShown => _party?.RowsShown ?? 0;
        public Func<string> SaveHandler { get; set; }

        public XMenuView Main => _main;
        public PartyView Party => _party;
        public BagView Bag => _bag;
        public ChoiceView Choice => _choice;

        public void Configure(Camera camera, IUiGameData data)
        {
            _camera = camera;
            _data = data;
        }

        bool Fail(string error)
        {
            IsAvailable = false;
            LastError = error ?? "unbekannt";
            Debug.LogWarning("[UI] Original-Fenster nicht verfügbar: " + LastError);
            return false;
        }

        public bool OpenMainMenu(Action onClosed)
        {
            if (IsOpen || _data == null) return false;
            var v = XMenuView.Create(_camera, transform, _data);
            if (v.Root == null || v.Model == null) { v.Destroy(); return Fail(v.Error); }
            _main = v;
            _closed = onClosed;
            Screen = UiScreen.Main;
            WindowsOpened++;
            return true;
        }

        // Auswahlfenster (Ja/Nein, Liste). done bekommt den gewählten Index (bei Abbruch den Abbruch-Eintrag).
        public bool OpenChoice(IReadOnlyList<string> entries, int cancelIndex, Action<int> done)
        {
            if (_choice != null || _data == null || entries == null || entries.Count == 0) return false;
            var v = ChoiceView.Create(_camera, transform, _data, entries, cancelIndex);
            if (v.Root == null || v.Model == null) { v.Destroy(); return Fail(v.Error); }
            _choice = v;
            _choiceDone = done;
            Debug.Log("[UI] Auswahl geöffnet: " + string.Join(" | ", entries));
            if (Screen == UiScreen.None) Screen = UiScreen.Choice;
            WindowsOpened++;
            return true;
        }

        public bool OpenNotice(string text, Action done)
        {
            if (_notice != null || _data == null) return false;
            var v = NoticeView.Create(_camera, transform, _data, text);
            if (v.Root == null) { v.Destroy(); return Fail(v.Error); }
            _notice = v;
            _noticeDone = done;
            if (Screen == UiScreen.None) Screen = UiScreen.Notice;
            WindowsOpened++;
            return true;
        }

        public bool HasChoice => _choice != null;
        public bool HasNotice => _notice != null;

        public void CloseAll()
        {
            DestroyChoice();
            DestroyNotice();
            _party?.Destroy(); _party = null;
            _bag?.Destroy(); _bag = null;
            _main?.Destroy(); _main = null;
            Screen = UiScreen.None;
        }

        void DestroyChoice() { _choice?.Destroy(); _choice = null; _choiceDone = null; }
        void DestroyNotice() { _notice?.Destroy(); _notice = null; _noticeDone = null; }

        // Ein Logikschritt (30 Hz) mit der Eingabe des Schritts.
        public void Tick(UiInputState ui)
        {
            if (_notice != null)
            {
                if (ui.ConfirmPressed || ui.CancelPressed)
                {
                    var done = _noticeDone;
                    DestroyNotice();
                    if (Screen == UiScreen.Notice) Screen = UiScreen.None;
                    done?.Invoke();
                }
                return;
            }
            if (_choice != null)
            {
                _choice.Model.Update(ui);
                _choice.Refresh();
                if (_choice.Model.IsDone)
                {
                    var result = _choice.Model.Result;
                    var done = _choiceDone;
                    DestroyChoice();
                    if (Screen == UiScreen.Choice) Screen = UiScreen.None;
                    done?.Invoke(result);
                }
                return;
            }
            switch (Screen)
            {
                case UiScreen.Main: TickMain(ui); break;
                case UiScreen.Party: TickParty(ui); break;
                case UiScreen.Bag: TickBag(ui); break;
            }
        }

        void TickMain(UiInputState ui)
        {
            var m = _main.Model;
            m.Update(ui);
            _main.Refresh();
            if (m.IsClosed)
            {
                var closed = _closed;
                CloseAll();
                closed?.Invoke();
                return;
            }
            if (m.ReportRequested)
            {
                m.ClearReport();
                AskSave();
                return;
            }
            switch (m.Chosen)
            {
                case MenuEntryId.Party:
                    var party = PartyView.Create(_camera, transform, _data, _data.PartyRows());
                    if (party.Root == null || party.Model == null) { party.Destroy(); Fail(party.Error); m.ResumeAfterChild(); return; }
                    _party = party;
                    _main.Root.SetActive(false);
                    Screen = UiScreen.Party;
                    WindowsOpened++;
                    break;
                case MenuEntryId.Bag:
                    var bag = BagView.Create(_camera, transform, _data, _data.BagPockets(), _data.Money);
                    if (bag.Root == null || bag.Model == null) { bag.Destroy(); Fail(bag.Error); m.ResumeAfterChild(); return; }
                    _bag = bag;
                    _main.Root.SetActive(false);
                    Screen = UiScreen.Bag;
                    WindowsOpened++;
                    break;
                case MenuEntryId.Report:
                    m.ResumeAfterChild();
                    AskSave();
                    break;
                default:
                    if (m.Chosen != MenuEntryId.None) m.ResumeAfterChild();
                    break;
            }
        }

        void AskSave()
        {
            if (_saveAsked) return;
            _saveAsked = true;
            var yes = _data.Label("ss_xmenu", "SS_xmenu_29") ?? "Speichern";
            var no = _data.Label("ss_xmenu", "SS_xmenu_49") ?? "Abbrechen";
            if (!OpenChoice(new[] { yes, no.Trim() }, 1, idx =>
            {
                _saveAsked = false;
                if (idx != 0 || SaveHandler == null) return;
                var result = SaveHandler();
                if (!string.IsNullOrEmpty(result)) OpenNotice(result, null);
            })) _saveAsked = false;
        }

        void TickParty(UiInputState ui)
        {
            var m = _party.Model;
            m.Update(ui);
            _party.Refresh();
            if (m.Chosen >= 0) m.ResumeAfterChoice();
            if (m.IsClosed) BackToMain(ref _party);
        }

        void TickBag(UiInputState ui)
        {
            var m = _bag.Model;
            m.Update(ui);
            _bag.Refresh();
            if (m.Chosen != null) m.ResumeAfterChoice();
            if (m.IsClosed) BackToMain(ref _bag);
        }

        void BackToMain<T>(ref T view) where T : class
        {
            switch (view)
            {
                case PartyView p: p.Destroy(); break;
                case BagView b: b.Destroy(); break;
            }
            view = null;
            _main.Root.SetActive(true);
            _main.Model.ResumeAfterChild();
            Screen = UiScreen.Main;
        }

        void OnDestroy() => CloseAll();
    }
}
