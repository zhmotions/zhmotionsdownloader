"""Queue-row action tests: the 📂 (show in Finder) and ↗ (open source page)
buttons added to every card, plus the font helpers behind the Text size setting.

    python3 tests/row_actions_test.py            # current source
    python3 tests/row_actions_test.py old.py     # an older copy, to see it fail
"""
import importlib.util
import pathlib
import queue
import threading
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "zh_downloader.py"
spec = importlib.util.spec_from_file_location("zhd", SRC)
zhd  = importlib.util.module_from_spec(spec)
sys.modules["zhd"] = zhd
spec.loader.exec_module(zhd)
REAL_JSAVE = zhd.jsave          # kept: the atomic-write test needs the real one
zhd.jsave = lambda *a, **k: None

fails = passes = 0


def eq(label, got, want):
    global fails, passes
    ok = got == want
    passes += ok
    fails += not ok
    print(("PASS  " if ok else "FAIL  ") + label + " = " + repr(got) +
          ("" if ok else "  (want " + repr(want) + ")"))


class Rec:
    """Records calls instead of touching Finder / the browser."""
    def __init__(self): self.calls = []
    def __call__(self, *a): self.calls.append(a[0] if len(a) == 1 else a)


def make_app():
    app = zhd.App.__new__(zhd.App)
    app._referers = {}
    app.logs = []
    app.log = lambda m, *a, **k: app.logs.append(m)
    app._open_folder = Rec()
    return app


def mk(url, done_f=None):
    it = zhd.DL(url, 1, 1, "")
    it.done_f = done_f
    return it


tmp = pathlib.Path(tempfile.mkdtemp())
real = tmp / "clip.mp4"; real.write_bytes(b"x" * 10)

# ── 📂 reveal ─────────────────────────────────────────────────────────────
rev = Rec(); zhd._reveal_path = rev
app = make_app()
app._reveal_item(mk("https://youtu.be/x", str(real)))
eq("finished row reveals the real file", rev.calls, [str(real)])
eq("and does not fall back to the download folder", app._open_folder.calls, [])

rev.calls.clear()
app._reveal_item(mk("https://youtu.be/x", str(tmp / "gone.mp4")))
eq("missing file: no reveal", rev.calls, [])
eq("missing file: opens the download folder instead",
   len(app._open_folder.calls), 1)

rev.calls.clear(); app._open_folder.calls.clear()
app._reveal_item(mk("https://youtu.be/x", None))
eq("unfinished row: opens the download folder", len(app._open_folder.calls), 1)

# ── ↗ open source ────────────────────────────────────────────────────────
web = Rec(); zhd.webbrowser.open = web
app = make_app()
app._open_source(mk("https://www.facebook.com/reel/123"))
eq("page URL opens as-is", web.calls, ["https://www.facebook.com/reel/123"])

# sniffed Artgrid/Artlist rows hold a raw .m3u8 — the page is in _referers
web.calls.clear()
app._referers["https://cdn.artgrid.io/a/master.m3u8"] = "https://artgrid.io/clip/99"
app._open_source(mk("https://cdn.artgrid.io/a/master.m3u8"))
eq("sniffed stream opens the page it came from", web.calls,
   ["https://artgrid.io/clip/99"])

web.calls.clear()
app._open_source(mk("/Users/me/local.mp4"))
eq("a local file has no source page", web.calls, [])

# ── transcode needs headroom, and says so when it hasn't got it ─────────
# A 4K60 re-encode wants ~4x the source; on a tight disk keep the original.
import collections as _c0, shutil as _sh0, tempfile as _tf0
_du0 = _c0.namedtuple("du", "total used free")
big = pathlib.Path(_tf0.mkdtemp()) / "clip.mp4"
big.write_bytes(b"0" * (2 * 1024 * 1024))          # 2 MB stand-in

app = make_app()
app.cfg = {"premiere": True}
app._ffprobe_codecs = lambda p: ("vp9", "opus", "yuv420p")
app._ffprobe_duration = lambda p: 30
app._pick_hw_encoder = lambda: ("h264_videotoolbox", [])
app._mq = type("Q", (), {"put": lambda self, x: None})()
it = mk("https://youtu.be/x", str(big))
it.idx = it.total = 1

zhd.shutil.disk_usage = lambda p: _du0(1, 1, 100 * 1024**2)      # 100 MB free
app._force_h264_if_needed(it)
eq("a tight disk keeps the original file",
   any("keeping the original" in m for m in app.logs), True)
