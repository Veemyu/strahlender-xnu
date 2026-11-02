import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.install import windows_setup as setup  # noqa: E402


class WindowsSetupEventTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="windows-events-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, ignore_errors=True))

    def test_a_download_reports_its_bytes_and_ends_with_the_final_count(self):
        source = self.directory / "payload.bin"
        source.write_bytes(b"x" * (3 << 20))
        seen = []
        setup.fetch(source.as_uri(), self.directory / "out/payload.bin", progress=lambda _text: None,
                    on_bytes=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (3 << 20, 3 << 20))
        self.assertTrue(all(done <= total for done, total in seen))
        self.assertEqual([done for done, _ in seen], sorted(done for done, _ in seen))   # never goes backwards
        self.assertEqual((self.directory / "out/payload.bin").stat().st_size, 3 << 20)

    def test_a_wrong_checksum_still_fails_while_reporting(self):
        source = self.directory / "payload.bin"
        source.write_bytes(b"abc")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            setup.fetch(source.as_uri(), self.directory / "out/payload.bin", sha256="0" * 64, progress=lambda _t: None,
                        on_bytes=lambda *_: None)
        self.assertFalse((self.directory / "out/payload.bin").exists())

    def test_events_are_one_json_object_per_line(self):
        lines = []
        events = setup.Events(lines.append)
        events.steps(12)
        events.step("qt", "download")
        events.bytes(5, 10)
        events.step("qt", "unpack")
        decoded = [json.loads(line) for line in lines]
        self.assertEqual(decoded[0], {"event": "steps", "total": 12})
        self.assertEqual(decoded[1], {"event": "step", "index": 1, "id": "qt", "phase": "download"})
        self.assertEqual(decoded[2], {"event": "bytes", "completed": 5, "total": 10})
        self.assertEqual(decoded[3]["index"], 2)

    def test_the_setup_announces_exactly_the_steps_it_runs_in_order(self):
        tools, out = self.directory / "tools", self.directory / "out"
        for name in ("vulkan", "hactool", "generator", "NOTICES"):
            (tools / name).mkdir(parents=True)
        lines = []

        def get(url, destination, *, progress=print, on_bytes=None, **check):
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(b"archive")
            on_bytes(7, 7)

        def unpacker(archive, destination):
            name = Path(destination).name
            if name == "toolchain":
                (Path(destination) / "llvm/bin").mkdir(parents=True)
                (Path(destination) / "llvm/bin/x86_64-w64-mingw32-clang.exe").write_bytes(b"clang")
            elif name == "qtbase":
                (Path(destination) / "q/bin").mkdir(parents=True)
                (Path(destination) / "q/bin/Qt6Core.dll").write_bytes(b"qt")
            elif name == "sdl":
                (Path(destination) / "SDL3-1").mkdir(parents=True)

        selected = {"target": "x86_64"}
        with mock.patch.object(setup.build.windows, "profile", return_value=selected), \
                mock.patch.object(setup.resolve_qt, "resolve", return_value={"qtbase": "u1", "toolchain": "u2", "qt": "6.10"}), \
                mock.patch.object(setup.resolve_qt, "text", return_value="sha1 name"), \
                mock.patch.object(setup.resolve_inputs, "latest_sdl_devel", return_value={"url": "u3", "sha256": "0" * 64}), \
                mock.patch.object(setup.resolve_inputs, "latest_ffmpeg", return_value={"url": "u4", "sha256": "0" * 64}), \
                mock.patch.object(setup.dependencies, "build_qt"), mock.patch.object(setup.dependencies, "import_ffmpeg"), \
                mock.patch.object(setup.build, "import_sdl"), mock.patch.object(setup.pipeline, "write_catalog"):
            setup.setup(tools, out, progress=lambda _t: None, get=get, unpacker=unpacker, events=setup.Events(lines.append))
        decoded = [json.loads(line) for line in lines]
        self.assertEqual(decoded[0], {"event": "steps", "total": setup.STEP_COUNT})
        steps = [(e["id"], e["phase"]) for e in decoded if e["event"] == "step"]
        self.assertEqual(steps, [("versions", "work"), ("qt", "download"), ("qt", "unpack"), ("toolchain", "download"),
                                 ("toolchain", "unpack"), ("sdl", "download"), ("sdl", "unpack"), ("ffmpeg", "download"),
                                 ("ffmpeg", "unpack"), ("bundle", "work"), ("tools", "work"), ("register", "work")])
        self.assertEqual(len(steps), setup.STEP_COUNT)
        self.assertEqual([e["index"] for e in decoded if e["event"] == "step"], list(range(1, setup.STEP_COUNT + 1)))
        self.assertTrue(any(e["event"] == "bytes" for e in decoded))

    def test_without_events_the_downloads_are_called_exactly_as_before(self):
        calls = []

        def get(url, destination, *, progress=print, **check):   # an old-style fake: no on_bytes
            calls.append(sorted(check))
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(b"a")

        tools, out = self.directory / "tools", self.directory / "out"
        for name in ("vulkan", "hactool", "generator", "NOTICES"):
            (tools / name).mkdir(parents=True)

        def unpacker(archive, destination):
            name = Path(destination).name
            if name == "toolchain":
                (Path(destination) / "llvm/bin").mkdir(parents=True)
                (Path(destination) / "llvm/bin/x86_64-w64-mingw32-clang.exe").write_bytes(b"clang")
            elif name == "qtbase":
                (Path(destination) / "q/bin").mkdir(parents=True)
                (Path(destination) / "q/bin/Qt6Core.dll").write_bytes(b"qt")
            elif name == "sdl":
                (Path(destination) / "SDL3-1").mkdir(parents=True)

        with mock.patch.object(setup.build.windows, "profile", return_value={"target": "x86_64"}), \
                mock.patch.object(setup.resolve_qt, "resolve", return_value={"qtbase": "u1", "toolchain": "u2", "qt": "6.10"}), \
                mock.patch.object(setup.resolve_qt, "text", return_value="sha1 name"), \
                mock.patch.object(setup.resolve_inputs, "latest_sdl_devel", return_value={"url": "u3", "sha256": "0" * 64}), \
                mock.patch.object(setup.resolve_inputs, "latest_ffmpeg", return_value={"url": "u4", "sha256": "0" * 64}), \
                mock.patch.object(setup.dependencies, "build_qt"), mock.patch.object(setup.dependencies, "import_ffmpeg"), \
                mock.patch.object(setup.build, "import_sdl"), mock.patch.object(setup.pipeline, "write_catalog"):
            setup.setup(tools, out, progress=lambda _t: None, get=get, unpacker=unpacker)
        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()
