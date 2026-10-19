#!/usr/bin/env python3
"""Bildvergleich und heuristische Fehlerbilder für die automatische Sichtprüfung (docs/visuelle-pruefung.md).

Aufrufe:
  scripts/visual_compare.py compare --run work/visual/auto/<lauf> [--baseline work/visual/auto/baseline]
        [--scenarios scripts/visual/scenarios.json] [--out DIR] [--strict] [--no-sheets]
        Vergleicht jedes Bild des Laufs mit der Baseline und prüft jedes Bild auf Fehlermuster; schreibt report.json,
        report.md und Kontaktbögen (contact/*.png) in den Laufordner. Exit-Code 0 = in Ordnung, 1 = Regression, 2 = Fehler.
  scripts/visual_compare.py analyze BILD... [--kind field|ui|room] [--json]
        Nur der Anomalie-Detektor (ohne Referenz), Kennzahlen und Flags je Bild.
  scripts/visual_compare.py accept --run LAUF [--baseline DIR]
        Übernimmt einen Lauf als neue Baseline (Bilder + Kennzahlen); die alte Baseline wandert nach <baseline>.alt.
  scripts/visual_compare.py ref import|compare|cache ...
        Referenzmodus gegen Ryujinx-Bilder (F8): Unity-Bild gegen Referenz, Histogramm-Angleichung, Raster-Heatmap (scripts/visual_ref.py).

Ordnerform eines Laufs: <lauf>/shots/<name>.png (oder PNGs direkt im Laufordner), optional <lauf>/capture.json (Aufnahme-Kennzahlen).
Nur Python-Standardbibliothek, numpy und Pillow (system-site-packages oder tools/pydeps); kein Netz, keine Neuinstallation.
Alle Heuristiken sind auf die bekannten Fehler des Nutzer-Screenshots und die guten Bilder (z422_h12_final.png) kalibriert; die Werte
stehen in THRESHOLDS und DETECTOR_PARAMS und lassen sich je Szenario in scenarios.json überschreiben.
"""
import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # Pillow liegt zusätzlich unter tools/pydeps
    sys.path.append(str(ROOT / "tools" / "pydeps"))
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover
        print("numpy und Pillow fehlen: " + str(exc), file=sys.stderr)
        sys.exit(2)

# ---------------------------------------------------------------------------------------------------------------------
# Schwellen
# ---------------------------------------------------------------------------------------------------------------------

# Regression gegen die Baseline (je Bild, je Szenario überschreibbar über "thresholds").
THRESHOLDS = {
    "ssim_min": 0.80,            # darunter: Bild hat sich stark verändert
    "mad_max": 12.0,             # mittlere absolute Abweichung (0..255 je Kanal)
    "changed_max": 0.25,         # Anteil Pixel mit Kanalabweichung > changed_pixel_delta
    "changed_pixel_delta": 16,
    "laplace_ratio_min": 0.50,   # Texturdetail darf nicht auf unter die Hälfte fallen
    "mean_shift_max": 25.0,      # größte Änderung eines Kanal-Mittelwerts
    "streak_delta_max": 0.03,    # Zunahme des Anteils gerichteter schräger Kacheln gegenüber der Baseline (Verschmierung/Streckung)
    "flat_delta_max": 0.08,      # Zunahme der größten flachen Region (Textur verloren)
}

# Parameter der Anomalie-Detektoren (kalibriert, siehe docs/visuelle-pruefung.md).
DETECTOR_PARAMS = {
    "bar_black_max": 10,         # Kanalmaximum, bis zu dem ein Pixel für Balken als schwarz gilt
    "bar_column_fraction": 0.93, # Anteil schwarzer Pixel einer Spalte/Zeile, damit sie zum Balken zählt
    "bar_min_fraction": 0.015,   # Balkenbreite relativ zur Bildbreite/-höhe, ab der "balken" gemeldet wird
    "empty_std": 1.5,
    "empty_colors": 4,
    "mean_min": 10.0,
    "mean_max": 245.0,
    "magenta_fraction": 0.002,
    "cyan_fraction": 0.002,
    "white_min_channel": 250,
    "white_min_area_fraction": 0.005,    # Mindestgröße eines zusammenhängenden weißen Stücks (Emblem-Streifen <0,4 %, Fehlerquads >2 %)
    "white_min_area_px": 3000,
    "white_min_rect": 0.40,              # Rechteckigkeit (Fläche / Hüllrechteck): Quads 0,67–0,71, Emblem 0,22
    "white_flag_fraction": 0.005,        # Summe solcher Stücke relativ zur Inhaltsfläche
    "black_max_channel": 8,
    "black_min_area_fraction": 0.004,
    "black_flag_fraction": 0.04,
    "black_hint_fraction": 0.012,
    "flat_block": 8,
    "flat_range": 3,                     # Kanalspanne im 8x8-Block, bis zu der der Block als einfarbig gilt
    "flat_flag_fraction": 0.10,          # größte zusammenhängende flache Region relativ zur Inhaltsfläche
    "tile": 16,
    "tile_energy": 12.0,                 # Mindest-Gradientenstärke je Pixel, damit eine Kachel als "texturiert" zählt
    "coherence_min": 0.93,
    "diag_min_deg": 22.0,
    "diag_flag_fraction": 0.15,          # gerichtete schräge Kacheln relativ zur Inhaltsfläche (z54-Fischgrät legitim: 0,08; Referenzvergleich fängt Verschmierung besser)
    "hud_region": (0.0, 0.0, 0.30, 0.12),
    "hud_min_components": 20,
    "hud_min_channel": 200,
    "hud_min_fraction": 0.03,
}

