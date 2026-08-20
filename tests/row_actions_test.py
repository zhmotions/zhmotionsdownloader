"""Queue-row action tests: the 📂 (show in Finder) and ↗ (open source page)
buttons added to every card, plus the font helpers behind the Text size setting.

    python3 tests/row_actions_test.py            # current source
    python3 tests/row_actions_test.py old.py     # an older copy, to see it fail
"""
import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "zh_downloader.py"
spec = importlib.util.spec_from_file_location("zhd", SRC)
zhd  = importlib.util.module_from_spec(spec)
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
