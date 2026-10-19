#!/usr/bin/env python3
"""Tasten-Spieler für Ryujinx (läuft AUF dem Ryzen, KDE Plasma Wayland; Ablage ~/xnu-recomp/tools/ryzen_keys.py).

Legt per evdev/uinput eine virtuelle Tastatur "xnu-virtual-keyboard" an und spielt eine Tastenfolge (*.keys) ab. Die Tasten tragen die
Namen der Switch-Knöpfe (A, B, X, Y, L, R, ZL, ZR, PLUS, MINUS, UP, DOWN, LEFT, RIGHT, LSTICK_UP …, SCREENSHOT); die echte Tastenbelegung
liest das Skript aus ~/.config/Ryujinx/Config.json (input_config[0], hotkeys), es wird nichts geraten (Ausnahme: siehe --list, Plus/Minus
hängen vom Tastaturlayout ab und lassen sich per "map" überschreiben).

Aufruf:
  ryzen_keys.py ROUTE.keys [--dry-run] [--focus] [--time-limit SEK] [--shots-dir DIR] [--hold-ms N] [--speed F]
  ryzen_keys.py --check        Fokus prüfen (Exit 0 = aktives Fenster ist Ryujinx), nichts senden
  ryzen_keys.py --list         Belegung aus Config.json (Switch-Knopf -> Ryujinx-Taste -> evdev-Taste)

Sicherheit (Eingaben dürfen NIE in andere Fenster des Nutzers gelangen):
  * Vor JEDER Taste: aktives Fenster prüfen (xprop _NET_ACTIVE_WINDOW des Xwayland-Servers; KWin meldet für Wayland-native Fenster
    "keins"). Nur wenn der Titel mit "Ryujinx" beginnt und WM_CLASS "Ryujinx" ist, wird gesendet; sonst Abbruch (Exit 5), alle Tasten losgelassen.
  * Datei ~/xnu-recomp/STOP anlegen bricht jederzeit ab (Exit 3); Zeitlimit (Standard 300 s, Exit 4); nur eine Instanz (Exit 8).
  * --dry-run sendet nichts (kein uinput), zeigt Plan, Zeiten und Fokuszustand.
  * Nichts außerhalb ~/xnu-recomp wird geschrieben (Logs: ~/xnu-recomp/logs/ryzen_keys-*.log); Ryujinx schreibt seine Screenshots selbst.

Befehle einer .keys-Datei (eine je Zeile, # Kommentar):
  key NAME [hold_ms]       Knopf drücken und loslassen (Standard 120 ms)
  hold NAME ms             wie key, Dauer Pflicht (Laufen)
  down NAME / up NAME      Taste gedrückt halten / loslassen (werden am Ende garantiert losgelassen)
  combo NAME+NAME [ms]     mehrere Tasten gleichzeitig
  type TEXT                Buchstaben/Ziffern/Leerzeichen (Großbuchstaben mit Umschalt) als Tastatureingabe
  wait MS                  warten (in 50-ms-Scheiben, STOP wird beachtet)
  shot [timeout_s]         Screenshot-Taste (F8 laut Config), dann auf die neue Datei im Screenshot-Ordner warten (Synchronisation)
  shot_as VIEW [timeout_s] wie shot; das Bild gehört zur Referenzansicht VIEW (scripts/visual/ref_map.json), steht so im RESULT
  wait_shot [timeout_s]    nur auf eine neue Datei warten (z. B. wenn der Nutzer F8 drückt)
  require_focus            Fokus jetzt prüfen
  repeat N ... end         Block N-mal
  map NAME KEY_XXX         Zuordnung überschreiben (z. B. map PLUS KEY_KPPLUS)
  note TEXT                Text ins Log
Exit-Codes: 0 ok, 2 Aufruf/Config, 3 STOP-Datei, 4 Zeitlimit, 5 Fokus nicht Ryujinx, 6 kein neues Bild, 7 uinput nicht nutzbar, 8 läuft schon.
Letzte Ausgabezeile: RESULT {json} mit den neu entstandenen Screenshots.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
BASE = HOME / "xnu-recomp"
STOP = BASE / "STOP"
LOCK = BASE / "run" / "ryzen_keys.lock"
LOGDIR = BASE / "logs"
CONFIG = HOME / ".config" / "Ryujinx" / "Config.json"
SHOTS = HOME / ".config" / "Ryujinx" / "screenshots"
VKB_NAME = "xnu-virtual-keyboard"

# Ryujinx-Tastennamen (Avalonia/Ryujinx.Common.Configuration.Hid.Key) -> evdev, für Layout "us"
RYU_TO_EVDEV = {
    "Up": "KEY_UP", "Down": "KEY_DOWN", "Left": "KEY_LEFT", "Right": "KEY_RIGHT",
    "Enter": "KEY_ENTER", "Return": "KEY_ENTER", "Space": "KEY_SPACE", "Escape": "KEY_ESC", "Tab": "KEY_TAB", "BackSpace": "KEY_BACKSPACE",
    "Minus": "KEY_MINUS", "Plus": "KEY_EQUAL", "Comma": "KEY_COMMA", "Period": "KEY_DOT", "Slash": "KEY_SLASH",
    "ShiftLeft": "KEY_LEFTSHIFT", "ShiftRight": "KEY_RIGHTSHIFT", "ControlLeft": "KEY_LEFTCTRL", "AltLeft": "KEY_LEFTALT",
    "KeypadAdd": "KEY_KPPLUS", "KeypadSubtract": "KEY_KPMINUS", "Home": "KEY_HOME", "End": "KEY_END", "PageUp": "KEY_PAGEUP", "PageDown": "KEY_PAGEDOWN",
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    RYU_TO_EVDEV[_c] = "KEY_" + _c
for _d in "0123456789":
    RYU_TO_EVDEV["Number" + _d] = "KEY_" + _d
for _f in range(1, 13):
    RYU_TO_EVDEV["F%d" % _f] = "KEY_F%d" % _f

# Switch-Knopf -> (Abschnitt in Config.json, Feld)
BINDING_FIELDS = {
    "UP": ("left_joycon", "dpad_up"), "DOWN": ("left_joycon", "dpad_down"), "LEFT": ("left_joycon", "dpad_left"), "RIGHT": ("left_joycon", "dpad_right"),
    "MINUS": ("left_joycon", "button_minus"), "L": ("left_joycon", "button_l"), "ZL": ("left_joycon", "button_zl"),
    "PLUS": ("right_joycon", "button_plus"), "R": ("right_joycon", "button_r"), "ZR": ("right_joycon", "button_zr"),
    "A": ("right_joycon", "button_a"), "B": ("right_joycon", "button_b"), "X": ("right_joycon", "button_x"), "Y": ("right_joycon", "button_y"),
    "LSTICK_UP": ("left_joycon_stick", "stick_up"), "LSTICK_DOWN": ("left_joycon_stick", "stick_down"),
    "LSTICK_LEFT": ("left_joycon_stick", "stick_left"), "LSTICK_RIGHT": ("left_joycon_stick", "stick_right"), "LSTICK_PRESS": ("left_joycon_stick", "stick_button"),
    "RSTICK_UP": ("right_joycon_stick", "stick_up"), "RSTICK_DOWN": ("right_joycon_stick", "stick_down"),
    "RSTICK_LEFT": ("right_joycon_stick", "stick_left"), "RSTICK_RIGHT": ("right_joycon_stick", "stick_right"), "RSTICK_PRESS": ("right_joycon_stick", "stick_button"),
}
HOTKEY_FIELDS = {"SCREENSHOT": "screenshot", "PAUSE": "pause", "SHOW_UI": "show_ui", "MUTE": "toggle_mute", "VSYNC": "toggle_vsync_mode"}


class Abort(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def load_bindings(config_path=CONFIG):
    """Switch-Knopf/Hotkey -> Ryujinx-Taste aus Config.json (erste Tastatur-Eingabe, Player1)."""
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    ic = next((i for i in cfg.get("input_config", []) if i.get("backend") == "WindowKeyboard"), None)
    if ic is None:
        raise Abort(2, "Keine Tastatur-Eingabe (WindowKeyboard) in input_config von %s" % config_path)
    out = {}
    for name, (sec, fld) in BINDING_FIELDS.items():
        v = (ic.get(sec) or {}).get(fld)
        if v and v != "Unbound":
            out[name] = v
    for name, fld in HOTKEY_FIELDS.items():
        v = (cfg.get("hotkeys") or {}).get(fld)
        if v and v != "Unbound":
            out[name] = v
    return out


def evdev_name(ryu_key):
    if ryu_key not in RYU_TO_EVDEV:
        raise Abort(2, "Ryujinx-Taste %r hat keine bekannte evdev-Zuordnung (RYU_TO_EVDEV ergänzen oder 'map NAME KEY_XXX')" % ryu_key)
    return RYU_TO_EVDEV[ryu_key]


class Keymap:
    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.override = {}

    def resolve(self, name):
        """Name einer .keys-Datei -> evdev-Name (KEY_...). Reihenfolge: map-Überschreibung, Switch-Knopf, KEY_..., Ryujinx-Taste."""
        n = name.strip()
        if n.upper() in self.override:
            return self.override[n.upper()]
        if n.upper() in self.bindings:
            return evdev_name(self.bindings[n.upper()])
        if n.upper().startswith("KEY_"):
            return n.upper()
        if n in RYU_TO_EVDEV:
            return RYU_TO_EVDEV[n]
        raise Abort(2, "Unbekannte Taste %r (Switch-Knöpfe: %s)" % (name, ", ".join(sorted(self.bindings))))


# ---------------------------------------------------------------------------------------------------------------------
# Fokus
# ---------------------------------------------------------------------------------------------------------------------

def ryujinx_pid():
    me = os.getpid()
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            cmd = (p / "cmdline").read_bytes().split(b"\0")[0].decode("utf-8", "replace")
        except OSError:
            continue
        if cmd.endswith("/usr/bin/Ryujinx") or cmd.endswith("/Ryujinx"):
            return int(p.name)
    return None


def graphical_env():
    """Umgebung der Grafiksitzung (aus dem Ryujinx-Prozess): DISPLAY, XAUTHORITY, WAYLAND_DISPLAY, XDG_RUNTIME_DIR, DBUS."""
    env = dict(os.environ)
    pid = ryujinx_pid()
    if pid:
        try:
            for item in (Path("/proc/%d/environ" % pid)).read_bytes().split(b"\0"):
                k, _, v = item.decode("utf-8", "replace").partition("=")
                if k in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
                    env[k] = v
        except OSError:
            pass
    return env, pid


def run(cmd, env, timeout=5):
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def active_window(env):
    """(id, Titel, Klasse) des aktiven X11-Fensters oder None (Wayland-natives Fenster/keins aktiv)."""
    rc, out = run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], env)
    m = re.search(r"window id # (0x[0-9a-fA-F]+)", out)
    if rc != 0 or not m or int(m.group(1), 16) == 0:
        return None
    wid = m.group(1)
    rc, out = run(["xprop", "-id", wid, "_NET_WM_NAME", "WM_CLASS"], env)
    title = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', out)
    cls = re.search(r'WM_CLASS\(STRING\) = (.*)', out)
    return wid, title.group(1) if title else "", cls.group(1) if cls else ""


def focus_state(env):
    """('ok'|'fremd'|'keins', Beschreibung)"""
    w = active_window(env)
    if w is None:
        return "keins", "kein X11-Fenster aktiv (ein Wayland-Fenster oder nichts hat den Fokus)"
    wid, title, cls = w
    if title.startswith("Ryujinx") and "Ryujinx" in cls:
        return "ok", "%s %s" % (wid, title)
    return "fremd", "aktiv ist %s \"%s\" [%s]" % (wid, title, cls)


def try_focus(env):
    rc, out = run(["wmctrl", "-l"], env)
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[4].startswith("Ryujinx"):
            run(["wmctrl", "-i", "-a", parts[0]], env)
            t0 = time.time()
            while time.time() - t0 < 3:
                time.sleep(0.2)
                if focus_state(env)[0] == "ok":
                    return True
            return False
    return False


# ---------------------------------------------------------------------------------------------------------------------
# Folge parsen
# ---------------------------------------------------------------------------------------------------------------------

def parse_route(text):
    """Zeilen -> Liste von Operationen (Dict); repeat/end werden aufgelöst."""
    ops = []
    stack = [ops]
    counts = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        w = line.split()
        cmd, args = w[0].lower(), w[1:]
        try:
            if cmd == "repeat":
                counts.append(int(args[0]))
                block = []
                stack.append(block)
                continue
            if cmd == "end":
                if len(stack) < 2:
                    raise ValueError("end ohne repeat")
                block = stack.pop()
                n = counts.pop()
                for _ in range(n):
                    stack[-1].extend(dict(o) for o in block)
                continue
            if cmd in ("key", "hold"):
                if cmd == "hold" and len(args) < 2:
                    raise ValueError("hold braucht NAME und ms")
                stack[-1].append({"op": "key", "name": args[0], "hold": int(args[1]) if len(args) > 1 else None, "line": no})
            elif cmd in ("down", "up"):
                stack[-1].append({"op": cmd, "name": args[0], "line": no})
            elif cmd == "combo":
                stack[-1].append({"op": "combo", "names": args[0].split("+"), "hold": int(args[1]) if len(args) > 1 else None, "line": no})
            elif cmd == "type":
                stack[-1].append({"op": "type", "text": line.split(None, 1)[1], "line": no})
            elif cmd == "wait":
                stack[-1].append({"op": "wait", "ms": int(args[0]), "line": no})
            elif cmd in ("shot", "wait_shot"):
                stack[-1].append({"op": cmd, "timeout": float(args[0]) if args else 10.0, "view": None, "line": no})
            elif cmd == "shot_as":
                stack[-1].append({"op": "shot", "timeout": float(args[1]) if len(args) > 1 else 10.0, "view": args[0], "line": no})
            elif cmd == "require_focus":
                stack[-1].append({"op": "require_focus", "line": no})
            elif cmd == "map":
                stack[-1].append({"op": "map", "name": args[0], "key": args[1], "line": no})
            elif cmd == "note":
                stack[-1].append({"op": "note", "text": line.split(None, 1)[1] if len(args) else "", "line": no})
            else:
                raise ValueError("unbekannter Befehl %r" % cmd)
        except (IndexError, ValueError) as exc:
            raise Abort(2, "Zeile %d: %s (%s)" % (no, exc, raw.strip()))
    if len(stack) != 1:
        raise Abort(2, "repeat ohne end")
    return ops


def text_keys(text):
    """type TEXT -> Liste (evdev-Name, shift)"""
    out = []
    for ch in text:
        if ch.isalpha() and ch.isascii():
            out.append(("KEY_" + ch.upper(), ch.isupper()))
        elif ch.isdigit():
            out.append(("KEY_" + ch, False))
        elif ch == " ":
            out.append(("KEY_SPACE", False))
        else:
            raise Abort(2, "type: Zeichen %r nicht unterstützt" % ch)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Ausführung
# ---------------------------------------------------------------------------------------------------------------------

class Player:
    def __init__(self, keymap, env, dry=False, shots_dir=SHOTS, time_limit=300.0, hold_ms=120, speed=1.0, log=None):
        self.km, self.env, self.dry = keymap, env, dry
        self.shots_dir, self.time_limit, self.hold_ms, self.speed = Path(shots_dir), time_limit, hold_ms, speed
        self.t0 = time.time()
        self.ui = None
        self.pressed = set()
        self.shots = []
        self.log_f = log
        self.sent = 0

    def say(self, msg):
        line = "[%6.2f] %s" % (time.time() - self.t0, msg)
        print(line, flush=True)
        if self.log_f:
            self.log_f.write(line + "\n")
            self.log_f.flush()

    # --- Schutz
    def guard(self, need_focus=True):
        if STOP.exists():
            raise Abort(3, "STOP-Datei %s gefunden" % STOP)
        if time.time() - self.t0 > self.time_limit:
            raise Abort(4, "Zeitlimit %.0f s erreicht" % self.time_limit)
        if need_focus:
            st, desc = focus_state(self.env)
            if st != "ok":
                if self.dry:
                    self.say("(Trockenlauf) Fokus NICHT Ryujinx: %s" % desc)
                else:
                    raise Abort(5, "Fokus ist nicht Ryujinx: %s" % desc)

    def sleep(self, seconds):
        end = time.time() + seconds / self.speed
        while time.time() < end:
            self.guard(need_focus=False)
            time.sleep(min(0.05, max(0.0, end - time.time())))

    # --- uinput
    def open_ui(self, codes):
        if self.dry:
            return
        try:
            from evdev import UInput, ecodes
        except ImportError:
            raise Abort(7, "python-evdev fehlt")
        caps = {ecodes.EV_KEY: sorted({ecodes.ecodes[c] for c in codes} | {ecodes.KEY_LEFTSHIFT})}
        try:
            self.ui = UInput(caps, name=VKB_NAME, vendor=0x1209, product=0x7a01, version=1)
        except (PermissionError, OSError) as exc:
            raise Abort(7, "/dev/uinput nicht nutzbar: %s" % exc)
        time.sleep(0.7)  # Compositor soll die Tastatur kennen

    def _write(self, code, value):
        from evdev import ecodes
        self.ui.write(ecodes.EV_KEY, ecodes.ecodes[code], value)
        self.ui.syn()

    def press(self, code):
        self.pressed.add(code)
        if not self.dry:
            self._write(code, 1)
        self.sent += 1

    def release(self, code):
        self.pressed.discard(code)
        if not self.dry:
            self._write(code, 0)

    def release_all(self):
        for c in list(self.pressed):
            try:
                self.release(c)
            except OSError:
                pass

    def close(self):
        self.release_all()
        if self.ui is not None:
            self.ui.close()
            self.ui = None

    # --- Operationen
    def tap(self, codes, hold_ms):
        self.guard()
        for c in codes:
            self.press(c)
        self.sleep((hold_ms if hold_ms is not None else self.hold_ms) / 1000.0)
        for c in reversed(codes):
            self.release(c)
        self.sleep(0.08)

    def list_shots(self):
        if not self.shots_dir.is_dir():
            return {}
        return {p.name: p.stat().st_mtime for p in self.shots_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".bmp")}

    def wait_shot(self, before, timeout):
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            self.guard(need_focus=False)
            now = self.list_shots()
            new = [n for n in now if n not in before]
            if new:
                n = sorted(new, key=lambda x: now[x])[-1]
                size = (self.shots_dir / n).stat().st_size
                if size > 0 and size == last:
                    return n
                last = size
            time.sleep(0.2)
        raise Abort(6, "kein neues Bild im Screenshot-Ordner nach %.0f s" % timeout)

    def run_ops(self, ops):
        for op in ops:
            kind = op["op"]
            if kind == "note":
                self.say("Hinweis: " + op["text"])
            elif kind == "map":
                self.km.override[op["name"].upper()] = op["key"].upper()
            elif kind == "wait":
                self.say("wait %d ms" % op["ms"])
                self.sleep(op["ms"] / 1000.0)
            elif kind == "require_focus":
                st, desc = focus_state(self.env)
                self.say("Fokus: %s (%s)" % (st, desc))
                if st != "ok" and not self.dry:
                    raise Abort(5, "Fokus ist nicht Ryujinx: %s" % desc)
            elif kind == "key":
                code = self.km.resolve(op["name"])
                self.say("key %s (%s) hold %s ms" % (op["name"], code, op["hold"] if op["hold"] is not None else self.hold_ms))
                self.tap([code], op["hold"])
            elif kind == "combo":
                codes = [self.km.resolve(n) for n in op["names"]]
                self.say("combo %s hold %s ms" % ("+".join(codes), op["hold"] if op["hold"] is not None else self.hold_ms))
                self.tap(codes, op["hold"])
            elif kind == "down":
                code = self.km.resolve(op["name"])
                self.guard()
                self.say("down %s (%s)" % (op["name"], code))
                self.press(code)
            elif kind == "up":
                code = self.km.resolve(op["name"])
                self.say("up %s (%s)" % (op["name"], code))
                self.release(code)
            elif kind == "type":
                self.say("type %r" % op["text"])
                for code, shift in text_keys(op["text"]):
                    self.tap(["KEY_LEFTSHIFT", code] if shift else [code], 60)
            elif kind in ("shot", "wait_shot"):
                before = self.list_shots()
                if kind == "shot":
                    code = self.km.resolve("SCREENSHOT")
                    self.say("shot: %s drücken und auf neues Bild warten" % code)
                    self.tap([code], 80)
                else:
                    self.say("wait_shot: warte auf neues Bild")
                if self.dry:
                    self.shots.append({"name": "(Trockenlauf)", "view": op.get("view"), "t": round(time.time() - self.t0, 2)})
                    continue
                name = self.wait_shot(before, op["timeout"])
                self.say("neues Bild: %s%s" % (name, " als %s" % op["view"] if op.get("view") else ""))
                self.shots.append({"name": name, "view": op.get("view"), "t": round(time.time() - self.t0, 2), "mtime": self.list_shots().get(name)})
            else:
                raise Abort(2, "interner Fehler: Operation %s" % kind)


def collect_codes(ops, km):
    codes = {"KEY_LEFTSHIFT"}
    for op in ops:
        if op["op"] == "map":
            km.override[op["name"].upper()] = op["key"].upper()
    for op in ops:
        if op["op"] in ("key", "down", "up"):
            codes.add(km.resolve(op["name"]))
        elif op["op"] == "combo":
            codes.update(km.resolve(n) for n in op["names"])
        elif op["op"] == "type":
            codes.update(c for c, _ in text_keys(op["text"]))
        elif op["op"] == "shot":
            codes.add(km.resolve("SCREENSHOT"))
    return codes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("route", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--focus", action="store_true", help="Ryujinx-Fenster per wmctrl in den Vordergrund holen versuchen")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--shots-dir", default=str(SHOTS))
    ap.add_argument("--hold-ms", type=int, default=120)
    ap.add_argument("--speed", type=float, default=1.0, help="Zeitfaktor für wait/hold (2 = doppelt so schnell)")
    ap.add_argument("--config", default=str(CONFIG))
    a = ap.parse_args(argv)
    env, pid = graphical_env()
    try:
        bindings = load_bindings(a.config)
        km = Keymap(bindings)
        if a.list:
            for n in sorted(bindings):
                try:
                    ev = evdev_name(bindings[n])
                except Abort as e:
                    ev = "? (%s)" % e.msg
                print("%-14s %-12s %s" % (n, bindings[n], ev))
            return 0
        if a.check:
            st, desc = focus_state(env)
            print("Ryujinx-Prozess: %s; Fokus: %s (%s)" % (pid, st, desc))
            return 0 if st == "ok" else 5
        if not a.route:
            ap.error("ROUTE.keys fehlt")
        ops = parse_route(Path(a.route).read_text(encoding="utf-8"))
        codes = collect_codes(ops, km)
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "run").mkdir(exist_ok=True)
        LOGDIR.mkdir(exist_ok=True)
        if not a.dry_run:
            if LOCK.exists():
                try:
                    other = int(LOCK.read_text().strip())
                    os.kill(other, 0)
                    raise Abort(8, "läuft schon (PID %d)" % other)
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
            LOCK.write_text(str(os.getpid()))
        if STOP.exists():
            raise Abort(3, "STOP-Datei %s liegt schon da (löschen, dann neu starten)" % STOP)
        if pid is None:
            raise Abort(5, "Kein Ryujinx-Prozess gefunden")
        if a.focus and not try_focus(env):
            raise Abort(5, "Ryujinx-Fenster ließ sich nicht in den Vordergrund holen (Fokus manuell setzen)")
        logf = open(LOGDIR / time.strftime("ryzen_keys-%Y%m%d-%H%M%S.log"), "w", encoding="utf-8")
        pl = Player(km, env, a.dry_run, a.shots_dir, a.time_limit, a.hold_ms, a.speed, logf)
        code = 0
        try:
            pl.say("Folge %s: %d Operationen, %d Tasten, Modus %s" % (a.route, len(ops), len(codes), "TROCKENLAUF" if a.dry_run else "ECHT"))
            st, desc = focus_state(env)
            pl.say("Fokus vor dem Start: %s (%s)" % (st, desc))
            if not a.dry_run and st != "ok":
                raise Abort(5, "Fokus ist nicht Ryujinx: %s" % desc)
            pl.open_ui(codes)
            pl.run_ops(ops)
            pl.say("fertig")
        except Abort as e:
            pl.say("ABBRUCH (%d): %s" % (e.code, e.msg))
            code = e.code
        finally:
            pl.close()
            logf.close()
            if not a.dry_run and LOCK.exists():
                LOCK.unlink()
        print("RESULT " + json.dumps({"exit": code, "dry_run": a.dry_run, "shots": pl.shots, "keys_sent": pl.sent, "seconds": round(time.time() - pl.t0, 2)}, ensure_ascii=False))
        return code
    except Abort as e:
        print("FEHLER (%d): %s" % (e.code, e.msg), file=sys.stderr)
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
        return e.code


if __name__ == "__main__":
    sys.exit(main())
