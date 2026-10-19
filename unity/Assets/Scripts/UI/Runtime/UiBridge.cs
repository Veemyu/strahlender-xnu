using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Xnu.UI
{
    // Brücke zu den generierten Stub-Klassen (Assembly-CSharp, docs/stubs-1.md Abschnitt 5.3, Variante A):
    // Die Logik in Xnu.UI kennt nur diese Schnittstellen. Handgeschriebene partial-Teile der Stubs
    // (Assets/Scripts/DprHooks, nur mit XNU_STUBS) implementieren sie und reichen die serialisierten Felder durch.
    // Ohne Stubs bleiben die Original-Prefabs unbenutzbar; die Aufrufer fallen dann auf die eigenen Fenster zurück.

    // Textfeld mit Verweis auf eine Textdatei und ein Label (statische Beschriftung).
    public interface IUiText
    {
        TMP_Text Text { get; }
        bool UseMessage { get; }
        string MessageFile { get; }
        string MessageId { get; }
    }

    public interface IXMenuView
    {
        RectTransform ItemRoot { get; }
        RectTransform ReportRoot { get; }
        RectTransform GuideRoot { get; }
        RectTransform GotoMapRoot { get; }
        RectTransform SafariRoot { get; }
    }

    public interface IXMenuItemView
    {
        RectTransform Root { get; }
        Image Icon { get; }
        Image NewIcon { get; }
        IUiText NameText { get; }
        Sprite[] SpriteIcons { get; }
    }

    public interface IHpBarView
    {
        Slider Slider { get; }
        Image Body { get; }
        Sprite[] BodySprites { get; }
        float[] SwitchRatios { get; }
    }

    public interface IPartyView
    {
        RectTransform ContentRoot { get; }
    }

    public interface IPartyItemView
    {
        RectTransform Root { get; }
        TMP_Text Name { get; }
        TMP_Text Hp { get; }
        TMP_Text MaxHp { get; }
        TMP_Text Level { get; }
        IHpBarView HpBar { get; }
        Image Gender { get; }
        RectTransform ItemRoot { get; }
        Image MonsIcon { get; }
        Image HeldItemIcon { get; }
    }

    public interface IBagView
    {
        IBagPanelView Panel { get; }
    }

    public interface IBagPanelView
    {
        TMP_Text MoneyValue { get; }
        TMP_Text CategoryName { get; }
        TMP_Text NoData { get; }
        ScrollRect ListScroll { get; }
        IItemDescriptionView Description { get; }
        RectTransform LeftArrow { get; }
        RectTransform RightArrow { get; }
    }

    public interface IItemDescriptionView
    {
        Image ItemIcon { get; }
        TMP_Text ItemName { get; }
        TMP_Text Description { get; }
    }

    public interface IBagItemView
    {
        Image Icon { get; }
        TMP_Text Name { get; }
        Image NewIcon { get; }
        Image Favorite { get; }
        TMP_Text StockLabel { get; }
        TMP_Text StockValue { get; }
        Image Register { get; }
    }

    public interface IBagCategoryView
    {
        Image Image { get; }
        Sprite SelectSprite { get; }
        Sprite UnselectSprite { get; }
    }

    public interface IContextMenuView
    {
        RectTransform WindowRoot { get; }
        RectTransform ContentRoot { get; }
        IContextMenuItemView ItemPrefab { get; }
    }

    public interface IContextMenuItemView
    {
        TMP_Text Text { get; }
        Component Component { get; }
    }

    public interface IDialogView
    {
        TMP_Text Text { get; }
    }

    // Kampf-UI (Prefab battleviewuisystem)
    public interface IBtlStatusView
    {
        Component Component { get; }
        TMP_Text Name { get; }
        TMP_Text LevelValue { get; }
        TMP_Text Hp { get; }
        Image Gender { get; }
        IHpBarView HpBar { get; }
        Slider Exp { get; }
        GameObject BallBar { get; }
        GameObject Condition { get; }
    }

    public interface IBtlButtonView
    {
        Component Component { get; }
        Image Background { get; }
        TMP_Text Text { get; }
    }

    public interface IBtlActionButtonView : IBtlButtonView
    {
        Image LightFrame { get; }
        int ButtonType { get; }
    }

    public interface IBtlWazaButtonView : IBtlButtonView
    {
        TMP_Text Pp { get; }
        TMP_Text MaxPp { get; }
        GameObject EffectiveRoot { get; }
    }

    public interface IBtlWazaListView
    {
        Component Component { get; }
        IBtlWazaButtonView[] Buttons { get; }
        Sprite[] TypeSprites { get; }
        Color TextColor { get; }
    }

    public interface IBtlActionListView
    {
        Component Component { get; }
        IBtlActionButtonView[] Buttons { get; }
        GameObject XyFrame { get; }
    }

    public interface IBtlSystemView
    {
        IBtlStatusView[] StatusWindows { get; }
        IBtlActionListView ActionList { get; }
        IBtlWazaListView WazaList { get; }
    }
}
