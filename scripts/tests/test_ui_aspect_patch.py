import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("ui_aspect_patch", Path(__file__).resolve().parents[1] / "recomp/ui_aspect_patch.py")
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


class CandidateSourcesTests(unittest.TestCase):
    def touch(self, root, relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_mod_paths_match_ignoring_case_and_only_files_of_the_tool_are_taken(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # (the folders keep one spelling: the test also runs on case-insensitive file systems; the tool lowercases every path)
            wanted = [self.touch(root, "Data/StreamingAssets/AssetAssistant/UIs/ui/uiresidentwindow"),
                      self.touch(root, "Data/RESOURCES.ASSETS"),
                      self.touch(root, "Data/StreamingAssets/AssetAssistant/FureaiHiroba/demo/timeline/evolve")]
            self.touch(root, "Data/StreamingAssets/AssetAssistant/UIs/ui/readme.txt")   # has an extension: not a bundle
            self.touch(root, "Data/StreamingAssets/AssetAssistant/Pokemon Database/master")
            self.assertEqual(patch.candidate_sources(root), sorted(wanted))
            self.assertEqual(patch.candidate_sources(root, only="uiresidentwindow"), [wanted[0]])

    def test_demo_timeline_is_recognised_in_any_case(self):
        self.assertTrue(patch.is_demo_timeline(Path("data/streamingassets/assetassistant/fureaihiroba/DEMO/Timeline/evolve")))
        self.assertFalse(patch.is_demo_timeline(Path("Data/StreamingAssets/AssetAssistant/FureaiHiroba/demo/pokemonview")))


if __name__ == "__main__":
    unittest.main()
