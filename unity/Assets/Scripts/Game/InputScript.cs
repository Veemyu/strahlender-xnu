using System;
using System.Collections.Generic;
using System.Globalization;

namespace Xnu.Game
{
    // Eingabe eines Ticks aus einem Skript (statt Hand-Eingabe): Tasten als Daten, dazu ein Kampfbefehl.
    public struct ScriptFrame
    {
        public bool A, B, Plus;
        public bool Up, Down, Left, Right;
        public int Fight;            // -1 = keiner, sonst Attackenplatz 0..3
        public int Starter;          // -1 = keiner
        public bool Any => A || B || Plus || Up || Down || Left || Right || Fight >= 0;

        public static ScriptFrame None => new ScriptFrame { Fight = -1, Starter = -1 };
    }

    // Was ein Skript vom Treiber braucht (Zustand erfragen, Sonderbefehle ausführen).
    public interface IScriptWorld
    {
        // "Title", "Field", "Event", "Battle", "Menu", "Transition" (Zonenwechsel läuft), "Textbox", "BattleMenu" ...
        string StateName { get; }
        // Sonderbefehl (goto, nearnpc, encounter, shot, log, save, ...). true = fertig, false = im nächsten Tick erneut.
        bool Execute(string command, string[] args);
    }

    // Eingabeskript, eine Anweisung je Zeile, '#' beginnt einen Kommentar. Anweisungen:
    //   wait N                 N Ticks nichts tun            tap A|B|Plus|Up|Down|Left|Right   Taste einen Tick drücken
    //   hold Up|Down|Left|Right N   Richtung N Ticks halten   mash N     N Ticks lang alle 6 Ticks A drücken   mashuntil NAME N  A drücken, bis Zustand NAME (höchstens N Ticks)
    //   (Richtungen sind Bildschirmrichtungen; in Innenräumen mit gedrehter Kamera liegt "Up" bei Zellrichtung gy-1)
    //   waitstate NAME N       bis zum Zustand NAME (höchstens N Ticks); überschritten = weiter, Zähler timeouts
    //   fight S                Kampf: Attackenplatz S wählen  starter I   Startwahl I
    //   alles andere           wird an IScriptWorld.Execute gegeben (goto X Y DIR, nearnpc, encounter, shot NAME, log TEXT, save, quit)
    public sealed class InputScript
    {
        public sealed class Step
        {
            public string Command;
            public string[] Args;
            public int Line;
            public int Number(int index, int fallback = 0) =>
                index < Args.Length && int.TryParse(Args[index], NumberStyles.Integer, CultureInfo.InvariantCulture, out var v) ? v : fallback;
        }

        public readonly List<Step> Steps = new List<Step>();

        public static InputScript Parse(string text)
        {
            var s = new InputScript();
            var n = 0;
            foreach (var raw in (text ?? "").Split('\n'))
            {
                n++;
                var line = raw;
                var hash = line.IndexOf('#');
                if (hash >= 0) line = line.Substring(0, hash);
                line = line.Trim();
                if (line.Length == 0) continue;
                var parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                var args = new string[parts.Length - 1];
                Array.Copy(parts, 1, args, 0, args.Length);
                s.Steps.Add(new Step { Command = parts[0].ToLowerInvariant(), Args = args, Line = n });
            }
            return s;
        }
    }

    public sealed class InputScriptRunner
    {
        readonly InputScript _script;
        int _index;
        int _counter;
        bool _started;

        public int Index => _index;
        public int Timeouts { get; private set; }
        public int Ticks { get; private set; }
        public bool Finished => _index >= _script.Steps.Count;
        public string Current => Finished ? "" : _script.Steps[_index].Command + " " + string.Join(" ", _script.Steps[_index].Args);

        public InputScriptRunner(InputScript script) => _script = script ?? throw new ArgumentNullException(nameof(script));

        void Advance()
        {
            _index++;
            _counter = 0;
            _started = false;
        }

        public ScriptFrame Next(IScriptWorld world)
        {
            Ticks++;
            var f = ScriptFrame.None;
            // Sonderbefehle und leere Anweisungen verbrauchen keinen Tick, wenn danach noch etwas folgt (höchstens 64 pro Tick).
            for (var guard = 0; guard < 64 && !Finished; guard++)
            {
                var st = _script.Steps[_index];
                switch (st.Command)
                {
                    case "wait":
                        if (_counter++ < st.Number(0)) return f;
                        Advance();
                        continue;
                    case "tap":
                        if (_started) { Advance(); continue; }
                        _started = true;
                        SetButton(ref f, st.Args.Length > 0 ? st.Args[0] : "A");
                        return f;
                    case "hold":
                        if (_counter++ >= st.Number(1)) { Advance(); continue; }
                        SetButton(ref f, st.Args.Length > 0 ? st.Args[0] : "Up");
                        return f;
                    case "mash":
                        if (_counter >= st.Number(0)) { Advance(); continue; }
                        if (_counter % 6 == 0) f.A = true;
                        _counter++;
                        return f;
                    case "mashuntil":
                        if (st.Args.Length > 0 && string.Equals(world.StateName, st.Args[0], StringComparison.OrdinalIgnoreCase)) { Advance(); continue; }
                        if (_counter >= st.Number(1, 600)) { Timeouts++; Advance(); continue; }
                        if (_counter % 6 == 0) f.A = true;
                        _counter++;
                        return f;
                    case "waitstate":
                        if (st.Args.Length > 0 && string.Equals(world.StateName, st.Args[0], StringComparison.OrdinalIgnoreCase)) { Advance(); continue; }
                        if (_counter++ >= st.Number(1, 600)) { Timeouts++; Advance(); continue; }
                        return f;
                    case "fight":
                        f.Fight = st.Number(0);
                        Advance();
                        return f;
                    case "starter":
                        f.Starter = st.Number(0);
                        Advance();
                        return f;
                    default:
                        if (world.Execute(st.Command, st.Args)) { Advance(); continue; }
                        return f;
                }
            }
            return f;
        }

        static void SetButton(ref ScriptFrame f, string name)
        {
            switch (name.ToLowerInvariant())
            {
                case "a": f.A = true; break;
                case "b": f.B = true; break;
                case "plus": f.Plus = true; break;
                case "up": f.Up = true; break;
                case "down": f.Down = true; break;
                case "left": f.Left = true; break;
                case "right": f.Right = true; break;
            }
        }
    }
}
