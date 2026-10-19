#!/usr/bin/env python3
"""QA-Harness der rekompilierten BDSP-Laufzeit (siehe qa_run.sh und docs/recomp-qa.md).

Startet work/recomp/qa/bin/bdsp_boot headless mit einem Eingabeskript aus scenarios/<name>.txt, sammelt Log, Screenshots, RSS und
Bildrate, erkennt Abstürze (Exit-Code, Signal, FATAL, letzter Gast-Stack mit IL2CPP-Namen), Hänger (Bildstillstand, Thread-Zustände)
und unbehandelte Dienste/SVCs, und schreibt <lauf>/report.md und report.json. Nur Standardbibliothek, numpy und Pillow; kein Netz.

Szenariodatei (eine Anweisung je Zeile, # beginnt einen Kommentar):
  desc <Text>                         Beschreibung
  timeout <s> | shots <Bilder> | il2sym on|off | save base|none | env KEY=WERT     Einstellungen (gelten für die aktuelle Phase)
  include <szenario>                  Eingaben, Prüfungen (und mark-Zeilen) eines anderen Szenarios an dieser Stelle einfügen
  phase                               neuer Prozess (z. B. Spiel neu starten); gleicher Spielstandordner, Zeit beginnt bei 0
  <Sekunde> <TASTE[+TASTE]> [Dauer]   Tastendruck (A B X Y L R ZL ZR PLUS MINUS UP DOWN LEFT RIGHT LSTICK RSTICK), Dauer Standard 0,3 s
  anchor <Name> <IL2-Teil>            Bezugszeit = erster Aufruf der Spielmethode; danach "<Name>+<Sekunden>" statt <Sekunde> (ereignisgesteuert, unabhängig von der Ladezeit)
  cycle <von> <Spanne> <Dauer> T1,T2,..  nacheinander jeweils <Dauer> s halten, im Kreis, <Spanne> Sekunden lang (<von> auch "Anker+s")
  every <von> <Spanne> <Periode> <TASTE> [Dauer]   Taste periodisch
  mark <Teilzeichenkette>             Zeitpunkt des ersten Auftretens der IL2CPP-Methode in der Zeitleiste ausgeben
  expect il2 <Teil> | il2-not <Teil> | log <regex> | log-not <regex> | fps-min <Wert> [ab <s>] | rss-max <MiB> | frames <n>
         save-valid | save-changed | save-unchanged | save-time-gt <Sekunden>
"""
import argparse
import bisect
import fcntl
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
QA = ROOT / "work" / "recomp" / "qa"
SCN = Path(__file__).resolve().parent / "scenarios"
KEYS = {"NONE", "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "UP", "DOWN", "LEFT", "RIGHT", "LSTICK", "RSTICK"}
MIN_FREE_GB = 15


# ---------------------------------------------------------------------------------------------------------------------
# Szenarien
# ---------------------------------------------------------------------------------------------------------------------

def new_phase():
    return {"inputs": [], "anchors": {}, "timeout": 150, "shots": 135, "il2sym": True, "save": "base", "env": {}, "finish": 0}


def parse_scenario(name, depth=0):
    path = SCN / (name + ".txt")
    if not path.is_file():
        raise SystemExit("Szenario %s nicht gefunden (%s)" % (name, path))
    sc = {"name": name, "desc": "", "phases": [new_phase()], "expects": [], "marks": []}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        tok = line.split()
        key = tok[0]
        ph = sc["phases"][-1]
        try:
            if key == "desc":
                sc["desc"] = line[4:].strip()
            elif key == "timeout":
                ph["timeout"] = int(tok[1])
            elif key == "finish":
                ph["finish"] = float(tok[1])
            elif key == "shots":
                ph["shots"] = int(tok[1])
            elif key == "il2sym":
                ph["il2sym"] = tok[1] == "on"
            elif key == "save":
                ph["save"] = tok[1]
            elif key == "env":
                k, v = tok[1].split("=", 1)
                ph["env"][k] = v
            elif key == "phase":
                sc["phases"].append(new_phase())
            elif key == "anchor":   # anchor <Name> <IL2CPP-Teilzeichenkette>: Zeit des ersten Aufrufs, Bezug für "<Name>+<Sekunden>"
                ph["anchors"][tok[1]] = " ".join(tok[2:])
            elif key == "include":
                if depth > 3:
                    raise ValueError("include zu tief")
                inc = parse_scenario(tok[1], depth + 1)
                ph["inputs"] += inc["phases"][0]["inputs"]
                ph["anchors"].update(inc["phases"][0]["anchors"])
                sc["expects"] += inc["expects"]
                sc["marks"] += inc["marks"]
            elif key == "mark":
                sc["marks"].append(line[5:].strip())
            elif key == "expect":
                sc["expects"].append(tok[1:])
            elif key == "cycle":
                a0, t0 = tspec(tok[1])
                t1, dur, seq = float(tok[2]), float(tok[3]), tok[4].split(",")
                t, i = t0, 0
                while t + dur <= t0 + t1:
                    ph["inputs"].append((a0, t, seq[i % len(seq)], dur))
                    t += dur
                    i += 1
            elif key == "every":
                a0, t0 = tspec(tok[1])
                span, per = float(tok[2]), float(tok[3])
                dur = float(tok[5]) if len(tok) > 5 else 0.3
                t = t0
                while t < t0 + span:
                    ph["inputs"].append((a0, t, tok[4], dur))
                    t += per
            elif key[0].isdigit() or "+" in key:
                a0, t = tspec(tok[0])
                keys = tok[1]
                dur = float(tok[2]) if len(tok) > 2 else 0.3
                for k in keys.split("+"):
                    if k not in KEYS:
                        raise ValueError("unbekannte Taste " + k)
                ph["inputs"].append((a0, t, keys, dur))
            else:
                raise ValueError("unbekannte Anweisung " + key)
        except (IndexError, ValueError) as exc:
            raise SystemExit("%s:%d: %s (%s)" % (path.name, n, exc, raw.strip()))
    for ph in sc["phases"]:
        for a0, _, _, _ in ph["inputs"]:
            if a0 and a0 not in ph["anchors"]:
                raise SystemExit("%s: Anker %s nicht definiert" % (path.name, a0))
        ph["inputs"].sort(key=lambda x: (x[0] or "", x[1]))
    return sc


def tspec(s):
    """'12.5' -> (None, 12.5); 'boot+6' -> ('boot', 6.0): absolute Sekunde ab Prozessstart oder Sekunde nach einem Anker."""
    if "+" in s and not s[0].isdigit():
        a, _, off = s.partition("+")
        return a, float(off)
    return None, float(s)


def input_string(inputs):
    return ",".join("%g:%s:%g" % (t, k, d) for a, t, k, d in inputs if not a and k != "NONE")


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------

def sha256(p, n=12):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def free_gb():
    return shutil.disk_usage(ROOT).free / 2**30


_il2 = None


def il2_lookup(addr):
    global _il2
    if _il2 is None:
        _il2 = ([], [])
        p = ROOT / "work/recomp/il2sym.tsv"
        if p.is_file():
            pairs = []
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                a, _, n = line.partition("\t")
                try:
                    pairs.append((int(a, 16), n))
                except ValueError:
                    pass
            pairs.sort()
            _il2 = ([a for a, _ in pairs], [n for _, n in pairs])
    addrs, names = _il2
    i = bisect.bisect_right(addrs, addr) - 1
    if i >= 0 and addr - addrs[i] < 0x4000:
        return "%s+%#x" % (names[i], addr - addrs[i])
    return None


def sym_line(line):
    def rep(m):
        s = il2_lookup(int(m.group(1), 16))
        return m.group(1) + (" <%s>" % s if s else "")
    return re.sub(r"\b(70[0-9a-f]{8})\b(?! <)", rep, line)


def spark(values, width=60):
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    if len(values) > width:
        step = len(values) / width
        values = [sum(values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]) / max(1, len(values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)])) for i in range(width)]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return blocks[3] * len(values)
    return "".join(blocks[min(7, int((v - lo) / (hi - lo) * 8))] for v in values)


