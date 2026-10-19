"""Tests für scripts/ryzen_keys.py – ohne uinput, ohne Ryzen: Parser, Tastenbelegung, Sicherheitsabbrüche (Fokus, STOP, Zeitlimit)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ryzen_keys as rk  # noqa: E402
from test_visual_compare import Tmp  # noqa: E402

CONFIG = {
    "hotkeys": {"screenshot": "F8", "pause": "F5", "show_ui": "Unbound"},
    "input_config": [{
        "backend": "WindowKeyboard",
        "left_joycon_stick": {"stick_up": "W", "stick_down": "S", "stick_left": "A", "stick_right": "D", "stick_button": "F"},
        "right_joycon_stick": {"stick_up": "I"},
        "left_joycon": {"dpad_up": "Up", "dpad_down": "Down", "dpad_left": "Left", "dpad_right": "Right", "button_minus": "Minus", "button_l": "E", "button_zl": "Q"},
        "right_joycon": {"button_plus": "Plus", "button_r": "U", "button_zr": "O", "button_a": "Z", "button_b": "X", "button_x": "C", "button_y": "V"},
    }],
}


class FakePlayer(rk.Player):
    """Player ohne echte Wartezeiten."""


class KeymapTests(Tmp):
    def setUp(self):
        super().setUp()
        self.cfg = self.tmp / "Config.json"
        self.cfg.write_text(json.dumps(CONFIG), encoding="utf-8")

    def test_bindings_from_config(self):
        b = rk.load_bindings(self.cfg)
        self.assertEqual(b["A"], "Z")
        self.assertEqual(b["B"], "X")
        self.assertEqual(b["SCREENSHOT"], "F8")
        self.assertNotIn("SHOW_UI", b)           # Unbound wird nicht geraten
        km = rk.Keymap(b)
        self.assertEqual(km.resolve("A"), "KEY_Z")
        self.assertEqual(km.resolve("up"), "KEY_UP")
        self.assertEqual(km.resolve("SCREENSHOT"), "KEY_F8")
        self.assertEqual(km.resolve("KEY_ESC"), "KEY_ESC")
        km.override["PLUS"] = "KEY_KPPLUS"
        self.assertEqual(km.resolve("PLUS"), "KEY_KPPLUS")
        with self.assertRaises(rk.Abort):
            km.resolve("GIBTESNICHT")

    def test_missing_keyboard_config(self):
        self.cfg.write_text(json.dumps({"input_config": [{"backend": "GamepadSDL2"}]}), encoding="utf-8")
        with self.assertRaises(rk.Abort) as cm:
            rk.load_bindings(self.cfg)
        self.assertEqual(cm.exception.code, 2)


class ParseTests(unittest.TestCase):
    def test_parse_all_commands_and_repeat(self):
        ops = rk.parse_route("""
            # Kommentar
            note Start
            key A
            hold UP 500   # Laufen
            repeat 3
              key DOWN 50
              wait 100
            end
            combo L+R 200
            type Ab 1
            shot_as ref_x 7
            wait_shot
            map PLUS KEY_KPPLUS
            require_focus
        """)
        kinds = [o["op"] for o in ops]
        self.assertEqual(kinds, ["note", "key", "key", "key", "wait", "key", "wait", "key", "wait", "combo", "type", "shot", "wait_shot", "map", "require_focus"])
        self.assertEqual(ops[2]["hold"], 500)
        self.assertEqual(ops[11]["view"], "ref_x")
        self.assertEqual(ops[11]["timeout"], 7.0)

    def test_parse_errors(self):
        for bad in ("repeat 2\nkey A", "end", "key", "hold UP", "wait x", "tanzen"):
            with self.assertRaises(rk.Abort, msg=bad):
                rk.parse_route(bad)

    def test_type_keys(self):
        self.assertEqual(rk.text_keys("aB 1"), [("KEY_A", False), ("KEY_B", True), ("KEY_SPACE", False), ("KEY_1", False)])
        with self.assertRaises(rk.Abort):
            rk.text_keys("ä")

    def test_shipped_routes_parse(self):
        routes = Path(rk.__file__).resolve().parent / "visual" / "routes"
        files = sorted(routes.glob("*.keys"))
        self.assertTrue(files)
        for f in files:
            ops = rk.parse_route(f.read_text(encoding="utf-8"))
            self.assertTrue(any(o["op"] == "shot" for o in ops), f.name)
            self.assertEqual(ops[0]["op"], "require_focus", "jede Route beginnt mit der Fokusprüfung: " + f.name)


class FocusGuardTests(Tmp):
    def player(self, dry=False, limit=300.0):
        km = rk.Keymap({"A": "Z", "SCREENSHOT": "F8", "UP": "Up"})
        p = rk.Player(km, {}, dry=dry, shots_dir=self.tmp / "shots", time_limit=limit, hold_ms=1, speed=1000.0)
        p.say = lambda msg: None
        return p

    def test_foreign_focus_aborts_before_any_key(self):
        p = self.player()
        sent = []
        p.press = lambda c: sent.append(c)
        with mock.patch.object(rk, "focus_state", return_value=("fremd", "aktiv ist 0x1 \"Konsole\" [konsole]")):
            with self.assertRaises(rk.Abort) as cm:
                p.run_ops(rk.parse_route("key A"))
        self.assertEqual(cm.exception.code, 5)
        self.assertEqual(sent, [])

    def test_wayland_native_window_counts_as_no_focus(self):
        p = self.player()
        with mock.patch.object(rk, "active_window", return_value=None):
            self.assertEqual(rk.focus_state({})[0], "keins")
            with self.assertRaises(rk.Abort) as cm:
                p.run_ops(rk.parse_route("key A"))
        self.assertEqual(cm.exception.code, 5)

    def test_focus_ok_requires_ryujinx_title_and_class(self):
        with mock.patch.object(rk, "active_window", return_value=("0x1", "Ryujinx 1.2.78 - X", '"Ryujinx", "Ryujinx"')):
            self.assertEqual(rk.focus_state({})[0], "ok")
        with mock.patch.object(rk, "active_window", return_value=("0x1", "Ryujinx Notizen - Browser", '"firefox", "Firefox"')):
            self.assertEqual(rk.focus_state({})[0], "fremd")
        with mock.patch.object(rk, "active_window", return_value=("0x1", "Terminal", '"Ryujinx", "Ryujinx"')):
            self.assertEqual(rk.focus_state({})[0], "fremd")

    def test_focus_lost_midway_releases_held_key(self):
        p = self.player()
        events = []
        p.press = lambda c: (events.append(("down", c)), p.pressed.add(c))
        p.release = lambda c: (events.append(("up", c)), p.pressed.discard(c))
        states = iter([("ok", "x"), ("fremd", "Browser")])
        with mock.patch.object(rk, "focus_state", side_effect=lambda env: next(states)):
            with self.assertRaises(rk.Abort):
                p.run_ops(rk.parse_route("key A\nkey UP"))
        self.assertEqual(events[0], ("down", "KEY_Z"))
        self.assertEqual(events[1], ("up", "KEY_Z"))
        self.assertNotIn(("down", "KEY_UP"), events)
        p.release_all()
        self.assertEqual(p.pressed, set())

    def test_stop_file_and_time_limit(self):
        p = self.player()
        stop = self.tmp / "STOP"
        stop.write_text("x")
        with mock.patch.object(rk, "STOP", stop), mock.patch.object(rk, "focus_state", return_value=("ok", "")):
            with self.assertRaises(rk.Abort) as cm:
                p.run_ops(rk.parse_route("wait 50"))
            self.assertEqual(cm.exception.code, 3)
        p2 = self.player(limit=0.0)
        with mock.patch.object(rk, "STOP", self.tmp / "nope"), mock.patch.object(rk, "focus_state", return_value=("ok", "")):
            with self.assertRaises(rk.Abort) as cm:
                p2.t0 -= 5
                p2.run_ops(rk.parse_route("key A"))
            self.assertEqual(cm.exception.code, 4)

    def test_dry_run_sends_nothing_even_without_focus(self):
        p = self.player(dry=True)
        with mock.patch.object(rk, "focus_state", return_value=("fremd", "Browser")), mock.patch.object(rk, "STOP", self.tmp / "nope"):
            p.run_ops(rk.parse_route("key A\nhold UP 20\nshot_as v 1"))
        self.assertEqual(p.shots[0]["view"], "v")
        self.assertIsNone(p.ui)

    def test_wait_shot_detects_new_file(self):
        shots = self.tmp / "shots"
        shots.mkdir()
        (shots / "old.png").write_bytes(b"x")
        p = self.player()
        before = p.list_shots()
        (shots / "new.png").write_bytes(b"abc")
        with mock.patch.object(rk, "STOP", self.tmp / "nope"):
            self.assertEqual(p.wait_shot(before, 3), "new.png")
            with self.assertRaises(rk.Abort) as cm:
                p.wait_shot(p.list_shots(), 0.5)
            self.assertEqual(cm.exception.code, 6)

    def test_collect_codes(self):
        km = rk.Keymap({"A": "Z", "SCREENSHOT": "F8", "L": "E", "R": "U"})
        ops = rk.parse_route("key A\ncombo L+R\nshot\ntype a")
        self.assertEqual(rk.collect_codes(ops, km), {"KEY_LEFTSHIFT", "KEY_Z", "KEY_E", "KEY_U", "KEY_F8", "KEY_A"})


if __name__ == "__main__":
    unittest.main()
