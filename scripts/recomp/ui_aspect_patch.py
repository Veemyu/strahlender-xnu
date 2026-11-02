#!/usr/bin/env python3
"""Aspect-ratio patch for the game's UI bundles (build step, runs on the user's own extraction).

The UI is authored for a 1280x720 canvas. Screens, backgrounds and the key-guide bar are fixed 1280x720 rectangles in the middle of
the canvas, so on a taller or wider canvas they leave gaps. This turns every such rectangle into a full stretch of its parent, which
is identical on 16:9 and fills any other aspect ratio. Together with the canvas match mode chosen by the runtime (height matching
when wider, width matching when narrower than 16:9) nothing is cropped and nothing is stretched out of proportion.

Output is an overlay tree (same relative paths as the RomFS) that the runtime lays over the game's files. The input is never modified.
Usage: ui_aspect_patch.py --romfs <romfs dir> --out <overlay dir> [--only <bundle name>] [--dry-run]
"""
import argparse
import os
import re
import sys
from pathlib import Path

UI_ROOT = Path("Data/StreamingAssets/AssetAssistant/UIs")
EXTRA_FILE = Path("Data/resources.assets")
SCREEN = (1280.0, 720.0)
# Render-texture views keep their proportions: stretching them would distort 3D models.
KEEP_NAMES = ("rawimage", "modelview", "rawimagemodel")
# Only prefab roots, screen windows and backdrops are stretched. Other full-size containers (party lists, maps) hold the screen's content: they stay a
# centered 16:9 block, so top-anchored and centered parts of one layout never drift apart on a taller or wider canvas.
BACKDROP = re.compile(r"(^|_)(bg|back|backdrop|background|blur|flash|frash|fade|border)(_|\d|$)|^netbg$", re.IGNORECASE)


def import_unitypy():
    root = Path(__file__).resolve().parents[2]
    for candidate in (os.environ.get("BDSP_PYDEPS"), str(root / "tools/pydeps")):
        if candidate and os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
    import UnityPy  # noqa: E402
    return UnityPy


# Objects whose parent is not a plain full-screen rectangle but which must still fill the canvas (menu blur backdrop in resources.assets).
FORCE_STRETCH = ("BlurBg", "BlurBg/Canvas", "BlurBg/Canvas/Bg")


def near(a, b, eps=0.51):
    return abs(a - b) <= eps


def covers_parent(t):
    """True if the transform exactly fills a 1280x720 parent (collapsed anchors, size 1280x720)."""
    amin, amax = t["m_AnchorMin"], t["m_AnchorMax"]
    if not (near(amin["x"], amax["x"], 1e-4) and near(amin["y"], amax["y"], 1e-4)):
        return False
    size, pos, pivot = t["m_SizeDelta"], t["m_AnchoredPosition"], t["m_Pivot"]
    if not (near(size["x"], SCREEN[0]) and near(size["y"], SCREEN[1])):
        return False
    left = amin["x"] * SCREEN[0] + pos["x"] - pivot["x"] * size["x"]
    bottom = amin["y"] * SCREEN[1] + pos["y"] - pivot["y"] * size["y"]
    return near(left, 0.0) and near(bottom, 0.0)


def is_stretch(t):
    amin, amax = t["m_AnchorMin"], t["m_AnchorMax"]
    return near(amin["x"], 0, 1e-4) and near(amin["y"], 0, 1e-4) and near(amax["x"], 1, 1e-4) and near(amax["y"], 1, 1e-4) \
        and near(t["m_SizeDelta"]["x"], 0) and near(t["m_SizeDelta"]["y"], 0) and near(t["m_AnchoredPosition"]["x"], 0) and near(t["m_AnchoredPosition"]["y"], 0)


def make_stretch(t):
    t["m_AnchorMin"] = {"x": 0.0, "y": 0.0}
    t["m_AnchorMax"] = {"x": 1.0, "y": 1.0}
    t["m_AnchoredPosition"] = {"x": 0.0, "y": 0.0}
    t["m_SizeDelta"] = {"x": 0.0, "y": 0.0}
    t["m_Pivot"] = {"x": 0.5, "y": 0.5}


def patch_bundle(UnityPy, source, destination, dry_run):
    env = UnityPy.load(str(source))
    names, trees, readers = {}, {}, {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            names[obj.path_id] = obj.read().m_Name
        elif obj.type.name == "RectTransform":
            trees[obj.path_id] = obj.read_typetree()
            readers[obj.path_id] = obj
    gameobject_of = {pid: t["m_GameObject"]["m_PathID"] for pid, t in trees.items()}
    parent_of = {pid: t["m_Father"]["m_PathID"] for pid, t in trees.items()}
    children = {}
    for pid, father in parent_of.items():
        children.setdefault(father, []).append(pid)
    changed = []

    def visit(pid, parent_is_screen, is_root=False):
        t = trees[pid]
        name = names.get(gameobject_of[pid], "")
        keep = any(k in name.lower() for k in KEEP_NAMES)
        eligible = is_root or name == "Window" or bool(BACKDROP.search(name))
        screen = False
        if parent_is_screen and not keep and eligible and covers_parent(t):
            make_stretch(t)
            changed.append(pid)
            screen = True
        elif parent_is_screen and (is_stretch(t) or is_root):   # the code places a prefab root over the whole canvas
            screen = True
        for child in children.get(pid, []):
            visit(child, screen)

    def path_of(pid):
        parts = []
        while pid in trees:
            parts.append(names.get(gameobject_of[pid], ""))
            pid = parent_of[pid]
        return "/".join(reversed(parts))

    for pid in trees:
        if any(path_of(pid).endswith(f) for f in FORCE_STRETCH) and not is_stretch(trees[pid]):
            make_stretch(trees[pid])
            changed.append(pid)
    forced = set(changed)
    for pid, father in parent_of.items():
        if father == 0 or father not in trees:
            visit(pid, True, True)
    changed[:] = list(dict.fromkeys(changed))
    if not changed:
        return 0
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.name.endswith(".assets"):
            # A plain serialized file (resources.assets): rewriting it with UnityPy changes its layout and the game crashes on it. Only
            # floats change here, so every rectangle is overwritten in place at its original offset and length.
            data = bytearray(source.read_bytes())
            for pid in changed:
                obj = readers[pid]
                start, size = obj.byte_start, obj.byte_size
                new = obj.save_typetree(trees[pid])
                if len(new) != size:
                    raise ValueError("rectangle changed size")
                data[start:start + size] = new
            destination.write_bytes(bytes(data))
        else:
            for pid in changed:
                readers[pid].save_typetree(trees[pid])
            destination.write_bytes(env.file.save(packer="original"))
    return len(changed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--romfs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    UnityPy = import_unitypy()
    romfs, out = Path(args.romfs), Path(args.out)
    total_files = total_changes = 0
    sources = [romfs / EXTRA_FILE] if (romfs / EXTRA_FILE).is_file() and not args.only else []   # UIManager's own objects (blur background)
    for directory, _, files in os.walk(romfs / UI_ROOT):
        for name in sorted(files):
            if "." not in name and not (args.only and name != args.only):
                sources.append(Path(directory) / name)
    for source in sources:
        relative = source.relative_to(romfs)
        try:
            count = patch_bundle(UnityPy, source, out / relative, args.dry_run)
        except Exception as error:  # a bundle that is not an asset bundle
            print(f"skip {relative}: {error}", file=sys.stderr)
            continue
        if count:
            total_files += 1
            total_changes += count
            print(f"{relative}: {count} rectangles")
    print(f"{total_changes} rectangles in {total_files} bundles")


if __name__ == "__main__":
    main()
