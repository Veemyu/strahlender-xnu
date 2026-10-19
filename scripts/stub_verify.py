#!/usr/bin/env python3
"""Verifikation der erzeugten Stubs im Wegwerf-Unity-Projekt (work/unity-stubs): Bundles laden, Missing Script
zaehlen (vorher/nachher), Feldwerte gegen den TypeTree vergleichen, Konsolenfehler, Ladezeit, Speicher.

Aufruf (nur ein Editor/Batch zugleich fuer dieses Projekt; die Editoren auf unity/ und work/unity-shader-lab bleiben unberuehrt):
    python3 scripts/stub_verify.py --phase both
Ergebnisse: work/stubs/verify_before.json, verify_after.json, plan.json. Shader-Bundles werden nie geladen.
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_gen  # noqa: E402

ROOT = stub_gen.ROOT
ASSETS = stub_gen.ASSETS
UNITY = "/Applications/Unity/Hub/Editor/6000.3.26f1/Unity.app/Contents/MacOS/Unity"
SHADER_NAMES = {"shaders", "fxparticle", "tmpshader"}
BUILTIN_KEYS = {"m_GameObject", "m_Enabled", "m_Script", "m_Name", "m_EditorHideFlags", "m_EditorClassIdentifier",
                "m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance", "m_PrefabAsset"}
MAX_PATHS_PER_SAMPLE = 400


def rel(p):
    return os.path.relpath(p, ASSETS).replace(os.sep, "/")


def is_shader_bundle(r):
    return os.path.basename(r).split(".")[0] in SHADER_NAMES


def dep_closure(mains, bundles):
    """Ladereihenfolge (Abhaengigkeiten zuerst) ueber CAB-Namen; Sprachvarianten: je CAB eine, bevorzugt '.ge'."""
    cab_to = collections.defaultdict(list)
    for b, info in bundles.items():
        for c in info["cabs"]:
            cab_to[c].append(b)
    order, seen = [], set()

    def pick(c):
        cands = sorted(cab_to.get(c, []))
        cands = [x for x in cands if not is_shader_bundle(x)]
        for x in cands:
            if x.endswith(".ge"):
                return x
        return cands[0] if cands else None

    def visit(b):
        if b in seen:
            return
        seen.add(b)
        for d in bundles[b]["deps"]:
            t = pick(d)
            if t is not None and t != b:
                visit(t)
        order.append(b)

    for m in mains:
        visit(m)
    return order


def leaf_paths(prefix, v, out):
    if isinstance(v, dict):
        if "m_FileID" in v and "m_PathID" in v and len(v) <= 2:
            out.append((prefix, "ptr:set" if v["m_PathID"] != 0 else "ptr:null"))
            return
        for k, x in v.items():
            leaf_paths(prefix + "." + k if prefix else k, x, out)
    elif isinstance(v, (list, tuple)):
        out.append((prefix + ".Array.size", str(len(v))))
        for i, x in enumerate(v):
            leaf_paths("%s.Array.data[%d]" % (prefix, i), x, out)
    elif isinstance(v, bool):
        out.append((prefix, "1" if v else "0"))
    elif isinstance(v, int):
        out.append((prefix, str(v)))
    elif isinstance(v, float):
        out.append((prefix, repr(v)))
    elif isinstance(v, str):
        out.append((prefix, v))


def samples_for(bundle_rel, per_class, only=None):
    sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
    import UnityPy
    env = UnityPy.load(os.path.join(ASSETS, bundle_rel))
    out = []
    count = collections.Counter()
    for f in env.files.values():
        files = [f] if getattr(f, "objects", None) is not None else list(getattr(f, "files", {}).values())
        for sf in files:
            if getattr(sf, "objects", None) is None:
                continue
            scripts = {}
            for pid, o in sf.objects.items():
                if o.type.name == "MonoScript":
                    s = o.read()
                    scripts[pid] = (s.m_AssemblyName, s.m_Namespace, s.m_ClassName)
            for pid, o in sf.objects.items():
                if o.type.name != "MonoBehaviour":
                    continue
                st = o.serialized_type
                if st is None or st.node is None or not st.node.m_Children:
                    continue
                idx = st.script_type_index
                sc = sf.script_types[idx] if idx is not None and 0 <= idx < len(sf.script_types) else None
                if sc is None or sc.local_serialized_file_index != 0:
                    continue
                info = scripts.get(sc.local_identifier_in_file)
                if info is None or info[0] != "Assembly-CSharp.dll":
                    continue
                key = "%s.%s" % (info[1], info[2]) if info[1] else info[2]
                if only is not None and key not in only:
                    continue
                if count[key] >= per_class:
                    continue
                count[key] += 1
                try:
                    tree = o.read_typetree()
                except Exception:  # noqa: BLE001
                    continue
                pairs = []
                for k, v in tree.items():
                    if k in BUILTIN_KEYS:
                        continue
                    leaf_paths(k, v, pairs)
                pairs = pairs[:MAX_PATHS_PER_SAMPLE]
                out.append({"bundle": bundle_rel, "pathId": pid, "cls": key,
                            "paths": [p for p, _ in pairs], "vals": [v for _, v in pairs]})
    return out


def pick_candidates(group_dir, limit_mb, max_try):
    d = os.path.join(ASSETS, group_dir)
    files = []
    for dp, _, fn in os.walk(d):
        for f in sorted(fn):
            p = os.path.join(dp, f)
            if os.path.getsize(p) <= limit_mb * 1048576 and not f.endswith(".manifest"):
                files.append(p)
    files.sort(key=lambda p: (os.path.getsize(p), p))
    found = []
    for p in files[:max_try]:
        r = stub_gen.scan_file(p)
        n = 0
        for u in r["uses"]:
            info = r["scripts"].get(u["script"]) if u["script"] else None
            if info and info[0] == "Assembly-CSharp.dll":
                n += u["n"]
        if n:
            found.append((n, rel(p)))
    found.sort(key=lambda x: (-x[0], x[1]))
    return found


def build_plan(args):
    with open(args.scan, encoding="utf-8") as f:
        scan = json.load(f)
    bundles = scan["bundles"]
    mains = {
        "ui": ["UIs/ui/uiresidentwindow"],
        "umgebung": ["Environments/fields/area001"],
        "event": ["Dpr/ev_script"],
        "stammdaten": ["Dpr/masterdatas", "Battle/battle_masterdatas"],
    }
    ch = pick_candidates("Characters", 40, 60)
    sc = pick_candidates("Dpr/scenes", 80, 12)
    if ch:
        mains["charakter"] = [ch[0][1]]
    if sc:
        mains["szene"] = [sc[0][1]]
    groups, expects = [], []
    for name, ms in mains.items():
        ms = [m for m in ms if m in bundles]
        load = dep_closure(ms, bundles)
        groups.append({"name": name, "load": load, "main": ms})
        for m in ms:
            expects.extend(samples_for(m, args.per_class))
    return {"root": ASSETS, "report": os.path.join(ROOT, "work", "stubs", "verify_report.json"),
            "groups": groups, "expects": expects}


def run_unity(project, plan_path, log, timeout):
    cmd = [UNITY, "-batchmode", "-nographics", "-projectPath", project, "-logFile", log,
           "-executeMethod", "StubProbe.Run", "-stubPlan", plan_path, "-quit"]
    t = time.time()
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    return p.returncode, time.time() - t


def summarize(res):
    cls = res.get("classes", [])
    leaves = sum(c["leaves"] for c in cls)
    match = sum(c["match"] for c in cls)
    return {
        "samples": sum(c["samples"] for c in cls), "found": sum(c["samplesFound"] for c in cls),
        "leaves": leaves, "match": match, "mismatch": sum(c["mismatch"] for c in cls),
        "missing": sum(c["missing"] for c in cls), "ptr_unresolved": sum(c["ptrUnresolved"] for c in cls),
        "match_percent": round(100.0 * match / leaves, 2) if leaves else None,
        "classes_with_samples": len(cls),
        "classes_fully_equal": sum(1 for c in cls if c["samplesFound"] and c["fullyEqual"] == c["samplesFound"]),
        "errors": res.get("errorCount"), "warnings": res.get("warningCount"),
    }


def build_bulk_plan(args):
    """Ein Bundle je Gruppe (ohne Erwartungen): Missing-Script-Zaehlung ueber viele Bundles."""
    with open(args.scan, encoding="utf-8") as f:
        bundles = json.load(f)["bundles"]
    tops = [t.strip() for t in args.bulk.split(",") if t.strip()]
    groups = []
    for b in sorted(bundles):
        if b.split("/")[0] not in tops or is_shader_bundle(b):
            continue
        if os.path.getsize(os.path.join(ASSETS, b)) > args.bulk_max_mb * 1048576:
            continue
        if len(b.rsplit(".", 1)) == 2 and len(b.rsplit(".", 1)[1]) == 2 and "/" not in b.rsplit(".", 1)[1] and not b.endswith(".ge"):
            continue
        groups.append({"name": b, "load": dep_closure([b], bundles), "main": [b]})
    return {"root": ASSETS, "report": os.path.join(ROOT, "work", "stubs", "verify_report.json"), "light": True,
            "groups": groups, "expects": []}


def summarize_bulk(res):
    top = collections.defaultdict(lambda: collections.Counter())
    worst = []
    for g in res.get("groups", []):
        t = g["name"].split("/")[0]
        c = top[t]
        c["bundles"] += 1
        c["null"] += g["bundlesNull"]
        for k in ("prefabs", "components", "missingScripts", "stubComponents", "scriptableObjects", "scriptableObjectsStub"):
            c[k] += g[k]
        c["ms"] += g["loadMs"] + g["assetsMs"]
        if g["missingScripts"]:
            worst.append((g["missingScripts"], g["name"]))
    return {t: dict(c) for t, c in top.items()}, sorted(worst, reverse=True)[:8]


def run_bridge(a, plan_path, out_dir):
    """Bruecken-Test: handgeschriebener partial-Teil eines Stubs (Assembly-CSharp) implementiert eine Schnittstelle der
    asmdef-Assembly Xnu.Bridge und meldet sich in Awake/OnDestroy dort an; Logik sieht nur die Schnittstelle."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    with open(os.path.join(a.project, "Assets", "XnuStubs", "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    ui_classes = {e["cls"] for e in plan["expects"] if e["bundle"] in next(g["main"] for g in plan["groups"] if g["name"] == "ui")}
    pick = None
    for c in sorted(man["classes"], key=lambda c: -c["instances"]):
        full = (c["namespace"] + "." + c["name"]) if c["namespace"] else c["name"]
        if c["origin"] == "script" and c["kind"] == "class" and not c["abstract"] and c["base"] == "global::UnityEngine.MonoBehaviour" \
                and full in ui_classes and "<" not in c["name"] and "." not in c["name"]:
            pick = c
            break
    if pick is None:
        print("Bruecke: keine geeignete Klasse gefunden")
        return
    bdir = os.path.join(a.project, "Assets", "XnuBridge")
    os.makedirs(bdir, exist_ok=True)
    for fn in os.listdir(os.path.join(HERE, "stub_bridge")):
        shutil.copyfile(os.path.join(HERE, "stub_bridge", fn), os.path.join(bdir, fn))
    ns = pick["namespace"]
    body = ("[global::UnityEngine.ExecuteAlways]\npublic partial class %s : global::Xnu.Bridge.IBridgeHost\n{\n"
            "    public int BridgeFieldCount => GetType().GetFields(global::System.Reflection.BindingFlags.Instance | "
            "global::System.Reflection.BindingFlags.Public | global::System.Reflection.BindingFlags.NonPublic | "
            "global::System.Reflection.BindingFlags.DeclaredOnly).Length;\n"
            "    private void Awake() { global::Xnu.Bridge.BridgeHub.Attach(this); }\n"
            "    private void OnDestroy() { global::Xnu.Bridge.BridgeHub.Detach(this); }\n}\n") % pick["name"]
    text = ("namespace %s\n{\n%s}\n" % (ns, body)) if ns else body
    hdir = os.path.join(a.project, "Assets", "XnuBridgeHooks")  # ohne asmdef = Assembly-CSharp, getrennt vom asmdef-Ordner
    os.makedirs(hdir, exist_ok=True)
    with open(os.path.join(hdir, "BridgeHook.cs"), "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [UNITY, "-batchmode", "-nographics", "-projectPath", a.project, "-logFile", os.path.join(out_dir, "unity_bridge.log"),
           "-executeMethod", "StubProbe.BridgeRun", "-stubPlan", plan_path, "-quit"]
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=a.timeout)
    rp = plan["report"] + ".bridge.txt"
    print("== Bruecke: Exit %s" % p.returncode)
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            print(f.read().strip())


