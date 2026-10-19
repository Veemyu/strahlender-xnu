using System;
using System.Collections.Generic;
using Xnu.Battle;
using Xnu.Battle.Flow;

namespace Xnu.Game
{
    // Namen und Meldungen für die Kampfdarstellung. Die Spiel-Implementierung (GameBattleTexts) liest die lokalen Meldungsdateien;
    // Tests nehmen eine erfundene Tabelle. Rückgabe null/leer = nicht vorhanden.
    public interface IBattleTexts
    {
        string Species(int monsNo);
        string Move(int moveNo);
        string Item(int itemNo);
        // Originalmeldung: Datei, Label, Wörter für die Platzhalter 0, 1, ... [A: Zuordnung der Platzhalter ist aus den Namen erschlossen].
        string Label(string msbt, string label, params string[] words);
    }

    // Ein Schritt der Kampfdarstellung: eine Meldung und die Zustandsänderung, die mit ihr sichtbar wird.
    public sealed class BattleBeat
    {
        public LogKind Kind;
        public string Text = "";
        public bool FromLabel;          // Text stammt aus einer Originalmeldung, sonst Platzhalter
        public int Poke = -1;           // betroffenes Pokémon (Kampf-ID), -1 = keins
        public int Side = -1;
        public bool SetHp;
        public int Hp;
        public bool SendOut;            // Poke tritt auf das Feld
        public bool Fainted;
        public bool Ends;               // Kampfende
        public float Seconds = 1.0f;
    }

    // Spielt das strukturierte Ereignisprotokoll von BattleEngine als Folge von BattleBeat ab. Reine Logik: Das Protokoll wird mit Pump()
    // eingelesen (bei jedem Aufruf nur die neuen Einträge), Dequeue() liefert den nächsten Schritt, Apply() setzt den gezeigten Zustand
    // (KP, aktives Pokémon). Der gezeigte Zustand läuft dem Engine-Zustand hinterher, bis alle Schritte gespielt sind.
    public sealed class BattleLogPlayer
    {
        public BattleEngine Engine { get; }
        readonly IBattleTexts _texts;
        readonly Queue<BattleBeat> _queue = new Queue<BattleBeat>();
        int _read;

        public readonly Dictionary<int, int> ShownHp = new Dictionary<int, int>();
        public readonly int[] ShownActive = { -1, -1 };
        public int BeatsMade { get; private set; }
        public int LabelBeats { get; private set; }
        public readonly Dictionary<LogKind, int> KindCounts = new Dictionary<LogKind, int>();
        public readonly Dictionary<LogKind, int> LabelKinds = new Dictionary<LogKind, int>();

        public BattleLogPlayer(BattleEngine engine, IBattleTexts texts)
        {
            Engine = engine ?? throw new ArgumentNullException(nameof(engine));
            _texts = texts ?? throw new ArgumentNullException(nameof(texts));
        }

        public bool HasBeats => _queue.Count > 0;
        public int Pending => _queue.Count;

        public int MaxHp(int pokeId) => Engine.FindMon(pokeId)?.Poke.MaxHp ?? 0;

        public string NameOf(int pokeId)
        {
            var m = Engine.FindMon(pokeId);
            return m == null ? "?" : Name(m.Poke.MonsNo);
        }

        string Name(int monsNo)
        {
            var n = _texts.Species(monsNo);
            return string.IsNullOrEmpty(n) ? "#" + monsNo : n;
        }

        public string MoveName(int id)
        {
            var n = _texts.Move(id);
            return string.IsNullOrEmpty(n) ? "Attacke " + id : n;
        }

        // Neue Protokolleinträge in Schritte umsetzen.
        public int Pump()
        {
            var made = 0;
            var log = Engine.Log;
            while (_read < log.Count)
            {
                var beat = Make(log[_read]);
                _read++;
                if (beat == null) continue;
                _queue.Enqueue(beat);
                made++;
                BeatsMade++;
                if (beat.FromLabel) LabelBeats++;
                KindCounts.TryGetValue(beat.Kind, out var c);
                KindCounts[beat.Kind] = c + 1;
                if (beat.FromLabel)
                {
                    LabelKinds.TryGetValue(beat.Kind, out var l);
                    LabelKinds[beat.Kind] = l + 1;
                }
            }
            return made;
        }

