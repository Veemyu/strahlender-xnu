#!/usr/bin/env python3
"""Starts the installed game for a few seconds on a runner and reports only alive or exited with a code.

The game's output goes nowhere (no console, no log), so a smoke start can never leak game data into a log. Alive after the
time is a pass (the process loaded, mapped and started rendering or waiting); an exit before that is a failure. Standard library.

Usage: smoke.py --target macos|linux|windows --installed PATH [--seconds N]
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def launch_command(target, installed):
    installed = Path(installed)
    if target == "macos":
        return [str(installed / "Contents/MacOS/BDSP")]
    if target == "windows":
        return [str(installed)]
    # Linux: the installed app is <root>/share/strahlender-xnu/app and the launcher sets the game's environment
    launcher = installed.parents[2] / "bin/strahlender-xnu"
    command = [str(launcher)]
    if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        command = ["xvfb-run", "-a", "-s", "-screen 0 1280x720x24"] + command
    return command


def stop(process):
    """Ends the process and everything it started (xvfb-run, the launcher script and the game are separate processes)."""
    pid = getattr(process, "pid", None)
    if os.name != "nt" and pid:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            process.kill()
    else:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass   # a game stuck in the kernel (no GPU on a runner) must not hold the step


def run(command, seconds, popen=subprocess.Popen, sleep=time.sleep):
    process = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=os.name != "nt")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            return "exited early with code %d" % code, False
        sleep(0.5)
    stop(process)
    return "alive after %d seconds" % seconds, True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("macos", "linux", "windows"))
    parser.add_argument("--installed", required=True)
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args(argv)
    message, ok = run(launch_command(args.target, args.installed), args.seconds)
    print("smoke: " + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
