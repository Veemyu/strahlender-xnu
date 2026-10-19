using System.Collections.Generic;
using NUnit.Framework;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Xnu.Boot;
using Xnu.Game;
using Xnu.Game.Unity;
using Xnu.UI;

namespace Xnu.Tests
{
    // Menülogik und Datenbindung der Original-Fenster (synthetisch: erfundene Daten, eigene Komponenten statt Stubs).
    public sealed class UiScreensTests
    {
        static UiInputState Down() => new UiInputState(false, false, false, false, 1);
        static UiInputState Up() => new UiInputState(false, false, false, false, -1);
        static UiInputState Right() => new UiInputState(false, false, false, false, 0, 1);
        static UiInputState Left() => new UiInputState(false, false, false, false, 0, -1);
        static UiInputState A() => new UiInputState(true, false, true, false);
        static UiInputState B() => new UiInputState(false, true, false, true);
        static UiInputState Plus() => new UiInputState(false, false, false, false, 0, 0, true);

        // ---- ListCursor / GridCursor ----

        [Test]
        public void ListCursorClampsAndScrolls()
        {
            var c = new ListCursor(20, 8);
            Assert.IsFalse(c.Move(-1));
            for (var i = 0; i < 9; i++) c.Move(1);
            Assert.AreEqual(9, c.Index);
            Assert.AreEqual(2, c.Top);
            Assert.IsTrue(c.HasMoreAbove);
            c.Set(100);
            Assert.AreEqual(19, c.Index);
            Assert.AreEqual(12, c.Top);
            Assert.IsFalse(c.HasMoreBelow);
            Assert.AreEqual(8, c.VisibleCount);
        }

        [Test]
        public void ListCursorWrapsAndHandlesEmpty()
        {
            var w = new ListCursor(3, 8, true);
            w.Move(-1);
            Assert.AreEqual(2, w.Index);
            w.Move(1);
            Assert.AreEqual(0, w.Index);
            var e = new ListCursor(0, 4);
            Assert.IsFalse(e.Move(1));
            Assert.AreEqual(0, e.VisibleCount);
            e.SetCount(2);
            Assert.AreEqual(2, e.VisibleCount);
            Assert.Throws<System.ArgumentOutOfRangeException>(() => new ListCursor(1, 0));
        }

        [Test]
        public void ListCursorSetCountClampsIndex()
        {
            var c = new ListCursor(10, 4);
            c.Set(9);
            c.SetCount(3);
            Assert.AreEqual(2, c.Index);
            Assert.AreEqual(0, c.Top);
        }

        [Test]
        public void GridCursorMovesInRowsAndColumns()
        {
            var g = new GridCursor(8, 4);
            Assert.IsTrue(g.Move(1, 0));
            Assert.AreEqual(1, g.Index);
            Assert.IsTrue(g.Move(0, 1));
            Assert.AreEqual(5, g.Index);
            Assert.IsFalse(g.Move(0, 1));
            g.Set(7);
            Assert.IsFalse(g.Move(1, 0));
            Assert.IsTrue(g.Move(-1, 0));
            Assert.AreEqual(6, g.Index);
        }

        [Test]
        public void GridCursorShortLastRowClampsDownMove()
        {
            var g = new GridCursor(6, 4);
            g.Set(3);
            Assert.IsTrue(g.Move(0, 1));
            Assert.AreEqual(5, g.Index);
        }

        // ---- Hauptmenü ----

        static List<MenuEntry> Entries() => new List<MenuEntry>
        {
            new MenuEntry { Id = MenuEntryId.Zukan, Label = "Z", Enabled = false },
            new MenuEntry { Id = MenuEntryId.Party, Label = "P" },
            new MenuEntry { Id = MenuEntryId.Bag, Label = "B" },
        };

