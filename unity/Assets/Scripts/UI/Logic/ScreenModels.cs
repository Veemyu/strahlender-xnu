using System;
using System.Collections.Generic;

namespace Xnu.UI
{
    // Menüeinträge der ersten Menüebene (Reihenfolge und Zuordnung stammen aus dem Original-Prefab, die Kennung aus dem Textlabel des Eintrags).
    public enum MenuEntryId { None, Zukan, Party, Bag, Card, Map, Seal, Setting, Gift, Report }

    public sealed class MenuEntry
    {
        public MenuEntryId Id;
        public string Label = "";
        public bool Enabled = true;
    }

    // Hauptmenü: Raster-Cursor über die Einträge, Ergebnis = gewählter Eintrag oder Schließen.
    public sealed class MainMenuModel
    {
        public IReadOnlyList<MenuEntry> Entries { get; }
        public GridCursor Cursor { get; }
        public bool IsClosed { get; private set; }
        public MenuEntryId Chosen { get; private set; } = MenuEntryId.None;
        // Plus im offenen Menü: Bericht (Speichern) anfordern.
        public bool ReportRequested { get; private set; }

        public MainMenuModel(IReadOnlyList<MenuEntry> entries, int columns)
        {
            if (entries == null || entries.Count == 0) throw new ArgumentException("keine Einträge", nameof(entries));
            Entries = entries;
            Cursor = new GridCursor(entries.Count, columns);
        }

        public MenuEntry Current => Entries[Cursor.Index];

        // Ein Bild Eingabe. Gewählt wird nur ein aktivierter Eintrag; Abbrechen schließt das Menü.
        public void Update(UiInputState input)
        {
            if (IsClosed || Chosen != MenuEntryId.None) return;
            if (input.MoveX != 0 || input.MoveY != 0) Cursor.Move(input.MoveX, input.MoveY);
            if (input.ConfirmPressed && Current.Enabled) Chosen = Current.Id;
            else if (input.CancelPressed) IsClosed = true;
            else if (input.MenuPressed) ReportRequested = true;
        }

        // Nach der Rückkehr aus einer Unterseite: Auswahl und Bericht-Anfrage zurücknehmen.
        public void ResumeAfterChild()
        {
            Chosen = MenuEntryId.None;
            ReportRequested = false;
        }

        public void ClearReport() => ReportRequested = false;

        // Bildet das Textlabel eines Eintrags (z. B. "SS_xmenu_28") auf die Kennung ab. Die Nummern sind die der Original-Prefabs.
        public static MenuEntryId IdFromLabel(string label)
        {
            switch (label)
            {
                case "SS_xmenu_28": return MenuEntryId.Zukan;
                case "SS_xmenu_27": return MenuEntryId.Party;
                case "SS_xmenu_30": return MenuEntryId.Bag;
                case "SS_xmenu_47": return MenuEntryId.Card;
                case "SS_xmenu_31": return MenuEntryId.Map;
                case "SS_xmenu_48": return MenuEntryId.Seal;
                case "SS_xmenu_38": return MenuEntryId.Setting;
                case "SS_xmenu_40": return MenuEntryId.Gift;
                case "SS_xmenu_29": return MenuEntryId.Report;
                default: return MenuEntryId.None;
            }
        }

        // Nur Party, Beutel und Bericht sind in dieser Scheibe belegt; die übrigen zeigen den Rahmen.
        public static bool IsImplemented(MenuEntryId id) => id == MenuEntryId.Party || id == MenuEntryId.Bag || id == MenuEntryId.Report;
    }

    public enum HpStage { Normal, Warning, Danger, Fainted }

    public static class HpStages
    {
        // Schwellen des Originals: unter 50 % Warnung, unter 25 % Gefahr, 0 = besiegt (docs/ui-spezifikation-1.md 3.6).
        public static HpStage Of(int hp, int maxHp)
        {
            if (hp <= 0) return HpStage.Fainted;
            if (maxHp <= 0) return HpStage.Normal;
            var r = (float)hp / maxHp;
            if (r < 0.25f) return HpStage.Danger;
            if (r < 0.5f) return HpStage.Warning;
            return HpStage.Normal;
        }

