import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.install import vk_shaders

REPO = Path(__file__).resolve().parents[2]
TOOLS = {"cc": ["cc"], "cflags": ["-I", "inc"], "libs": ["-L", "lib", "-lshaderc_shared"], "suffix": "",
         "toolchain": "cc 1", "shaderc": "sc 1"}


def make_root(base):
    root = Path(base) / "root"
    for name in vk_shaders.TRANSLATOR_SOURCES:
        path = root / "shader_translator" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("translator " + name)
    for name in vk_shaders.WARM_SOURCES + vk_shaders.SCRIPT_SOURCES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source " + name)
    return root


def make_work(base, with_bundle=True):
    work = Path(base) / "work"
    if with_bundle:
        bundle = work / vk_shaders.BUNDLES[0]
        bundle.parent.mkdir(parents=True)
        bundle.write_bytes(b"x" * 10)
    return work


class FakeRunner:
    """Stands in for the extractor, compilers, translator and spirv_warm; records the command lines."""

    def __init__(self, work, warm_files=3, fail=None):
        self.work, self.warm_files, self.fail, self.commands = work, warm_files, fail, []

    def __call__(self, command, env=None, cwd=None, on_line=None):
        self.commands.append(command)
        name = Path(command[0]).name
        place = vk_shaders.folders(self.work)
        if self.fail and self.fail in " ".join(command):
            on_line("boom")
            return 1
        if "shader_extract_blobs.py" in " ".join(command):
            place["blobs"].mkdir(parents=True, exist_ok=True)
            index = {"blobs": [{"stage": "vs", "hash": "aa"}, {"stage": "fs", "hash": "bb"}, {"stage": "cs", "hash": "cc"}]}
            (place["blobs"] / "index.json").write_text(json.dumps(index))
        elif command[0] == "cc":
            Path(command[command.index("-o") + 1]).write_text("binary")
        elif name == "maxwell2msl":
            for number in range(self.warm_files):
                (place["glsl"] / ("v_%016x.glsl" % number)).write_text("void main(){}")
        elif name == "spirv_warm":
            out = Path(command[command.index("--out") + 1]) / "spirv"
            out.mkdir(parents=True)
            for number in range(self.warm_files):
                (out / ("%016x.spv" % number)).write_bytes(b"spv")
            on_line("warm: total %d" % self.warm_files)
            on_line("warm: progress 2 of %d" % self.warm_files)
            on_line("warm: done compiled %d present 0 failed 0" % self.warm_files)
        return 0


class StampTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)
        self.work = make_work(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_stamp_is_stable_and_follows_everything_the_output_depends_on(self):
        first = vk_shaders.stamp(self.root, self.work, "cc 1", "sc 1")
        self.assertEqual(first, vk_shaders.stamp(self.root, self.work, "cc 1", "sc 1"))
        self.assertNotEqual(first, vk_shaders.stamp(self.root, self.work, "cc 2", "sc 1"))
        self.assertNotEqual(first, vk_shaders.stamp(self.root, self.work, "cc 1", "sc 2"))
        (self.root / "shader_translator" / "translate.c").write_text("changed")
        changed = vk_shaders.stamp(self.root, self.work, "cc 1", "sc 1")
        self.assertNotEqual(first, changed)
        (self.work / vk_shaders.BUNDLES[0]).write_bytes(b"y" * 11)
        self.assertNotEqual(changed, vk_shaders.stamp(self.root, self.work, "cc 1", "sc 1"))

    def test_the_cache_key_of_the_renderer_and_the_tool_is_one_definition(self):
        header = (REPO / "scripts/recomp/runtime/nvn/vulkan/src/nvn/vulkan/spv_cache.h").read_text()
        for user in ("src/nvn/vulkan/shaders.c", "spirv_warm.c"):
            text = (REPO / "scripts/recomp/runtime/nvn/vulkan" / user).read_text()
            self.assertIn("spv_cache.h", text)
            self.assertNotIn("0xcbf29ce484222325", text)
        self.assertIn("0xcbf29ce484222325", header)

    def test_the_progress_line_of_spirv_warm_is_parsed(self):
        self.assertEqual(vk_shaders.parse_progress("warm: progress 150 of 2739"), (150, 2739))
        self.assertIsNone(vk_shaders.parse_progress("warm: done compiled 5 present 0 failed 0"))
        self.assertIsNone(vk_shaders.parse_progress("shaders: translating"))

    def test_only_the_vulkan_targets_apply(self):
        for target in ("windows", "windows-arm64", "linux"):
            self.assertTrue(vk_shaders.applies(target))
        for target in ("macos", "ios", "android"):
            self.assertFalse(vk_shaders.applies(target))

    def test_tool_commands_name_the_sources_and_libraries(self):
        commands = vk_shaders.tool_commands(self.root, Path("out"), {**TOOLS, "suffix": ".exe"})
        binary, translator = commands["translator"]
        self.assertEqual(binary, Path("out/maxwell2msl.exe"))
        self.assertIn(str(self.root / "shader_translator/main.c"), translator)
        _binary, warm = commands["warm"]
        self.assertEqual(warm[0], "cc")
        self.assertIn("-lshaderc_shared", warm)
        self.assertIn("-I", warm)

    def test_the_batch_list_names_vertex_and_fragment_programs_only(self):
        blobs = Path(self.temp.name) / "blobs"
        blobs.mkdir()
        index = {"blobs": [{"stage": "vs", "hash": "a1"}, {"stage": "fs", "hash": "b2"}, {"stage": "cs", "hash": "c3"}]}
        (blobs / "index.json").write_text(json.dumps(index))
        listing = Path(self.temp.name) / "list.txt"
        self.assertEqual(vk_shaders.translation_list(blobs, listing), 2)
        lines = listing.read_text().splitlines()
        self.assertEqual([line.split()[0] for line in lines], ["vs", "fs"])


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)
        self.work = make_work(self.temp.name)
        self.log, self.progress = [], []

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, runner, tools=TOOLS, **options):
        return vk_shaders.prepare(self.root, self.work, tools, self.log.append, lambda *counts: self.progress.append(counts),
                                  python="python", run=runner, **options)

    def test_a_build_fills_the_cache_reports_progress_and_is_reused_while_nothing_changes(self):
        runner = FakeRunner(self.work)
        self.assertEqual(self.prepare(runner), ("complete", "3"))
        place = vk_shaders.folders(self.work)
        self.assertEqual(vk_shaders.prebuilt_count(place["prebuilt"]), 3)
        self.assertFalse(place["glsl"].exists())
        self.assertFalse(place["stage"].exists())
        self.assertEqual(self.progress, [(2, 3)])
        self.assertEqual(self.log[0], "shaders: reading the shader programs of the game")
        self.assertIn("shaders: compiling the SPIR-V shaders", self.log)
        self.assertEqual(self.log[-1], "shaders: 3 SPIR-V shaders ready")
        translate = [command for command in runner.commands if Path(command[0]).name == "maxwell2msl"][0]
        self.assertEqual(translate[translate.index("--vs-out-mask") + 1], vk_shaders.VS_OUT_MASK)
        self.assertIn("--glsl", translate)

        again = FakeRunner(self.work)
        self.assertEqual(self.prepare(again)[0], "reused")
        self.assertEqual(again.commands, [])

        (self.root / "shader_translator" / "translate.c").write_text("a new translator")
        rebuilt = FakeRunner(self.work, warm_files=4)
        self.assertEqual(self.prepare(rebuilt), ("complete", "4"))
        self.assertEqual(vk_shaders.prebuilt_count(place["prebuilt"]), 4)

    def test_a_different_shaderc_rebuilds(self):
        self.prepare(FakeRunner(self.work))
        runner = FakeRunner(self.work)
        self.assertEqual(self.prepare(runner, {**TOOLS, "shaderc": "sc 2"})[0], "complete")
        self.assertTrue(runner.commands)

    def test_a_missing_shader_bundle_skips_without_running_anything(self):
        work = make_work(Path(self.temp.name) / "other", with_bundle=False)
        runner = FakeRunner(work)
        status, _detail = vk_shaders.prepare(self.root, work, TOOLS, self.log.append, run=runner)
        self.assertEqual(status, "skipped")
        self.assertEqual(runner.commands, [])

    def test_every_failure_skips_and_leaves_no_half_written_cache(self):
        for failing in ("shader_extract_blobs.py", "main.c", "spirv_warm.c", "--batch", "--out"):
            with self.subTest(failing=failing):
                self.log.clear()
                shutil.rmtree(vk_shaders.folders(self.work)["base"], ignore_errors=True)
                status, _detail = self.prepare(FakeRunner(self.work, fail=failing), force=True)
                self.assertEqual(status, "skipped")
                self.assertTrue(any(line.startswith("shaders: failed") for line in self.log), self.log)
                place = vk_shaders.folders(self.work)
                self.assertFalse(place["stage"].exists())
                self.assertFalse(place["stamp"].exists())

    def test_missing_tools_skip_and_a_failing_tool_lookup_does_not_raise(self):
        def broken():
            raise vk_shaders.Missing("the shaderc development package is missing")
        self.assertEqual(self.prepare(FakeRunner(self.work), broken)[0], "skipped")
        self.assertIn("shaders: skipped: the shaderc development package is missing", self.log)

    def test_too_few_compiled_files_are_not_accepted(self):
        class Few(FakeRunner):
            def __call__(self, command, env=None, cwd=None, on_line=None):
                status = super().__call__(command, env, cwd, on_line)
                if Path(command[0]).name == "spirv_warm":
                    for file in sorted((Path(command[command.index("--out") + 1]) / "spirv").glob("*.spv"))[1:]:
                        file.unlink()
                return status
        self.assertEqual(self.prepare(Few(self.work, warm_files=6))[0], "skipped")
        self.assertEqual(vk_shaders.prebuilt_count(vk_shaders.folders(self.work)["prebuilt"]), 0)


if __name__ == "__main__":
    unittest.main()
