"""Stage editable Liquid Glass icons and native previews; never rebuild an app.

Requires the user's extracted icon source, Pillow, and Xcode's Icon Composer.
The .icon schema and ictool interface are version-dependent; validate on the
installed Apple renderer rather than treating these fields as a stable SDK API.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import game_icons
from icon_artwork import ipad_artwork, superellipse


from icon_composer import document, foreground, find_renderer, render


def contact_sheet(rows, output):
    from PIL import Image, ImageDraw
    cell, header, thumb = 290, 44, 256
    sheet = Image.new("RGB", (cell * 4, header + len(rows) * (cell + 32)), (42, 45, 52))
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(("Accepted flat icon", "Glass: light angle 0", "Glass: light angle 120", "Glass: dark")):
        draw.text((index * cell + 12, 16), label, fill="white")
    for row, (locale, paths) in enumerate(rows):
        y = header + row * (cell + 32)
        draw.text((12, y + cell), locale, fill="white")
        for col, path in enumerate(paths):
            with Image.open(path) as source:
                icon = source.convert("RGBA").resize((thumb, thumb), Image.Resampling.LANCZOS)
                # Presentation-only outer mask; never written into the .icon source layers.
                from PIL import ImageChops
                icon.putalpha(ImageChops.multiply(icon.getchannel("A"), superellipse(thumb)))
                sheet.paste(icon, (col * cell + 17, y), icon)
    sheet.save(output)


def stage(source, output, locales=None, renderer=None, layout="inset"):
    if layout not in ("inset", "full-bleed"):
        raise ValueError("Unknown artwork layout: " + layout)
    source = Path(source)
    manifest = game_icons.load_source(source)
    if not manifest["variants"]:
        raise ValueError("Staging requires valid original artwork; no placeholder is generated")
    output = game_icons.output_path(output)
    if output.exists():
        raise ValueError("Staging directory already exists; select a new output to preserve prior reviews")
    wanted = set(locales or (v["id"] for v in manifest["variants"]))
    variants = [v for v in manifest["variants"] if v["id"] in wanted]
    missing = wanted - {v["id"] for v in variants}
    if missing:
        raise ValueError("Unavailable icon languages: " + ", ".join(sorted(missing)))
    renderer = Path(renderer) if renderer else find_renderer()
    if not renderer.is_file():
        raise ValueError("Native renderer is missing")
    version = subprocess.check_output([str(renderer), "--version"], text=True).strip()
    output.mkdir(parents=True)
    rows, entries = [], []
    for variant in variants:
        data = (source / variant["image"]).read_bytes()
        bundle = output / (variant["id"] + ".icon")
        (bundle / "Assets").mkdir(parents=True)
        foreground(data, layout=layout).save(bundle / "Assets/artwork.png")
        game_icons.write_json(bundle / "icon.json", document(data))
        preview_dir = output / variant["id"]
        preview_dir.mkdir()
        flat = preview_dir / "accepted-flat.png"
        ipad_artwork(data).save(flat)
        paths = [flat]
        for name, appearance, angle in (("glass-light-000", "Light", 0),
                                        ("glass-light-120", "Light", 120),
                                        ("glass-dark-000", "Dark", 0)):
            target = preview_dir / (name + ".png")
            render(renderer, bundle, target, appearance, angle)
            paths.append(target)
        rows.append((variant["id"], paths))
        contact_sheet([(variant["id"], paths)], preview_dir / "review.png")
        entries.append({"id": variant["id"], "source_sha256": hashlib.sha256(data).hexdigest(),
                        "document": bundle.name, "previews": [str(p.relative_to(output)) for p in paths]})
        print("Staged native previews: " + variant["id"], flush=True)
    contact_sheet(rows, output / "review.png")
    game_icons.write_json(output / "staging.json", {"schema": 1, "renderer_version": version, "layout": layout,
                          "status": "review-only; not integrated into any app build", "variants": entries})
    (output / "README.md").write_text(
        "# Liquid Glass icon staging\n\n"
        "Start with review.png. Each language has an editable .icon package and\n"
        "1024px previews rendered by Apple's local Icon Composer tool.\n"
        "The first column is the accepted flat iPad icon for comparison.\n"
        "Glass previews use light angles 0 and 120 degrees, plus dark appearance.\n"
        "Only the comparison sheet adds a presentation mask; source documents\n"
        "leave the outer mask to Apple. Lighting is not painted into artwork.\n"
        "Layout: " + layout + ". Sources are resampled to 1024px with Lanczos,\n"
        "then positioned at 100% scale and X=0, Y=0 in Icon Composer.\n"
        "Full-bleed has no source margin or corner mask; Apple supplies the outer shape.\n"
        "Inset preserves the earlier rounded inner tile for comparison.\n"
        "The original image remains one foreground layer; no invented\n"
        "separation of the logo or character. Movement on the device requires\n"
        "a later compiled app test. These PNGs are static native previews.\n\n"
        "Review checkpoint only: no app rebuild, signing, installation, or\n"
        "change to existing icon selection. Generated data must not enter Git.\n",
        encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="work/recomp/icons/source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--locales", help="Comma-separated IDs; default: all available variants")
    parser.add_argument("--layout", choices=("inset", "full-bleed"), default="inset")
    args = parser.parse_args()
    try:
        result = stage(args.source, args.output, args.locales.split(",") if args.locales else None,
                       layout=args.layout)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit("Icon staging failed: " + str(error)) from error
    print("Review directory: " + str(result))


if __name__ == "__main__":
    main()
