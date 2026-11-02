import io
import unittest
import urllib.error
import urllib.request
from unittest import mock

from scripts.recomp import resolve_inputs as resolver
from scripts.recomp import web

SDL_FEED = ('<feed><entry><link href="https://github.com/libsdl-org/SDL/releases/tag/release-3.4.18"/></entry>'
            '<entry><link href="https://github.com/libsdl-org/SDL/releases/tag/prerelease-3.5.0"/></entry>'
            '<entry><link href="https://github.com/libsdl-org/SDL/releases/tag/release-3.2.30"/></entry>'
            '<entry><link href="/libsdl-org/SDL/releases/tag/release-3.2.4"/></entry></feed>')
DEVEL = "SDL3-devel-3.4.18-mingw.tar.gz"
SDL_PAGE = ('<a href="/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-3.4.18.tar.gz"><span>sha256:%s</span>'
            '<a href="/libsdl-org/SDL/releases/download/release-3.4.18/%s"><span>sha256:%s</span>'
            '<a href="/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-devel-3.4.18-VC.zip"><span>sha256:%s</span>'
            % ("a" * 64, DEVEL, "b" * 64, "c" * 64))
FFMPEG = "\n".join("%s  %s" % (h * 64, n) for h, n in (
    ("1", "ffmpeg-master-latest-win64-lgpl-shared.zip"), ("2", "ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip"),
    ("3", "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"), ("4", "ffmpeg-n8.0-latest-win64-lgpl-shared-8.0.zip"),
    ("5", "ffmpeg-n8.1-latest-win64-gpl-shared-8.1.zip")))


def site(url, headers=None, limited=True):
    """What the network says: the API answers 403, github.com pages work."""
    if "api.github.com" in url:
        raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, io.BytesIO(b""))
    pages = {"releases.atom": SDL_FEED, "expanded_assets/release-3.4.18": SDL_PAGE, "checksums.sha256": FFMPEG}
    for key, body in pages.items():
        if url.endswith(key):
            return web.Response(body.encode())
    raise AssertionError("unexpected request " + url)


def fake_urlopen(request, timeout=60):
    url = request if isinstance(request, str) else request.full_url
    return site(url)


class RateLimitTests(unittest.TestCase):
    def test_sdl_comes_from_the_release_pages_when_the_api_is_rate_limited(self):
        with mock.patch.object(resolver.web, "urlopen", fake_urlopen):
            found = resolver.latest_sdl_devel()
        self.assertEqual(found["version"], "3.4.18")
        self.assertEqual(found["name"], DEVEL)
        self.assertEqual(found["sha256"], "b" * 64)   # the hash after the developer package's own link, not the first on the page
        self.assertEqual(found["url"], "https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/" + DEVEL)

    def test_ffmpeg_comes_from_the_checksum_file_and_the_newest_wanted_major_wins(self):
        with mock.patch.object(resolver.web, "urlopen", fake_urlopen):
            found = resolver.latest_ffmpeg()
        self.assertEqual(found["name"], "ffmpeg-n%d.1-latest-win64-lgpl-shared-%d.1.zip" % (resolver.FFMPEG_MAJOR, resolver.FFMPEG_MAJOR))
        self.assertEqual(found["sha256"], "2" * 64 if resolver.FFMPEG_MAJOR == 8 else "3" * 64)
        self.assertTrue(found["url"].endswith("/latest/" + found["name"]))

    def test_other_errors_and_injected_sources_are_not_papered_over(self):
        with mock.patch.object(resolver.web, "urlopen", side_effect=urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b""))) as opener:
            with mock.patch.object(resolver, "sdl_without_api") as fallback:
                with self.assertRaises(urllib.error.HTTPError):
                    resolver.latest_sdl_devel()
                fallback.assert_not_called()   # a server error is not the rate limit
        def failing(url):
            raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, io.BytesIO(b""))
        with mock.patch.object(resolver, "sdl_without_api") as fallback:
            with self.assertRaises(urllib.error.HTTPError):
                resolver.latest_sdl_devel(get=failing)   # tests and callers that pass their own source keep their errors
            fallback.assert_not_called()

    def test_if_the_pages_fail_too_the_original_rate_limit_error_is_raised(self):
        def api_limited_pages_down(request, timeout=60):
            url = request if isinstance(request, str) else request.full_url
            if "api.github.com" in url:
                raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, io.BytesIO(b""))
            raise urllib.error.URLError(OSError("offline"))
        with mock.patch.object(resolver.web, "urlopen", api_limited_pages_down):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                resolver.latest_ffmpeg()
        self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