FLAG_TEXT = {
    "leer_konstant": ("fehler", "Bild leer oder (nahezu) konstant"),
    "mittel_ausserhalb": ("fehler", "Bildmittel außerhalb des erlaubten Bereichs"),
    "magenta": ("fehler", "Magenta-Flächen (fehlendes Material/Shader)"),
    "cyan": ("fehler", "Cyan-Flächen (Aufnahme vor dem ersten Bild oder Fehlmaterial)"),
    "weisse_flaeche": ("fehler", "reinweiße zusammenhängende Flächenstücke (Rechtecke ohne Textur)"),
    "schwarze_flaeche": ("fehler", "große schwarze Flächen im Inhalt"),
    "flach_gross": ("fehler", "große einfarbig-flache Region (Wasser/Boden ohne Textur)"),
    "gestreckt": ("fehler", "gerichtete, gestreckte oder verschmierte Strukturen (Kacheln mit Gradientenkohärenz)"),
    "balken": ("fehler", "schwarze Seitenbalken (Bild füllt das Fenster nicht)"),
    "hud_text": ("hinweis", "dichte Text-/Debug-Überlagerung in der Bildecke"),
}

KIND_DETECTORS = {
    "field": ["balken", "leer", "mittel", "farben", "weiss", "schwarz", "flach", "streckung", "hud"],
    "room": ["balken", "leer", "mittel", "farben", "weiss", "schwarz", "streckung", "hud"],  # Raum: einfarbiger Hintergrund erlaubt
    "ui": ["leer", "mittel", "farben"],
}


# ---------------------------------------------------------------------------------------------------------------------
# Bild laden und Grundgrößen
# ---------------------------------------------------------------------------------------------------------------------

def load_rgb(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8).copy()


def luma(rgb):
    f = rgb.astype(np.float32)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def box_mean(x, k):
    c = np.cumsum(np.cumsum(x.astype(np.float64), axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / float(k * k)


def ssim_map(a, b, k=8):
    """SSIM-Karte (Form (H-k+1, W-k+1)) auf der Luminanz; None, wenn das Bild kleiner als das Fenster ist."""
    x, y = luma(a).astype(np.float64), luma(b).astype(np.float64)
    if x.shape[0] < k or x.shape[1] < k:
        return None
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = box_mean(x, k), box_mean(y, k)
    vx = box_mean(x * x, k) - mx * mx
    vy = box_mean(y * y, k) - my * my
    cxy = box_mean(x * y, k) - mx * my
    return ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))


def ssim(a, b, k=8):
    """Strukturähnlichkeit (SSIM, Mittel über gleichförmige k×k-Fenster) auf der Luminanz; eigene Implementierung."""
    s = ssim_map(a, b, k)
    if s is None:
        return 1.0 if np.array_equal(a, b) else 0.0
    return float(s.mean())


def laplace_variance(rgb):
    """Varianz des Laplace-Operators auf der Luminanz: Maß für Kantenschärfe/Texturdetail."""
    y = luma(rgb)
    if y.shape[0] < 3 or y.shape[1] < 3:
        return 0.0
    lap = 4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:]
    return float(lap.var())


def histograms(rgb):
    y = luma(rgb)
    hl, _ = np.histogram(y, bins=16, range=(0, 256))
    n = float(y.size)
    out = {"luma16": [round(float(v) / n, 5) for v in hl]}
    for i, c in enumerate("rgb"):
        h, _ = np.histogram(rgb[..., i], bins=8, range=(0, 256))
        out[c + "8"] = [round(float(v) / n, 5) for v in h]
    return out


def hist_distance(a, b):
    ha, _ = np.histogram(luma(a), bins=32, range=(0, 256))
    hb, _ = np.histogram(luma(b), bins=32, range=(0, 256))
    return float(0.5 * np.abs(ha / ha.sum() - hb / hb.sum()).sum())


