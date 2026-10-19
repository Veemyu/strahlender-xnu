using System.Collections.Generic;

namespace Xnu.Render
{
    // Beobachtungen am Bild-Aufbau (Unity-frei, damit die Regeln ohne Editor testbar sind).
    public struct RenderFacts
    {
        public int GeneratedMaterials;      // Anzahl Materialien mit erzeugtem Shader (0 = Ersatzmaterial, Regeln greifen nicht)
        public int ActiveDirectionalLights; // aktive und eingeschaltete Richtungslichter
        public float BrightestSunIntensity; // größte Intensität unter diesen Lichtern
        public int GlobalsSet;              // von GameGlobals gesetzte Namen
        public int GlobalsTotal;            // Anzahl der Spiel-Globals (GameGlobals.Specs.Count)
    }

    public enum RenderProblemKind { NoSun, DarkSun, GlobalsUnset, SeveralSuns }

    public readonly struct RenderProblem
    {
        public readonly RenderProblemKind Kind;
        public readonly string Message;
        public RenderProblem(RenderProblemKind kind, string message) { Kind = kind; Message = message; }
        public bool IsBlack => Kind == RenderProblemKind.NoSun || Kind == RenderProblemKind.DarkSun;
        public override string ToString() => Message;
    }

    // Regeln aus den Labormessungen (docs/material-remap.md, Abschnitt 10b): Die erzeugten Forward-Shader zeichnen ohne Licht
    // exakt schwarz, auch wenn alle Spiel-Globals gesetzt sind; ohne Globals ist das Bild nur dunkler.
    public static class RenderChecks
    {
        public static List<RenderProblem> Evaluate(RenderFacts f)
        {
            var list = new List<RenderProblem>();
            if (f.GeneratedMaterials <= 0) return list;
            if (f.ActiveDirectionalLights == 0)
                list.Add(new RenderProblem(RenderProblemKind.NoSun,
                    "Kein aktives Richtungslicht: Die erzeugten Forward-Shader zeichnen schwarz (Lab: Bildmittel 0, 0, 0 ohne Licht). SunLight.Ensure aufrufen."));
            else if (f.BrightestSunIntensity <= 0f)
                list.Add(new RenderProblem(RenderProblemKind.DarkSun,
                    "Das Richtungslicht hat Intensität 0: Das Bild bleibt schwarz."));
            else if (f.ActiveDirectionalLights > 1)
                list.Add(new RenderProblem(RenderProblemKind.SeveralSuns,
                    f.ActiveDirectionalLights + " Richtungslichter: Unity nimmt nur das hellste als Hauptlicht (das Original hat eines je Szene)."));
            if (f.GlobalsTotal > 0 && f.GlobalsSet == 0)
                list.Add(new RenderProblem(RenderProblemKind.GlobalsUnset,
                    "Spiel-Globals nicht gesetzt (GameGlobals.SetDefaults oder EnvironmentDriver): Das Bild ist dunkler als im Spiel."));
            return list;
        }

        public static bool WillBeBlack(RenderFacts f)
        {
            foreach (var p in Evaluate(f)) if (p.IsBlack) return true;
            return false;
        }
    }
}
