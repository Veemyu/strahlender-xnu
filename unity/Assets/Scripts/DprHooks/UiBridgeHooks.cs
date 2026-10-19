// Handgeschriebene partial-Teile der generierten Stub-Klassen (Assembly-CSharp, ohne asmdef).
// Nur mit XNU_STUBS (csc.rsp, von der Build-Stufe `stubs` geschrieben): ohne Stubs existieren die Klassen nicht.
// Dünne Durchreicher: sie implementieren die Schnittstellen aus Xnu.UI (UiBridge.cs) und enthalten keine Logik.
#if XNU_STUBS
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Xnu.UI;

namespace Dpr.UI
{
    public partial class UIText : IUiText
    {
        TMP_Text IUiText.Text => this;
        bool IUiText.UseMessage => _useMessage;
        string IUiText.MessageFile => _messageFile;
        string IUiText.MessageId => _messageId;
    }

    public partial class XMenuTop : IXMenuView
    {
        RectTransform IXMenuView.ItemRoot => _itemRoot;
        RectTransform IXMenuView.ReportRoot => _reportWindow;
        RectTransform IXMenuView.GuideRoot => _messageWindowRoot;
        RectTransform IXMenuView.GotoMapRoot => _gotoTownMapRoot;
        RectTransform IXMenuView.SafariRoot => _safariRoot;
    }

    public partial class HpBar : IHpBarView
    {
        Slider IHpBarView.Slider => barSlider;
        Image IHpBarView.Body => bodyImage;
        Sprite[] IHpBarView.BodySprites => bodySprites;
        float[] IHpBarView.SwitchRatios => switchSpriteRatioValues;
    }

    public partial class PokemonParty : IPartyView
    {
        RectTransform IPartyView.ContentRoot => _contentRoot;
    }

    public partial class PokemonPartyItem : IPartyItemView
    {
        RectTransform IPartyItemView.Root => _root;
        TMP_Text IPartyItemView.Name => _name;
        TMP_Text IPartyItemView.Hp => _hp;
        TMP_Text IPartyItemView.MaxHp => _maxHp;
        TMP_Text IPartyItemView.Level => _level;
        IHpBarView IPartyItemView.HpBar => _hpBar;
        Image IPartyItemView.Gender => _sex;
        RectTransform IPartyItemView.ItemRoot => _itemRoot;
        Image IPartyItemView.MonsIcon => _pokemonIcon != null ? ((IPokemonIconParts)_pokemonIcon).Mons : null;
        Image IPartyItemView.HeldItemIcon => _pokemonIcon != null ? ((IPokemonIconParts)_pokemonIcon).Item : null;
    }

    interface IPokemonIconParts
    {
        Image Mons { get; }
        Image Item { get; }
    }

    public partial class PokemonIcon : IPokemonIconParts
    {
        Image IPokemonIconParts.Mons => _imageMonsIcon;
        Image IPokemonIconParts.Item => _imageItemIcon;
    }

    public partial class UIBag : IBagView
    {
        IBagPanelView IBagView.Panel => bagItemPanel;
    }

    public partial class BagItemPanel : IBagPanelView
    {
        TMP_Text IBagPanelView.MoneyValue => moneyValueText;
        TMP_Text IBagPanelView.CategoryName => categoryNameText;
        TMP_Text IBagPanelView.NoData => noDataText;
        ScrollRect IBagPanelView.ListScroll => itemListScrollView != null ? ((IScrollParts)itemListScrollView).Rect : null;
        IItemDescriptionView IBagPanelView.Description => bagItemDescriptionPanel;
        RectTransform IBagPanelView.LeftArrow => categoryLeftArrowRectTransform;
        RectTransform IBagPanelView.RightArrow => categoryRightArrowRectTransform;
    }

    interface IScrollParts
    {
        ScrollRect Rect { get; }
    }

    public partial class UIScrollView : IScrollParts
    {
        ScrollRect IScrollParts.Rect => scrollRect;
    }

    public partial class ItemDescriptionPanel : IItemDescriptionView
    {
        Image IItemDescriptionView.ItemIcon => itemIconImage;
        TMP_Text IItemDescriptionView.ItemName => itemNameText;
        TMP_Text IItemDescriptionView.Description => descriptionText;
    }

