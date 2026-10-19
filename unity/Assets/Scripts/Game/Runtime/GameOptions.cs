using System;

namespace Xnu.Game.Unity
{
    // Startoptionen des Spieltreibers (reine Logik, testbar): Kommandozeile vor Umgebungsvariable.
    //   -xnuInputScript <Datei>  oder XNU_SCRIPTED_INPUT   Eingabeskript statt Hand-Eingabe (docs/vertikaler-durchstich-1.md)
    //   -xnuSaveSource <Pfad>    oder XNU_SAVE_SOURCE       Quelle für den ersten Import (nur gelesen)
    //   -xnuSaveRoot <Ordner>    oder XNU_SAVE_ROOT         Ablage der Slots (Standard: persistentDataPath/Saves)
    //   -xnuShotDir <Ordner>     oder XNU_SHOT_DIR          Ziel der Bildaufnahmen (Skriptbefehl shot)
    //   -xnuAutoContinue         oder XNU_AUTO_CONTINUE=1   Titel überspringen
    //   -xnuTargetFps <N>        oder XNU_TARGET_FPS        Application.targetFrameRate (iOS: ohne Vorgabe 30)
    //   -xnuPerfLog              oder XNU_PERF_LOG=1        alle 5 s eine Zeile XNUPERF| (Bildrate, Speicher, Thermik, Fehler)
    public sealed class GameOptions
    {
        public string ScriptPath = "";
        public string SaveSource = "";
        public string SaveRoot = "";
        public string ShotDir = "";
        public bool AutoContinue;
        public int TargetFps;
        public bool PerfLog;

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
            if (int.TryParse(Pick("-xnuTargetFps", "XNU_TARGET_FPS"), out var fps) && fps > 0 && fps <= 240) o.TargetFps = fps;
            var flag = false;
            var perf = false;
            if (args != null) foreach (var a in args) { if (a == "-xnuAutoContinue") flag = true; if (a == "-xnuPerfLog") perf = true; }
            var e2 = env?.Invoke("XNU_AUTO_CONTINUE");
            o.AutoContinue = flag || e2 == "1";
            o.PerfLog = perf || env?.Invoke("XNU_PERF_LOG") == "1";
            return o;
        }
    }
}
