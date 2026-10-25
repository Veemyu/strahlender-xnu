#!/usr/bin/env python3
"""Plan explicit installer releases and collect verified native build artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ("macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64")


def plan(version, event, ref, channel, revision, run_id, attempt):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Installer Cargo version must be a stable three-part version.")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected the exact source commit SHA.")
    if event == "push":
        if ref != "installer-v" + version:
            raise ValueError("Installer release tag must match installer/Cargo.toml.")
        channel = "release"
    elif event != "workflow_dispatch":
        raise ValueError("Only a manual run or an explicit installer release tag can publish.")
    if channel not in ("artifacts", "nightly", "release"):
        raise ValueError("Unknown installer channel.")
    if channel == "nightly":
        if not run_id.isdigit() or not attempt.isdigit():
            raise ValueError("Expected numeric GitHub run identifiers.")
        tag = f"installer-nightly-{run_id}-{attempt}"
    elif channel == "release":
        tag = "installer-v" + version
    else:
        tag = ""
    return {"channel": channel, "version": version, "tag": tag, "revision": revision}


def collect(artifacts, output, release):
    if output.exists():
        raise ValueError("Release staging directory already exists.")
    inventory = {}
    for target in TARGETS:
        suffixes = ("zip", "tar.gz") if target.startswith("macos") else ("AppImage", "tar.gz")
        for suffix in suffixes:
            name = f"installer-{target}.{suffix}"
            matches = list(artifacts.rglob(name))
            if len(matches) != 1 or not matches[0].is_file() or matches[0].is_symlink():
                raise ValueError(f"Expected exactly one regular artifact: {name}")
            source = matches[0]
            checksum_file = source.parent / "SHA256SUMS"
            entries = {}
            for line in checksum_file.read_text().splitlines():
                digest, filename = line.split(maxsplit=1)
                entries[filename.lstrip("*")] = digest
            with source.open("rb") as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            if entries.get(name) != digest:
                raise ValueError(f"Artifact checksum mismatch: {name}")
            inventory[name] = (source, digest)
    output.mkdir(parents=True)
    for name, (source, _) in inventory.items():
        shutil.copy2(source, output / name)
    (output / "SHA256SUMS").write_text("".join(
        f"{digest}  {name}\n" for name, (_, digest) in sorted(inventory.items())))
    (output / "installer-build.json").write_text(json.dumps(
        {"schema": 1, **release, "targets": TARGETS}, indent=2) + "\n")


def publish(folder, release, repository):
    if release["channel"] == "artifacts":
        raise ValueError("Artifact-only runs must never publish a GitHub release.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository.")
    tag = release["tag"]
    # A stable tag may already exist; it must refer to this exact source revision.
    existing = subprocess.run(["git", "ls-remote", "origin", f"refs/tags/{tag}",
                               f"refs/tags/{tag}^{{}}"], check=True, capture_output=True, text=True)
    refs = dict(line.split()[::-1] for line in existing.stdout.splitlines())
    tagged = refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))
    if tagged and tagged != release["revision"]:
        raise ValueError("Existing release tag points to a different commit. Tags are never moved.")
    prerelease = release["channel"] == "nightly"
    title = ("Installer nightly · " + release["revision"][:8] if prerelease
             else "Strahlender Installer " + release["version"])
    notes = f"""Download the installer for your computer. No Rust, Python or source build is needed to open it.

| Platform | Download |
| --- | --- |
| Mac · Apple Silicon | `installer-macos-aarch64.zip` |
| Mac · Intel | `installer-macos-x86_64.zip` |
| Linux · x86_64 | `installer-linux-x86_64.AppImage` |
| Linux · ARM64 | `installer-linux-aarch64.AppImage` |

On macOS, unzip the download and open Strahlender Installer.app. This build is ad-hoc signed and is not notarized; Gatekeeper may require an explicit allowance in Privacy & Security.
On Linux, mark the AppImage as executable and open it. The portable tar.gz is available when AppImage mounting is unavailable.

The installer includes its own Python runtime. Building the game still needs platform build tools; setup checks list any missing requirements. Fresh-system dependency installation and the full four-host acceptance matrix remain under test. Windows installer downloads are not available yet.

Bring your own prod.keys, base game and optional update. Game files and keys are never included in these downloads. Game builds resolve the current main source at build time.

Source revision: `{release['revision']}`. Channel: **{release['channel']}**.
The updater is enabled only in builds configured with signed update metadata; these initial downloads can be updated manually through Releases.
"""
    with tempfile.TemporaryDirectory(prefix="installer-release-notes-") as temporary:
        path = Path(temporary) / "notes.md"
        path.write_text(notes)
        command = ["gh", "release", "create", tag, "--repo", repository,
                   "--target", release["revision"], "--draft", "--title", title,
                   "--notes-file", str(path)]
        if prerelease:
            command.append("--prerelease")
        command.extend(str(path) for path in sorted(folder.iterdir()) if path.is_file())
        subprocess.run(command, check=True)
    # Upload every artifact before exposing the release. Stable releases become
    # latest explicitly; nightly builds never replace the stable latest link.
    subprocess.run(["gh", "release", "edit", tag, "--repo", repository,
                    "--draft=false", "--latest=" + ("false" if prerelease else "true")], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--event", required=True)
    planning.add_argument("--ref", required=True)
    planning.add_argument("--channel", default="artifacts")
    planning.add_argument("--revision", required=True)
    planning.add_argument("--run-id", required=True)
    planning.add_argument("--attempt", required=True)
    planning.add_argument("--github-output", type=Path, required=True)
    assembling = sub.add_parser("collect")
    assembling.add_argument("--artifacts", type=Path, required=True)
    assembling.add_argument("--output", type=Path, required=True)
    assembling.add_argument("--plan", type=Path, required=True)
    publishing = sub.add_parser("publish")
    publishing.add_argument("--folder", type=Path, required=True)
    publishing.add_argument("--plan", type=Path, required=True)
    publishing.add_argument("--repository", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        version = tomllib.loads((ROOT / "installer/Cargo.toml").read_text())["package"]["version"]
        release = plan(version, args.event, args.ref, args.channel, args.revision, args.run_id, args.attempt)
        Path("installer-release-plan.json").write_text(json.dumps(release) + "\n")
        with args.github_output.open("a") as file:
            for key, value in release.items():
                file.write(f"{key}={value}\n")
    elif args.command == "collect":
        collect(args.artifacts, args.output, json.loads(args.plan.read_text()))
    else:
        publish(args.folder, json.loads(args.plan.read_text()), args.repository)


if __name__ == "__main__":
    main()
