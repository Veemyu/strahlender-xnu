#!/usr/bin/env python3
"""Reads the SPIR-V interface of the cache modules that scripts/shader_map.py matched to a bundle shader
(spirv-cross --reflect and --msl) and links it with the constant buffer layouts from the inventory.

Usage (from the repo root, needs spirv-cross in the PATH):
    PYTHONPATH=tools/pydeps python3 scripts/shader_reflect.py [--out work/shaders/reflect.json] [--limit N]

Prerequisite: work/shaders/inventory.json and work/shaders/mapping.json (see shader_inventory.py, shader_map.py).
Output: only names, indices and numbers (no shader contents). The SPIR-V modules are kept only in memory and
in work/shaders/reflect_tmp/; the folder is deleted at the end.
"""
import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE = Path("Ryujinx/games/0100000011d90000/cache/shader")
TMP = Path("work/shaders/reflect_tmp")
SOURCE_PRIORITY = {"shaders": 0, "fxparticle": 1, "tmpshader": 2, "resources.assets": 3}
SWIZ = {"x": 0, "y": 1, "z": 2, "w": 3, "r": 0, "g": 1, "b": 2, "a": 3}
UBO_RE = re.compile(r"\b(vp|fp)_c(\d+)\._m(\d+)\[(\d+)\](?:\.([xyzwrgba]+))?")
DYN_RE = re.compile(r"\b(vp|fp)_c(\d+)\._m(\d+)\[(?!\d+\])")


