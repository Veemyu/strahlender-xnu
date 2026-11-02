"""Shared deterministic Icon Composer documents, the classic fallback for Xcode before 26, and native Apple rendering."""
import subprocess
import sys
import tempfile
import hashlib
import json
import plistlib
import shutil
from pathlib import Path

import game_icons
import build_stages   # scripts/ is on sys.path once game_icons is imported

STYLE = "liquid-glass-full-bleed-v1"
CLASSIC_STYLE = "classic-v1"
# iconset members of the classic macOS icon: point size, scale
ICONSET = [(size, scale) for size in (16, 32, 128, 256, 512) for scale in (1, 2)]


def write_documents(manifest, images, directory):
    """Derive every document from validated original data, never staging previews."""
    images, directory = Path(images), game_icons.output_path(directory)
    documents = {}
    for variant in manifest["variants"]:
        data = (images / variant["image"]).read_bytes()
        definition = document(data)
        digest = hashlib.sha256(STYLE.encode() + data + json.dumps(definition, sort_keys=True).encode()).hexdigest()
        name = "BDSP_" + digest[:24]
        variant["icon"] = name
        bundle = directory / (name + ".icon")
        if name not in documents:
            (bundle / "Assets").mkdir(parents=True, exist_ok=True)
            foreground(data, layout="full-bleed").save(bundle / "Assets/artwork.png")
            game_icons.write_json(bundle / "icon.json", definition)
            documents[name] = bundle
    return documents


def compile_icons(documents, primary, output, platform):
    output = game_icons.output_path(output)
    # This is a dedicated compiler scratch directory, never the app bundle.
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    partial = output / "icon-info.plist"
    command = ["xcrun", "actool", "--compile", str(output), "--platform", platform,
               "--minimum-deployment-target", "17.0" if platform == "iphoneos" else "13.0",
               "--app-icon", primary, "--output-partial-info-plist", str(partial)]
    if platform == "iphoneos":
        command += ["--target-device", "ipad"]
        for name in documents:
            if name != primary:
                command += ["--alternate-app-icon", name]
    result = subprocess.run(command + [str(p) for p in documents.values()],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise ValueError("Native icon compilation failed: " + result.stdout[-2500:])
    # actool before Xcode 26 does not know Icon Composer (.icon) documents: it skips them, exits 0
    # and writes only an empty partial Info.plist, so the missing outputs are the only sign.
    expected = ["Assets.car"] + ([primary + ".icns"] if platform == "macosx" else [])
    missing = [name for name in expected if not (output / name).is_file()]
    if missing:
        raise ValueError("Native icon compilation produced no %s (actool %s). Icon Composer documents need "
                         "Xcode 26 or newer; with an older Xcode set BDSP_LEGACY_ICONS=1 for the classic icon."
                         % (", ".join(missing), build_stages.actool_version() or "of unknown version"))
    return plistlib.loads(partial.read_bytes())


def use_classic():
    """True when the classic fallback applies (Xcode before 26, unreadable actool, or BDSP_LEGACY_ICONS=1)."""
    style, detail = build_stages.icon_style()
    if style == "classic":
        print("Notice: classic app icon without Liquid Glass (%s). Xcode 26 or newer builds the Liquid Glass icon." % detail,
              file=sys.stderr)
    return style == "classic"


def classic_names(manifest):
    """Stable icon name per variant (identical artwork shares one); the extract stage normally supplies it."""
    for variant in manifest["variants"]:
        variant["icon"] = variant.get("icon") or "BDSP_" + variant["sha256"][:24]


def classic_icns(data, destination):
    """Classic ICNS through iconutil: the macOS tile (transparent margin, rounded corners) built by icon_artwork."""
    from icon_artwork import mac_artwork

    destination = game_icons.output_path(destination)
    Image = game_icons.image_module()[0]
    base = mac_artwork(data, "edge-to-edge")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iconset-", dir=destination.parent) as temporary:
        iconset = Path(temporary) / "BDSP.iconset"
        iconset.mkdir()
        for size, scale in ICONSET:
            pixels = size * scale
            image = base if pixels == base.width else base.resize((pixels, pixels), Image.Resampling.LANCZOS)
            image.save(iconset / ("icon_%dx%d%s.png" % (size, size, "@2x" if scale == 2 else "")))
        result = subprocess.run(["iconutil", "--convert", "icns", "--output", str(destination), str(iconset)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode or not destination.is_file():
        raise ValueError("iconutil produced no %s: %s" % (destination.name, result.stdout[-1000:]))


def document(data, specular=True):
    from icon_artwork import background, square

    color = background(square(data))
    return {
        "fill": {"solid": "srgb:" + ",".join(f"{c / 255:.6f}" for c in color) + ",1.000000"},
        "groups": [{
            "name": "Original artwork",
            "layers": [{"image-name": "artwork.png", "name": "Original language artwork",
                        "position": {"scale": 1, "translation-in-points": [0, 0]}}],
            "specular": specular,
            "blur-material": 0,
            "translucency": {"enabled": False, "value": 0},
            "shadow": {"kind": "neutral", "opacity": 0.15},
        }],
        "supported-platforms": {"squares": "shared"},
    }


def foreground(data, size=1024, layout="inset"):
    """Create an inset or full-bleed source, without baked lighting or shadows."""
    from icon_artwork import square, superellipse

    Image = game_icons.image_module()[0]
    if layout == "full-bleed":
        # The system supplies the outer mask; leave every source corner opaque.
        return square(data).resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    if layout != "inset":
        raise ValueError("Unknown artwork layout: " + layout)
    margin = round(size / 16)
    side = size - 2 * margin
    artwork = square(data).resize((side, side), Image.Resampling.LANCZOS).convert("RGBA")
    artwork.putalpha(superellipse(side))
    canvas = Image.new("RGBA", (size, size))
    canvas.alpha_composite(artwork, (margin, margin))
    return canvas
