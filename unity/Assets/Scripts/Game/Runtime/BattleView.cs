using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Xnu.Battle.Flow;
using Xnu.UI;

namespace Xnu.Game.Unity
{
    // Kleine uGUI-Bausteine für Kampf- und Titelansicht (nur eigene Objekte, Standardschrift, keine Originalshader).
    public static class UiKit
    {
        public static RectTransform Panel(Transform parent, string name, Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            rt.anchorMin = anchorMin; rt.anchorMax = anchorMax; rt.offsetMin = offsetMin; rt.offsetMax = offsetMax;
            var img = go.GetComponent<Image>();
            img.color = color;
            img.raycastTarget = false;
            return rt;
        }

        public static TextMeshProUGUI Label(Transform parent, string name, Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax,
            float size, Color color, TextAlignmentOptions align)
        {
            var go = new GameObject(name, typeof(RectTransform));
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            rt.anchorMin = anchorMin; rt.anchorMax = anchorMax; rt.offsetMin = offsetMin; rt.offsetMax = offsetMax;
            var t = go.AddComponent<TextMeshProUGUI>();
            t.fontSize = size;
            t.color = color;
            t.alignment = align;
            t.textWrappingMode = TextWrappingModes.Normal;
            t.overflowMode = TextOverflowModes.Overflow;
            t.raycastTarget = false;
            return t;
        }
    }

    // Eine Infotafel (Name, Stufe, KP-Balken) mit weichem Nachlaufen des Balkens.
    sealed class InfoPanel
    {
        public readonly RectTransform Root;
        readonly TextMeshProUGUI _name, _hpText;
        readonly RectTransform _fill;
        readonly Image _fillImage;
        float _shown = 1f;
        float _target = 1f;

        public float Ratio => _shown;
        public string NameText => _name.text;
        public string HpText => _hpText.text;

        public InfoPanel(Transform parent, string name, Vector2 anchor, Vector2 pivotOffset, bool showNumbers)
        {
            Root = UiKit.Panel(parent, name, anchor, anchor, pivotOffset, pivotOffset + new Vector2(440f, 110f), new Color(0.96f, 0.96f, 0.9f, 0.95f));
            _name = UiKit.Label(Root, "Name", Vector2.zero, Vector2.one, new Vector2(16f, 52f), new Vector2(-16f, -6f), 32f, new Color(0.1f, 0.1f, 0.14f), TextAlignmentOptions.MidlineLeft);
            var back = UiKit.Panel(Root, "HpBack", Vector2.zero, new Vector2(1f, 0f), new Vector2(16f, 22f), new Vector2(-16f, 40f), new Color(0.25f, 0.25f, 0.28f, 1f));
            _fill = UiKit.Panel(back, "HpFill", Vector2.zero, Vector2.one, new Vector2(2f, 2f), new Vector2(-2f, -2f), new Color(0.2f, 0.75f, 0.3f, 1f));
            _fillImage = _fill.GetComponent<Image>();
            _hpText = UiKit.Label(Root, "HpText", Vector2.zero, new Vector2(1f, 0f), new Vector2(16f, 0f), new Vector2(-16f, 22f), 20f, new Color(0.15f, 0.15f, 0.2f), TextAlignmentOptions.MidlineRight);
            _hpText.gameObject.SetActive(showNumbers);
        }

        public void Set(string name, int level, int hp, int maxHp, bool instant)
        {
            _name.text = name + "   Lv. " + level;
            _hpText.text = hp + " / " + maxHp;
            _target = maxHp <= 0 ? 0f : Mathf.Clamp01(hp / (float)maxHp);
            if (instant) _shown = _target;
            Apply();
        }

        public void Tick(float dt)
        {
            _shown = Mathf.MoveTowards(_shown, _target, dt * 0.9f);
            Apply();
        }

        void Apply()
        {
            var a = _fill.anchorMax;
            a.x = Mathf.Max(0.001f, _shown);
            _fill.anchorMax = a;
            _fillImage.color = _shown > 0.5f ? new Color(0.2f, 0.75f, 0.3f) : _shown > 0.2f ? new Color(0.95f, 0.8f, 0.15f) : new Color(0.9f, 0.2f, 0.2f);
        }
    }

