#!/usr/bin/env python3
"""Aufnahmeliste der Sichtprüfung lesen, prüfen und für die Aufnahme exportieren (scripts/visual/scenarios.json).

  visual_scenarios.py validate [--file F]                 Struktur prüfen (stabile eindeutige Namen, Folgen, Zonen/Zellen, Stunden)
  visual_scenarios.py list [--runner field|game] [--tag T] [--names a,b]    Namen, einer je Zeile
  visual_scenarios.py script FOLGE [--file F] [--out DATEI]   Eingabeskript einer Spiel-Folge (Zeilen aus scenarios.json)
  visual_scenarios.py export-field --out DATEI [--tag T] [--names a,b]  field-Szenarien mit Standardwerten als JSON {"items": [...]} für Xnu.Visual.Capture
  visual_scenarios.py sequences                            Namen der Spiel-Folgen
Exit-Code 0 = in Ordnung, 1 = Prüfung fehlgeschlagen, 2 = Aufruffehler.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "scripts" / "visual" / "scenarios.json"
FACINGS = {"up", "right", "down", "left"}
KINDS = {"field", "room", "ui"}
RUNNERS = {"field", "game"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.]*$")


def load(path=None):
    p = Path(path) if path else DEFAULT_FILE
    return json.loads(p.read_text(encoding="utf-8"))


def merged(data):
    d = data.get("defaults", {})
    out = []
    for s in data.get("scenarios", []):
        m = dict(d)
        m.update(s)
        out.append(m)
    return out


def shots_of(sequence):
    return [ln.split()[1] for ln in sequence.get("lines", []) if ln.split() and ln.split()[0] == "shot" and len(ln.split()) > 1]


def validate(data):
    errors = []
    names = set()
    seqs = data.get("sequences", {})
    for sc in merged(data):
        n = sc.get("name", "")
        if not NAME_RE.match(n):
            errors.append("Name ungültig: %r (Kleinbuchstaben, Ziffern, _ und .)" % n)
        if n in names:
            errors.append("Name doppelt: " + n)
        names.add(n)
        runner = sc.get("runner")
        if runner not in RUNNERS:
            errors.append("%s: runner %r unbekannt" % (n, runner))
        if sc.get("kind") not in KINDS:
            errors.append("%s: kind %r unbekannt" % (n, sc.get("kind")))
        if (sc.get("width"), sc.get("height")) != (1280, 720):
            errors.append("%s: Auflösung %sx%s (erwartet 1280x720)" % (n, sc.get("width"), sc.get("height")))
        if runner == "field":
            if not isinstance(sc.get("zone"), int) or sc["zone"] < 0:
                errors.append("%s: zone fehlt" % n)
            cell = sc.get("cell")
            if cell is None and sc.get("locator") is None:
                errors.append("%s: cell oder locator nötig" % n)
            if cell is not None and not (isinstance(cell, list) and len(cell) == 2 and all(isinstance(v, int) for v in cell)):
                errors.append("%s: cell muss [x, y] sein" % n)
            if sc.get("facing") not in FACINGS:
                errors.append("%s: facing %r ungültig" % (n, sc.get("facing")))
            if not (0 <= float(sc.get("hour", 12)) <= 24):
                errors.append("%s: hour außerhalb 0..24" % n)
            if int(sc.get("settle_frames", 0)) < 1:
                errors.append("%s: settle_frames < 1" % n)
        elif runner == "game":
            seq = sc.get("sequence")
            if seq not in seqs:
                errors.append("%s: Folge %r fehlt" % (n, seq))
            elif n not in shots_of(seqs[seq]):
                errors.append("%s: kein 'shot %s' in Folge %s" % (n, n, seq))
    for sname, seq in seqs.items():
        for shot in shots_of(seq):
            if shot not in names:
                errors.append("Folge %s: shot %s ohne Szenario" % (sname, shot))
        lines = seq.get("lines", [])
        if not lines or lines[-1].split()[0] != "quit":
            errors.append("Folge %s endet nicht mit quit" % sname)
    return errors


def select(data, runner=None, tag=None, names=None):
    out = []
    for sc in merged(data):
        if runner and sc["runner"] != runner:
            continue
        if tag and tag not in sc.get("tags", []):
            continue
        if names and sc["name"] not in names:
            continue
        out.append(sc)
    return out


def ref_hours(ref_map_path, assignments_path):
    """Spielstunde der Ryujinx-Referenzen je Unity-Szenario (Name -> Stunde), damit Unity dieselbe Tageszeit rendert."""
    ref_map = json.loads(Path(ref_map_path).read_text(encoding="utf-8"))
    assign = json.loads(Path(assignments_path).read_text(encoding="utf-8")).get("views", {})
    out = {}
    for v in ref_map.get("views", []):
        h = assign.get(v["view"], {}).get("game_hour")
        if h is not None:
            for n in v.get("unity", []):
                out.setdefault(n, h)
    return out


def export_field(data, tag=None, names=None, hours=None):
    items = []
    for sc in select(data, "field", tag, names):
        hour = float((hours or {}).get(sc["name"], sc["hour"]))
        items.append({
            "name": sc["name"], "zone": sc["zone"],
            "hasCell": sc.get("cell") is not None, "cellX": sc["cell"][0] if sc.get("cell") else 0, "cellY": sc["cell"][1] if sc.get("cell") else 0,
            "locator": sc["locator"] if sc.get("locator") is not None else 0,
            "facing": sc["facing"], "hour": hour, "settleFrames": int(sc["settle_frames"]),
            "width": int(sc["width"]), "height": int(sc["height"]),
        })
    return {"version": 1, "items": items}


def mark_requested(run_dir, names, mode=""):
    """Namen in <run>/capture.json unter "requested" eintragen (Vereinigung): nur diese gelten beim Vergleich als erwartet."""
    p = Path(run_dir) / "capture.json"
    cap = {}
    if p.is_file():
        try:
            cap = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            cap = {}
    req = list(cap.get("requested", []))
    for n in names:
        if n not in req:
            req.append(n)
    cap["requested"] = req
    if mode:
        cap["mode"] = mode
    p.write_text(json.dumps(cap, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "list", "script", "export-field", "sequences", "shots", "mark-requested"):
        p = sub.add_parser(name)
        p.add_argument("--file", default=str(DEFAULT_FILE))
        if name in ("list", "export-field", "sequences", "mark-requested"):
            if name in ("list", "export-field"):
                p.add_argument("--tag")
            p.add_argument("--names")
        if name == "shots":
            p.add_argument("--sequence", required=True)
        if name == "mark-requested":
            p.add_argument("--run", required=True)
            p.add_argument("--mode", default="")
        if name == "list":
            p.add_argument("--runner", choices=sorted(RUNNERS))
        if name == "script":
            p.add_argument("sequence")
        if name in ("script", "export-field"):
            p.add_argument("--out")
        if name == "export-field":
            p.add_argument("--ref-hours", help="assignments.json der Ryujinx-Referenzen: Szenarien der Referenzansichten mit deren Spielstunde rendern")
            p.add_argument("--ref-map", default=str(ROOT / "scripts" / "visual" / "ref_map.json"))
    a = ap.parse_args(argv)
    try:
        data = load(a.file)
    except (OSError, ValueError) as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 2
    names = set(a.names.split(",")) if getattr(a, "names", None) else None
    if a.cmd == "validate":
        errs = validate(data)
        for e in errs:
            print("FEHLER " + e)
        print("%d Szenarien, %d Folgen, %d Fehler" % (len(data.get("scenarios", [])), len(data.get("sequences", {})), len(errs)))
        return 1 if errs else 0
    if a.cmd == "list":
        for sc in select(data, a.runner, a.tag, names):
            print(sc["name"])
        return 0
    if a.cmd == "sequences":
        for n, seq in data.get("sequences", {}).items():
            if names is None or names & set(shots_of(seq)):
                print(n)
        return 0
    if a.cmd == "shots":
        seq = data.get("sequences", {}).get(a.sequence)
        if seq is None:
            print("Folge %r unbekannt" % a.sequence, file=sys.stderr)
            return 2
        for s in shots_of(seq):
            print(s)
        return 0
    if a.cmd == "mark-requested":
        return mark_requested(a.run, [n for n in (a.names or "").replace(" ", ",").split(",") if n], a.mode)
    if a.cmd == "script":
        seq = data.get("sequences", {}).get(a.sequence)
        if seq is None:
            print("Folge %r unbekannt" % a.sequence, file=sys.stderr)
            return 2
        text = "\n".join(["# Aus scripts/visual/scenarios.json (Folge %s), nicht von Hand ändern" % a.sequence] + seq["lines"]) + "\n"
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if a.cmd == "export-field":
        hours = None
        if a.ref_hours:
            hours = ref_hours(a.ref_map, a.ref_hours)
        text = json.dumps(export_field(data, a.tag, names, hours), indent=1, ensure_ascii=False)
        if not a.out:
            print(text)
        else:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(text, encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
