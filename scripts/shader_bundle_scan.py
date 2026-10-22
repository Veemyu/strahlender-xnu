#!/usr/bin/env python3
"""Counts shader objects in Unity bundles (metadata/numbers only). Needs UnityPy."""
import sys
from collections import Counter

import UnityPy

for path in sys.argv[1:]:
    env = UnityPy.load(path)
    types = Counter()
    shaders = []
    for o in env.objects:
        types[o.type.name] += 1
        if o.type.name == "Shader":
            try:
                s = o.parse_as_object() if hasattr(o, "parse_as_object") else o.read()
                shaders.append(s)
            except Exception as e:  # noqa
                shaders.append(None)
    print(path.split("/")[-1], dict(types.most_common(6)))
    print("  Shader-Objekte:", len(shaders))
    plat = Counter()
    sub = 0
    for s in shaders:
        if s is None:
            continue
        try:
            for p in s.platforms:
                plat[int(p)] += 1
        except Exception:
            pass
    print("  Plattform-IDs (gpu api enum):", dict(plat))
