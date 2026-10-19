#!/usr/bin/env python3
"""Exportiert die Licht-/Umgebungsdaten (EnvironmentSettings) und deren Zonenzuordnung (MapInfo.RenderSettings).

Eigener Code des strahlender-xnu-Projekts. Liest das Bundle Dpr/scriptableobjects/gamesettings aus dem selbst
extrahierten RomFS (UnityPy, Typtree) und schreibt zwei JSON-Dateien nach work/masterdata/ (gitignoriert; die
Werte sind Spieldaten und gehoeren nie ins Repo):

    EnvironmentSettings.json   je Asset: Name, path_id, CloudShadowEnable, FixedTime, FogMode, Morning..Midnight (Parameters)
    MapRenderSettings.json     je Zone (Index in MapInfo.ZoneData): ZoneID, Name der Settings, Wetter, FixedTime, ReflectionCamera
    EnvironmentScene.json      Szenenwerte der Feldszene (Dpr/scenes/field): serialisierte Felder des EnvironmentController
                               (Schattenentfernung, Wolken, Farben, Texturnamen), RenderSettings, Kameras, Lichter

Herleitung der Klassen: docs/shader-globals.md (EnvironmentSettings, EnvironmentSettings.Parameters, MapInfo.SheetZoneData).
Aufruf:  PYTHONPATH=tools/pydeps python3 scripts/environment_export.py [--assets ...] [--out work/masterdata]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

BUNDLE = "Dpr/scriptableobjects/gamesettings"
PERIODS = ("Morning", "Daytime", "Evening", "Night", "Midnight")


SCENE_BUNDLE = "Dpr/scenes/field"
SCENE_FLOATS = ("_Wetness", "_EmissionThreshold", "_EmissionScale", "_CloudShadowScale", "_CloudShadowBase", "_Blurry",
                "_ShadowDistance", "_ShadowNearPlaneOffset", "_ShadowNormalBias", "_WeatherMode", "_ShaderMode")
SCENE_TEXTURES = ("_NoiseTex", "_SnowTex", "_SnowNormalTex", "_CloudShadowTex", "_EnvironmentMap")


def _vec(v):
    return [v[k] for k in ("x", "y") if k in v] if v else []


def _col(v):
    return [v[k] for k in ("r", "g", "b", "a")] if v else []


def scene_document(controller, render_settings, texture_names, cameras=(), lights=(), external_names=None):
    """Szenenwerte des EnvironmentController (serialisierte Felder), RenderSettings, Kameras und Lichter einer Szene.

    controller: Typtree des MonoBehaviour EnvironmentController; texture_names: PathID -> Name der Texturen derselben Datei;
    external_names: (FileID, PathID) -> Name fuer Texturen in Nachbar-Bundles.
    Texturen werden nur als Name gefuehrt (die Pixel liegen im Bundle, nicht in der JSON-Datei)."""
    external_names = external_names or {}
    c = controller
    doc = {"controller": {k: c.get(k) for k in SCENE_FLOATS if k in c}}
    doc["controller"]["cloudSpeed"] = _vec(c.get("_CloudSpeed"))
    doc["controller"]["cloudTiling"] = _vec(c.get("_CloudTiling"))
    doc["controller"]["shadowColor"] = _col(c.get("_ShadowColor"))
    doc["controller"]["snowShadowColor"] = _col(c.get("_SnowShadowColor"))
    tex = {}
    for k in SCENE_TEXTURES:
        pp = c.get(k) or {}
        pid = pp.get("m_PathID", 0)
        tex[k] = texture_names.get(pid) if pid and not pp.get("m_FileID") else (
            external_names.get((pp.get("m_FileID"), pid), "extern") if pid else None)
    doc["controller"]["textures"] = tex
    r = render_settings or {}
    doc["renderSettings"] = {
        "fog": bool(r.get("m_Fog", False)), "fogColor": _col(r.get("m_FogColor")), "fogMode": r.get("m_FogMode"),
        "fogDensity": r.get("m_FogDensity"), "fogStart": r.get("m_LinearFogStart"), "fogEnd": r.get("m_LinearFogEnd"),
        "ambientMode": r.get("m_AmbientMode"), "ambientSky": _col(r.get("m_AmbientSkyColor")),
        "ambientEquator": _col(r.get("m_AmbientEquatorColor")), "ambientGround": _col(r.get("m_AmbientGroundColor")),
        "ambientIntensity": r.get("m_AmbientIntensity"), "subtractiveShadow": _col(r.get("m_SubtractiveShadowColor")),
        "skybox": bool((r.get("m_SkyboxMaterial") or {}).get("m_PathID", 0)),
        "reflectionMode": r.get("m_DefaultReflectionMode"), "reflectionIntensity": r.get("m_ReflectionIntensity"),
    }
    doc["cameras"] = [{
        "name": n, "clearFlags": t.get("m_ClearFlags"), "background": _col(t.get("m_BackGroundColor")),
        "near": t.get("near clip plane"), "far": t.get("far clip plane"), "fov": t.get("field of view"),
        "cullingMask": (t.get("m_CullingMask") or {}).get("m_Bits"), "hdr": t.get("m_HDR"), "msaa": t.get("m_AllowMSAA"),
        "depth": t.get("m_Depth"), "enabled": t.get("m_Enabled"),
    } for n, t in cameras]
    doc["lights"] = [{
        "name": n, "type": t.get("m_Type"), "color": _col(t.get("m_Color")), "intensity": t.get("m_Intensity"),
        "shadows": (t.get("m_Shadows") or {}).get("m_Type"), "bias": (t.get("m_Shadows") or {}).get("m_Bias"),
        "normalBias": (t.get("m_Shadows") or {}).get("m_NormalBias"), "cullingMask": (t.get("m_CullingMask") or {}).get("m_Bits"),
    } for n, t in lights]
    return doc


def read_scene(path):
    """Szenen-Bundle -> scene_document (None, wenn kein EnvironmentController darin liegt)."""
    import UnityPy
    env = UnityPy.load(path)
    objs = {o.path_id: o for o in env.objects}
    names = {}
    controller = render = None
    for o in env.objects:
        if o.type.name == "Texture2D":
            names[o.path_id] = o.read_typetree().get("m_Name")
    for o in env.objects:
        if o.type.name == "MonoBehaviour":
            try:
                tr = o.read_typetree()
            except Exception:
                continue
            if "_ShadowDistance" in tr:
                controller = tr
        elif o.type.name == "RenderSettings":
            render = o.read_typetree()
    if controller is None:
        return None
    ext_names = {}
    try:
        import material_export as me
        ext = []
        for bf in env.files.values():
            for f in getattr(bf, "files", {}).values():
                if hasattr(f, "externals"):
                    ext = [e.path for e in f.externals]
                    break
            if ext:
                break
        rel = os.path.relpath(path, os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant"))
        lookup = me.ExternalTextures().for_bundle(rel)
        for k in SCENE_TEXTURES:
            pp = controller.get(k) or {}
            fid, pid = pp.get("m_FileID", 0), pp.get("m_PathID", 0)
            cab = me.external_cab(ext[fid - 1]) if pid and 0 < fid <= len(ext) else None
            info = lookup(cab, pid) if cab else None
            if info:
                ext_names[(fid, pid)] = info["texName"]
    except Exception as e:  # Katalog fehlt o. ae.: Namen bleiben "extern"
        print("Hinweis: externe Texturnamen nicht aufgeloest:", e, file=sys.stderr)
    cams, lights = [], []
    for o in env.objects:
        if o.type.name not in ("GameObject",):
            continue
        g = o.read_typetree()
        for c in g["m_Component"]:
            co = objs.get(c["component"]["m_PathID"])
            if co is None:
                continue
            if co.type.name == "Camera":
                cams.append((g["m_Name"], co.read_typetree()))
            elif co.type.name == "Light":
                lights.append((g["m_Name"], co.read_typetree()))
    return scene_document(controller, render, names, cams, lights, ext_names)


def build_documents(records):
    """records: Ausgabe von masterdata_export.read_bundle(..., with_ids=True) -> (settings_doc, zones_doc, stats)."""
    settings = []
    by_id = {}
    for r in records:
        if r.get("class") != "EnvironmentSettings":
            continue
        d = r["data"]
        item = {
            "name": r.get("name", ""),
            "pathId": r.get("path_id"),
            "cloudShadowEnable": bool(d.get("CloudShadowEnable", 0)),
            "fixedTime": bool(d.get("FixedTime", 0)),
            "fogMode": d.get("FogMode", 0),
            "periods": {p: d[p] for p in PERIODS if p in d},
        }
        settings.append(item)
        by_id[item["pathId"]] = item
    zones = []
    for r in records:
        if r.get("class") != "MapInfo":
            continue
        for i, z in enumerate(r["data"].get("ZoneData", [])):
            ref = (z.get("RenderSettings") or {}).get("m_PathID", 0)
            target = by_id.get(ref)
            zones.append({
                "index": i, "zoneId": z.get("ZoneID"), "settings": target["name"] if target else None,
                "settingsPathId": ref if target else 0, "weather": z.get("Weather", 0),
                "fixedTime": bool(z.get("FixedTime", 0)), "reflectionCamera": bool(z.get("ReflectionCamera", 0)),
            })
    stats = {
        "settings": len(settings), "zones": len(zones), "zonesWithSettings": sum(1 for z in zones if z["settings"]),
        "settingsUsedByZones": len({z["settingsPathId"] for z in zones if z["settings"]}),
    }
    return {"settings": settings}, {"zones": zones}, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", default=os.path.join(ROOT, "work", "romfs", "Data", "StreamingAssets", "AssetAssistant"))
    ap.add_argument("--out", default=os.path.join(ROOT, "work", "masterdata"))
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    if "work" not in out.split(os.sep):
        sys.exit("Abbruch: die Ausgabe enthaelt Spieldaten und gehoert nur unter work/.")
    sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
    import masterdata_export as mx  # noqa: E402
    unitypy = mx.load_unitypy()
    records = mx.read_bundle(unitypy, os.path.join(args.assets, BUNDLE), with_ids=True)
    settings, zones, stats = build_documents(records)
    os.makedirs(out, exist_ok=True)
    for name, doc in (("EnvironmentSettings.json", settings), ("MapRenderSettings.json", zones)):
        with open(os.path.join(out, name), "w") as f:
            json.dump(doc, f)
    scene_path = os.path.join(args.assets, SCENE_BUNDLE)
    if os.path.isfile(scene_path):
        scene = read_scene(scene_path)
        if scene is not None:
            with open(os.path.join(out, "EnvironmentScene.json"), "w") as f:
                json.dump(scene, f, indent=1)
            stats["scene"] = {"cameras": len(scene["cameras"]), "lights": len(scene["lights"]),
                              "shadowDistance": scene["controller"].get("_ShadowDistance")}
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
