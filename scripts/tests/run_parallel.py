#!/usr/bin/env python3
"""Runs unittest modules with every test method in its own process, several at the same time, and prints the
slowest ones. Exit code is non-zero if any test fails. Standard library only.

Usage: python scripts/tests/run_parallel.py [--jobs N] scripts.tests.test_a scripts.tests.test_b ..."""
import argparse
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor


def test_ids(modules):
    ids = []

    def walk(suite):
        for item in suite:
            walk(item) if isinstance(item, unittest.TestSuite) else ids.append(item.id())

    walk(unittest.defaultTestLoader.loadTestsFromNames(modules))
    return ids


def run(test):
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "unittest", test], capture_output=True, text=True, errors="replace")
    return test, done.returncode, time.monotonic() - start, done.stdout + done.stderr


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    parser.add_argument("modules", nargs="+")
    args = parser.parse_args(argv)
    sys.path.insert(0, os.getcwd())
    ids = test_ids(args.modules)
    # The known heavy tests start first so they do not end up last in the queue.
    ids.sort(key=lambda name: not any(word in name for word in ("full_graphical", "native_pipeline", "kernel", "gui_driver")))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run, ids))
    failed = [r for r in results if r[1]]
    for test, _, seconds, output in failed:
        print(f"::group::FAILED {test} after {seconds:.0f} s")
        print(output)
        print("::endgroup::")
    for test, code, seconds, _ in sorted(results, key=lambda r: -r[2])[:8]:
        print(f"{seconds:6.1f} s  {'ok    ' if code == 0 else 'FAILED'}  {test}")
    print(f"{len(results)} tests, {len(failed)} failed")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
