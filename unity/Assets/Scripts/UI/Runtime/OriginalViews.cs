using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Xnu.UI
{
    public static class UiFind
    {
        // Alle Komponenten unterhalb von root (auch inaktive), die die Schnittstelle T implementieren, in Hierarchiereihenfolge.
        public static List<T> All<T>(GameObject root) where T : class
        {
            var list = new List<T>();
            foreach (var mb in root.GetComponentsInChildren<MonoBehaviour>(true))
                if (mb is T t) list.Add(t);
            return list;
        }

        public static T First<T>(GameObject root) where T : class
        {
            foreach (var mb in root.GetComponentsInChildren<MonoBehaviour>(true))
                if (mb is T t) return t;
            return null;
        }

        public static Transform Child(Transform root, string name)
        {
            if (root == null) return null;
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == name) return t;
            return null;
        }

        public static GameObject GameObjectOf(object component) => (component as Component)?.gameObject;

        public static void SetText(TMP_Text t, string text)
        {
            if (t != null) t.text = text ?? "";
        }

        // Symbole, die das Original zur Laufzeit per Logik belegt (Sprite fehlt im Prefab): ohne Sprite ausblenden, sonst weiße Fläche.
        public static int HideEmptyIcons(GameObject root)
        {
            var n = 0;
            foreach (var img in root.GetComponentsInChildren<Image>(true))
            {
                if (img.sprite != null || !img.enabled) continue;
                if (img.name.IndexOf("Icon", StringComparison.OrdinalIgnoreCase) < 0) continue;
                img.enabled = false;
                n++;
            }
            return n;
        }
    }

    // Hauptmenü aus dem Original-Prefab (acht Einträge im Raster): Cursor = Symbol „an“, Leuchtrahmen, leichte Vergrößerung.
    public sealed class XMenuView
    {
        public GameObject Root { get; private set; }
        public MainMenuModel Model { get; private set; }
        public int ItemCount => _items.Count;
        public string Error { get; private set; }
        readonly List<IXMenuItemView> _items = new List<IXMenuItemView>();
        IXMenuView _menu;
        int _shown = -1;

        public static XMenuView Create(Camera camera, Transform parent, IUiLabelSource labels)
        {
            var go = OriginalWindowFactory.Create("ui/prefab/xmenu", camera, UiCanvasFactory.SortingWindow, parent, labels, out _);
            if (go == null) return new XMenuView { Error = OriginalWindowFactory.LastError };
            return Bind(go);
        }

        // Bindet eine schon instanziierte Menühierarchie (auch für Tests mit eigenen Komponenten).
        public static XMenuView Bind(GameObject go)
        {
            var v = new XMenuView();
            v.Root = go;
            v._menu = UiFind.First<IXMenuView>(go);
            var items = UiFind.All<IXMenuItemView>(go);
            if (v._menu == null || items.Count == 0) { v.Error = "Menü-Komponenten fehlen (Stubs nicht gebunden?)"; return v; }
            v._items.AddRange(items);
            if (v._menu.SafariRoot != null) v._menu.SafariRoot.gameObject.SetActive(false);
            UiFind.HideEmptyIcons(go);
            foreach (var it in items) if (it.Icon != null && it.Icon.sprite == null) it.Icon.enabled = false;
            var entries = new List<MenuEntry>();
            foreach (var it in items)
            {
                var id = MainMenuModel.IdFromLabel(it.NameText?.MessageId ?? "");
                var label = it.NameText?.Text != null ? it.NameText.Text.text : "";
                entries.Add(new MenuEntry { Id = id, Label = label, Enabled = MainMenuModel.IsImplemented(id) });
            }
            var columns = 2;
            var grid = v._menu.ItemRoot != null ? v._menu.ItemRoot.GetComponent<GridLayoutGroup>() : null;
            if (grid != null && grid.constraint == GridLayoutGroup.Constraint.FixedColumnCount) columns = Math.Max(1, grid.constraintCount);
            else if (grid != null && grid.constraint == GridLayoutGroup.Constraint.FixedRowCount) columns = Math.Max(1, (items.Count + grid.constraintCount - 1) / grid.constraintCount);
            v.Model = new MainMenuModel(entries, columns);
            v.Refresh(true);
            return v;
        }

        public void Refresh(bool force = false)
        {
            if (Model == null) return;
            var sel = Model.Cursor.Index;
            if (!force && sel == _shown) return;
            _shown = sel;
            for (var i = 0; i < _items.Count; i++)
            {
                var it = _items[i];
                var on = i == sel;
                var sprites = it.SpriteIcons;
                if (it.Icon != null && sprites != null && sprites.Length >= 2 && sprites[on ? 1 : 0] != null) it.Icon.sprite = sprites[on ? 1 : 0];
                var light = UiFind.Child(it.Root, "LightFrame");
                if (light != null) light.gameObject.SetActive(on);
                if (it.Root != null) it.Root.localScale = on ? new Vector3(1.06f, 1.06f, 1f) : Vector3.one;
                if (it.NewIcon != null) it.NewIcon.gameObject.SetActive(false);
            }
        }

        public void SetReportVisible(bool visible)
        {
            if (_menu?.ReportRoot != null) _menu.ReportRoot.gameObject.SetActive(visible);
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }

    // Party aus dem Original-Prefab (sechs Reihen): Name, Stufe, KP, Balken, Geschlecht, Item, Icon aus den Bundles.
    public sealed class PartyView
    {
        public GameObject Root { get; private set; }
        public PartyScreenModel Model { get; private set; }
        public string Error { get; private set; }
        public int RowsShown { get; private set; }
        readonly List<IPartyItemView> _items = new List<IPartyItemView>();
        int _shown = -1;

        public static PartyView Create(Camera camera, Transform parent, IUiLabelSource labels, IReadOnlyList<PartyRow> rows)
        {
            var go = OriginalWindowFactory.Create("ui/prefab/pokemonselect", camera, UiCanvasFactory.SortingWindow + 10, parent, labels, out _);
            if (go == null) return new PartyView { Error = OriginalWindowFactory.LastError };
            return Bind(go, rows, labels);
        }

        public static PartyView Bind(GameObject go, IReadOnlyList<PartyRow> rows, IUiLabelSource labels = null)
        {
            var v = new PartyView();
            v.Root = go;
            var party = UiFind.First<IPartyView>(go);
            if (party == null) { v.Error = "Party-Komponenten fehlen (Stubs nicht gebunden?)"; return v; }
            foreach (var it in UiFind.All<IPartyItemView>(party.ContentRoot.gameObject)) v._items.Add(it);
            v.Model = new PartyScreenModel(rows);
            v.Fill(rows, labels);
            v.Refresh(true);
            return v;
        }

        // Stufe als Beschriftung der Vorlage („Lv.“ + Zahl) aus der Textdatei; ohne Label nur die Zahl.
        static void SetLevel(TMP_Text text, int level, IUiLabelSource labels)
        {
            if (text == null) return;
            if (text is IUiText ut && ut.UseMessage && !string.IsNullOrEmpty(ut.MessageId) && labels is IUiNumberLabelSource nl)
            {
                var s = nl.Label(ut.MessageFile, ut.MessageId, level);
                if (s != null) { text.text = s; return; }
            }
            text.text = level.ToString();
        }

        void Fill(IReadOnlyList<PartyRow> rows, IUiLabelSource labels)
        {
            for (var i = 0; i < _items.Count; i++)
            {
                var item = _items[i];
                var go = UiFind.GameObjectOf(item);
                if (i >= rows.Count) { if (go != null) go.SetActive(false); continue; }
                RowsShown++;
                var r = rows[i];
                UiFind.SetText(item.Name, r.Name);
                SetLevel(item.Level, r.Level, labels);
                UiFind.SetText(item.Hp, r.Hp.ToString());
                UiFind.SetText(item.MaxHp, r.MaxHp.ToString());
                HpBarBinder.Apply(item.HpBar, r.HpRatio, r.Stage);
                if (item.Gender != null)
                {
                    item.Gender.gameObject.SetActive(r.Gender != 2 && !r.IsEgg);
                    item.Gender.color = r.Gender == 1 ? new Color(1f, 0.55f, 0.65f) : new Color(0.55f, 0.75f, 1f);
                }
                if (item.MonsIcon != null)
                {
                    var sprite = UiBundles.LoadPokemonIcon(r.MonsNo, r.Form) ?? UiBundles.LoadPokemonIcon(r.MonsNo, 0);
                    if (sprite != null) { item.MonsIcon.sprite = sprite; item.MonsIcon.enabled = true; }
                }
                if (item.ItemRoot != null) item.ItemRoot.gameObject.SetActive(false);
                if (item.HeldItemIcon != null) item.HeldItemIcon.gameObject.SetActive(!string.IsNullOrEmpty(r.ItemName));
            }
        }

        public void Refresh(bool force = false)
        {
            if (Model == null) return;
            var sel = Model.Cursor.Index;
            if (!force && sel == _shown) return;
            _shown = sel;
            for (var i = 0; i < _items.Count; i++)
            {
                var item = _items[i];
                var light = UiFind.Child(item.Root, "Image_LightFrame");
                if (light != null) light.gameObject.SetActive(i == sel && i < Model.Rows.Count);
                if (item.Root != null) item.Root.localScale = i == sel ? new Vector3(1.03f, 1.03f, 1f) : Vector3.one;
            }
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }

    public static class HpBarBinder
    {
        public static void Apply(IHpBarView bar, float ratio, HpStage stage)
        {
            if (bar == null) return;
            if (bar.Slider != null) bar.Slider.value = Mathf.Lerp(bar.Slider.minValue, bar.Slider.maxValue, ratio);
            if (bar.Body != null && bar.BodySprites != null && bar.BodySprites.Length > 0)
            {
                var idx = SpriteIndex(bar.SwitchRatios, bar.BodySprites.Length, ratio, stage);
                if (bar.BodySprites[idx] != null) bar.Body.sprite = bar.BodySprites[idx];
            }
        }

        // Schwellen aus dem Prefab (z. B. 0,5 / 0,2 / 0): erster Eintrag, dessen Schwelle unterschritten wird nicht; sonst Stufe des Originals.
        public static int SpriteIndex(float[] switchRatios, int spriteCount, float ratio, HpStage stage)
        {
            if (switchRatios != null && switchRatios.Length > 0)
            {
                for (var k = 0; k < switchRatios.Length && k < spriteCount; k++)
                    if (ratio > switchRatios[k]) return k;
                return Math.Min(spriteCount, switchRatios.Length) - 1;
            }
            var idx = stage == HpStage.Danger || stage == HpStage.Fainted ? 2 : stage == HpStage.Warning ? 1 : 0;
            return Math.Min(idx, spriteCount - 1);
        }
    }

    // Beutel aus dem Original-Prefab: Taschenreiter, Liste (Zeilen aus der Vorlage), Beschreibung, Geld.
    public sealed class BagView
    {
        public GameObject Root { get; private set; }
        public BagScreenModel Model { get; private set; }
        public string Error { get; private set; }
        public int RowCount => _rows.Count;
        readonly List<IBagItemView> _rows = new List<IBagItemView>();
        readonly List<IBagCategoryView> _tabs = new List<IBagCategoryView>();
        IBagPanelView _panel;
        RectTransform _cursorFrame;
        RectTransform _content;
        int _shownTop = -2, _shownIndex = -1, _shownPocket = -1;
        int _money;

        public static BagView Create(Camera camera, Transform parent, IUiLabelSource labels, IReadOnlyList<BagPocket> pockets, int money)
        {
            var go = OriginalWindowFactory.Create("ui/prefab/bag", camera, UiCanvasFactory.SortingWindow + 10, parent, labels, out _);
            if (go == null) return new BagView { Error = OriginalWindowFactory.LastError };
            return Bind(go, pockets, money);
        }

        public static BagView Bind(GameObject go, IReadOnlyList<BagPocket> pockets, int money)
        {
            var v = new BagView { _money = money };
            v.Root = go;
            var bag = UiFind.First<IBagView>(go);
            v._panel = bag?.Panel;
            if (v._panel == null || v._panel.ListScroll == null) { v.Error = "Beutel-Komponenten fehlen (Stubs nicht gebunden?)"; return v; }
            v._content = v._panel.ListScroll.content;
            var template = UiFind.First<IBagItemView>(v._content.gameObject);
            if (template == null) { v.Error = "Listenvorlage fehlt"; return v; }
            var templateGo = UiFind.GameObjectOf(template);
            v._rows.Add(template);
            v.Model = new BagScreenModel(pockets);
            for (var i = 1; i < BagScreenModel.VisibleRows; i++)
            {
                var clone = UnityEngine.Object.Instantiate(templateGo, templateGo.transform.parent, false);
                clone.name = templateGo.name + " " + i;
                v._rows.Add(clone.GetComponent<IBagItemView>());
            }
            foreach (var t in UiFind.All<IBagCategoryView>(go))
            {
                v._tabs.Add(t);
                var fresh = UiFind.Child(UiFind.GameObjectOf(t)?.transform, "NewIcon");
                if (fresh != null) fresh.gameObject.SetActive(false);
            }
            // Bereiche, die nur zu Unterseiten gehören (Party zur Item-Verwendung, Mengenwahl, Attackenanzeige, Effekte)
            foreach (var hidden in new[] { "PokeParty", "SelectAmount", "WazaBattle", "WazaContest", "WazaSelectPanel", "EffectRoot" })
            {
                var h = UiFind.Child(go.transform, hidden);
                if (h != null) h.gameObject.SetActive(false);
            }
            UiFind.HideEmptyIcons(go);
            var cursor = UiFind.Child(go.transform, "CursorFrame_02");
            v._cursorFrame = cursor as RectTransform;
            v.Refresh(true);
            return v;
        }

        public void Refresh(bool force = false)
        {
            if (Model == null || _panel == null) return;
            var cur = Model.Cursor;
            if (!force && cur.Top == _shownTop && cur.Index == _shownIndex && Model.PocketIndex == _shownPocket) return;
            _shownTop = cur.Top;
            _shownIndex = cur.Index;
            _shownPocket = Model.PocketIndex;
            var pocket = Model.Pocket;
            UiFind.SetText(_panel.MoneyValue, _money.ToString("N0", System.Globalization.CultureInfo.GetCultureInfo("de-DE")));
            UiFind.SetText(_panel.CategoryName, pocket.Name);
            if (_panel.NoData != null) _panel.NoData.gameObject.SetActive(pocket.Entries.Count == 0);
            for (var i = 0; i < _tabs.Count; i++)
            {
                var tab = _tabs[i];
                if (tab.Image == null) continue;
                var sprite = i == Model.PocketIndex ? tab.SelectSprite : tab.UnselectSprite;
                if (sprite != null) tab.Image.sprite = sprite;
            }
            for (var i = 0; i < _rows.Count; i++)
            {
                var row = _rows[i];
                var rowGo = UiFind.GameObjectOf(row);
                var idx = cur.Top + i;
                if (idx >= pocket.Entries.Count) { rowGo.SetActive(false); continue; }
                rowGo.SetActive(true);
                var e = pocket.Entries[idx];
                UiFind.SetText(row.Name, e.Name);
                UiFind.SetText(row.StockValue, e.Count.ToString());
                if (row.NewIcon != null) row.NewIcon.gameObject.SetActive(false);
                if (row.Favorite != null) row.Favorite.gameObject.SetActive(false);
                if (row.Register != null) row.Register.gameObject.SetActive(false);
                if (row.Icon != null) row.Icon.gameObject.SetActive(false);
            }
            var current = Model.Current;
            var d = _panel.Description;
            if (d != null)
            {
                UiFind.SetText(d.ItemName, current?.Name ?? "");
                UiFind.SetText(d.Description, current?.Description ?? "");
                if (d.ItemIcon != null) d.ItemIcon.gameObject.SetActive(false);
            }
            if (_panel.LeftArrow != null) _panel.LeftArrow.gameObject.SetActive(Model.Pockets.Count > 1);
            if (_panel.RightArrow != null) _panel.RightArrow.gameObject.SetActive(Model.Pockets.Count > 1);
            if (_content != null) LayoutRebuilder.ForceRebuildLayoutImmediate(_content);
            PlaceCursor(cur.Index - cur.Top);
        }

        void PlaceCursor(int visibleIndex)
        {
            if (_cursorFrame == null) return;
            var show = Model.Current != null && visibleIndex >= 0 && visibleIndex < _rows.Count;
            _cursorFrame.gameObject.SetActive(show);
            if (!show) return;
            var row = UiFind.GameObjectOf(_rows[visibleIndex]).transform as RectTransform;
            if (row == null) return;
            _cursorFrame.position = row.position;
            _cursorFrame.sizeDelta = new Vector2(_cursorFrame.sizeDelta.x, row.rect.height);
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }

    // Auswahlfenster (Ja/Nein, Liste) aus dem Original-Kontextmenü: Einträge aus der Vorlage, Pfeil am gewählten Eintrag.
    public sealed class ChoiceView
    {
        public GameObject Root { get; private set; }
        public ChoiceMenuModel Model { get; private set; }
        public string Error { get; private set; }
        readonly List<IContextMenuItemView> _items = new List<IContextMenuItemView>();
        int _shown = -1;

        public static ChoiceView Create(Camera camera, Transform parent, IUiLabelSource labels, IReadOnlyList<string> entries, int cancelIndex)
        {
            var go = OriginalWindowFactory.Create("ui/prefab/contextmenu", camera, UiCanvasFactory.SortingWindow + 100, parent, labels, out _);
            if (go == null) return new ChoiceView { Error = OriginalWindowFactory.LastError };
            return Bind(go, entries, cancelIndex);
        }

        public static ChoiceView Bind(GameObject go, IReadOnlyList<string> entries, int cancelIndex)
        {
            var v = new ChoiceView();
            v.Root = go;
            var menu = UiFind.First<IContextMenuView>(go);
            if (menu?.ItemPrefab == null || menu.ContentRoot == null) { v.Error = "Kontextmenü-Komponenten fehlen (Stubs nicht gebunden?)"; return v; }
            var templateGo = menu.ItemPrefab.Component.gameObject;
            var parentTf = templateGo.transform.parent;
            for (var i = 0; i < entries.Count; i++)
            {
                var itemGo = i == 0 ? templateGo : UnityEngine.Object.Instantiate(templateGo, parentTf, false);
                itemGo.SetActive(true);
                var item = itemGo.GetComponent<IContextMenuItemView>();
                UiFind.SetText(item.Text, entries[i]);
                v._items.Add(item);
            }
            // Box unten rechts über der Meldungsbox (Referenz 1280×720); das Fenster selbst füllt den Bildschirm
            if (menu.ContentRoot != null)
            {
                menu.ContentRoot.anchorMin = menu.ContentRoot.anchorMax = new Vector2(1f, 0f);
                menu.ContentRoot.pivot = new Vector2(1f, 0f);
                menu.ContentRoot.anchoredPosition = new Vector2(-60f, 200f);
            }
            v.Model = new ChoiceMenuModel(entries.Count, cancelIndex);
            v.Refresh(true);
            LayoutRebuilder.ForceRebuildLayoutImmediate(menu.ContentRoot);
            return v;
        }

        public void Refresh(bool force = false)
        {
            if (Model == null || (!force && Model.Cursor == _shown)) return;
            _shown = Model.Cursor;
            for (var i = 0; i < _items.Count; i++)
            {
                var arrow = UiFind.Child(_items[i].Component.transform, "CursorArrow");
                if (arrow != null) arrow.gameObject.SetActive(i == Model.Cursor);
            }
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }

    // Hinweisfenster (Systemdialog aus dem Original-Prefab) mit einem Text; Bestätigen oder Abbrechen schließt.
    public sealed class NoticeView
    {
        public GameObject Root { get; private set; }
        public string Error { get; private set; }

        public static NoticeView Create(Camera camera, Transform parent, IUiLabelSource labels, string text)
        {
            var v = new NoticeView();
            var go = OriginalWindowFactory.Create("ui/prefab/dialog", camera, UiCanvasFactory.SortingWindow + 100, parent, labels, out _);
            if (go == null) { v.Error = OriginalWindowFactory.LastError; return v; }
            v.Root = go;
            var d = UiFind.First<IDialogView>(go);
            if (d?.Text == null) { v.Error = "Dialog-Komponenten fehlen (Stubs nicht gebunden?)"; return v; }
            d.Text.text = text;
            return v;
        }

        public void Destroy()
        {
            if (Root != null) UnityEngine.Object.Destroy(Root);
            Root = null;
        }
    }
}
