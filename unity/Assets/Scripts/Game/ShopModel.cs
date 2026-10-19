using System;
using System.Collections.Generic;
using Xnu.Data;

namespace Xnu.Game
{
    public enum ShopKind
    {
        Friendly,        // DPR_SHOP_OPEN(Zonenname): Freundschaftsladen der Zone, Abzeichen-Staffelung (FS)
        Fixed,           // SHOP_OPEN_FIXED(Nr.)
        Battle,          // SHOP_OPEN_BATTLE(Nr.): BP-Laden (Kampfpunkte)
        Sell,            // SHOP_OPEN_SELL
        Other,           // Aufkleber, Blumen, Wetter, Boutique, Palpark, Tobari: nur Anfrage
    }

    public enum ShopResult
    {
        Ok,
        NoMoney,
        NoSpace,
        NotOffered,
        NotOwned,
        Invalid,
    }

    public sealed class ShopItem
    {
        public int ItemNo;
        public int Price;
    }

    // Laden-Anfrage des Ereignisses (Kauf/Verkauf): Der Kern kennt Angebot, Preise und Abrechnung; die Oberfläche zeigt die Liste und ruft Buy/Sell.
    public sealed class ShopRequest
    {
        public ShopKind Kind;
        public int ShopId;
        public string ZoneName = "";
        public bool IsOpen;
        public readonly List<ShopItem> Items = new List<ShopItem>();
        public int Purchases;
        public int Sales;
    }

    public sealed partial class GameSession
    {
        public ShopRequest Shop { get; private set; }

        // Angebot aus den ShopTables (XLSXContent.ShopTable) [P: Tabelle; A: Zuordnung Zone/Abzeichen und Preis = ItemRecord.Price bzw. BpPrice].
        public ShopRequest OpenShop(ShopKind kind, int shopId = 0, string zoneName = "", int zoneId = -1)
        {
            var shop = new ShopRequest { Kind = kind, ShopId = shopId, ZoneName = zoneName, IsOpen = true };
            var tables = (Data as GameData)?.Shops;
            if (tables != null)
            {
                switch (kind)
                {
                    case ShopKind.Friendly:
                        foreach (var e in tables.FriendlyShop)
                            if ((e.ZoneId < 0 || e.ZoneId == zoneId) && e.BadgeNum <= BadgeCount) AddOffer(shop, e.ItemNo, false);
                        break;
                    case ShopKind.Fixed:
                        foreach (var e in tables.FixedShop)
                            if (e.ShopId == shopId) AddOffer(shop, e.ItemNo, false);
                        break;
                    case ShopKind.Battle:
                        foreach (var e in tables.BpShop)
                            if (e.ShopId == shopId) AddOffer(shop, e.ItemNo, true);
                        break;
                }
            }
            Shop = shop;
            return shop;
        }

        void AddOffer(ShopRequest shop, int itemNo, bool bp)
        {
            var rec = Data.Battle.GetItem(itemNo);
            shop.Items.Add(new ShopItem { ItemNo = itemNo, Price = rec == null ? 0 : bp ? rec.BpPrice : rec.Price });
        }

        public void CloseShop()
        {
            if (Shop != null) Shop.IsOpen = false;
        }

        // Kauf: Geld (bzw. BP im BP-Laden) und Beutelplatz (Obergrenze 999) prüfen, dann abbuchen und einlagern.
        public ShopResult Buy(int itemNo, int count)
        {
            if (Shop == null || !Shop.IsOpen || count <= 0) return ShopResult.Invalid;
            var offer = Shop.Items.Find(i => i.ItemNo == itemNo);
            if (offer == null) return ShopResult.NotOffered;
            var cost = (long)offer.Price * count;
            var bp = Shop.Kind == ShopKind.Battle;
            if (cost > (bp ? World.BattlePoints : Money)) return ShopResult.NoMoney;
            if (!CanAddItem(itemNo, count)) return ShopResult.NoSpace;
            if (bp) World.BattlePoints -= (int)cost; else AddMoney(-(int)cost);
            AddItem(itemNo, count);
            Shop.Purchases++;
            return ShopResult.Ok;
        }

        // Verkauf: der halbe Preis [A: Vorgängerspiele]; Items ohne Preis lassen sich nicht verkaufen.
        public ShopResult Sell(int itemNo, int count)
        {
            if (Shop == null || !Shop.IsOpen || Shop.Kind != ShopKind.Sell || count <= 0) return ShopResult.Invalid;
            if (GetItemCount(itemNo) < count) return ShopResult.NotOwned;
            var rec = Data.Battle.GetItem(itemNo);
            if (rec == null || rec.Price <= 0) return ShopResult.NotOffered;
            SubItem(itemNo, count);
            AddMoney((int)Math.Min(int.MaxValue, (long)(rec.Price / 2) * count));
            Shop.Sales++;
            return ShopResult.Ok;
        }
    }
}