eq("and never starts the encoder", any("[transcode]" in m for m in app.logs), False)
zhd.shutil.disk_usage = _sh0.disk_usage

# ── the update cache does not hoard installers ──────────────────────────
import tempfile as _tf2
cache = pathlib.Path(_tf2.mkdtemp())
for n in ("ZHDownloader-6.6.20.pkg", "ZHDownloader-6.6.26.pkg",
          "ZHDownloader-9.9.9.pkg", "notes.txt"):
    (cache / n).write_bytes(b"x")
zhd.UPD_DIR = cache
zhd.APP_VER = "6.6.27"
zhd._prune_update_cache()
left = sorted(f.name for f in cache.iterdir())
eq("installers already applied are deleted", left,
   ["ZHDownloader-9.9.9.pkg", "notes.txt"])

# ── names Windows cannot take ───────────────────────────────────────────
eq("a reserved device name is escaped", zhd._safe_name("CON.mp4"), "_CON.mp4")
eq("…in any case", zhd._safe_name("nul.zip"), "_nul.zip")
eq("com9 too", zhd._safe_name("COM9.mov"), "_COM9.mov")
eq("a normal name is untouched", zhd._safe_name("console.mp4"), "console.mp4")
eq("trailing dots and spaces go", zhd._safe_name("clip. "), "clip")

# ── a very long name must not break the rename ──────────────────────────
app = make_app()
app.cfg = {"conflict": "rename"}
deep = pathlib.Path("/tmp/" + "d" * 60)
long_target = deep / ("t" * 300 + ".mp4")
out = app._resolve_conflict(long_target)
eq("the path is trimmed to something the OS accepts", len(str(out)) <= 400, True)
eq("…keeping the extension", out.suffix, ".mp4")

# ── cancelling mid-extraction shows a state, not silence ────────────────
app = make_app()
app._mq = queue.Queue()
app.queue = type("Q", (), {"selection": lambda self: [], "redraw": lambda self: None})()
it = mk("https://youtu.be/x"); it.status = "downloading"
it.stop_ev = threading.Event()
app.queue.selection = lambda: [it]
app._selected_items = lambda: [it]
app._cancel_selected()
eq("the row reports that it is stopping", it.status, "stopping")
eq("and the worker is told", it.stop_ev.is_set(), True)
it2 = mk("https://youtu.be/y"); it2.status = "done"; it2.stop_ev = threading.Event()
app._selected_items = lambda: [it2]
app._cancel_selected()
eq("a finished row is left alone", it2.status, "done")

# ── settings must survive a crash mid-write ─────────────────────────────
import json as _json, os as _os, tempfile as _tf3, threading as _th3
cfgp = pathlib.Path(_tf3.mkdtemp()) / "cfg.json"
REAL_JSAVE(cfgp, {"theme": "Studio", "n": 1})
eq("config written", _json.loads(cfgp.read_text())["theme"], "Studio")
eq("no temp file left behind", (cfgp.parent / (cfgp.name + ".tmp")).exists(), False)

# concurrent writers must never leave a half-file
def _writer(i):
    for k in range(40):
        REAL_JSAVE(cfgp, {"who": i, "k": k, "pad": "x" * 500})


