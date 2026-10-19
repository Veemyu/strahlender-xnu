import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import material_export as me  # noqa: E402


class ExternalTextureTests(unittest.TestCase):
    EXT = ["Library/unity default resources", "archive:/CAB-aa/CAB-aa", "archive:/CAB-bb/CAB-bb"]

    def mats(self):
        return [{"name": "m", "textures": {
            "_A": {"file": 0, "pathId": 5, "texName": "local"},          # im selben Bundle: unberuehrt
            "_B": {"file": 2, "pathId": 7},                               # Nachbar-Bundle
            "_C": {"file": 3, "pathId": 9},                               # unbekannt
            "_D": {"file": 1, "pathId": 3},                               # eingebaute Ressource ohne CAB
            "_E": {"scale": [1, 1], "offset": [0, 0]},                    # leerer Slot
        }}]

    def test_external_cab(self):
        self.assertEqual("CAB-aa", me.external_cab("archive:/CAB-aa/CAB-aa"))
        self.assertIsNone(me.external_cab("Library/unity default resources"))

    def test_fill(self):
        calls = []

        def lookup(cab, pid):
            calls.append((cab, pid))
            return {"texName": "T", "width": 4, "height": 8, "extBundle": "X/y"} if (cab, pid) == ("CAB-aa", 7) else None

        mats = self.mats()
        done, rest = me.fill_external_textures(mats, self.EXT, lookup)
        self.assertEqual((1, 2), (done, rest))
        t = mats[0]["textures"]
        self.assertEqual("T", t["_B"]["texName"])
        self.assertEqual("X/y", t["_B"]["extBundle"])
        self.assertEqual("local", t["_A"]["texName"])
        self.assertNotIn("texName", t["_C"])
        self.assertEqual([("CAB-aa", 7), ("CAB-bb", 9)], calls)   # eingebaute Ressource und leere Slots werden nicht gesucht


if __name__ == "__main__":
    unittest.main()
