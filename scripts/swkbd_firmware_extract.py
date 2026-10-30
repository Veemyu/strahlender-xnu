#!/usr/bin/env python3
"""Extracts the files the on-screen keyboard needs from the user's own Switch firmware into one folder (BDSP_FIRMWARE_DATA).

  swkbd_firmware_extract.py --nca-dir <registered NCA folder> --keys <prod.keys> --hactool <hactool> --out <folder>

Output (nothing of it belongs in the repository):
  swkbd/lyt/*.szs                              keyboard layouts and animations (title 0100000000001008)
  swkbd/message/<language>/swkbd.msbt.szs      button labels
  swkbd/sound/swkbd.bfsar                      sound archive of the keyboard (key, cursor, enter sounds)
  fonts/nintendo_udsg-r_std_003.bfttf          text font (title 0100000000000811)
  fonts/nintendo_ext_003.bfttf                 button glyphs (title 0100000000000810)
  fonts/nintendo_ud*.bfttf                       Chinese and Korean text fonts, for characters the text font lacks (titles 0100000000000812 to 14; optional)
  0100000000000823.romfs                       word list of the name check (title 0100000000000823)

hactool prints key material in some warnings; its output is never shown, only the Title ID / Content Type / Content Size lines are read.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

SWKBD, FONT_STD, FONT_EXT, NGWORDS = "0100000000001008", "0100000000000811", "0100000000000810", "0100000000000823"
FONTS_CJK = ("0100000000000812", "0100000000000813", "0100000000000814")   # Chinese simplified / traditional, Korean


def hactool(tool, keys, args):
    r = subprocess.run([tool, "-k", keys] + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace")
    return r.stdout


def nca_info(tool, keys, path):
    out = hactool(tool, keys, ["-i", path])
    info = {}
    for line in out.splitlines():
        for key in ("Title ID", "Content Type", "Content Size"):
            if line.startswith(key + ":"):
                info[key] = line.split(":", 1)[1].strip()
    return info


def find_ncas(nca_dir, tool, keys, wanted):
    found = {}
    for name in sorted(os.listdir(nca_dir)):
        p = os.path.join(nca_dir, name)
        if os.path.isdir(p):
            p = os.path.join(p, "00")
        if not os.path.isfile(p):
            continue
        info = nca_info(tool, keys, p)
        tid = info.get("Title ID", "")
        if tid in wanted and info.get("Content Type") in ("Program", "Data", "PublicData"):
            size = int(info.get("Content Size", "0"), 16) if info.get("Content Size", "0").startswith("0x") else 0
            if tid not in found or size > found[tid][1]:
                found[tid] = (p, size)
    return {t: v[0] for t, v in found.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nca-dir", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--hactool", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ncas = find_ncas(a.nca_dir, a.hactool, a.keys, {SWKBD, FONT_STD, FONT_EXT, NGWORDS, *FONTS_CJK})
    missing = [t for t in (SWKBD, FONT_STD, FONT_EXT, NGWORDS) if t not in ncas]
    if missing:
        print("not found in the firmware folder: " + ", ".join(missing), file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if SWKBD in ncas:
            d = os.path.join(tmp, "swkbd")
            hactool(a.hactool, a.keys, ["--romfsdir=" + d, ncas[SWKBD]])
            lyt = os.path.join(a.out, "swkbd", "lyt")
            os.makedirs(lyt, exist_ok=True)
            for f in os.listdir(os.path.join(d, "lyt")):
                shutil.copy2(os.path.join(d, "lyt", f), lyt)
            snd = os.path.join(d, "sound")
            for f in os.listdir(snd) if os.path.isdir(snd) else []:
                os.makedirs(os.path.join(a.out, "swkbd", "sound"), exist_ok=True)
                shutil.copy2(os.path.join(snd, f), os.path.join(a.out, "swkbd", "sound"))
            msg = os.path.join(d, "message")
            for lang in os.listdir(msg) if os.path.isdir(msg) else []:
                src = os.path.join(msg, lang, "swkbd.msbt.szs")
                if os.path.isfile(src):
                    os.makedirs(os.path.join(a.out, "swkbd", "message", lang), exist_ok=True)
                    shutil.copy2(src, os.path.join(a.out, "swkbd", "message", lang, "swkbd.msbt.szs"))
        for tid, names in ((FONT_STD, ["nintendo_udsg-r_std_003.bfttf"]), (FONT_EXT, ["nintendo_ext_003.bfttf"])):
            if tid in ncas:
                d = os.path.join(tmp, tid)
                hactool(a.hactool, a.keys, ["--romfsdir=" + d, ncas[tid]])
                os.makedirs(os.path.join(a.out, "fonts"), exist_ok=True)
                for n in names:
                    if os.path.isfile(os.path.join(d, n)):
                        shutil.copy2(os.path.join(d, n), os.path.join(a.out, "fonts", n))
        for tid in FONTS_CJK:   # optional: every bfttf the title holds
            if tid in ncas:
                d = os.path.join(tmp, tid)
                hactool(a.hactool, a.keys, ["--romfsdir=" + d, ncas[tid]])
                os.makedirs(os.path.join(a.out, "fonts"), exist_ok=True)
                for n in os.listdir(d) if os.path.isdir(d) else []:
                    if n.endswith(".bfttf"):
                        shutil.copy2(os.path.join(d, n), os.path.join(a.out, "fonts", n))
        if NGWORDS in ncas:
            hactool(a.hactool, a.keys, ["--romfs=" + os.path.join(a.out, NGWORDS + ".romfs"), ncas[NGWORDS]])
    for rel in ("swkbd/lyt/Qwerty.szs", "fonts/nintendo_udsg-r_std_003.bfttf", "fonts/nintendo_ext_003.bfttf", NGWORDS + ".romfs"):
        print(("ok      " if os.path.isfile(os.path.join(a.out, rel)) else "MISSING ") + rel)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
