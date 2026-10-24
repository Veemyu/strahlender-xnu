"""Hardware-based compiler concurrency must use fast hosts and protect small ones."""

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "recomp" / "parallel_jobs.py"
SPEC = importlib.util.spec_from_file_location("parallel_jobs", SCRIPT)
parallel_jobs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parallel_jobs)


class RecompParallelJobsTests(unittest.TestCase):
    def test_eight_core_sixteen_gib_host_uses_all_cores(self):
        self.assertEqual(parallel_jobs.choose_jobs(8, 16 * parallel_jobs.GIB), 8)

    def test_large_host_scales_beyond_the_old_four_job_limit(self):
        self.assertEqual(parallel_jobs.choose_jobs(32, 64 * parallel_jobs.GIB), 32)
        self.assertEqual(parallel_jobs.choose_jobs(32, 32 * parallel_jobs.GIB), 20)

    def test_small_host_limits_memory_pressure(self):
        self.assertEqual(parallel_jobs.choose_jobs(8, 4 * parallel_jobs.GIB), 1)
        self.assertEqual(parallel_jobs.choose_jobs(8, 8 * parallel_jobs.GIB), 4)
        self.assertEqual(parallel_jobs.choose_jobs(2, 16 * parallel_jobs.GIB), 2)


if __name__ == "__main__":
    unittest.main()
