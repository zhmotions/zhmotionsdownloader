"""Tests for the Cookies dropdown's "file" option (_cookie_opts_for,
_cookie_header_for's file branch) — an exported cookies.txt as an
alternative to cookiesfrombrowser, which needs macOS Full Disk Access
(an ad-hoc-signed app can silently lose that grant on every rebuild —
see change-log 2026-10-06). A plain file read needs no OS permission.

    python3 tests/cookie_file_test.py
"""
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile

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


def make_app(cookies_file=None):
    app = zhd.App.__new__(zhd.App)
    app.cfg = {"cookies_file": cookies_file} if cookies_file else {}
    return app


# -- _cookie_opts_for: picks cookiefile vs cookiesfrombrowser ---------------
app = make_app()
eq("no file configured yet: empty (nothing to retry WITH)",
   app._cookie_opts_for("file"), {})

app = make_app("/definitely/not/a/real/path.txt")
eq("configured path doesn't exist: empty, not a crash",
   app._cookie_opts_for("file"), {})

fd, real_path = tempfile.mkstemp(suffix=".txt")
os.close(fd)
try:
    app = make_app(real_path)
    eq("real file configured: cookiefile opt", app._cookie_opts_for("file"),
       {"cookiefile": real_path})

    app = make_app(real_path)
    eq("non-file mode ignores cookies_file entirely, uses the browser name",
       app._cookie_opts_for("chrome"), {"cookiesfrombrowser": ("chrome",)})

    # -- _cookie_header_for: reads a real Netscape cookie file -------------
    NETSCAPE = (
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tsid\tabc123\n"
        ".other.example\tTRUE\t/\tFALSE\t0\tsid\tshouldnotmatch\n"
    )
    with open(real_path, "w") as f:
        f.write(NETSCAPE)

    app = make_app(real_path)
    app.ck_var = type("V", (), {"get": lambda self: "file"})()
    app.log = lambda m, *a, **k: None
    hdr = app._cookie_header_for("https://example.com/video.mp4")
    eq("cookie header built from the file, right domain only", hdr, "sid=abc123")

    # Cached on the SAME app instance — a 2nd call must not re-read the file.
    with open(real_path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")  # would now be empty if re-read
    hdr2 = app._cookie_header_for("https://example.com/other.mp4")
    eq("jar cached, 2nd call doesn't re-read the (now-empty) file", hdr2, "sid=abc123")
finally:
    os.unlink(real_path)

# -- no cookies_file key at all (fresh install, never configured) ----------
app = zhd.App.__new__(zhd.App)
app.cfg = {}
eq("fresh cfg, no cookies_file key: still safe, empty", app._cookie_opts_for("file"), {})

# -- _cookies_received: the extension's 🍪 Login button path ---------------
# Redirect the module constant so the test never touches the real
# ~/.zhdownloader-cookies.txt.
_tmp_dir = tempfile.mkdtemp()
_fake_cookies_path = pathlib.Path(_tmp_dir) / "cookies.txt"
_real_cookies_path = zhd.COOKIES_FILE_PATH
zhd.COOKIES_FILE_PATH = _fake_cookies_path
try:
    NETSCAPE2 = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n"

    app = zhd.App.__new__(zhd.App)
    app.cfg = {}
    app.logs = []
    app.log = lambda m, *a, **k: app.logs.append(m)
    notified = []
    app._notify = lambda *a, **k: notified.append(a)
    app.ck_var = type("V", (), {"get": lambda self: "none", "set": lambda self, v: setattr(self, "_v", v)})()

    app._cookies_received(NETSCAPE2, "youtube.com")
    eq("cookies_received: file actually written", _fake_cookies_path.read_text(), NETSCAPE2)
    eq("cookies_received: cfg points at it", app.cfg.get("cookies_file"), str(_fake_cookies_path))
    eq("cookies_received: cfg switched to file mode", app.cfg.get("cookies"), "file")
    eq("cookies_received: live dropdown flipped to file too", app.ck_var._v, "file")
    eq("cookies_received: user told (not silent)",
       any("Got your" in m for m in app.logs), True)
    eq("cookies_received: desktop notification fired", len(notified), 1)

    # Second call, no ck_var yet (UI not built — e.g. extension talks to the
    # app before the window finished constructing): must not crash.
    app2 = zhd.App.__new__(zhd.App)
    app2.cfg = {}
    app2.logs = []
    app2.log = lambda m, *a, **k: app2.logs.append(m)
    app2._notify = lambda *a, **k: None
    app2._cookies_received(NETSCAPE2, "youtube.com")
    eq("cookies_received: works fine with no ck_var (UI not up yet)",
       app2.cfg.get("cookies"), "file")
finally:
    zhd.COOKIES_FILE_PATH = _real_cookies_path
    shutil.rmtree(_tmp_dir, ignore_errors=True)

print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
