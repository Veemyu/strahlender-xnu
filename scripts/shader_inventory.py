#!/usr/bin/env python3
"""Liest die Shader-Objekte der Switch-Bundles (UnityFS, Unity 2019.4) per UnityPy-TypeTree
und schreibt ein strukturiertes Inventar (nur Namen, Zahlen, Render-States, Parameter-Layouts;
keine Binaerdaten).

Aufruf (aus dem Repo-Root):
    PYTHONPATH=tools/pydeps python3 scripts/shader_inventory.py [--out work/shaders/inventory.json]
"""
import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path

import lz4.block
import UnityPy

BUNDLES = [
    "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/shaders",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Effects/fxparticle",
]
# Zusaetzliche Shader-Quelle ausserhalb der beiden Bundles (9 Shader, siehe docs/shader-inventar.md)
EXTRA_SOURCES = [
    "work/romfs/Data/resources.assets",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/tmpshader",
    "work/romfs/Data/StreamingAssets/AssetAssistant/FureaiHiroba/poffin/prefabs",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Environments/prefab_map/c10r0101",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Environments/underground/ugspace03",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Environments/bg/arenas/ground/g070",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/scenes/digfossil",
    "work/romfs/Data/StreamingAssets/AssetAssistant/Dpr/fieldui/gymseq",
]

BLEND = {0: "Zero", 1: "One", 2: "DstColor", 3: "SrcColor", 4: "OneMinusDstColor", 5: "SrcAlpha",
         6: "OneMinusSrcColor", 7: "DstAlpha", 8: "OneMinusDstAlpha", 9: "SrcAlphaSaturate",
         10: "OneMinusSrcAlpha"}
BLENDOP = {0: "Add", 1: "Sub", 2: "RevSub", 3: "Min", 4: "Max"}
COMPARE = {0: "Disabled", 1: "Never", 2: "Less", 3: "Equal", 4: "LEqual", 5: "Greater",
           6: "NotEqual", 7: "GEqual", 8: "Always"}
CULL = {0: "Off", 1: "Front", 2: "Back"}
STENCIL_OP = {0: "Keep", 1: "Zero", 2: "Replace", 3: "IncrSat", 4: "DecrSat", 5: "Invert",
              6: "IncrWrap", 7: "DecrWrap"}
PROP_TYPE = {0: "Color", 1: "Vector", 2: "Float", 3: "Range", 4: "Texture"}
TEX_DIM = {0: "None", 1: "Any", 2: "2D", 3: "3D", 4: "Cube", 5: "2DArray", 6: "CubeArray"}
PASS_TYPE = {0: "Normal", 1: "Use", 2: "Grab"}
GPU_TYPE = {26: "ConsoleVS", 27: "ConsoleFS", 28: "ConsoleHS", 29: "ConsoleDS", 30: "ConsoleGS"}
PLATFORM = {18: "Vulkan", 19: "Switch"}


def fval(v):
    """Wert einer ShaderLab-Zahl: (Zahl, Name der Material-Eigenschaft oder None)."""
    name = v.get("name")
    return v.get("val"), (None if name in (None, "", "<noninit>") else name)


def dec(table, v):
    return table.get(int(v), int(v)) if v is not None else None


def decode_state(st):
    rt = []
    for i in range(8):
        b = st[f"rtBlend{i}"]
        d = {}
        for key, tab in (("srcBlend", BLEND), ("destBlend", BLEND), ("srcBlendAlpha", BLEND),
                         ("destBlendAlpha", BLEND), ("blendOp", BLENDOP), ("blendOpAlpha", BLENDOP)):
            v, n = fval(b[key])
            d[key] = dec(tab, v)
            if n:
                d[key + "_prop"] = n
        v, n = fval(b["colMask"])
        d["colMask"] = int(v)
        if n:
            d["colMask_prop"] = n
        rt.append(d)
    out = {"rtBlend": rt if st["rtSeparateBlend"] else rt[:1], "rtSeparateBlend": st["rtSeparateBlend"]}
    for key, tab in (("zTest", COMPARE), ("culling", CULL)):
        v, n = fval(st[key])
        out[key] = dec(tab, v)
        if n:
            out[key + "_prop"] = n
    for key in ("zWrite", "zClip", "offsetFactor", "offsetUnits", "alphaToMask", "stencilReadMask",
                "stencilWriteMask", "stencilRef"):
        v, n = fval(st[key])
        out[key] = v
        if n:
            out[key + "_prop"] = n
    for key in ("stencilOp", "stencilOpFront", "stencilOpBack"):
        s = st[key]
        d = {}
        for k2, v in s.items():
            val, n = fval(v)
            tab = COMPARE if k2 == "comp" else STENCIL_OP
            d[k2] = dec(tab, val)
            if n:
                d[k2 + "_prop"] = n
        out[key] = d
    out["fogMode"] = st["fogMode"]
    out["lighting"] = st["lighting"]
    out["lod"] = st["m_LOD"]
    out["tags"] = {t[0]: t[1] for t in st["m_Tags"]["tags"]}
    out["gpuProgramID"] = st["gpuProgramID"]
    return out