    public partial class BagItemButton : IBagItemView
    {
        Image IBagItemView.Icon => iconImage;
        TMP_Text IBagItemView.Name => nameText;
        Image IBagItemView.NewIcon => newIconImage;
        Image IBagItemView.Favorite => favoriteIconImage;
        TMP_Text IBagItemView.StockLabel => stockCountLabelText;
        TMP_Text IBagItemView.StockValue => stockCountValueText;
        Image IBagItemView.Register => registerButtonImage;
    }

    public partial class UISwitchImageButton : IBagCategoryView
    {
        Image IBagCategoryView.Image => image;
        Sprite IBagCategoryView.SelectSprite => selectSprite;
        Sprite IBagCategoryView.UnselectSprite => unSelectSprite;
    }

    public partial class ContextMenuWindow : IContextMenuView
    {
        RectTransform IContextMenuView.WindowRoot => _windowRoot;
        RectTransform IContextMenuView.ContentRoot => _contentRoot;
        IContextMenuItemView IContextMenuView.ItemPrefab => _itemPrefab;
    }

    public partial class ContextMenuItem : IContextMenuItemView
    {
        TMP_Text IContextMenuItemView.Text => _text;
        Component IContextMenuItemView.Component => this;
    }

    public partial class DialogWindow : IDialogView
    {
        TMP_Text IDialogView.Text => dialogText;
    }
}

public partial class XMenuTopItem : IXMenuItemView
{
    RectTransform IXMenuItemView.Root => _root;
    Image IXMenuItemView.Icon => _icon;
    Image IXMenuItemView.NewIcon => _newIcon;
    IUiText IXMenuItemView.NameText => _name;
    Sprite[] IXMenuItemView.SpriteIcons => _spriteIcons;
}

namespace Dpr.Battle.View.UI
{
    public partial class BUIStatusWindow : IBtlStatusView
    {
        Component IBtlStatusView.Component => this;
        TMP_Text IBtlStatusView.Name => _nameText;
        TMP_Text IBtlStatusView.LevelValue => _lvValueText;
        TMP_Text IBtlStatusView.Hp => _hpText;
        Image IBtlStatusView.Gender => _sexImage;
        IHpBarView IBtlStatusView.HpBar => _hpBar;
        Slider IBtlStatusView.Exp => _expSlider;
        GameObject IBtlStatusView.BallBar => _ballBar;
        GameObject IBtlStatusView.Condition => _condPanel != null ? _condPanel.gameObject : null;
    }

    public abstract partial class BUIButtonBase<T> : IBtlButtonView
    {
        Component IBtlButtonView.Component => this;
        Image IBtlButtonView.Background => _backgroundImage;
        TMP_Text IBtlButtonView.Text => _text;
    }

    public partial class BUIActionSelectButton : IBtlActionButtonView
    {
        Image IBtlActionButtonView.LightFrame => _lightFrame;
        int IBtlActionButtonView.ButtonType => (int)_buttonType;
    }

    public partial class BUIWazaButton : IBtlWazaButtonView
    {
        TMP_Text IBtlWazaButtonView.Pp => _ppText;
        TMP_Text IBtlWazaButtonView.MaxPp => _maxPpText;
        GameObject IBtlWazaButtonView.EffectiveRoot => _effectiveObj;
    }

    public partial class BUIWazaList : IBtlWazaListView
    {
        Component IBtlWazaListView.Component => this;
        IBtlWazaButtonView[] IBtlWazaListView.Buttons => System.Array.ConvertAll(_wazaButtons, b => (IBtlWazaButtonView)b);
        Sprite[] IBtlWazaListView.TypeSprites => _wazaTypeSprites;
        Color IBtlWazaListView.TextColor => _wazaTextColor;
    }

    public partial class BUIActionList : IBtlActionListView
    {
        Component IBtlActionListView.Component => this;
        IBtlActionButtonView[] IBtlActionListView.Buttons => _actionButtons.ConvertAll(b => (IBtlActionButtonView)b).ToArray();
        GameObject IBtlActionListView.XyFrame => _xyButtonFrame;
    }
}

namespace Dpr.Battle.View.Systems
{
    public partial class BattleViewUISystem : IBtlSystemView
    {
        IBtlStatusView[] IBtlSystemView.StatusWindows => System.Array.ConvertAll(_statusWindows, w => (IBtlStatusView)w);
        IBtlActionListView IBtlSystemView.ActionList => _actionList;
        IBtlWazaListView IBtlSystemView.WazaList => _wazaList;
    }
}
#endif