class HostCache:
    def __init__(self):
        self.toc = (CACHE / "vulkan_apple.toc").read_bytes()
        self.data = (CACHE / "vulkan_apple.data").read_bytes()

    def modules(self, i):
        off, unc, _ = struct.unpack_from("<QII", self.toc, 32 + 16 * i)
        algo = self.data[off]
        body = self.data[off + 1:]
        if algo == 1:
            blob = zlib.decompressobj(-15).decompress(body, unc)
        elif algo == 0:
            blob = bytes(body[:unc])
        else:
            import brotli
            blob = brotli.Decompressor().process(bytes(body[:max(unc * 2, 65536)]))[:unc]
        cnt = struct.unpack_from("<i", blob, 0)[0]
        p = 4
        mods = {}
        for _ in range(cnt):
            stage, ln = struct.unpack_from("<ii", blob, p)
            p += 8
            mods[stage] = blob[p:p + ln]
            p += ln
        return mods  # Ryujinx ShaderStage: 1 = Vertex, 5 = Fragment


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def analyse(task):
    entry, stage, spv = task
    f = TMP / f"{entry}_{stage}.spv"
    f.write_bytes(spv)
    refl = run(["spirv-cross", str(f), "--reflect"])
    msl = run(["spirv-cross", str(f), "--msl", "--msl-version", "20300"])
    f.unlink()
    res = {"ok": refl is not None and msl is not None}
    if not res["ok"]:
        return entry, stage, res
    j = json.loads(refl)
    res["ubos"] = [{"name": u["name"], "binding": u["binding"], "set": u.get("set"), "size": u["block_size"]} for u in j.get("ubos", [])]
    res["inputs"] = sorted(i["location"] for i in j.get("inputs", []))
    res["outputs"] = sorted(i["location"] for i in j.get("outputs", []))
    res["textures"] = [{"binding": t.get("binding"), "set": t.get("set"), "type": t.get("type")} for t in j.get("textures", [])]
    res["samplers"] = [{"binding": t.get("binding"), "set": t.get("set")} for t in j.get("separate_samplers", [])]
    res["sampledImages"] = len(j.get("sampled_images", [])) + len(j.get("separate_images", []))
    res["ssbos"] = len(j.get("ssbos", []))
    res["images"] = len(j.get("images", []))
    used = defaultdict(set)  # (cb) -> {Byte-Offsets}
    for m in UBO_RE.finditer(msl):
        cb = f"{m.group(1)}_c{m.group(2)}"
        base = int(m.group(4)) * 16
        sw = m.group(5)
        if sw:
            for ch in sw:
                used[cb].add(base + 4 * SWIZ[ch])
        else:
            used[cb].update(range(base, base + 16, 4))
    res["usedBytes"] = {k: sorted(v) for k, v in used.items()}
    res["dynamicIndexing"] = sorted({f"{m.group(1)}_c{m.group(2)}" for m in DYN_RE.finditer(msl)})
    res["mslLines"] = msl.count("\n")
    return entry, stage, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/shaders/reflect.json")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    if shutil.which("spirv-cross") is None:
        sys.exit("spirv-cross missing")
    mapping = json.load(open("work/shaders/mapping.json"))
    inv = json.load(open("work/shaders/inventory.json"))
    sub_lookup = {}
    for sh in inv["shaders"] + inv["extraShaders"]:
        for ssi, ss in enumerate(sh["subShaders"]):
            for psi, ps in enumerate(ss["passes"]):
                for st, subs in ps["stages"].items():
                    for spi, sp in enumerate(subs):
                        sub_lookup[(sh["bundle"], sh["name"], ssi, psi, st, spi)] = sp
    programs = {p["id"]: p for p in mapping["programs"]}

    chosen = []
    for e in mapping["cacheEntries"]:
        if e["status"] != "full":
            continue
        cands = sorted(e["candidates"], key=lambda c: (SOURCE_PRIORITY.get(c["bundle"], 9), c["shader"], c["subShader"], c["pass"]))
        chosen.append((e, cands[0]))
    if args.limit:
        chosen = chosen[:args.limit]

    TMP.mkdir(parents=True, exist_ok=True)
    host = HostCache()
    tasks = []
    for e, c in chosen:
        mods = host.modules(e["index"])
        for stage, name in ((1, "vertex"), (5, "fragment")):
            if stage in mods:
                tasks.append((e["index"], name, mods[stage]))
    print("Module:", len(tasks), file=sys.stderr)
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for entry, stage, res in ex.map(analyse, tasks):
            results[(entry, stage)] = res
    shutil.rmtree(TMP, ignore_errors=True)

    entries_out = []
    agg = defaultdict(lambda: {"entries": 0, "hwCbByUnityBinding": Counter(), "usedMembers": defaultdict(Counter),
                               "dynamic": Counter(), "textureBindings": Counter(), "inputs": Counter(), "outputs": Counter(),
                               "ubos": Counter(), "supportBufferOnlyStages": 0})
    bind_map = Counter()  # (stage, unity cb name, unity binding, hw cb) -> count
    rule_check = Counter()  # (stage, observed without prediction, predicted without observation) -> count
    failed = 0
    for e, c in chosen:
        rec = {"cacheIndex": e["index"], "shader": c["shader"], "bundle": c["bundle"], "subShader": c["subShader"], "pass": c["pass"],
               "candidateCount": len(e["candidates"])}
        a = agg[(c["bundle"], c["shader"])]
        a["entries"] += 1
        for stage, plist in (("vertex", c["vertexPrograms"]), ("fragment", c["fragmentPrograms"])):
            res = results.get((e["index"], stage))
            if not res or not res["ok"]:
                failed += 1
                continue
            rec[stage] = {k: v for k, v in res.items() if k != "ok"}
            pre = "vp" if stage == "vertex" else "fp"
            sub = None
            for pid in plist:
                p = programs[pid]
                sub = sub_lookup.get((p["bundle"], p["shader"], p["subShader"], p["pass"], stage, p["subProgram"]))
                if sub:
                    break
            for u in res["ubos"]:
                a["ubos"][f'{stage}:{u["name"]}:{u["size"]}'] += 1
            if stage == "vertex":
                a["inputs"].update(f"{stage}:{i}" for i in res["inputs"])
            a["outputs"].update(f"{stage}:{i}" for i in res["outputs"])
            a["textureBindings"].update(f'{stage}:{t["set"]}:{t["binding"]}:{t["type"]}' for t in res["textures"])
            for cb in res["dynamicIndexing"]:
                a["dynamic"][f"{stage}:{cb}"] += 1
            if sub:
                cbs = {cb["name"]: cb for cb in sub["constantBuffers"]}
                bind_idx = {b["name"]: b["index"] for b in sub["cbBindings"]}
                # Rule (checked below): HW cbuf = Unity binding index + 3
                predicted = {bind_idx[n] + 3 for n in cbs if n in bind_idx}
                observed = {int(n.split("_c")[1]) for n in res["usedBytes"]}
                rule_check[(stage, tuple(sorted(observed - predicted)), tuple(sorted(predicted - observed)))] += 1
                for n, cb in cbs.items():
                    if n not in bind_idx:
                        continue
                    hw = f"{pre}_c{bind_idx[n] + 3}"
                    bind_map[(stage, n, bind_idx[n], hw)] += 1
                    for o in res["usedBytes"].get(hw, []):
                        for m in cb["members"]:
                            size = (m["components"] * 4) if m["arraySize"] == 0 else m["arraySize"] * 16
                            if m["offset"] <= o < m["offset"] + max(size, 4):
                                a["usedMembers"][f"{stage}:{n}"][m["name"]] += 1
                                break
        entries_out.append(rec)
    summary_agg = {}
    for (bundle, name), a in sorted(agg.items()):
        summary_agg[f"{bundle}: {name}"] = {
            "cacheEntries": a["entries"],
            "ubos": dict(a["ubos"]),
            "textureBindings": dict(a["textureBindings"]),
            "vertexInputs": dict(a["inputs"]),
            "outputs": dict(a["outputs"]),
            "dynamicIndexing": dict(a["dynamic"]),
            "usedMembers": {k: dict(v.most_common()) for k, v in a["usedMembers"].items()},
        }
    out = {"modulesAnalysed": len(results), "modulesFailed": failed, "unityBindingToHwCb": {f"{k[0]}|{k[1]}|{k[2]}->{k[3]}": v for k, v in bind_map.items()},
           "hwCbRuleCheck": {f"{k[0]}|extra_observed={list(k[1])}|not_observed={list(k[2])}": v for k, v in rule_check.items()},
           "perShader": summary_agg, "entries": entries_out}
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("done:", len(results), "modules,", failed, "errors ->", args.out)


if __name__ == "__main__":
    main()