def tags_of(d):
    return {t[0]: t[1] for t in d["tags"]}


def decode_props(parsed):
    props = []
    for p in parsed["m_PropInfo"]["m_Props"]:
        e = {"name": p["m_Name"], "label": p["m_Description"], "type": PROP_TYPE.get(p["m_Type"], p["m_Type"]),
             "flags": p["m_Flags"], "attributes": list(p["m_Attributes"])}
        if p["m_Type"] == 4:
            e["texDim"] = TEX_DIM.get(p["m_DefTexture"]["m_TexDim"], p["m_DefTexture"]["m_TexDim"])
            e["defaultTexture"] = p["m_DefTexture"]["m_DefaultName"]
        else:
            e["default"] = [p[f"m_DefValue[{i}]"] for i in range(4)] if p["m_Type"] in (0, 1) else \
                [p["m_DefValue[0]"]] if p["m_Type"] == 2 else \
                [p["m_DefValue[0]"], p["m_DefValue[1]"], p["m_DefValue[2]"]]
        props.append(e)
    return props


class Blob:
    """Dekomprimierte Segmente des Programm-Blobs eines Shaders fuer eine Plattform."""

    def __init__(self, tt, plat_index=0):
        raw = bytes(tt["compressedBlob"])
        self.segments = []
        for off, cl, dl in zip(tt["offsets"][plat_index], tt["compressedLengths"][plat_index],
                               tt["decompressedLengths"][plat_index]):
            self.segments.append(lz4.block.decompress(raw[off:off + cl], uncompressed_size=dl))
        seg0 = self.segments[0]
        cnt = struct.unpack_from("<I", seg0, 0)[0]
        self.entries = [struct.unpack_from("<III", seg0, 4 + 12 * i) for i in range(cnt)]

    def get(self, idx):
        off, ln, seg = self.entries[idx]
        return self.segments[seg][off:off + ln]


def struct_info(s, names_by_idx):
    """Struktur-Feld eines Konstantenpuffers (Instancing: Array von Strukturen, z. B. unity_Builtins0Array)."""
    def members(ms, kind):
        return [{"name": names_by_idx.get(m["m_NameIndex"], f"#{m['m_NameIndex']}"), "offset": m["m_Index"],
                 "arraySize": m["m_ArraySize"], "kind": kind,
                 "components": m["m_RowCount"] * 4 if kind == "matrix" else m["m_Dim"]} for m in ms]
    mem = members(s["m_MatrixMembers"], "matrix") + members(s["m_VectorMembers"], "vector")
    mem.sort(key=lambda m: m["offset"])
    return {"name": names_by_idx.get(s["m_NameIndex"], f"#{s['m_NameIndex']}"), "offset": s["m_Index"],
            "arraySize": s["m_ArraySize"], "structSize": s["m_StructSize"], "members": mem}


def stage_info(prog, names_by_idx, blob):
    subs = []
    for sp in prog["m_SubPrograms"]:
        cbs = []
        for cb in sp["m_ConstantBuffers"]:
            members = [(names_by_idx.get(m["m_NameIndex"], f"#{m['m_NameIndex']}"), m["m_Index"], m["m_RowCount"] * 4 if "m_RowCount" in m else m["m_Dim"], m["m_ArraySize"], "matrix" if "m_RowCount" in m else "vector")
                       for m in cb["m_MatrixParams"] + cb["m_VectorParams"]]
            members.sort(key=lambda m: m[1])
            cbs.append({"name": names_by_idx.get(cb["m_NameIndex"], f"#{cb['m_NameIndex']}"), "size": cb["m_Size"],
                        "members": [{"name": a, "offset": b, "components": c, "arraySize": d, "kind": e} for a, b, c, d, e in members],
                        "structParams": len(cb["m_StructParams"]),
                        "structs": [struct_info(s, names_by_idx) for s in cb["m_StructParams"]]})
        bindings = [{"name": names_by_idx.get(b["m_NameIndex"], f"#{b['m_NameIndex']}"), "index": b["m_Index"]}
                    for b in sp["m_ConstantBufferBindings"]]
        tex = [{"name": names_by_idx.get(t["m_NameIndex"], f"#{t['m_NameIndex']}"), "index": t["m_Index"],
                "sampler": t["m_SamplerIndex"], "dim": TEX_DIM.get(t["m_Dim"], t["m_Dim"]), "multisampled": t["m_MultiSampled"]}
               for t in sp["m_TextureParams"]]
        kws = [names_by_idx.get(i, f"#{i}") for i in sp["m_GlobalKeywordIndices"]]
        lkws = [names_by_idx.get(i, f"#{i}") for i in sp["m_LocalKeywordIndices"]]
        e = blob.entries[sp["m_BlobIndex"]]
        subs.append({
            "blobIndex": sp["m_BlobIndex"], "blobSize": e[1], "blobSegment": e[2],
            "gpuProgramType": GPU_TYPE.get(sp["m_GpuProgramType"], sp["m_GpuProgramType"]),
            "hwTier": sp["m_ShaderHardwareTier"], "requirements": sp["m_ShaderRequirements"],
            "globalKeywords": kws, "localKeywords": lkws,
            "inputChannels": [{"source": c["source"], "target": c["target"]} for c in sp["m_Channels"]["m_Channels"]],
            "sourceMap": sp["m_Channels"]["m_SourceMap"],
            "constantBuffers": cbs, "cbBindings": bindings, "textures": tex,
            "looseVectorParams": len(sp["m_VectorParams"]), "looseMatrixParams": len(sp["m_MatrixParams"]),
            "bufferParams": len(sp["m_BufferParams"]), "uavParams": len(sp["m_UAVParams"]),
            "buffers": [{"name": names_by_idx.get(b["m_NameIndex"], f"#{b['m_NameIndex']}"), "index": b["m_Index"]}
                        for b in sp["m_BufferParams"]],
            "samplerCount": len(sp["m_Samplers"]),
        })
    return subs


