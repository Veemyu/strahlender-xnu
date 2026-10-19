using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;
using Xnu.Core;
using Debug = UnityEngine.Debug;

namespace Xnu.Field.Editor
{
    // Prüfwerkzeug mit den lokalen Spieldaten (XNU_GAMEDATA): lädt Zone 422, geht durch Tür, Raum, Treppe und Gebietswechsel,
    // streamt Blöcke und protokolliert Speicher und Zeiten. Läuft ohne Spielmodus (Coroutinen werden von Hand getrieben),
    // auch im Batchmodus: Unity -batchmode -nographics -projectpath unity -executeMethod Xnu.Field.Editor.FieldVerify.RunBatch
    // Bericht nach XNU_FIELD_REPORT (Standard <GameData>/field-verify.txt, also nach work/). Spielt nichts ab (kein Ton).
    public static class FieldVerify
    {
        [MenuItem("Xnu/Field/Verify (Zonenwechsel, Streaming)")]
        public static void RunMenu() => Debug.Log(Execute());

        public static void RunBatch()
        {
            var ok = true;
            string report;
            try { report = Execute(); }
            catch (Exception e) { report = "FEHLER: " + e; ok = false; }
            var path = Environment.GetEnvironmentVariable("XNU_FIELD_REPORT");
            if (string.IsNullOrEmpty(path)) path = Path.Combine(GameDataPaths.Root, "field-verify.txt");
            File.WriteAllText(path, report);
            EditorApplication.Exit(ok && !report.Contains("FEHLER") ? 0 : 1);
        }

        static void Drive(FieldController f, IEnumerator root, int maxSteps = 200000)
        {
            var stack = new Stack<IEnumerator>();
            stack.Push(root);
            var steps = 0;
            while (stack.Count > 0)
            {
                var top = stack.Peek();
                if (!top.MoveNext()) { stack.Pop(); continue; }
                if (top.Current is IEnumerator inner) stack.Push(inner);
                else f.Fade.Tick(0.05f);
                if (++steps > maxSteps) throw new InvalidOperationException("Coroutine endet nicht");
            }
        }

        static string Cell(FieldController f) => "Zone " + f.zoneId + " Zelle (" + f.Mover.GridX + ", " + f.Mover.GridY + ") Blick " + f.Mover.Facing;