        [Test]
        public void MainMenuSkipsDisabledEntries()
        {
            var m = new MainMenuModel(Entries(), 3);
            m.Update(A());
            Assert.AreEqual(MenuEntryId.None, m.Chosen);
            m.Update(Right());
            m.Update(A());
            Assert.AreEqual(MenuEntryId.Party, m.Chosen);
        }

        [Test]
        public void MainMenuCancelClosesAndPlusRequestsReport()
        {
            var m = new MainMenuModel(Entries(), 3);
            m.Update(Plus());
            Assert.IsTrue(m.ReportRequested);
            m.ClearReport();
            Assert.IsFalse(m.ReportRequested);
            m.Update(B());
            Assert.IsTrue(m.IsClosed);
        }

        [Test]
        public void MainMenuResumeAfterChildClearsChoice()
        {
            var m = new MainMenuModel(Entries(), 3);
            m.Update(Right());
            m.Update(A());
            m.ResumeAfterChild();
            Assert.AreEqual(MenuEntryId.None, m.Chosen);
            m.Update(Right());
            m.Update(A());
            Assert.AreEqual(MenuEntryId.Bag, m.Chosen);
        }

        [Test]
        public void MenuLabelsMapToEntryIds()
        {
            Assert.AreEqual(MenuEntryId.Party, MainMenuModel.IdFromLabel("SS_xmenu_27"));
            Assert.AreEqual(MenuEntryId.Bag, MainMenuModel.IdFromLabel("SS_xmenu_30"));
            Assert.AreEqual(MenuEntryId.None, MainMenuModel.IdFromLabel("unbekannt"));
            Assert.IsTrue(MainMenuModel.IsImplemented(MenuEntryId.Report));
            Assert.IsFalse(MainMenuModel.IsImplemented(MenuEntryId.Zukan));
        }

        [Test]
        public void MainMenuRejectsEmptyList() =>
            Assert.Throws<System.ArgumentException>(() => new MainMenuModel(new List<MenuEntry>(), 2));

        // ---- Party ----

        [Test]
        public void HpStagesFollowThresholds()
        {
            Assert.AreEqual(HpStage.Normal, HpStages.Of(50, 100));
            Assert.AreEqual(HpStage.Warning, HpStages.Of(49, 100));
            Assert.AreEqual(HpStage.Danger, HpStages.Of(24, 100));
            Assert.AreEqual(HpStage.Fainted, HpStages.Of(0, 100));
            Assert.AreEqual(0.5f, HpStages.Ratio(50, 100), 1e-6f);
            Assert.AreEqual(0f, HpStages.Ratio(5, 0));
            Assert.AreEqual(1f, HpStages.Ratio(500, 100));
        }

        [Test]
        public void HpBarSpriteIndexUsesPrefabThresholds()
        {
            var ratios = new[] { 0.5f, 0.2f, 0f };
            Assert.AreEqual(0, HpBarBinder.SpriteIndex(ratios, 3, 0.9f, HpStage.Normal));
            Assert.AreEqual(1, HpBarBinder.SpriteIndex(ratios, 3, 0.3f, HpStage.Warning));
            Assert.AreEqual(2, HpBarBinder.SpriteIndex(ratios, 3, 0.1f, HpStage.Danger));
            Assert.AreEqual(2, HpBarBinder.SpriteIndex(ratios, 3, 0f, HpStage.Fainted));
            Assert.AreEqual(1, HpBarBinder.SpriteIndex(null, 3, 0.3f, HpStage.Warning));
        }

        static List<PartyRow> Rows(int n)
        {
            var l = new List<PartyRow>();
            for (var i = 0; i < n; i++) l.Add(new PartyRow { Slot = i, Name = "M" + i, Level = 10 + i, Hp = 20, MaxHp = 40 });
            return l;
        }

        [Test]
        public void PartyScreenNavigatesAndChooses()
        {
            var m = new PartyScreenModel(Rows(3));
            m.Update(Down());
            m.Update(Down());
            m.Update(Down());
            Assert.AreEqual(2, m.Cursor.Index);
            m.Update(A());
            Assert.AreEqual(2, m.Chosen);
            m.ResumeAfterChoice();
            Assert.AreEqual(-1, m.Chosen);
            m.Update(B());
            Assert.IsTrue(m.IsClosed);
            Assert.AreEqual(HpStage.Normal, m.Rows[0].Stage);
        }

