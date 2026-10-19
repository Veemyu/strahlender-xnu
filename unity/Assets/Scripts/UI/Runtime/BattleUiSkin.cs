using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Xnu.UI
{
    public readonly struct SkinMove
    {
        public readonly string Name;
        public readonly int Pp, MaxPp, Type;
        public SkinMove(string name, int pp, int maxPp, int type) { Name = name; Pp = pp; MaxPp = maxPp; Type = type; }
    }

    // Kampf-UI aus dem Original-Prefab (battleviewuisystem): Statusfenster (Name, Stufe, KP), Befehlsliste (Kampf/Pokémon/Beutel/Flucht)
    // und Attackenliste (Name, PP, Typ-Grafik). Meldungsfenster und Ablauf bleiben in BattleView.
    public sealed class BattleUiSkin
    {
        // Reihenfolge der Befehle im Original (ActionButtonType): Kampf 0, Pokémon 1, Beutel 2, Flucht 3.
        public static readonly int[] CommandTypes = { 0, 2, 1, 3 };

        static readonly string[] KeepChildren = { "BUIActionList", "StatusWindows", "BUIWazaList" };

        public GameObject Root { get; private set; }
        public string Error { get; private set; }
        public int VisibleActionButtons { get; private set; }
        public int VisibleWazaButtons { get; private set; }

        IBtlStatusView _near, _far;
        IBtlActionListView _actions;
        IBtlWazaListView _wazas;

        public static BattleUiSkin Create(Camera camera, Transform parent, IUiLabelSource labels, int sortingOrder)
        {
            var go = OriginalWindowFactory.Create("ui/prefab/battleviewuisystem", camera, sortingOrder, parent, labels, out _);
            if (go == null) return new BattleUiSkin { Error = OriginalWindowFactory.LastError };
            return Bind(go);
        }

        public static BattleUiSkin Bind(GameObject go)
        {
            var s = new BattleUiSkin { Root = go };
            var sys = UiFind.First<IBtlSystemView>(go);
            if (sys == null || sys.StatusWindows == null || sys.StatusWindows.Length < 2 || sys.ActionList == null || sys.WazaList == null)
            {
                s.Error = "Kampf-UI-Komponenten fehlen (Stubs nicht gebunden?)";
                return s;
            }
            s._near = sys.StatusWindows[0];
            s._far = sys.StatusWindows[1];
            s._actions = sys.ActionList;
            s._wazas = sys.WazaList;
            var desc = UiFind.Child(go.transform, "DescriptionButton");
            if (desc != null) desc.gameObject.SetActive(false);
            for (var i = 0; i < go.transform.childCount; i++)
            {
                var c = go.transform.GetChild(i);
                if (Array.IndexOf(KeepChildren, c.name) < 0) c.gameObject.SetActive(false);
            }
            for (var i = 2; i < sys.StatusWindows.Length; i++) sys.StatusWindows[i].Component.gameObject.SetActive(false);
            foreach (var w in new[] { s._near, s._far })
            {
                var cg = w.Component.GetComponent<CanvasGroup>();
                if (cg != null) cg.alpha = 1f;
                w.Component.gameObject.SetActive(true);
                if (w.BallBar != null) w.BallBar.SetActive(false);
                if (w.Condition != null) w.Condition.SetActive(false);
            }
            if (s._far.Exp != null) s._far.Exp.gameObject.SetActive(false);
            s.HideCommands();
            s.HideMoves();
            return s;
        }

        static void ShowGroup(Component c, bool on)
        {
            if (c == null) return;
            c.gameObject.SetActive(on);
            var cg = c.GetComponent<CanvasGroup>();
            if (cg != null) cg.alpha = on ? 1f : 0f;
        }

        public void SetVisible(bool on)
        {
            if (Root != null) Root.SetActive(on);
        }

        public void SetStatus(bool player, string name, int level, int hp, int maxHp, int gender, float expRatio = 0f)
        {
            var w = player ? _near : _far;
            if (w == null) return;
            UiFind.SetText(w.Name, name);
            UiFind.SetText(w.LevelValue, level.ToString());
            if (w.Hp != null)
            {
                w.Hp.gameObject.SetActive(player);
                w.Hp.text = hp + " / " + maxHp;
            }
            HpBarBinder.Apply(w.HpBar, HpStages.Ratio(hp, maxHp), HpStages.Of(hp, maxHp));
            if (w.Gender != null)
            {
                var known = (gender == 0 || gender == 1) && w.Gender.sprite != null;
                w.Gender.gameObject.SetActive(known);
                w.Gender.color = gender == 1 ? new Color(1f, 0.55f, 0.65f) : new Color(0.55f, 0.75f, 1f);
            }
            if (player && w.Exp != null) w.Exp.value = Mathf.Lerp(w.Exp.minValue, w.Exp.maxValue, Mathf.Clamp01(expRatio));
        }

        public void HideCommands() => ShowGroup(_actions?.Component, false);

        public void SetHpRatio(bool player, float ratio)
        {
            var w = player ? _near : _far;
            if (w == null) return;
            var hp = Mathf.RoundToInt(ratio * 100f);
            HpBarBinder.Apply(w.HpBar, ratio, HpStages.Of(hp, 100));
        }

        // Befehlsliste mit Cursor auf Eintrag cursor (0 Kampf, 1 Beutel, 2 Pokémon, 3 Flucht wie die Zeilen der Kampfansicht).
        public void ShowCommands(int cursor)
        {
            if (_actions == null) return;
            ShowGroup(_actions.Component, true);
            var shown = 0;
            foreach (var b in _actions.Buttons)
            {
                var slot = Array.IndexOf(CommandTypes, ((IBtlActionButtonView)b).ButtonType);
                var go = b.Component.gameObject;
                go.SetActive(slot >= 0);
                if (slot < 0) continue;
                shown++;
                var cg = go.GetComponent<CanvasGroup>();
                if (cg != null) cg.alpha = 1f;
                var anim = go.GetComponent<Animator>();
                if (anim != null) anim.enabled = false;
                var on = slot == cursor;
                var ab = (IBtlActionButtonView)b;
                if (ab.LightFrame != null) ab.LightFrame.gameObject.SetActive(on);
                b.Component.transform.localScale = on ? new Vector3(1.06f, 1.06f, 1f) : Vector3.one;
            }
            VisibleActionButtons = shown;
            if (_actions.XyFrame != null) _actions.XyFrame.SetActive(false);
        }

        public void HideMoves() => ShowGroup(_wazas?.Component, false);

        public void ShowMoves(IReadOnlyList<SkinMove> moves, int cursor)
        {
            if (_wazas == null) return;
            ShowGroup(_wazas.Component, true);
            var shown = 0;
            for (var i = 0; i < _wazas.Buttons.Length; i++)
            {
                var b = _wazas.Buttons[i];
                var go = b.Component.gameObject;
                if (i >= moves.Count) { go.SetActive(false); continue; }
                shown++;
                go.SetActive(true);
                var m = moves[i];
                UiFind.SetText(b.Text, m.Name);
                UiFind.SetText(b.Pp, m.Pp.ToString());
                UiFind.SetText(b.MaxPp, m.MaxPp.ToString());
                if (b.EffectiveRoot != null) b.EffectiveRoot.SetActive(false);
                if (b.Background != null && _wazas.TypeSprites != null && m.Type >= 0 && m.Type < _wazas.TypeSprites.Length && _wazas.TypeSprites[m.Type] != null)
                    b.Background.sprite = _wazas.TypeSprites[m.Type];
                var on = i == cursor;
                b.Component.transform.localScale = on ? new Vector3(1.05f, 1.05f, 1f) : Vector3.one;
                if (b.Background != null) b.Background.color = on ? Color.white : new Color(0.82f, 0.82f, 0.82f, 1f);
            }
            VisibleWazaButtons = shown;
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }
}