def inventory_shader(obj, bundle):
    tt = obj.read_typetree()
    parsed = tt["m_ParsedForm"]
    blob = Blob(tt)
    sh = {
        "bundle": Path(bundle).name, "pathId": obj.path_id, "name": parsed["m_Name"],
        "customEditor": parsed["m_CustomEditorName"], "fallback": parsed["m_FallbackName"],
        "dependencies": [d for d in parsed["m_Dependencies"]] if parsed["m_Dependencies"] else [],
        "platforms": [PLATFORM.get(p, p) for p in tt["platforms"]],
        "blob": {"segments": len(blob.segments), "compressed": sum(tt["compressedLengths"][0]),
                 "decompressed": sum(tt["decompressedLengths"][0]), "entries": len(blob.entries),
                 "entryBytes": sum(e[1] for e in blob.entries)},
        "properties": decode_props(parsed), "subShaders": [],
    }
    for ss in parsed["m_SubShaders"]:
        ssd = {"lod": ss["m_LOD"], "tags": tags_of(ss["m_Tags"]), "passes": []}
        for ps in ss["m_Passes"]:
            names = {i: n for n, i in ps["m_NameIndices"]}
            stages = {}
            for key in ("progVertex", "progFragment", "progGeometry", "progHull", "progDomain", "progRayTracing"):
                stages[key[4:].lower()] = stage_info(ps[key], names, blob)
            pd = {"type": PASS_TYPE.get(ps["m_Type"], ps["m_Type"]), "name": ps["m_Name"], "useName": ps["m_UseName"],
                  "textureName": ps["m_TextureName"], "tags": tags_of(ps["m_Tags"]),
                  "programMask": ps["m_ProgramMask"], "hasInstancing": ps["m_HasInstancingVariant"],
                  "hasProceduralInstancing": ps["m_HasProceduralInstancingVariant"],
                  "state": decode_state(ps["m_State"]), "nameTable": {n: i for n, i in ps["m_NameIndices"]},
                  "stages": stages}
            pd["programCounts"] = {k: len(v) for k, v in stages.items()}
            combos = Counter()
            for k, v in stages.items():
                for sub in v:
                    combos[tuple(sorted(sub["globalKeywords"] + sub["localKeywords"]))] += 1
            pd["keywordCombinations"] = len(combos)
            pd["keywords"] = sorted({kw for c in combos for kw in c})
            ssd["passes"].append(pd)
        sh["subShaders"].append(ssd)
    return sh


def inventory_svc(env):
    out = []
    for o in env.objects:
        if o.type.name == "ShaderVariantCollection":
            tt = o.read_typetree()
            out.append(tt)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/shaders/inventory.json")
    args = ap.parse_args()
    result = {"bundles": {}, "shaders": [], "extraShaders": []}
    for src in EXTRA_SOURCES:
        env = UnityPy.load(src)
        for o in env.objects:
            if o.type.name == "Shader":
                result["extraShaders"].append(inventory_shader(o, src))
    for b in BUNDLES:
        env = UnityPy.load(b)
        cnt = Counter(o.type.name for o in env.objects)
        result["bundles"][Path(b).name] = {"objectTypes": dict(cnt), "size": Path(b).stat().st_size}
        for o in env.objects:
            if o.type.name == "Shader":
                result["shaders"].append(inventory_shader(o, b))
        svcs = []
        for tt in inventory_svc(env):
            for sh in tt["m_Shaders"]:
                pid = sh[0]["m_PathID"]
                svcs.append({"collection": tt["m_Name"], "shaderPathId": pid,
                             "variants": [{"keywords": v["keywords"], "passType": v["passType"]} for v in sh[1]["variants"]]})
        if svcs:
            result["bundles"][Path(b).name]["variantCollections"] = svcs
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(len(result["shaders"]), "Shader +", len(result["extraShaders"]), "aus weiteren Quellen ->", args.out)


if __name__ == "__main__":
    sys.exit(main())
