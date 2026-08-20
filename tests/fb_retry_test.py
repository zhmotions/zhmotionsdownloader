"""Facebook cookie-retry tests for App._run_video.

Drives the REAL _run_video with yt_dlp.YoutubeDL stubbed, and asserts which
opts each attempt used. Covers the bug where a public /reel/ URL failed with
"Cannot parse data" because Chrome cookies were attached: Facebook serves the
React shell to a logged-in session, so the retry has to DROP the cookies —
while private videos still need the old add-cookies retry.

    python3 tests/fb_retry_test.py                  # current source
    python3 tests/fb_retry_test.py old.py           # any older copy, to see it fail
"""
import importlib.util
import pathlib
import queue
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "zh_downloader.py"
spec = importlib.util.spec_from_file_location("zhd", SRC)
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


def run(url, base_opts, fail_when, exc=None):
    """Returns the list of attempts (each = True if that attempt sent cookies)."""
    attempts = []

    class FakeYDL:
        def __init__(self, o):
            self.o = o
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download(self, urls):
            has_ck = "cookiesfrombrowser" in self.o
            attempts.append(has_ck)
            if fail_when(has_ck):
                raise (exc or zhd.yt_dlp.utils.DownloadError(
                    "ERROR: [facebook] 123: Cannot parse data; please report this issue"))

    real = zhd.yt_dlp.YoutubeDL
    zhd.yt_dlp.YoutubeDL = FakeYDL
    try:
        app = zhd.App.__new__(zhd.App)
        app._mq = queue.Queue()
        app._stop = threading.Event()
        app._paused = False
        app.logs = []
        app.log = lambda m, *a, **k: app.logs.append(m)
        app._ydl_opts = lambda *a, **k: dict(base_opts)
        item = zhd.DL(url, 0, 0, "")
        item.status = "downloading"
        item.done_f = None
        item.stop_ev = threading.Event()
        app._run_video(url, "/tmp", "hd", item)
        # _run_video swallows the DownloadError: it logs it and marks the row.
        return attempts, app.logs, item.status
    finally:
        zhd.yt_dlp.YoutubeDL = real


FB = "https://www.facebook.com/reel/1650134176280128"
YT = "https://www.youtube.com/watch?v=AAA"
CK = {"cookiesfrombrowser": ("chrome",)}

# 1. public FB reel: cookies attached → parse fails → retry WITHOUT cookies
at, logs, status = run(FB, CK, fail_when=lambda has_ck: has_ck)
eq("public reel: two attempts", len(at), 2)
eq("public reel: first sent cookies, retry did not", at, [True, False])
eq("public reel: user told why", any("without cookies" in m for m in logs), True)

# 2. private FB video: no cookies → parse fails → retry WITH chrome cookies
at, logs, status = run(FB, {}, fail_when=lambda has_ck: not has_ck)
eq("private video: two attempts", len(at), 2)
eq("private video: cookie-less first, cookies on retry", at, [False, True])

# 3. Facebook broken both ways (dead/blocked video) → one retry, then give up
at, logs, status = run(FB, CK, fail_when=lambda has_ck: True)
eq("dead video: exactly one retry", len(at), 2)
eq("dead video: row marked error", status, "error")
eq("dead video: yt-dlp message logged",
   any("Cannot parse data" in m for m in logs), True)

# 4. non-Facebook "cannot parse" is NOT retried (no pointless second fetch)
at, logs, status = run(YT, CK, fail_when=lambda has_ck: True)
eq("youtube: single attempt", len(at), 1)
eq("youtube: row marked error", status, "error")

# 5. regression: a cookie READ failure still falls back to no cookies
at, logs, status = run(YT, CK, fail_when=lambda has_ck: has_ck,
                    exc=zhd.yt_dlp.utils.DownloadError(
                        "ERROR: Could not copy Chrome cookie database"))
eq("cookie read failure: retried cookie-less", at, [True, False])

print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