        [Test]
        public void PartyScreenEmptyDoesNotChoose()
        {
            var m = new PartyScreenModel(new List<PartyRow>());
            m.Update(A());
            Assert.AreEqual(-1, m.Chosen);
            Assert.IsNull(m.Current);
        }

        // ---- Beutel ----

        static List<BagPocket> Pockets()
        {
            var p0 = new BagPocket { Name = "P0" };
            for (var i = 0; i < 12; i++) p0.Entries.Add(new BagEntry { ItemNo = i + 1, Name = "I" + i, Count = i + 1 });
            var p1 = new BagPocket { Name = "P1" };
            var p2 = new BagPocket { Name = "P2" };
            p2.Entries.Add(new BagEntry { ItemNo = 99, Name = "X", Count = 1 });
            return new List<BagPocket> { p0, p1, p2 };
        }

        [Test]
        public void BagScreenSwitchesPocketsWithWrapAndResetsCursor()
        {
            var m = new BagScreenModel(Pockets());
            m.Update(Down());
            m.Update(Down());
            Assert.AreEqual(2, m.Cursor.Index);
            m.Update(Right());
            Assert.AreEqual(1, m.PocketIndex);
            Assert.AreEqual(0, m.Cursor.Index);
            Assert.IsNull(m.Current);
            m.Update(Left());
            m.Update(Left());
            Assert.AreEqual(2, m.PocketIndex);
            Assert.AreEqual("X", m.Current.Name);
        }

        [Test]
        public void BagScreenScrollsLongList()
        {
            var m = new BagScreenModel(Pockets());
            for (var i = 0; i < 10; i++) m.Update(Down());
            Assert.AreEqual(10, m.Cursor.Index);
            Assert.AreEqual(3, m.Cursor.Top);
            m.Update(A());
            Assert.AreEqual("I10", m.Chosen.Name);
            m.ResumeAfterChoice();
            m.Update(B());
            Assert.IsTrue(m.IsClosed);
        }

        [Test]
        public void BagScreenEmptyPocketCannotChoose()
        {
            var m = new BagScreenModel(Pockets());
            m.Update(Right());
            m.Update(A());
            Assert.IsNull(m.Chosen);
        }

        // ---- Bundle-Filter ----

        [Test]
        public void BundleFilterExcludesShadersAndForeignLanguages()
        {
            Assert.IsTrue(UiBundles.IsExcluded(new BundleRecord { Project = "Shaders", Name = "shaders" }));
            Assert.IsTrue(UiBundles.IsExcluded(new BundleRecord { Project = "UIs", Name = "x/common_lang.en" }));
            Assert.IsFalse(UiBundles.IsExcluded(new BundleRecord { Project = "UIs", Name = "x/common_lang.ge" }));
            Assert.IsFalse(UiBundles.IsExcluded(new BundleRecord { Project = "UIs", Name = "ui/uiresidentwindow" }));
            Assert.IsTrue(UiBundles.IsExcluded(new BundleRecord { Project = "UIs", Name = "foo", AssetPaths = new[] { "assets/a/b.shader" } }));
        }

        // ---- Textbindung und Materialien (eigene Komponenten statt Stubs) ----

        sealed class FakeLabels : IUiNumberLabelSource
        {
            public string Label(string msbt, string label) => msbt == "f" && label == "L1" ? "Text {2:2}" : null;
            public string Label(string msbt, string label, long number) => msbt == "f" && label == "LV" ? "Lv. " + number : null;
        }

        sealed class FakeText : MonoBehaviour, IUiText
        {
            public string File, Id;
            public bool Use = true;
            public TMP_Text Text => GetComponent<TMP_Text>();
            public bool UseMessage => Use;
            public string MessageFile => File;
            public string MessageId => Id;
        }

