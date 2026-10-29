#!/usr/bin/env python3
"""Resolves the newest upstream releases of the Windows build inputs (the compiler and Qt come from resolve_qt.py), downloads them and records what was used.

Nothing is pinned in the repository: every run of the GitHub Actions job windows-buildenv.yml takes the current
release of each project, hashes what it downloaded, and writes resolved copies of windows-dependencies.json and
windows-sources.json (the recipes read them through BDSP_WINDOWS_CONTRACT / BDSP_WINDOWS_SOURCES). The resolved files
travel inside the published build environment, so each bundle documents exactly which versions it contains.
Only compatibility lines stay fixed: FFmpeg major 8 (its C API is what the movie code uses) and Unicorn 2.1.4.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "installer/assets"
FFMPEG_MAJOR = 8


def api(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "strahlender-xnu-ci"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "strahlender-xnu-ci"}), timeout=60) as response:
        return response.read().decode("utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, destination):
    try:
        with urllib.request.urlopen(url, timeout=300) as response, open(destination, "wb") as output:
            shutil.copyfileobj(response, output)
    except OSError:
        curl = shutil.which("curl")
        if not curl:
            raise
        subprocess.run([curl, "-fsSL", "--retry", "3", "-o", str(destination), url], check=True)


def version_key(name):
    return tuple(int(part) for part in re.findall(r"\d+", name))


def newest(names, pattern):
    matching = [name for name in names if re.fullmatch(pattern, name)]
    if not matching:
        raise ValueError("No release matches " + pattern)
    return max(matching, key=version_key)


def tags(repository, get=api):
    return {item["name"]: item["commit"]["sha"] for item in get("https://api.github.com/repos/%s/tags?per_page=100" % repository)}


def release_asset(release, pattern):
    for asset in release["assets"]:
        if re.fullmatch(pattern, asset["name"]):
            return asset
    raise ValueError("Release %s has no asset %s" % (release.get("tag_name"), pattern))


def resolve(get=api, get_text=text):
    """Returns (contract updates, source entries, downloads) without touching the network beyond `get`."""
    sdl_releases = [r for r in get("https://api.github.com/repos/libsdl-org/SDL/releases?per_page=40")
                    if re.fullmatch(r"release-3\.\d+\.\d+", r["tag_name"]) and not r["prerelease"] and not r["draft"]]
    sdl = max(sdl_releases, key=lambda r: version_key(r["tag_name"]))
    sdl_version = sdl["tag_name"].removeprefix("release-")
    sdl_asset = release_asset(sdl, r"SDL3-%s\.tar\.gz" % re.escape(sdl_version))
    ffmpeg_release = get("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest")
    ffmpeg_names = [a["name"] for a in ffmpeg_release["assets"]]
    ffmpeg_name = newest(ffmpeg_names, r"ffmpeg-n%d\.\d+-latest-win64-lgpl-shared-%d\.\d+\.zip" % (FFMPEG_MAJOR, FFMPEG_MAJOR))
    ffmpeg_asset = release_asset(ffmpeg_release, re.escape(ffmpeg_name))

    def archive(repository, revision):
        return "https://github.com/%s/archive/%s.tar.gz" % (repository, revision)

    vulkan = tags("KhronosGroup/Vulkan-Headers", get)
    vulkan_tag = newest(vulkan, r"vulkan-sdk-\d+\.\d+\.\d+\.\d+")
    vma = tags("GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator", get)
    vma_tag = newest(vma, r"v\d+\.\d+\.\d+")
    shaderc = tags("google/shaderc", get)
    shaderc_tag = newest(shaderc, r"v\d{4}\.\d+")
    deps = get_text("https://raw.githubusercontent.com/google/shaderc/%s/DEPS" % shaderc[shaderc_tag])
    pinned = dict(re.findall(r"'(\w+)_revision': '([0-9a-f]{40})'", deps))
    ffmpeg_branch = re.search(r"n(\d+\.\d+)-latest", ffmpeg_name).group(1)
    ffmpeg_source = tags("FFmpeg/FFmpeg", get)
    ffmpeg_source_tag = newest(ffmpeg_source, r"n%s(\.\d+)?" % re.escape(ffmpeg_branch))
    hactool_head = get("https://api.github.com/repos/SciresM/hactool/commits/HEAD")["sha"]
    sources = {
        "vulkan-headers": ("KhronosGroup/Vulkan-Headers", vulkan_tag, vulkan[vulkan_tag]),
        "vma": ("GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator", vma_tag, vma[vma_tag]),
        "shaderc": ("google/shaderc", shaderc_tag, shaderc[shaderc_tag]),
        "glslang": ("KhronosGroup/glslang", "shaderc-%s-DEPS" % shaderc_tag, pinned["glslang"]),
        "spirv-headers": ("KhronosGroup/SPIRV-Headers", "shaderc-%s-DEPS" % shaderc_tag, pinned["spirv_headers"]),
        "spirv-tools": ("KhronosGroup/SPIRV-Tools", "shaderc-%s-DEPS" % shaderc_tag, pinned["spirv_tools"]),
        "ffmpeg": ("FFmpeg/FFmpeg", ffmpeg_source_tag, ffmpeg_source[ffmpeg_source_tag]),
        "hactool": ("SciresM/hactool", "HEAD", hactool_head),
    }
    downloads = [
        {"role": "SDL3", "name": "SDL3-source.tar.gz", "url": sdl_asset["browser_download_url"], "version": sdl_version},
        {"role": "ffmpeg-binaries", "name": "ffmpeg-binaries.zip", "url": ffmpeg_asset["browser_download_url"], "version": ffmpeg_name},
    ]
    for name, (repository, version, revision) in sources.items():
        downloads.append({"role": name, "name": "%s-%s.tar.gz" % (name, revision), "url": archive(repository, revision),
                          "version": version, "repository": repository, "revision": revision})
    return downloads


def fetch(downloads, out, fetcher=download):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for item in downloads:
        target = out / item["name"]
        fetcher(item["url"], target)
        item["size_bytes"] = target.stat().st_size
        item["sha256"] = sha256(target)
    return downloads


def write_resolved(downloads, destination, assets=ASSETS):
    """Resolved copies of the two lock files: same schema, current versions, measured hashes."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    by_role = {item["role"]: item for item in downloads}
    contract = json.loads((assets / "windows-dependencies.json").read_text(encoding="utf-8"))
    sources = json.loads((assets / "windows-sources.json").read_text(encoding="utf-8"))
    for component in contract["components"]:
        if component["id"] == "SDL3":
            item = by_role["SDL3"]
            component["version"] = item["version"]
            component["source_archive"].update(url=item["url"], sha256=item["sha256"], size_bytes=item["size_bytes"])
        elif component["id"] == "ffmpeg":
            item = by_role["ffmpeg-binaries"]
            with zipfile.ZipFile(destination.parent / "downloads" / item["name"]) as archive:
                entries = archive.infolist()
            roots = {entry.filename.split("/")[0] for entry in entries}
            if len(roots) != 1:
                raise ValueError("Expected one FFmpeg archive root")
            component["version"] = item["version"]
            component["artifacts"][0].update(url=item["url"], sha256=item["sha256"], size_bytes=item["size_bytes"],
                                             expanded_size_bytes=sum(entry.file_size for entry in entries),
                                             archive_root=roots.pop())
    for name, entry in sources["sources"].items():
        item = by_role[name]
        entry.update(version=item["version"], revision=item["revision"], sha256=item["sha256"], size_bytes=item["size_bytes"])
    (destination / "windows-dependencies.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    (destination / "windows-sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Folder for the downloads; the resolved lock files go to ../resolved")
    args = parser.parse_args(argv)
    try:
        downloads = fetch(resolve(), args.out)
        write_resolved(downloads, args.out.parent / "resolved")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print("Resolving the inputs failed: " + str(error), file=sys.stderr)
        return 4
    for item in downloads:
        print("%-14s %-40s %s" % (item["role"], item["version"], item["sha256"][:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
