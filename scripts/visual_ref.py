#!/usr/bin/env python3
"""Vergleich mit Ryujinx-Referenzbildern (docs/visuelle-pruefung.md, Abschnitt Ryujinx-Referenz).

  visual_ref.py import  --raw work/visual/ref/ryujinx/raw --dest work/visual/ref/ryujinx [--offset SEK] [--map ref_map.json]
        Rohbilder (F8-Screenshots) den Ansichten aus ref_map.json zuordnen (Reihenfolge der Dateizeit oder Umbenennung),
        auf 1280x720 normalisieren (schwarze Ränder abschneiden, auf 16:9 zuschneiden, skalieren) nach <dest>/views/<Ansicht>.png,
        Zuordnung und Spieluhr nach <dest>/assignments.json. Idempotent: bekannte Dateien werden nicht erneut zugeordnet.
  visual_ref.py import --source recomp [--raw DIR…] [--all-free]
        Rekompilations-Screenshots (Standard: work/recomp/shots = Mac-Metal, work/visual/recomp = Ryzen) nach work/visual/ref/recomp/views/.
        Zuordnung nur per Name (Ansichtsname, "aliases" in ref_map.json, Präfix free_); sonst wird die Datei übergangen.
  visual_ref.py compare --run work/visual/auto/<lauf> [--source ryujinx|recomp] [--ref work/visual/ref/ryujinx] [--out DIR] [--gate] [--no-align]
        Unity-/Recomp-Bild des Laufs gegen die Referenz: SSIM, mittlere Abweichung (roh und nach Histogramm-Angleichung),
        Kantenschärfe-Verhältnis, Farbstich, Raster-Heatmap (8x8) mit schlechtesten Zellen; Bericht ref_report.md/json und
        Kontaktbogen contact/ref_NN.png (Referenz | Unity | Differenz-Heatmap). Aufruf auch: visual_compare.py ref compare ...
  visual_ref.py refs [--a recomp] [--b ryujinx]
        Zwei Referenzquellen gegeneinander (Rekompilation gegen Ryujinx): gleiche Ansichten, Kennzahlen, Heatmap, Kontaktbogen.
  visual_ref.py cache --entries NAME=GRÖSSE:ANZAHL ... [--used work/materials_all/used_final.json]
        Ryujinx-Shader-Cache (nur Zahlen) neben die Zahl unserer genutzten Varianten stellen.
Exit-Code compare: 0 = in Ordnung (oder ohne --gate), 1 = Schwelle verletzt (--gate), 2 = Fehler.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visual_compare as vc  # noqa: E402
from visual_compare import np, Image, ImageDraw  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT / "scripts" / "visual" / "ref_map.json"
DEFAULT_REF = ROOT / "work" / "visual" / "ref" / "ryujinx"
# Referenzquellen: Ryujinx (Emulator, F8) und Rekompilation (Original-Engine rekompiliert: Mac-Metal und Ryzen-Vulkan)
SOURCES = {"ryujinx": DEFAULT_REF, "recomp": ROOT / "work" / "visual" / "ref" / "recomp"}
RECOMP_RAW = (ROOT / "work" / "recomp" / "shots", ROOT / "work" / "visual" / "recomp")
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp"}


def load_map(path=None):
    return json.loads(Path(path or DEFAULT_MAP).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------------
# Normalisieren und Zuordnen
# ---------------------------------------------------------------------------------------------------------------------

def normalize(rgb, width=1280, height=720, crop_bars=True):
    """Schwarze Ränder abschneiden, auf Seitenverhältnis width:height zuschneiden (mittig), auf width x height skalieren."""
    img = rgb
    if crop_bars:
        l, t, r, b = vc.find_bars(img, vc.DETECTOR_PARAMS)
        if (l or t or r or b) and img.shape[0] - t - b > 16 and img.shape[1] - l - r > 16:
            img = img[t:img.shape[0] - b, l:img.shape[1] - r]
    h, w = img.shape[:2]
    target = width / float(height)
    if abs(w / float(h) - target) > 0.02:
        if w / float(h) > target:
            nw = int(round(h * target)); x0 = (w - nw) // 2
            img = img[:, x0:x0 + nw]
        else:
            nh = int(round(w / target)); y0 = (h - nh) // 2
            img = img[y0:y0 + nh, :]
    if img.shape[1] != width or img.shape[0] != height:
        img = np.asarray(Image.fromarray(np.ascontiguousarray(img)).resize((width, height), Image.LANCZOS), dtype=np.uint8)
    return img


def game_hour(epoch, offset_seconds):
    """Spielstunde in Ryujinx (Annahme: Host-Epoche + system_time_offset, Zeitzone UTC)."""
    return round(((int(epoch) + int(offset_seconds)) % 86400) / 3600.0, 2)


def import_new(raw_dir, dest, ref_map, offset_seconds=0, log=print, since=None):
    raw_dir, dest = Path(raw_dir), Path(dest)
    (dest / "views").mkdir(parents=True, exist_ok=True)
    state_path = dest / "assignments.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"files": {}, "views": {}}
    norm = ref_map.get("normalize", {})
    views = [v["view"] for v in ref_map.get("views", [])]
    files = sorted((p for p in raw_dir.glob("*") if p.suffix.lower() in IMG_EXT), key=lambda p: (p.stat().st_mtime, p.name))
    new = [p for p in files if p.name not in state["files"]]
    # Originale, die der Nutzer/ryujinx_record.sh umbenannt hat (<Ansicht>__<Original>), nicht noch einmal der Reihe nach zuordnen
    renamed_from = {p.name.split("__", 1)[1] for p in files if "__" in p.name}
    for p in [p for p in new if p.name in renamed_from]:
        state["files"][p.name] = {"view": None, "ignored": "umbenannte Kopie vorhanden", "mtime": int(p.stat().st_mtime)}
    new = [p for p in new if p.name not in renamed_from]
    # Umbenannte Dateien zuerst: Name beginnt mit dem Namen einer Ansicht (gelten auch vor --since: ausdrücklicher Wunsch)
    claimed = {}
    for p in new:
        for v in views:
            if p.stem == v or p.stem.startswith(v + "_") or p.stem.startswith(v + "-"):
                claimed[p.name] = v
                break
    if since:
        for p in [p for p in new if p.name not in claimed and p.stat().st_mtime < since]:
            state["files"][p.name] = {"view": None, "ignored": "vor --since", "mtime": int(p.stat().st_mtime)}
            log("  %-40s ignoriert (älter als --since)" % p.name)
        new = [p for p in new if p.name in claimed or p.stat().st_mtime >= since]
    taken = set(state["views"]) | set(claimed.values())
    free_views = [v for v in views if v not in taken]
    out = []
    for p in new:
        if p.name in claimed:
            view = claimed[p.name]
        elif p.stem.startswith("free_"):
            view = p.stem.split("__")[0]
        elif free_views:
            view = free_views.pop(0)
        else:
            view = "free_" + p.stem
        rgb = vc.load_rgb(p)
        n = normalize(rgb, norm.get("width", 1280), norm.get("height", 720), norm.get("crop_bars", True))
        Image.fromarray(n).save(dest / "views" / (view + ".png"))
        st = p.stat()
        entry = {
            "view": view, "source_size": [int(rgb.shape[1]), int(rgb.shape[0])], "mtime": int(st.st_mtime),
            "mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "game_hour": game_hour(st.st_mtime, offset_seconds), "time_offset": int(offset_seconds),
            "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
        }
        state["files"][p.name] = entry
        state["views"][view] = {"file": p.name, "game_hour": entry["game_hour"]}
        out.append((p.name, view, entry["game_hour"]))
        log("  %-40s -> %-24s Spielstunde %.2f (Quelle %dx%d)" % (p.name, view, entry["game_hour"], rgb.shape[1], rgb.shape[0]))
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    return out, state


def _view_for(stem, views, aliases):
    """Ansicht zu einem Dateinamen: Ansichtsname (auch als Präfix) oder Alias-Präfix aus ref_map.json."""
    for v in views:
        if stem == v or stem.startswith(v + "_") or stem.startswith(v + "-"):
            return v
    for v, al in aliases.items():
        if any(stem.startswith(a) for a in al):
            return v
    return None


def import_recomp(raw_dirs, dest, ref_map, log=print, all_free=False):
    """Rekompilations-Screenshots (Mac-Metal: work/recomp/shots, Ryzen: work/visual/recomp) als zweite Referenzquelle.
    Nur Zuordnung per Name (Ansichtsname, Alias aus ref_map.json "aliases" oder Präfix free_); alles andere wird übergangen
    (all_free=True: auch als free_<Name> führen). Eine geänderte Datei (Größe/Zeit) wird erneut importiert, die neuere gewinnt."""
    dest = Path(dest)
    (dest / "views").mkdir(parents=True, exist_ok=True)
    state_path = dest / "assignments.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"files": {}, "views": {}}
    norm = ref_map.get("normalize", {})
    views = [v["view"] for v in ref_map.get("views", [])]
    aliases = {v["view"]: v.get("aliases", []) for v in ref_map.get("views", []) if v.get("aliases")}
    files = []
    for d in raw_dirs:
        files += [p for p in Path(d).glob("*") if p.suffix.lower() in IMG_EXT]
    files.sort(key=lambda p: (p.stat().st_mtime, str(p)))
    out = []
    for p in files:
        key = "%s/%s" % (p.parent.name, p.name)
        st = p.stat()
        sig = [int(st.st_mtime), st.st_size]
        if state["files"].get(key, {}).get("sig") == sig:
            continue
        view = _view_for(p.stem, views, aliases)
        if view is None and p.stem.startswith("free_"):
            view = p.stem.split("__")[0]
        if view is None and all_free:
            view = "free_" + p.stem
        if view is None:
            continue
        rgb = vc.load_rgb(p)
        Image.fromarray(normalize(rgb, norm.get("width", 1280), norm.get("height", 720), norm.get("crop_bars", True))).save(dest / "views" / (view + ".png"))
        state["files"][key] = {"view": view, "sig": sig, "source_size": [int(rgb.shape[1]), int(rgb.shape[0])],
                               "mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}
        state["views"][view] = {"file": key, "game_hour": None}
        out.append((key, view))
        log("  %-52s -> %-24s (Quelle %dx%d)" % (key, view, rgb.shape[1], rgb.shape[0]))
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    return out, state


def refs_compare(dir_a, dir_b, ref_map, out, label_a="recomp", label_b="ryujinx", align=True, log=print):
    """Zwei Referenzquellen gegeneinander (z. B. Rekompilation gegen Ryujinx): gleiche Ansichten, B ist die Referenz."""
    dir_a, dir_b, out = Path(dir_a), Path(dir_b), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cmp_cfg = ref_map.get("compare", {})
    grid = tuple(cmp_cfg.get("grid", [8, 8]))
    results = []
    for v in ref_map.get("views", []):
        pa, pb = dir_a / "views" / (v["view"] + ".png"), dir_b / "views" / (v["view"] + ".png")
        res = {"view": v["view"], "title": v.get("title", ""), "unity": label_a}
        if not (pa.is_file() and pb.is_file()):
            res["status"] = "fehlt (%s)" % ", ".join(n for n, p in ((label_a, pa), (label_b, pb)) if not p.is_file())
        else:
            m, _, _, valid, diff_m = compare_pair(vc.load_rgb(pb), vc.load_rgb(pa), v.get("mask"), grid, cmp_cfg.get("cell_bad_mad", 28.0), cmp_cfg.get("max_shift_px", 48), align)
            (out / "ref").mkdir(exist_ok=True)
            Image.fromarray(heatmap(diff_m, valid, m, grid)).save(out / "ref" / (v["view"] + "_heatmap.png"))
            res.update(status="verglichen", metrics=m, ref_path=str(pb), unity_path=str(pa), game_hour=None, violations=[])
            log("  %-24s SSIM %.3f (angeglichen %.3f)  MAD %.1f -> %.1f" % (v["view"], m["ssim"], m["ssim_matched"], m["mad"], m["mad_matched"]))
        results.append(res)
    sheets = make_sheets(results, out / "contact")
    rep = {"run": str(out), "ref_dir": "%s gegen %s" % (label_a, label_b), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "align": align,
           "results": results, "problems": [], "contact_sheets": [str(p) for p in sheets]}
    (out / "ref_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "ref_report.md").write_text(render_md(rep).replace("Referenzvergleich (Ryujinx ↔ Unity)", "Quellenvergleich (%s ↔ %s)" % (label_a, label_b)), encoding="utf-8")
    return rep
# ---------------------------------------------------------------------------------------------------------------------

def valid_mask(h, w, rects):
    m = np.ones((h, w), dtype=bool)
    for r in rects or []:
        x0, y0, x1, y1 = int(r[0] * w), int(r[1] * h), int(round(r[2] * w)), int(round(r[3] * h))
        m[y0:y1, x0:x1] = False
    return m


def match_hist(src, ref, valid):
    """Histogramm-Angleichung je Kanal (nur gültige Pixel): gleicht Helligkeit/Tageszeit-Offsets aus."""
    out = np.empty_like(src)
    for c in range(3):
        s, r = src[..., c][valid], ref[..., c][valid]
        if s.size == 0 or r.size == 0:
            out[..., c] = src[..., c]
            continue
        sv, sc = np.unique(s, return_counts=True)
        rv, rc = np.unique(r, return_counts=True)
        scdf = np.cumsum(sc) / float(s.size)
        rcdf = np.cumsum(rc) / float(r.size)
        mapped = np.interp(scdf, rcdf, rv)
        lut = np.interp(np.arange(256), sv, mapped)
        out[..., c] = np.clip(lut[src[..., c]] + 0.5, 0, 255).astype(np.uint8)
    return out


def best_shift(a, b, max_shift=48, down=4):
    """Verschiebung (dx, dy) in Pixeln, mit der a an b ausgerichtet wird (Kreuzkorrelation per FFT auf verkleinerter Luminanz)."""
    def small(img):
        y = vc.luma(img)
        h, w = (y.shape[0] // down) * down, (y.shape[1] // down) * down
        return y[:h, :w].reshape(h // down, down, w // down, down).mean(axis=(1, 3))
    x, y = small(a), small(b)
    x = x - x.mean()
    y = y - y.mean()
    corr = np.fft.irfft2(np.fft.rfft2(y) * np.conj(np.fft.rfft2(x)), s=x.shape)
    ms = max(1, max_shift // down)
    best, bd = -1e30, (0, 0)
    for dy in range(-ms, ms + 1):
        for dx in range(-ms, ms + 1):
            v = corr[dy % x.shape[0], dx % x.shape[1]]
            if v > best:
                best, bd = v, (dx, dy)
    return bd[0] * down, bd[1] * down


def apply_shift(img, dx, dy):
    """Bild um (dx, dy) verschieben; Rückgabe (Bild, gültig-Maske)."""
    h, w = img.shape[:2]
    out = np.zeros_like(img)
    ok = np.zeros((h, w), dtype=bool)
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    if xs1 > xs0 and ys1 > ys0:
        out[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = img[ys0:ys1, xs0:xs1]
        ok[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = True
    return out, ok


def cell_label(col, row):
    return "%s%d" % (chr(ord("A") + col), row + 1)


def compare_pair(ref, uni, rects=None, grid=(8, 8), cell_bad_mad=28.0, max_shift=48, align=True, top=5):
    """Kennzahlen Referenz vs. Unity (beide RGB uint8). Rückgabe: (Kennzahlen, ausgerichtetes Unity-Bild, angeglichenes Bild, Gültig-Maske, Differenz)."""
    h, w = ref.shape[:2]
    if uni.shape != ref.shape:
        uni = np.asarray(Image.fromarray(uni).resize((w, h), Image.LANCZOS), dtype=np.uint8)
    valid = valid_mask(h, w, rects)
    shift = (0, 0)
    if align:
        shift = best_shift(uni, ref, max_shift)
        uni, ok = apply_shift(uni, *shift)
        valid &= ok
    vn = float(valid.sum())
    if vn < 100:
        raise ValueError("kein gültiger Bildbereich")
    diff_raw = np.abs(ref.astype(np.int16) - uni.astype(np.int16)).mean(axis=2)
    matched = match_hist(uni, ref, valid)
    diff_m = np.abs(ref.astype(np.int16) - matched.astype(np.int16)).mean(axis=2)
    sm = vc.ssim_map(ref, uni, 8)
    smm = vc.ssim_map(ref, matched, 8)
    vv = valid[:sm.shape[0], :sm.shape[1]]
    ssim_raw = float(sm[vv].mean()) if vv.any() else 0.0
    ssim_m = float(smm[vv].mean()) if vv.any() else 0.0
    rows, cols = valid.any(axis=1), valid.any(axis=0)
    lr, lu = vc.laplace_variance(ref[rows][:, cols]), vc.laplace_variance(uni[rows][:, cols])
    mr, mu = ref[valid].mean(axis=0), uni[valid].mean(axis=0)
    lum_ratio = float(vc.luma(uni)[valid].mean() / max(1e-6, vc.luma(ref)[valid].mean()))
    cast = [float((mu[i] / max(1e-6, mr[i])) / max(1e-6, lum_ratio)) for i in range(3)]
    gx, gy = grid
    cells = []
    for r in range(gy):
        row = []
        for c in range(gx):
            y0, y1, x0, x1 = r * h // gy, (r + 1) * h // gy, c * w // gx, (c + 1) * w // gx
            v = valid[y0:y1, x0:x1]
            if v.mean() < 0.25:
                row.append(None)
                continue
            d = float(diff_m[y0:y1, x0:x1][v].mean())
            sy1, sx1 = min(y1, smm.shape[0]), min(x1, smm.shape[1])
            sv = valid[y0:sy1, x0:sx1]
            s = float(smm[y0:sy1, x0:sx1][sv].mean()) if sv.size and sv.any() else 0.0
            row.append({"mad": round(d, 2), "ssim": round(s, 3)})
        cells.append(row)
    flat = [(cells[r][c]["mad"], r, c) for r in range(gy) for c in range(gx) if cells[r][c]]
    bad = [f for f in flat if f[0] > cell_bad_mad]
    flat.sort(reverse=True)
    metrics = {
        "shift": [int(shift[0]), int(shift[1])], "valid_fraction": round(vn / float(h * w), 4),
        "ssim": round(ssim_raw, 4), "ssim_matched": round(ssim_m, 4),
        "mad": round(float(diff_raw[valid].mean()), 2), "mad_matched": round(float(diff_m[valid].mean()), 2),
        "changed_matched": round(float((diff_m[valid] > 32).mean()), 4),
        "laplace_ref": round(lr, 1), "laplace_unity": round(lu, 1), "laplace_ratio": round(lu / lr, 3) if lr > 1e-6 else 0.0,
        "mean_rgb_ref": [round(float(v), 1) for v in mr], "mean_rgb_unity": [round(float(v), 1) for v in mu],
        "brightness_ratio": round(lum_ratio, 3), "color_cast": [round(v, 3) for v in cast],
        "grid": cells, "bad_cells": len(bad), "bad_cell_fraction": round(len(bad) / float(max(1, len(flat))), 3),
        "worst_cells": [{"cell": cell_label(c, r), "mad": m, "ssim": cells[r][c]["ssim"]} for m, r, c in flat[:top]],
    }
    return metrics, uni, matched, valid, diff_m


_LUT = None


def heat_lut():
    global _LUT
    if _LUT is None:
        stops = [(0.0, (0, 0, 0)), (0.25, (30, 30, 160)), (0.5, (200, 40, 40)), (0.75, (255, 200, 40)), (1.0, (255, 255, 255))]
        lut = np.zeros((256, 3), dtype=np.uint8)
        for i in range(256):
            t = i / 255.0
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t0 <= t <= t1:
                    f = (t - t0) / (t1 - t0)
                    lut[i] = [int(c0[k] + (c1[k] - c0[k]) * f) for k in range(3)]
                    break
        _LUT = lut
    return _LUT


def heatmap(diff_m, valid, metrics, grid=(8, 8), vmax=64.0):
    """Differenz-Heatmap (geglättet) mit Rasterlinien; schlechteste Zellen rot umrandet und beschriftet."""
    h, w = diff_m.shape
    d = vc.box_mean(np.pad(diff_m.astype(np.float64), ((8, 8), (8, 8)), mode="edge"), 17)[:h, :w]
    idx = np.clip(d / vmax * 255.0, 0, 255).astype(np.uint8)
    img = heat_lut()[idx]
    img[~valid] = (40, 40, 40)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    gx, gy = grid
    for c in range(1, gx):
        dr.line([(c * w // gx, 0), (c * w // gx, h)], fill=(90, 90, 90), width=1)
    for r in range(1, gy):
        dr.line([(0, r * h // gy), (w, r * h // gy)], fill=(90, 90, 90), width=1)
    for wc in metrics["worst_cells"][:3]:
        c, r = ord(wc["cell"][0]) - 65, int(wc["cell"][1:]) - 1
        dr.rectangle([c * w // gx + 2, r * h // gy + 2, (c + 1) * w // gx - 3, (r + 1) * h // gy - 3], outline=(255, 60, 60), width=3)
        dr.text((c * w // gx + 8, r * h // gy + 6), "%s %.0f" % (wc["cell"], wc["mad"]), fill=(255, 255, 255), font=vc.font(22))
    return np.asarray(im, dtype=np.uint8)


def compare_run(run, ref_dir, ref_map, out=None, align=True, gate=False, log=print):
    run, ref_dir = Path(run).resolve(), Path(ref_dir)
    out = Path(out).resolve() if out else run
    out.mkdir(parents=True, exist_ok=True)
    cmp_cfg = ref_map.get("compare", {})
    grid = tuple(cmp_cfg.get("grid", [8, 8]))
    gates = cmp_cfg.get("gates", {})
    shots = vc.list_images(run)
    state_path = ref_dir / "assignments.json"
    assign = json.loads(state_path.read_text(encoding="utf-8")).get("views", {}) if state_path.is_file() else {}
    results, problems = [], []
    for v in ref_map.get("views", []):
        refp = ref_dir / "views" / (v["view"] + ".png")
        name = next((n for n in v.get("unity", []) if n in shots), None)
        res = {"view": v["view"], "title": v.get("title", ""), "unity": name, "optional": bool(v.get("optional"))}
        if not refp.is_file():
            res["status"] = "keine Referenz"
        elif name is None:
            res["status"] = "kein Unity-Bild"
            if not v.get("optional"):
                problems.append("%s: kein Unity-Bild (%s)" % (v["view"], ", ".join(v.get("unity", []))))
        else:
            ref, uni = vc.load_rgb(refp), vc.load_rgb(shots[name])
            m, _, _, valid, diff_m = compare_pair(ref, uni, v.get("mask"), grid, cmp_cfg.get("cell_bad_mad", 28.0), cmp_cfg.get("max_shift_px", 48), align)
            res.update(status="verglichen", metrics=m, ref_path=str(refp), unity_path=str(shots[name]), game_hour=assign.get(v["view"], {}).get("game_hour"))
            viol = []
            if "ssim_matched_min" in gates and m["ssim_matched"] < gates["ssim_matched_min"]:
                viol.append("SSIM (angeglichen) %.3f < %.2f" % (m["ssim_matched"], gates["ssim_matched_min"]))
            if "bad_cells_max" in gates and m["bad_cell_fraction"] > gates["bad_cells_max"]:
                viol.append("schlechte Zellen %.0f %% > %.0f %%" % (m["bad_cell_fraction"] * 100, gates["bad_cells_max"] * 100))
            res["violations"] = viol
            if gate and viol:
                problems.append("%s: %s" % (v["view"], "; ".join(viol)))
            (out / "ref").mkdir(exist_ok=True)
            Image.fromarray(heatmap(diff_m, valid, m, grid)).save(out / "ref" / (v["view"] + "_heatmap.png"))
            log("  %-24s %-22s SSIM %.3f (angeglichen %.3f)  MAD %.1f -> %.1f  schlechte Zellen %d" % (
                v["view"], name, m["ssim"], m["ssim_matched"], m["mad"], m["mad_matched"], m["bad_cells"]))
        results.append(res)
    sheets = make_sheets(results, out / "contact")
    report = {"run": str(run), "ref_dir": str(ref_dir), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "align": align, "gate": gate,
              "results": results, "problems": problems, "contact_sheets": [str(p) for p in sheets]}
    (out / "ref_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "ref_report.md").write_text(render_md(report), encoding="utf-8")
    return report, (1 if problems else 0)


def make_sheets(results, outdir, thumb=(416, 234), rows=4):
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("ref_*.png"):
        old.unlink()
    done = [r for r in results if r["status"] == "verglichen"]
    files = []
    tw, th = thumb
    for si in range(0, len(done), rows):
        chunk = done[si:si + rows]
        sheet = Image.new("RGB", (3 * (tw + 6) + 6, len(chunk) * (th + 40) + 6), (24, 24, 28))
        dr = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            y = 6 + i * (th + 40)
            m = r["metrics"]
            hint = "Spielstunde %.1f" % r["game_hour"] if r.get("game_hour") is not None else ""
            vc._caption(dr, (6, y), "%s <-> %s   SSIM %.3f (angegl. %.3f)  MAD %.1f->%.1f  %s" % (r["view"], r["unity"], m["ssim"], m["ssim_matched"], m["mad"], m["mad_matched"], hint),
                        (255, 120, 120) if r["violations"] else (230, 230, 230), 13)
            vc._caption(dr, (6, y + 17), "Laplace x%.2f  Farbstich R/G/B x%.2f/%.2f/%.2f  Helligkeit x%.2f  schlechteste Zellen: %s" % (
                m["laplace_ratio"], m["color_cast"][0], m["color_cast"][1], m["color_cast"][2], m["brightness_ratio"],
                " ".join("%s(%.0f)" % (c["cell"], c["mad"]) for c in m["worst_cells"][:3])), (255, 200, 80), 12)
            hp = outdir.parent / "ref" / (r["view"] + "_heatmap.png")
            sheet.paste(vc.thumb_of(vc.load_rgb(r["ref_path"]), tw, th), (6, y + 34))
            sheet.paste(vc.thumb_of(vc.load_rgb(r["unity_path"]), tw, th), (6 + tw + 6, y + 34))
            sheet.paste(vc.thumb_of(vc.load_rgb(hp), tw, th), (6 + 2 * (tw + 6), y + 34))
        p = outdir / ("ref_%02d.png" % (si // rows + 1))
        sheet.save(p)
        files.append(p)
    return files


def render_md(rep):
    L = ["# Referenzvergleich (Ryujinx ↔ Unity): Lauf %s" % Path(rep["run"]).name, ""]
    L.append("Erstellt %s. Referenzen: `%s`. Ausrichtung: %s. Schwellen nur mit --gate bindend (Exit-Code)." % (
        rep["created"], rep["ref_dir"], "Verschiebung per Kreuzkorrelation" if rep["align"] else "keine"))
    L += ["", "| Ansicht | Unity-Bild | Spielstunde | SSIM | SSIM angegl. | MAD roh→angegl. | Laplace-Verh. | Farbstich R/G/B | Helligkeit | schlechte Zellen | schlechteste Zellen |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["results"]:
        if r["status"] != "verglichen":
            L.append("| %s | %s | | | | | | | | | **%s** |" % (r["view"], r.get("unity") or "–", r["status"]))
            continue
        m = r["metrics"]
        L.append("| %s | %s | %s | %.3f | %.3f | %.1f→%.1f | %.2f | %.2f/%.2f/%.2f | %.2f | %d von %d | %s |" % (
            r["view"], r["unity"], r.get("game_hour") if r.get("game_hour") is not None else "–", m["ssim"], m["ssim_matched"], m["mad"], m["mad_matched"],
            m["laplace_ratio"], m["color_cast"][0], m["color_cast"][1], m["color_cast"][2], m["brightness_ratio"], m["bad_cells"],
            sum(1 for row in m["grid"] for c in row if c), ", ".join("%s (%.0f)" % (c["cell"], c["mad"]) for c in m["worst_cells"])))
    L += ["", "Lesehilfe: SSIM/MAD roh sind durch Kamera, Tageszeit und Figurenplatzierung verfälscht; „angeglichen“ = Unity-Bild per Histogramm an die Referenz angepasst "
          "(Helligkeits-/Zeitversatz entfernt). Laplace-Verhältnis < 1: Unity unschärfer/detailärmer als Ryujinx. Farbstich = Verhältnis der Kanalmittel Unity/Referenz, "
          "bereinigt um die Gesamthelligkeit (1,00 = kein Stich). Zellen A1–H8: Spalte A–H von links, Zeile 1–8 von oben.", ""]
    L += ["## Auffälligkeiten", ""]
    notes_all = []
    for r in rep["results"]:
        if r["status"] == "verglichen":
            m = r["metrics"]
            notes = []
            if m["laplace_ratio"] < 0.6:
                notes.append("deutlich detailärmer als die Referenz (Laplace ×%.2f)" % m["laplace_ratio"])
            if max(m["color_cast"]) / max(1e-6, min(m["color_cast"])) > 1.15:
                notes.append("Farbstich R/G/B ×%.2f/%.2f/%.2f" % tuple(m["color_cast"]))
            if m["bad_cell_fraction"] > 0.35:
                notes.append("%d Zellen stark abweichend" % m["bad_cells"])
            if m["shift"] != [0, 0]:
                notes.append("Bildversatz (%d, %d) px ausgeglichen" % tuple(m["shift"]))
            if notes:
                notes_all.append("- **%s**: %s" % (r["view"], "; ".join(notes)))
    L += notes_all or ["Keine."]
    L += ["", "## Regressionen/Schwellen", ""]
    L += ["- " + p for p in rep["problems"]] or ["Keine."]
    L += ["", "## Zur manuellen/Agenten-Sichtung", "",
          "Kontaktbögen (links Referenz, Mitte Unity, rechts Differenz-Heatmap mit Rasterzellen; rot umrandet = schlechteste Zellen):", ""]
    L += ["- `%s`" % p for p in rep["contact_sheets"]] or ["- (keine Referenzen oder keine passenden Unity-Bilder)"]
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------------------------
# Shader-Cache-Zahlen
# ---------------------------------------------------------------------------------------------------------------------

def cache_report(entries, used_path=None):
    """entries: ["guest=19584:1222", ...] (Dateigröße der .toc : Zähler im Kopf). Eintragsgröße 16 Byte, Kopf 32 Byte (Ryujinx-TOC)."""
    lines = []
    counts = {}
    for e in entries:
        name, rest = e.split("=", 1)
        size, head = rest.split(":")
        derived = (int(size) - 32) // 16
        counts[name] = int(head) if int(head) > 0 else derived
        note = "" if int(head) == 0 else ("" if derived == int(head) else "  ABWEICHUNG")
        lines.append("%-14s TOC %6d Byte -> %5d Einträge (Kopfzähler %s)%s" % (name, int(size), derived, head if int(head) > 0 else "nicht belegt", note))
    if used_path and Path(used_path).is_file():
        used = len(json.loads(Path(used_path).read_text(encoding="utf-8")))
        lines.append("Unsere genutzten Shader-Varianten (%s): %d" % (Path(used_path).name, used))
        if counts.get("guest"):
            lines.append("Ryujinx-Gastshader (guest) je genutzter Variante: %.1f (guest enthält je Programm Stufen und Zustandsvarianten; kein 1:1-Vergleich)" % (counts["guest"] / float(used)))
        if counts.get("vulkan_nvidia"):
            lines.append("Ryujinx-Host-Programme (vulkan_nvidia) je genutzter Variante: %.1f" % (counts["vulkan_nvidia"] / float(used)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import")
    i.add_argument("--source", default="ryujinx", choices=sorted(SOURCES), help="ryujinx (F8-Screenshots, Zuordnung nach Reihenfolge/Name) oder recomp (Rekompilation, nur nach Name/Alias)")
    i.add_argument("--raw", nargs="+", default=None)
    i.add_argument("--dest", default=None)
    i.add_argument("--map", default=str(DEFAULT_MAP))
    i.add_argument("--offset", type=int, default=0, help="Ryujinx system_time_offset in Sekunden")
    i.add_argument("--since", default="", help="Dateien mit älterer Dateizeit ignorieren (\"YYYY-MM-DD HH:MM\", Ortszeit des Macs)")
    i.add_argument("--all-free", action="store_true", help="recomp: auch nicht zugeordnete Dateien als free_<Name> führen")
    c = sub.add_parser("compare")
    c.add_argument("--run", required=True)
    c.add_argument("--source", default="ryujinx", choices=sorted(SOURCES))
    c.add_argument("--ref", default=None)
    c.add_argument("--map", default=str(DEFAULT_MAP))
    c.add_argument("--out")
    c.add_argument("--gate", action="store_true")
    c.add_argument("--no-align", action="store_true")
    r = sub.add_parser("refs", help="zwei Referenzquellen gegeneinander (Standard: recomp gegen ryujinx)")
    r.add_argument("--a", default="recomp", choices=sorted(SOURCES))
    r.add_argument("--b", default="ryujinx", choices=sorted(SOURCES))
    r.add_argument("--map", default=str(DEFAULT_MAP))
    r.add_argument("--out")
    r.add_argument("--no-align", action="store_true")
    k = sub.add_parser("cache")
    k.add_argument("--entries", nargs="+", required=True)
    k.add_argument("--used", default=str(ROOT / "work" / "materials_all" / "used_final.json"))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "import":
            dest = a.dest or str(SOURCES[a.source])
            if a.source == "recomp":
                raws = a.raw or [str(p) for p in RECOMP_RAW]
                done, _ = import_recomp([r for r in raws if Path(r).is_dir()], dest, load_map(a.map), all_free=a.all_free)
                print("%d Datei(en) importiert." % len(done))
                return 0
            raw = (a.raw or [str(Path(dest) / "raw")])[0]
            Path(raw).mkdir(parents=True, exist_ok=True)
            since = time.mktime(time.strptime(a.since, "%Y-%m-%d %H:%M")) if a.since else None
            done, _ = import_new(raw, dest, load_map(a.map), a.offset, since=since)
            print("%d neue Datei(en) zugeordnet." % len(done))
            return 0
        if a.cmd == "compare":
            ref_dir = a.ref or str(SOURCES[a.source])
            out = a.out or (str(Path(a.run) / a.source) if a.source != "ryujinx" else None)
            rep, code = compare_run(a.run, ref_dir, load_map(a.map), out, not a.no_align, a.gate)
            print("Bericht: %s" % ((Path(out) if out else Path(a.run)) / "ref_report.md"))
            for p in rep["problems"]:
                print("SCHWELLE " + p)
            return code
        if a.cmd == "refs":
            out = a.out or str(DEFAULT_REF.parent / ("%s_vs_%s" % (a.a, a.b)))
            rep = refs_compare(SOURCES[a.a], SOURCES[a.b], load_map(a.map), out, a.a, a.b, not a.no_align)
            print("Bericht: %s" % (Path(out) / "ref_report.md"))
            return 0
        if a.cmd == "cache":
            print(cache_report(a.entries, a.used))
            return 0
    except (OSError, ValueError, KeyError) as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
