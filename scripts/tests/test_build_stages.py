"""Tests für scripts/build_stages.py – nur synthetische Daten, keine Keys, keine Spieldateien, keine Unity-Starts."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

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
        self.assertEqual(bs.select_stages(["deploy", "masterdata", "unity"]), ["masterdata", "unity-build", "deploy"])
        self.assertEqual(bs.select_stages(["xcode"]), ["deploy"])

    def test_from_to(self):
        self.assertEqual(bs.select_stages(from_stage="masterdata", to_stage="video"), ["masterdata", "shaders", "video"])
        self.assertEqual(bs.select_stages(from_stage="assets"), ["assets", "stubs", "unity-build", "deploy"])
        self.assertEqual(bs.select_stages(to_stage="extract"), ["tools", "extract"])

    def test_from_after_to_fails(self):
        with self.assertRaises(ValueError):
            bs.select_stages(from_stage="video", to_stage="il2cpp")

    def test_only(self):
        self.assertEqual(bs.select_stages(only=["video,shaders"]), ["shaders", "video"])
        with self.assertRaises(ValueError):
            bs.select_stages(only=["video"], from_stage="tools")

    def test_unknown_stage(self):
        with self.assertRaises(ValueError) as cm:
            bs.select_stages(["nix"])
        self.assertIn("Unbekannte Stufe", str(cm.exception))

    def test_explicit_stage_outside_range_is_empty(self):
        with self.assertRaises(ValueError):
            bs.select_stages(["tools"], from_stage="video")

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bs.main(["stages", "--stage", "nix"]), bs.EX_USAGE)
            self.assertEqual(bs.main(["stages", "--only", "audio"]), 0)


class MarkerTests(unittest.TestCase):
    def test_roundtrip_and_mismatch(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertFalse(bs.marker_matches(work, "video", "abc"))
            bs.write_marker(work, "video", "abc", {"dateien": "3"})
            self.assertTrue(bs.marker_matches(work, "video", "abc"))
            self.assertFalse(bs.marker_matches(work, "video", "abd"))
            self.assertFalse(bs.marker_matches(work, "assets", "abc"))
            with open(bs.marker_path(work, "video")) as f:
                self.assertEqual(json.load(f)["notes"], {"dateien": "3"})
            bs.clear_marker(work, "video")
            self.assertFalse(bs.marker_matches(work, "video", "abc"))

    def test_corrupt_marker_is_ignored(self):
        with tempfile.TemporaryDirectory() as work:
            write(bs.marker_path(work, "video"), "{kaputt")
            self.assertFalse(bs.marker_matches(work, "video", "abc"))


class HashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "repo")
        self.work = os.path.join(self.tmp.name, "work")
        write(os.path.join(self.root, "scripts", "masterdata_export.py"), "v1")
        write(os.path.join(self.root, "scripts", "video_convert.sh"), "v1")
        write(os.path.join(self.work, "romfs", "Data", "StreamingAssets", "Movie", "a.webm"), "12345")
        write(os.path.join(self.work, "romfs", "Data", "StreamingAssets", "AssetAssistant", "b", "bundle"), "123")
        manifest = {"title_id": "t", "title_version": 1, "exefs": {"main": {"sha256": "aa"}},
                    "romfs": {"files": 2, "bytes": 8}}
        write(os.path.join(self.work, "manifest.json"), json.dumps(manifest))

    def tearDown(self):
        self.tmp.cleanup()

    def h(self, stage, **kw):
        return bs.stage_hash(stage, self.root, self.work, env={}, **kw)[0]

    def test_stable(self):
        self.assertEqual(self.h("masterdata"), self.h("masterdata"))

    def test_script_change_changes_hash(self):
        before = self.h("masterdata")
        write(os.path.join(self.root, "scripts", "masterdata_export.py"), "v2")
        self.assertNotEqual(before, self.h("masterdata"))

    def test_manifest_change_changes_hash(self):
        before = self.h("masterdata")
        with open(os.path.join(self.work, "manifest.json")) as f:
            m = json.load(f)
        m["exefs"]["main"]["sha256"] = "bb"
        write(os.path.join(self.work, "manifest.json"), json.dumps(m))
        self.assertNotEqual(before, self.h("masterdata"))

    def test_video_depends_on_profile_and_sources(self):
        base = self.h("video")
        self.assertNotEqual(base, self.h("video", profile="h265-crf14"))
        write(os.path.join(self.work, "romfs", "Data", "StreamingAssets", "Movie", "b.webm"), "1")
        self.assertNotEqual(base, self.h("video"))

    def test_assets_follow_upstream_markers_and_bundles(self):
        base = self.h("assets")
        bs.write_marker(self.work, "video", "v-neu")
        after_video = self.h("assets")
        self.assertNotEqual(base, after_video)
        write(os.path.join(self.work, "romfs", "Data", "StreamingAssets", "AssetAssistant", "c", "bundle2"), "9")
        self.assertNotEqual(after_video, self.h("assets"))

    def test_unity_build_depends_on_target_and_sources(self):
        write(os.path.join(self.root, "unity", "Assets", "Scripts", "A.cs"), "class A {}")
        a = self.h("unity-build", target="macos")
        self.assertNotEqual(a, self.h("unity-build", target="ios"))
        write(os.path.join(self.root, "unity", "Assets", "Scripts", "A.cs"), "class B {}")
        self.assertNotEqual(a, self.h("unity-build", target="macos"))
        # .DS_Store und Library zählen nicht
        write(os.path.join(self.root, "unity", "Assets", "Scripts", ".DS_Store"), "x")
        write(os.path.join(self.root, "unity", "Library", "Cache.cs"), "x")
        b = self.h("unity-build", target="macos")
        write(os.path.join(self.root, "unity", "Library", "Cache.cs"), "y")
        self.assertEqual(b, self.h("unity-build", target="macos"))

    def test_deploy_hash_never_contains_team_id(self):
        digest, parts = bs.stage_hash("deploy", self.root, self.work, "ios", env={"TEAM_ID": "ABCDE12345"})
        self.assertNotIn("ABCDE12345", json.dumps(parts))
        other, _ = bs.stage_hash("deploy", self.root, self.work, "ios", env={"TEAM_ID": "ZZZZZ99999"})
        self.assertNotEqual(digest, other)


class EnvFileTests(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "local.env")
            write(p, "# Kommentar\nOTHER=1\nexport TEAM_ID=\"AB12\"\n\nX='y'\n")
            self.assertEqual(bs.read_env_value(p, "TEAM_ID"), "AB12")
            self.assertEqual(bs.read_env_value(p, "X"), "y")
            self.assertIsNone(bs.read_env_value(p, "FEHLT"))
            self.assertIsNone(bs.read_env_value(os.path.join(d, "nix"), "TEAM_ID"))

    def test_empty_value_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "e")
            write(p, "TEAM_ID=\n")
            self.assertIsNone(bs.read_env_value(p, "TEAM_ID"))


UNITY = "/Applications/Unity/Hub/Editor/6000.3.26f1/Unity.app/Contents/MacOS/Unity"


class EditorDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "unity")
        os.makedirs(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_main_editor_found(self):
        ps = "  100 /bin/zsh\n  200 %s -projectpath %s -useHub -hubIPC\n" % (UNITY, self.project)
        self.assertEqual(bs.find_editor_pid(ps, self.project), 200)

    def test_workers_and_other_projects_ignored(self):
        ps = ("201 %s -adb2 -batchMode -name AssetImportWorker0 -projectPath %s -logFile x\n"
              "202 %s -projectpath /woanders/unity -useHub\n"
              "203 /Applications/Unity/Hub/Editor/6000.3.26f1/Unity.app/Contents/Helpers/UnityShaderCompiler %s\n"
              % (UNITY, self.project, UNITY, self.project))
        self.assertIsNone(bs.find_editor_pid(ps, self.project))

    def test_batch_editor_found_with_camel_case_flag(self):
        ps = "300 %s -batchmode -projectPath %s -quit\n" % (UNITY, self.project)
        self.assertEqual(bs.find_editor_pid(ps, self.project), 300)

    def test_no_processes(self):
        self.assertIsNone(bs.find_editor_pid("", self.project))


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root = os.path.join(t, "repo")
        self.work = os.path.join(t, "work")
        self.tools = os.path.join(t, "tools")
        self.unity = os.path.join(t, "Editor")
        self.xcode = os.path.join(t, "Xcode")
        for d in (self.root, self.work, self.xcode):
            os.makedirs(d)
        write(os.path.join(self.tools, "hactool", "hactool"))
        os.chmod(os.path.join(self.tools, "hactool", "hactool"), 0o755)
        write(os.path.join(self.tools, "il2cppdumper-bin", "Il2CppDumper.dll"))
        os.makedirs(os.path.join(self.tools, "pydeps", "UnityPy"))
        os.makedirs(os.path.join(self.tools, "pydeps", "capstone"))
        os.makedirs(os.path.join(self.tools, "pydeps", "unicorn"))
        write(os.path.join(self.root, "research", "LASRecomp", "tools", "gen.py"))
        os.makedirs(os.path.join(self.root, "research", "LASRecomp", "runtime", "nvn"))
        base = os.path.join(self.unity, bs.UNITY_VERSION)
        os.makedirs(os.path.join(base, "Unity.app"))
        os.makedirs(os.path.join(base, "Unity.app", "Contents", "PlaybackEngines", "MacStandaloneSupport",
                                 "Variations", "macos_arm64_player_nondevelopment_il2cpp"))
        os.makedirs(os.path.join(base, "PlaybackEngines", "iOSSupport"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_pf(self, stages, target="all", which=None, run=None, free=lambda p: 200.0):
        which = which or (lambda c: "/usr/bin/" + c)
        run = run or (lambda cmd, env=None, timeout=60: (True, "8.0.100" if "dotnet" in cmd[0]
                                                         else "libx265 encoder" if "-encoders" in cmd else "Xcode 26"))
        return bs.preflight(stages, target, self.root, self.work, self.tools, self.unity, self.xcode, 60,
                            which=which, run=run, free=free, home=self.tmp.name)

    def names(self, items, ok):
        return [i["name"] for i in items if i["ok"] == ok and i["level"] == "fehlt"]

    def test_everything_present(self):
        items = self.run_pf(bs.STAGES)
        self.assertEqual(self.names(items, False), [])

    def test_disk_requirement(self):
        items = self.run_pf(["masterdata"], free=lambda p: 42.0)
        self.assertEqual(self.names(items, False), ["Plattenplatz >= 60 GB frei"])
        lines, missing, disk = bs.format_preflight(items)
        self.assertTrue(disk)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = bs.main(["preflight", "--stages", "masterdata", "--root", self.root, "--work", self.work,
                          "--tools-dir", self.tools, "--unity-root", self.unity, "--min-free-gb", "100000000"])
        self.assertEqual(rc, bs.EX_DISK)

    def test_only_selected_stages_are_checked(self):
        items = self.run_pf(["audio"], which=lambda c: None)
        self.assertEqual(self.names(items, False), [])
        items = self.run_pf(["video"], which=lambda c: None)
        self.assertEqual(self.names(items, False), ["ffmpeg mit libx265"])

    def test_ffmpeg_without_x265(self):
        run = lambda cmd, env=None, timeout=60: (True, "libx264 only")
        items = self.run_pf(["video"], run=run)
        self.assertEqual(self.names(items, False), ["ffmpeg mit libx265"])

    def test_old_dotnet(self):
        run = lambda cmd, env=None, timeout=60: (True, "6.0.400")
        items = self.run_pf(["il2cpp"], run=run)
        self.assertEqual(self.names(items, False), ["dotnet >= 8"])

    def test_missing_unity_modules_and_hactool(self):
        os.rmdir(os.path.join(self.unity, bs.UNITY_VERSION, "PlaybackEngines", "iOSSupport"))
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        items = self.run_pf(["extract", "unity-build"], target="ios")
        self.assertEqual(sorted(self.names(items, False)), ["Unity-Modul iOS Build Support", "hactool"])
        # nur das iOS-Ziel gewählt: das Mac-Modul wird nicht verlangt
        items = self.run_pf(["unity-build"], target="ios")
        self.assertNotIn("Unity-Modul Mac Build Support (IL2CPP)", [i["name"] for i in items])

    def test_hactool_is_built_by_tools_stage(self):
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        items = self.run_pf(["tools", "extract"])
        self.assertEqual(self.names(items, False), [])

    def test_missing_cli_is_only_a_hint(self):
        which = lambda c: None if c == "unity" else "/usr/bin/" + c
        items = self.run_pf(["unity-build"], which=which)
        self.assertEqual(self.names(items, False), [])
        self.assertTrue(any(i["name"].startswith("unity CLI") and i["level"] == "hinweis" for i in items))

    def test_install_list_has_no_sudo(self):
        os.remove(os.path.join(self.tools, "hactool", "hactool"))
        shutil_free = lambda p: 1.0
        items = self.run_pf(bs.STAGES, which=lambda c: None, run=lambda cmd, env=None, timeout=60: (False, ""),
                            free=shutil_free)
        _, missing, _ = bs.format_preflight(items)
        text = "\n".join(bs.install_list(missing))
        self.assertNotIn("sudo ", text)
        self.assertIn("brew install ffmpeg", text)
        self.assertNotIn("Plattenplatz", text)


class RecompStageTests(unittest.TestCase):
    """Stufe recomp: Reihenfolge, Preflight (Platz, Klon, Pakete) und Eingabe-Hashes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root, self.work, self.tools = (os.path.join(t, n) for n in ("repo", "work", "tools"))
        for m in ("main", "sdk", "subsdk0", "rtld"):
            write(os.path.join(self.work, "exefs", m), m)
        write(os.path.join(self.work, "exefs", "main.npdm"), "npdm")
        os.makedirs(os.path.join(self.tools, "pydeps", "capstone"))
        os.makedirs(os.path.join(self.tools, "pydeps", "unicorn"))
        write(os.path.join(self.root, "research", "LASRecomp", "tools", "gen.py"))
        os.makedirs(os.path.join(self.root, "research", "LASRecomp", "runtime", "nvn"))
        write(os.path.join(self.root, "scripts", "recomp", "eh_gen.py"), "gen")
        write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "main.c"), "int main(){}")
        write(os.path.join(self.root, "scripts", "recomp", "app", "make_app.sh"), "#!/bin/sh")

    def tearDown(self):
        self.tmp.cleanup()

    def pf(self, free=30.0, min_free=60, which=None, run=None, target="all", stages=("recomp",)):
        which = which or (lambda c: "/usr/bin/" + c)
        run = run or (lambda cmd, env=None, timeout=60: (True, "ok"))
        return bs.preflight(list(stages), target, self.root, self.work, self.tools, "/nicht/da", "/nicht/da", min_free,
                            which=which, run=run, free=lambda p: free, home=self.tmp.name)

    def missing(self, items):
        return [i["name"] for i in items if not i["ok"] and i["level"] == "fehlt"]

    def test_order_after_il2cpp(self):
        self.assertEqual(bs.STAGES[bs.STAGES.index("il2cpp") + 1], "recomp")
        self.assertEqual(bs.normalize_stage("macapp"), "recomp")

    def test_preflight_ok_and_disk_limit_is_25_gb(self):
        self.assertEqual(self.missing(self.pf(free=30.0)), [])
        self.assertEqual(self.missing(self.pf(free=21.0)), ["Plattenplatz >= 25 GB frei (Stufe recomp)"])
        # bewusst weniger verlangt
        self.assertEqual(self.missing(self.pf(free=21.0, min_free=15)), [])

    def test_disk_exit_code(self):
        items = self.pf(free=10.0)
        lines, missing, disk = bs.format_preflight(items)
        self.assertTrue(disk)
        self.assertEqual(len(missing), 1)

    def test_missing_clone_and_packages_get_german_hints(self):
        os.rmdir(os.path.join(self.root, "research", "LASRecomp", "runtime", "nvn"))
        os.rmdir(os.path.join(self.tools, "pydeps", "unicorn"))
        items = self.pf()
        self.assertEqual(sorted(self.missing(items)), ["Python-Pakete capstone, unicorn in tools/pydeps (Generator)",
                                                       "research/LASRecomp (Generator und NVN-Schicht, MIT)"])
        _, missing, _ = bs.format_preflight(items)
        text = "\n".join(bs.install_list(missing))
        self.assertIn("git clone https://github.com/peiikai/LASRecomp", text)
        self.assertNotIn("sudo ", text)

    def test_ios_target_does_not_check_mac_app_tools(self):
        names = [i["name"] for i in self.pf(which=lambda c: None, target="ios")]
        self.assertNotIn("clang (Homebrew-LLVM im PATH)", names)

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

    def test_generator_hash_ignores_runtime(self):
        h0, _ = bs.stage_hash("recomp-gen", self.root, self.work)
        write(os.path.join(self.root, "scripts", "recomp", "rt-bdsp", "main.c"), "int main(){return 2;}")
        self.assertEqual(h0, bs.stage_hash("recomp-gen", self.root, self.work)[0])
        write(os.path.join(self.root, "scripts", "recomp", "eh_gen.py"), "gen v2")
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
