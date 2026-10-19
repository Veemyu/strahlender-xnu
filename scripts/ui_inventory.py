#!/usr/bin/env python3
"""Inventar der UI-Bundles und -Assets (Analysephase ap-ui). Liest nur Katalog (work/dpr_catalog.json) und
Bundle-Objektlisten per UnityPy; liest nie Audio-Objekte, schreibt nur unter work/ui (gitignored).

Befehle:
    catalog   Katalog-Statistik je Projekt/Gruppe/Dateiendung -> work/ui/catalog_stats.json
    bundles   UnityPy-Objekttypen je UI-relevantem Bundle     -> work/ui/bundle_types.json
              (--limit N begrenzt die Zahl der geoeffneten Bundles je Gruppe)
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
CATALOG = os.path.join(ROOT, "work", "dpr_catalog.json")
ASSETS = os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant")
OUT = os.path.join(ROOT, "work", "ui")


def ext(path):
    base = path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1] if "." in base else ""


def group_of(rec):
    """Gruppe = Projekt plus erste ein bis zwei Pfadsegmente des Bundle-Namens."""
    parts = rec["n"].split("/")
    if rec["p"] == "UIs":
        return "UIs/" + (parts[0] if len(parts) > 1 else "(root)")
    if rec["p"] == "Message":
        return "Message"
    return rec["p"] + "/" + (parts[0] if len(parts) > 1 else "(root)")


def load_catalog():
    with open(CATALOG, encoding="utf-8") as f:
        return json.load(f)


def cmd_catalog():
    cat = load_catalog()
    recs = cat["recs"]
    out = {}
    # alle UIs-Bundles, Message, plus Bundles ausserhalb mit ui-ahnlichem Namen
    sel = [r for r in recs if r["p"] in ("UIs", "Message")]
    ui_like = [r for r in recs if r["p"] not in ("UIs", "Message") and any(
        k in r["n"].lower() for k in ("/ui", "ui/", "font", "tmp", "textmesh", "msgwindow", "atlas", "sprite", "graphictext"))]
    for name, subset in (("UIs_Message", sel), ("andere_ui_aehnlich", ui_like)):
        grp = collections.defaultdict(lambda: {"bundles": 0, "bytes": 0, "assets": 0, "ext": collections.Counter()})
        for r in subset:
            g = grp[group_of(r)]
            g["bundles"] += 1
            g["bytes"] += r["size"]
            for a in r["ap"] or []:
                g["assets"] += 1
                g["ext"][ext(a)] += 1
        out[name] = {k: {"bundles": v["bundles"], "bytes": v["bytes"], "assets": v["assets"], "ext": dict(v["ext"])}
                     for k, v in sorted(grp.items())}
        print("==", name, len(subset), "Bundles", sum(r["size"] for r in subset), "Bytes")
        for k, v in sorted(out[name].items()):
            print("%-45s %5d B  %9.1f MiB  %6d Assets  %s" % (k, v["bundles"], v["bytes"] / 1048576, v["assets"], dict(sorted(v["ext"].items(), key=lambda x: -x[1])[:6])))
    # Sprachvarianten
    variants = collections.Counter(v.rsplit(".", 1)[-1] for v in cat["variants"])
    out["variants"] = dict(variants)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "catalog_stats.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


def cmd_bundles(limit):
    import UnityPy
    cat = load_catalog()
    recs = [r for r in cat["recs"] if r["p"] == "UIs"]
    per_group = collections.defaultdict(list)
    for r in recs:
        per_group[group_of(r)].append(r)
    result = {}
    skip = {"AudioClip", "AudioManager"}
    for g, lst in sorted(per_group.items()):
        lst = sorted(lst, key=lambda r: r["n"])
        if limit and len(lst) > limit:
            step = len(lst) / limit
            lst = [lst[int(i * step)] for i in range(limit)]
        types = collections.Counter()
        scripts = collections.Counter()
        opened = 0
        for r in lst:
            path = os.path.join(ASSETS, r["p"], r["n"])
            if not os.path.isfile(path):
                continue
            try:
                env = UnityPy.load(path)
            except Exception as e:  # noqa: BLE001
                types["LOADFEHLER:" + type(e).__name__] += 1
                continue
            opened += 1
            for o in env.objects:
                tn = o.type.name
                if tn in skip:
                    continue
                types[tn] += 1
        result[g] = {"geoeffnet": opened, "von": len(per_group[g]), "typen": dict(types.most_common())}
        print(g, opened, "/", len(per_group[g]), dict(types.most_common(8)))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bundle_types.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)


def script_name(mb):
    try:
        s = mb.m_Script.read()
        return (s.m_Namespace + "." if s.m_Namespace else "") + s.m_ClassName
    except Exception:  # noqa: BLE001
        return None


def cmd_deep():
    """Skriptklassen, Canvas/CanvasScaler und Prefab-Groessen der UI-Prefab-Bundles."""
    import UnityPy
    cat = load_catalog()
    targets = [r for r in cat["recs"] if (r["p"] == "UIs" and r["n"].startswith("ui/")) or r["n"] in ("fieldui/main", "fieldui/gymseq")]
    classes = collections.Counter()
    scalers = collections.Counter()
    canvases = collections.Counter()
    prefabs = []
    for r in targets:
        path = os.path.join(ASSETS, r["p"], r["n"])
        if not os.path.isfile(path):
            continue
        env = UnityPy.load(path)
        counts = collections.Counter()
        for o in env.objects:
            tn = o.type.name
            counts[tn] += 1
            if tn == "MonoBehaviour":
                mb = o.read()
                name = script_name(mb)
                classes[name] += 1
                if name == "UnityEngine.UI.CanvasScaler":
                    t = o.read_typetree()
                    key = (t.get("m_UiScaleMode"), (round(t["m_ReferenceResolution"]["x"]), round(t["m_ReferenceResolution"]["y"])),
                           t.get("m_ScreenMatchMode"), t.get("m_MatchWidthOrHeight"))
                    scalers[key] += 1
            elif tn == "Canvas":
                t = o.read_typetree()
                canvases[(t["m_RenderMode"], t["m_OverrideSorting"])] += 1
        prefabs.append({"bundle": r["n"], "size": r["size"], "objekte": dict(counts.most_common(12)), "deps": len(r["deps"] or [])})
    out = {
        "skriptklassen": dict(classes.most_common()),
        "canvasscaler(uiScaleMode, referenz, matchMode, match)": {str(k): v for k, v in scalers.most_common()},
        "canvas(renderMode, overrideSorting)": {str(k): v for k, v in canvases.most_common()},
        "bundles": prefabs,
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "deep.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("CanvasScaler:", out["canvasscaler(uiScaleMode, referenz, matchMode, match)"])
    print("Canvas:", out["canvas(renderMode, overrideSorting)"])
    print("Skriptklassen:", len(classes), "MonoBehaviours:", sum(classes.values()))
    for k, v in classes.most_common(25):
        print("  ", k, v)


def cmd_windows():
    """Je Prefab-Wurzel (Container) die Hierarchie auswerten: GameObjects, Skriptklassen, Bilder, Animatoren, Canvas."""
    import UnityPy
    cat = load_catalog()
    targets = [r for r in cat["recs"] if (r["p"] == "UIs" and r["n"].startswith("ui/") and not r["n"].startswith("ui/demo")) or r["n"] == "fieldui/main"]
    rows = []
    for r in targets:
        path = os.path.join(ASSETS, r["p"], r["n"])
        if not os.path.isfile(path):
            continue
        env = UnityPy.load(path)
        by_id = {o.path_id: o for o in env.objects}
        go_cache = {}

        def go_components(go_id):
            if go_id not in go_cache:
                t = by_id[go_id].read_typetree()
                go_cache[go_id] = t
            return go_cache[go_id]

        # GameObject -> RectTransform/Transform-Kinder
        tf_of = {}
        for o in env.objects:
            if o.type.name in ("RectTransform", "Transform"):
                t = o.read_typetree()
                tf_of[t["m_GameObject"]["m_PathID"]] = (o.path_id, [c["m_PathID"] for c in t["m_Children"]])
        tf_to_go = {v[0]: k for k, v in tf_of.items()}
        for key, ptr in env.container.items():
            if ptr.type.name != "GameObject":
                continue
            seen = []
            stack = [ptr.path_id]
            comp = collections.Counter()
            while stack:
                gid = stack.pop()
                if gid not in by_id:
                    continue
                seen.append(gid)
                t = go_components(gid)
                for c in t["m_Component"]:
                    co = by_id.get(c["component"]["m_PathID"])
                    if co is None:
                        continue
                    tn = co.type.name
                    if tn == "MonoBehaviour":
                        nm = script_name(co.read())
                        comp[nm or "?"] += 1
                    elif tn not in ("RectTransform", "Transform"):
                        comp[tn] += 1
                if gid in tf_of:
                    for ch in tf_of[gid][1]:
                        if ch in tf_to_go:
                            stack.append(tf_to_go[ch])
            rows.append({"bundle": r["n"], "asset": key, "gameobjects": len(seen), "komponenten": dict(comp.most_common(14)),
                         "image": comp.get("UnityEngine.UI.Image", 0) + comp.get("UnityEngine.UI.RawImage", 0),
                         "text": comp.get("Dpr.UI.UIText", 0) + comp.get("TMPro.TextMeshProUGUI", 0) + comp.get("UnityEngine.UI.Text", 0),
                         "animator": comp.get("Animator", 0), "skripte": sum(v for k, v in comp.items() if k.startswith("Dpr."))})
    rows.sort(key=lambda x: -x["gameobjects"])
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "windows.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    for x in rows:
        print("%-52s %5d GO %4d Img %4d Txt %3d Anim %4d Dpr-Skripte" % (x["asset"], x["gameobjects"], x["image"], x["text"], x["animator"], x["skripte"]))
    print(len(rows), "Prefabs")


def cmd_fonts():
    """TextMeshPro-Schriftassets: Atlasgroesse, Glyph-/Zeichenzahl, Quellschrift, Fallback."""
    import UnityPy
    out = {}
    d = os.path.join(ASSETS, "Dpr", "font")
    for name in sorted(os.listdir(d)):
        env = UnityPy.load(os.path.join(d, name))
        info = {"typen": dict(collections.Counter(o.type.name for o in env.objects)), "fontassets": [], "ttf": [], "atlanten": []}
        for o in env.objects:
            if o.type.name == "Font":
                f = o.read()
                info["ttf"].append({"bytes": len(f.m_FontData or b"")})
            elif o.type.name == "Texture2D":
                f = o.read()
                if f.m_Width:
                    info["atlanten"].append({"name": f.m_Name, "w": f.m_Width, "h": f.m_Height, "format": int(f.m_TextureFormat)})
            elif o.type.name == "MonoBehaviour":
                t = o.read_typetree()
                if "m_GlyphTable" not in t:
                    continue
                face = t.get("m_FaceInfo") or {}
                info["fontassets"].append({
                    "name": t.get("m_Name"),
                    "version": t.get("m_Version"),
                    "populationMode": t.get("m_AtlasPopulationMode"),
                    "atlas": [t.get("m_AtlasWidth"), t.get("m_AtlasHeight")],
                    "padding": t.get("m_AtlasPadding"),
                    "glyphe": len(t.get("m_GlyphTable") or []), "zeichen": len(t.get("m_CharacterTable") or []),
                    "fallback": len(t.get("m_FallbackFontAssetTable") or []),
                    "pointSize": face.get("m_PointSize"), "zeilenhoehe": face.get("m_LineHeight"),
                    "hatQuellschrift": bool((t.get("m_SourceFontFile") or {}).get("m_PathID")),
                })
        out[name] = info
        print(name, json.dumps(info))
    with open(os.path.join(OUT, "fonts.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "bundles", "deep", "fonts", "windows"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "catalog":
        cmd_catalog()
    elif a.cmd == "deep":
        cmd_deep()
    elif a.cmd == "windows":
        cmd_windows()
    elif a.cmd == "fonts":
        cmd_fonts()
    else:
        cmd_bundles(a.limit)


if __name__ == "__main__":
    main()
