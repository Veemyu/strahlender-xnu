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


class FakeUnityPy(object):
    """Just enough of UnityPy for patch_bundle: a prefab root with a full-screen "Window" child."""

    class Object(object):
        def __init__(self, kind, path_id, data):
            self.type = type("Kind", (), {"name": kind})()
            self.path_id = path_id
            self.data = data
            self.byte_start, self.byte_size = 0, 0

        def read(self):
            return type("Read", (), {"m_Name": self.data})()

        def read_typetree(self):
            return self.data

    def __init__(self, prefab):
        def rect(owner, father):
            return {"m_GameObject": {"m_PathID": owner}, "m_Father": {"m_PathID": father},
                    "m_AnchorMin": {"x": 0.5, "y": 0.5}, "m_AnchorMax": {"x": 0.5, "y": 0.5},
                    "m_SizeDelta": {"x": 1280.0, "y": 720.0}, "m_AnchoredPosition": {"x": 0.0, "y": 0.0}, "m_Pivot": {"x": 0.5, "y": 0.5}}
        kind = self.Object
        self.objects = [kind("GameObject", 1, prefab), kind("GameObject", 2, "Window"),
                        kind("RectTransform", 11, rect(1, 0)), kind("RectTransform", 12, rect(2, 11))]

    def load(self, _path):
        return self


class PatchBundleTests(unittest.TestCase):
    def count(self, prefab):
        return patch.patch_bundle(FakeUnityPy(prefab), Path("bundle"), Path("unused"), True)

    def test_screens_are_stretched_but_the_boxes_the_game_places_by_their_size_are_not(self):
        self.assertEqual(self.count("Bag"), 2)
        # ContextMenu holds the Yes/No box of the starter selection: stretched, its size reads 0 and the box leaves the screen.
        self.assertEqual(self.count("ContextMenu"), 0)
        self.assertEqual(self.count("ContextMenu_Scroll"), 0)


if __name__ == "__main__":
    unittest.main()
