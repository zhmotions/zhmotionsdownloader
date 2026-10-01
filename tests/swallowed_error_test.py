"""Tests for the ignoreerrors=True swallowed-failure path in App._run_video.

yt-dlp runs with ignoreerrors=True (playlists need one bad item to not kill the
whole batch), so a failed extraction never raises — yt-dlp just calls the
logger and returns. _run_video used to hardcode "unsupported url" for
_error_hint() in that path regardless of what actually went wrong, so a
"Sign in to confirm you're not a bot" / private-video / Cloudflare failure all
showed the same generic "no extractor for this site" message. Fixed by having
_Log remember the last error it was given, and (for Cloudflare specifically)
retrying once with curl_cffi impersonation before giving up.

    python3 tests/swallowed_error_test.py
"""
import importlib.util
import pathlib
import queue
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("zhd", ROOT / "zh_downloader.py")
zhd = importlib.util.module_from_spec(spec)
sys.modules["zhd"] = zhd
spec.loader.exec_module(zhd)
zhd.jsave = lambda *a, **k: None

fails = passes = 0


def eq(label, got, want):
    global fails, passes
    ok = got == want
    passes += ok
    fails += not ok
    print(("PASS  " if ok else "FAIL  ") + label + " = " + repr(got) +
          ("" if ok else "  (want " + repr(want) + ")"))


def run(err_text, cffi_available, succeed_on_impersonate=True):
    """One _run_video pass where yt-dlp SWALLOWS the failure (ignoreerrors):
    logs `err_text` via the opts logger, download() returns normally, no file.
    If a retry arrives with impersonate set, optionally let it "succeed"."""
    attempts = []

    class FakeYDL:
        def __init__(self, o):
            self.o = o
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download(self, urls):
            imp = self.o.get("impersonate")
            attempts.append(imp)
            if imp and succeed_on_impersonate:
                # "succeeds" the way a real yt-dlp run does: the progress hook
                # already stamped item.done_f via the finished-status payload.
                self.o["_item"].done_f = "/tmp/fake.mp4"
                return
            self.o["logger"].error(err_text)

    real_ydl = zhd.yt_dlp.YoutubeDL
    real_cffi = zhd._cffi_available
    zhd.yt_dlp.YoutubeDL = FakeYDL
    zhd._cffi_available = lambda: cffi_available
    try:
        app = zhd.App.__new__(zhd.App)
        app._mq = queue.Queue()
        app._stop = threading.Event()
        app._paused = False
        app.logs = []
        app.log = lambda m, *a, **k: app.logs.append(m)
        item = zhd.DL("https://example.com/x", 0, 0, "")
        item.status = "downloading"
        item.done_f = None
        item.stop_ev = threading.Event()

        def _ydl_opts(out, fk, it, url=""):
            return {"logger": zhd._Log(app), "_item": it}
        app._ydl_opts = _ydl_opts
        app._fallback_to_file = lambda *a, **k: False
        app._rename_if_uuid = lambda *a, **k: None
        app._cleanup_intermediates = lambda *a, **k: None
        app.ff = None
        app._run_video("https://example.com/x", "/tmp", "hd", item)
        return attempts, app.logs, item.status, item.done_f
    finally:
        zhd.yt_dlp.YoutubeDL = real_ydl
        zhd._cffi_available = real_cffi


CF = "ERROR: [generic] Got HTTP Error 403 caused by Cloudflare anti-bot challenge; see ..."
BOT = "ERROR: [youtube] abc123: Sign in to confirm you're not a bot. Use --cookies-from-browser ..."

# 1. Swallowed bot-wall error: the SPECIFIC hint fires, not the generic one.
at, logs, status, done = run(BOT, cffi_available=True)
eq("bot-wall: no impersonate retry attempted", at, [None])
eq("bot-wall: row marked error", status, "error")
eq("bot-wall: real hint shown (Cookies), not the generic 'no extractor' one",
   any("Set Cookies to your browser" in m for m in logs), True)
eq("bot-wall: generic hint NOT shown",
   any("No extractor for this site" in m for m in logs), False)

# 2. Swallowed Cloudflare 403, curl_cffi available: one impersonate retry, succeeds.
at, logs, status, done = run(CF, cffi_available=True, succeed_on_impersonate=True)
eq("cloudflare: two attempts, second impersonated", at, [None, "chrome"])
eq("cloudflare: retry succeeded — file landed", done, "/tmp/fake.mp4")
eq("cloudflare: row marked done, not error", status, "done")

# 3. Swallowed Cloudflare 403, curl_cffi available, impersonation ALSO fails.
at, logs, status, done = run(CF, cffi_available=True, succeed_on_impersonate=False)
eq("cloudflare both fail: two attempts", at, [None, "chrome"])
eq("cloudflare both fail: row marked error", status, "error")
eq("cloudflare both fail: Cloudflare-specific hint shown",
   any("Cloudflare check blocked the request" in m for m in logs), True)

# 4. Swallowed Cloudflare 403, curl_cffi NOT bundled: no retry attempted at all.
at, logs, status, done = run(CF, cffi_available=False)
eq("no curl_cffi: no retry attempted", at, [None])
eq("no curl_cffi: row marked error", status, "error")

print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
