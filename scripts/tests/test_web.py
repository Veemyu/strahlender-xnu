import ssl
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.recomp import web  # noqa: E402


def certificate_error():
    return urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"))


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="web-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, ignore_errors=True))

    def test_only_certificate_problems_are_recognised(self):
        self.assertTrue(web.is_certificate_error(certificate_error()))
        self.assertTrue(web.is_certificate_error(ssl.SSLCertVerificationError(1, "x")))
        self.assertFalse(web.is_certificate_error(urllib.error.URLError(OSError("Network is unreachable"))))
        missing = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        self.addCleanup(missing.close)
        self.assertFalse(web.is_certificate_error(missing))

    def test_a_certificate_error_is_retried_once_with_curl_and_other_errors_are_not(self):
        request = urllib.request.Request("https://example.test/data.json", headers={"User-Agent": "test"})
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=certificate_error()), \
                mock.patch.object(web, "_curl", return_value="curl.exe"), \
                mock.patch.object(web.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b'{"ok": true}')) as run:
            with web.urlopen(request) as response:
                self.assertEqual(response.read(), b'{"ok": true}')
        command = run.call_args.args[0]
        self.assertEqual(command[0], "curl.exe")
        self.assertIn("https://example.test/data.json", command)
        self.assertIn("user-agent: test", [part.lower() for part in command])   # urllib spells the header User-agent
        self.assertNotIn("-k", command)   # verification stays on: curl checks the certificate with Windows' own handling
        self.assertNotIn("--insecure", command)
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=urllib.error.URLError(OSError("offline"))), \
                mock.patch.object(web.subprocess, "run") as never:
            with self.assertRaises(urllib.error.URLError):
                web.urlopen(request)
        never.assert_not_called()

    def test_without_curl_or_when_curl_fails_the_original_error_is_raised(self):
        request = urllib.request.Request("https://example.test/")
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=certificate_error()), \
                mock.patch.object(web, "_curl", return_value=None):
            with self.assertRaises(urllib.error.URLError):
                web.urlopen(request)
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=certificate_error()), \
                mock.patch.object(web, "_curl", return_value="curl"), \
                mock.patch.object(web.subprocess, "run", return_value=SimpleNamespace(returncode=60, stdout=b"")):
            with self.assertRaises(urllib.error.URLError):
                web.urlopen(request)

    def test_a_download_writes_the_whole_file_and_reports_bytes(self):
        source = self.directory / "payload.bin"
        source.write_bytes(b"x" * (2 << 20))
        seen = []
        web.download_file(source.as_uri(), self.directory / "out/payload.bin", on_bytes=lambda a, b: seen.append((a, b)))
        self.assertEqual((self.directory / "out/payload.bin").stat().st_size, 2 << 20)
        self.assertEqual(seen[-1], (2 << 20, 2 << 20))
        self.assertFalse((self.directory / "out/payload.bin.partial").exists())

    def test_a_certificate_error_downloads_with_curl_and_reports_the_growing_file(self):
        destination = self.directory / "ffmpeg.zip"
        partial = self.directory / "ffmpeg.zip.partial"
        sizes = []

        class Curl:
            def __init__(self, command, **_):
                self.polls = 0
                self.returncode = 0

            def poll(self):
                self.polls += 1
                partial.write_bytes(b"a" * (self.polls * 1000))
                return None if self.polls < 3 else 0
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=certificate_error()), \
                mock.patch.object(web, "_curl", return_value="curl.exe"), \
                mock.patch.object(web.subprocess, "Popen", Curl):
            web.download_file("https://example.test/ffmpeg.zip", destination, on_bytes=lambda a, b: sizes.append((a, b)),
                              sleep=lambda _s: None)
        self.assertEqual(destination.read_bytes(), b"a" * 3000)
        self.assertEqual(sizes[0], (1000, 0))   # unknown total while curl runs
        self.assertEqual(sizes[-1], (3000, 3000))
        self.assertFalse(partial.exists())

    def test_a_failed_curl_download_leaves_nothing_behind(self):
        destination = self.directory / "x.zip"

        class Curl:
            returncode = 22

            def __init__(self, *a, **k):
                pass

            def poll(self):
                return 22
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=certificate_error()), \
                mock.patch.object(web, "_curl", return_value="curl"), mock.patch.object(web.subprocess, "Popen", Curl):
            with self.assertRaises(urllib.error.URLError):
                web.download_file("https://example.test/x.zip", destination, sleep=lambda _s: None)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
