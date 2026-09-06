"""_do_start queue-preservation tests.

Drives the real App._do_start against a bare instance (no Tk mainloop) with the
few widgets/IO it touches stubbed out. Covers the bug where sending a new URL
from the browser extension wiped a paused / still-downloading / errored row:
`kept` used to keep only status == "done".

    python3 tests/queue_test.py
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
zhd.jsave = lambda *a, **k: None          # keep the test off the real state file

fails = passes = 0


def eq(label, got, want):
    global fails, passes
    ok = got == want
    if ok:
        passes += 1
    else:
        fails += 1
    print(("PASS  " if ok else "FAIL  ") + label + " = " + repr(got) +
          ("" if ok else "  (want " + repr(want) + ")"))


class Fake:
    """Swallows every widget call the method makes."""
    def __getattr__(self, _):
        return lambda *a, **k: None


class FakeBox(Fake):
    def get(self, *a, **k):
        return ""


def make_app(items):
    app = zhd.App.__new__(zhd.App)
    app._items = items
    app._run_items = []
    app._stop = threading.Event()
    app._paused = False
    app._done_files = []
    app._spd_history = []
    app._referers = {}
    app._workers = []
    app._mq = queue.Queue()
    app._heal_tries = {}
    app.state = {}
    app.cfg = {}
    app.logs = []
    app.log = lambda m: app.logs.append(m)
    app._build_rows = lambda *a, **k: None
    app.is_pro = lambda: True
    app.url_box = FakeBox()
    app.btn_dl = app.btn_cancel = app.btn_pause = app.res_frame = Fake()
    app.concur_var = Fake()

    def runner(item):                      # finish instantly so the watcher exits
        item.status = "done"
    app._runner = runner
    app._space_ok = lambda out: True       # don't let a full test-runner disk skip _do_start
    return app


def mk(url, status, name=None):
    it = zhd.DL(url, 0, 0, "")
    it.status = status
    if name:
        it.name = name
    return it


Y = "https://www.youtube.com/watch?v="

# ── 1. unfinished rows survive a new send ─────────────────────────────────
a, b, c = mk(Y + "AAA", "done"), mk(Y + "BBB", "paused"), mk(Y + "CCC", "error")
app = make_app([a, b, c])
app._do_start([Y + "DDD"], "/tmp", "hd")
eq("all four rows kept", [i.url for i in app._items],
   [Y + "AAA", Y + "BBB", Y + "CCC", Y + "DDD"])
eq("paused row still paused", b.status, "paused")
eq("only the finished row is display-only",
   [getattr(i, "_prev_run", False) for i in app._items], [True, False, False, False])
eq("worker spawned for the new URL only", [i.url for i in app._run_items], [Y + "DDD"])

# ── 2. a still-downloading row is not dropped either ──────────────────────
live = mk(Y + "LIVE", "downloading")
app = make_app([live])
app._do_start([Y + "NEW"], "/tmp", "hd")
eq("in-flight row survives", [i.url for i in app._items], [Y + "LIVE", Y + "NEW"])
eq("in-flight row not marked display-only", getattr(live, "_prev_run", False), False)

# ── 3. re-sending the one URL already queued → re-runs it, no second row ──
# (this hits the "URL list unchanged" branch, which resets and re-runs in place)
paused = mk(Y + "SAME", "paused")
app = make_app([paused])
app._do_start([Y + "SAME"], "/tmp", "hd")
eq("no duplicate row", [i.url for i in app._items], [Y + "SAME"])
eq("the existing row is what re-runs", [i.url for i in app._run_items], [Y + "SAME"])

# ── 4. mixed batch: dup filtered, genuinely new one still starts ──────────
paused = mk(Y + "SAME", "paused")
app = make_app([paused])
app._do_start([Y + "SAME", Y + "OTHER"], "/tmp", "hd")
eq("only the new URL is added", [i.url for i in app._items], [Y + "SAME", Y + "OTHER"])
eq("and only it gets a worker", [i.url for i in app._run_items], [Y + "OTHER"])
eq("paused row left alone", paused.status, "paused")
eq("user told how to resume it",
   any("already in the list" in m for m in app.logs), True)

# ── 5. finished rows still capped at 20 ──────────────────────────────────
app = make_app([mk(Y + "D%02d" % n, "done") for n in range(25)])
app._do_start([Y + "NEW"], "/tmp", "hd")
eq("oldest finished rows trimmed", len(app._items), 21)
eq("kept the newest 20", app._items[0].url, Y + "D05")

# ── 6. two different YouTube videos are never confused ───────────────────
app = make_app([mk(Y + "AAA", "paused")])
app._do_start([Y + "BBB"], "/tmp", "hd")
eq("different ?v= is a different video", len(app._items), 2)

print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
