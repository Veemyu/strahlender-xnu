// Verifikation der Stubs im Wegwerf-Projekt work/unity-stubs (Editor-Skript, wird von scripts/stub_verify.py hineinkopiert).
//   Unity -batchmode -nographics -projectPath work/unity-stubs -executeMethod StubProbe.Run -stubPlan <plan.json> -quit
// Laedt Bundles (nie Shader-Bundles), zaehlt fehlende Skripte, Stub-Komponenten, Konsolenfehler, Zeit/Speicher und
// vergleicht Feldwerte ausgewaehlter Instanzen mit den erwarteten Werten aus dem TypeTree (Plan, von Python erzeugt).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

public static class StubProbe
{
    [Serializable] public class Expect { public string bundle; public long pathId; public string cls; public string[] paths; public string[] vals; }
    [Serializable] public class Group { public string name; public string[] load; public string[] main; }
    [Serializable] public class Plan { public string root; public string report; public bool light; public Group[] groups; public Expect[] expects; }

    [Serializable] public class ClassStat { public string cls; public int samples; public int samplesFound; public int leaves; public int match; public int mismatch; public int missing; public int ptrUnresolved; public int fullyEqual; public string[] badPaths = new string[0]; }
    [Serializable] public class GroupResult
    {
        public string name; public int bundlesLoaded; public int bundlesNull; public double loadMs; public double assetsMs;
        public int prefabs; public int gameObjects; public int components; public int missingScripts; public int stubComponents;
        public int scriptableObjects; public int scriptableObjectsStub; public int scenesOpened; public int sceneErrors;
        public long managedBefore; public long managedAfter; public long nativeAfter;
        public string[] nullBundles;
    }
    [Serializable] public class Result
    {
        public GroupResult[] groups; public ClassStat[] classes; public string[] errors; public int errorCount; public int warningCount;
        public string[] errorKinds; public int[] errorKindCounts; public int expectTotal; public int expectFound;
    }

    static readonly List<string> errs = new List<string>();
    static readonly Dictionary<string, int> errKinds = new Dictionary<string, int>();
    static int errCount, warnCount;

