import json
from pathlib import Path
import tempfile
import unittest

from scripts.recomp import resolve_inputs as resolver


def canned(url):
    tags = lambda names: [{"name": n, "commit": {"sha": (n.encode().hex() * 5)[:40]}} for n in names]
    if "SDL/releases" in url:
        return [{"tag_name": "release-2.40.0", "prerelease": False, "draft": False, "assets": []},
                {"tag_name": "release-3.6.0", "prerelease": True, "draft": False, "assets": []},
                {"tag_name": "release-3.4.18", "prerelease": False, "draft": False,
                 "assets": [{"name": "SDL3-3.4.18.tar.gz", "browser_download_url": "https://x/sdl.tar.gz"}]}]
    if "FFmpeg-Builds" in url:
        names = ["ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip", "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip",
                 "ffmpeg-n8.0-latest-win64-lgpl-shared-8.0.zip", "ffmpeg-master-latest-win64-lgpl-shared.zip"]
        return {"assets": [{"name": n, "browser_download_url": "https://x/" + n} for n in names]}
    if "Vulkan-Headers/tags" in url:
        return tags(["vulkan-sdk-1.4.300.0", "vulkan-sdk-1.4.363.0", "v1.3.0", "vulkan-sdk-1.3.999.0"])
    if "VulkanMemoryAllocator/tags" in url:
        return tags(["v3.4.0", "v3.5.0", "v3.10.0-rc1"])
    if "shaderc/tags" in url:
        return tags(["v2025.9", "v2026.4", "v2026.10"])
    if "FFmpeg/FFmpeg/tags" in url:
        return tags(["n8.1", "n8.1.3", "n8.1.10", "n9.0", "n8.0.1"])
    if "hactool/commits/HEAD" in url:
        return {"sha": "a" * 40}
    raise AssertionError(url)


DEPS = "'glslang_revision': '%s',\n'spirv_headers_revision': '%s',\n'spirv_tools_revision': '%s',\n" % ("1" * 40, "2" * 40, "3" * 40)


class ResolveInputsTests(unittest.TestCase):
    def test_picks_the_newest_stable_release_of_each_project_within_the_compatible_ffmpeg_line(self):
        items = {i["role"]: i for i in resolver.resolve(canned, lambda url: DEPS)}
        self.assertNotIn("SDL3", items)  # the user's machine takes SDL3 and the FFmpeg binaries straight from their publishers
        self.assertEqual(items["ffmpeg"]["version"], "n8.1.10")
        self.assertEqual(items["vulkan-headers"]["version"], "vulkan-sdk-1.4.363.0")
        self.assertEqual(items["vma"]["version"], "v3.5.0")
        self.assertEqual(items["shaderc"]["version"], "v2026.10")
        self.assertEqual((items["glslang"]["revision"], items["spirv-tools"]["revision"]), ("1" * 40, "3" * 40))
        self.assertEqual(items["hactool"]["revision"], "a" * 40)
        self.assertTrue(all(i["url"].startswith("https://") for i in items.values()))

    def test_resolved_lock_files_keep_the_schema_and_carry_the_measured_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "downloads"
            fake = lambda url, target: Path(target).write_bytes(url.encode())
            downloads = resolver.fetch(resolver.resolve(canned, lambda url: DEPS), out, fake)
            resolved = resolver.write_resolved(downloads, Path(temporary) / "resolved")
            contract = json.loads((resolved / "windows-dependencies.json").read_text())
            sources = json.loads((resolved / "windows-sources.json").read_text())
            self.assertEqual(sources["sources"]["ffmpeg"]["version"], "n8.1.10")
            self.assertEqual(sources["sources"]["vma"]["version"], "v3.5.0")
            self.assertEqual(len(sources["sources"]["hactool"]["sha256"]), 64)
            self.assertEqual(sources["sources"]["hactool"]["size_bytes"], len(sources["sources"]["hactool"]["revision"]) and
                             (out / ("hactool-" + "a" * 40 + ".tar.gz")).stat().st_size)

    def test_sdl_and_ffmpeg_for_the_users_machine_carry_the_digests_github_publishes(self):
        def get(url):
            if "SDL/releases" in url:
                return [{"tag_name": "release-3.4.18", "prerelease": False, "draft": False, "assets": [
                    {"name": "SDL3-devel-3.4.18-mingw.tar.gz", "browser_download_url": "https://x/sdl.tar.gz", "digest": "sha256:" + "a" * 64},
                    {"name": "SDL3-3.4.18.tar.gz", "browser_download_url": "https://x/src.tar.gz", "digest": "sha256:" + "b" * 64}]}]
            return {"assets": [
                {"name": "ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip", "browser_download_url": "https://x/ff.zip", "digest": "sha256:" + "c" * 64},
                {"name": "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip", "browser_download_url": "https://x/ff9.zip", "digest": "sha256:" + "d" * 64}]}
        sdl, ffmpeg = resolver.latest_sdl_devel(get), resolver.latest_ffmpeg(get)
        self.assertEqual((sdl["url"], sdl["sha256"]), ("https://x/sdl.tar.gz", "a" * 64))
        self.assertEqual((ffmpeg["url"], ffmpeg["sha256"]), ("https://x/ff.zip", "c" * 64))

    def test_a_release_without_a_published_digest_is_refused(self):
        get = lambda url: {"assets": [{"name": "ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip", "browser_download_url": "https://x/ff.zip"}]}
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            resolver.latest_ffmpeg(get)


if __name__ == "__main__":
    unittest.main()