        static FakeText MakeText(Transform parent, string file, string id)
        {
            var go = new GameObject("t", typeof(RectTransform), typeof(TextMeshProUGUI));
            go.transform.SetParent(parent, false);
            var t = go.AddComponent<FakeText>();
            t.File = file;
            t.Id = id;
            return t;
        }

        [Test]
        public void TextBinderFillsLabelsAndBlanksPlaceholders()
        {
            var root = new GameObject("root");
            try
            {
                var a = MakeText(root.transform, "f", "L1");
                var b = MakeText(root.transform, "f", "fehlt");
                var c = MakeText(root.transform, "", "");
                var n = UiTextBinder.Apply(root, new FakeLabels(), out var missing);
                Assert.AreEqual(1, n);
                Assert.AreEqual(1, missing);
                Assert.AreEqual("Text ", a.Text.text);
                Assert.IsTrue(string.IsNullOrEmpty(c.Text.text));
            }
            finally { Object.DestroyImmediate(root); }
        }

        [Test]
        public void HideEmptyIconsOnlyTouchesIconImagesWithoutSprite()
        {
            var root = new GameObject("root", typeof(RectTransform));
            try
            {
                Image Make(string name)
                {
                    var g = new GameObject(name, typeof(RectTransform), typeof(Image));
                    g.transform.SetParent(root.transform, false);
                    return g.GetComponent<Image>();
                }
                var icon = Make("IconImage");
                var plain = Make("Background");
                Assert.AreEqual(1, UiFind.HideEmptyIcons(root));
                Assert.IsFalse(icon.enabled);
                Assert.IsTrue(plain.enabled);
            }
            finally { Object.DestroyImmediate(root); }
        }

        // ---- Datenbindung aus dem Spielstand ----

        [Test]
        public void GameUiDataBuildsPartyRowsAndBagPockets()
        {
            var save = GameFixture.NewSave(partyLevel: 22, money: 777);
            var session = new GameSession(save, GameFixture.Data(), 1);
            session.AddItem(17, 3);
            var data = new GameUiData(session);
            Assert.AreEqual(777, data.Money);

            var rows = data.PartyRows();
            Assert.AreEqual(1, rows.Count);
            Assert.AreEqual(22, rows[0].Level);
            Assert.AreEqual(rows[0].Hp > 0 ? 1 : 0, rows[0].HpRatio > 0f ? 1 : 0);

            var pockets = data.BagPockets();
            Assert.AreEqual(GameUiData.PocketOrder.Length, pockets.Count);
            Assert.AreEqual(1, pockets[0].Entries.Count);
            Assert.AreEqual("Trank", pockets[0].Entries[0].Name);
            Assert.AreEqual(3, pockets[0].Entries[0].Count);
            Assert.AreEqual("Trank", data.ItemName(17));
        }

        [Test]
        public void GameUiDataNumberLabelReturnsNullForUnknownLabel()
        {
            var session = new GameSession(GameFixture.NewSave(), GameFixture.Data(), 1);
            var data = new GameUiData(session);
            Assert.IsNull(data.Label("ss_itemname", "NICHT_DA"));
            Assert.IsNull(data.Label("ss_itemname", "NICHT_DA", 5));
            Assert.AreEqual("Trank", data.Label("ss_itemname", "ITEMNAME_017"));
        }

        [Test]
        public void ManagerWithoutDataStaysClosed()
        {
            var go = new GameObject("wm");
            try
            {
                var wm = go.AddComponent<UiWindowManager>();
                wm.Configure(null, null);
                Assert.IsFalse(wm.OpenMainMenu(null));
                Assert.IsFalse(wm.IsOpen);
                Assert.IsTrue(wm.IsAvailable);
                wm.Tick(Down());
            }
            finally { Object.DestroyImmediate(go); }
        }
    }
}