        public static string Execute()
        {
            var sb = new StringBuilder();
            var go = new GameObject("FieldVerify") { hideFlags = HideFlags.HideAndDontSave };
            try
            {
                var f = go.AddComponent<FieldController>();
                f.zoneId = 422;
                f.streaming = true;
                f.usePlayerModel = true;
                f.showNpcs = true;
                f.useGeneratedShaders = false;
                f.headlessUnload = true;
                f.fadeOutSeconds = 0.1f; f.fadeInSeconds = 0.1f;
                IEnumerator pending = null;
                f.CoroutineRunner = e => pending = e;

                var clock = Stopwatch.StartNew();
                Drive(f, f.Load());
                sb.AppendLine("Laden Zone 422: " + clock.ElapsedMilliseconds + " ms, Loaded=" + f.Loaded + " Fehler=" + f.Error);
                sb.AppendLine("Material: " + f.MaterialMode + "; Fremdmaterial " + f.ForeignMaterials);
                sb.AppendLine("Spielerfigur: " + f.AvatarNote);
                sb.AppendLine(Cell(f) + ", Höhe " + f.Mover.Height.ToString("F2") + ", Blöcke " + f.Streamer.Loaded.Count + "/" + CountAvail(f) + ", NPCs " + f.NpcCount + ", Ladeabstand " + f.EffectiveLoadDistance);
                sb.AppendLine(f.BuildStats.ToString());

                // Tür: nach unten in die gesperrte Türzelle (116, 885).
                for (var i = 0; i < 20 && pending == null; i++) f.TickLogic(1f / 30f, MoveDir.Down, false);
                sb.AppendLine("Tür ausgelöst: " + (pending != null));
                if (pending != null) { var p = pending; pending = null; clock.Restart(); Drive(f, p); sb.AppendLine("  -> " + Cell(f) + ", " + clock.ElapsedMilliseconds + " ms, Loaded=" + f.Loaded + " Fehler=" + f.Error + ", Blöcke " + f.Streamer.Loaded.Count + ", NPCs " + f.NpcCount); }
                sb.AppendLine("  Bericht: " + Last(f));

                // Raum: zwei Zellen hinein, wieder auf die Türzelle (Warp zurück).
                for (var i = 0; i < 60; i++) f.TickLogic(1f / 30f, MoveDir.Down, false);
                sb.AppendLine("Im Raum: " + Cell(f));
                for (var i = 0; i < 200 && pending == null; i++) f.TickLogic(1f / 30f, MoveDir.Up, false);
                sb.AppendLine("Warp (Ausgang) ausgelöst: " + (pending != null));
                if (pending != null) { var p = pending; pending = null; clock.Restart(); Drive(f, p); sb.AppendLine("  -> " + Cell(f) + ", " + clock.ElapsedMilliseconds + " ms, Blöcke " + f.Streamer.Loaded.Count); }
                sb.AppendLine("  Bericht: " + Last(f));

                // Streaming in 422: entlang der Südrichtung springen und die Blockauswahl messen.
                sb.AppendLine("Streaming (Teleport entlang x = 116):");
                foreach (var y in new[] { 886, 870, 850, 830, 800, 770, 886 })
                {
                    f.Mover.Teleport(116, y, MoveDir.Down);
                    f.ForceStream();
                    f.Memory.Mark("Stream y=" + y);
                    sb.AppendLine("  y=" + y + ": Blöcke " + f.Streamer.Loaded.Count + ", geladen " + f.Streamer.LoadCount + ", entladen " + f.Streamer.UnloadCount + ", " + f.Memory.Entries[f.Memory.Entries.Count - 1]);
                }
                sb.AppendLine("Spitze gleichzeitig geladener Blöcke: " + f.Streamer.PeakLoaded);

                // Gebietswechsel: Hakutai (Zone 54, area003), anderes Bundle → Karte entladen und laden.
                clock.Restart();
                var e2 = f.SwitchZone(54);
                Drive(f, e2);
                sb.AppendLine("Gebietswechsel 422 -> 54: " + clock.ElapsedMilliseconds + " ms, " + Cell(f) + ", Loaded=" + f.Loaded + " Fehler=" + f.Error + ", Blöcke " + f.Streamer.Loaded.Count);
                sb.AppendLine("  Bericht: " + Last(f));
                clock.Restart();
                Drive(f, f.SwitchZone(425));
                sb.AppendLine("Wechsel 54 -> 425: " + clock.ElapsedMilliseconds + " ms, " + Cell(f) + ", Loaded=" + f.Loaded + " Fehler=" + f.Error);
                sb.AppendLine("  Bericht: " + Last(f));

                sb.AppendLine("--- Speicherprotokoll ---");
                sb.AppendLine(f.Memory.ToString());
                sb.AppendLine("Wechsel gesamt: " + f.TransitionsDone);
                f.Unload();
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
                if (Xnu.Input.GameInput.Instance != null) UnityEngine.Object.DestroyImmediate(Xnu.Input.GameInput.Instance.gameObject);
                var cam = GameObject.Find("FieldCamera");
                if (cam != null) UnityEngine.Object.DestroyImmediate(cam);
            }
            return sb.ToString();
        }

        static string Last(FieldController f) => f.TransitionReports.Count > 0 ? f.TransitionReports[f.TransitionReports.Count - 1] : "(keiner)";

        static int CountAvail(FieldController f)
        {
            var n = 0;
            foreach (var _ in f.Streamer.Available) n++;
            return n;
        }
    }
}
