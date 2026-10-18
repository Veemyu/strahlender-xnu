using System.Collections.Generic;

namespace Xnu.Battle.Events
{
    // Liefert die Handler-Tabelle eines Tokusei/Items (HandlerGetFunc); prio darf die Hauptprioritaet aendern (nur Tokusei).
    public delegate EventHandlerTable[] HandlerGetFunc(ref EventPriority priority);

    // Fahigkeits-Handler (Handler.Tokusei, Spezifikation Abschnitt 5.1). Registriert ist ein Minimalsatz als Beweis des
    // Konzepts; die uebrigen 218 Tokusei-Handlerklassen des Originals folgen nach demselben Muster.
    public static class TokuseiHandlers
    {
        // TokuseiNo-Werte des Originals.
        public const ushort Fukugan = 14;       // Facettenauge: Genauigkeit x1,3
        public const ushort Tikaramoti = 37;    // Kraftkoloss: physischer Angriff x2
        public const ushort AtuiSibou = 47;     // Dickes Fell: Feuer/Eis gegen den Traeger halbiert
        public const ushort Tekunisyan = 101;   // Techniker: Attacken bis Kraft 60 x1,5

        static readonly Dictionary<ushort, HandlerGetFunc> Funcs = new Dictionary<ushort, HandlerGetFunc>
        {
            { Fukugan, (ref EventPriority p) => new[] { new EventHandlerTable(EventId.WAZA_HIT_RATIO, HandlerFukugan) } },
            { Tikaramoti, (ref EventPriority p) => new[] { new EventHandlerTable(EventId.ATTACKER_POWER, HandlerTikaramoti) } },
            { AtuiSibou, (ref EventPriority p) => new[] { new EventHandlerTable(EventId.ATTACKER_POWER, HandlerAtuiSibou) } },
            { Tekunisyan, (ref EventPriority p) => new[] { new EventHandlerTable(EventId.WAZA_POWER, HandlerTekunisyan) } },
        };

        public static HandlerGetFunc GetHandlerGetFunc(ushort tokusei) => Funcs.TryGetValue(tokusei, out var f) ? f : null;

        public static bool IsImplemented(ushort tokusei) => Funcs.ContainsKey(tokusei);

        // Tokusei.Add: Faktor TOKUSEI mit subID = Tokusei-Nr., Unterprioritaet = Initiative ohne Stufen, dependID = Pokemon-ID.
        public static EventFactor Add(EventSystem es, BattlePoke bpp)
        {
            ushort tokusei = (ushort)bpp.GetValue(PokeValueId.TOKUSEI);
            var func = GetHandlerGetFunc(tokusei);
            if (func == null) return null;
            var priority = EventPriority.TOKUSEI;
            var table = func(ref priority);
            if (table == null) return null;
            return es.AddFactor(EventFactorType.TOKUSEI, tokusei, priority, (ushort)bpp.GetValueBase(PokeValueId.AGILITY), bpp.Id, table, (byte)table.Length);
        }

        // Tokusei.Remove: entfernt die Faktoren des Pokemon, solange Arbeitswert 4 gleich 0 ist.
        public static void Remove(EventSystem es, BattlePoke bpp)
        {
            var container = es.Container;
            var f = container.SeekFactor(EventFactorType.TOKUSEI, bpp.Id);
            while (f != null && f.GetWorkValue(4) == 0)
            {
                es.RemoveFactor(f);
                f = container.SeekFactor(EventFactorType.TOKUSEI, bpp.Id);
            }
        }

        // Tokusei.Swap: beide Pokemon verlieren ihre Fahigkeits-Faktoren und bekommen sie neu.
        public static void Swap(EventSystem es, BattlePoke a, BattlePoke b)
        {
            var fa = es.Container.SeekFactor(EventFactorType.TOKUSEI, a.Id);
            var fb = es.Container.SeekFactor(EventFactorType.TOKUSEI, b.Id);
            if (fa != null) es.RemoveFactor(fa);
            if (fb != null) es.RemoveFactor(fb);
            Add(es, a);
            Add(es, b);
        }

