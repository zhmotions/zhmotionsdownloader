"""Whole-UI smoke test: build the real App and poke the parts other code calls.

The UI rewrite moved widgets between frames (Download button out of the tab, the
options into a collapsible card, the log behind a toggle). Anything that still
reaches for a widget by attribute — schedulers, the queue runner, dialogs, the
tray — breaks only at runtime, so this builds the actual window on a withdrawn
root, with HOME redirected to a temp dir and the network/bridge/tray stubbed.

    python3 tests/smoke_ui_test.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
import threading

HOME = tempfile.mkdtemp(prefix="zh-smoke-")
os.environ["HOME"] = HOME                      # before import: paths are module-level

import tkinter as tk                           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "zh_downloader.py"
spec = importlib.util.spec_from_file_location("zhd", SRC)
zhd  = importlib.util.module_from_spec(spec)
sys.modules["zhd"] = zhd
spec.loader.exec_module(zhd)

fails = passes = 0


def ok(label, cond, detail=""):
    global fails, passes
    passes += bool(cond); fails += not bool(cond)
    print(("PASS  " if cond else "FAIL  ") + label + (("  " + detail) if detail and not cond else ""))


def check(label, fn):
    try:
        fn(); ok(label, True)
    except Exception as e:
        ok(label, False, "%s: %s" % (type(e).__name__, e))


assert str(zhd.CFG_PATH).startswith(HOME), "test would have written the real config"

# keep the app off the network, the bridge port, the tray and the update check
for name in ("_start_bridge", "_setup_tray", "_check_resume", "_poll", "_poll_clip",
             "_check_for_updates_async", "_reverify_license", "_restore_basket_if_on",
             "_license_gate", "_apply_autostart"):
    setattr(zhd.App, name, lambda self, *a, **k: None)
zhd.App._licensed = lambda self: True
zhd.App.is_pro    = lambda self: True

try:
    root = tk.Tk()
except Exception as e:
    print("SKIP: no Tk display (%s)" % e); sys.exit(0)
root.withdraw()

app = zhd.App(root)
root.update_idletasks()
ok("the whole window builds", True)

# ── widgets other code reaches for by attribute ──────────────────────────
for attr in ("url_box", "btn_dl", "btn_pause", "btn_cancel", "nb", "q_frame", "log_txt",
             "status_var", "spd_var", "graph", "folder_var", "fmt_var", "mode_var",
             "ck_var", "sub_var", "thumb_var", "pl_var", "_sched_var", "_sched_lbl",
             "res_frame", "res_lbl", "_pro_btn", "_dot", "_concur_lbl", "hist_tree",
             "_adv_frame", "_act_row", "_log_head", "_log_body", "_log_toggle",
             "concur_var", "rate_var", "conf_var", "slang_var"):
    ok("App.%s exists" % attr, hasattr(app, attr))

# ── the buttons the rest of the code drives ─────────────────────────────
check("btn_dl takes state+text (start/schedule/finish paths)",
      lambda: (app.btn_dl.configure(state="disabled", text="Running..."),
               app.btn_dl.configure(state="normal", text="↓  Download")))
check("btn_pause / btn_cancel take state",
      lambda: (app.btn_pause.configure(state="normal"),
               app.btn_cancel.configure(state="disabled")))

# ── the new toggles, both directions, twice ─────────────────────────────
check("Advanced options folds and unfolds",
      lambda: [app._toggle_adv(v) for v in (True, False, True, False)])
check("log panel shows and hides",
      lambda: [app._toggle_log(v) for v in (True, False, True, False)])
check("folded summary reads the current settings", app._adv_summary)

# ── queue rows: build, update, act ───────────────────────────────────────
item = zhd.DL("https://www.youtube.com/watch?v=smoke", 1, 1, "")
item.status = "downloading"; item.pct = 42; item.done_f = None
item.stop_ev = threading.Event()
check("queue cards build", lambda: app._build_rows([item]))
root.update_idletasks()
check("row updates for every status", lambda: [
    (setattr(item, "status", st), app._update_row(item))
    for st in ("waiting", "downloading", "paused", "done", "error", "cancelled")])
ok("row keeps its widget refs",
   all(getattr(item, a, None) is not None
       for a in ("_lbl_icon", "_lbl_meta", "_prog", "_btn_pause", "_btn_folder", "_btn_src")))
check("empty queue renders", lambda: app._build_rows([]))

# ── menu / dialog entry points that touch moved widgets ─────────────────
zhd.messagebox.showinfo = lambda *a, **k: None
zhd.messagebox.showwarning = lambda *a, **k: None
zhd.messagebox.askyesno = lambda *a, **k: False
check("Clear Queue", app._clear_queue)
check("Clear Log", app._clear_log)
check("log writes", lambda: app.log("[info] smoke"))
check("status bar updates", lambda: app.status_var.set("smoke"))
check("theme switch re-styles", lambda: app.set_theme("macOS", refresh=False))
check("text-size setting saves", lambda: app._on_text_size("Large"))
check("settings save path", lambda: app._save_setting("concurrent", 4))
check("schedule label updates", lambda: app._sched_var.set("In 1 hour"))
check("stats view rebuilds", app._build_stats_view)
check("history view refreshes", app._hist_refresh)
check("history reveal survives an empty selection", app._hist_reveal)
check("basket toggles", app._toggle_basket)
check("basket toggles back", app._toggle_basket)

root.destroy()
print()
print(("%d FAILED, " % fails if fails else "") + "%d passed" % passes)
sys.exit(1 if fails else 0)
