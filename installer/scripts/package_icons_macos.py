"""Compile the installer artwork with the game's native Icon Composer pipeline."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/recomp/app"))
from icon_composer import compile_icons  # noqa: E402


def package(artwork, app, scratch):
    resources = app / "Contents/Resources"
    info_path = app / "Contents/Info.plist"
    if not resources.is_dir() or not info_path.is_file():
        raise ValueError("Expected an existing installer .app bundle")
    # Scratch is a new dedicated directory, never a game or application directory.
    scratch.mkdir(parents=True, exist_ok=False)
    iconset = scratch / "Installer.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        shutil.copyfile(artwork / f"{size}.png", iconset / f"icon_{size}x{size}.png")
        shutil.copyfile(artwork / f"{size * 2}.png", iconset / f"icon_{size}x{size}@2x.png")
    classic = scratch / "Installer.icns"
    subprocess.run(["xcrun", "iconutil", "--convert", "icns", "--output", str(classic), str(iconset)], check=True)

    bundle = scratch / "Installer.icon"
    (bundle / "Assets").mkdir(parents=True)
    shutil.copyfile(artwork / "foreground.png", bundle / "Assets/artwork.png")
    # Match the BDSP material settings, with our white surface kept separate.
    white = {"solid": "srgb:1.000000,1.000000,1.000000,1.000000"}
    document = {
        # Prevent automatic dark backgrounds from obscuring the charcoal artwork.
        "fill-specializations": [{"value": white}, {"appearance": "dark", "value": white}],
        "groups": [{
            "name": "Installer artwork",
            "layers": [{"image-name": "artwork.png", "name": "Vee and installation mark",
                        "position": {"scale": 1, "translation-in-points": [0, 0]}}],
            "specular": True,
            "blur-material": 0,
            "translucency": {"enabled": False, "value": 0},
            "shadow": {"kind": "neutral", "opacity": 0.15},
        }],
        "supported-platforms": {"squares": "shared"},
    }
    (bundle / "icon.json").write_text(json.dumps(document, indent=2) + "\n")
    compiled = scratch / "compiled"
    partial = compile_icons({"Installer": bundle}, "Installer", compiled, "macosx")
    catalog = compiled / "Assets.car"
    if not catalog.is_file() or not (compiled / "Installer.icns").is_file():
        raise ValueError("Native icon compiler did not produce the installer icon and asset catalog")
    if partial.get("CFBundleIconName") != "Installer":
        raise ValueError("Native icon compiler returned unexpected icon metadata")
    shutil.copyfile(classic, resources / "Installer.icns")
    shutil.copyfile(catalog, resources / "Assets.car")
    shutil.copyfile(artwork / "icon.svg", resources / "installer-icon.svg")
    info = plistlib.loads(info_path.read_bytes())
    # Never copy a compiler-generated deployment target over macOS 12 support.
    info.update({key: value for key, value in partial.items()
                 if key in ("CFBundleIconName", "CFBundleIcons", "CFBundleIcons~ipad")})
    info["CFBundleIconFile"] = "Installer"
    info_path.write_bytes(plistlib.dumps(info))
    print("Installer icons: native Glass asset catalog and classic macOS fallback ready.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        package(args.artwork.resolve(), args.app.resolve(), args.scratch.resolve())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Installer icon packaging failed: {error}") from error


if __name__ == "__main__":
    main()
