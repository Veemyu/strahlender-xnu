#!/usr/bin/env python3
"""Variantenwahl fuer Material-Exporte (Referenzumsetzung von unity/Assets/Scripts/Render/ShaderVariantResolver.cs).

Zweck: aus den Material-Exporten (scripts/material_export.py) die Liste der tatsaechlich gebrauchten Shader-Varianten
bilden (fuer scripts/shader_wrap_all.py --used) und Abdeckung/Luecken zahlenmaessig melden. Regeln: docs/material-remap.md.
Beide Umsetzungen (Python, C#) laufen gegen dieselben Testfaelle: unity/Assets/Tests/EditMode/Fixtures/variant_resolution_cases.json.

Aufruf (Repo-Root):
        python3 scripts/material_variants.py --materials work/materials --used-out work/materials/used_variants.json \
        [--manifest work/shaders/build/variants.json] [--instancing] [--report work/materials/variants_report.json] \
        [--extra-used scripts/runtime_variants.json] [--exclude-shader FxSystem/Particle]
Ohne --manifest wird die Variantenliste aus work/shaders/inventory.json abgeleitet (gleiche Aufzaehlung wie shader_wrap_all.py).
"""
import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ENV = {"forward": ["DIRECTIONAL", "SHADOWS_SCREEN"], "shadow": ["SHADOWS_DEPTH"], "relax": ["INSTANCING_ON", "SHADOWS_SCREEN"]}


class Index:
    def __init__(self, entries):
        self.by = collections.defaultdict(lambda: collections.defaultdict(list))
        self.light = {}
        for e in entries:
            if e.get("status", "ok") != "ok" or e.get("sub", 0) != 0:
                continue
            self.by[e["shader"]][e["pass"]].append({"file": e["file"], "keywords": sorted(e["keywords"])})
            if e.get("lightMode"):
                self.light[(e["shader"], e["pass"])] = e["lightMode"]

    def role(self, shader, p):
        return role_of(self.universe(shader, p), self.light.get((shader, p)))

    def passes(self, shader):
        return sorted(self.by.get(shader, {}))

    def variants(self, shader, p):
        return self.by.get(shader, {}).get(p, [])

    def universe(self, shader, p):
        u = set()
        for v in self.variants(shader, p):
            u.update(v["keywords"])
        return u


def role_of(universe, light_mode=None):
    """forward | shadow | add. LIGHTMODE (aus dem Inventar) entscheidet; ohne Angabe die Schlüsselwörter des Passes."""
    lm = (light_mode or "").upper()
    if lm == "SHADOWCASTER":
        return "shadow"
    if lm == "FORWARDADD":
        return "add"
    if lm:
        return "forward"
    return "shadow" if ("SHADOWS_DEPTH" in universe or "SHADOWS_CUBE" in universe) else "forward"


def resolve(index, shader, p, material_keywords, instancing=False, env=None):
    """-> dict(file, quality, role, requested, ignored, missing, extra); quality: exact|relaxed|nearest|unavailable."""
    env = env or DEFAULT_ENV
    variants = index.variants(shader, p)
    uni = index.universe(shader, p)
    role = index.role(shader, p)
    out = {"pass": p, "role": role, "file": None, "quality": "unavailable", "requested": [], "ignored": [], "missing": [], "extra": []}
    if not variants:
        return out
    mat_all = set(material_keywords)
    mat = {k for k in mat_all if k in uni}
    out["ignored"] = sorted(mat_all - uni)
    env_kw = list(env["forward"] if role == "forward" else env["shadow"] if role == "shadow" else [])
    if instancing:
        env_kw.append("INSTANCING_ON")
    env_kw = [k for k in env_kw if k in uni]

    def fill(v, want, q):
        out.update(file=v["file"], keywords=list(v["keywords"]), quality=q, requested=sorted(want), missing=sorted(want - set(v["keywords"])),
                   extra=[k for k in v["keywords"] if k not in want])
        return out

    full = mat | set(env_kw)
    cur = list(env_kw)
    for step in range(len(env["relax"]) + 1):
        want = mat | set(cur)
        for v in variants:
            if set(v["keywords"]) == want and len(v["keywords"]) == len(want):
                return fill(v, full, "exact" if step == 0 else "relaxed")
        if step < len(env["relax"]) and env["relax"][step] in cur:
            cur.remove(env["relax"][step])
    envs = set(env_kw)
    best = min(variants, key=lambda v: (len(mat - set(v["keywords"])), len(envs - set(v["keywords"])),
                                         len([k for k in v["keywords"] if k not in full]), len(v["keywords"]), v["file"]))
    return fill(best, full, "nearest")