    // Kampfansicht (eigenes uGUI, Platzhalter statt Modelle/Sprites): Gegner- und Spielerinfo mit KP-Balken, Meldungsfenster,
    // Befehlsmenü (Kampf/Beutel/Pokémon/Flucht), Attackenwahl, Pokémon-Wechsel. Spielt BattleBeat-Schritte des BattleLogPlayer ab.
    // Eingabe und Zeit kommen von außen (Tick), dadurch ohne Fokus und mit Skripteingabe nutzbar.
    [DisallowMultipleComponent]
    public sealed class BattleView : MonoBehaviour
    {
        public const int SortingOrder = 700;
        public enum Mode { Idle, Beats, Command, Moves, Party, Notice }

        public struct Result
        {
            public BattleCommand? Command;
            public int Replacement;
        }

        Canvas _canvas;
        RectTransform _root;
        InfoPanel _enemy, _player;
        TextMeshProUGUI _message, _menuText;
        RectTransform _menuPanel;
        RectTransform _enemySprite, _playerSprite;
        TextMeshProUGUI _enemyTag, _playerTag;
        BattleSession _session;
        BattleLogPlayer _log;
        BattleBeat _current;
        float _beatTimer;
        float _noticeTimer;
        int _cursor;
        readonly List<int> _partyChoices = new List<int>();

        public bool Active { get; private set; }
        public Mode CurrentMode { get; private set; } = Mode.Idle;
        public string MessageText => _message != null ? _message.text : "";
        public string MenuText => _menuText != null ? _menuText.text : "";
        public int Cursor => _cursor;
        public BattleLogPlayer Log => _log;
        public int BeatsShown { get; private set; }
        public int CommandsIssued { get; private set; }
        public float EnemyBar => _enemy?.Ratio ?? 0f;
        public float PlayerBar => _player?.Ratio ?? 0f;
        public string EnemyName => _enemy?.NameText ?? "";
        public string PlayerName => _player?.NameText ?? "";
        // Läuft die Ansicht gerade Schritte ab (dann bleibt die Spielschleife angehalten)?
        public bool Busy => Active && (CurrentMode == Mode.Beats || CurrentMode == Mode.Notice || _current != null || (_log != null && _log.HasBeats));

        public void Build(Camera camera)
        {
            if (_canvas != null) return;
            _canvas = UiCanvasFactory.Create("BattleCanvas", camera, SortingOrder, transform);
            _root = UiKit.Panel(_canvas.transform, "Root", Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero, new Color(0.28f, 0.45f, 0.38f, 1f));
            UiKit.Panel(_root, "Ground", Vector2.zero, new Vector2(1f, 0.42f), Vector2.zero, Vector2.zero, new Color(0.36f, 0.56f, 0.3f, 1f));

            _enemy = new InfoPanel(_root, "EnemyInfo", new Vector2(0f, 1f), new Vector2(40f, -150f), false);
            _player = new InfoPanel(_root, "PlayerInfo", new Vector2(1f, 0f), new Vector2(-480f, 470f), true);

            _enemySprite = UiKit.Panel(_root, "EnemySprite", new Vector2(0.48f, 0.55f), new Vector2(0.48f, 0.55f), new Vector2(-110f, -110f), new Vector2(110f, 110f), new Color(0.85f, 0.35f, 0.3f, 1f));
            _playerSprite = UiKit.Panel(_root, "PlayerSprite", new Vector2(0.22f, 0.3f), new Vector2(0.22f, 0.3f), new Vector2(-130f, -130f), new Vector2(130f, 130f), new Color(0.3f, 0.45f, 0.9f, 1f));
            _enemyTag = UiKit.Label(_enemySprite, "Tag", Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero, 36f, Color.white, TextAlignmentOptions.Center);
            _playerTag = UiKit.Label(_playerSprite, "Tag", Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero, 36f, Color.white, TextAlignmentOptions.Center);

            var box = UiKit.Panel(_root, "MessageBox", new Vector2(0f, 0f), new Vector2(1f, 0f), new Vector2(40f, 24f), new Vector2(-40f, 190f), new Color(0.08f, 0.1f, 0.16f, 0.92f));
            _message = UiKit.Label(box, "Message", Vector2.zero, Vector2.one, new Vector2(28f, 16f), new Vector2(-28f, -16f), 36f, Color.white, TextAlignmentOptions.TopLeft);

            _menuPanel = UiKit.Panel(_root, "Menu", new Vector2(1f, 0f), new Vector2(1f, 0f), new Vector2(-460f, 204f), new Vector2(-40f, 204f + 250f), new Color(0.96f, 0.96f, 0.9f, 0.97f));
            _menuText = UiKit.Label(_menuPanel, "MenuText", Vector2.zero, Vector2.one, new Vector2(24f, 12f), new Vector2(-16f, -12f), 34f, new Color(0.1f, 0.1f, 0.14f), TextAlignmentOptions.TopLeft);
            _menuText.lineSpacing = 8f;
            _root.gameObject.SetActive(false);
            _menuPanel.gameObject.SetActive(false);
        }

