"""Deterministic Apple icon composition from the user's original square artwork."""
import io
import math
from statistics import median
from PIL import Image, ImageDraw, ImageFilter

MAC_STYLES = ("framed-dark", "edge-to-edge", "framed-light")


def square(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB")


def background(image):
    size = image.width
    samples = [image.getpixel((x, y)) for x in (0, size // 32, size - 1 - size // 32, size - 1)
               for y in (0, size // 32, size - 1 - size // 32, size - 1)]
    return tuple(max(8, min(64, round(median(pixel[channel] for pixel in samples) * .6))) for channel in range(3))


def ipad_artwork(data, size=1024):
    """Opaque square with rounded inset artwork; iPadOS applies the outer mask."""
    original = square(data)
    canvas = Image.new("RGB", (size, size), background(original))
    margin = round(size / 16)
    content = original.resize((size - 2 * margin, size - 2 * margin), Image.Resampling.LANCZOS)
    canvas.paste(content, (margin, margin), superellipse(content.width))
    return canvas


def superellipse(size, exponent=5):
    # Own analytic approximation of a continuous rounded square; no downloaded mask or artwork.
    scale = 3
    edge = size * scale
    center = (edge - 1) / 2
    mask = Image.new("L", (edge, edge), 0)
    points = []
    for step in range(2048):
        angle = 2 * math.pi * step / 2048
        cosine, sine = math.cos(angle), math.sin(angle)
        points.append((center + center * math.copysign(abs(cosine) ** (2 / exponent), cosine),
                       center + center * math.copysign(abs(sine) ** (2 / exponent), sine)))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def mac_artwork(data, style="framed-dark", size=1024):
    """Legacy ICNS/Dock rendering: transparent outer margin, continuous tile and optional inner frame."""
    if style not in MAC_STYLES:
        raise ValueError("Unknown deterministic icon style")
    original = square(data)
    outer = round(size * 100 / 1024)
    side = size - 2 * outer
    mask = superellipse(side)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("L", (size, size), 0)
    shadow.paste(mask, (outer, outer + round(size * .009)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * .012)).point(lambda alpha: round(alpha * .20))
    canvas.putalpha(shadow)
    base = (225, 231, 239) if style == "framed-light" else background(original)
    tile = Image.new("RGBA", (side, side), base + (255,))
    inset = 0 if style == "edge-to-edge" else round(side * .065)
    artwork = original.resize((side - 2 * inset, side - 2 * inset), Image.Resampling.LANCZOS)
    if inset:
        # Concentric inner tile, softly feathered rather than a square photo or a hard stroke.
        inner_mask = superellipse(artwork.width).filter(ImageFilter.GaussianBlur(size * .0012))
        inner_shadow = Image.new("L", (side, side), 0)
        inner_shadow.paste(inner_mask, (inset, inset + max(1, round(size * .002))))
        inner_shadow = inner_shadow.filter(ImageFilter.GaussianBlur(size * .004)).point(lambda alpha: round(alpha * .22))
        shade = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        shade.putalpha(inner_shadow)
        tile = Image.alpha_composite(tile, shade)
        artwork = artwork.convert("RGBA")
        artwork.putalpha(inner_mask)
        tile.alpha_composite(artwork, (inset, inset))
    else:
        tile.paste(artwork, (inset, inset))
    tile.putalpha(mask)
    canvas.alpha_composite(tile, (outer, outer))
    return canvas


def preview(data, output):
    """Side-by-side review sheet; the caller enforces the work/ output boundary."""
    width, height = 360, 420
    sheet = Image.new("RGB", (width * 3, height), (45, 48, 54))
    draw = ImageDraw.Draw(sheet)
    labels = ("A: Dark frame", "B: Edge to edge", "C: Light frame")
    for index, (style, label) in enumerate(zip(MAC_STYLES, labels)):
        icon = mac_artwork(data, style, 320)
        sheet.paste(icon, (width * index + 20, 30), icon)
        draw.text((width * index + 24, 375), label, fill="white")
    sheet.save(output)