        public BattleBeat Dequeue() => _queue.Count > 0 ? _queue.Dequeue() : null;

        // Zustand zeigen, der mit dem Schritt sichtbar wird.
        public void Apply(BattleBeat b)
        {
            if (b == null) return;
            if (b.SendOut && b.Poke >= 0 && b.Side >= 0)
            {
                ShownActive[b.Side] = b.Poke;
                if (!ShownHp.ContainsKey(b.Poke)) ShownHp[b.Poke] = b.Hp;
            }
            if (b.SetHp && b.Poke >= 0) ShownHp[b.Poke] = Math.Max(0, b.Hp);
        }

        int SideOf(int pokeId) => pokeId < 0 ? -1 : Engine.FindMon(pokeId)?.Side ?? pokeId / 6;

        BattleBeat Make(LogEvent e)
        {
            var b = new BattleBeat { Kind = e.Kind, Poke = e.Poke, Side = SideOf(e.Poke) };
            var who = e.Poke >= 0 ? NameOf(e.Poke) : "";
            var other = e.Target >= 0 ? NameOf(e.Target) : "";
            switch (e.Kind)
            {
                case LogKind.BattleStart:
                    if (Engine.IsWild)
                    {
                        var enemy = Name(Engine.Active(BattleEngine.EnemySide).Poke.MonsNo);
                        b.Text = Original(b, "ss_btl_std", "BTL_STRID_STD_Encount_Wild1", enemy) ?? "Ein wildes " + enemy + " erscheint!";
                    }
                    else b.Text = Original(b, "ss_btl_std", "BTL_STRID_STD_Encount_NPC1") ?? "Ein Trainer fordert dich heraus!";
                    b.Seconds = 1.4f;
                    return b;
                case LogKind.SendOut:
                    b.SendOut = true;
                    b.Hp = e.Value2;
                    b.Text = b.Side == BattleEngine.PlayerSide ? "Los, " + who + "!" : (Engine.IsWild ? "" : "Der Gegner schickt " + who + " in den Kampf!");
                    if (b.Text.Length == 0) { b.Seconds = 0.05f; }
                    return b;
                case LogKind.TurnStart:
                case LogKind.ActionOrder:
                case LogKind.TurnEnd:
                case LogKind.HitCount:
                case LogKind.EvGained:
                case LogKind.Fainted:
                    return null;
                case LogKind.MoveUsed: b.Text = who + " setzt " + MoveName(e.Id) + " ein!"; return b;
                case LogKind.MoveFailed: b.Text = who + ": " + MoveName(e.Id) + " schlägt fehl!"; return b;
                case LogKind.MoveMissed: b.Text = "Der Angriff von " + who + " geht daneben!"; return b;
                case LogKind.NoEffect: b.Text = "Es hat keine Wirkung auf " + who + "."; return b;
                case LogKind.Critical: b.Text = "Ein Volltreffer!"; b.Seconds = 0.8f; return b;
                case LogKind.Effectiveness:
                    if (e.Value > AffinityId.Normal) b.Text = "Das ist sehr effektiv!";
                    else if (e.Value < AffinityId.Normal) b.Text = "Das ist nicht sehr effektiv …";
                    else return null;
                    b.Seconds = 0.8f;
                    return b;
                case LogKind.Damage:
                    b.SetHp = true; b.Hp = e.Value2; b.Seconds = 0.6f;
                    b.Text = who + " verliert " + e.Value + " KP.";
                    return b;
                case LogKind.Recover:
                    b.SetHp = true; b.Hp = e.Value2;
                    b.Text = who + " erholt sich um " + e.Value + " KP.";
                    return b;
                case LogKind.Drain:
                    b.Text = who + " saugt KP von " + other + " ab.";
                    return b;
                case LogKind.Recoil:
                    b.SetHp = true; b.Hp = e.Value2;
                    b.Text = who + " erleidet Rückstoß.";
                    return b;
                case LogKind.StatChange:
                    b.Text = who + ": Wert " + e.Id + " " + (e.Value > 0 ? "steigt" : "sinkt") + " (" + e.Value2 + ").";
                    return b;
                case LogKind.StatChangeBlocked: b.Text = "Bei " + who + " geht der Wert nicht weiter " + (e.Value > 0 ? "hoch." : "runter."); return b;
                case LogKind.SickAdded: b.Text = who + " bekommt Zustand " + e.Id + "."; return b;
                case LogKind.SickFailed: b.Text = "Bei " + who + " wirkt der Zustand nicht."; return b;
                case LogKind.SickCured: b.Text = who + " wird Zustand " + e.Id + " los."; return b;
                case LogKind.SickDamage:
                case LogKind.ConfusionDamage:
                case LogKind.WeatherDamage:
                case LogKind.HazardDamage:
                    b.SetHp = true; b.Hp = e.Value2;
                    b.Text = who + " nimmt " + e.Value + " Schaden.";
                    return b;
                case LogKind.WeatherStart: b.Text = "Das Wetter ändert sich."; return b;
                case LogKind.WeatherEnd: b.Text = "Das Wetter beruhigt sich."; return b;
                case LogKind.Faint:
                    b.Fainted = true; b.SetHp = true; b.Hp = 0;
                    b.Text = who + " wurde besiegt!";
                    b.Seconds = 1.2f;
                    return b;
                case LogKind.ExpGained:
                    b.Text = Original(b, "ss_btl_std", e.Value2 == 1 ? "BTL_STRID_STD_GetExp_Bonus" : "BTL_STRID_STD_GetExp", who, e.Value.ToString())
                             ?? who + " erhält " + e.Value + " Erfahrungspunkte.";
                    return b;
                case LogKind.LevelUp:
                    b.Text = Original(b, "ss_btl_std", "BTL_STRID_STD_LevelUp", who, e.Value.ToString()) ?? who + " erreicht Level " + e.Value + "!";
                    b.Seconds = 1.2f;
                    return b;
                case LogKind.Switch:
                    b.Text = "Zurück, " + who + "! Los, " + other + "!";
                    b.SendOut = true; b.Poke = e.Target; b.Side = SideOf(e.Target);
                    b.Hp = Engine.FindMon(e.Target)?.Poke.Hp ?? 0;
                    return b;
                case LogKind.ItemUsed: b.Text = "Item " + e.Id + " wurde bei " + who + " benutzt."; return b;
                case LogKind.RunAttempt: b.Text = "Flucht wird versucht …"; return b;
                case LogKind.RunSuccess:
                    b.Text = Original(b, "ss_btl_std", "BTL_STRID_STD_EscapeSuccess") ?? "Du bist entkommen!";
                    return b;
                case LogKind.RunFailed: b.Text = "Du kommst nicht weg!"; return b;
                case LogKind.BattleEnd:
                    b.Ends = true;
                    b.Text = e.Value == (int)BattleResult.Win ? "Der Kampf ist gewonnen!" : e.Value == (int)BattleResult.Lose ? "Du hast den Kampf verloren …" : "Der Kampf ist vorbei.";
                    b.Seconds = 1.2f;
                    return b;
                case LogKind.PrizeMoney: b.Text = "Du erhältst " + e.Value + " Geld."; return b;
                case LogKind.MoneyLost: b.Text = "Du verlierst " + e.Value + " Geld."; return b;
                case LogKind.AbilityActivated: b.Text = "Fähigkeit von " + who + " wirkt."; return b;
                case LogKind.ItemActivated: b.Text = "Item von " + who + " wirkt."; return b;
                case LogKind.ItemConsumed: b.Text = "Item von " + who + " wurde verbraucht."; return b;
                case LogKind.SideEffectStart: b.Text = "Ein Seiteneffekt beginnt."; return b;
                case LogKind.SideEffectEnd: b.Text = "Ein Seiteneffekt endet."; return b;
                case LogKind.Protected: b.Text = who + " schützt sich."; return b;
                case LogKind.Forced: b.Text = who + " wird weggeschickt."; return b;
                case LogKind.FieldEffectStart: b.Text = "Ein Feldeffekt beginnt."; return b;
                case LogKind.FieldEffectEnd: b.Text = "Ein Feldeffekt endet."; return b;
                default: b.Text = e.Kind.ToString(); return b;
            }
        }

        // Originalmeldung versuchen; leer/fehlend = null (Platzhalter greift). Markiert den Schritt bei Erfolg.
        string Original(BattleBeat b, string msbt, string label, params string[] words)
        {
            var t = _texts.Label(msbt, label, words);
            if (string.IsNullOrWhiteSpace(t)) return null;
            b.FromLabel = true;
            return t;
        }
    }
}