def build_coverage_plan(args):
    """Gierige Bundle-Auswahl, die moeglichst jede Assembly-CSharp-Klasse mit TypeTree mindestens einmal enthaelt."""
    with open(args.scan, encoding="utf-8") as f:
        scan = json.load(f)
    bundles = scan["bundles"]
    want = {k for k, c in scan["classes"].items() if k.startswith("Assembly-CSharp.dll|") and any(h != "-" for h in c["schemas"])}
    cand = {}
    for b, info in bundles.items():
        if is_shader_bundle(b) or b.startswith("Dpr/scenes/") or not info.get("classes"):
            continue
        if os.path.getsize(os.path.join(ASSETS, b)) > args.bulk_max_mb * 1048576:
            continue
        cand[b] = {k for k in info["classes"] if k in want}
    chosen = []
    left = set(want)
    while left:
        best = max(sorted(cand), key=lambda b: (len(cand[b] & left), -os.path.getsize(os.path.join(ASSETS, b))), default=None)
        if best is None or not (cand[best] & left):
            break
        chosen.append((best, cand[best] & left))
        left -= cand[best]
    groups, expects = [], []
    for b, ks in chosen:
        groups.append({"name": b, "load": dep_closure([b], bundles), "main": [b]})
        only = {k.split("|")[1] + "." + k.split("|")[2] if k.split("|")[1] else k.split("|")[2] for k in ks}
        expects.extend(samples_for(b, args.per_class, only))
    print("Abdeckung: %d von %d Klassen in %d Bundles erreichbar, %d ohne ladbares Bundle" % (
        len(want) - len(left), len(want), len(chosen), len(left)))
    return {"root": ASSETS, "report": os.path.join(ROOT, "work", "stubs", "verify_report.json"), "light": True,
            "groups": groups, "expects": expects}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", default=stub_gen.DEFAULT_SCAN)
    ap.add_argument("--project", default=os.path.join(ROOT, "work", "unity-stubs"))
    ap.add_argument("--phase", choices=["before", "after", "both", "plan", "bridge"], default="both")
    ap.add_argument("--per-class", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--bulk", default="", help="Kommaliste von Oberordnern: je Bundle eine Gruppe, nur Zaehlung")
    ap.add_argument("--bulk-max-mb", type=int, default=60)
    ap.add_argument("--coverage", action="store_true", help="je Klasse ein Sample (gierige Bundle-Auswahl), nur Phase after")
    a = ap.parse_args()
    out_dir = os.path.join(ROOT, "work", "stubs")
    plan_path = os.path.join(out_dir, "plan_bulk.json" if a.bulk else "plan_cov.json" if a.coverage else "plan.json")
    if a.coverage:
        plan = build_coverage_plan(a)
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        print("Abdeckungs-Plan: %d Bundles, %d Erwartungen" % (len(plan["groups"]), len(plan["expects"])))
    elif a.bulk:
        plan = build_bulk_plan(a)
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        print("Bulk-Plan: %d Bundles" % len(plan["groups"]))
    elif not os.path.exists(plan_path) or a.phase == "plan":
        plan = build_plan(a)
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        print("Plan: %d Gruppen, %d Erwartungen" % (len(plan["groups"]), len(plan["expects"])))
        for g in plan["groups"]:
            print("  %-10s main=%s, laden=%d Bundles" % (g["name"], g["main"], len(g["load"])))
        if a.phase == "plan":
            return
    ed = os.path.join(a.project, "Assets", "Editor")
    os.makedirs(ed, exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "stub_probe.cs"), os.path.join(ed, "StubProbe.cs"))
    bdir = os.path.join(a.project, "Assets", "XnuBridge")
    os.makedirs(bdir, exist_ok=True)
    for fn in os.listdir(os.path.join(HERE, "stub_bridge")):
        shutil.copyfile(os.path.join(HERE, "stub_bridge", fn), os.path.join(bdir, fn))
    if a.phase == "bridge":
        run_bridge(a, plan_path, out_dir)
        return
    stubs = os.path.join(a.project, "Assets", "XnuStubs")
    parked = os.path.join(a.project, "_XnuStubs_parked")
    phases = ["before", "after"] if a.phase == "both" else [a.phase]
    for ph in phases:
        moved = False
        if ph == "before" and os.path.isdir(stubs):
            shutil.move(stubs, parked)
            if os.path.exists(stubs + ".meta"):
                os.remove(stubs + ".meta")
            moved = True
        try:
            rc, secs = run_unity(a.project, plan_path, os.path.join(out_dir, "unity_%s.log" % ph), a.timeout)
        finally:
            if moved:
                shutil.move(parked, stubs)
        rp = os.path.join(out_dir, "verify_report.json")
        res = {}
        if os.path.exists(rp):
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
            os.replace(rp, os.path.join(out_dir, "verify_%s.json" % ph))
        print("== Phase %s: Exit %s, %.0f s" % (ph, rc, secs))
        if a.coverage:
            os.replace(os.path.join(out_dir, "verify_%s.json" % ph), os.path.join(out_dir, "verify_cov_%s.json" % ph))
            print("  Feldbindung:", json.dumps(summarize(res)))
            bad = [c for c in res.get("classes", []) if c["samplesFound"] and c["fullyEqual"] < c["samplesFound"]]
            lost = [c for c in res.get("classes", []) if not c["samplesFound"]]
            print("  Klassen mit Abweichung: %d, Klassen ohne gefundenes Sample: %d" % (len(bad), len(lost)))
            for c in bad[:15]:
                print("    %s: %d/%d Blaetter, %s" % (c["cls"], c["match"], c["leaves"], c["badPaths"][:3]))
            continue
        if a.bulk:
            os.replace(os.path.join(out_dir, "verify_%s.json" % ph), os.path.join(out_dir, "verify_bulk_%s.json" % ph))
            tops, worst = summarize_bulk(res)
            for t, c in sorted(tops.items()):
                print("  %-18s %s" % (t, json.dumps(c)))
            print("  groesste Missing-Zahlen:", worst)
            print("  Konsole: Fehler %s, Warnungen %s" % (res.get("errorCount"), res.get("warningCount")))
            for k, n in list(zip(res.get("errorKinds", []), res.get("errorKindCounts", [])))[:10]:
                print("    %5d x %s" % (n, k))
            continue
        for g in res.get("groups", []):
            print("  %-10s Bundles %d (null %d), Prefabs %d, Komponenten %d, Missing %d, Stub-Komp. %d, SO %d (Stub %d), "
                  "Laden %.0f ms, Assets %.0f ms, Heap %+.1f MB, nativ %.0f MB" % (
                      g["name"], g["bundlesLoaded"], g["bundlesNull"], g["prefabs"], g["components"], g["missingScripts"],
                      g["stubComponents"], g["scriptableObjects"], g["scriptableObjectsStub"], g["loadMs"], g["assetsMs"],
                      (g["managedAfter"] - g["managedBefore"]) / 1048576.0, g["nativeAfter"] / 1048576.0))
        print("  Feldbindung:", json.dumps(summarize(res)))


if __name__ == "__main__":
    main()
