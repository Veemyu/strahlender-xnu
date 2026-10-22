#!/usr/bin/env python3
"""Mass production: generate all wrappable shader variants as .shader (one file per shader/pass/keyword set).

Own code of the strahlender-xnu project. Inputs as for scripts/shader_wrap.py (work/shaders/: inventory.json,
prog_blob.json, blobs/; no Ryujinx cache). Output (game data: only under work/ or in a gitignored
Unity project, never in the repo): <out>/<name>.shader, <out>/variants.json (status and error reason per variant).

Usage:
    python3 scripts/shader_wrap_all.py --out work/unity-shader-lab/Assets/XnuShaders [--used used.json] [--shader NAME]
--used: JSON list [{"shader": "...", "keywords": ["..."]}] of the keyword sets actually used by materials/scenes;
all other variants are not generated (stripping: variant count and bundle size).
Exit code 0 if every wanted variant was generated, otherwise 1 (the list is in variants.json).
"""
import argparse
import collections
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shader_wrap as sw  # noqa: E402


def variants(inv, all_subshaders=False):
    """(shader, subshader, pass, keyword set) of all normal passes whose keyword set occurs in both vertex and fragment stage."""
    for sh in inv["shaders"]:
        for si, ss in enumerate(sh["subShaders"][: (None if all_subshaders else 1)]):
            for pi, p in enumerate(ss["passes"]):
                if p["type"] != "Normal":
                    continue
                vt = {tuple(sorted(set(v.get("globalKeywords", [])) | set(v.get("localKeywords", [])))) for v in p["stages"].get("vertex", [])}
                seen = set()
                for e in p["stages"].get("fragment", []):
                    k = tuple(sorted(set(e.get("globalKeywords", [])) | set(e.get("localKeywords", []))))
                    if k in vt and k not in seen:
                        seen.add(k)
                        yield sh, si, pi, k


def variant_name(sh, si, pi, k):
    h = hashlib.sha1("|".join(k).encode()).hexdigest()[:8]  # stable (no hash())
    return f"{sw.ident(sh['name'])}_s{si}_p{pi}_{h}"


def pass_keysets(p):
    """Keyword sets that occur in both the vertex and fragment stage of the pass."""
    def sets(stage):
        return {tuple(sorted(set(e.get("globalKeywords", [])) | set(e.get("localKeywords", [])))) for e in p["stages"].get(stage, [])}
    return sets("vertex") & sets("fragment")


def shadow_partner(ss, forward_pass, k):
    """Shadow caster pass (index, keywords) for a forward variant k, or None.

    Rule like ShaderVariantResolver: requested = (k intersected with all keywords of the caster pass) plus SHADOWS_DEPTH;
    exact variant, otherwise without INSTANCING_ON."""
    for ci, cp in enumerate(ss["passes"]):
        if ci == forward_pass or cp["type"] != "Normal" or cp.get("tags", {}).get("LIGHTMODE") != "SHADOWCASTER":
            continue
        have = pass_keysets(cp)
        universe = {x for t in have for x in t}
        want = (set(k) & universe) | {"SHADOWS_DEPTH"}
        for cand in (want, want - {"INSTANCING_ON"}):
            if tuple(sorted(cand)) in have:
                return ci, sorted(cand)
        return None
    return None


def namespace(args, **kw):
    d = dict(shader=None, bundle=None, sub=0, pass_index=0, keywords=[], mode="named", out=None, name=None, renderers="metal",
             pragma=[], fast_math=False, translator_args=[], color_mask=None, no_cull=False, inventory=str(args.inventory),
             mapping=None, prog_blob=str(args.prog_blob), blobs=str(args.blobs), workdir=str(args.workdir), also=[], no_aux=False)
    d.update(kw)
    return argparse.Namespace(**d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="target folder (gitignored, e.g. work/unity-shader-lab/Assets/XnuShaders)")
    ap.add_argument("--used", help="JSON list of used keyword sets (stripping)")
    ap.add_argument("--shader", help="only this shader name")
    ap.add_argument("--all-subshaders", action="store_true")
    ap.add_argument("--combine-shadow", action="store_true",
                    help="generate forward variants with the matching shadow caster pass in the same shader "
                         "(Unity takes the shadow caster from the material's shader; variants.json: field 'shadow')")
    ap.add_argument("--mode", choices=("named", "array"), default="named")
    ap.add_argument("--inventory", default=str(sw.WORK / "inventory.json"))
    ap.add_argument("--prog-blob", default=str(sw.WORK / "prog_blob.json"))
    ap.add_argument("--blobs", default=str(sw.WORK / "blobs"))
    ap.add_argument("--workdir", default=str(sw.WORK / "wrap_tmp"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    ignored = "work" in out.resolve().parts or subprocess.run(
        ["git", "check-ignore", "-q", str(out / "x.shader")], cwd=sw.REPO).returncode == 0
    if not ignored:
        sys.exit("Abort: generated shaders contain game data and belong only under work/ or in a gitignored folder.")
    out.mkdir(parents=True, exist_ok=True)
    used = None
    if args.used:
        used = {(u["shader"], tuple(sorted(u["keywords"]))) for u in json.loads(Path(args.used).read_text())}
    inv = json.loads(Path(args.inventory).read_text())
    t0 = time.time()
    stats, errors, manifest = collections.Counter(), collections.Counter(), []
    for sh, si, pi, k in variants(inv, args.all_subshaders):
        if args.shader and sh["name"] != args.shader:
            continue
        stats["total"] += 1
        if used is not None and (sh["name"], k) not in used:
            stats["stripped"] += 1
            continue
        name = variant_name(sh, si, pi, k)
        a = namespace(args, shader=sh["name"], bundle=sh.get("bundle"), sub=si, pass_index=pi, keywords=list(k),
                      out=str(out / f"{name}.shader"), name=f"XNU/Generated/{name}", mode=args.mode)
        entry = {"file": f"{name}.shader", "shader": sh["name"], "sub": si, "pass": pi, "keywords": list(k),
                 "lightMode": sh["subShaders"][si]["passes"][pi].get("tags", {}).get("LIGHTMODE")}
        if args.combine_shadow and entry["lightMode"] == "FORWARDBASE":
            sp = shadow_partner(sh["subShaders"][si], pi, k)
            if sp:
                a.also = [f"{sp[0]}:{','.join(sp[1])}"]
                entry["shadow"] = {"pass": sp[0], "keywords": sp[1]}
        aux = sw.aux_blocks(sh["subShaders"][si], pi)
        if aux[0] or aux[1]:
            entry["aux"] = {"grab": [x.strip() for x in aux[0]], "use": [x.strip() for x in aux[1]]}
        try:
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    sw.wrap(a)
            except sw.WrapError as e:
                if not a.also:
                    raise
                # shadow caster not translatable: generate the forward variant anyway, without the shadow caster
                entry["shadowError"] = str(e).split("translation failed: ")[-1][:80]
                entry.pop("shadow", None)
                a.also = []
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    sw.wrap(a)
            stats["ok"] += 1
            entry["status"] = "ok"
        except sw.WrapError as e:
            msg = str(e).split("translation failed: ")[-1][:80]
            stats["error"] += 1
            errors[msg] += 1
            entry.update(status="error", error=msg)
        manifest.append(entry)
    (out / "variants.json").write_text(json.dumps({"stats": dict(stats), "errors": dict(errors), "variants": manifest}, indent=1))
    print(json.dumps({"stats": dict(stats), "errors": dict(errors), "sec": round(time.time() - t0)}, indent=1))
    return 0 if not stats["error"] else 1


if __name__ == "__main__":
    sys.exit(main())
