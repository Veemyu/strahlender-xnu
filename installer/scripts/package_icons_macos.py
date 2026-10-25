"""Regenerate or verify the vendored native Mac installer icons."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/recomp/app"))
from icon_composer import compile_icons  # noqa: E402


SOURCE = ROOT / "installer/assets/brand/icon.svg"
ASSETS = ROOT / "installer/assets/brand/macos"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(assets, source=SOURCE):
    metadata = json.loads((assets / "metadata.json").read_text())
    if metadata["source_sha256"] != digest(source):
        raise ValueError("Mac installer icons are stale; regenerate them from the approved SVG")
    for name in ("Installer.icns", "Assets.car"):
        if metadata["files"][name] != digest(assets / name):
            raise ValueError(f"Mac installer icon checksum mismatch: {name}")


def generate(artwork, output, scratch):
    if digest(artwork / "icon.svg") != digest(SOURCE):
        raise ValueError("Exported artwork is stale; rerun installer_icons first")
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
    # Keep the brand artwork flat; Apple owns the outer white surface and mask.
    white = {"solid": "srgb:1.000000,1.000000,1.000000,1.000000"}
    document = {
        # Prevent automatic dark backgrounds from obscuring the charcoal artwork.
        "fill-specializations": [{"value": white}, {"appearance": "dark", "value": white}],
        "groups": [{
            "name": "Installer artwork",
            "layers": [{"image-name": "artwork.png", "name": "Vee and installation mark",
                        "glass": False,
                        "position": {"scale": 1, "translation-in-points": [0, 0]}}],
            "specular": False,
            "blur-material": 0,
            "translucency": {"enabled": False, "value": 0},
            "shadow": {"kind": "none", "opacity": 0},
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
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(classic, output / "Installer.icns")
    shutil.copyfile(catalog, output / "Assets.car")
    metadata = {
        "source_sha256": digest(SOURCE),
        "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
        "minimum_catalog_target": "13.0",
        "classic_fallback_target": "12.0",
        "files": {name: digest(output / name) for name in ("Installer.icns", "Assets.car")},
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    verify(output)
    print("Native Mac icons regenerated and verified. Review the artwork before committing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork", type=Path)
    parser.add_argument("--output", type=Path, default=ASSETS)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            verify(args.output.resolve())
            print("Vendored Mac installer icons match the approved SVG and checksums.")
        else:
            if not args.artwork or not args.scratch:
                parser.error("Regeneration requires --artwork and a new --scratch directory")
            generate(args.artwork.resolve(), args.output.resolve(), args.scratch.resolve())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Installer icon preparation failed: {error}") from error


if __name__ == "__main__":
    main()
