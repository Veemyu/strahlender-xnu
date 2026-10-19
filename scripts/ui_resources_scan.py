#!/usr/bin/env python3
"""Liest work/romfs/Data/resources.assets (ohne TypeTree fuer MonoBehaviours): Klassenzaehlung nach Skript-PPtr
und die Zahlenfelder von MsgWindowConfig nach dem Feldlayout aus work/il2cpp/dump.cs.

Ausgabe nur auf stdout und work/ui/resources_scan.json; keine Texte.
"""
import collections
import json
import os
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "pydeps"))
DATA = os.path.join(ROOT, "work", "romfs", "Data")
OUT = os.path.join(ROOT, "work", "ui")


def script_names():
    import UnityPy
    env = UnityPy.load(os.path.join(DATA, "globalgamemanagers.assets"))
    names = {}
    for o in env.objects:
        if o.type.name == "MonoScript":
            d = o.read()
            names[o.path_id] = (d.m_Namespace + "." if d.m_Namespace else "") + d.m_ClassName
    return names


def main():
    import UnityPy
    names = script_names()
    env = UnityPy.load(os.path.join(DATA, "resources.assets"))
    counts = collections.Counter()
    types = collections.Counter(o.type.name for o in env.objects)
    cfg = []
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        # m_GameObject(PPtr 12) m_Enabled(1+3) m_Script(PPtr 12): Script-PPtr bei Offset 16
        file_id, path_id = struct.unpack_from("<iq", raw, 16)
        cls = names.get(path_id, "?%d/%d" % (file_id, path_id))
        counts[cls] += 1
        if cls.endswith("MsgWindowConfig"):
            n = struct.unpack_from("<i", raw, 28)[0]
            off = 32
            ln = n
            if ln < 0 or ln > 16:
                cfg.append({"fehler": "Namenslaenge unplausibel", "n": n})
                continue
            off += (ln + 3) & ~3
            cnt = struct.unpack_from("<i", raw, off)[0]
            off += 4
            speeds = list(struct.unpack_from("<%df" % cnt, raw, off))
            off += 4 * cnt
            f = struct.unpack_from("<7f", raw, off)
            off += 28
            wait_frames = struct.unpack_from("<i", raw, off)[0]
            off += 4
            pad, anim = struct.unpack_from("<fi", raw, off)
            cfg.append({"msgSpeed": speeds, "windowWidthOffset": f[0], "speakerFrameWidthOffset": f[1], "offsetMessagePosX": f[2],
                        "iconMoveDist": f[3], "addAngleSec": f[4], "fastForwardMagnification": f[5],
                        "scrollTextDuration": f[6], "waitAfterFinishMsgFrame": wait_frames, "textLinePaddingOffset": pad,
                        "wndAnimType": anim, "rest_bytes": len(raw) - off})
    out = {"objekttypen": dict(types), "skriptklassen": dict(counts.most_common()), "MsgWindowConfig": cfg}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "resources_scan.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out["objekttypen"]))
    for k, v in counts.most_common():
        print(k, v)
    print(cfg)


if __name__ == "__main__":
    main()
