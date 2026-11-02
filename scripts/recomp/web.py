"""HTTPS downloads for the setup scripts, with a way out when Python cannot verify a certificate chain.

On some Windows machines Python's `urllib` fails with "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate": Python does
not fetch missing intermediate certificates the way a browser does, and a fresh Windows can lack a root until Windows Update brings it.
The `curl` that ships with Windows 10 and later uses Windows' own certificate handling (Schannel), so a second try with it succeeds
where Python fails. Verification stays on in both paths; the downloads are also checked against the publisher's SHA-1 or SHA-256."""
import io
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def is_certificate_error(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(error)


def _curl():
    return shutil.which("curl.exe") or shutil.which("curl")


def _header_arguments(request):
    arguments = []
    for name, value in (request.header_items() if hasattr(request, "header_items") else ()):
        arguments += ["-H", "%s: %s" % (name, value)]
    return arguments


class Response(io.BytesIO):
    """What `urlopen` returns after the curl retry: read(), json.load() and `with` work as with urllib's response."""
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self.status = 200


def urlopen(request, timeout=60):
    """urllib's urlopen; on a certificate error one retry with curl (the whole body is read into memory: for small texts and JSON)."""
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.URLError, ssl.SSLError, OSError) as error:
        curl = _curl()
        if not is_certificate_error(error) or not curl:
            raise
        url = request if isinstance(request, str) else request.full_url
        result = subprocess.run([curl, "-fsSL", "--retry", "2", "--max-time", str(int(timeout)), *_header_arguments(request), url],
                                capture_output=True)
        if result.returncode:
            raise error
        return Response(result.stdout)


def _finish(partial, destination, seconds=90, pause=1.0, sleep=time.sleep, clock=time.monotonic):
    """Moves the finished download into place. Right after a large write Windows (Defender, the indexer) can hold the file for a while
    and the rename fails with "access denied" (WinError 5); it succeeds a few seconds later. If it stays locked, copying works as the
    scanner only blocks the rename, and the partial file is removed on a best-effort basis."""
    deadline = clock() + seconds
    while True:
        try:
            partial.replace(destination)
            return
        except OSError:
            if clock() >= deadline:
                break
            sleep(pause)
    shutil.copyfile(partial, destination)
    partial.unlink(missing_ok=True)


def download_file(url, destination, timeout=600, on_bytes=None, sleep=time.sleep, clock=time.monotonic):
    """Downloads `url` into `destination` (written completely or not at all). on_bytes(received, total) is called about four times a
    second; total is 0 when unknown. Certificate error: one retry with curl, which reports the size on disk instead of a total."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(partial, "wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            received, reported = 0, 0.0
            for chunk in iter(lambda: response.read(1 << 20), b""):
                output.write(chunk)
                received += len(chunk)
                if on_bytes and clock() - reported >= 0.25:
                    reported = clock()
                    on_bytes(received, total)
            if on_bytes:
                on_bytes(received, total)
    except (urllib.error.URLError, ssl.SSLError, OSError) as error:
        curl = _curl()
        partial.unlink(missing_ok=True)
        if not is_certificate_error(error) or not curl:
            raise
        process = subprocess.Popen([curl, "-fsSL", "--retry", "3", "--connect-timeout", "30", "-o", str(partial), url],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while process.poll() is None:
            if on_bytes and partial.exists():
                on_bytes(partial.stat().st_size, 0)
            sleep(0.25)
        if process.returncode:
            partial.unlink(missing_ok=True)
            raise error
        if on_bytes:
            on_bytes(partial.stat().st_size, partial.stat().st_size)
    _finish(partial, destination, sleep=sleep, clock=clock)
    return destination
