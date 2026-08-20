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

root.destroy()
print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
