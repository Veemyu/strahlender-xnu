#!/usr/bin/env python3
"""Material-Export: liest die Material-Objekte der Switch-Bundles (UnityFS, Unity 2019.4) per UnityPy-TypeTree und
schreibt je Bundle eine JSON-Datei mit allem, was der Material-Umbau braucht (Shadername, Keywords, Render-Queue,
Override-Tags, Floats, Farben, Texturverweise). Eigener Code des strahlender-xnu-Projekts.

Die Ausgabe enthaelt Spielinhalte (Materialnamen, Werte) und gehoert deshalb nur nach work/ (gitignoriert);
das Skript bricht ab, wenn der Zielordner nicht ignoriert ist.

Aufruf (Repo-Root):
    PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials BUNDLE [BUNDLE ...]
    PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials --dir Environments/fields
    PYTHONPATH=tools/pydeps python3 scripts/material_export.py --out work/materials --used work/materials/used.json --dir Environments
BUNDLE: Pfad relativ zu work/romfs/Data/StreamingAssets/AssetAssistant (z. B. Environments/fields/area001).
--used schreibt zusaetzlich die Liste [{"shader","keywords"}] aller vorkommenden (Shader, Material-Keyword-Menge)
fuer scripts/shader_wrap_all.py --used (Strippen, docs/material-remap.md).
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "work" / "romfs" / "Data" / "StreamingAssets" / "AssetAssistant"
INVENTORY = REPO / "work" / "shaders" / "inventory.json"
FORMAT = 1


class ShaderResolver:
    """(Dateiverweis, PathID) eines Material-Shaders -> Shadername, ueber das Shader-Inventar."""

    def __init__(self, inventory, cab_to_bundle):
        self.cab_to_bundle = cab_to_bundle  # "CAB-..." -> Inventar-Bundlename ("shaders", "fxparticle")
        self.by_key = {}
        for s in inventory.get("shaders", []):
            self.by_key[(s["bundle"], s["pathId"])] = s["name"]
        for s in inventory.get("extraShaders", []):
            self.by_key[(s["bundle"], s["pathId"])] = s["name"]

    def resolve(self, file_id, path_id, externals):
        """externals: Liste der externen Dateipfade der Material-Datei (FileID n = externals[n-1])."""
        if path_id == 0:
            return None
        if file_id == 0 or file_id > len(externals):
            return None
        ext = externals[file_id - 1]
        base = ext.rstrip("/").split("/")[-1]
        bundle = self.cab_to_bundle.get(base)
        if bundle is None and base in ("resources.assets", "unity_builtin_extra"):
            bundle = base
        return self.by_key.get((bundle, path_id))


def convert_material(tr, externals, resolver, texture_info=None):
    """TypeTree-Dict eines Material-Objekts -> JSON-Eintrag (rein, ohne UnityPy; getestet in test_material_export.py)."""
    texture_info = texture_info or {}
    sp = tr.get("m_SavedProperties", {})
    shader = tr.get("m_Shader", {})
    keywords = sorted(k for k in (tr.get("m_ShaderKeywords") or "").split() if k)
    textures = {}
    for name, env in sp.get("m_TexEnvs", []):
        pp = env["m_Texture"]
        t = {"scale": [env["m_Scale"]["x"], env["m_Scale"]["y"]], "offset": [env["m_Offset"]["x"], env["m_Offset"]["y"]]}
        if pp["m_PathID"] != 0:
            t["file"] = pp["m_FileID"]
            t["pathId"] = pp["m_PathID"]
            info = texture_info.get((pp["m_FileID"], pp["m_PathID"]))
            if info:
                t.update(info)
        textures[name] = t
    return {
        "name": tr["m_Name"],
        "shader": resolver.resolve(shader.get("m_FileID", 0), shader.get("m_PathID", 0), externals),
        "shaderRef": [shader.get("m_FileID", 0), shader.get("m_PathID", 0)],
        "keywords": keywords,
        "renderQueue": tr.get("m_CustomRenderQueue", -1),
        "tags": {k: v for k, v in tr.get("stringTagMap", [])},
        "disabledPasses": list(tr.get("disabledShaderPasses", [])),
        "instancing": bool(tr.get("m_EnableInstancingVariants", False)),
        "floats": {k: v for k, v in sp.get("m_Floats", [])},
        "ints": {k: v for k, v in sp.get("m_Ints", [])},
        "colors": {k: [v["r"], v["g"], v["b"], v["a"]] for k, v in sp.get("m_Colors", [])},
        "textures": textures,
    }


def cab_map():
    """CAB-Name -> Inventar-Bundlename der Shader-Bundles (aus den Dateien selbst gelesen)."""
    import UnityPy
    out = {}
    for rel, name in (("Dpr/shaders", "shaders"), ("Effects/fxparticle", "fxparticle")):
        p = ASSETS / rel
        if not p.exists():
            continue
        env = UnityPy.load(str(p))
        for bf in env.files.values():
            for fname in getattr(bf, "files", {}):
                if fname.startswith("CAB-") and not fname.endswith(".resS"):
                    out[fname] = name
    return out


def texture_table(env):
    """(FileID 0, PathID) -> Name, Breite, Hoehe, Format der Texturen derselben Datei."""
    t = {}
    for o in env.objects:
        if o.type.name in ("Texture2D", "Cubemap", "Texture3D", "Texture2DArray"):
            try:
                tr = o.read_typetree()
            except Exception:
                continue
            t[(0, o.path_id)] = {"texName": tr.get("m_Name"), "width": tr.get("m_Width"), "height": tr.get("m_Height"),
                                 "format": tr.get("m_TextureFormat"), "texType": o.type.name}
    return t


def export_bundle(path, resolver):
    import UnityPy
    env = UnityPy.load(str(path))
    tex = texture_table(env)
    mats, ext = [], []
    for bf in env.files.values():
        for f in getattr(bf, "files", {}).values():
            if hasattr(f, "externals"):
                ext = [e.path for e in f.externals]
                break
        if ext:
            break
    for o in env.objects:
        if o.type.name != "Material":
            continue
        try:
            tr = o.read_typetree()
        except Exception as e:  # defektes Objekt: melden, nicht abbrechen
            mats.append({"error": str(e)[:80], "pathId": o.path_id})
            continue
        m = convert_material(tr, ext, resolver, tex)
        m["pathId"] = o.path_id
        mats.append(m)
    return mats


def check_ignored(out):
    out = Path(out).resolve()
    if "work" in out.parts:
        return
    r = subprocess.run(["git", "check-ignore", "-q", str(out / "x.json")], cwd=REPO)
    if r.returncode != 0:
        sys.exit("Abbruch: Materialdaten enthalten Spielinhalte und gehoeren nur unter work/ oder in einen gitignorierten Ordner.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundles", nargs="*")
    ap.add_argument("--dir", action="append", default=[], help="alle Bundles unterhalb dieses Ordners (relativ zu AssetAssistant)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--used", help="Liste gebrauchter (Shader, Keywords) schreiben")
    ap.add_argument("--inventory", default=str(INVENTORY))
    a = ap.parse_args(argv)
    check_ignored(a.out)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    inv = json.loads(Path(a.inventory).read_text())
    resolver = ShaderResolver(inv, cab_map())
    todo = list(a.bundles)
    for d in a.dir:
        todo += sorted(str(p.relative_to(ASSETS)) for p in (ASSETS / d).rglob("*") if p.is_file() and p.suffix == "")
    used = set()
    stat = Counter()
    for rel in todo:
        mats = export_bundle(ASSETS / rel, resolver)
        if not mats:
            stat["bundles_ohne_material"] += 1
            continue
        names = Counter(m.get("name") for m in mats)
        (out / (rel.replace("/", "__") + ".json")).write_text(json.dumps({"format": FORMAT, "bundle": rel, "materials": mats}, indent=1))
        stat["bundles"] += 1
        stat["materialien"] += len(mats)
        stat["doppelte_namen"] += sum(1 for c in names.values() if c > 1)
        stat["ohne_shadername"] += sum(1 for m in mats if "error" not in m and not m["shader"])
        for m in mats:
            if m.get("shader"):
                used.add((m["shader"], tuple(m["keywords"])))
        print(f"{rel}: {len(mats)} Materialien")
    if a.used:
        Path(a.used).write_text(json.dumps([{"shader": s, "keywords": list(k)} for s, k in sorted(used)], indent=1))
    print(json.dumps(dict(stat), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
