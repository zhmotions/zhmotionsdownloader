"""Custom-drawn control tests: RoundedButton, RoundedSelect, Switch.

These replaced the ttk button / OptionMenu / Checkbutton in the new UI. Both
bugs found while building them were attribute shadowing (self._w and
self._options are tkinter internals), which only shows up at widget creation —
so the test creates them for real on a withdrawn Tk root.

    python3 tests/widgets_test.py
"""
import importlib.util
import pathlib
import sys
import tkinter as tk

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


try:
    root = tk.Tk()
except Exception as e:                       # headless box, no display
    print("SKIP: no Tk display (%s)" % e)
    sys.exit(0)
root.withdraw()
frame = tk.Frame(root, bg=zhd.T["BG"]); frame.pack()

# ── RoundedButton ────────────────────────────────────────────────────────
clicks = []
b = zhd.RoundedButton(frame, "↓  Download", lambda: clicks.append(1))
eq("button was created", bool(b.winfo_exists()), True)
eq("it drew something", len(b.find_all()) >= 2, True)
b._release()
eq("click runs the command", len(clicks), 1)

b.configure(state="disabled")
b._release()
eq("disabled button ignores clicks", len(clicks), 1)
eq("state is readable", b.cget("state"), "disabled")

b.configure(state="normal", text="Running...")
eq("text is settable (used for Running…/Scheduled…)", b.cget("text"), "Running...")
b._release()
eq("re-enabled button clicks again", len(clicks), 2)

# ── RoundedSelect ────────────────────────────────────────────────────────
picked = []
var = tk.StringVar(value="none")
sel = zhd.RoundedSelect(frame, var, ["none", "chrome", "safari"], width=120,
                        command=lambda v: picked.append(v))
eq("select was created", bool(sel.winfo_exists()), True)
sel._choose("chrome")
eq("choosing sets the variable", var.get(), "chrome")
eq("and fires the callback", picked, ["chrome"])
var.set("safari")                      # external change (cfg load, reset…)
eq("variable stays the source of truth", var.get(), "safari")

# ── Switch ───────────────────────────────────────────────────────────────
fired = []
bv = tk.BooleanVar(value=False)
sw = zhd.Switch(frame, "Thumbnail", bv, command=lambda: fired.append(bv.get()))
eq("switch was created", bool(sw.winfo_exists()), True)
sw._toggle()
eq("toggle turns it on", bv.get(), True)
eq("callback sees the new value", fired, [True])
sw._toggle()
eq("toggle turns it off", bv.get(), False)

# ── RoundedSlider ────────────────────────────────────────────────────────
saved = []
iv = tk.IntVar(value=3)
sl = zhd.RoundedSlider(frame, iv, from_=1, to=5, step=1, width=100,
                       command=lambda v: saved.append(v))
eq("slider was created", bool(sl.winfo_exists()), True)


class E:                       # a click at a given x
    def __init__(self, x): self.x = x


sl._set_from_x(E(8 + 100))     # far right = max
eq("dragging to the end gives the max", iv.get(), 5)
sl._set_from_x(E(8))           # far left = min
eq("dragging to the start gives the min", iv.get(), 1)
sl._set_from_x(E(-50))         # outside the track
eq("out-of-track drags clamp", iv.get(), 1)
eq("every change was saved", saved, [5, 1])

# ── RoundedPanel ─────────────────────────────────────────────────────────
panel = zhd.RoundedPanel(frame, radius=10)
tk.Label(panel.inner, text="card content").pack()
panel.pack(fill="x")
root.update_idletasks()
eq("panel has an inner content frame", bool(panel.inner.winfo_exists()), True)
eq("panel accepts a ttk parent bg lookup", zhd._pbg(panel) != "", True)

# ── QueueList: the row action icons must actually fire ──────────────────
# They were dead once: the row-wide click rectangle overlaps every glyph, and
# find_overlapping matches by bounding box, so the row always won the hit test.
calls = []


class FakeApp:
    def _pause_item(self, i):  calls.append(("pause", i))
    def _reveal_item(self, i): calls.append(("folder", i))
    def _open_source(self, i): calls.append(("source", i))
    def _remove_item(self, i): calls.append(("remove", i))
    def _sync_toolbar(self):   pass
    def _queue_menu(self, e):  pass


class Ev:
    def __init__(self, x, y, state=0): self.x, self.y, self.state = x, y, state


import tempfile as _tf
tmpf = pathlib.Path(_tf.mkdtemp()) / "done.mp4"
tmpf.write_bytes(b"x" * 32)

done = zhd.DL("https://youtu.be/a", 1, 2, ""); done.status = "done"; done.done_f = str(tmpf)
live = zhd.DL("https://youtu.be/b", 2, 2, ""); live.status = "downloading"; live.pct = 40

ql = zhd.QueueList(frame, FakeApp())
ql.pack(fill="both", expand=True)
ql.configure(width=900, height=300)
root.update_idletasks()
ql.set_items([done, live])
root.update_idletasks()


def click_action(item, action):
    """Click the middle of that row's action pad."""
    ids = [c for c in ql.find_withtag("a=%s" % action)
           if ("i=%s" % item.id) in ql.gettags(c)]
    x1, y1, x2, y2 = ql.bbox(ids[0])
    ql._click(Ev((x1 + x2) // 2, (y1 + y2) // 2))


eq("list drew both rows", len(ql.items), 2)
click_action(done, "folder")
eq("folder icon fires on a finished row", [c[0] for c in calls], ["folder"])
click_action(done, "source")
eq("source icon fires", [c[0] for c in calls][-1], "source")
click_action(live, "pause")
eq("pause icon fires on the live row", [c[0] for c in calls][-1], "pause")
calls.clear()
click_action(live, "folder")          # no file yet → disabled
eq("folder stays dead while the file does not exist", calls, [])
click_action(done, "remove")
eq("remove icon fires", [c[0] for c in calls], ["remove"])

# clicking the row body selects instead of acting
calls.clear()
ql._click(Ev(300, 30))
eq("clicking the row body selects it", len(ql.selection()), 1)
eq("and runs no action", calls, [])

root.destroy()
print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
