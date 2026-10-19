using System;

namespace Xnu.Game.Unity
{
    // Startoptionen des Spieltreibers (reine Logik, testbar): Kommandozeile vor Umgebungsvariable.
    //   -xnuInputScript <Datei>  oder XNU_SCRIPTED_INPUT   Eingabeskript statt Hand-Eingabe (docs/vertikaler-durchstich-1.md)
    //   -xnuSaveSource <Pfad>    oder XNU_SAVE_SOURCE       Quelle für den ersten Import (nur gelesen)
    //   -xnuSaveRoot <Ordner>    oder XNU_SAVE_ROOT         Ablage der Slots (Standard: persistentDataPath/Saves)
    //   -xnuShotDir <Ordner>     oder XNU_SHOT_DIR          Ziel der Bildaufnahmen (Skriptbefehl shot)
    //   -xnuAutoContinue         oder XNU_AUTO_CONTINUE=1   Titel überspringen
    public sealed class GameOptions
    {
        public string ScriptPath = "";
        public string SaveSource = "";
        public string SaveRoot = "";
        public string ShotDir = "";
        public bool AutoContinue;

        public static GameOptions Parse(string[] args, Func<string, string> env)
        {
            var o = new GameOptions();
            string Arg(string name)
            {
                if (args == null) return null;
                for (var i = 0; i < args.Length - 1; i++)
                    if (args[i] == name && !string.IsNullOrWhiteSpace(args[i + 1])) return args[i + 1].Trim();
                return null;
            }
            string Pick(string arg, string envName)
            {
                var a = Arg(arg);
                if (a != null) return a;
                var e = env?.Invoke(envName);
                return string.IsNullOrWhiteSpace(e) ? "" : e.Trim();
            }
            o.ScriptPath = Pick("-xnuInputScript", "XNU_SCRIPTED_INPUT");
            o.SaveSource = Pick("-xnuSaveSource", "XNU_SAVE_SOURCE");
            o.SaveRoot = Pick("-xnuSaveRoot", "XNU_SAVE_ROOT");
            o.ShotDir = Pick("-xnuShotDir", "XNU_SHOT_DIR");
            var flag = false;
            if (args != null) foreach (var a in args) if (a == "-xnuAutoContinue") flag = true;
            var e2 = env?.Invoke("XNU_AUTO_CONTINUE");
            o.AutoContinue = flag || e2 == "1";
            return o;
        }
    }
}
