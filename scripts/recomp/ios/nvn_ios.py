#!/usr/bin/env python3
"""Erzeugt aus der umgeschriebenen metal.m (nvn_rebase32.py) das iOS-Gegenstück metal_ios.m: AppKit durch UIKit ersetzt, der SDL-Fensterteil
(ab der Marke "UI thread") durch scripts/recomp/ios/ui_ios.inc. Aufruf: nvn_ios.py <nvn-src32>"""
import os
import sys

root = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(root, "nvn/metal.m"), encoding="utf-8").read()
marker = "// ================================================================== UI thread"
if marker not in s:
    sys.exit("metal.m: Marke 'UI thread' fehlt")
s = s[: s.index(marker)]
if "#import <AppKit/AppKit.h>" not in s:
    sys.exit("metal.m: AppKit-Import fehlt")
s = s.replace("#import <AppKit/AppKit.h>", "#import <UIKit/UIKit.h>")
s += open(os.path.join(here, "ui_ios.inc"), encoding="utf-8").read()
open(os.path.join(root, "nvn/metal_ios.m"), "w", encoding="utf-8").write(s)

# renderer.m: Depth24Unorm_Stencil8 gibt es unter iOS nicht (Nvidia-Formate werden dort ohnehin auf Depth32Float_Stencil8 abgebildet)
r = open(os.path.join(root, "nvn/renderer.m"), encoding="utf-8").read()
r = r.replace(" || s.pixelFormat == MTLPixelFormatDepth24Unorm_Stencil8", "")
if "Depth24Unorm_Stencil8" in r:
    sys.exit("renderer.m: weitere Depth24Unorm_Stencil8-Stelle, Regel erweitern")
open(os.path.join(root, "nvn/renderer_ios.m"), "w", encoding="utf-8").write(r)
print("metal_ios.m, renderer_ios.m geschrieben")
