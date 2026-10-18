#!/usr/bin/env python3
"""Erzeugt Markdown-Tabellen und Kennzahlen fuer docs/shader-inventar.md aus den JSON-Dateien
(work/shaders/inventory.json, mapping.json, reflect.json).

Aufruf: python3 scripts/shader_report.py [--out work/shaders/tables.md]
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

FAMILIES = [
    ("Charakter / Pokémon-Modelle", ["Delphis/Character/", "Delphis/Poffin", "Mitake/MitakeStandard", "Mitake/MitakeDepthOnly"]),
    ("Umgebung", ["Delphis/Map/", "Delphis/Snowfield", "Delphis/WaterSimulation", "Custom/WaterInteration", "Dpr/Objects/", "Custom/StencilMask"]),
    ("UI / Text / Video", ["UI/", "TextMeshPro/", "MovieTexture", "Delphis/UI/"]),
    ("Partikel / Effekte", ["FxSystem/", "Mitake/Fire", "Mitake/Smoke", "Mitake/MitakeGround", "Custom/ProceduralPlane", "Custom/AfterImage",
                            "Delphis/Battle/", "Custom/Contest/", "Delphis/Dig/", "Delphis/Map/Additive"]),
    ("Post-Processing", ["Custom/Bloom", "Custom/DepthOfField", "Custom/Fxaa", "Custom/Gaussian", "Custom/Downsample", "Custom/ExpandFocus",
                         "Custom/ResolveFocus", "Custom/CaptureFocus", "Custom/EffectCopy", "Dpr/PostEffect/"]),
]
FAMILY_FIRST = ["Partikel / Effekte"]  # Vorrang bei Mehrfachtreffern (z. B. Delphis/Map/Additive)

BUILTIN_RE = re.compile(r"^(unity_|glstate_|_WorldSpace|_ProjectionParams$|_ScreenParams$|_ZBufferParams$|_Time$|_SinTime$|_CosTime$|"
                        r"_LightColor0$|_LightShadowData$|_LightPositionRange$|_ShadowOffsets|_SpecColor$|_Light\w*Params$|_CameraDepth)")
DERIVED_RE = re.compile(r"(_ST|_TexelSize|_HDR|_ProjS)$")
BLEND = {"Zero": "0", "One": "1"}


def family(name):
    order = FAMILY_FIRST + [f for f, _ in FAMILIES if f not in FAMILY_FIRST]
    fam = dict(FAMILIES)
    for f in order:
        for pre in fam[f]:
            if name.startswith(pre):
                return f
    return "Sonstige"


def stencil_active(st):
    sop = st["stencilOp"]
    return sop.get("comp") not in (None, "Disabled", "Always") or sop.get("pass") not in (None, "Keep") or sop.get("fail") not in (None, "Keep") or sop.get("zfail") not in (None, "Keep")


def state_str(st, tags):
    parts = []
    r = st["rtBlend"][0]
    if r.get("srcBlend_prop") or r.get("destBlend_prop"):
        parts.append(f'Blend [{r.get("srcBlend_prop")}] [{r.get("destBlend_prop")}]')
    elif not (r["srcBlend"] == "One" and r["destBlend"] == "Zero"):
        s = f'Blend {r["srcBlend"]} {r["destBlend"]}'
        if r["srcBlendAlpha"] != r["srcBlend"] or r["destBlendAlpha"] != r["destBlend"]:
            s += f', {r["srcBlendAlpha"]} {r["destBlendAlpha"]}'
        if r["blendOp"] != "Add":
            s += f' Op {r["blendOp"]}'
        parts.append(s)
    zw = st["zWrite"]
    parts.append("ZWrite " + (f'[{st["zWrite_prop"]}]' if st.get("zWrite_prop") else "On" if zw == 1 else "Off"))
    parts.append("ZTest " + (f'[{st["zTest_prop"]}]' if st.get("zTest_prop") else st["zTest"]))
    parts.append("Cull " + (f'[{st["culling_prop"]}]' if st.get("culling_prop") else st["culling"]))
    cm = r["colMask"]
    if r.get("colMask_prop"):
        parts.append(f'ColorMask [{r["colMask_prop"]}]')
    elif cm != 15:
        parts.append(f"ColorMask {cm}")
    if st["offsetFactor"] or st["offsetUnits"]:
        parts.append(f'Offset {st["offsetFactor"]},{st["offsetUnits"]}')
    if stencil_active(st):
        sop = st["stencilOp"]
        parts.append(f'Stencil Ref {int(st["stencilRef"])} Comp {sop.get("comp")} Pass {sop.get("pass")}')
    if st["alphaToMask"]:
        parts.append("AlphaToMask")
    return "; ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/shaders/tables.md")
    args = ap.parse_args()
    inv = json.load(open("work/shaders/inventory.json"))
    mp = json.load(open("work/shaders/mapping.json"))
    rf = json.load(open("work/shaders/reflect.json"))
    per = mp["stats"]["perShader"]
    out = []
    w = out.append

    shaders = inv["shaders"]
    byfam = defaultdict(list)
    for s in shaders:
        byfam[family(s["name"])].append(s)

    # Pro Shader: Kennzahlen
    def info(s):
        passes = [p for ss in s["subShaders"] for p in ss["passes"]]
        v = sum(p["programCounts"]["vertex"] for p in passes)
        f = sum(p["programCounts"]["fragment"] for p in passes)
        kwc = sum(p["keywordCombinations"] for p in passes)
        kws = sorted({k for p in passes for k in p["keywords"]})
        tex = [p["name"] for p in s["properties"] if p["type"] == "Texture"]
        inst = any(p["hasInstancing"] for p in passes)
        return passes, v, f, kwc, kws, tex, inst

    w("## Tabelle A: Übersicht je Shader\n")
    w("Spalten: Pässe (alle SubShader), Programme Vertex/Fragment, Keyword-Kombinationen (Summe über Pässe), Keywords (Anzahl), Eigenschaften (gesamt/Texturen), Instancing, Cache-Einträge (voll zugeordnet).\n")
    for fam, lst in sorted(byfam.items()):
        w(f"\n### {fam} ({len(lst)})\n")
        w("| Shader | Pässe | V/F | Kombi | Kw | Prop/Tex | Inst | Cache |")
        w("|---|---|---|---|---|---|---|---|")
        for s in sorted(lst, key=lambda x: x["name"]):
            passes, v, f, kwc, kws, tex, inst = info(s)
            c = per.get(f'{s["bundle"]}: {s["name"]}', {}).get("cacheEntries", 0)
            w(f'| `{s["name"]}` | {len(passes)} | {v}/{f} | {kwc} | {len(kws)} | {len(s["properties"])}/{len(tex)} | {"ja" if inst else "nein"} | {c} |')

    w("\n## Tabelle B: Render-State je Pass\n")
    for fam, lst in sorted(byfam.items()):
        w(f"\n### {fam}\n")
        w("| Shader | Pass | Tags | State |")
        w("|---|---|---|---|")
        for s in sorted(lst, key=lambda x: x["name"]):
            for ss in s["subShaders"]:
                sst = ", ".join(f"{k}={v}" for k, v in sorted(ss["tags"].items()))
                for i, p in enumerate(ss["passes"]):
                    pt = ", ".join(f"{k.title() if k == 'LIGHTMODE' else k}={v}" for k, v in sorted({**p["tags"], **p["state"]["tags"]}.items())
                                   if k in ("LIGHTMODE", "QUEUE", "RenderType"))
                    nm = p["name"] or p["useName"] or f"#{i}"
                    typ = "" if p["type"] == "Normal" else f' ({p["type"]})'
                    w(f'| `{s["name"]}` | {nm}{typ} | {pt or sst} | {state_str(p["state"], p["tags"])} |')

    # Statistik
    stat = Counter()
    blend = Counter(); zw = Counter(); zt = Counter(); cull = Counter(); queue = Counter(); rtype = Counter(); lod = Counter()
    stencil = 0; passcount = Counter(); usepass = 0; grab = 0
    inst_shaders = []
    prog = Counter()
    props_types = Counter()
    for s in shaders:
        passes = [p for ss in s["subShaders"] for p in ss["passes"]]
        passcount[len(passes)] += 1
        lod[tuple(ss["lod"] for ss in s["subShaders"])] += 1
        for ss in s["subShaders"]:
            queue[ss["tags"].get("Queue") or ss["tags"].get("QUEUE", "-")] += 1
            rtype[ss["tags"].get("RenderType", "-")] += 1
        for p in passes:
            st = p["state"]; r = st["rtBlend"][0]
            blend[f'{r["srcBlend"]}/{r["destBlend"]}' + ("(Prop)" if r.get("srcBlend_prop") else "")] += 1
            zw[str(st["zWrite"]) + ("(Prop)" if st.get("zWrite_prop") else "")] += 1
            zt[st["zTest"] + ("(Prop)" if st.get("zTest_prop") else "")] += 1
            cull[st["culling"] + ("(Prop)" if st.get("culling_prop") else "")] += 1
            if stencil_active(st):
                stencil += 1
            if p["type"] == "Use": usepass += 1
            if p["type"] == "Grab": grab += 1
            for k, v in p["programCounts"].items():
                prog[k] += v
        if any(p["hasInstancing"] for p in passes):
            inst_shaders.append(s["name"])
        for pr in s["properties"]:
            props_types[pr["type"]] += 1
    w("\n## Kennzahlen (64 Shader)\n")
    w(f"- Programme gesamt (Vertex/Fragment/Geometry/Hull/Domain): {prog['vertex']}/{prog['fragment']}/{prog['geometry']}/{prog['hull']}/{prog['domain']}")
    w(f"- Pässe je Shader: {dict(sorted(passcount.items()))}; SubShader-LOD: {dict(lod)}")
    w(f"- Queue-Tags: {dict(queue)}; RenderType: {dict(rtype)}")
    w(f"- Blend (Pass-Zähler): {dict(blend)}")
    w(f"- ZWrite: {dict(zw)}; ZTest: {dict(zt)}; Cull: {dict(cull)}; Pässe mit Stencil: {stencil}; UsePass/GrabPass: {usepass}/{grab}")
    w(f"- Shader mit Instancing-Variante: {len(inst_shaders)} ({', '.join(sorted(inst_shaders))})")
    w(f"- Eigenschaftstypen (alle Shader): {dict(props_types)}")
    custom = Counter(s["customEditor"] for s in shaders if s["customEditor"])
    fb = {s["name"]: s["fallback"] for s in shaders if s["fallback"]}
    w(f"- CustomEditor: {dict(custom)}; Fallback: {fb}")
    w(f"- Plattform-IDs: {dict(Counter(tuple(s['platforms']) for s in shaders))}")
    blobs = sum(s["blob"]["compressed"] for s in shaders), sum(s["blob"]["decompressed"] for s in shaders)
    w(f"- Programm-Blobs: {blobs[0]} B komprimiert, {blobs[1]} B entpackt; Segmente je Shader: {dict(Counter(s['blob']['segments'] for s in shaders))}")
    gp = Counter(); hw = Counter(); sm = Counter()
    for s in shaders:
        for ss in s["subShaders"]:
            for p in ss["passes"]:
                for st, subs in p["stages"].items():
                    for sp in subs:
                        gp[sp["gpuProgramType"]] += 1; hw[sp["hwTier"]] += 1; sm[sp["requirements"]] += 1
    w(f"- GpuProgramType: {dict(gp)}; HardwareTier: {dict(hw)}; ShaderRequirements: {dict(sm)}")

    # Eingänge/Texturen
    texdim = Counter(); texprops = Counter()
    for s in shaders:
        for p in s["properties"]:
            if p["type"] == "Texture":
                texdim[p["texDim"]] += 1; texprops[p["name"]] += 1
    w(f"- Textur-Eigenschaften: {dict(texdim)}; häufigste Namen: {texprops.most_common(12)}")
    chans = Counter()
    for s in shaders:
        for ss in s["subShaders"]:
            for p in ss["passes"]:
                for sp in p["stages"]["vertex"]:
                    chans[tuple(sorted((c["source"], c["target"]) for c in sp["inputChannels"]))] += 1
    w(f"- Vertex-Kanalbelegungen (Unity-Quelle→Eingang), häufigste: {chans.most_common(6)}")

    # Member-Klassifikation
    cls = defaultdict(lambda: defaultdict(set))  # klasse -> name -> shaders
    for s in inv["shaders"] + inv["extraShaders"]:
        propnames = {p["name"] for p in s["properties"]}
        for ss in s["subShaders"]:
            for p in ss["passes"]:
                for st, subs in p["stages"].items():
                    for sp in subs:
                        for cb in sp["constantBuffers"]:
                            for m in cb["members"]:
                                n = m["name"]
                                if BUILTIN_RE.match(n) and n not in propnames:
                                    k = "builtin"
                                elif n in propnames:
                                    k = "material"
                                elif DERIVED_RE.search(n) and DERIVED_RE.sub("", n) in propnames:
                                    k = "derived"
                                else:
                                    k = "global"
                                cls[k][n].add(s["name"])
    w("\n## Konstanten-Klassifikation (Namen in VGlobals/PGlobals/UnityInstancing_*)\n")
    for k in ("builtin", "derived", "material", "global"):
        w(f"- {k}: {len(cls[k])} Namen")
    w("\n### Unity-Built-ins (Name: Anzahl Shader)\n")
    w(", ".join(f"`{n}` {len(v)}" for n, v in sorted(cls["builtin"].items(), key=lambda kv: (-len(kv[1]), kv[0]))))
    w("\n### Nicht-Material, nicht-Built-in („globale“ Werte, vom Spiel zu liefern)\n")
    w(", ".join(f"`{n}` {len(v)}" for n, v in sorted(cls["global"].items(), key=lambda kv: (-len(kv[1]), kv[0]))))

    # Verwendete Built-ins laut SPIR-V
    used = defaultdict(set)
    for key, v in rf["perShader"].items():
        for cb, names in v["usedMembers"].items():
            for n in names:
                if BUILTIN_RE.match(n):
                    used[n].add(key)
    w("\n### Tatsächlich im Code genutzte Built-ins (Zahl Shader, SPIR-V-Zugriffe der zugeordneten Cache-Module)\n")
    w(", ".join(f"`{n}` {len(v)}" for n, v in sorted(used.items(), key=lambda kv: (-len(kv[1]), kv[0]))))
    w("\n### Reflexion: Constant-Buffer-Bindung\n")
    w(f"- {json.dumps(rf['unityBindingToHwCb'])}")
    w(f"- Regelprüfung (HW-cbuf = Unity-Bindung + 3): {json.dumps(rf['hwCbRuleCheck'])}")
    ubo = Counter(); tb = Counter(); dyn = Counter(); vin = Counter()
    for key, v in rf["perShader"].items():
        for k in v["ubos"]:
            st, nm, sz = k.split(":")
            ubo[f"{st}:{nm}:{sz}"] += v["ubos"][k]
        for k in v["dynamicIndexing"]:
            dyn[k] += v["dynamicIndexing"][k]
    w(f"- UBO-Namen/-Größen (Zähler über Module): {dict(ubo)}")
    w(f"- Dynamisch indizierte Constant-Buffer: {dict(dyn)}")
    Path(args.out).write_text("\n".join(out) + "\n")
    print("geschrieben:", args.out, len(out), "Zeilen")


if __name__ == "__main__":
    main()
