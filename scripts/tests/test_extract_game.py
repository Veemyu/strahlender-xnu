import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import extract_game as extraction
from scripts.recomp import portable_build as build


class ExtractionTests(unittest.TestCase):
    def test_discarded_extraction_output_is_drained_without_retention_or_overflow(self):
        commands = build.Commands()
        try:
            source = "import sys; sys.stdout.write('private file\\n' * 200000)"
            self.assertEqual(commands.capture(
                [os.sys.executable, "-c", source], limit=10, discard_output=True), b"")
            with self.assertRaises(subprocess.CalledProcessError) as error:
                commands.capture([os.sys.executable, "-c", source + "; sys.exit(7)"],
                                 limit=10, discard_output=True)
            self.assertEqual(error.exception.returncode, 7)
            self.assertEqual(error.exception.output, b"")
            with self.assertRaisesRegex(ValueError, "line callback"):
                commands.capture([], discard_output=True, on_line=lambda line: None)
        finally:
            commands.close()

    def test_capture_limit_and_callback_failure_cancel_a_waiting_tool(self):
        for callback_failure in (False, True):
            with self.subTest(callback_failure=callback_failure):
                commands = build.Commands()
                def failed_callback(line):
                    raise ValueError("callback failed")
                started = time.monotonic()
                try:
                    with self.assertRaisesRegex(ValueError, "callback failed" if callback_failure else "capture limit"):
                        commands.capture(
                            [os.sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(10)"],
                            limit=1024 if callback_failure else 1,
                            on_line=failed_callback if callback_failure else None)
                    self.assertLess(time.monotonic() - started, 5)
                finally:
                    commands.close()

    def test_native_capture_is_private_bounded_and_preserves_unicode_environment(self):
        commands = build.Commands()
        try:
            result = commands.capture(
                [os.sys.executable, "-c", "import os; print(os.environ['BDSP_TEST_CAPTURE'])"],
                env={**os.environ, "BDSP_TEST_CAPTURE": "\u65e5\u672c\u8a9e", "PYTHONIOENCODING": "utf-8"})
            self.assertEqual(result.decode("utf-8").strip(), "\u65e5\u672c\u8a9e")
            with self.assertRaisesRegex(ValueError, "capture limit"):
                commands.capture([os.sys.executable, "-c", "print('x' * 10000)"], limit=10)
        finally:
            commands.close()

    def test_native_capture_streams_complete_lines_before_process_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "acknowledged"
            commands = build.Commands()
            lines = []
            def line(text):
                lines.append(text)
                marker.touch()
            source = ("import pathlib,sys,time; marker=pathlib.Path(sys.argv[1]); "
                      "print('ready',flush=True); end=time.monotonic()+3\n"
                      "while not marker.exists() and time.monotonic()<end: time.sleep(.01)\n"
                      "assert marker.exists(), 'output was not streamed'\nprint('complete')\n")
            try:
                output = commands.capture([os.sys.executable, "-c", source, marker], on_line=line)
                self.assertEqual(lines, ["ready", "complete"])
                self.assertIn(b"complete", output)
            finally:
                commands.close()

    def test_metadata_uses_existing_helpers_and_failure_never_exposes_tool_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game.nca").write_bytes(b"synthetic")
            class Commands:
                def capture(self, arguments, **options):
                    self.arguments, self.options = arguments, options
                    if options.get("discard_output"):
                        return b""
                    return (b"Title ID: 0100000011d90000\nContent Type: Program\n"
                            b"Content Size: 1000\nKey Area Key: NEVER LOG THIS\n")
            commands = Commands()
            tool = extraction.ExtractionTool(root / "tool.exe", root / "selected.keys", commands, root / "home")
            rows = tool.classify(root)
            self.assertEqual(extraction.pick(rows, "Program")["path"], str(root / "game.nca"))
            self.assertNotIn("NEVER", json.dumps(rows))
            self.assertIn("--suppresskeys", commands.arguments)
            self.assertFalse(commands.options["discard_output"])
            self.assertEqual(tool.run("--romfsdir=output", "private file", discard_output=True), "")
            self.assertTrue(commands.options["discard_output"])
            self.assertEqual(commands.options["env"]["HOME"], str(root / "home"))
            with patch.object(commands, "capture", side_effect=subprocess.CalledProcessError(
                    5, ["--titlekey=SECRET"], output=b"PRIVATE KEYS")):
                with self.assertRaisesRegex(ValueError, "Native extraction failed") as error:
                    tool.run("-i", "private file")
            self.assertNotIn("SECRET", str(error.exception))
            self.assertNotIn("PRIVATE", str(error.exception))

    def test_related_meta_uses_the_selected_title_family_not_the_largest_other_game(self):
        rows = [dict(path="matching", title_id="0100000011d90800", content_type="Meta", size=1),
                dict(path="other-game", title_id="0100000000000800", content_type="Meta", size=100)]
        for row in rows:
            row.update(rights_id="", master_key_rev=0, encryption="Standard")
        self.assertEqual(extraction.related(rows, "Meta", "0100000011d90000")["path"], "matching")
        rows.append(dict(rows[0], path="ambiguous"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            extraction.related(rows, "Meta", "0100000011d90000")

    def test_full_synthetic_flow_cache_update_and_atomic_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, work = root / "input", root / "work"
            base.mkdir()
            (base / "program.nca").write_bytes(b"program")
            keys = root / "selected.keys"
            keys.write_text("synthetic keys")
            class Commands:
                def capture(self, arguments, **options):
                    if "-i" in arguments:
                        return b"Title ID: 0100000011d90000\nContent Type: Program\nContent Size: 1000\n"
                    for argument in arguments:
                        if str(argument).startswith("--exefsdir="):
                            output = Path(str(argument).split("=", 1)[1])
                            output.mkdir()
                            (output / "main").write_bytes(b"synthetic main")
                        if str(argument).startswith("--romfsdir="):
                            output = Path(str(argument).split("=", 1)[1])
                            output.mkdir()
                            (output / "asset.bin").write_bytes(b"synthetic asset")
                    return b""
            commands = Commands()
            manifest = extraction.extract_game(base, keys, work, "tool.exe", commands)
            record = json.loads(manifest.read_text())
            self.assertEqual(record["title_id"], "0100000011d90000")
            self.assertNotIn(str(keys), manifest.read_text())
            self.assertFalse(any(work.glob("extract-*")))
            with patch.object(commands, "capture", side_effect=AssertionError("cache should match")):
                self.assertEqual(extraction.extract_game(base, keys, work, "tool.exe", commands), manifest)
            (base / "program.nca").write_bytes(b"changed")
            with patch.object(commands, "capture", side_effect=subprocess.CalledProcessError(5, ["private"])):
                with self.assertRaisesRegex(ValueError, "metadata is unavailable"):
                    extraction.extract_game(base, keys, work, "tool.exe", commands)
            self.assertEqual(json.loads(manifest.read_text()), record)
            extraction.extract_game(base, keys, work, "tool.exe", commands, force=True)
            self.assertNotEqual(json.loads(manifest.read_text())["inputs"], record["inputs"])


    def test_icons_are_ingested_from_the_control_nca_and_missing_icons_defeat_the_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, work, icons = root / "input", root / "work", root / "work/icons"
            base.mkdir()
            for name in ("program", "control"):
                (base / (name + ".nca")).write_bytes(name.encode())
            keys = root / "selected.keys"
            keys.write_text("synthetic keys")
            class Commands:
                def capture(self, arguments, **options):
                    if "-i" in arguments:
                        kind = "Program" if Path(str(arguments[-1])).stem == "program" else "Control"
                        return ("Title ID: 0100000011d90000\nContent Type: %s\nContent Size: 1000\n" % kind).encode()
                    for argument in arguments:
                        if str(argument).startswith(("--exefsdir=", "--romfsdir=")):
                            output = Path(str(argument).split("=", 1)[1])
                            output.mkdir()
                            (output / ("main" if "exefs" in str(argument) else "asset.bin")).write_bytes(b"x")
                    return b""
            seen = []
            def ingest(base_control, update_control, destination, title_id):
                seen.append((base_control.name, update_control, title_id))
                Path(destination).mkdir(parents=True, exist_ok=True)
                (Path(destination) / "icons.json").write_text("{}")
            with patch("scripts.recomp.app.game_icons.ingest", side_effect=ingest):
                extraction.extract_game(base, keys, work, "tool.exe", Commands(), icons=icons)
                self.assertEqual(seen, [("control", None, "0100000011d90000")])
                extraction.extract_game(base, keys, work, "tool.exe", Commands(), icons=icons)
                self.assertEqual(len(seen), 1)  # manifest and icons match: nothing is extracted again
                (icons / "icons.json").unlink()
                extraction.extract_game(base, keys, work, "tool.exe", Commands(), icons=icons)
                self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