        public bool IsBuilt => _canvas != null;
        public Canvas Canvas => _canvas;

        public void Begin(BattleSession session, IBattleTexts texts)
        {
            _session = session;
            _log = new BattleLogPlayer(session.Engine, texts);
            _current = null;
            _message.text = "";
            _cursor = 0;
            Active = true;
            CurrentMode = Mode.Beats;
            _root.gameObject.SetActive(true);
            _menuPanel.gameObject.SetActive(false);
            var e = session.Engine;
            var enemy = e.Active(BattleEngine.EnemySide);
            var me = e.Active(BattleEngine.PlayerSide);
            _enemyTag.text = "#" + enemy.Poke.MonsNo;
            _playerTag.text = "#" + me.Poke.MonsNo;
            _enemyTag.color = _playerTag.color = Color.white;
            _enemy.Set(_log.NameOf(enemy.PokeId), enemy.Level, enemy.Poke.Hp, enemy.Poke.MaxHp, true);
            _player.Set(_log.NameOf(me.PokeId), me.Level, me.Poke.Hp, me.Poke.MaxHp, true);
            _log.Pump();
        }

        public void End()
        {
            Active = false;
            CurrentMode = Mode.Idle;
            _current = null;
            if (_root != null) _root.gameObject.SetActive(false);
        }

        // Ein Schritt der Ansicht (30 Hz oder je Bild). Gibt einen Befehl zurück, wenn der Spieler gewählt hat.
        public Result Tick(float dt, UiInputState input)
        {
            var result = new Result { Replacement = -1 };
            if (!Active) return result;
            _enemy.Tick(dt);
            _player.Tick(dt);
            _log.Pump();

            if (CurrentMode == Mode.Notice)
            {
                _noticeTimer -= dt;
                if (_noticeTimer <= 0f || input.AnyPressed) CurrentMode = Mode.Command;
                return result;
            }

            if (_current != null)
            {
                _beatTimer -= dt * (input.ConfirmHeld ? 3f : 1f);
                if (_beatTimer > 0f) return result;
                _current = null;
            }
            if (_log.HasBeats)
            {
                ShowBeat(_log.Dequeue());
                return result;
            }

            var engine = _session.Engine;
            if (_session.IsFinished || engine.Phase == BattlePhase.Finished || engine.Phase == BattlePhase.NotStarted)
            {
                End();
                return result;
            }
            if (engine.Phase == BattlePhase.AwaitReplacement)
            {
                for (var i = 0; i < engine.Parties[BattleEngine.PlayerSide].Count; i++)
                    if (!engine.Parties[BattleEngine.PlayerSide][i].IsFainted) { result.Replacement = i; break; }
                return result;
            }

            if (CurrentMode == Mode.Beats) EnterCommand();
            switch (CurrentMode)
            {
                case Mode.Command: TickCommand(input, ref result); break;
                case Mode.Moves: TickMoves(input, ref result); break;
                case Mode.Party: TickParty(input, ref result); break;
            }
            return result;
        }

        void ShowBeat(BattleBeat b)
        {
            _current = b;
            _beatTimer = b.Seconds;
            BeatsShown++;
            _log.Apply(b);
            _menuPanel.gameObject.SetActive(false);
            CurrentMode = Mode.Beats;
            if (b.Text.Length > 0) _message.text = b.Text;
            var e = _session.Engine;
            if (b.SendOut || b.SetHp || b.Fainted) RefreshPanels(b.SendOut);
            if (b.Fainted && b.Side >= 0) (b.Side == BattleEngine.PlayerSide ? _playerSprite : _enemySprite).gameObject.SetActive(false);
        }

