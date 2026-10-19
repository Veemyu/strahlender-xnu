import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import battle_oracle_flow as bf  # noqa: E402


class FlowOracleHelpers(unittest.TestCase):
    def test_groups_cover_the_documented_functions(self):
        self.assertEqual(set(bf.GROUPS), {"actpri", "sickcont", "sickturn", "escape", "sort", "agility", "confdmg", "tables"})

    def test_random_cont_layout(self):
        import random
        r = random.Random(1)
        for kind, t in (("none", 0), ("perm", 1), ("turn", 2), ("poke", 3), ("poketurn", 4)):
            v = bf.random_cont(r, kind)
            self.assertEqual(v & 7, t)
            self.assertLess(v >> 3 & 0x1F, 32)

    def test_masks(self):
        self.assertEqual(bf.u32(-1), 0xFFFFFFFF)
        self.assertEqual(bf.u64(-1), 0xFFFFFFFFFFFFFFFF)


if __name__ == "__main__":
    unittest.main()