def image_metrics(rgb):
    h, w = rgb.shape[:2]
    y = luma(rgb)
    mean = rgb.reshape(-1, 3).mean(axis=0)
    q = (rgb >> 3).astype(np.uint32)
    colors = int(np.unique((q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]).size)
    hist = np.bincount(y.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    p = hist[hist > 0] / hist.sum()
    return {
        "width": int(w), "height": int(h),
        "mean_rgb": [round(float(v), 2) for v in mean],
        "luma_mean": round(float(y.mean()), 2),
        "luma_std": round(float(y.std()), 2),
        "colors_5bit": colors,
        "laplace_var": round(laplace_variance(rgb), 2),
        "entropy": round(float(-(p * np.log2(p)).sum()), 3),
        "hist": histograms(rgb),
    }


# ---------------------------------------------------------------------------------------------------------------------
# Zusammenhängende Komponenten (ohne scipy): Laufweiten + Union-Find, 4er-Nachbarschaft
# ---------------------------------------------------------------------------------------------------------------------

def components(mask, min_area=1):
    """Liefert Liste von Komponenten {area, bbox=(x0,y0,x1,y1) (x1,y1 exklusiv), rect=Füllgrad} der True-Pixel, nach Fläche absteigend."""
    h, w = mask.shape
    if h == 0 or w == 0 or not mask.any():
        return []
    m = np.zeros((h, w + 2), dtype=np.int8)
    m[:, 1:-1] = mask
    d = np.diff(m, axis=1)
    parent = []
    run_y, run_s, run_e = [], [], []
    prev = []
    for y in range(h):
        s = np.flatnonzero(d[y] == 1)
        e = np.flatnonzero(d[y] == -1)
        cur = []
        for a, b in zip(s.tolist(), e.tolist()):
            rid = len(parent)
            parent.append(rid)
            run_y.append(y); run_s.append(a); run_e.append(b)
            cur.append((a, b, rid))
        i = j = 0
        while i < len(prev) and j < len(cur):
            pa, pb, pid = prev[i]
            ca, cb, cid = cur[j]
            if pa < cb and ca < pb:
                ra, rb = pid, cid
                while parent[ra] != ra:
                    parent[ra] = parent[parent[ra]]; ra = parent[ra]
                while parent[rb] != rb:
                    parent[rb] = parent[parent[rb]]; rb = parent[rb]
                if ra != rb:
                    parent[rb] = ra
            if pb < cb:
                i += 1
            else:
                j += 1
        prev = cur
    n = len(parent)
    root = np.empty(n, dtype=np.int64)
    for i in range(n):
        r = i
        while parent[r] != r:
            parent[r] = parent[parent[r]]; r = parent[r]
        root[i] = r
    ys, ss, es = np.array(run_y), np.array(run_s), np.array(run_e)
    ln = es - ss
    area = np.bincount(root, weights=ln, minlength=n)
    x0 = np.full(n, 1 << 30); x1 = np.zeros(n, dtype=np.int64)
    y0 = np.full(n, 1 << 30); y1 = np.zeros(n, dtype=np.int64)
    np.minimum.at(x0, root, ss); np.maximum.at(x1, root, es)
    np.minimum.at(y0, root, ys); np.maximum.at(y1, root, ys + 1)
    out = []
    for r in np.flatnonzero(area >= min_area):
        bw, bh = int(x1[r] - x0[r]), int(y1[r] - y0[r])
        a = int(area[r])
        out.append({"area": a, "bbox": (int(x0[r]), int(y0[r]), int(x1[r]), int(y1[r])), "rect": round(a / float(max(1, bw * bh)), 3)})
    out.sort(key=lambda c: -c["area"])
    return out


def _shift_box(box, dx, dy):
    return [int(box[0] + dx), int(box[1] + dy), int(box[2] + dx), int(box[3] + dy)]


# ---------------------------------------------------------------------------------------------------------------------
# Anomalie-Detektor (ohne Referenz)
# ---------------------------------------------------------------------------------------------------------------------

def find_bars(rgb, p):
    """Schwarze Balken am Rand: (links, oben, rechts, unten) in Pixeln."""
    h, w = rgb.shape[:2]
    dark = rgb.max(axis=2) <= p["bar_black_max"]
    cols = dark.mean(axis=0) >= p["bar_column_fraction"]
    rows = dark.mean(axis=1) >= p["bar_column_fraction"]

    def lead(v):
        n = 0
        while n < len(v) and v[n]:
            n += 1
        return n
    left, right = lead(cols), lead(cols[::-1])
    top, bottom = lead(rows), lead(rows[::-1])
    if left + right >= w or top + bottom >= h:
        return 0, 0, 0, 0
    return left, top, right, bottom


def gradient_field(y):
    """Sobel-Gradienten (gx, gy) auf der Luminanz, Ränder 0."""
    gx = np.zeros_like(y); gy = np.zeros_like(y)
    gx[1:-1, 1:-1] = (y[:-2, 2:] + 2 * y[1:-1, 2:] + y[2:, 2:] - y[:-2, :-2] - 2 * y[1:-1, :-2] - y[2:, :-2]) / 8.0
    gy[1:-1, 1:-1] = (y[2:, :-2] + 2 * y[2:, 1:-1] + y[2:, 2:] - y[:-2, :-2] - 2 * y[:-2, 1:-1] - y[:-2, 2:]) / 8.0
    return gx, gy


def detect_streaks(c, p):
    """Gerichtete Strukturen: Strukturtensor je Kachel. Liefert Kennzahlen, Kachel-Boxen schräger kohärenter Kachel."""
    y = luma(c)
    gx, gy = gradient_field(y)
    t = p["tile"]
    th, tw = (y.shape[0] // t) * t, (y.shape[1] // t) * t
    if th == 0 or tw == 0:
        return {"textured": 0, "coherent": 0, "diag": 0, "tiles": 0}, []

    def tile_sum(v):
        return v[:th, :tw].reshape(th // t, t, tw // t, t).sum(axis=(1, 3))
    jxx, jyy, jxy = tile_sum(gx * gx), tile_sum(gy * gy), tile_sum(gx * gy)
    energy = (jxx + jyy) / float(t * t)
    textured = energy >= p["tile_energy"]
    den = np.maximum(jxx + jyy, 1e-6)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / den
    ang = np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) % 180.0
    off_axis = np.minimum.reduce([ang, np.abs(ang - 90.0), 180.0 - ang])
    coherent = textured & (coh >= p["coherence_min"])
    diag = coherent & (off_axis >= p["diag_min_deg"])
    boxes = [[int(i % diag.shape[1] * t), int(i // diag.shape[1] * t), int(i % diag.shape[1] * t + t), int(i // diag.shape[1] * t + t)]
             for i in np.flatnonzero(diag.ravel())]
    return ({"textured": int(textured.sum()), "coherent": int(coherent.sum()), "diag": int(diag.sum()), "tiles": int(diag.size)}, boxes)


def detect_hud(img, p):
    """Viele kleine weiße Komponenten (Textglyphen) in der Bildecke des ganzen Bildes (auch über Balken): Debug-Überlagerung."""
    h, w = img.shape[:2]
    rx0, ry0, rx1, ry1 = p["hud_region"]
    x0, y0, x1, y1 = int(rx0 * w), int(ry0 * h), max(1, int(rx1 * w)), max(1, int(ry1 * h))
    sub = img[y0:y1, x0:x1]
    mask = sub.min(axis=2) >= p["hud_min_channel"]
    comps = [k for k in components(mask, min_area=3) if k["area"] <= 1500]
    frac = float(mask.mean())
    return {"glyphs": len(comps) if frac >= p["hud_min_fraction"] else 0, "fraction": round(frac, 4), "box": [x0, y0, x1, y1]}


def anomalies(rgb, kind="field", overrides=None, allow=()):
    """Prüft ein Bild ohne Referenz. Rückgabe: {"flags": [...], "stats": {...}}; jedes Flag hat flag, severity, value, threshold, text, boxes."""
    p = dict(DETECTOR_PARAMS)
    if overrides:
        p.update(overrides)
    active = KIND_DETECTORS.get(kind, KIND_DETECTORS["field"])
    h, w = rgb.shape[:2]
    flags, stats = [], {}

    def add(name, value, threshold, boxes=None, severity=None):
        sev, text = FLAG_TEXT[name]
        flags.append({"flag": name, "severity": severity or sev, "value": round(float(value), 4), "threshold": threshold, "text": text,
                      "boxes": boxes or [], "allowed": name in allow})

    left, top, right, bottom = find_bars(rgb, p)
    cw, ch = w - left - right, h - top - bottom
    c = rgb[top:h - bottom, left:w - right] if (left or top or right or bottom) else rgb
    area = float(max(1, c.shape[0] * c.shape[1]))
    stats["content_box"] = [left, top, w - right, h - bottom]
    bar_fraction = 1.0 - area / float(w * h)
    stats["bar_fraction"] = round(bar_fraction, 4)
    if "balken" in active and (left / w >= p["bar_min_fraction"] or right / w >= p["bar_min_fraction"] or
                               top / h >= p["bar_min_fraction"] or bottom / h >= p["bar_min_fraction"]):
        boxes = []
        if left: boxes.append([0, 0, left, h])
        if right: boxes.append([w - right, 0, w, h])
        if top: boxes.append([0, 0, w, top])
        if bottom: boxes.append([0, h - bottom, w, h])
        add("balken", bar_fraction, p["bar_min_fraction"], boxes)

    y = luma(c)
    stats["luma_mean"] = round(float(y.mean()), 2)
    stats["luma_std"] = round(float(y.std()), 2)
    q = (c >> 3).astype(np.uint32)
    stats["colors_5bit"] = int(np.unique((q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]).size)
    if "leer" in active and (stats["luma_std"] < p["empty_std"] or stats["colors_5bit"] <= p["empty_colors"]):
        add("leer_konstant", stats["luma_std"], p["empty_std"], [[0, 0, w, h]])
    if "mittel" in active and not (p["mean_min"] <= stats["luma_mean"] <= p["mean_max"]):
        add("mittel_ausserhalb", stats["luma_mean"], [p["mean_min"], p["mean_max"]])
    if "farben" in active:
        r, g, b = c[..., 0].astype(np.int16), c[..., 1].astype(np.int16), c[..., 2].astype(np.int16)
        mag = (r >= 180) & (b >= 180) & (g * 3 <= np.minimum(r, b))
        cya = (g >= 180) & (b >= 180) & (r * 3 <= np.minimum(g, b))
        stats["magenta_fraction"] = round(float(mag.mean()), 5)
        stats["cyan_fraction"] = round(float(cya.mean()), 5)
        if stats["magenta_fraction"] >= p["magenta_fraction"]:
            add("magenta", stats["magenta_fraction"], p["magenta_fraction"],
                [_shift_box(k["bbox"], left, top) for k in components(mag, 20)[:5]])
        if stats["cyan_fraction"] >= p["cyan_fraction"]:
            add("cyan", stats["cyan_fraction"], p["cyan_fraction"],
                [_shift_box(k["bbox"], left, top) for k in components(cya, 20)[:5]])

    if "weiss" in active:
        wm = c.min(axis=2) >= p["white_min_channel"]
        min_area = max(p["white_min_area_px"], int(p["white_min_area_fraction"] * area))
        comps = [k for k in components(wm, min_area) if k["rect"] >= p["white_min_rect"]]
        wf = sum(k["area"] for k in comps) / area
        stats["white_fraction"] = round(float(wf), 5)
        stats["white_components"] = len(comps)
        stats["white_largest_rect"] = comps[0]["rect"] if comps else 0.0
        if wf >= p["white_flag_fraction"]:
            add("weisse_flaeche", wf, p["white_flag_fraction"], [_shift_box(k["bbox"], left, top) for k in comps[:6]])

    if "schwarz" in active:
        bm = c.max(axis=2) <= p["black_max_channel"]
        comps = components(bm, max(300, int(p["black_min_area_fraction"] * area)))
        bf = sum(k["area"] for k in comps) / area
        stats["black_fraction"] = round(float(bf), 5)
        if bf >= p["black_flag_fraction"]:
            add("schwarze_flaeche", bf, p["black_flag_fraction"], [_shift_box(k["bbox"], left, top) for k in comps[:6]])

    if "flach" in active:
        t = p["flat_block"]
        th, tw = (c.shape[0] // t) * t, (c.shape[1] // t) * t
        blocks = c[:th, :tw].reshape(th // t, t, tw // t, t, 3)
        rng = blocks.max(axis=(1, 3)).astype(np.int16) - blocks.min(axis=(1, 3)).astype(np.int16)
        flat = rng.max(axis=2) <= p["flat_range"]
        comps = components(flat, 4)
        carea = float(flat.size)
        largest = comps[0]["area"] / carea if comps else 0.0
        stats["flat_fraction"] = round(float(flat.mean()), 4)
        stats["flat_largest"] = round(float(largest), 4)
        if largest >= p["flat_flag_fraction"]:
            add("flach_gross", largest, p["flat_flag_fraction"],
                [_shift_box([k["bbox"][0] * t, k["bbox"][1] * t, k["bbox"][2] * t, k["bbox"][3] * t], left, top) for k in comps[:4]])

    if "streckung" in active:
        st, boxes = detect_streaks(c, p)
        stats.update({"streak_tiles_textured": st["textured"], "streak_tiles_coherent": st["coherent"], "streak_tiles_diag": st["diag"]})
        frac = st["diag"] * p["tile"] * p["tile"] / area
        stats["streak_diag_fraction"] = round(float(frac), 4)
        if frac >= p["diag_flag_fraction"]:
            tb = [_shift_box(b, left, top) for b in boxes]
            add("gestreckt", frac, p["diag_flag_fraction"], tb[:80])

    if "hud" in active:
        hud = detect_hud(rgb, p)
        stats["hud_glyphs"] = hud["glyphs"]
        if hud["glyphs"] >= p["hud_min_components"]:
            add("hud_text", hud["glyphs"], p["hud_min_components"], [hud["box"]])
    return {"flags": flags, "stats": stats}


def active_flags(result):
    """Namen der Flags, die nicht per Szenario erlaubt sind."""
    return [f["flag"] for f in result["flags"] if not f.get("allowed")]


def error_flags(result):
    return [f["flag"] for f in result["flags"] if not f.get("allowed") and f["severity"] == "fehler"]


# ---------------------------------------------------------------------------------------------------------------------
# Vergleich zweier Bilder
# ---------------------------------------------------------------------------------------------------------------------

def compare_images(base, cur, thresholds=None):
    """Kennzahlen Baseline → aktuell. Bilder verschiedener Größe: das aktuelle wird auf die Baseline-Größe skaliert, Flag size_changed."""
    t = dict(THRESHOLDS)
    if thresholds:
        t.update(thresholds)
    size_changed = base.shape != cur.shape
    if size_changed:
        cur = np.asarray(Image.fromarray(cur).resize((base.shape[1], base.shape[0]), Image.BILINEAR), dtype=np.uint8)
    diff = np.abs(base.astype(np.int16) - cur.astype(np.int16))
    mad = float(diff.mean())
    changed = float((diff.max(axis=2) > t["changed_pixel_delta"]).mean())
    mse = float((diff.astype(np.float64) ** 2).mean())
    psnr = float("inf") if mse == 0 else 10 * math.log10(255.0 * 255.0 / mse)
    lb, lc = laplace_variance(base), laplace_variance(cur)
    mb, mc = base.reshape(-1, 3).mean(axis=0), cur.reshape(-1, 3).mean(axis=0)
    out = {
        "size_changed": bool(size_changed),
        "mean_abs_diff": round(mad, 3),
        "changed_fraction": round(changed, 5),
        "ssim": round(ssim(base, cur), 4),
        "psnr": None if math.isinf(psnr) else round(psnr, 2),
        "laplace_base": round(lb, 2), "laplace_run": round(lc, 2),
        "laplace_ratio": round(lc / lb, 3) if lb > 1e-6 else (1.0 if lc <= 1e-6 else 99.0),
        "mean_rgb_base": [round(float(v), 2) for v in mb], "mean_rgb_run": [round(float(v), 2) for v in mc],
        "mean_shift": round(float(np.abs(mc - mb).max()), 2),
        "hist_distance": round(hist_distance(base, cur), 4),
    }
    v = []
    if out["ssim"] < t["ssim_min"]: v.append("ssim %.3f < %.2f" % (out["ssim"], t["ssim_min"]))
    if mad > t["mad_max"]: v.append("MAD %.1f > %.1f" % (mad, t["mad_max"]))
    if changed > t["changed_max"]: v.append("geändert %.1f %% > %.0f %%" % (changed * 100, t["changed_max"] * 100))
    if out["laplace_ratio"] < t["laplace_ratio_min"]: v.append("Texturdetail %.2f < %.2f" % (out["laplace_ratio"], t["laplace_ratio_min"]))
    if out["mean_shift"] > t["mean_shift_max"]: v.append("Mittelwert-Verschiebung %.1f > %.0f" % (out["mean_shift"], t["mean_shift_max"]))
    if size_changed: v.append("Bildgröße geändert")
    out["violations"] = v
    return out


def diff_image(base, cur, gain=4.0):
    """Differenzbild verstärkt (hell = verändert); Größen werden auf die Baseline gebracht."""
    if base.shape != cur.shape:
        cur = np.asarray(Image.fromarray(cur).resize((base.shape[1], base.shape[0]), Image.BILINEAR), dtype=np.uint8)
    d = np.abs(base.astype(np.int16) - cur.astype(np.int16)) * gain
    return np.clip(d, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------------------
# Läufe, Szenarien, Bericht
# ---------------------------------------------------------------------------------------------------------------------

def shots_dir(run):
    run = Path(run)
    return run / "shots" if (run / "shots").is_dir() else run


def list_images(run):
    d = shots_dir(run)
    if not d.is_dir():
        return {}
    return {p.stem: p for p in sorted(d.glob("*.png"))}


def load_scenarios(path):
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    out = {}
    for s in data.get("scenarios", []):
        m = dict(defaults); m.update(s)
        out[m["name"]] = m
    return out


def evaluate(run, baseline=None, scenarios=None, strict=False, sheets=True, out=None, gain=4.0, log=print):
    """Vergleicht einen Lauf; schreibt report.json, report.md, diff/*.png, contact/*.png. Rückgabe: (report dict, exit_code)."""
    run = Path(run).resolve()
    out = Path(out).resolve() if out else run
    out.mkdir(parents=True, exist_ok=True)
    scenarios = scenarios or {}
    cur_imgs = list_images(run)
    base_imgs = list_images(baseline) if baseline and Path(baseline).exists() else {}
    base_meta = {}
    if baseline and (Path(baseline) / "baseline.json").is_file():
        base_meta = json.loads((Path(baseline) / "baseline.json").read_text(encoding="utf-8"))
    results, problems = [], []
    names = list(cur_imgs.keys())
    capture = None
    if (run / "capture.json").is_file():
        try:
            capture = json.loads((run / "capture.json").read_text(encoding="utf-8"))
        except ValueError:
            capture = None
    requested = set(capture.get("requested", [])) if capture and capture.get("requested") else None
    for name in scenarios:
        wanted = scenarios[name].get("required", True) and scenarios[name].get("enabled", True)
        if requested is not None:
            wanted = wanted and name in requested
        if name not in cur_imgs and wanted:
            results.append({"name": name, "status": "fehlt", "flags": [], "violations": ["Aufnahme fehlt im Lauf"]})
            problems.append(name + ": Aufnahme fehlt")
    for name in names:
        sc = scenarios.get(name, {})
        kind = sc.get("kind", "field")
        t0 = time.time()
        cur = load_rgb(cur_imgs[name])
        an = anomalies(cur, kind, sc.get("detector_overrides"), sc.get("allow", ()))
        res = {"name": name, "path": str(cur_imgs[name]), "kind": kind, "metrics": image_metrics(cur),
               "anomalies": an, "flags": active_flags(an), "error_flags": error_flags(an), "violations": [], "status": "neu"}
        base_flags = None
        if name in base_imgs:
            base = load_rgb(base_imgs[name])
            res["status"] = "verglichen"
            res["baseline_path"] = str(base_imgs[name])
            res["compare"] = compare_images(base, cur, sc.get("thresholds"))
            res["violations"].extend(res["compare"]["violations"])
            bm = base_meta.get("images", {}).get(name)
            if bm is not None:
                base_flags, base_stats = bm.get("error_flags", []), bm.get("stats", {})
            else:
                ban = anomalies(base, kind, sc.get("detector_overrides"), sc.get("allow", ()))
                base_flags, base_stats = error_flags(ban), ban["stats"]
            res["baseline_error_flags"] = base_flags
            res["new_flags"] = [f for f in res["error_flags"] if f not in base_flags]
            res["resolved_flags"] = [f for f in base_flags if f not in res["error_flags"]]
            if res["new_flags"]:
                res["violations"].append("neue Fehlerflags: " + ", ".join(res["new_flags"]))
            th = dict(THRESHOLDS); th.update(sc.get("thresholds") or {})
            for key, tkey, label in (("streak_diag_fraction", "streak_delta_max", "gerichtete Strukturen"), ("flat_largest", "flat_delta_max", "flache Region")):
                if key in an["stats"] and key in base_stats:
                    delta = an["stats"][key] - base_stats[key]
                    res["compare"][key + "_delta"] = round(delta, 4)
                    if delta > th[tkey]:
                        res["violations"].append("%s +%.3f > %.3f" % (label, delta, th[tkey]))
            if sc.get("diff", True) and res["compare"]["changed_fraction"] > 0.0005:
                (out / "diff").mkdir(exist_ok=True)
                Image.fromarray(diff_image(base, cur, gain)).save(out / "diff" / (name + ".png"))
        else:
            res["new_flags"] = list(res["error_flags"])
            if strict and res["error_flags"]:
                res["violations"].append("Fehlerflags ohne Baseline: " + ", ".join(res["error_flags"]))
        if res["violations"]:
            problems.append(name + ": " + "; ".join(res["violations"]))
        res["seconds"] = round(time.time() - t0, 2)
        results.append(res)
        log("  %-34s %-10s flags=%s" % (name, res["status"], ",".join(res["flags"]) or "-"))
    # Baseline-Bilder ohne aktuellen Gegenpart sind nur eine Notiz (Szenario entfernt/umbenannt).
    orphans = [n for n in base_imgs if n not in cur_imgs and (not scenarios or n in scenarios)]
    report = {
        "run": str(run), "baseline": str(baseline) if baseline else None, "baseline_present": bool(base_imgs),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "thresholds": THRESHOLDS, "strict": strict,
        "images": results, "orphans": orphans, "problems": problems, "capture": capture,
        "summary": {
            "images": len(cur_imgs), "compared": sum(1 for r in results if r["status"] == "verglichen"),
            "new": sum(1 for r in results if r["status"] == "neu"), "missing": sum(1 for r in results if r["status"] == "fehlt"),
            "with_error_flags": sum(1 for r in results if r.get("error_flags")), "regressions": len(problems),
        },
    }
    sheet_files = []
    if sheets and cur_imgs:
        sheet_files = make_contact_sheets(results, base_imgs, cur_imgs, out / "contact", gain)
    report["contact_sheets"] = [str(p) for p in sheet_files]
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report, out), encoding="utf-8")
    return report, (1 if problems else 0)


# ---------------------------------------------------------------------------------------------------------------------
# Kontaktbögen
# ---------------------------------------------------------------------------------------------------------------------

_FONT = {}


def font(size=13):
    if size not in _FONT:
        _FONT[size] = None
        for cand in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if os.path.isfile(cand):
                try:
                    _FONT[size] = ImageFont.truetype(cand, size)
                    break
                except OSError:
                    pass
        if _FONT[size] is None:
            try:
                _FONT[size] = ImageFont.load_default(size=size)
            except TypeError:  # ältere Pillow
                _FONT[size] = ImageFont.load_default()
    return _FONT[size]


def thumb_of(rgb, w, h, boxes=None, color=(255, 40, 40)):
    im = Image.fromarray(rgb)
    sx, sy = w / float(im.width), h / float(im.height)
    im = im.resize((w, h), Image.LANCZOS)
    if boxes:
        dr = ImageDraw.Draw(im)
        for b in boxes[:40]:
            dr.rectangle([b[0] * sx, b[1] * sy, max(b[0] * sx + 1, b[2] * sx), max(b[1] * sy + 1, b[3] * sy)], outline=color, width=2)
    return im


def _caption(draw, xy, text, fill=(255, 255, 255), size=13):
    draw.text(xy, text, fill=fill, font=font(size))


def make_contact_sheets(results, base_imgs, cur_imgs, outdir, gain=4.0, thumb=(416, 234), rows_per_sheet=4, grid_cols=4, grid_thumb=(312, 176)):
    """uebersicht_NN.png (Raster aller Bilder des Laufs, Flächen rot markiert) und vergleich_NN.png (Baseline | Lauf | Differenz x gain)."""
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.png"):
        old.unlink()
    files = []
    present = [r for r in results if r["status"] in ("verglichen", "neu")]
    # Übersicht
    per = grid_cols * 5
    for si in range(0, len(present), per):
        chunk = present[si:si + per]
        gw, gh = grid_thumb
        cell_h = gh + 34
        rows = (len(chunk) + grid_cols - 1) // grid_cols
        sheet = Image.new("RGB", (grid_cols * (gw + 6) + 6, rows * (cell_h + 6) + 6), (24, 24, 28))
        dr = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            x, y = 6 + (i % grid_cols) * (gw + 6), 6 + (i // grid_cols) * (cell_h + 6)
            boxes = [b for f in r["anomalies"]["flags"] if f["severity"] == "fehler" and not f.get("allowed") for b in f["boxes"]]
            sheet.paste(thumb_of(load_rgb(r["path"]), gw, gh, boxes), (x, y + 32))
            bad = bool(r["violations"])
            _caption(dr, (x, y), r["name"], (255, 120, 120) if bad else (230, 230, 230), 14)
            fl = ",".join(r["flags"]) or "ohne Flags"
            _caption(dr, (x, y + 16), fl[:52], (255, 200, 80) if r["flags"] else (120, 200, 120), 12)
        p = outdir / ("uebersicht_%02d.png" % (si // per + 1))
        sheet.save(p)
        files.append(p)
    # Vorher/Nachher/Differenz
    pairs = [r for r in present if r["status"] == "verglichen"]
    pairs.sort(key=lambda r: -r["compare"]["changed_fraction"])
    tw, th = thumb
    for si in range(0, len(pairs), rows_per_sheet):
        chunk = pairs[si:si + rows_per_sheet]
        sheet = Image.new("RGB", (3 * (tw + 6) + 6, len(chunk) * (th + 40) + 6), (24, 24, 28))
        dr = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            y = 6 + i * (th + 40)
            base, cur = load_rgb(r["baseline_path"]), load_rgb(r["path"])
            boxes = [b for f in r["anomalies"]["flags"] if f["severity"] == "fehler" and not f.get("allowed") for b in f["boxes"]]
            c = r["compare"]
            head = "%s   SSIM %.3f  MAD %.1f  geändert %.1f %%  Laplace x%.2f" % (r["name"], c["ssim"], c["mean_abs_diff"], c["changed_fraction"] * 100, c["laplace_ratio"])
            _caption(dr, (6, y), head, (255, 120, 120) if r["violations"] else (230, 230, 230), 14)
            _caption(dr, (6, y + 17), ("Flags: " + ",".join(r["flags"])) if r["flags"] else "Flags: keine", (255, 200, 80) if r["flags"] else (120, 200, 120), 12)
            sheet.paste(thumb_of(base, tw, th), (6, y + 34))
            sheet.paste(thumb_of(cur, tw, th, boxes), (6 + tw + 6, y + 34))
            sheet.paste(thumb_of(diff_image(base, cur, gain), tw, th), (6 + 2 * (tw + 6), y + 34))
        p = outdir / ("vergleich_%02d.png" % (si // rows_per_sheet + 1))
        sheet.save(p)
        files.append(p)
    return files


# ---------------------------------------------------------------------------------------------------------------------
# Markdown-Bericht
# ---------------------------------------------------------------------------------------------------------------------

def _rgb(v):
    return "%d,%d,%d" % tuple(int(round(x)) for x in v)


def render_markdown(rep, out):
    L = []
    s = rep["summary"]
    L.append("# Sichtprüfung: Lauf %s" % Path(rep["run"]).name)
    L.append("")
    L.append("Erstellt %s. Baseline: %s. Ergebnis: **%s**." % (
        rep["created"], rep["baseline"] if rep["baseline_present"] else "keine (alle Bilder neu)",
        "Regression" if rep["problems"] else "in Ordnung"))
    L.append("")
    L.append("| Bilder | verglichen | neu | fehlend | mit Fehlerflags | Regressionen |")
    L.append("|---|---|---|---|---|---|")
    L.append("| %d | %d | %d | %d | %d | %d |" % (s["images"], s["compared"], s["new"], s["missing"], s["with_error_flags"], s["regressions"]))
    L.append("")
    if rep.get("capture"):
        c = rep["capture"]
        L.append("Aufnahme: " + ", ".join("%s %s" % (k, v) for k, v in c.items() if not isinstance(v, (list, dict))) + ".")
        L.append("")
    L.append("## Tabelle")
    L.append("")
    L.append("| Bild | Status | SSIM | MAD | geändert | Laplace alt→neu | Mittel RGB (neu) | Flags |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rep["images"]:
        if r["status"] == "fehlt":
            L.append("| %s | **fehlt** | | | | | | |" % r["name"])
            continue
        c = r.get("compare")
        fl = ", ".join(("**%s**" % f if f in r["error_flags"] else f) + ("*" if f in r.get("new_flags", []) and c else "") for f in r["flags"]) or "–"
        if c:
            L.append("| %s | verglichen | %.3f | %.1f | %.1f %% | %.0f→%.0f | %s | %s |" % (
                r["name"], c["ssim"], c["mean_abs_diff"], c["changed_fraction"] * 100, c["laplace_base"], c["laplace_run"], _rgb(c["mean_rgb_run"]), fl))
        else:
            m = r["metrics"]
            L.append("| %s | neu | – | – | – | –→%.0f | %s | %s |" % (r["name"], m["laplace_var"], _rgb(m["mean_rgb"]), fl))
    L.append("")
    L.append("Fett = Fehlerflag, `*` = neu gegenüber der Baseline. Schwellen: " + ", ".join("%s %s" % (k, v) for k, v in rep["thresholds"].items()) + ".")
    L.append("")
    L.append("## Regressionen")
    L.append("")
    if rep["problems"]:
        for pr in rep["problems"]:
            L.append("- " + pr)
    else:
        L.append("Keine.")
    L.append("")
    L.append("## Heuristische Fehlerbilder (Details)")
    L.append("")
    any_flag = False
    for r in rep["images"]:
        if r["status"] == "fehlt":
            continue
        fl = [f for f in r["anomalies"]["flags"]]
        if not fl:
            continue
        any_flag = True
        L.append("**%s**" % r["name"])
        for f in fl:
            L.append("- `%s` (%s%s): %s; Wert %s, Schwelle %s%s" % (
                f["flag"], f["severity"], ", erlaubt" if f.get("allowed") else "", f["text"], f["value"], f["threshold"],
                "; Fläche(n) " + str(f["boxes"][:3]) if f["boxes"] and f["flag"] != "gestreckt" else ""))
        L.append("")
    if not any_flag:
        L.append("Keine Auffälligkeiten.")
        L.append("")
    if rep["orphans"]:
        L.append("Baseline-Bilder ohne Bild im Lauf: " + ", ".join(rep["orphans"]) + ".")
        L.append("")
    L.append("## Zur manuellen/Agenten-Sichtung")
    L.append("")
    L.append("Kontaktbögen (mit dem view-Tool öffnen; rote Rahmen = erkannte Fehlerflächen; Vergleichsbögen: links Baseline, Mitte Lauf, rechts Differenz ×4, nach Veränderung sortiert):")
    L.append("")
    for p in rep.get("contact_sheets", []):
        L.append("- `%s`" % p)
    if not rep.get("contact_sheets"):
        L.append("- (keine Kontaktbögen erzeugt)")
    L.append("")
    L.append("Einzelbilder des Laufs: `%s`. Zum Akzeptieren nach der Sichtung: `scripts/visual_auto.sh accept %s`." % (shots_dir(rep["run"]), Path(rep["run"]).name))
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------------------------
# Baseline übernehmen
# ---------------------------------------------------------------------------------------------------------------------

def accept_run(run, baseline, scenarios=None, log=print):
    run, baseline = Path(run), Path(baseline)
    imgs = list_images(run)
    if not imgs:
        raise SystemExit("Lauf %s enthält keine PNG-Bilder." % run)
    scenarios = scenarios or {}
    if baseline.exists():
        old = baseline.with_name(baseline.name + ".alt")
        if old.exists():
            shutil.rmtree(old)
        baseline.rename(old)
        log("Alte Baseline -> %s" % old)
    (baseline / "shots").mkdir(parents=True)
    meta = {"accepted_from": str(run), "accepted_at": time.strftime("%Y-%m-%d %H:%M:%S"), "images": {}}
    for name, p in imgs.items():
        shutil.copyfile(p, baseline / "shots" / (name + ".png"))
        sc = scenarios.get(name, {})
        an = anomalies(load_rgb(p), sc.get("kind", "field"), sc.get("detector_overrides"), sc.get("allow", ()))
        meta["images"][name] = {"flags": active_flags(an), "error_flags": error_flags(an), "stats": an["stats"]}
    (baseline / "baseline.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    log("Baseline mit %d Bildern: %s" % (len(imgs), baseline))
    return meta


# ---------------------------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--run", required=True)
    c.add_argument("--baseline", default=str(ROOT / "work" / "visual" / "auto" / "baseline"))
    c.add_argument("--scenarios", default=str(ROOT / "scripts" / "visual" / "scenarios.json"))
    c.add_argument("--out", default=None)
    c.add_argument("--strict", action="store_true", help="auch Fehlerflags von Bildern ohne Baseline sind Regressionen")
    c.add_argument("--no-sheets", action="store_true")
    c.add_argument("--gain", type=float, default=4.0)
    a = sub.add_parser("analyze")
    a.add_argument("images", nargs="+")
    a.add_argument("--kind", default="field", choices=sorted(KIND_DETECTORS))
    a.add_argument("--json", action="store_true")
    k = sub.add_parser("accept")
    k.add_argument("--run", required=True)
    k.add_argument("--baseline", default=str(ROOT / "work" / "visual" / "auto" / "baseline"))
    k.add_argument("--scenarios", default=str(ROOT / "scripts" / "visual" / "scenarios.json"))
    r = sub.add_parser("ref", help="Referenzmodus (Ryujinx): import | compare | cache, siehe scripts/visual_ref.py")
    r.add_argument("refargs", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "ref":
            import visual_ref
            return visual_ref.main(args.refargs)
        if args.cmd == "compare":
            sc = load_scenarios(args.scenarios)
            rep, code = evaluate(args.run, args.baseline, sc, args.strict, not args.no_sheets, args.out, args.gain)
            out = Path(args.out) if args.out else Path(args.run)
            print("Bericht: %s" % (out / "report.md"))
            for p in rep["problems"]:
                print("REGRESSION " + p)
            return code
        if args.cmd == "analyze":
            for path in args.images:
                an = anomalies(load_rgb(path), args.kind)
                if args.json:
                    print(json.dumps({"image": path, **an}, ensure_ascii=False))
                else:
                    print("%-60s %s" % (path, ",".join(f["flag"] + ("(" + f["severity"][0] + ")") for f in an["flags"]) or "-"))
            return 0
        if args.cmd == "accept":
            accept_run(args.run, args.baseline, load_scenarios(args.scenarios))
            return 0
    except (OSError, ValueError) as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