        void RefreshPanels(bool instant)
        {
            var e = _session.Engine;
            for (var side = 0; side < 2; side++)
            {
                var id = _log.ShownActive[side];
                if (id < 0) continue;
                var mon = e.FindMon(id);
                if (mon == null) continue;
                _log.ShownHp.TryGetValue(id, out var hp);
                var panel = side == BattleEngine.PlayerSide ? _player : _enemy;
                var tag = side == BattleEngine.PlayerSide ? _playerTag : _enemyTag;
                var sprite = side == BattleEngine.PlayerSide ? _playerSprite : _enemySprite;
                var newTag = "#" + mon.Poke.MonsNo;
                var fresh = tag.text != newTag;
                tag.text = newTag;
                if (fresh || hp > 0) sprite.gameObject.SetActive(true);
                panel.Set(_log.NameOf(id), mon.Level, hp, mon.Poke.MaxHp, instant || fresh);
            }
        }

        void EnterCommand()
        {
            CurrentMode = Mode.Command;
            _cursor = 0;
            _message.text = "Was soll " + _log.NameOf(_session.Engine.Active(BattleEngine.PlayerSide).PokeId) + " tun?";
        }

        void ShowMenu(string[] rows)
        {
            _menuPanel.gameObject.SetActive(true);
            var sb = new StringBuilder();
            for (var i = 0; i < rows.Length; i++)
            {
                sb.Append(i == _cursor ? "> " : "   ").Append(rows[i]);
                if (i < rows.Length - 1) sb.Append('\n');
            }
            _menuText.text = sb.ToString();
        }

        int Move(UiInputState input, int count)
        {
            if (input.MoveY != 0) _cursor = (_cursor + (input.MoveY > 0 ? 1 : count - 1)) % count;
            return _cursor;
        }

        static readonly string[] CommandRows = { "Kampf", "Beutel", "Pokémon", "Flucht" };

        void TickCommand(UiInputState input, ref Result r)
        {
            Move(input, CommandRows.Length);
            ShowMenu(CommandRows);
            if (!input.ConfirmPressed) return;
            switch (_cursor)
            {
                case 0: CurrentMode = Mode.Moves; _cursor = 0; break;
                case 1: Notice("Der Beutel ist im Kampf noch nicht umgesetzt."); break;
                case 2: CurrentMode = Mode.Party; _cursor = 0; break;
                case 3: Issue(BattleCommand.Run(), ref r); break;
            }
        }

        void TickMoves(UiInputState input, ref Result r)
        {
            var mon = _session.Engine.Active(BattleEngine.PlayerSide);
            var rows = new List<string>();
            for (var i = 0; i < BattleMon.MoveCount; i++)
            {
                if (mon.Moves[i] == 0) continue;
                var n = _log.MoveName(mon.Moves[i]);
                rows.Add(n + "  " + mon.Pp[i] + "/" + mon.MaxPp[i]);
            }
            if (rows.Count == 0) { Issue(BattleCommand.Fight(0), ref r); return; }
            Move(input, rows.Count);
            ShowMenu(rows.ToArray());
            if (input.CancelPressed) { CurrentMode = Mode.Command; _cursor = 0; return; }
            if (input.ConfirmPressed) Issue(BattleCommand.Fight(_cursor), ref r);
        }

        void TickParty(UiInputState input, ref Result r)
        {
            var e = _session.Engine;
            var party = e.Parties[BattleEngine.PlayerSide];
            var rows = new List<string>();
            _partyChoices.Clear();
            for (var i = 0; i < party.Count; i++)
            {
                var m = party[i];
                rows.Add(_log.NameOf(m.PokeId) + "  " + m.Poke.Hp + "/" + m.Poke.MaxHp + (i == e.ActiveIndex(BattleEngine.PlayerSide) ? " *" : ""));
                _partyChoices.Add(i);
            }
            Move(input, rows.Count);
            ShowMenu(rows.ToArray());
            if (input.CancelPressed) { CurrentMode = Mode.Command; _cursor = 0; return; }
            if (input.ConfirmPressed) Issue(BattleCommand.Change(_partyChoices[_cursor]), ref r);
        }

        void Issue(BattleCommand cmd, ref Result r)
        {
            if (!_session.Engine.IsCommandValid(BattleEngine.PlayerSide, cmd, out var reason))
            {
                Notice(string.IsNullOrEmpty(reason) ? "Das geht jetzt nicht." : reason);
                return;
            }
            CommandsIssued++;
            r.Command = cmd;
            _menuPanel.gameObject.SetActive(false);
            CurrentMode = Mode.Beats;
        }

        void Notice(string text)
        {
            _message.text = text;
            _noticeTimer = 1.5f;
            CurrentMode = Mode.Notice;
            _menuPanel.gameObject.SetActive(false);
        }
    }
}