def merge_used(used, extras, exclude):
    """used: Menge (Shader, Keyword-Tupel); extras: [{shader, keywords}] werden aufgenommen, Shader aus exclude entfernt."""
    out = set(used)
    for e in extras:
        out.add((e["shader"], tuple(sorted(e["keywords"]))))
    skip = set(exclude)
    return {u for u in out if u[0] not in skip}


def inventory_manifest(inventory):
    sys.path.insert(0, str(REPO / "scripts"))
    import shader_wrap_all as swa
    out = []
    for sh, si, pi, k in swa.variants(inventory):
        out.append({"file": swa.variant_name(sh, si, pi, k) + ".shader", "shader": sh["name"], "sub": si, "pass": pi,
                    "keywords": list(k), "status": "ok",
                    "lightMode": sh["subShaders"][si]["passes"][pi].get("tags", {}).get("LIGHTMODE")})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--materials", required=True, help="Ordner mit den Exporten (*.json von material_export.py)")
    ap.add_argument("--used-out", required=True)
    ap.add_argument("--extra-used", action="append", default=[],
                    help="JSON [{shader, keywords}]: zur Laufzeit per Code gesetzte Keyword-Mengen (z. B. scripts/runtime_variants.json), "
                         "werden unveraendert in die benutzte Menge uebernommen")
    ap.add_argument("--exclude-shader", action="append", default=[],
                    help="Shadername, dessen Varianten nicht in --used-out erscheinen (z. B. FxSystem/Particle: ~2.000 Varianten)")
    ap.add_argument("--manifest")
    ap.add_argument("--inventory", default=str(REPO / "work" / "shaders" / "inventory.json"))
    ap.add_argument("--instancing", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    if a.manifest:
        entries = json.loads(Path(a.manifest).read_text())["variants"]
    else:
        entries = inventory_manifest(json.loads(Path(a.inventory).read_text()))
    idx = Index(entries)
    keys = {}
    for e in entries:
        if e.get("status", "ok") == "ok" and e.get("sub", 0) == 0:
            keys[e["file"]] = (e["shader"], tuple(sorted(e["keywords"])))
    stat, per_shader, misses = collections.Counter(), collections.defaultdict(collections.Counter), []
    used = set()
    seen = set()
    for f in sorted(Path(a.materials).glob("*.json")):
        if f.name.startswith("used") or f.name.startswith("variants_report"):
            continue
        for m in json.loads(f.read_text()).get("materials", []):
            if "error" in m or not m.get("shader"):
                stat["ohne_shader"] += 1
                continue
            stat["materialien"] += 1
            sig = (m["shader"], tuple(m["keywords"]))
            first = sig not in seen
            seen.add(sig)
            if not idx.passes(m["shader"]):
                stat["shader_ohne_variante"] += 1
                per_shader[m["shader"]]["unavailable"] += 1
                continue
            for p in idx.passes(m["shader"]):
                r = resolve(idx, m["shader"], p, m["keywords"], a.instancing)
                if idx.role(m["shader"], p) == "forward":
                    stat["forward_" + r["quality"]] += 1
                    per_shader[m["shader"]][r["quality"]] += 1
                    if r["quality"] in ("nearest", "unavailable") and first:
                        misses.append({"shader": m["shader"], "keywords": m["keywords"], "missing": r["missing"], "pass": p})
                else:
                    stat[r["role"] + "_" + r["quality"]] += 1
                if r["file"]:
                    used.add(keys[r["file"]])
    for extra in a.extra_used:
        used = merge_used(used, json.loads(Path(extra).read_text()), ())
    used = merge_used(used, [], a.exclude_shader)
    Path(a.used_out).write_text(json.dumps([{"shader": s, "keywords": list(k)} for s, k in sorted(used)], indent=1))
    rep = {"stat": dict(stat), "benutzte_varianten": len(used), "verschiedene_material_keywordmengen": len(seen),
           "je_shader": {k: dict(v) for k, v in sorted(per_shader.items())}, "luecken": misses[:200]}
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({k: rep[k] for k in ("stat", "benutzte_varianten", "verschiedene_material_keywordmengen")}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