def median(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


# ---------------------------------------------------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------------------------------------------------

PAD_BITS = {n: i for i, n in enumerate(["A", "B", "X", "Y", "LSTICK", "RSTICK", "L", "R", "ZL", "ZR", "PLUS", "MINUS", "LEFT", "UP", "RIGHT", "DOWN"])}


def keys_mask(keys):
    m = 0
    for k in keys.split("+"):
        m |= (1 << PAD_BITS[k]) if k in PAD_BITS else 0   # NONE: keine Taste (nur Zeitmarke für finish)
    return m


def feeder(log_path, ph, ctl_path, stop, found, proc=None):
    """Ereignisgesteuerte Eingaben: wartet auf den ersten Aufruf der Anker-Methoden im Log und schreibt die Tastenmaske in die Steuerdatei
    (BDSP_INPUT_CTL, von der Laufzeit je Abfrage gelesen)."""
    steps = [(a, t, keys_mask(k), d) for a, t, k, d in ph["inputs"] if a]
    if not steps:
        return
    finished = False
    fd = os.open(ctl_path, os.O_WRONLY)
    last = 0
    rest = b""
    f = None
    while not stop.is_set():
        if f is None and os.path.exists(log_path):
            f = open(log_path, "rb")
        if f is not None:
            chunk = f.read(1 << 20)
            if chunk:
                lines = (rest + chunk).split(b"\n")
                rest = lines.pop()
                for ln in lines:
                    if b"[il2]" in ln:
                        s = ln.decode("utf-8", "replace")
                        for a, sub in ph["anchors"].items():
                            if a not in found and sub in s:
                                found[a] = time.time()
        now = time.time()
        mask = 0
        for a, t, m, d in steps:
            if a in found and found[a] + t <= now < found[a] + t + d:
                mask |= m
        if mask != last:
            os.pwrite(fd, b"%016x\n" % mask, 0)
            last = mask
        # finish <s>: nach der letzten ereignisgesteuerten Eingabe so lange weiterlaufen, dann beenden (SIGINT: die Laufzeit schreibt den Bericht);
        # das Zeitlimit bleibt nur Sicherung. So hängt das Ende eines Laufs nicht von der Ladezeit (Fremdlast) ab.
        if ph.get("finish") and proc is not None and not finished:
            ends = [found[a] + t + d for a, t, m, d in steps if a in found]
            if len(ends) == len(steps) and now > max(ends) + ph["finish"]:
                finished = True
                found["_ende"] = time.time()
                try:
                    os.kill(proc.pid, signal.SIGINT)
                except OSError:
                    pass
        time.sleep(0.02)
    os.pwrite(fd, b"%016x\n" % 0, 0)
    os.close(fd)


def run_phase(args, sc, idx, ph, run_dir):
    tag = "p%d" % (idx + 1)
    log_path = run_dir / ("log_%s.txt" % tag)
    shots = run_dir / ("shots_%s" % tag)
    ctl = run_dir / ("input_ctl_%s.txt" % tag)
    ctl.write_text("%016x\n" % 0)
    inp = input_string(ph["inputs"])
    timeout = args.timeout or ph["timeout"]
    env = dict(os.environ)
    env.update({"BDSP_IMG": args.img, "BDSP_SHOT_DIR": str(shots), "BDSP_TRACE_INPUT": "1", "BDSP_INPUT_CTL": str(ctl), "BDSP_BT": "1", "BDSP_TRACE_SYNC": "300",
                "BDSP_DUMP": "7004f91f60:24"})   # Gastspeicher beim Ende ausgeben: Ereignis des Hauptthreads (Hänger-Analyse)
    if ph["il2sym"] and not args.no_il2sym and (ROOT / "work/recomp/il2sym.tsv").is_file():
        env["BDSP_IL2SYM"] = "work/recomp/il2sym.tsv"
    env.update(ph["env"])
    cmd = [args.bin, "--headless", "--timeout", str(timeout), "--save", str(run_dir / "save")]
    if ph["shots"]:
        cmd += ["--screenshot-after", str(ph["shots"])]
    if inp:
        if len(inp) > 3900 or len(ph["inputs"]) > 250:
            f = run_dir / ("input_%s.txt" % tag)
            f.write_text(inp, encoding="utf-8")
            inp = "@" + str(f)
        cmd += ["--input-script", inp]
    samples = []
    found = {}
    stop = threading.Event()
    t0 = time.time()
    th = None
    with open(log_path, "wb") as lf:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, env=env)
        if any(a for a, _, _, _ in ph["inputs"]):
            th = threading.Thread(target=feeder, args=(log_path, ph, str(ctl), stop, found, proc), daemon=True)
            th.start()
        killed = None
        last_sample = 0.0
        while proc.poll() is None:
            time.sleep(0.5)
            el = time.time() - t0
            if el - last_sample >= 2.0:
                last_sample = el
                try:
                    out = subprocess.run(["ps", "-o", "rss=,%cpu=", "-p", str(proc.pid)], capture_output=True, text=True, timeout=5).stdout.split()
                    if len(out) >= 2:
                        samples.append((round(el, 1), int(out[0]) // 1024, float(out[1]), round(os.getloadavg()[0], 1)))
                except (subprocess.SubprocessError, ValueError):
                    pass
                if not killed and el > timeout + 60:
                    killed = "kein Ende 60 s nach dem Zeitlimit: beendet"
                    proc.terminate()
                    time.sleep(3)
                    if proc.poll() is None:
                        proc.kill()
                elif not killed and free_gb() < 10:
                    killed = "Platte fast voll (%.1f GB): abgebrochen" % free_gb()
                    proc.terminate()
        proc.wait()
    stop.set()
    if th:
        th.join(2)
    rc = proc.returncode
    return {"tag": tag, "cmd": " ".join(cmd), "log": str(log_path), "shots": str(shots), "returncode": rc, "wall": round(time.time() - t0, 1),
            "samples": samples, "killed": killed, "input_steps": len(ph["inputs"]), "timeout": timeout,
            "anchors": {k: round(v - t0, 1) for k, v in found.items()}, "anchors_missing": [a for a in ph["anchors"] if a not in found and any(x[0] == a for x in ph["inputs"])]}



# ---------------------------------------------------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------------------------------------------------

METAL = re.compile(r"\[metal\] t=([\d.]+) frame (\d+) ([\d.]+) fps max (\d+)ms level (\S+) \((\d+) draws, (\d+) skipped, (\d+) passes, (\d+) dispatches")
IL2 = re.compile(r"\[il2\]\s+(\d+) ms t(\d+) (.*)")
NOISE = re.compile(r"FATAL|unimplemented|nicht umgesetzt|nicht implementiert|unsupported|not supported|not implemented|fehlt|failed|pipeline|Fehler|error|WARN|mismatch|invalid|ungültig|abort",
                   re.I)
NOISE_SKIP = re.compile(r"^\[metal\] t=|^\[il2\]|^\[kernel\] CreateThread|^\[copy\]|^\[input\]|^\[texdump\]|^  Thread \d+:")


def norm_msg(s):
    s = re.sub(r"0x[0-9a-fA-F]+|\b[0-9a-f]{7,}\b|-?\d+(\.\d+)?", "#", s)
    return s[:160]


def analyze_log(path, ph_cfg):
    text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).is_file() else ""
    lines = text.splitlines()
    r = {"lines": len(lines), "complete": False, "result": "", "il2_first": {}, "il2_count": 0, "fps": [], "fatal": [], "signal": None,
         "host_bt": [], "guest_bt": [], "guest_regs": "", "unimpl_ipc": {}, "unimpl_svc": [], "nvn_missing": [], "noise": {}, "threads": {},
         "svc_total": 0, "ipc_total": 0, "romfs": "", "rss_final": "", "services": {}, "frames_presented": 0, "last_il2": [], "movie": [], "inputs": 0,
         "thread_detail": [], "sync_tail": [], "dumps": []}
    section = None
    noise = {}
    last_il2 = []
    for i, line in enumerate(lines):
        m = METAL.match(line)
        if m:
            r["fps"].append({"t": float(m.group(1)), "frame": int(m.group(2)), "fps": float(m.group(3)), "max_ms": int(m.group(4)), "level": m.group(5),
                             "draws": int(m.group(6)), "skipped": int(m.group(7)), "passes": int(m.group(8)), "dispatch": int(m.group(9))})
            continue
        m = IL2.match(line)
        if m:
            r["il2_count"] += 1
            name = m.group(3).strip()
            if name not in r["il2_first"]:
                r["il2_first"][name] = int(m.group(1))
            last_il2.append("%s ms t%s %s" % (m.group(1), m.group(2), name))
            if len(last_il2) > 40:
                last_il2.pop(0)
            continue
        if line.startswith("[input] Tasten"):
            r["inputs"] += 1
        if line.startswith("==== ERGEBNIS"):
            r["complete"] = True
            r["result"] = line.strip("= ").replace("ERGEBNIS: ", "")
            section = "result"
            continue
        if line.startswith("dump "):
            r["dumps"].append(line.strip())
        if line.startswith("FATAL"):
            r["fatal"].append(line)
        if line.startswith("*** Signal"):
            r["signal"] = line
            section = "hostbt"
            continue
        if section == "hostbt":
            if line.startswith("Gast:"):
                section = "regs"
            elif line.startswith("  "):
                r["host_bt"].append(line.strip())
                continue
        if line.startswith("Gast-Rückverfolgung"):
            section = "guestbt"
            continue
        if section == "guestbt":
            if line.startswith("  lr ") or re.match(r"\s+#\d+ ", line):
                r["guest_bt"].append(line.strip())
                continue
            section = None
        if line.startswith("[ipc]") and "nicht umgesetzt" in line:
            mm = re.match(r"\[ipc\] (\S+) Befehl (\d+) nicht umgesetzt", line)
            if mm:
                r["unimpl_ipc"].setdefault("%s:%s" % (mm.group(1), mm.group(2)), 0)
        mm = re.match(r"\s+fehlt: (\S+) Befehl (\d+) \((\d+)x\)", line)
        if mm:
            r["unimpl_ipc"]["%s:%s" % (mm.group(1), mm.group(2))] = int(mm.group(3))
        if "nicht umgesetzte SVC" in line:
            r["unimpl_svc"].append(line)
        if section == "result":
            if line.startswith("  Thread "):
                mm = re.search(r"Thread (\d+): .*?, (läuft|beendet), letzte SVC (\S+) \((\w+)\), (\d+) SVCs, (\d+) IPC", line)
                if mm:
                    key = "%s/%s" % (mm.group(2), mm.group(4))
                    r["threads"][key] = r["threads"].get(key, 0) + 1
                    r["thread_detail"].append({"id": int(mm.group(1)), "state": mm.group(2), "svc": mm.group(4), "svcs": int(mm.group(5)), "ipc": int(mm.group(6)),
                                               "wait": "", "mutex": "", "bt": []})
            elif line.startswith("      wartet:") and r["thread_detail"]:
                r["thread_detail"][-1]["wait"] = line.strip()
            elif line.startswith("      Mutex ") and r["thread_detail"]:
                r["thread_detail"][-1]["mutex"] = line.strip()
            elif re.match(r"      (lr|#\d+) ", line) and r["thread_detail"]:
                r["thread_detail"][-1]["bt"].append(line.strip())
            if line.startswith("Synchronisation, letzte Ereignisse:"):
                section = "sync"
                continue
            mm = re.match(r"\s+(\S.*\S|\S)$", line)
            if line.startswith("NVN-Funktionen ohne Host-Umsetzung"):
                section = "nvnmiss"
                continue
        if section == "sync":
            if line.startswith("  T"):
                r["sync_tail"].append(line.strip())
                continue
            section = "result"
        if section == "nvnmiss":
            if line.startswith("  ") and "(keine)" not in line:
                r["nvn_missing"].append(line.strip())
                continue
            section = "result"
        if line.startswith("NVN: "):
            mm = re.match(r"NVN: (\d+) Bilder", line)
            if mm:
                r["frames_presented"] = int(mm.group(1))
        mm = re.match(r"IPC-Anfragen gesamt (\d+)", line)
        if mm:
            r["ipc_total"] = int(mm.group(1))
        mm = re.match(r"\d+ verschiedene SVCs, (\d+) Aufrufe", line)
        if mm:
            r["svc_total"] = int(mm.group(1))
        if line.startswith("RomFS-Lesezugriffe"):
            r["romfs"] = line
        if line.startswith("RSS jetzt"):
            r["rss_final"] = line
        if line.startswith("Dienste/Befehle (Anzahl):"):
            for tok in line.split(":", 1)[1].split():
                mm = re.match(r"(.+)\((\d+)\)$", tok)
                if mm:
                    r["services"][mm.group(1)] = int(mm.group(2))
        if line.startswith("[movie]"):
            r["movie"].append(line)
        if NOISE.search(line) and not NOISE_SKIP.match(line) and not line.startswith("  fehlt:") and not line.startswith("davon mit Standardantwort"):
            k = norm_msg(line)
            noise[k] = noise.get(k, 0) + 1
            if noise[k] == 1:
                r["noise_example_" + str(len(noise))] = line[:200]
    r["noise"] = noise
    r["last_il2"] = last_il2[-15:]
    return r


def fps_stats(series, since=0.0):
    v = [e["fps"] for e in series if e["t"] >= since]
    if not v:
        return {}
    s = sorted(v)
    return {"n": len(v), "mean": round(sum(v) / len(v), 1), "median": round(median(v), 1), "min": round(s[0], 1), "p5": round(s[max(0, int(len(s) * 0.05))], 1),
            "max": round(s[-1], 1)}


def detect_stalls(series, end_secs, min_gap=12.0):
    stalls = []
    for a, b in zip(series, series[1:]):
        if b["t"] - a["t"] > min_gap or (b["frame"] == a["frame"]):
            stalls.append({"von_t": a["t"], "bis_t": b["t"], "frame": a["frame"]})
    if series and end_secs and end_secs - series[-1]["t"] > min_gap + 3:
        stalls.append({"von_t": series[-1]["t"], "bis_t": end_secs, "frame": series[-1]["frame"], "ende": True})
    return stalls


def shot_infos(shots_dir, series):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        sys.path.append(str(ROOT / "tools" / "pydeps"))
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            return [], None
    files = sorted(Path(shots_dir).glob("frame_*.png"))
    frames = [e["frame"] for e in series]
    ts = [e["t"] for e in series]
    infos = []
    prev = None
    for f in files:
        fr = int(f.stem.split("_")[1])
        t = None
        if frames and frames[0] <= fr <= frames[-1]:
            t = round(float(np.interp(fr, frames, ts)), 1)
        try:
            im = Image.open(f).convert("RGB")
        except OSError:
            continue
        small = np.asarray(im.resize((160, 90))).astype(np.int16)
        d = {"file": f.name, "frame": fr, "t": t, "mean": round(float(small.mean()), 1), "black": bool(small.mean() < 4),
             "same_as_prev": bool(prev is not None and np.abs(small - prev).mean() < 0.3)}
        prev = small
        infos.append(d)
    return infos, (files, Image)


def contact_sheet(files, infos, out_prefix, cols=4, rows=4, thumb=(400, 225)):
    from PIL import Image, ImageDraw
    per = cols * rows
    sheets = []
    for s in range(0, len(files), per):
        part = files[s:s + per]
        im = Image.new("RGB", (cols * thumb[0], ((len(part) + cols - 1) // cols) * thumb[1]), (24, 24, 24))
        dr = ImageDraw.Draw(im)
        for i, f in enumerate(part):
            try:
                t = Image.open(f).convert("RGB").resize(thumb)
            except OSError:
                continue
            x, y = (i % cols) * thumb[0], (i // cols) * thumb[1]
            im.paste(t, (x, y))
            info = infos[s + i]
            dr.rectangle([x, y, x + 150, y + 12], fill=(0, 0, 0))
            dr.text((x + 2, y), "%s  t=%s" % (f.stem.replace("frame_", "F"), info["t"]), fill=(255, 255, 0))
        p = "%s_%02d.png" % (out_prefix, s // per + 1)
        im.save(p)
        sheets.append(p)
    return sheets


def check_save(run_dir, base_dir):
    sd = run_dir / "save" / "save_1" / "SaveData.bin"
    b = base_dir / "save_1" / "SaveData.bin"
    r = {"exists": sd.is_file()}
    if not sd.is_file():
        return r
    r["sha"] = sha256(sd)
    r["base_sha"] = sha256(b) if b.is_file() else None
    r["changed"] = r["sha"] != r["base_sha"]
    r["size"] = sd.stat().st_size
    out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/bdsp_save.py"), "check", str(sd)], capture_output=True, text=True).stdout
    r["check"] = out.strip().replace("\n", " | ")
    r["valid"] = "Hash gültig: ja" in out and "passt: ja" in out
    r["mtime"] = time.strftime("%H:%M:%S", time.localtime(sd.stat().st_mtime))
    return r


def evaluate(sc, phases, run_dir, save_info, args):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    crash = False
    for p in phases:
        a = p["analysis"]
        rc = p["returncode"]
        reason = []
        if a["signal"]:
            reason.append(a["signal"].strip("* "))
        if a["fatal"]:
            reason.append(a["fatal"][0][:120])
        if rc not in (0, None) and not reason:
            reason.append("Exit-Code %s%s" % (rc, " (Signal %s)" % signal.Signals(-rc).name if rc is not None and rc < 0 else ""))
        if p["killed"]:
            reason.append(p["killed"])
        if not a["complete"] and not reason:
            reason.append("kein Ergebnisbericht (Prozess ohne Abschlussbericht beendet)")
        if reason:
            crash = True
        add("Phase %s ohne Absturz/FATAL" % p["tag"], not reason, "; ".join(reason) or "Exit-Code 0, %s" % a["result"])
        stalls = p.get("stalls", [])
        add("Phase %s ohne Bildstillstand (> 12 s)" % p["tag"], not stalls, "; ".join("t=%.0f..%.0f bei Bild %d" % (s["von_t"], s["bis_t"], s["frame"]) for s in stalls[:4]))
        if p.get("anchors_missing"):
            add("Phase %s: alle Eingabe-Anker erreicht" % p["tag"], False, "nicht erreicht: " + ", ".join(p["anchors_missing"]))
        if a["unimpl_svc"]:
            add("Phase %s: nicht umgesetzte SVC" % p["tag"], False, a["unimpl_svc"][0][:150])
        if a["nvn_missing"]:
            add("Phase %s: NVN-Funktionen ohne Umsetzung" % p["tag"], False, ", ".join(a["nvn_missing"][:5]))
    il2_all = {}
    for p in phases:
        for k, v in p["analysis"]["il2_first"].items():
            il2_all.setdefault(k, v)
    texts = "\n".join(Path(p["log"]).read_text(encoding="utf-8", errors="replace") for p in phases)
    for e in sc["expects"]:
        kind = e[0]
        arg = " ".join(e[1:])
        try:
            if kind == "il2":
                hit = [k for k in il2_all if arg in k]
                add("erwartet IL2CPP-Aufruf %s" % arg, hit, "erstmals bei %.1f s" % (min(il2_all[k] for k in hit) / 1000) if hit else "nicht aufgetreten")
            elif kind == "il2-not":
                hit = [k for k in il2_all if arg in k]
                add("erwartet kein IL2CPP-Aufruf %s" % arg, not hit, hit[0] if hit else "")
            elif kind == "log":
                add("erwartet Logzeile /%s/" % arg, re.search(arg, texts, re.M), "")
            elif kind == "log-not":
                m = re.search(arg, texts, re.M)
                add("erwartet keine Logzeile /%s/" % arg, not m, m.group(0)[:100] if m else "")
            elif kind == "fps-min":
                since = float(e[3]) if len(e) > 3 and e[2] == "ab" else 0.0
                st = fps_stats([x for p in phases for x in p["analysis"]["fps"]], since)
                add("Bildrate (Median) >= %s ab %g s" % (e[1], since), st and st["median"] >= float(e[1]), "Median %s, p5 %s" % (st.get("median"), st.get("p5")))
            elif kind == "rss-max":
                mx = max([s[1] for p in phases for s in p["samples"]] or [0])
                add("RSS-Spitze <= %s MiB" % e[1], mx <= float(e[1]), "gemessen %d MiB" % mx)
            elif kind == "frames":
                n = sum(p["analysis"]["frames_presented"] for p in phases)
                add("mindestens %s Bilder präsentiert" % e[1], n >= int(e[1]), "gemessen %d" % n)
            elif kind == "save-valid":
                add("Spielstand gültig (bdsp_save.py check)", save_info.get("valid"), save_info.get("check", ""))
            elif kind == "save-changed":
                add("Spielstand wurde geschrieben (Hash geändert)", save_info.get("changed"), "%s -> %s" % (save_info.get("base_sha"), save_info.get("sha")))
            elif kind == "save-unchanged":
                add("Spielstand unverändert", save_info.get("exists") and not save_info.get("changed"), "%s" % save_info.get("sha"))
        except (IndexError, ValueError) as exc:
            add("Prüfung %s fehlerhaft definiert" % " ".join(e), False, str(exc))
    return checks, crash


def render_md(rep):
    L = []
    w = L.append
    w("# QA-Lauf %s\n" % rep["run"])
    w("Szenario **%s**: %s  " % (rep["scenario"], rep["desc"]))
    w("Start %s, Dauer %.0f s, Binärdatei `%s` (sha256 %s…), Bild-Ordner `%s`  " % (rep["started"], rep["wall"], rep["bin"], rep["bin_sha"], rep["img"]))
    w("\n**Ergebnis: %s** (%d von %d Prüfungen bestanden)\n" % ("BESTANDEN" if rep["ok"] else "FEHLER", sum(c["ok"] for c in rep["checks"]), len(rep["checks"])))
    w("| Prüfung | Ergebnis | Angabe |\n|---|---|---|")
    for c in rep["checks"]:
        w("| %s | %s | %s |" % (c["name"], "ok" if c["ok"] else "**FEHLER**", c["detail"].replace("|", "/")))
    for p in rep["phases"]:
        a = p["analysis"]
        w("\n## Phase %s (Zeitlimit %d s, %d Eingabeschritte, Exit-Code %s)\n" % (p["tag"], p["timeout"], p["input_steps"], p["returncode"]))
        w("- Ergebnis laut Laufzeit: %s" % (a["result"] or "(kein Ergebnisbericht)"))
        w("- Bilder präsentiert: %d, IL2CPP-Methoden (erste Aufrufe): %d, IPC-Anfragen: %d, SVC-Aufrufe: %d, Tastenänderungen im Gast: %d" % (a["frames_presented"], len(a["il2_first"]), a["ipc_total"], a["svc_total"], a["inputs"]))
        if a["romfs"]:
            w("- %s" % a["romfs"])
        st = p.get("fps_stats")
        if st:
            w("- Bildrate: Median %s, Mittel %s, p5 %s, Minimum %s, Maximum %s (n=%d Intervalle à 2 s)" % (st["median"], st["mean"], st["p5"], st["min"], st["max"], st["n"]))
            w("  - Verlauf `%s`" % spark([e["fps"] for e in a["fps"]]))
        if p["samples"]:
            rs = [s[1] for s in p["samples"]]
            w("- RSS (Host, alle 2 s): Spitze %d MiB, Median %d MiB, zuletzt %d MiB; CPU des Prozesses Median %.0f %%; Last des Macs (Load 1 min) Median %.0f, Spitze %.0f%s" % (
                max(rs), median(rs), rs[-1], median([s[2] for s in p["samples"]]), median([s[3] for s in p["samples"]]), max(s[3] for s in p["samples"]),
                " **(hohe Fremdlast: Bildraten nicht aussagekräftig)**" if median([s[3] for s in p["samples"]]) > 12 else ""))
            w("  - Verlauf `%s`" % spark(rs))
        if p.get("marks"):
            w("\n**Zeitleiste** (erster Aufruf der markierten Methoden):\n")
            for name, ms in p["marks"]:
                w("- %7.1f s  %s" % (ms / 1000, name))
        if p.get("anchors"):
            w("- Eingabe-Anker (Sekunden ab Start des Harness): " + ", ".join("%s %.1f" % kv for kv in p["anchors"].items()))
        if a["threads"]:
            w("\nThread-Zustände am Ende: " + ", ".join("%s ×%d" % (k, v) for k, v in sorted(a["threads"].items(), key=lambda x: -x[1])))
        if p.get("stalls"):
            w("\n**Bildstillstände:** " + "; ".join("t=%.0f bis %.0f s (Bild %d)" % (s["von_t"], s["bis_t"], s["frame"]) for s in p["stalls"]))
            w("\n### Thread-Zustände beim Stillstand (Hänger-Analyse)\n")
            w("Beteiligt (Hauptthread 80, Mutex-/Arbiter-Wartende, Threads mit IPC im Dauerbetrieb):\n\n```")
            for d in a["thread_detail"]:
                if d["state"] == "beendet" or not (d["id"] == 80 or d["svc"] in ("ArbitrateLock", "ArbitrateUnlock", "SleepThread", "WaitSynchronization") or d["ipc"] > 1000 or d["mutex"]):
                    continue
                w("Thread %d: %s, %d SVCs, %d IPC" % (d["id"], d["svc"], d["svcs"], d["ipc"]))
                for x in ([d["wait"], d["mutex"]] + d["bt"][:8]):
                    if x:
                        w("    " + sym_line(x)[:200])
            w("```")
            if a["dumps"]:
                w("\nGastspeicher beim Ende (Wörter ab Adresse):\n\n```")
                L.extend(a["dumps"])
                w("```")
            if a["sync_tail"]:
                w("\nLetzte Synchronisationsereignisse (T = Thread):\n\n```")
                L.extend(a["sync_tail"][-40:])
                w("```")
        if a["signal"] or a["fatal"] or p["returncode"] not in (0, None):
            w("\n### Absturz / Abbruch\n")
            if a["signal"]:
                w("- %s" % a["signal"].strip())
            for f in a["fatal"][:5]:
                w("- `%s`" % sym_line(f)[:300])
            w("- Exit-Code %s, Dauer %.0f s" % (p["returncode"], p["wall"]))
            if a["host_bt"]:
                w("\nHost-Rückverfolgung (oberste 12):\n\n```")
                L.extend(x[:150] for x in a["host_bt"][:12])
                w("```")
            if a["guest_bt"]:
                w("\nLetzter Gast-Stack (mit IL2CPP-Namen):\n\n```")
                L.extend(sym_line(x)[:200] for x in a["guest_bt"])
                w("```")
            if a["last_il2"]:
                w("\nLetzte erstmals aufgerufene Spielmethoden:\n\n```")
                L.extend(a["last_il2"])
                w("```")
        if a["unimpl_ipc"]:
            w("\n### Unbehandelte IPC-Befehle (Standardantwort)\n\n| Dienst:Befehl | Häufigkeit |\n|---|---|")
            for k, v in sorted(a["unimpl_ipc"].items(), key=lambda x: -x[1]):
                w("| %s | %d |" % (k, v))
        if a["unimpl_svc"]:
            w("\n### Nicht umgesetzte SVCs\n")
            for s in a["unimpl_svc"][:5]:
                w("- `%s`" % s[:200])
        if a["nvn_missing"]:
            w("\n### NVN-Funktionen ohne Host-Umsetzung\n")
            for s in a["nvn_missing"][:20]:
                w("- %s" % s)
        if a["noise"]:
            w("\n### Auffällige Logzeilen (Muster, Häufigkeit)\n\n| Anzahl | Muster |\n|---|---|")
            for k, v in sorted(a["noise"].items(), key=lambda x: -x[1])[:15]:
                w("| %d | `%s` |" % (v, k.replace("|", "/")))
        top = sorted(a["services"].items(), key=lambda x: -x[1])[:8]
        if top:
            w("\nHäufigste Dienstbefehle: " + ", ".join("%s ×%d" % kv for kv in top))
        if p.get("shot_summary"):
            s = p["shot_summary"]
            w("\n### Bilder\n\n%d Bilder in `%s` (schwarz: %d, unverändert zum Vorgänger: %d)." % (s["n"], p["shots"], s["black"], s["same"]))
            for c in s["sheets"]:
                w("- Kontaktbogen `%s`" % c)
    if rep.get("save"):
        s = rep["save"]
        w("\n## Spielstand\n\n- `SaveData.bin`: %s, Größe %s, sha256 %s…, Ausgangsstand %s…, geändert: %s, Änderungszeit %s" % ("vorhanden" if s.get("exists") else "fehlt", s.get("size"), s.get("sha"), s.get("base_sha"), s.get("changed"), s.get("mtime")))
        w("- Prüfung: %s" % s.get("check"))
    return "\n".join(L) + "\n"


def build_report(run_dir, sc, phases, args, started, bin_sha):
    for p in phases:
        a = analyze_log(p["log"], None)
        p["analysis"] = a
        end = a["fps"][-1]["t"] if a["fps"] else 0
        m = re.search(r"nach ([\d.]+) s", a["result"])
        endt = float(m.group(1)) if m else p["wall"]
        p["stalls"] = detect_stalls(a["fps"], endt)
        p["fps_stats"] = fps_stats(a["fps"], 30.0) or fps_stats(a["fps"])
        marks = []
        for mk in sc["marks"]:
            hit = [(v, k) for k, v in a["il2_first"].items() if mk in k]
            if hit:
                v, k = min(hit)
                marks.append((k, v))
        p["marks"] = sorted(marks, key=lambda x: x[1])
        infos, extra = shot_infos(p["shots"], a["fps"]) if Path(p["shots"]).is_dir() else ([], None)
        sheets = []
        if extra and infos:
            files = extra[0]
            keep = [(f, i) for f, i in zip(files, infos) if not i["black"] and not i["same_as_prev"]]   # Kontaktbogen nur mit Bildern, die etwas zeigen
            if keep:
                sheets = contact_sheet([f for f, _ in keep], [i for _, i in keep], str(Path(p["shots"]).parent / ("contact_%s" % p["tag"])))
        p["shot_summary"] = {"n": len(infos), "black": sum(i["black"] for i in infos), "same": sum(i["same_as_prev"] for i in infos), "sheets": sheets, "files": infos}
    save_info = check_save(run_dir, QA / "save_base") if (run_dir / "save").is_dir() and any(p.get("returncode") is not None for p in phases) else {}
    checks, crash = evaluate(sc, phases, run_dir, save_info, args)
    ok = all(c["ok"] for c in checks)
    rep = {"run": run_dir.name, "scenario": sc["name"], "desc": sc["desc"], "started": started, "wall": sum(p["wall"] for p in phases), "bin": args.bin, "bin_sha": bin_sha,
           "img": args.img, "ok": ok, "crash": crash, "checks": checks, "save": save_info,
           "phases": [{k: v for k, v in p.items() if k not in ("analysis",)} | {"analysis": {k: v for k, v in p["analysis"].items() if k not in ("fps", "il2_first")} | {"fps": p["analysis"]["fps"], "il2_first_count": len(p["analysis"]["il2_first"])}} for p in phases]}
    for pr, p in zip(rep["phases"], phases):
        pr["il2_first"] = p["analysis"]["il2_first"]
        if len(pr["il2_first"]) > 4000:
            pr["il2_first"] = dict(list(pr["il2_first"].items())[:4000])
    (run_dir / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    # der Markdown-Bericht braucht die Rohdaten je Phase (a, marks, ...)
    md_rep = dict(rep)
    md_rep["phases"] = [dict(pr, analysis=p["analysis"]) for pr, p in zip(rep["phases"], phases)]
    (run_dir / "report.md").write_text(render_md(md_rep), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?")
    ap.add_argument("--bin", default=str(QA / "bin" / "bdsp_boot"))
    ap.add_argument("--img", default="work/recomp/img_gfx2")
    ap.add_argument("--no-il2sym", action="store_true")
    ap.add_argument("--timeout", type=int, default=0)
    ap.add_argument("--label", default="")
    ap.add_argument("--min-free", type=int, default=10, help="harte Untergrenze freier Platz in GB (Soll 15: Warnung darunter)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    if args.list:
        for p in sorted(SCN.glob("*.txt")):
            d = [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("desc ")]
            print("%-16s %s" % (p.stem, d[0][5:] if d else ""))
        return 0
    if args.report:
        run_dir = Path(args.report).resolve()
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        sc = parse_scenario(meta["scenario"])
        phases = meta["phases"]
        rep = build_report(run_dir, sc, phases, args, meta["started"], meta["bin_sha"])
        print("Bericht: %s" % (run_dir / "report.md"))
        return 0 if rep["ok"] else 1
    if not args.scenario:
        ap.error("Szenario fehlt")
    if not Path(args.bin).is_file():
        print("Binärdatei fehlt: %s" % args.bin, file=sys.stderr)
        return 2
    if free_gb() < args.min_free:
        print("Zu wenig freier Platz: %.1f GB (< %d GB)" % (free_gb(), args.min_free), file=sys.stderr)
        return 3
    if free_gb() < MIN_FREE_GB:
        print("Warnung: nur %.1f GB frei (Soll %d GB); dieser Lauf braucht unter 100 MB" % (free_gb(), MIN_FREE_GB), file=sys.stderr)
    sc = parse_scenario(args.scenario)
    QA.mkdir(parents=True, exist_ok=True)
    lock = open(QA / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Es läuft schon ein QA-Lauf (Sperrdatei %s)" % (QA / ".lock"), file=sys.stderr)
        return 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = QA / ("%s-%s%s" % (args.scenario, stamp, ("-" + args.label) if args.label else ""))
    run_dir.mkdir(parents=True)
    base = QA / "save_base"
    phases = []
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    bin_sha = sha256(args.bin)
    if sc["phases"][0]["save"] == "base":
        shutil.copytree(base, run_dir / "save")
    else:
        (run_dir / "save").mkdir()
        if (base / "user_id.hex").is_file():
            shutil.copy(base / "user_id.hex", run_dir / "save" / "user_id.hex")
    for i, ph in enumerate(sc["phases"]):
        print("[qa] Phase %d/%d: %d Eingaben, Zeitlimit %d s" % (i + 1, len(sc["phases"]), len(ph["inputs"]), args.timeout or ph["timeout"]), flush=True)
        res = run_phase(args, sc, i, ph, run_dir)
        phases.append(res)
        print("[qa] Phase %d beendet: Exit-Code %s nach %.0f s" % (i + 1, res["returncode"], res["wall"]), flush=True)
        if res["returncode"] not in (0, None) and i + 1 < len(sc["phases"]):
            print("[qa] Absturz, weitere Phasen entfallen", flush=True)
            break
    (run_dir / "meta.json").write_text(json.dumps({"scenario": sc["name"], "started": started, "bin_sha": bin_sha, "phases": phases}, indent=1), encoding="utf-8")
    rep = build_report(run_dir, sc, phases, args, started, bin_sha)
    print("[qa] Ergebnis %s -> %s" % ("BESTANDEN" if rep["ok"] else "FEHLER", run_dir / "report.md"))
    for c in rep["checks"]:
        if not c["ok"]:
            print("  FEHLER: %s: %s" % (c["name"], c["detail"]))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
