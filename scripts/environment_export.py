#!/usr/bin/env python3
"""Exportiert die Licht-/Umgebungsdaten (EnvironmentSettings) und deren Zonenzuordnung (MapInfo.RenderSettings).

Eigener Code des strahlender-xnu-Projekts. Liest das Bundle Dpr/scriptableobjects/gamesettings aus dem selbst
extrahierten RomFS (UnityPy, Typtree) und schreibt zwei JSON-Dateien nach work/masterdata/ (gitignoriert; die
Werte sind Spieldaten und gehoeren nie ins Repo):

    EnvironmentSettings.json   je Asset: Name, path_id, CloudShadowEnable, FixedTime, FogMode, Morning..Midnight (Parameters)
    MapRenderSettings.json     je Zone (Index in MapInfo.ZoneData): ZoneID, Name der Settings, Wetter, FixedTime, ReflectionCamera

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
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