        // handler_Tikaramoti @0x1a3f7b0: Angreifer bin ich und die Attacke ist physisch (Schadensart 1) -> Verhaeltnis x2.
        static void HandlerTikaramoti(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            if (args.GetVar(EventVarLabel.DAMAGE_TYPE) == 1) args.MulVar(EventVarLabel.RATIO, 0x2000);
        }

        // handler_AtuiSibou @0x1a3f640: Verteidiger bin ich und der Attackentyp ist Feuer (9) oder Eis (14) -> Verhaeltnis x0,5.
        static void HandlerAtuiSibou(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_DEF) != pokeId) return;
            int type = args.GetVar(EventVarLabel.WAZA_TYPE) & 0xFF;
            if (type == 14 || type == 9) args.MulVar(EventVarLabel.RATIO, 0x800);
        }

        // handler_Fukugan @0x1a40a00: Angreifer bin ich -> Genauigkeitsverhaeltnis x0x14CD (ca. 1,3).
        static void HandlerFukugan(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) == pokeId) args.MulVar(EventVarLabel.RATIO, 0x14CD);
        }

        // handler_Technician @0x1a43500: Angreifer bin ich und die Kraft liegt unter 61 -> Kraftverhaeltnis x1,5.
        static void HandlerTekunisyan(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            if ((uint)args.GetVar(EventVarLabel.WAZA_POWER) < 0x3D) args.MulVar(EventVarLabel.WAZA_POWER_RATIO, 0x1800);
        }
    }

    // Item-Handler (Handler.Item, Spezifikation Abschnitt 5.2). Minimalsatz; die Sperr-Logik der Kodawari-Items und der
    // Rueckstoss des Lebensorbs (weitere Tabelleneintraege) sind noch nicht umgesetzt.
    public static class ItemHandlers
    {
        // ItemNo-Werte des Originals.
        public const ushort KodawariHachimaki = 220;  // Wahlband: physischer Angriff x1,5
        public const ushort KoukakuLens = 265;        // Weitwinkellinse: Genauigkeit gemaess Item-Wert
        public const ushort MonosiriMegane = 267;     // Wise-Glasses-Item: spezielle Kraft gemaess Item-Wert
        public const ushort TatuzinNoObi = 268;       // Expertengurt: Schaden bei Wirkung > normal gemaess Item-Wert
        public const ushort InotiNoTama = 270;        // Lebensorb: Schaden gemaess Item-Wert (ohne Rueckstoss)

        delegate EventHandlerTable[] ItemGetFunc();

        static readonly Dictionary<ushort, ItemGetFunc> Funcs = new Dictionary<ushort, ItemGetFunc>
        {
            { KodawariHachimaki, () => new[] { new EventHandlerTable(EventId.ATTACKER_POWER, HandlerKodawariHachimakiPow) } },
            { KoukakuLens, () => new[] { new EventHandlerTable(EventId.WAZA_HIT_RATIO, HandlerKoukakuLens) } },
            { MonosiriMegane, () => new[] { new EventHandlerTable(EventId.WAZA_POWER, HandlerMonosiriMegane) } },
            { TatuzinNoObi, () => new[] { new EventHandlerTable(EventId.WAZA_DMG_PROC3, HandlerTatuzinNoObi) } },
            { InotiNoTama, () => new[] { new EventHandlerTable(EventId.WAZA_DMG_PROC3, HandlerInotiNoTamaDamage) } },
        };

        public static bool IsImplemented(ushort item) => Funcs.ContainsKey(item);

        // Handler-Tabelle eines Items; null, wenn fuer das Item (noch) kein Handler vorhanden ist.
        public static EventHandlerTable[] GetTable(ushort item) => Funcs.TryGetValue(item, out var func) ? func() : null;

        // Item.addHandler: Faktor ITEM, Hauptprioritaet ITEM, Unterprioritaet = Initiative ohne Stufen; die Ereignisstufe
        // setzt der Container (aktuelle Aufruftiefe).
        public static EventFactor AddHandler(EventSystem es, BattlePoke bpp, ushort itemNo)
        {
            if (!Funcs.TryGetValue(itemNo, out var func)) return null;
            var table = func();
            if (table == null) return null;
            return es.AddFactor(EventFactorType.ITEM, itemNo, EventPriority.ITEM, (ushort)bpp.GetValueBase(PokeValueId.AGILITY), bpp.Id, table, (byte)table.Length);
        }

        public static EventFactor Add(EventSystem es, BattlePoke bpp) => AddHandler(es, bpp, bpp.Item);

        // Item.Remove: entfernt die Item-Faktoren des Pokemon, deren Arbeitswert 6 gleich 0 ist.
        public static void Remove(EventSystem es, BattlePoke bpp)
        {
            var container = es.Container;
            var f = container.SeekFactor(EventFactorType.ITEM, bpp.Id);
            while (f != null)
            {
                var next = container.GetNextFactor(f, false);
                if (f.GetWorkValue(6) == 0 && f.Exists)
                {
                    if (!f.Calling) container.RemoveFactor(f);
                    else f.RemoveReserve = true;
                }
                f = next;
            }
        }

        // item_AttackValue_to_Ratio @0x1a05d30: Item-Wert w (Prozent) -> ((w + 100) * 4096 + 0,5) / 100 (ganzzahlig).
        public static int AttackValueToRatio(int attackValue)
        {
            int v = attackValue + 100;
            float rounding = v < 1 ? -0.5f : 0.5f;
            return (int)((float)v * 4096.0f + rounding) / 100;
        }

        static int ItemRatio(EventHandlerArgs args) => AttackValueToRatio(args.Env.GetItemAttackValue(args.MyFactor.SubId));

        // handler_KodawariHachimaki_Pow @0x1a12600: Angreifer bin ich, nicht im G-Modus, physisch -> Verhaeltnis x1,5.
        static void HandlerKodawariHachimakiPow(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            var poke = args.Env.GetPoke(pokeId);
            if (poke.IsGMode) return;
            if (args.GetVar(EventVarLabel.DAMAGE_TYPE) == 1) args.MulVar(EventVarLabel.RATIO, 0x1800);
        }

        // handler_KoukakuLens @0x1a10d30: Angreifer bin ich -> Genauigkeitsverhaeltnis gemaess Item-Wert.
        static void HandlerKoukakuLens(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            args.MulVar(EventVarLabel.RATIO, ItemRatio(args));
        }

        // handler_MonosiriMegane @0x1a11a80: Angreifer bin ich, spezielle Attacke (Schadensart 2) -> Kraftverhaeltnis gemaess Item-Wert.
        static void HandlerMonosiriMegane(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            if (args.GetVar(EventVarLabel.DAMAGE_TYPE) == 2) args.MulVar(EventVarLabel.WAZA_POWER_RATIO, ItemRatio(args));
        }

        // handler_TatsujinNoObi @0x1a13910: Angreifer bin ich und die Typenwirkung ist ueberdurchschnittlich (ID > 7) -> Endfaktor gemaess Item-Wert.
        static void HandlerTatuzinNoObi(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) != pokeId) return;
            if (args.GetVar(EventVarLabel.TYPEAFF) > 7) args.MulVar(EventVarLabel.RATIO, ItemRatio(args));
        }

        // handler_InochiNoTama_Damage @0x1a13cf0: Angreifer bin ich -> Endfaktor gemaess Item-Wert.
        static void HandlerInotiNoTamaDamage(EventHandlerArgs args, byte pokeId)
        {
            if (args.GetVar(EventVarLabel.POKEID_ATK) == pokeId) args.MulVar(EventVarLabel.RATIO, ItemRatio(args));
        }
    }
}
