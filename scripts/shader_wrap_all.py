#!/usr/bin/env python3
"""Massenfertigung: alle verpackbaren Shader-Varianten als .shader erzeugen (eine Datei je Shader/Pass/Keyword-Menge).

Eigener Code des strahlender-xnu-Projekts. Eingaben wie scripts/shader_wrap.py (work/shaders/: inventory.json,
prog_blob.json, blobs/; kein Ryujinx-Cache). Ausgabe (Spieldaten: nur unter work/ oder in einem gitignorierten
Unity-Projekt, nie im Repo): <out>/<name>.shader, <out>/variants.json (je Variante Status, Fehlergrund).

Aufruf:
    python3 scripts/shader_wrap_all.py --out work/unity-shader-lab/Assets/XnuShaders [--used used.json] [--shader NAME]
--used: JSON-Liste [{"shader": "...", "keywords": ["..."]}], die tatsaechlich von Materialien/Szenen gebrauchten
Keyword-Mengen; alle anderen Varianten werden nicht erzeugt (Strippen: Variantenzahl und Bundlegroesse).
Exit-Code 0, wenn jede gewuenschte Variante erzeugt wurde, sonst 1 (die Liste steht in variants.json).
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
    """(Shader, SubShader, Pass, Keyword-Menge) aller Normal-Paesse, deren Keyword-Menge in Vertex- und Fragmentstufe vorkommt."""
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
    h = hashlib.sha1("|".join(k).encode()).hexdigest()[:8]  # stabil (kein hash())
    return f"{sw.ident(sh['name'])}_s{si}_p{pi}_{h}"


def namespace(args, **kw):
    d = dict(shader=None, bundle=None, sub=0, pass_index=0, keywords=[], mode="named", out=None, name=None, renderers="metal",
             pragma=[], fast_math=False, translator_args=[], color_mask=None, no_cull=False, inventory=str(args.inventory),
             mapping=None, prog_blob=str(args.prog_blob), blobs=str(args.blobs), workdir=str(args.workdir))
    d.update(kw)
    return argparse.Namespace(**d)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="Zielordner (gitignoriert, z. B. work/unity-shader-lab/Assets/XnuShaders)")
    ap.add_argument("--used", help="JSON-Liste gebrauchter Keyword-Mengen (Strippen)")
    ap.add_argument("--shader", help="nur dieser Shadername")
    ap.add_argument("--all-subshaders", action="store_true")
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
        sys.exit("Abbruch: erzeugte Shader enthalten Spieldaten und gehoeren nur unter work/ oder in einen gitignorierten Ordner.")
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
            stats["gestrichen"] += 1
            continue
        name = variant_name(sh, si, pi, k)
        a = namespace(args, shader=sh["name"], bundle=sh.get("bundle"), sub=si, pass_index=pi, keywords=list(k),
                      out=str(out / f"{name}.shader"), name=f"XNU/Generated/{name}", mode=args.mode)
        entry = {"file": f"{name}.shader", "shader": sh["name"], "sub": si, "pass": pi, "keywords": list(k),
                 "lightMode": sh["subShaders"][si]["passes"][pi].get("tags", {}).get("LIGHTMODE")}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                sw.wrap(a)
            stats["ok"] += 1
            entry["status"] = "ok"
        except sw.WrapError as e:
            msg = str(e).split("translation failed: ")[-1][:80]
            stats["fehler"] += 1
            errors[msg] += 1
            entry.update(status="fehler", error=msg)
        manifest.append(entry)
    (out / "variants.json").write_text(json.dumps({"stats": dict(stats), "errors": dict(errors), "variants": manifest}, indent=1))
    print(json.dumps({"stats": dict(stats), "errors": dict(errors), "sec": round(time.time() - t0)}, indent=1))
    return 0 if not stats["fehler"] else 1


if __name__ == "__main__":
    sys.exit(main())