        public static float Ratio(int hp, int maxHp) => maxHp <= 0 ? 0f : Math.Max(0f, Math.Min(1f, (float)hp / maxHp));
    }

    // Eine Zeile der Party (Daten aus dem Spielstand, Namen aus den lokalen Textdateien).
    public sealed class PartyRow
    {
        public int Slot;
        public int MonsNo;
        public int Form;
        public string Name = "";
        public int Level;
        public int Hp;
        public int MaxHp;
        // 0 = männlich, 1 = weiblich, 2 = ohne
        public int Gender;
        public string ItemName = "";
        public bool IsEgg;
        public string Status = "";

        public HpStage Stage => HpStages.Of(Hp, MaxHp);
        public float HpRatio => HpStages.Ratio(Hp, MaxHp);
    }

    public sealed class PartyScreenModel
    {
        public IReadOnlyList<PartyRow> Rows { get; }
        public ListCursor Cursor { get; }
        public bool IsClosed { get; private set; }
        public int Chosen { get; private set; } = -1;

        public PartyScreenModel(IReadOnlyList<PartyRow> rows)
        {
            Rows = rows ?? throw new ArgumentNullException(nameof(rows));
            Cursor = new ListCursor(rows.Count, 6, false);
        }

        public PartyRow Current => Rows.Count == 0 ? null : Rows[Cursor.Index];

        public void Update(UiInputState input)
        {
            if (IsClosed || Chosen >= 0) return;
            if (input.MoveY != 0) Cursor.Move(input.MoveY);
            if (input.ConfirmPressed && Rows.Count > 0) Chosen = Cursor.Index;
            else if (input.CancelPressed) IsClosed = true;
        }

        public void ResumeAfterChoice() => Chosen = -1;
    }

    public sealed class BagEntry
    {
        public int ItemNo;
        public string Name = "";
        public int Count;
        public string Description = "";
    }

    public sealed class BagPocket
    {
        public int PocketId;
        public string Name = "";
        public readonly List<BagEntry> Entries = new List<BagEntry>();
    }

    // Beutel: Taschen (L/R oder links/rechts), Liste mit sichtbarem Ausschnitt, Auswahl eines Eintrags.
    public sealed class BagScreenModel
    {
        public const int VisibleRows = 8;

        public IReadOnlyList<BagPocket> Pockets { get; }
        public int PocketIndex { get; private set; }
        public ListCursor Cursor { get; }
        public bool IsClosed { get; private set; }
        public BagEntry Chosen { get; private set; }

        public BagScreenModel(IReadOnlyList<BagPocket> pockets, int visibleRows = VisibleRows)
        {
            if (pockets == null || pockets.Count == 0) throw new ArgumentException("keine Taschen", nameof(pockets));
            Pockets = pockets;
            Cursor = new ListCursor(pockets[0].Entries.Count, visibleRows, false);
        }

        public BagPocket Pocket => Pockets[PocketIndex];
        public BagEntry Current => Pocket.Entries.Count == 0 ? null : Pocket.Entries[Cursor.Index];

        public void SetPocket(int index)
        {
            PocketIndex = ((index % Pockets.Count) + Pockets.Count) % Pockets.Count;
            Cursor.Reset();
            Cursor.SetCount(Pocket.Entries.Count);
        }

        public void Update(UiInputState input)
        {
            if (IsClosed || Chosen != null) return;
            if (input.MoveX != 0) SetPocket(PocketIndex + input.MoveX);
            if (input.MoveY != 0) Cursor.Move(input.MoveY);
            if (input.ConfirmPressed && Current != null) Chosen = Current;
            else if (input.CancelPressed) IsClosed = true;
        }

        public void ResumeAfterChoice() => Chosen = null;
    }
}
