"""Tests for scripts/build_stages.py: synthetic data only, no keys, no game files, no Unity starts."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_stages as bs  # noqa: E402


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class StageSelectionTests(unittest.TestCase):
    def test_all_is_ordered(self):
        self.assertEqual(bs.select_stages(["all"]), bs.STAGES)
        self.assertEqual(bs.select_stages([]), bs.STAGES)

    def test_order_is_canonical_and_aliases_work(self):
        self.assertEqual(bs.select_stages(["recomp", "extract", "tools"]), ["tools", "extract", "recomp"])
        self.assertEqual(bs.select_stages(["macapp"]), ["recomp"])

    def test_from_to(self):
        self.assertEqual(bs.select_stages(from_stage="extract", to_stage="recomp"), ["extract", "recomp"])
        self.assertEqual(bs.select_stages(from_stage="recomp"), ["recomp"])
        self.assertEqual(bs.select_stages(to_stage="extract"), ["tools", "extract"])

    def test_from_after_to_fails(self):
        with self.assertRaises(ValueError):
            bs.select_stages(from_stage="recomp", to_stage="extract")

    def test_removed_stages_are_unknown(self):
        for name in ("il2cpp", "masterdata", "video", "audio", "shaders", "shader"):
            with self.assertRaises(ValueError):
                bs.select_stages([name])

    def test_only(self):
        self.assertEqual(bs.select_stages(only=["recomp,tools"]), ["tools", "recomp"])
        with self.assertRaises(ValueError):
            bs.select_stages(only=["recomp"], from_stage="tools")

    def test_unknown_stage(self):
        with self.assertRaises(ValueError) as cm:
            bs.select_stages(["nix"])
        self.assertIn("Unknown stage", str(cm.exception))

    def test_explicit_stage_outside_range_is_empty(self):
        with self.assertRaises(ValueError):
            bs.select_stages(["tools"], from_stage="recomp")

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bs.main(["stages", "--stage", "nix"]), bs.EX_USAGE)
            self.assertEqual(bs.main(["stages", "--only", "recomp"]), 0)


class MarkerTests(unittest.TestCase):
    def test_roundtrip_and_mismatch(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertFalse(bs.marker_matches(work, "extract", "abc"))
            bs.write_marker(work, "extract", "abc", {"files": "3"})
            self.assertTrue(bs.marker_matches(work, "extract", "abc"))
            self.assertFalse(bs.marker_matches(work, "extract", "abd"))
            self.assertFalse(bs.marker_matches(work, "assets", "abc"))
            with open(bs.marker_path(work, "extract")) as f:
                self.assertEqual(json.load(f)["notes"], {"files": "3"})
            bs.clear_marker(work, "extract")
            self.assertFalse(bs.marker_matches(work, "extract", "abc"))

    def test_corrupt_marker_is_ignored(self):
        with tempfile.TemporaryDirectory() as work:
            write(bs.marker_path(work, "extract"), "{kaputt")
            self.assertFalse(bs.marker_matches(work, "extract", "abc"))


class HashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "repo")
        self.work = os.path.join(self.tmp.name, "work")
        write(os.path.join(self.root, "scripts", "recomp", "build_all.sh"), "v1")
        manifest = {"title_id": "t", "title_version": 1, "exefs": {"main": {"sha256": "aa"}},
                    "romfs": {"files": 2, "bytes": 8}}
        write(os.path.join(self.work, "manifest.json"), json.dumps(manifest))

    def tearDown(self):
        self.tmp.cleanup()

    def h(self, stage, **kw):
        return bs.stage_hash(stage, self.root, self.work, env={}, **kw)[0]

    def test_stable(self):
        self.assertEqual(self.h("recomp"), self.h("recomp"))

    def test_script_change_changes_hash(self):
        before = self.h("recomp")
        write(os.path.join(self.root, "scripts", "recomp", "build_all.sh"), "v2")
        self.assertNotEqual(before, self.h("recomp"))

    def test_manifest_change_changes_hash(self):
        before = self.h("extract")
        with open(os.path.join(self.work, "manifest.json")) as f:
            m = json.load(f)
        m["exefs"]["main"]["sha256"] = "bb"
        write(os.path.join(self.work, "manifest.json"), json.dumps(m))
        self.assertNotEqual(before, self.h("extract"))


class EnvFileTests(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "local.env")
            write(p, "# Kommentar\nOTHER=1\nexport TEAM_ID=\"AB12\"\n\nX='y'\n")
            self.assertEqual(bs.read_env_value(p, "TEAM_ID"), "AB12")
            self.assertEqual(bs.read_env_value(p, "X"), "y")
            self.assertIsNone(bs.read_env_value(p, "MISSING"))
            self.assertIsNone(bs.read_env_value(os.path.join(d, "nix"), "TEAM_ID"))

    def test_empty_value_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "e")
            write(p, "TEAM_ID=\n")
            self.assertIsNone(bs.read_env_value(p, "TEAM_ID"))


class PreflightTests(unittest.TestCase):
    def test_selected_git_is_checked_instead_of_a_shadowing_path_entry(self):
        with patch.dict(os.environ, BDSP_GIT="/selected/system/git"):
            items = self.run_pf(["tools"], target="linux",
                                which=lambda name: name if name == "/selected/system/git" else None)
        git = next(item for item in items if item["name"] == "git (for hactool)")
        self.assertTrue(git["ok"])
        self.assertEqual(git["detail"], "/selected/system/git")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root = os.path.join(t, "repo")
        self.work = os.path.join(t, "work")
        self.tools = os.path.join(t, "tools")
        for d in (self.root, self.work):
            os.makedirs(d)
        write(os.path.join(self.tools, "hactool", "hactool"))
        os.chmod(os.path.join(self.tools, "hactool", "hactool"), 0o755)
        os.makedirs(os.path.join(self.tools, "pydeps", "UnityPy"))
        write(os.path.join(self.tools, "pydeps", "lz4", "__init__.py"), "")
        write(os.path.join(self.tools, "pydeps", "lz4", "block.py"), "")
        os.makedirs(os.path.join(self.tools, "pydeps", "capstone"))
        os.makedirs(os.path.join(self.tools, "pydeps", "unicorn"))
        write(os.path.join(self.root, "scripts", "recomp", "native-generator", "src", "generator.c"))
        write(os.path.join(self.root, "scripts", "recomp", "upstream", "runtime", "cpu.h"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_pf(self, stages, target="all", which=None, run=None, free=lambda p: 200.0):
        which = which or (lambda c: "/usr/bin/" + c)
        run = run or (lambda cmd, env=None, timeout=60: (True, "ok"))
        return bs.preflight(stages, target, self.root, self.work, self.tools, bs.MIN_FREE_GB,
                            which=which, run=run, free=free)

    def names(self, items, ok):
        return [i["name"] for i in items if i["ok"] == ok and i["level"] == "missing"]

    def test_everything_present(self):
        items = self.run_pf(bs.STAGES)
        self.assertEqual(self.names(items, False), [])

    def write_icons(self, variants):
        source = os.path.join(self.work, "recomp", "icons", "source")
        write(os.path.join(source, "icons.json"), json.dumps({"schema": 1, "variants": variants}))
        return source

    def test_recomp_needs_the_original_icons(self):
        items = self.run_pf(["recomp"], target="macos")
        self.assertIn("Original game icons", self.names(items, False))
        self.write_icons([])
        self.assertIn("Original game icons", self.names(self.run_pf(["recomp"], target="macos"), False))
        self.write_icons([{"id": "en-US"}])
        items = self.run_pf(["recomp"], target="macos")
        self.assertNotIn("Original game icons", self.names(items, False))

    def test_icons_may_come_from_the_extract_stage_of_the_same_run(self):
        items = self.run_pf(["extract", "recomp"], target="macos")
        self.assertNotIn("Original game icons", self.names(items, False))
        self.assertTrue(any(i["name"] == "Original game icons" and i["level"] == "note" for i in items))

    def test_disk_requirement(self):
        items = self.run_pf(["extract"], free=lambda p: 32.0)
        self.assertEqual(self.names(items, False), ["Disk space >= 40 GB free"])
        lines, missing, disk = bs.format_preflight(items)
        self.assertTrue(disk)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = bs.main(["preflight", "--stages", "extract", "--root", self.root, "--work", self.work,
                          "--tools-dir", self.tools, "--min-free-gb", "100000000"])
        self.assertEqual(rc, bs.EX_DISK)

    def test_free_space_uses_decimal_gigabytes(self):
        with patch.object(bs.shutil, "disk_usage", return_value=type("Usage", (), {"free": 50_000_000_000})()):
            self.assertEqual(bs.free_gb(self.work), 50.0)

    def test_only_selected_stages_are_checked(self):
        items = self.run_pf(["extract"], which=lambda c: None)
        self.assertEqual(self.names(items, False), [])
        items = self.run_pf(["tools"], which=lambda c: None)
        self.assertEqual(self.names(items, False), ["git (for hactool)", "make (for hactool)", "cc (for hactool)"])

    def test_missing_hactool_is_reported_for_extract(self):
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        items = self.run_pf(["extract"])
        self.assertEqual(self.names(items, False), ["hactool"])

    def test_hactool_is_built_by_tools_stage(self):
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        items = self.run_pf(["tools", "extract"])
        self.assertEqual(self.names(items, False), [])

    def test_install_list_has_no_sudo(self):
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        shutil_free = lambda p: 1.0
        items = self.run_pf(bs.STAGES, which=lambda c: None, run=lambda cmd, env=None, timeout=60: (False, ""),
                            free=shutil_free)
        _, missing, _ = bs.format_preflight(items)
        text = "\n".join(bs.install_list(missing))
        self.assertNotIn("sudo ", text)
        self.assertIn("brew install sdl3 ffmpeg", text)
        self.assertNotIn("Disk space", text)


class RecompStageTests(unittest.TestCase):
    """Stage recomp: order, preflight (space, clone, packages) and input hashes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root, self.work, self.tools = (os.path.join(t, n) for n in ("repo", "work", "tools"))
        for m in ("main", "sdk", "subsdk0", "rtld"):
            write(os.path.join(self.work, "exefs", m), m)
        write(os.path.join(self.work, "exefs", "main.npdm"), "npdm")
        os.makedirs(os.path.join(self.tools, "pydeps", "capstone"))
        os.makedirs(os.path.join(self.tools, "pydeps", "unicorn"))
        write(os.path.join(self.root, "scripts", "recomp", "native-generator", "src", "generator.c"))
        write(os.path.join(self.root, "scripts", "recomp", "upstream", "runtime", "cpu.h"))
        write(os.path.join(self.root, "scripts", "recomp", "native-generator", "src", "generator.c"), "gen")
        write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "main.c"), "int main(){}")
        write(os.path.join(self.root, "scripts", "recomp", "app", "make_app.sh"), "#!/bin/sh")
        write(os.path.join(self.work, "recomp", "icons", "source", "icons.json"),
              json.dumps({"schema": 1, "variants": [{"id": "en-US"}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def pf(self, free=30.0, min_free=60, which=None, run=None, target="all", stages=("recomp",)):
        which = which or (lambda c: "/usr/bin/" + c)
        run = run or (lambda cmd, env=None, timeout=60: (True, "ok"))
        return bs.preflight(list(stages), target, self.root, self.work, self.tools, min_free,
                            which=which, run=run, free=lambda p: free)

    def missing(self, items):
        return [i["name"] for i in items if not i["ok"] and i["level"] == "missing"]

    def test_order_after_extract(self):
        self.assertEqual(bs.STAGES[bs.STAGES.index("extract") + 1], "recomp")
        self.assertEqual(bs.normalize_stage("macapp"), "recomp")

    def test_preflight_ok_and_disk_limit_is_25_gb(self):
        self.assertEqual(self.missing(self.pf(free=30.0)), [])
        self.assertEqual(self.missing(self.pf(free=21.0)), ["Disk space >= 25 GB free (stage recomp)"])
        # bewusst weniger verlangt
        self.assertEqual(self.missing(self.pf(free=21.0, min_free=15)), [])

    def test_disk_exit_code(self):
        items = self.pf(free=10.0)
        lines, missing, disk = bs.format_preflight(items)
        self.assertTrue(disk)
        self.assertEqual(len(missing), 1)

    def test_missing_clone_and_packages_get_hints(self):
        os.remove(os.path.join(self.root, "scripts", "recomp", "upstream", "runtime", "cpu.h"))
        def run(cmd, env=None, timeout=60):
            return (cmd[-1] != "--check-unicorn", "")

        items = self.pf(run=run)
        self.assertEqual(sorted(self.missing(items)), ["Native generator sources and runtime headers",
                                                       "Unicorn 2.1.4 C engine and headers (native generator)"])
        _, missing, _ = bs.format_preflight(items)
        text = "\n".join(bs.install_list(missing))
        self.assertIn("git checkout -- scripts/recomp/native-generator", text)
        self.assertNotIn("sudo ", text)

    def test_generator_packages_are_imported_with_pydeps_on_pythonpath(self):
        commands = []

        def run(cmd, env=None, timeout=60):
            commands.append((cmd, env))
            return (cmd[-1] != "--check-unicorn", "")

        items = self.pf(run=run)
        self.assertIn("Unicorn 2.1.4 C engine and headers (native generator)", self.missing(items))
        generator = next(env for cmd, env in commands if cmd[-1] == "--check-unicorn")
        self.assertEqual(generator["PYTHONPATH"].split(os.pathsep)[0], os.path.join(self.tools, "pydeps"))

    def test_private_runtime_checks_only_its_isolated_interpreter(self):
        commands = []

        def run(cmd, env=None, timeout=60):
            commands.append((cmd, env))
            return True, ""

        with patch.dict(os.environ, {"BDSP_INSTALLER_PRIVATE_RUNTIME": "1"}):
            self.pf(run=run)
        imports = [(cmd, env) for cmd, env in commands if cmd[-1].startswith("import ")]
        self.assertTrue(imports)
        self.assertTrue(all(cmd[0] == sys.executable and cmd[1] == "-I" for cmd, _ in imports))
        self.assertTrue(all(env.get("PYTHONPATH") == os.environ.get("PYTHONPATH") for _, env in imports))

    def test_ios_target_does_not_check_mac_app_tools(self):
        names = [i["name"] for i in self.pf(which=lambda c: None, target="ios")]
        self.assertNotIn("clang (Homebrew LLVM in PATH)", names)

    def test_hash_reacts_to_module_runtime_and_options(self):
        env = {"XNU_RECOMP_OPTS": "o0kb=300"}
        h0, _ = bs.stage_hash("recomp", self.root, self.work, env=env)
        self.assertEqual(h0, bs.stage_hash("recomp", self.root, self.work, env=env)[0])
        write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "main.c"), "int main(){return 1;}")
        h1, _ = bs.stage_hash("recomp", self.root, self.work, env=env)
        self.assertNotEqual(h0, h1)
        write(os.path.join(self.work, "exefs", "main"), "anderer Dump")
        h2, _ = bs.stage_hash("recomp", self.root, self.work, env=env)
        self.assertNotEqual(h1, h2)
        h3, _ = bs.stage_hash("recomp", self.root, self.work, env={"XNU_RECOMP_OPTS": "o0kb=1000"})
        self.assertNotEqual(h2, h3)

    def test_nvn_stamp_covers_src_translator_and_prepare(self):
        nvn = os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "nvn")
        os.makedirs(nvn, exist_ok=True)
        for name in ("prepare.sh", "hash.inc.sh"):
            shutil.copy(os.path.join(os.path.dirname(bs.__file__), "recomp", "rt-bdsp", "nvn", name), nvn)
        for rel in ("nvn/src/nvn/metal.m", "nvn/src/rt.h", "shader_translator/translate.c", "shader_translator/shader.h"):
            write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", rel) if rel.startswith("nvn") else os.path.join(self.root, rel), "v1")
        rec = os.path.join(self.root, "scripts", "recomp")
        s0 = bs.nvn_source_stamp(rec)
        self.assertEqual(s0, bs.nvn_source_stamp(rec))
        for path in (os.path.join(nvn, "src", "rt.h"), os.path.join(self.root, "shader_translator", "shader.h"),
                     os.path.join(nvn, "prepare.sh")):
            old = open(path).read()
            write(path, old + "\n# x")
            self.assertNotEqual(s0, bs.nvn_source_stamp(rec), path)
            write(path, old)
        self.assertEqual(s0, bs.nvn_source_stamp(rec))

    def test_generator_hash_ignores_runtime(self):
        h0, _ = bs.stage_hash("recomp-gen", self.root, self.work)
        write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "main.c"), "int main(){return 2;}")
        self.assertEqual(h0, bs.stage_hash("recomp-gen", self.root, self.work)[0])
        write(os.path.join(self.root, "scripts", "recomp", "native-generator", "src", "generator.c"), "gen v2")
        self.assertNotEqual(h0, bs.stage_hash("recomp-gen", self.root, self.work)[0])


class TreeSizeTests(unittest.TestCase):
    def test_counts_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "a", "x"), "123")
            write(os.path.join(d, "y"), "45")
            write(os.path.join(d, ".DS_Store"), "ignored")
            self.assertEqual(bs.tree_size(d), (2, 5))


if __name__ == "__main__":
    unittest.main()
