"""Shared deterministic Icon Composer documents and native Apple rendering."""
import subprocess
import hashlib
import json
import plistlib
import shutil
from pathlib import Path

import game_icons
from icon_artwork import background, square, superellipse

STYLE = "liquid-glass-full-bleed-v1"


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
    return plistlib.loads(partial.read_bytes())


def document(data, specular=True):
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


def find_renderer():
    developer = Path(subprocess.check_output(["xcode-select", "-p"], text=True).strip())
    renderer = developer.parent / "Applications/Icon Composer.app/Contents/Executables/ictool"
    if not renderer.is_file():
        raise ValueError("Icon Composer's native ictool renderer was not found in the selected Xcode")
    return renderer


def render(renderer, bundle, output, appearance="Light", angle=0, platform="iOS"):
    subprocess.run([str(renderer), str(bundle), "--export-preview", platform, appearance,
                    "1024", "1024", "1", str(angle), str(output)],
                   check=True, capture_output=True, timeout=60)
    Image = game_icons.image_module()[0]
    with Image.open(output) as image:
        if image.format != "PNG" or image.size != (1024, 1024):
            raise ValueError("Unexpected native icon preview dimensions or format")