    static string Arg(string name)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
        return null;
    }

    static void OnLog(string msg, string stack, LogType t)
    {
        if (t == LogType.Warning) { warnCount++; return; }
        if (t == LogType.Log) return;
        errCount++;
        var line = msg.Split('\n')[0];
        var kind = System.Text.RegularExpressions.Regex.Replace(line, "[0-9]+", "#");
        if (kind.Length > 140) kind = kind.Substring(0, 140);
        errKinds.TryGetValue(kind, out var c); errKinds[kind] = c + 1;
        if (errs.Count < 40) errs.Add(line.Length > 300 ? line.Substring(0, 300) : line);
    }

    public static void BridgeRun()
    {
        int code = 0;
        try
        {
            var plan = JsonUtility.FromJson<Plan>(File.ReadAllText(Arg("-stubPlan")));
            Application.logMessageReceived += OnLog;
            Group g = null;
            foreach (var x in plan.groups) if (x.name == (Arg("-bridgeGroup") ?? "ui")) g = x;
            if (g == null) throw new Exception("Gruppe fehlt");
            AssetBundle.UnloadAllAssetBundles(true);
            foreach (var rel in g.load) AssetBundle.LoadFromFile(Path.Combine(plan.root, rel));
            int hosts = 0, prefabsWithHost = 0, afterAttach = 0, fieldSum = 0, afterDestroy = -1;
            GameObject first = null;
            foreach (var rel in g.main)
            {
                foreach (var ab in AssetBundle.GetAllLoadedAssetBundles())
                {
                    foreach (var name in ab.GetAllAssetNames())
                    {
                        if (!name.EndsWith(".prefab")) continue;
                        var go = ab.LoadAsset<GameObject>(name);
                        if (go == null) continue;
                        var hs = go.GetComponentsInChildren<Xnu.Bridge.IBridgeHost>(true);
                        if (hs.Length == 0) continue;
                        hosts += hs.Length; prefabsWithHost++;
                        if (first == null) first = go;
                    }
                }
            }
            if (first != null)
            {
                var inst = UnityEngine.Object.Instantiate(first);
                afterAttach = Xnu.Bridge.BridgeHub.Hosts.Count;
                fieldSum = Xnu.Bridge.BridgeHub.SumFields(Xnu.Bridge.BridgeHub.Hosts);
                UnityEngine.Object.DestroyImmediate(inst);
                afterDestroy = Xnu.Bridge.BridgeHub.Hosts.Count;
            }
            var text = "hosts_in_prefabs=" + hosts + "\nprefabs_with_host=" + prefabsWithHost + "\nattached_after_instantiate=" + afterAttach +
                       "\nnotified=" + Xnu.Bridge.BridgeHub.Notified + "\nfield_count_sum=" + fieldSum + "\nattached_after_destroy=" + afterDestroy +
                       "\nconsole_errors=" + errCount + "\n";
            File.WriteAllText(plan.report + ".bridge.txt", text);
            AssetBundle.UnloadAllAssetBundles(true);
        }
        catch (Exception e) { Console.WriteLine("BridgeRun-Fehler: " + e); code = 2; }
        EditorApplication.Exit(code);
    }

    public static void Run()
    {
        int code = 0;
        try
        {
            var plan = JsonUtility.FromJson<Plan>(File.ReadAllText(Arg("-stubPlan")));
            Application.logMessageReceived += OnLog;
            var res = new Result();
            var gres = new List<GroupResult>();
            var cstats = new Dictionary<string, ClassStat>();
            foreach (var g in plan.groups) gres.Add(RunGroup(plan, g, cstats, res));
            res.groups = gres.ToArray();
            var cl = new List<ClassStat>(cstats.Values);
            cl.Sort((x, y) => string.CompareOrdinal(x.cls, y.cls));
            res.classes = cl.ToArray();
            res.errors = errs.ToArray(); res.errorCount = errCount; res.warningCount = warnCount;
            var kinds = new List<string>(errKinds.Keys); kinds.Sort();
            res.errorKinds = kinds.ToArray();
            res.errorKindCounts = new int[kinds.Count];
            for (int i = 0; i < kinds.Count; i++) res.errorKindCounts[i] = errKinds[kinds[i]];
            File.WriteAllText(plan.report, JsonUtility.ToJson(res, true));
        }
        catch (Exception e)
        {
            Console.WriteLine("StubProbe-Fehler: " + e);
            code = 2;
        }
        EditorApplication.Exit(code);
    }

    static bool IsStub(UnityEngine.Object o) =>
        o != null && o.GetType().Assembly.GetName().Name == "Assembly-CSharp";

    static GroupResult RunGroup(Plan plan, Group g, Dictionary<string, ClassStat> cstats, Result res)
    {
        var r = new GroupResult { name = g.name };
        AssetBundle.UnloadAllAssetBundles(true);
        if (!plan.light) { GC.Collect(); r.managedBefore = GC.GetTotalMemory(true); }
        var sw = Stopwatch.StartNew();
        var byName = new Dictionary<string, AssetBundle>();
        var nulls = new List<string>();
        foreach (var rel in g.load)
        {
            var ab = AssetBundle.LoadFromFile(Path.Combine(plan.root, rel));
            if (ab == null) { r.bundlesNull++; nulls.Add(rel); continue; }
            r.bundlesLoaded++;
            byName[rel] = ab;
        }
        r.loadMs = sw.Elapsed.TotalMilliseconds;
        sw.Restart();
        var local = new Dictionary<(string, long), UnityEngine.Object>();
        foreach (var rel in g.main)
        {
            if (!byName.TryGetValue(rel, out var ab)) continue;
            if (ab.isStreamedSceneAssetBundle)
            {
                foreach (var sp in ab.GetAllScenePaths())
                {
                    try
                    {
                        var sc = UnityEditor.SceneManagement.EditorSceneManager.OpenScene(sp, UnityEditor.SceneManagement.OpenSceneMode.Single);
                        r.scenesOpened++;
                        foreach (var root in sc.GetRootGameObjects())
                        {
                            foreach (var t in root.GetComponentsInChildren<Transform>(true)) r.gameObjects++;
                            foreach (var c in root.GetComponentsInChildren<Component>(true))
                            {
                                r.components++;
                                if (c == null) { r.missingScripts++; continue; }
                                if (IsStub(c)) r.stubComponents++;
                            }
                        }
                    }
                    catch (Exception ex) { r.sceneErrors++; Debug.Log("Szene nicht oeffenbar: " + ex.Message.Split('\n')[0]); }
                }
                continue;
            }
            foreach (var name in ab.GetAllAssetNames())
            {
                if (name.EndsWith(".prefab"))
                {
                    var go = ab.LoadAsset<GameObject>(name);
                    if (go == null) continue;
                    r.prefabs++;
                    foreach (var t in go.GetComponentsInChildren<Transform>(true)) r.gameObjects++;
                    foreach (var c in go.GetComponentsInChildren<Component>(true))
                    {
                        r.components++;
                        if (c == null) { r.missingScripts++; continue; }
                        if (IsStub(c)) { r.stubComponents++; Register(local, rel, c); }
                    }
                }
            }
            foreach (var so in ab.LoadAllAssets<ScriptableObject>())
            {
                r.scriptableObjects++;
                if (IsStub(so)) { r.scriptableObjectsStub++; Register(local, rel, so); }
            }
        }
        r.assetsMs = sw.Elapsed.TotalMilliseconds;
        foreach (var e in plan.expects)
        {
            if (Array.IndexOf(g.main, e.bundle) < 0) continue;
            Compare(e, local, cstats, res);
        }
        r.managedAfter = GC.GetTotalMemory(false);
        r.nativeAfter = UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();
        r.nullBundles = nulls.ToArray();
        AssetBundle.UnloadAllAssetBundles(true);
        return r;
    }

    static void Register(Dictionary<(string, long), UnityEngine.Object> map, string bundle, UnityEngine.Object o)
    {
        long id = unchecked((long)Unsupported.GetLocalIdentifierInFileForPersistentObject(o));
        if (id != 0) map[(bundle, id)] = o;
    }

    static void Compare(Expect e, Dictionary<(string, long), UnityEngine.Object> local, Dictionary<string, ClassStat> cstats, Result res)
    {
        if (!cstats.TryGetValue(e.cls, out var cs)) { cs = new ClassStat { cls = e.cls }; cstats[e.cls] = cs; }
        cs.samples++; res.expectTotal++;
        if (!local.TryGetValue((e.bundle, e.pathId), out var obj) || obj == null) return;
        cs.samplesFound++; res.expectFound++;
        var actual = new Dictionary<string, string>();
        try { Collect(new SerializedObject(obj), actual); } catch (Exception ex) { Debug.Log("Collect: " + ex.Message); return; }
        bool all = true;
        for (int i = 0; i < e.paths.Length; i++)
        {
            cs.leaves++;
            if (!actual.TryGetValue(e.paths[i], out var v)) { cs.missing++; all = false; AddBad(cs, "fehlt:" + e.paths[i]); continue; }
            if (Same(e.vals[i], v)) cs.match++;
            else if (e.vals[i] == "ptr:set" && v == "ptr:null") { cs.ptrUnresolved++; all = false; AddBad(cs, "ptr:" + e.paths[i]); }
            else { cs.mismatch++; all = false; AddBad(cs, "wert:" + e.paths[i]); }
        }
        if (all) cs.fullyEqual++;
    }

    static void AddBad(ClassStat cs, string s)
    {
        if (cs.badPaths.Length >= 5) return;
        var l = new List<string>(cs.badPaths) { s };
        cs.badPaths = l.ToArray();
    }

    static bool Same(string a, string b)
    {
        if (a == b) return true;
        if (double.TryParse(a, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var x) &&
            double.TryParse(b, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var y))
            return Math.Abs(x - y) <= 1e-5 * Math.Max(1.0, Math.Abs(x));
        return false;
    }

    static void Collect(SerializedObject so, Dictionary<string, string> d)
    {
        var it = so.GetIterator();
        bool enter = true;
        while (it.Next(enter))
        {
            enter = true;
            string p = it.propertyPath;
            switch (it.propertyType)
            {
                case SerializedPropertyType.Integer:
                case SerializedPropertyType.Character:
                case SerializedPropertyType.LayerMask:
                case SerializedPropertyType.ArraySize:
                case SerializedPropertyType.Enum:
                    d[p] = it.longValue.ToString(); break;
                case SerializedPropertyType.Boolean: d[p] = it.boolValue ? "1" : "0"; break;
                case SerializedPropertyType.Float: d[p] = it.doubleValue.ToString("R", System.Globalization.CultureInfo.InvariantCulture); break;
                case SerializedPropertyType.String: d[p] = it.stringValue; enter = false; break;
                case SerializedPropertyType.ObjectReference:
                    d[p] = it.objectReferenceInstanceIDValue != 0 ? "ptr:set" : "ptr:null"; enter = false; break;
            }
        }
    }
}
