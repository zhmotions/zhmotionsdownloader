"""Screenshot the real app window — never ship UI changes unseen.

Builds a throwaway copy of zh_downloader.py that (a) uses its own bridge port so
it can't disturb a running instance, (b) runs against an isolated HOME so it
touches no real config/state, (c) seeds three fake queue rows, then captures its
own window by CGWindowID (works even behind other windows / on another Space).

    python3 tests/ui_shot.py out.png              # Downloads tab
    python3 tests/ui_shot.py out.png --tab 3      # Settings tab
    python3 tests/ui_shot.py out.png --theme macOS --size "Extra large"

macOS only (uses screencapture + Quartz); run it with the venv python that has
the app's deps: .venv/bin/python tests/ui_shot.py …
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC  = ROOT / "zh_downloader.py"

HARNESS = '''
    # ── ui_shot harness ──────────────────────────────────────────────────
    import os as _os, subprocess as _sp
    def _seed():
        try:
            rows = [("Sunset Timelapse over Dhaka 4K.mp4", "done", 100),
                    ("Facebook reel — Astaxanthin promo", "downloading", 62),
                    ("Artgrid — city night b-roll", "waiting", 0)]
            items = []
            for i, (nm, st, pc) in enumerate(rows, 1):
                it = DL("https://example.com/clip%d" % i, i, len(rows), "")
                it.name = nm; it.status = st; it.pct = pc
                it.done_f = _os.environ.get("ZH_SHOT_FILE") if st == "done" else None
                it.size_v = 148 * 1024 * 1024
                it.speed_v = int(5.2 * 1024 * 1024) if st == "downloading" else 0
                it.eta_v = 34 if st == "downloading" else None
                items.append(it)
            _app._items = items; _app._build_rows(items)
        except Exception as e: print("[ui_shot] seed failed:", e, flush=True)
    def _tab():
        try:
            n = int(_os.environ.get("ZH_SHOT_TAB", "0"))
            if n: _app.nb.select(n)
        except Exception as e: print("[ui_shot] tab failed:", e, flush=True)
    def _ready():
        try:
            root.deiconify(); root.attributes("-topmost", True); root.update()
            print("[ui_shot] ready", flush=True)
        except Exception as e: print("[ui_shot] ready failed:", e, flush=True)
    root.after(3000, _seed); root.after(3600, _tab); root.after(4200, _ready)
    root.after(int(_os.environ.get("ZH_ALIVE_MS", "40000")), root.destroy)
'''


def build_preview(dst):
    s = SRC.read_text()
    s = s.replace("BRIDGE_PORT = 9613", "BRIDGE_PORT = 9613 + 100", 1)   # own port
    s = s.replace("        App(root)", "        _app = App(root)", 1)
    s = s.replace("    root.mainloop()", HARNESS + "    root.mainloop()", 1)
    dst.write_text(s)


def _quartz_capture(wid, out):
    """Render one window to PNG through the window server."""
    try:
        import Quartz
        from Quartz import CoreGraphics as CG
        img = Quartz.CGWindowListCreateImage(
            CG.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, wid,
            Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution)
        if img is None or Quartz.CGImageGetWidth(img) < 200: return
        url = CG.CFURLCreateWithFileSystemPath(None, str(out), CG.kCFURLPOSIXPathStyle, False)
        dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
        if not dest: return
        Quartz.CGImageDestinationAddImage(dest, img, None)
        Quartz.CGImageDestinationFinalize(dest)
    except Exception as e:
        print("[ui_shot] quartz capture failed:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--tab", default="0")
    ap.add_argument("--theme", default="Graphite")
    ap.add_argument("--size", default="Default")
    ap.add_argument("--cfg", action="append", default=[],
                    help="extra config, e.g. --cfg adv_open=1 --cfg log_open=1")
    a = ap.parse_args()

    import Quartz                                    # noqa: F401  (macOS only)
    work = pathlib.Path(tempfile.mkdtemp(prefix="zh-uishot-"))
    home = work / "home"; (home / ".config" / "zhdownloader").mkdir(parents=True)
    lic = pathlib.Path.home() / ".config" / "zhdownloader" / "license.json"
    if lic.exists():                                  # skip the license gate
        (home / ".config" / "zhdownloader" / "license.json").write_bytes(lic.read_bytes())
    cfg = {"theme": a.theme, "text_size": a.size}
    for kv in a.cfg:
        k, _, v = kv.partition("=")
        cfg[k] = {"1": True, "0": False, "true": True, "false": False}.get(v.lower(), v)
    (home / ".zhdownloader.json").write_text(json.dumps(cfg))
    sample = home / "Sample clip.mp4"; sample.write_bytes(b"0" * 2048)

    # res_path() looks for assets/ next to the script, so the copy needs its own
    # (without it the header logo silently vanishes from the screenshot)
    try: (work / "assets").symlink_to(ROOT / "assets")
    except Exception: pass
    preview = work / "ui_preview.py"; build_preview(preview)
    log = work / "run.log"
    env = dict(os.environ, HOME=str(home), ZH_SHOT_TAB=a.tab, ZH_SHOT_FILE=str(sample))
    p = subprocess.Popen([sys.executable, str(preview)],
                         stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env, cwd=str(ROOT))
    for _ in range(60):
        time.sleep(0.5)
        if "[ui_shot] ready" in log.read_text(): break
    else:
        p.terminate(); sys.exit("app never reported ready — see " + str(log))
    time.sleep(1.0)

    wins = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    win = next((w for w in wins
                if w.get("kCGWindowOwnerPID") == p.pid
                and "ZH Downloader" in str(w.get("kCGWindowName") or "")
                and w.get("kCGWindowBounds", {}).get("Height", 0) > 400), None)
    if not win:
        p.terminate(); sys.exit("app window not found in the window list")
    out = pathlib.Path(a.out)
    # Quartz composites the window straight out of the window server, so it works
    # while the window is covered or parked on another Space. screencapture -l is
    # the fallback, then the plain screen region.
    _quartz_capture(win["kCGWindowNumber"], out)
    if not out.exists() or out.stat().st_size < 20000:
        subprocess.run(["screencapture", "-x", "-o", "-l%d" % win["kCGWindowNumber"], a.out])
    if not out.exists() or out.stat().st_size < 20000:
        b = win["kCGWindowBounds"]
        subprocess.run(["screencapture", "-x", "-o", "-R%d,%d,%d,%d"
                        % (b["X"], b["Y"], b["Width"], b["Height"]), a.out])
        print("[ui_shot] window capture failed — used the screen region instead")
    p.terminate()
    if not out.exists() or out.stat().st_size < 20000:
        sys.exit("capture failed — got no usable image")
    print("shot:", a.out, "(theme %s, text %s, tab %s)" % (a.theme, a.size, a.tab))


if __name__ == "__main__":
    main()
