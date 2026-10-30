#!/usr/bin/env python3
"""Runs unittest modules as separate processes at the same time and prints each one's output and run time.

Usage: python scripts/tests/run_parallel.py scripts.tests.test_a scripts.tests.test_b ...
Exit code is non-zero if any module fails. Standard library only."""
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


def run(module):
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "unittest", "--durations", "5", module], capture_output=True, text=True, errors="replace")
    return module, done.returncode, time.monotonic() - start, done.stdout + done.stderr


def main(modules):
    with ThreadPoolExecutor(max_workers=len(modules)) as pool:
        results = list(pool.map(run, modules))
    for module, code, seconds, output in results:
        print(f"::group::{module}: {'ok' if code == 0 else 'FAILED'} in {seconds:.0f} s")
        print(output)
        print("::endgroup::")
    for module, code, seconds, _ in results:
        print(f"{seconds:6.0f} s  {'ok    ' if code == 0 else 'FAILED'}  {module}")
    return int(any(code for _, code, _, _ in results))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
