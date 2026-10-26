#!/usr/bin/env python3
"""Build the real desktop app, capture its dark-mode UI states, and verify the PNG matrix.

Only Python's standard library is required. The app must be allowed to open a
desktop window. Captures use synthetic fixtures and never load saved preferences.
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import struct
import subprocess

SCENARIOS = (
    "error-prerequisite",
    "setup-dependencies", "update-available", "update-confirmation",
    "target", "target-ios", "target-mac", "demo-target-ios", "review-ios", "setup-ios",
    "keys-empty", "keys-selected", "keys-not-found", "game-empty", "game-selected",
    "nca", "update-empty", "update-selected", "mods-folder", "mods-folder-ios", "mods-empty",
    "mods-selected", "mods-exefs-only", "mods-ips-ready", "mods-ips-ios-ready", "review-mod", "error", "error-details", "error-disk",
    "review", "review-portable", "demo-review", "setup", "build-options", "installed", "installed-test", "generator-analyze", "generator-emit", "progress", "progress-details",
    "preflight-running", "preflight-details", "finished", "long-name", "demo",
)
INSTALLER = Path(__file__).resolve().parents[1]
ROOT = INSTALLER.parent


def dimensions(path):
    with path.open("rb") as image:
        header = image.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid screenshot: {path}")
    return struct.unpack(">II", header[16:24])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--backend", choices=("wgpu", "tiny-skia"), default="wgpu")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--language", choices=("de", "en"), default="de")
    parser.add_argument("--platform", choices=("mac", "windows", "linux"))
    parser.add_argument("--scenes", default="target", help="Comma-separated changed scenes; 'all' explicitly requests the full matrix")
    args = parser.parse_args()
    scenes = SCENARIOS if args.scenes == "all" else tuple(dict.fromkeys(args.scenes.split(',')))
    if not scenes or any(scene not in SCENARIOS for scene in scenes):
        parser.error("Unknown or empty scene; choose from: " + ', '.join(SCENARIOS))
    destination = args.directory or ROOT / "work" / "installer-ui" / datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not args.skip_build:
        subprocess.run(["cargo", "build", "--locked", "--manifest-path", str(INSTALLER / "Cargo.toml")], check=True)
    binary = Path(os.environ.get("CARGO_TARGET_DIR", str(INSTALLER / "target"))) / "debug" / ("strahlender-xnu-installer.exe" if os.name == "nt" else "strahlender-xnu-installer")
    environment = dict(os.environ, ICED_BACKEND=args.backend, BDSP_LANG=args.language)
    command = [str(binary), "--capture-dir", str(destination), "--scenes", ",".join(scenes)]
    if args.platform:
        command += ["--platform", args.platform]
    subprocess.run(command, env=environment, check=True, timeout=90)
    rows = []
    baseline = next((scene for scene in scenes if scene not in ("error-details", "progress-details", "preflight-details")), None)
    standard_size = dimensions(destination / f"dark-{baseline}.png") if baseline else None
    for scenario in scenes:
        sizes = [dimensions(destination / f"dark-{scenario}.png")]
        width, height = sizes[0]
        if scenario not in ("error-details", "progress-details", "preflight-details") and standard_size is not None and sizes[0] != standard_size:
            raise ValueError(f"Window size changed between views: {scenario}: {sizes[0]} vs {standard_size}")
        if scenario in ("error-details", "progress-details", "preflight-details") and standard_size is not None:
            expected_height = standard_size[1] * (630 / 480)
            if width != standard_size[0] or abs(height - expected_height) > 2:
                raise ValueError(f"Unexpected log expansion: {scenario}: {sizes[0]}")
        if width < 360 or height < 360:
            raise ValueError(f"Unexpected screenshot size for {scenario}: {sizes[0]}")
        rows.append(f"| {scenario} | [Dark](dark-{scenario}.png) | {width} × {height} |")
    report = "\n".join([
        "# Installer UI review", "", f"Renderer: `{args.backend}`. Language: `{args.language}`. Simulated platform: `{args.platform or 'native'}`. Real Iced window captures, synthetic sources.", "",
        f"All {len(scenes)} dark-mode PNGs exist. Main-content layout was checked for overflow in the real widget tree.",
        "Visual review is still required; these checks do not prove correct layout or interaction.", "",
        "| State | Dark | Pixels |", "| --- | --- | --- |", *rows, "",
    ])
    (destination / "review.md").write_text(report, encoding="utf-8")
    print(f"\nVerified {len(scenes)} screenshots: {destination / 'review.md'}")


if __name__ == "__main__":
    main()