ts = [_th3.Thread(target=_writer, args=(i,)) for i in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
try:
    _json.loads(cfgp.read_text()); ok_json = True
except Exception:
    ok_json = False
eq("six threads writing at once still leaves valid JSON", ok_json, True)

# unicode survives (a Bangla settings value, or a Bangla filename in history)
REAL_JSAVE(cfgp, {"name": "বাংলা ভিডিও"})
eq("unicode is written as text, not escapes",
   _json.loads(cfgp.read_text())["name"], "বাংলা ভিডিও")

# ── one video must not become two rows ──────────────────────────────────
app = make_app()
same = [("https://www.youtube.com/watch?v=-jgksoAlAkw&t=54s",
         "https://www.youtube.com/live/-jgksoAlAkw?si=x1KEu56m2lJ0e9-p"),
        ("https://youtu.be/-jgksoAlAkw", "https://www.youtube.com/shorts/-jgksoAlAkw"),
        ("https://www.pexels.com/download/video/29660252/",
         "https://www.pexels.com/download/video/29660252/?fps=30.0&h=1920&w=1080"),
        ("https://cdn/a/master.m3u8?token=1", "https://cdn/a/master.m3u8?token=2")]
for a, b in same:
    eq("same video: %s" % a.split("/")[-1][:28], app._dedup_key(a) == app._dedup_key(b), True)
eq("different videos stay apart",
   app._dedup_key("https://www.youtube.com/watch?v=AAA") ==
   app._dedup_key("https://www.youtube.com/watch?v=BBB"), False)

# ── a row needs a name a human can read ─────────────────────────────────
eq("a watch URL is not called 'watch'",
   zhd._provisional_name("https://www.youtube.com/watch?v=-jgksoAlAkw&t=54s"),
   "YouTube · -jgksoAlAkw")
eq("youtu.be too", zhd._provisional_name("https://youtu.be/abc123"), "YouTube · abc123")
eq("a real filename is kept",
   zhd._provisional_name("https://site/clip_final.mp4"), "clip_final.mp4")
eq("a bare id keeps its host",
   zhd._provisional_name("https://vimeo.com/download/"), "vimeo.com")

# ── routing: files must not be sent to the video extractor ──────────────
# Every one of these came out of the user's log as "no media found".
for u, want in [
    ("https://cdn.x/AEUX_0.8.2.zip?sig=abc", "file"),
    ("https://www.dropbox.com/scl/fi/x/Play_CavalryCircles.zip?rlkey=1", "file"),
    ("https://s3.x/original.mp4?response-content-disposition=attachment", "video"),
    ("https://cdn/x?fileName=pack.rar&response-content-disposition=attachment", "file"),
    ("https://www.youtube.com/watch?v=abc", "video"),
    ("https://vimeo.com/56015672", "video"),
    ("https://site/report.pdf", "file"),
    ("https://site/clip.mp4", "video"),
    ("https://site/some/page", "video"),
]:
    eq("classify %s" % u[:46], zhd.classify(u), want)

# ── server-supplied filenames ───────────────────────────────────────────
eq("RFC 5987 filename", zhd._cd_filename("attachment; filename*=UTF-8''July%2E26.mp4"),
   "July.26.mp4")
eq("quoted filename", zhd._cd_filename('attachment; filename="July 26.mp4"'), "July 26.mp4")
eq("no filename", zhd._cd_filename("inline"), "")
eq("a server name cannot escape the folder", zhd._safe_name("../../etc/passwd"), "passwd")
eq("illegal characters are dropped", zhd._safe_name('bad:name?.mp4'), "badname.mp4")

# ── fallback decision ───────────────────────────────────────────────────
app = make_app()
app.folder_var = type("V", (), {"get": lambda self: "/tmp"})()
app._referers = {}


def _fake_head(ctype="", fname="", total=0):
    def head(self):
        self.ctype = ctype
        return total, False, fname
    return head


_orig_head = zhd.FileDL._head
zhd.FileDL._head = _fake_head("text/html", "", 1000)
eq("an html page is not a file", app._downloadable_file("https://site/page"), False)
zhd.FileDL._head = _fake_head("application/zip", "", 500000)
eq("a zip is a file", app._downloadable_file("https://site/x"), True)
zhd.FileDL._head = _fake_head("", "pack.rar", 0)
eq("a named attachment is a file", app._downloadable_file("https://site/x"), True)
zhd.FileDL._head = _fake_head("", "", 0)
eq("no headers at all → don't guess", app._downloadable_file("https://site/x"), False)
zhd.FileDL._head = _orig_head

# ── cookies for plain file downloads (Cloudflare 403s without them) ─────
app = make_app()
app.ck_var = type("V", (), {"get": lambda self: "none"})()
eq("cookies off → no header", app._cookie_header_for("https://site/x.zip"), "")

app.ck_var = type("V", (), {"get": lambda self: "chrome"})()
app._cookie_jar_cache = {"chrome": [
    type("C", (), {"domain": ".site.com", "name": "a", "value": "1"})(),
    type("C", (), {"domain": "other.com", "name": "b", "value": "2"})(),
]}
eq("only this host's cookies are sent",
   app._cookie_header_for("https://cdn.site.com/x.zip"), "a=1")
eq("a different host gets nothing",
   app._cookie_header_for("https://elsewhere.net/x.zip"), "")

hdrs = zhd.FileDL("https://site/x.zip", "/tmp", referer="https://site/page",
                  cookie="a=1")._headers()
eq("the file downloader sends a browser UA",
   "Chrome" in hdrs["User-Agent"], True)
eq("…the referer", hdrs.get("Referer"), "https://site/page")
eq("…and the cookies", hdrs.get("Cookie"), "a=1")

# ── the app remembers the extension between restarts ────────────────────
app = make_app()
app.cfg = {}
eq("no memory yet → banner would show", bool(app.cfg.get("ext_last_seen")), False)
import time as _t
app.cfg["ext_last_seen"] = int(_t.time()) - 90
eq("a minute-old sighting reads as minutes", app._ago(_t.time() - app.cfg["ext_last_seen"]), "1m")
eq("seconds stay seconds", app._ago(30), "30s")
eq("hours roll up", app._ago(7200), "2h")
eq("days roll up", app._ago(3 * 86400), "3d")

# ── full disk: refuse to start, and say so ──────────────────────────────
import collections as _c
import shutil as _sh

_du = _c.namedtuple("du", "total used free")
app = make_app()
app.status_var = type("V", (), {"set": lambda self, v: None})()
zhd.shutil.disk_usage = lambda p: _du(500, 499, 200 * 1024 * 1024)   # 200 MB left
eq("a nearly full disk blocks the start", app._space_ok("/tmp"), False)
eq("and the log names the real problem",
   any("free on the disk" in m for m in app.logs), True)
app.logs.clear()
zhd.shutil.disk_usage = lambda p: _du(500, 100, 40 * 1024**3)        # 40 GB left
eq("plenty of room starts normally", app._space_ok("/tmp"), True)
eq("and stays quiet", app.logs, [])
zhd.shutil.disk_usage = _sh.disk_usage

eq("the disk-full error explains itself",
   "disk is full" in zhd._error_hint("ERROR: [Errno 28] No space left on device: '/x/y.webp'"),
   True)

# ── Pinterest: variant playlist → master (full quality) ──────────────────
H = "https://v1.pinimg.com/videos/iht/hls/23/65/73/abc123abc123def"
eq("a 540w variant is rewritten to the master",
   zhd._pinterest_master(H + "_540w.m3u8"), H + ".m3u8")
eq("a 720w variant too", zhd._pinterest_master(H + "_720w.m3u8"), H + ".m3u8")
eq("query strings survive", zhd._pinterest_master(H + "_240w.m3u8?a=1"), H + ".m3u8?a=1")
eq("the master is left alone", zhd._pinterest_master(H + ".m3u8"), H + ".m3u8")
eq("other CDNs are untouched",
   zhd._pinterest_master("https://cdn.artlist.io/a/master_720w.m3u8"),
   "https://cdn.artlist.io/a/master_720w.m3u8")
eq("a pin page URL is untouched",
   zhd._pinterest_master("https://www.pinterest.com/pin/123/"),
   "https://www.pinterest.com/pin/123/")

# ── error hints (what the user should DO about a failure) ────────────────
eq("vimeo login wall names the site",
   "vimeo.com" in zhd._error_hint("ERROR: [vimeo] The web client only works when logged-in.",
                                  "https://vimeo.com/56015672"), True)
eq("blob: URL is explained",
   zhd._error_hint("no media", "blob:https://suno.com/52b5cc23").startswith("blob:"), True)
eq("unsupported site points at the extension",
   "extension" in zhd._error_hint("ERROR: Unsupported URL: https://frame.io/x"), True)
eq("403 suggests cookies",
   "Cookies" in zhd._error_hint("ERROR: unable to download video data: HTTP Error 403: Forbidden"), True)
eq("a plain failure gets no invented advice",
   zhd._error_hint("ERROR: [youtube] xyz: Video unavailable"), "")

# ── Text size → font helpers ─────────────────────────────────────────────
zhd._FAM_CACHE[("x",)] = "x"          # keep _pick_family off a live Tk root
zhd.UI_SCALE = 1.0
eq("default bumps the old sizes by 2 pt", zhd._f(10)[1], 12)
eq("style flags are preserved", zhd._f(10, "bold")[2], "bold")
zhd.UI_SCALE = zhd.TEXT_SIZES["Large"]
eq("Large scales on top of the bump", zhd._f(10)[1], round(12 * 1.15))
zhd.UI_SCALE = zhd.TEXT_SIZES["Extra large"]
eq("Extra large scales too", zhd._f(9)[1], round(11 * 1.3))
eq("mono keeps its own baseline", zhd._mono(9)[1], round(10 * 1.3))
zhd.UI_SCALE = 1.0

print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
