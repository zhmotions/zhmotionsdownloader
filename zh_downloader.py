"""
ZH Downloader v5.1 - Universal Download Manager by ZH Motions
IDM-class features: tabs, concurrent downloads, history, stats, themes,
categories, speed limit, conflict dialog, completion actions,
drag-drop URLs, tray icon, card thumbnails.
"""

import os, sys, threading, queue as Q, json, subprocess, shutil, platform
import re, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import yt_dlp
except ImportError:
    print("Run: pip install -r requirements.txt"); sys.exit(1)

# Optional deps (degrade gracefully if missing)
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from tkinterdnd2 import TkinterDnD, DND_TEXT, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

try:
    import pystray
    # pystray on macOS calls [NSApplication run] from a background thread which
    # conflicts with Tkinter's main-thread NSApplication and crashes via
    # "NSUpdateCycleInitialize called off the main thread". Disable on Darwin.
    HAS_TRAY = (platform.system() != "Darwin")
except ImportError:
    HAS_TRAY = False

# -- Constants --------------------------------------------------------------
APP_NAME    = "ZH Downloader"
APP_VER     = "5.5.0"
APP_AUTHOR  = "ZH Motions"
APP_URL     = "https://zhmotions.com"
BRIDGE_PORT = 9613

DEFAULT_DIR  = str(Path.home() / "Downloads" / "ZHDownloader")
CFG_PATH     = Path.home() / ".zhdownloader.json"
STATE_PATH   = Path.home() / ".zhdownloader-state.json"
HIST_PATH    = Path.home() / ".zhdownloader-history.json"
STATS_PATH   = Path.home() / ".zhdownloader-stats.json"
PARTS_DIR    = Path.home() / ".zhdownloader-parts"
THUMBS_DIR   = Path.home() / ".zhdownloader-thumbs"

THREADS         = 8
MAX_HISTORY     = 500
MAX_CONCURRENT  = 5

# -- Themes -----------------------------------------------------------------
THEMES = {
    # Default light — clean modern flat UI
    "Light": {
        "BG":"#f5f6f8","SURF":"#ffffff","SURF2":"#eceef2","BORDER":"#d6d9e0",
        "ACCENT":"#2563eb","ACCENT2":"#1d4ed8","MAROON":"#dbeafe",
        "TEXT":"#1f2937","MUTED":"#6b7280",
        "GREEN":"#10b981","YELLOW":"#f59e0b","RED":"#ef4444","BLUE":"#3b82f6","PURPLE":"#8b5cf6",
        "HEADER":"#ffffff","INPUT":"#ffffff","LOG_BG":"#f8fafc","LOG_FG":"#475569",
    },
    "Cream": {
        "BG":"#faf7f2","SURF":"#ffffff","SURF2":"#f0ebe2","BORDER":"#d4c5b0",
        "ACCENT":"#d97706","ACCENT2":"#b45309","MAROON":"#fed7aa",
        "TEXT":"#3d2914","MUTED":"#92715c",
        "GREEN":"#16a34a","YELLOW":"#ca8a04","RED":"#dc2626","BLUE":"#0284c7","PURPLE":"#9333ea",
        "HEADER":"#ffffff","INPUT":"#ffffff","LOG_BG":"#fdfbf7","LOG_FG":"#7a5a3a",
    },
    "Sunset": {
        "BG":"#160800","SURF":"#1e0d02","SURF2":"#271205","BORDER":"#3d1e08",
        "ACCENT":"#ff8c42","ACCENT2":"#ff6b35","MAROON":"#8b2500",
        "TEXT":"#ffddc0","MUTED":"#7a4a2a",
        "GREEN":"#6fcf97","YELLOW":"#f2c94c","RED":"#eb5757","BLUE":"#56ccf2","PURPLE":"#bb86fc",
        "HEADER":"#2a0e00","INPUT":"#1e0d02","LOG_BG":"#0d0500","LOG_FG":"#5a3010",
    },
    "Midnight": {
        "BG":"#0a0e1a","SURF":"#111729","SURF2":"#1a2238","BORDER":"#2a3550",
        "ACCENT":"#5b9aff","ACCENT2":"#3d7fd6","MAROON":"#1f3a6e",
        "TEXT":"#dde8ff","MUTED":"#5a6a8a",
        "GREEN":"#34d399","YELLOW":"#fbbf24","RED":"#f87171","BLUE":"#60a5fa","PURPLE":"#a78bfa",
        "HEADER":"#0d1428","INPUT":"#111729","LOG_BG":"#070b15","LOG_FG":"#3a4860",
    },
    "Forest": {
        "BG":"#0c1612","SURF":"#152822","SURF2":"#1d3a30","BORDER":"#2a503f",
        "ACCENT":"#7ed957","ACCENT2":"#5cb83d","MAROON":"#1d3d2a",
        "TEXT":"#dff5e3","MUTED":"#5a7a68",
        "GREEN":"#86efac","YELLOW":"#fde047","RED":"#fb7185","BLUE":"#5eead4","PURPLE":"#c084fc",
        "HEADER":"#0f1d18","INPUT":"#152822","LOG_BG":"#070d0a","LOG_FG":"#3a5547",
    },
    "Mono Dark": {
        "BG":"#1a1a1a","SURF":"#252525","SURF2":"#303030","BORDER":"#454545",
        "ACCENT":"#e5e5e5","ACCENT2":"#cccccc","MAROON":"#3a3a3a",
        "TEXT":"#f0f0f0","MUTED":"#888888",
        "GREEN":"#a0d995","YELLOW":"#e8d56b","RED":"#e89090","BLUE":"#9bc8e8","PURPLE":"#c8a8e8",
        "HEADER":"#202020","INPUT":"#252525","LOG_BG":"#101010","LOG_FG":"#555555",
    },
}

# Active theme - mutated at runtime via set_theme()
T = THEMES["Light"].copy()

# -- File categories --------------------------------------------------------
CATEGORIES = {
    "Video": (".mp4",".mkv",".mov",".avi",".webm",".flv",".m4v",".wmv",".mpg",".mpeg",".ts",".m3u8",".mpd"),
    "Audio": (".mp3",".wav",".flac",".aac",".m4a",".ogg",".opus",".wma"),
    "Image": (".jpg",".jpeg",".png",".gif",".webp",".svg",".bmp",".tiff",".heic"),
    "Document": (".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".epub",".rtf"),
    "Archive": (".zip",".rar",".7z",".tar",".gz",".bz2",".iso"),
    "App": (".exe",".dmg",".pkg",".msi",".apk",".deb",".rpm"),
}

def categorize(filename):
    ext = Path(filename).suffix.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts: return cat
    return "Other"

# -- Helpers ----------------------------------------------------------------
def jload(p, d):
    try:
        if Path(p).exists(): return json.loads(Path(p).read_text())
    except: pass
    return d

def jsave(p, d):
    try: Path(p).write_text(json.dumps(d, indent=2))
    except: pass

def find_ff():
    """Locate bundled ffmpeg binary. Search PATH, PyInstaller temp,
    executable dir, common install locations. Required for HD merge."""
    # 1. System PATH first
    p = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if p and Path(p).exists(): return p

    # 2. PyInstaller temp dir (_MEIPASS for onefile, app bundle for macOS)
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates += [meipass/"ffmpeg.exe", meipass/"ffmpeg",
                       meipass/"bin"/"ffmpeg.exe", meipass/"bin"/"ffmpeg"]

    # 3. Executable directory (next to the .exe)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates += [exe_dir/"ffmpeg.exe", exe_dir/"ffmpeg",
                       exe_dir/"bin"/"ffmpeg.exe"]

    # 4. Script directory (run from source)
    here = Path(__file__).parent
    candidates += [here/"ffmpeg.exe", here/"ffmpeg",
                   here/"bin"/"ffmpeg.exe"]

    # 5. Common Windows install paths
    if platform.system() == "Windows":
        candidates += [
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
        ]

    for c in candidates:
        if c.exists():
            return str(c)
    return None

def res_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

def sz(b):
    if not b: return ""
    for u in ("B","KB","MB","GB"):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"

def spd(bps): return sz(bps)+"/s" if bps else "-"

def eta(s):
    if s is None or s < 0: return "-"
    m,s = divmod(int(s),60); h,m = divmod(m,60)
    if h: return f"{h}h{m}m"
    if m: return f"{m}m{s}s"
    return f"{s}s"

def now_iso():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")

# -- URL classifier ---------------------------------------------------------
VH = ("youtube.com","youtu.be","vimeo.com","tiktok.com","instagram.com",
      "facebook.com","fb.watch","twitter.com","x.com","twitch.tv",
      "reddit.com","dailymotion.com","pinterest.com","soundcloud.com",
      "bilibili.com","rumble.com","bitchute.com","odysee.com","streamable.com",
      "artgrid.io","artlist.io","patreon.com")
VE = (".mp4",".m3u8",".mpd",".webm",".mov",".mkv",".ts",".flv")
FE = (".pdf",".zip",".rar",".7z",".exe",".dmg",".pkg",".msi",
      ".jpg",".jpeg",".png",".gif",".webp",".svg",".mp3",".wav",
      ".flac",".aac",".doc",".docx",".xls",".xlsx",".ppt",".pptx",
      ".apk",".iso",".tar",".gz",".bz2",".epub",".torrent")
URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.I)

def classify(url):
    if not url: return None
    u = url.strip().lower()
    if not URL_RE.match(url.strip()): return None
    if any(h in u for h in VH): return "video"
    if any(u.endswith(e) for e in VE): return "video"
    if any(u.endswith(e) for e in FE): return "file"
    return "video"

def type_badge(url):
    u = url.lower()
    if any(h in u for h in VH): return "VIDEO"
    if any(x in u for x in (".mp3",".wav",".flac","soundcloud")): return "AUDIO"
    if ".pdf" in u: return "PDF"
    if any(x in u for x in (".zip",".rar",".7z")): return "ZIP"
    if any(x in u for x in (".exe",".dmg",".pkg",".msi")): return "APP"
    if any(x in u for x in (".jpg",".png",".gif",".webp")): return "IMG"
    return "FILE"

# -- Format options ---------------------------------------------------------
# Aggressive HD floor: require height>=1080 for HD format, height>=2160 for 4K.
# If source has no HD/4K, yt-dlp errors and we report quality unavailable.
# This prevents silent 360p downloads when user wants HD.
_4K = (
    "bestvideo[height>=2160][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height>=2160]+bestaudio/"
    "bestvideo[height>=1440][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height>=1440]+bestaudio/"
    "bestvideo[height>=1080]+bestaudio/best"
)
_HD = (
    "bestvideo[height>=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height>=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[height>=1080]+bestaudio/"
    "bestvideo[height>=720]+bestaudio/best"
)

FMTS = {
    "4k":      {"label":"4K (2160p)",   "fmt":_4K, "merge":"mp4", "fb":"best", "pp_compat":True},
    "hd":      {"label":"HD (1080p)",   "fmt":_HD, "merge":"mp4", "fb":"best", "pp_compat":True},
    # Audio only
    "mp3":     {"label":"Audio MP3",    "fmt":"ba/b", "audio":"mp3"},
    "wav":     {"label":"Audio WAV",    "fmt":"ba/b", "audio":"wav"},
}

# -- Download item ----------------------------------------------------------
class DL:
    _id = 0
    def __init__(self, url, idx, total, referer=""):
        DL._id += 1
        self.id      = DL._id
        self.url     = url
        self.referer = referer
        self.idx     = idx
        self.total   = total
        self.badge   = type_badge(url)
        self.name    = urllib.parse.unquote(
                           Path(urllib.parse.urlparse(url).path).name or url[:50])[:80]
        self.status  = "waiting"
        self.pct     = 0.0
        self.speed_v = 0
        self.eta_v   = None
        self.size_v  = 0
        self.done_f  = ""
        self.priority = 1   # 0=high, 1=normal, 2=low
        self.start_t = 0
        self.end_t   = 0
        # UI refs
        self.row     = None
        self._lbl_icon = None
        self._lbl_name = None
        self._lbl_meta = None
        self._prog     = None

# -- History store ----------------------------------------------------------
class HistoryStore:
    def __init__(self, path=HIST_PATH):
        self.path = path
        self.data = jload(path, {"items":[]})
    def add(self, item):
        rec = {
            "name":     Path(item.done_f).name if item.done_f else item.name,
            "path":     item.done_f or "",
            "url":      item.url,
            "size":     item.size_v,
            "status":   item.status,
            "category": categorize(item.done_f or item.name),
            "ts":       now_iso(),
        }
        self.data.setdefault("items",[]).insert(0, rec)
        self.data["items"] = self.data["items"][:MAX_HISTORY]
        jsave(self.path, self.data)
        return rec
    def clear(self):
        self.data = {"items":[]}
        jsave(self.path, self.data)
    def all(self): return self.data.get("items",[])
    def filter(self, term):
        t = term.lower().strip()
        if not t: return self.all()
        return [r for r in self.all() if t in r.get("name","").lower() or t in r.get("url","").lower()]

# -- Stats store ------------------------------------------------------------
class StatsStore:
    def __init__(self, path=STATS_PATH):
        self.path = path
        self.data = jload(path, {
            "total_files":0,"total_bytes":0,"total_time":0,
            "by_category":{},"by_day":{},"max_speed":0,"sessions":0,
        })
        self.data["sessions"] = self.data.get("sessions",0) + 1
        self.save()
    def record(self, item):
        d = self.data
        d["total_files"]  = d.get("total_files",0) + 1
        d["total_bytes"]  = d.get("total_bytes",0) + (item.size_v or 0)
        dur = max(0, item.end_t - item.start_t) if item.end_t and item.start_t else 0
        d["total_time"]   = d.get("total_time",0) + dur
        cat = categorize(item.done_f or item.name)
        d.setdefault("by_category",{})
        d["by_category"][cat] = d["by_category"].get(cat,0) + 1
        import datetime
        day = datetime.date.today().isoformat()
        d.setdefault("by_day",{})
        d["by_day"][day] = d["by_day"].get(day,0) + (item.size_v or 0)
        if item.speed_v and item.speed_v > d.get("max_speed",0):
            d["max_speed"] = item.speed_v
        self.save()
    def save(self): jsave(self.path, self.data)

# -- Multi-thread file downloader -------------------------------------------
class FileDL:
    def __init__(self, url, dest, n=THREADS, prog_cb=None, log_cb=None,
                 cancel_fn=None, rate_limit=0):
        self.url    = url
        self.dest   = Path(dest)
        self.n      = n
        self.prog   = prog_cb or (lambda *a: None)
        self.log    = log_cb or print
        self.cancel = cancel_fn or (lambda: False)
        self.rate_limit = rate_limit  # bytes/sec, 0 = unlimited
        self._lock  = threading.Lock()
        self._done  = 0
        self._total = 0
        self._t0    = 0

    def _head(self):
        req = urllib.request.Request(self.url, method="HEAD",
              headers={"User-Agent":"ZHDownloader/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                total = int(r.headers.get("Content-Length",0))
                res   = "bytes" in r.headers.get("Accept-Ranges","")
                fname = ""
                cd = r.headers.get("Content-Disposition","")
                if "filename=" in cd:
                    fname = cd.split("filename=")[-1].strip().strip('"\'')
                return total, res, fname
        except Exception as e:
            self.log(f"[warn] HEAD: {e}")
            return 0, False, ""

    def _out(self, srv):
        if srv: return self.dest / srv
        n = urllib.parse.unquote(Path(urllib.parse.urlparse(self.url).path).name) or "download"
        return self.dest / n

    def _throttle(self, n):
        if self.rate_limit <= 0: return
        elapsed = time.time() - self._t0
        expected = self._done / self.rate_limit
        delay = expected - elapsed
        if delay > 0: time.sleep(min(delay, 0.5))

    def _tick(self, n):
        with self._lock:
            self._done += n
            el = time.time()-self._t0
            s  = self._done/el if el>0 else 0
            r  = (self._total-self._done)/s if s>0 and self._total else None
            p  = self._done/self._total*100 if self._total else 0
        self.prog(p, s, r)
        self._throttle(n)

    def _chunk(self, s, e, part):
        ex = part.stat().st_size if part.exists() else 0
        rs = s+ex
        if ex and rs>e:
            with self._lock: self._done += ex
            return
        h = {"User-Agent":"ZHDownloader/5.0","Range":f"bytes={rs}-{e}"}
        req = urllib.request.Request(self.url, headers=h)
        with urllib.request.urlopen(req, timeout=60) as r:
            with open(part,"ab") as f:
                while True:
                    if self.cancel(): return
                    c = r.read(65536)
                    if not c: break
                    f.write(c); self._tick(len(c))

    def _single(self, out):
        ex = out.stat().st_size if out.exists() else 0
        h  = {"User-Agent":"ZHDownloader/5.0"}
        if ex: h["Range"] = f"bytes={ex}-"
        with self._lock: self._done += ex
        req = urllib.request.Request(self.url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if not self._total:
                    self._total = int(r.headers.get("Content-Length",0))+ex
                with open(out,"ab") as f:
                    while True:
                        if self.cancel(): return
                        c = r.read(65536)
                        if not c: break
                        f.write(c); self._tick(len(c))
        except urllib.error.HTTPError as e:
            if e.code != 416: raise

    def run(self):
        self._t0 = time.time()
        self.dest.mkdir(parents=True, exist_ok=True)
        total, res, srv = self._head()
        self._total = total
        out = self._out(srv)
        self.log(f"[file] {out.name}  {sz(total)}")
        if not res or total==0 or self.n==1:
            self._single(out)
        else:
            chunk = total//self.n
            PARTS_DIR.mkdir(parents=True, exist_ok=True)
            parts = []
            with ThreadPoolExecutor(max_workers=self.n) as pool:
                futs = []
                for i in range(self.n):
                    s = i*chunk
                    e = (s+chunk-1) if i<self.n-1 else total-1
                    p = PARTS_DIR/f"{out.stem}.part{i}"
                    parts.append(p)
                    futs.append(pool.submit(self._chunk,s,e,p))
                for f in futs: f.result()
            if self.cancel():
                self.log("[pause] chunks saved for resume")
                return None
            with open(out,"wb") as dst:
                for p in parts:
                    if p.exists(): dst.write(p.read_bytes()); p.unlink()
        if self.cancel(): return None
        self.log(f"[done] {out}")
        return str(out)

# -- HTTP bridge ------------------------------------------------------------
class Bridge(BaseHTTPRequestHandler):
    app = None
    def log_message(self,*a): pass
    def _c(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
    def do_OPTIONS(self):
        self.send_response(204); self._c(); self.end_headers()
    def do_GET(self):
        if self.path=="/ping":
            self.send_response(200); self._c()
            self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"app":APP_NAME,"version":APP_VER,"ok":True}).encode())
        else:
            self.send_response(404); self._c(); self.end_headers()
    def do_POST(self):
        if self.path!="/download":
            self.send_response(404); self._c(); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length","0"))
            d = json.loads(self.rfile.read(n) or b"{}")
        except: d={}
        url     = (d.get("url")     or "").strip()
        referer = (d.get("referer") or "").strip()
        if not url:
            self.send_response(400); self._c(); self.end_headers()
            self.wfile.write(b'{"ok":false}'); return
        self.app._mq.put(("ext_url", (url, referer)))
        self.send_response(200); self._c()
        self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(b'{"ok":true}')

# -- Main App ---------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root      = root
        # Auto-detect installed browser for cookies default
        default_cookies = "chrome"
        for browser, path in [("chrome", Path.home()/"Library/Application Support/Google/Chrome"),
                              ("safari", Path.home()/"Library/Safari"),
                              ("firefox", Path.home()/"Library/Application Support/Firefox"),
                              ("edge",   Path.home()/"Library/Application Support/Microsoft Edge"),
                              ("brave",  Path.home()/"Library/Application Support/BraveSoftware/Brave-Browser")]:
            if path.exists(): default_cookies = browser; break

        self.cfg       = jload(CFG_PATH, {
            "dir":DEFAULT_DIR, "fmt":"4k", "cookies":default_cookies, "clip":True,
            "theme":"Light", "concurrent":3, "rate_kbps":0, "categorize":False,
            "completion_sound":True, "shutdown_after":False, "conflict":"rename",
        })
        # Apply theme
        self.set_theme(self.cfg.get("theme","Light"), refresh=False)
        self.state     = jload(STATE_PATH,{"queue":[]})
        self.history   = HistoryStore()
        self.stats     = StatsStore()
        self._mq       = Q.Queue()
        self._stop     = threading.Event()
        self._paused   = False
        self._workers  = []
        self._items    = []
        self._done_files = []
        self._clip_last  = ""
        self._clip_on    = tk.BooleanVar(value=self.cfg.get("clip",True))
        self._spd_history = []
        self._sched_time  = None
        self._sched_timer = None
        self._referers    = {}
        self.ff           = find_ff()
        self._row_widgets = {}   # item.id -> dict of widget refs

        root.title(f"{APP_NAME} v{APP_VER}")
        root.geometry("1100x800")
        root.minsize(900,640)
        root.configure(bg=T["BG"])
        # Center on screen
        root.update_idletasks()
        try:
            sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
            x = max(0, (sw - 1100) // 2); y = max(0, (sh - 800) // 2)
            root.geometry(f"1100x800+{x}+{y}")
        except: pass

        self._ui()
        self._poll()
        self._poll_clip()
        self._start_bridge()
        self._check_resume()
        self._setup_tray()

        # Intercept window close to minimize-to-tray (if available)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.ff:
            self.log("[warn] ffmpeg not found - HD merge/audio extract may fail\n"
                     "       Mac: brew install ffmpeg | Win: choco install ffmpeg")

    # -- theme --------------------------------------------------------------
    def set_theme(self, name, refresh=True):
        if name not in THEMES: name = "Light"
        T.update(THEMES[name])
        self.cfg["theme"] = name
        jsave(CFG_PATH, self.cfg)
        if refresh: self._apply_theme()

    def _apply_theme(self):
        """Theme switch requires restart for full restyle. ttk re-config helps minimally."""
        s = ttk.Style()
        self._config_styles(s)
        messagebox.showinfo(APP_NAME, "Theme will fully apply after restart.")

    def _config_styles(self, s):
        try: s.theme_use("clam")
        except: pass
        s.configure("TFrame",       background=T["BG"])
        s.configure("Card.TFrame",  background=T["SURF"])
        s.configure("TLabel",       background=T["BG"], foreground=T["TEXT"], font=("Helvetica",10))
        s.configure("Muted.TLabel", background=T["BG"], foreground=T["MUTED"], font=("Helvetica",9))
        s.configure("Title.TLabel", background=T["BG"], foreground=T["ACCENT"], font=("Helvetica",13,"bold"))
        s.configure("TCheckbutton", background=T["BG"], foreground=T["MUTED"], font=("Helvetica",10))
        s.map("TCheckbutton", background=[("active",T["BG"])])
        # Auto-pick button text color based on theme luminance
        btn_fg = "#ffffff" if T["BG"].startswith("#") and sum(int(T["BG"][i:i+2],16) for i in (1,3,5)) < 384 else "#ffffff"
        # Main button always white text on accent
        s.configure("Main.TButton", background=T["ACCENT"], foreground="#ffffff",
                    font=("Helvetica",11,"bold"), padding=(18,9), borderwidth=0,
                    relief="flat", anchor="center")
        s.map("Main.TButton",
              background=[("active",T["ACCENT2"]),("pressed",T["ACCENT2"]),("disabled",T["SURF2"])],
              foreground=[("active","#ffffff"),("disabled",T["MUTED"])])
        s.configure("Ghost.TButton", background=T["SURF2"], foreground=T["TEXT"],
                    font=("Helvetica",10), padding=(10,7), borderwidth=1, relief="flat")
        s.map("Ghost.TButton",
              background=[("active",T["SURF"]),("disabled",T["BG"])],
              foreground=[("active",T["TEXT"]),("disabled",T["MUTED"])])
        s.configure("Danger.TButton", background=T["RED"], foreground="#ffffff",
                    font=("Helvetica",10,"bold"), padding=(10,7), borderwidth=0, relief="flat")
        s.configure("TProgressbar", troughcolor=T["SURF2"], background=T["ACCENT"],
                    borderwidth=0, thickness=6)
        s.configure("TNotebook", background=T["BG"], borderwidth=0)
        s.configure("TNotebook.Tab", background=T["SURF"], foreground=T["MUTED"],
                    font=("Helvetica",10,"bold"), padding=(18,9), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected",T["BG"]),("active",T["SURF2"])],
              foreground=[("selected",T["ACCENT"]),("active",T["TEXT"])])
        s.configure("Treeview", background=T["SURF"], foreground=T["TEXT"],
                    fieldbackground=T["SURF"], borderwidth=0, font=("Helvetica",10))
        s.configure("Treeview.Heading", background=T["SURF2"], foreground=T["MUTED"],
                    font=("Helvetica",9,"bold"), borderwidth=0)
        s.map("Treeview", background=[("selected",T["MAROON"])], foreground=[("selected",T["TEXT"])])
        s.configure("TScale", background=T["BG"], troughcolor=T["SURF2"])

    # -- UI -----------------------------------------------------------------
    def _ui(self):
        s = ttk.Style()
        self._config_styles(s)

        # Header — slimmer
        hdr = tk.Frame(self.root, bg=T["HEADER"], height=70)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        # Subtle bottom border
        tk.Frame(self.root, bg=T["BORDER"], height=1).pack(fill="x")
        hi = tk.Frame(hdr, bg=T["HEADER"]); hi.pack(fill="both", expand=True, padx=20, pady=10)
        lp = self._r("header-logo.png")
        if lp:
            try:
                self._logo = tk.PhotoImage(file=lp)
                tk.Label(hi, image=self._logo, bg=T["HEADER"], bd=0).pack(side="left", padx=(0,10))
            except: pass
        tx = tk.Frame(hi, bg=T["HEADER"]); tx.pack(side="left")
        tk.Label(tx, text=APP_NAME, bg=T["HEADER"], fg=T["ACCENT"],
                 font=("Helvetica",15,"bold")).pack(anchor="w")
        tk.Label(tx, text=f"v{APP_VER}  ·  Licensed to ZH Motions Students",
                 bg=T["HEADER"], fg=T["MUTED"], font=("Helvetica",9)).pack(anchor="w")
        # Right side info pills
        right = tk.Frame(hi, bg=T["HEADER"]); right.pack(side="right")
        self._dot = tk.Label(right, text="● Bridge", bg=T["HEADER"], fg=T["MUTED"], font=("Helvetica",9))
        self._dot.pack(side="right", padx=(0,10))
        self._concur_lbl = tk.Label(right, text="0/0 active", bg=T["HEADER"], fg=T["MUTED"], font=("Helvetica",9))
        self._concur_lbl.pack(side="right", padx=(0,14))
        # About + Help links in header
        about = tk.Label(right, text="ⓘ About", bg=T["HEADER"], fg=T["ACCENT"],
                         font=("Helvetica",9,"underline"), cursor="hand2")
        about.pack(side="right", padx=(0,10))
        about.bind("<Button-1>", lambda e: self._show_about())

        help_lbl = tk.Label(right, text="? Help", bg=T["HEADER"], fg=T["ACCENT"],
                            font=("Helvetica",9,"underline"), cursor="hand2")
        help_lbl.pack(side="right", padx=(0,10))
        help_lbl.bind("<Button-1>", lambda e: self._show_help())

        # Top toolbar (URL + add + drop-zone + global actions)
        bar = tk.Frame(self.root, bg=T["BG"])
        bar.pack(fill="x", padx=20, pady=(14,8))
        # URL row
        url_row = tk.Frame(bar, bg=T["BG"]); url_row.pack(fill="x")
        tk.Label(url_row, text="Paste URLs:", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",10,"bold")).pack(anchor="w")
        url_inner = tk.Frame(bar, bg=T["BG"]); url_inner.pack(fill="x", pady=(4,0))
        self.url_box = tk.Text(url_inner, height=3, font=("Menlo",10),
                               bg=T["INPUT"], fg=T["TEXT"], insertbackground=T["ACCENT"],
                               relief="flat", highlightthickness=1,
                               highlightbackground=T["BORDER"], highlightcolor=T["ACCENT"],
                               padx=12, pady=10, selectbackground=T["MAROON"])
        self.url_box.pack(side="left", fill="x", expand=True)
        self.url_box.bind("<Command-v>", lambda e: self.root.after(100, self._on_paste))
        self.url_box.bind("<Control-v>", lambda e: self.root.after(100, self._on_paste))

        # Drag-drop URLs (text or files) onto url_box
        if HAS_DND:
            try:
                self.url_box.drop_target_register(DND_TEXT, DND_FILES)
                self.url_box.dnd_bind("<<Drop>>", self._on_dnd_drop)
            except Exception as e:
                pass

        # Tabs
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=20, pady=(10,0))
        self._tab_downloads()
        self._tab_history()
        self._tab_stats()
        self._tab_settings()

        # Bottom status bar
        self._build_status_bar()

    def _build_status_bar(self):
        # Top border line on status bar
        tk.Frame(self.root, bg=T["BORDER"], height=1).pack(fill="x", side="bottom")
        bottom = tk.Frame(self.root, bg=T["SURF"], height=36)
        bottom.pack(fill="x", side="bottom"); bottom.pack_propagate(False)
        left = tk.Frame(bottom, bg=T["SURF"]); left.pack(side="left", padx=14, pady=6)
        self.status_var = tk.StringVar(value="Idle — paste URLs and press Download")
        tk.Label(left, textvariable=self.status_var, bg=T["SURF"], fg=T["MUTED"],
                 font=("Helvetica",9)).pack(side="left")
        right = tk.Frame(bottom, bg=T["SURF"]); right.pack(side="right", padx=14, pady=6)
        self.spd_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.spd_var, bg=T["SURF"], fg=T["ACCENT"],
                 font=("Helvetica",10,"bold")).pack(side="right")
        # Mini graph
        self.graph = tk.Canvas(right, bg=T["SURF2"], width=120, height=20,
                               highlightthickness=0)
        self.graph.pack(side="right", padx=(0,10))

    # -- Tab: Downloads -----------------------------------------------------
    def _tab_downloads(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text=f"  ⬇  Downloads  ")
        # Options row
        opt = tk.Frame(tab, bg=T["BG"]); opt.pack(fill="x", padx=4, pady=(12,8))
        self._lbl(opt, "Format").grid(row=0,column=0,sticky="w",padx=(0,4))
        self.fmt_var = tk.StringVar()
        fk = self.cfg.get("fmt","4k")
        if fk not in FMTS: fk = "4k"
        self.fmt_var.set(f"{fk}: {FMTS[fk]['label']}")
        fm = tk.OptionMenu(opt, self.fmt_var, *[f"{k}: {v['label']}" for k,v in FMTS.items()])
        self._style_menu(fm); fm.configure(width=22)
        fm.grid(row=0,column=1,sticky="w",padx=(0,12))

        self._lbl(opt, "Mode").grid(row=0,column=2,sticky="w",padx=(0,4))
        self.mode_var = tk.StringVar(value="auto: Auto-detect")
        mm = tk.OptionMenu(opt, self.mode_var,
                           "auto: Auto-detect","video: Video/Audio","file: General File")
        self._style_menu(mm); mm.configure(width=14)
        mm.grid(row=0,column=3,sticky="w",padx=(0,12))

        self._lbl(opt, "Cookies").grid(row=0,column=4,sticky="w",padx=(0,4))
        self.ck_var = tk.StringVar(value=self.cfg.get("cookies","none"))
        cm = tk.OptionMenu(opt, self.ck_var,"none","chrome","safari","firefox","edge","brave")
        self._style_menu(cm); cm.configure(width=9)
        cm.grid(row=0,column=5,sticky="w")

        # Toggles row
        chk = tk.Frame(tab, bg=T["BG"]); chk.pack(fill="x", padx=4, pady=(0,8))
        self.sub_var   = tk.BooleanVar()
        self.thumb_var = tk.BooleanVar(value=True)
        self.pl_var    = tk.BooleanVar()
        for v,l in [(self.sub_var,"Subtitles"),(self.thumb_var,"Thumbnail"),
                    (self.pl_var,"Full Playlist"),(self._clip_on,"Watch clipboard")]:
            ttk.Checkbutton(chk, text=l, variable=v).pack(side="left", padx=(0,16))

        # Folder + scheduler row
        fld = tk.Frame(tab, bg=T["BG"]); fld.pack(fill="x", padx=4, pady=(0,8))
        self._lbl(fld, "Save to").pack(side="left", padx=(0,4))
        self.folder_var = tk.StringVar(value=self.cfg.get("dir",DEFAULT_DIR))
        self._entry(fld, self.folder_var).pack(side="left", fill="x", expand=True, padx=(0,6))
        self._ghost_btn(fld, "Browse", self._pick_folder).pack(side="left", padx=(0,4))
        self._ghost_btn(fld, "Open",   self._open_folder).pack(side="left")

        # Scheduler
        sched = tk.Frame(tab, bg=T["BG"]); sched.pack(fill="x", padx=4, pady=(0,8))
        self._lbl(sched, "Schedule").pack(side="left", padx=(0,4))
        self._sched_var = tk.StringVar(value="Now")
        sm = tk.OptionMenu(sched, self._sched_var,
                           "Now","In 30 minutes","In 1 hour","In 2 hours",
                           "In 6 hours","In 12 hours","Tonight 11 PM",
                           "Tomorrow 6 AM","Tomorrow 9 AM")
        self._style_menu(sm); sm.configure(width=16); sm.pack(side="left")
        self._sched_lbl = tk.Label(sched, text="", bg=T["BG"], fg=T["ACCENT"],
                                   font=("Helvetica",10,"bold"))
        self._sched_lbl.pack(side="left", padx=(12,0))

        # Action buttons row
        btns = tk.Frame(tab, bg=T["BG"]); btns.pack(fill="x", padx=4, pady=(4,10))
        self.btn_dl     = ttk.Button(btns, text="↓ Download",  style="Main.TButton", command=self._start)
        self.btn_pause  = ttk.Button(btns, text="❚❚ Pause",    style="Ghost.TButton", command=self._do_pause,  state="disabled")
        self.btn_cancel = ttk.Button(btns, text="✕ Cancel",    style="Ghost.TButton", command=self._do_cancel, state="disabled")
        self.btn_dl.pack(side="left", padx=(0,8))
        self.btn_pause.pack(side="left", padx=(0,6))
        self.btn_cancel.pack(side="left")
        ttk.Button(btns, text="Grab from page", style="Ghost.TButton",
                   command=self._site_grab_dialog).pack(side="left", padx=(14,0))
        self._ghost_btn(btns, "Clear Log",   self._clear_log).pack(side="right")
        self._ghost_btn(btns, "Clear Queue", self._clear_queue).pack(side="right", padx=(0,6))

        # Resume banner (initially hidden)
        self.res_frame = tk.Frame(tab, bg="#152a15")
        self.res_lbl   = tk.Label(self.res_frame, text="", bg="#152a15", fg=T["GREEN"],
                                  font=("Helvetica",11,"bold"), padx=14, pady=8)
        self.res_lbl.pack(side="left")
        rb = tk.Frame(self.res_frame, bg="#152a15"); rb.pack(side="right", padx=8)
        ttk.Button(rb, text="Resume", style="Main.TButton", command=self._do_resume).pack(side="left", padx=(0,6))
        ttk.Button(rb, text="Discard",  style="Ghost.TButton", command=self._discard).pack(side="left")

        # Queue area (scrollable card list)
        sec = tk.Frame(tab, bg=T["BG"]); sec.pack(fill="x", padx=4, pady=(2,4))
        tk.Label(sec, text="QUEUE", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",9,"bold")).pack(side="left")
        tk.Frame(sec, bg=T["BORDER"], height=1).pack(side="left", fill="x", expand=True, padx=(8,0))

        body = tk.Frame(tab, bg=T["BG"])
        body.pack(fill="both", expand=True, padx=4, pady=(4,0))
        canvas = tk.Canvas(body, bg=T["BG"], highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        self.q_frame = tk.Frame(canvas, bg=T["BG"])
        self._q_win = canvas.create_window((0,0), window=self.q_frame, anchor="nw")
        self.q_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._q_win, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._empty_lbl = tk.Label(self.q_frame,
            text="No downloads yet. Paste URLs and press Download.",
            bg=T["BG"], fg=T["MUTED"], font=("Helvetica",10))
        self._empty_lbl.pack(pady=24)

        # Log section
        log_sec = tk.Frame(tab, bg=T["BG"]); log_sec.pack(fill="x", padx=4, pady=(8,4))
        tk.Label(log_sec, text="LOG", bg=T["BG"], fg=T["MUTED"], font=("Helvetica",9,"bold")).pack(side="left")
        tk.Frame(log_sec, bg=T["BORDER"], height=1).pack(side="left", fill="x", expand=True, padx=(8,0))
        lf = tk.Frame(tab, bg=T["BG"]); lf.pack(fill="x", padx=4, pady=(2,10))
        self.log_txt = tk.Text(lf, height=6, font=("Menlo",9),
                               bg=T["LOG_BG"], fg=T["LOG_FG"], relief="flat",
                               padx=10, pady=8, wrap="word", state="disabled")
        self.log_txt.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(lf, command=self.log_txt.yview).pack(side="right", fill="y")
        for tag,col in [("ok",T["GREEN"]),("warn",T["YELLOW"]),("err",T["RED"]),
                        ("info",T["ACCENT"]),("dim",T["LOG_FG"])]:
            self.log_txt.tag_configure(tag, foreground=col)

    # -- Tab: History -------------------------------------------------------
    def _tab_history(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="  📁  History  ")
        top = tk.Frame(tab, bg=T["BG"]); top.pack(fill="x", padx=4, pady=10)
        tk.Label(top, text="Past Downloads", bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica",13,"bold")).pack(side="left")
        self.hist_search = tk.StringVar()
        e = self._entry(top, self.hist_search); e.pack(side="right", padx=(8,0))
        e.configure(width=24)
        tk.Label(top, text="Search:", bg=T["BG"], fg=T["MUTED"]).pack(side="right")
        ttk.Button(top, text="Clear History", style="Danger.TButton",
                   command=self._hist_clear).pack(side="right", padx=(8,12))
        ttk.Button(top, text="Refresh", style="Ghost.TButton",
                   command=self._hist_refresh).pack(side="right", padx=(8,0))
        self.hist_search.trace_add("write", lambda *a: self._hist_refresh())

        cols = ("name","cat","size","when","url")
        self.hist_tree = ttk.Treeview(tab, columns=cols, show="headings", height=18)
        for c,t,w in [("name","Name",340),("cat","Category",90),("size","Size",90),
                      ("when","When",140),("url","URL",260)]:
            self.hist_tree.heading(c, text=t)
            self.hist_tree.column(c, width=w, anchor="w")
        self.hist_tree.pack(fill="both", expand=True, padx=4)
        hsb = ttk.Scrollbar(tab, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=hsb.set)
        self.hist_tree.bind("<Double-1>", self._hist_open)
        self.hist_tree.bind("<Button-2>", self._hist_menu)   # mac right-click
        self.hist_tree.bind("<Button-3>", self._hist_menu)
        self._hist_refresh()

        # Bottom actions
        bot = tk.Frame(tab, bg=T["BG"]); bot.pack(fill="x", padx=4, pady=(6,10))
        ttk.Button(bot, text="Open File",     style="Ghost.TButton",
                   command=lambda: self._hist_open(None)).pack(side="left", padx=(0,6))
        ttk.Button(bot, text="Reveal in Folder", style="Ghost.TButton",
                   command=self._hist_reveal).pack(side="left", padx=(0,6))
        ttk.Button(bot, text="Re-download",   style="Ghost.TButton",
                   command=self._hist_redownload).pack(side="left", padx=(0,6))
        ttk.Button(bot, text="Remove",        style="Danger.TButton",
                   command=self._hist_remove).pack(side="left")

    def _hist_refresh(self):
        for i in self.hist_tree.get_children(): self.hist_tree.delete(i)
        items = self.history.filter(self.hist_search.get())
        for r in items:
            self.hist_tree.insert("","end", values=(
                r.get("name",""),
                r.get("category","Other"),
                sz(r.get("size",0)) if r.get("size") else "-",
                r.get("ts","").replace("T"," "),
                r.get("url","")[:120],
            ), tags=(r.get("path",""),))

    def _hist_sel_path(self):
        sel = self.hist_tree.selection()
        if not sel: return None
        tags = self.hist_tree.item(sel[0],"tags")
        return tags[0] if tags else None

    def _hist_open(self, _e):
        p = self._hist_sel_path()
        if not p or not Path(p).exists():
            messagebox.showinfo(APP_NAME,"File not found on disk."); return
        if   platform.system()=="Darwin":  subprocess.run(["open", p])
        elif platform.system()=="Windows": os.startfile(p)
        else:                              subprocess.run(["xdg-open", p])

    def _hist_reveal(self):
        p = self._hist_sel_path()
        if not p: return
        d = str(Path(p).parent)
        if   platform.system()=="Darwin":  subprocess.run(["open","-R",p] if Path(p).exists() else ["open",d])
        elif platform.system()=="Windows": subprocess.run(["explorer","/select,", p])
        else:                              subprocess.run(["xdg-open", d])

    def _hist_redownload(self):
        sel = self.hist_tree.selection()
        if not sel: return
        vals = self.hist_tree.item(sel[0],"values")
        url = vals[4] if len(vals)>4 else ""
        if url:
            self.url_box.delete("1.0","end")
            self.url_box.insert("1.0", url)
            self.nb.select(0)
            self.log(f"[history] queued: {url[:80]}")

    def _hist_remove(self):
        sel = self.hist_tree.selection()
        if not sel: return
        for s in sel:
            vals = self.hist_tree.item(s,"values")
            url  = vals[4] if len(vals)>4 else ""
            self.history.data["items"] = [
                r for r in self.history.all() if r.get("url","") != url
            ]
        self.history.save = lambda: jsave(self.history.path, self.history.data)
        jsave(self.history.path, self.history.data)
        self._hist_refresh()

    def _hist_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg=T["SURF"], fg=T["TEXT"],
                    activebackground=T["MAROON"], activeforeground=T["ACCENT"])
        m.add_command(label="Open file",        command=lambda: self._hist_open(None))
        m.add_command(label="Reveal in folder", command=self._hist_reveal)
        m.add_command(label="Re-download",      command=self._hist_redownload)
        m.add_separator()
        m.add_command(label="Remove from history", command=self._hist_remove)
        try: m.tk_popup(e.x_root, e.y_root)
        finally: m.grab_release()

    def _hist_clear(self):
        if messagebox.askyesno(APP_NAME, "Clear all history? This cannot be undone."):
            self.history.clear()
            self._hist_refresh()

    # -- Tab: Stats ---------------------------------------------------------
    def _tab_stats(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="  📊  Stats  ")
        self.stats_tab = tab
        self._build_stats_view()

    def _build_stats_view(self):
        for w in self.stats_tab.winfo_children(): w.destroy()
        d = self.stats.data

        head = tk.Frame(self.stats_tab, bg=T["BG"]); head.pack(fill="x", padx=4, pady=10)
        tk.Label(head, text="Lifetime Statistics", bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica",13,"bold")).pack(side="left")
        ttk.Button(head, text="Refresh", style="Ghost.TButton",
                   command=self._build_stats_view).pack(side="right")
        ttk.Button(head, text="Reset Stats", style="Danger.TButton",
                   command=self._reset_stats).pack(side="right", padx=(0,6))

        # Big numbers
        nums = tk.Frame(self.stats_tab, bg=T["BG"]); nums.pack(fill="x", padx=4, pady=10)
        cards = [
            ("Files",        f"{d.get('total_files',0):,}",      T["ACCENT"]),
            ("Total Data",   sz(d.get('total_bytes',0)),          T["GREEN"]),
            ("Total Time",   eta(d.get('total_time',0)),          T["BLUE"]),
            ("Peak Speed",   spd(d.get('max_speed',0)),           T["YELLOW"]),
            ("Sessions",     f"{d.get('sessions',0):,}",          T["PURPLE"]),
        ]
        for label, val, col in cards:
            c = tk.Frame(nums, bg=T["SURF"], padx=14, pady=12)
            c.pack(side="left", padx=4, fill="both", expand=True)
            tk.Label(c, text=val,  bg=T["SURF"], fg=col, font=("Helvetica",18,"bold")).pack(anchor="w")
            tk.Label(c, text=label, bg=T["SURF"], fg=T["MUTED"], font=("Helvetica",9)).pack(anchor="w")

        # By category bar
        cat_frame = tk.Frame(self.stats_tab, bg=T["BG"]); cat_frame.pack(fill="x", padx=4, pady=10)
        tk.Label(cat_frame, text="Files by Category", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",10,"bold")).pack(anchor="w", pady=(0,6))
        cats = d.get("by_category",{}) or {}
        total = sum(cats.values()) or 1
        for cat, n in sorted(cats.items(), key=lambda x:-x[1]):
            row = tk.Frame(cat_frame, bg=T["BG"]); row.pack(fill="x", pady=2)
            tk.Label(row, text=cat, bg=T["BG"], fg=T["TEXT"], width=12, anchor="w",
                     font=("Helvetica",10)).pack(side="left")
            bar_outer = tk.Frame(row, bg=T["SURF2"], height=16); bar_outer.pack(side="left", fill="x", expand=True, padx=8)
            frac = n/total
            tk.Frame(bar_outer, bg=T["ACCENT"], height=16, width=int(400*frac)).place(x=0,y=0)
            tk.Label(row, text=f"{n}", bg=T["BG"], fg=T["MUTED"], width=8, anchor="e",
                     font=("Helvetica",10)).pack(side="right")

        # By day (last 14)
        day_frame = tk.Frame(self.stats_tab, bg=T["BG"]); day_frame.pack(fill="x", padx=4, pady=10)
        tk.Label(day_frame, text="Last 14 Days (Data)", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",10,"bold")).pack(anchor="w", pady=(0,6))
        import datetime as _dt
        today = _dt.date.today()
        days = [(today - _dt.timedelta(days=i)).isoformat() for i in range(13,-1,-1)]
        days_data = [(day, d.get("by_day",{}).get(day,0)) for day in days]
        mx = max((b for _,b in days_data), default=1) or 1
        canvas = tk.Canvas(day_frame, bg=T["SURF"], height=140, highlightthickness=0)
        canvas.pack(fill="x")
        canvas.update_idletasks()
        cw = canvas.winfo_width() or 800
        bw = cw / len(days_data) - 4
        for i,(day,b) in enumerate(days_data):
            x = i*(bw+4) + 2
            h = (b/mx)*110 if b else 2
            canvas.create_rectangle(x, 130-h, x+bw, 130, fill=T["ACCENT"], outline="")
            canvas.create_text(x+bw/2, 138, text=day[5:], fill=T["MUTED"], font=("Helvetica",7))

    def _reset_stats(self):
        if not messagebox.askyesno(APP_NAME,"Reset all lifetime statistics?"): return
        for k in ("total_files","total_bytes","total_time","max_speed"):
            self.stats.data[k] = 0
        self.stats.data["by_category"] = {}
        self.stats.data["by_day"] = {}
        self.stats.save()
        self._build_stats_view()

    # -- Tab: Settings ------------------------------------------------------
    def _tab_settings(self):
        tab = ttk.Frame(self.nb); self.nb.add(tab, text="  ⚙  Settings  ")
        head = tk.Frame(tab, bg=T["BG"]); head.pack(fill="x", padx=14, pady=(14,10))
        tk.Label(head, text="Settings", bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica",15,"bold")).pack(side="left")
        tk.Label(head, text="(saved automatically)", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",9)).pack(side="left", padx=(8,0), pady=(4,0))

        # Two-column grid layout for clean alignment
        body = tk.Frame(tab, bg=T["BG"]); body.pack(fill="both", expand=True, padx=14)
        body.columnconfigure(0, weight=0, minsize=280)
        body.columnconfigure(1, weight=1)

        # Theme dropdown
        self._add_setting(body, 0, "Theme",
            lambda r: tk.OptionMenu(r, tk.StringVar(value=self.cfg.get("theme","Light")),
                                    *THEMES.keys(), command=self._on_theme))

        # Concurrent downloads
        self.concur_var = tk.IntVar(value=self.cfg.get("concurrent",2))
        self._add_setting(body, 1, "Concurrent downloads (1-5)",
            lambda r: tk.Scale(r, from_=1, to=MAX_CONCURRENT, orient="horizontal",
                               variable=self.concur_var, length=200,
                               bg=T["BG"], fg=T["TEXT"], troughcolor=T["SURF2"],
                               highlightthickness=0, activebackground=T["ACCENT"],
                               command=lambda v: self._save_setting("concurrent", int(float(v)))))

        # Speed limit
        self.rate_var = tk.IntVar(value=self.cfg.get("rate_kbps",0))
        self._add_setting(body, 2, "Speed limit (KB/s — 0 = unlimited)",
            lambda r: tk.Scale(r, from_=0, to=50000, resolution=100, orient="horizontal",
                               variable=self.rate_var, length=300,
                               bg=T["BG"], fg=T["TEXT"], troughcolor=T["SURF2"],
                               highlightthickness=0, activebackground=T["ACCENT"],
                               command=lambda v: self._save_setting("rate_kbps", int(float(v)))))

        # Auto-categorize
        self.cat_var = tk.BooleanVar(value=self.cfg.get("categorize", False))
        self._add_setting(body, 3, "Auto-organize into Video / Audio / Documents folders",
            lambda r: ttk.Checkbutton(r, variable=self.cat_var,
                command=lambda: self._save_setting("categorize", self.cat_var.get())))

        # Completion sound
        self.snd_var = tk.BooleanVar(value=self.cfg.get("completion_sound", True))
        self._add_setting(body, 4, "Play sound on completion",
            lambda r: ttk.Checkbutton(r, variable=self.snd_var,
                command=lambda: self._save_setting("completion_sound", self.snd_var.get())))

        # Shutdown after
        self.shut_var = tk.BooleanVar(value=self.cfg.get("shutdown_after", False))
        self._add_setting(body, 5, "Shut down computer after all downloads complete",
            lambda r: ttk.Checkbutton(r, variable=self.shut_var,
                command=lambda: self._save_setting("shutdown_after", self.shut_var.get())))

        # Conflict resolution
        self.conf_var = tk.StringVar(value=self.cfg.get("conflict","rename"))
        self._add_setting(body, 6, "When file exists",
            lambda r: tk.OptionMenu(r, self.conf_var, "rename","overwrite","skip","ask",
                                    command=lambda v: self._save_setting("conflict", v)))

        # Footer
        ftr = tk.Frame(tab, bg=T["BG"]); ftr.pack(fill="x", padx=14, pady=(18,14))
        tk.Frame(ftr, bg=T["BORDER"], height=1).pack(fill="x", pady=(0,10))
        tk.Label(ftr, text=f"Config file: {CFG_PATH}", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",9)).pack(anchor="w")
        ttk.Button(ftr, text="Open config folder", style="Ghost.TButton",
                   command=lambda: subprocess.run(["open" if platform.system()=="Darwin"
                                                   else "xdg-open", str(CFG_PATH.parent)])
                   ).pack(anchor="w", pady=(6,0))

    def _add_setting(self, parent, row, label, widget_factory):
        """Place label in col 0, widget (built via factory) in col 1 of grid row."""
        tk.Label(parent, text=label, bg=T["BG"], fg=T["TEXT"], font=("Helvetica",10),
                 anchor="w").grid(row=row, column=0, sticky="w", pady=10, padx=(0,16))
        cell = tk.Frame(parent, bg=T["BG"])
        cell.grid(row=row, column=1, sticky="w", pady=10)
        widget = widget_factory(cell)
        widget.pack(side="left", anchor="w")
        if isinstance(widget, tk.OptionMenu):
            self._style_menu(widget); widget.configure(width=14)
        return widget

    def _save_setting(self, key, val):
        self.cfg[key] = val
        jsave(CFG_PATH, self.cfg)

    def _on_theme(self, name):
        self.set_theme(name, refresh=True)

    # -- res ----------------------------------------------------------------
    def _r(self, n):
        r = res_path()
        for p in [r/"assets"/n, r/n, Path(__file__).parent/"assets"/n]:
            if p.exists(): return str(p)

    # -- UI helpers ---------------------------------------------------------
    def _lbl(self, p, t):
        return tk.Label(p, text=t, bg=T["BG"], fg=T["MUTED"], font=("Helvetica",10,"bold"))

    def _entry(self, p, var):
        return tk.Entry(p, textvariable=var, bg=T["SURF"], fg=T["TEXT"],
                        insertbackground=T["ACCENT"], relief="flat",
                        highlightthickness=1, highlightbackground=T["BORDER"],
                        highlightcolor=T["ACCENT"], font=("Helvetica",10))

    def _ghost_btn(self, p, t, cmd):
        return ttk.Button(p, text=t, style="Ghost.TButton", command=cmd)

    def _style_menu(self, m):
        m.configure(bg=T["SURF2"], fg=T["TEXT"], activebackground=T["MAROON"],
                    activeforeground=T["ACCENT"], highlightthickness=0,
                    font=("Helvetica",10), relief="flat", bd=0, anchor="w")
        m["menu"].configure(bg=T["SURF2"], fg=T["TEXT"], activebackground=T["MAROON"],
                            activeforeground=T["ACCENT"], font=("Helvetica",10))

    # -- folder -------------------------------------------------------------
    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.folder_var.get())
        if d: self.folder_var.set(d)

    def _open_folder(self):
        p = self.folder_var.get(); Path(p).mkdir(parents=True, exist_ok=True)
        if   platform.system()=="Darwin":  subprocess.run(["open",p])
        elif platform.system()=="Windows": os.startfile(p)
        else:                              subprocess.run(["xdg-open",p])

    # -- log ----------------------------------------------------------------
    def log(self, msg, tag=None):
        if tag is None:
            ml = msg.lower()
            if any(k in ml for k in ("[done]","saved","merged","complete","finished","✓")): tag="ok"
            elif any(k in ml for k in ("[warn]","warning")): tag="warn"
            elif any(k in ml for k in ("[error]","failed","error","✗")): tag="err"
            elif any(k in ml for k in ("[bridge]","[file]","[info]","[resume]","[pause]","[cancel]","[history]","[schedule]","[grab]")): tag="info"
            else: tag="dim"
        self._mq.put(("log",(msg,tag)))

    def _clear_log(self):
        self.log_txt.configure(state="normal")
        self.log_txt.delete("1.0","end")
        self.log_txt.configure(state="disabled")

    def _clear_queue(self):
        if self._is_running():
            messagebox.showwarning(APP_NAME,"Stop current download first."); return
        for w in self.q_frame.winfo_children(): w.destroy()
        self._row_widgets.clear()
        self._empty_lbl = tk.Label(self.q_frame,
            text="No downloads yet. Paste URLs and press Download.",
            bg=T["BG"], fg=T["MUTED"], font=("Helvetica",10))
        self._empty_lbl.pack(pady=24)
        self._items = []
        self.url_box.delete("1.0","end")

    # -- queue cards --------------------------------------------------------
    def _build_rows(self, items):
        for w in self.q_frame.winfo_children(): w.destroy()
        self._row_widgets.clear()
        if not items:
            self._empty_lbl = tk.Label(self.q_frame,
                text="No downloads yet.", bg=T["BG"], fg=T["MUTED"],
                font=("Helvetica",10))
            self._empty_lbl.pack(pady=24); return
        for item in items: self._build_card(item)

    def _build_card(self, item):
        card = tk.Frame(self.q_frame, bg=T["SURF"], highlightthickness=1,
                        highlightbackground=T["BORDER"])
        card.pack(fill="x", pady=3, ipady=8, ipadx=10)
        inner = tk.Frame(card, bg=T["SURF"]); inner.pack(fill="x")

        # Left: status icon
        ico = tk.Label(inner, text="⏳", bg=T["SURF"], fg=T["MUTED"],
                       font=("Helvetica",16), width=2)
        ico.grid(row=0, column=0, rowspan=2, padx=(6,6), pady=4)

        # Thumbnail placeholder (PIL only)
        thumb = None
        if HAS_PIL:
            thumb = tk.Label(inner, bg=T["SURF2"], width=8, height=3,
                             text="", relief="flat")
            thumb.grid(row=0, column=1, rowspan=2, padx=(0,10), pady=2)
            # async fetch thumbnail
            threading.Thread(target=self._fetch_thumb,
                             args=(item, thumb), daemon=True).start()
            mid_col = 2
        else:
            mid_col = 1

        # Middle: badge + name + meta + progress
        mid = tk.Frame(inner, bg=T["SURF"])
        mid.grid(row=0, column=mid_col, sticky="ew", pady=2)
        inner.columnconfigure(mid_col, weight=1)

        cat = categorize(item.name)
        badge = tk.Label(mid, text=f" {item.badge} ", bg=T["MAROON"], fg=T["ACCENT"],
                         font=("Helvetica",8,"bold"), padx=4, pady=1)
        badge.pack(side="left", padx=(0,6))
        cat_badge = tk.Label(mid, text=f" {cat} ", bg=T["SURF2"], fg=T["MUTED"],
                             font=("Helvetica",8), padx=4, pady=1)
        cat_badge.pack(side="left", padx=(0,8))

        short = item.name if len(item.name)<=70 else item.name[:67]+"..."
        name = tk.Label(mid, text=f"[{item.idx}/{item.total}] {short}",
                        bg=T["SURF"], fg=T["TEXT"], font=("Helvetica",10,"bold"),
                        anchor="w")
        name.pack(side="left", fill="x", expand=True)

        meta = tk.Label(inner, text="Waiting...", bg=T["SURF"], fg=T["MUTED"],
                        font=("Helvetica",9), anchor="w")
        meta.grid(row=1, column=mid_col, sticky="ew", pady=(2,4))

        prog = ttk.Progressbar(inner, mode="determinate", maximum=100, length=220)
        prog.grid(row=0, column=mid_col+1, rowspan=2, padx=(8,10), sticky="e")
        prog["value"] = item.pct

        # Right: per-item action menu
        act = tk.Frame(inner, bg=T["SURF"])
        act.grid(row=0, column=mid_col+2, rowspan=2, padx=(0,6))
        ttk.Button(act, text="✕", style="Ghost.TButton",
                   command=lambda i=item: self._remove_item(i),
                   width=2).pack()

        self._row_widgets[item.id] = {
            "card":card,"icon":ico,"name":name,"meta":meta,"prog":prog,"thumb":thumb,
        }
        item.row = card
        item._lbl_icon = ico; item._lbl_name = name; item._lbl_meta = meta; item._prog = prog

    def _fetch_thumb(self, item, label):
        """Async fetch + display thumbnail for queue card. PIL only."""
        if not HAS_PIL: return
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        # Cache key
        import hashlib
        key = hashlib.md5(item.url.encode()).hexdigest()[:16]
        cache = THUMBS_DIR / f"{key}.png"
        try:
            if not cache.exists():
                # Try yt-dlp extract for thumbnail URL
                thumb_url = None
                try:
                    opts = {"quiet":True,"no_warnings":True,"skip_download":True,
                            "extract_flat":True,"socket_timeout":10}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(item.url, download=False)
                    if info:
                        thumb_url = info.get("thumbnail") or (
                            (info.get("thumbnails") or [{}])[-1].get("url"))
                except Exception:
                    pass
                # Fallback: direct image URL?
                if not thumb_url:
                    u = item.url.lower()
                    if any(u.endswith(e) for e in (".jpg",".jpeg",".png",".webp",".gif")):
                        thumb_url = item.url
                if not thumb_url: return
                # Download thumbnail
                req = urllib.request.Request(thumb_url, headers={
                    "User-Agent":"Mozilla/5.0 ZHDownloader"
                })
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = r.read()
                cache.write_bytes(data)
            # Load + resize
            img = Image.open(cache).convert("RGB")
            img.thumbnail((96, 54), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            # Apply on main thread
            def apply():
                if not label.winfo_exists(): return
                label.configure(image=tk_img, width=96, height=54, text="")
                label.image = tk_img  # keep ref
            self.root.after(0, apply)
        except Exception:
            pass

    def _remove_item(self, item):
        if item.status == "downloading":
            messagebox.showwarning(APP_NAME, "Cannot remove active download. Cancel first."); return
        self._items = [i for i in self._items if i.id != item.id]
        w = self._row_widgets.pop(item.id, None)
        if w and w["card"].winfo_exists(): w["card"].destroy()

    def _update_row(self, item):
        if not item.row or not item.row.winfo_exists(): return
        icons = {
            "waiting":     ("⏳", T["MUTED"]),
            "downloading": ("▼",  T["ACCENT"]),
            "done":        ("✓",  T["GREEN"]),
            "error":       ("✗",  T["RED"]),
            "paused":      ("❚❚", T["YELLOW"]),
            "cancelled":   ("—",  T["MUTED"]),
        }
        icon, col = icons.get(item.status, ("⏳", T["MUTED"]))
        item._lbl_icon.configure(text=icon, fg=col)
        item._prog["value"] = item.pct
        parts = []
        if item.size_v:  parts.append(sz(item.size_v))
        if item.speed_v: parts.append(spd(item.speed_v))
        if item.eta_v is not None: parts.append(f"ETA {eta(item.eta_v)}")
        if item.status=="done" and item.done_f:
            parts = [f"✓ {Path(item.done_f).name}"]
        item._lbl_meta.configure(text="  ·  ".join(parts) if parts else item.status.capitalize())

    # -- speed graph --------------------------------------------------------
    def _draw_graph(self):
        g = self.graph; g.delete("all")
        w,h = g.winfo_width(), g.winfo_height()
        if not self._spd_history or w<10: return
        vals = [v for _,v in self._spd_history[-40:]]
        mx   = max(vals) or 1
        pts  = []
        for i,v in enumerate(vals):
            x = int(i/(len(vals)-1)*w) if len(vals)>1 else w//2
            y = int(h - (v/mx)*(h-2) - 1)
            pts.extend([x,y])
        if len(pts)>=4:
            g.create_line(pts, fill=T["ACCENT"], width=1.5, smooth=True)

    # -- bridge -------------------------------------------------------------
    def _start_bridge(self):
        Bridge.app = self
        try:
            srv = ThreadingHTTPServer(("127.0.0.1",BRIDGE_PORT), Bridge)
        except OSError as e:
            self.log(f"[warn] bridge unavailable ({e})"); return
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.log(f"[bridge] http://127.0.0.1:{BRIDGE_PORT}")
        self._mq.put(("bridge_ok",None))

    # -- clipboard ----------------------------------------------------------
    CLIP_HOSTS = VH+("drive.google.com","dropbox.com","mega.nz","mediafire.com","wetransfer.com")

    def _looks_dl(self, s):
        if not s or not URL_RE.match(s.strip()): return False
        u = s.lower()
        return any(h in u for h in self.CLIP_HOSTS) or any(u.endswith(e) for e in VE+FE)

    def _poll_clip(self):
        if self._clip_on.get():
            try: clip = self.root.clipboard_get().strip()
            except: clip = ""
            if clip and clip!=self._clip_last and self._looks_dl(clip):
                self._clip_last = clip
                cur = self.url_box.get("1.0","end").strip()
                if clip not in cur:
                    self.url_box.delete("1.0","end")
                    self.url_box.insert("1.0",(cur+"\n"+clip).strip() if cur else clip)
                    self._mq.put(("status",f"📋 {clip[:70]}"))
                    try: self.root.bell()
                    except: pass
            elif clip: self._clip_last = clip
        self.root.after(1200, self._poll_clip)

    def _on_paste(self):
        try: clip = self.root.clipboard_get().strip()
        except: return

    def _on_dnd_drop(self, event):
        """Handle dragged URLs or file paths dropped on URL box."""
        raw = event.data or ""
        # TkinterDnD wraps paths with braces if spaces present; strip
        items = []
        cur = ""
        in_brace = False
        for ch in raw:
            if ch == "{": in_brace = True; continue
            if ch == "}":
                in_brace = False
                if cur: items.append(cur); cur = ""
                continue
            if ch == " " and not in_brace:
                if cur: items.append(cur); cur = ""
                continue
            cur += ch
        if cur: items.append(cur)
        # Convert local file paths to file:// URLs OR strip and keep as-is for http URLs
        urls = []
        for it in items:
            it = it.strip()
            if not it: continue
            if URL_RE.match(it):
                urls.append(it)
            elif Path(it).exists():
                self.log(f"[drop] local file ignored: {it}")
        if not urls:
            self.log("[drop] no valid URLs in drop")
            return "break"
        cur_txt = self.url_box.get("1.0","end").strip()
        merged = (cur_txt + "\n" + "\n".join(urls)).strip() if cur_txt else "\n".join(urls)
        self.url_box.delete("1.0","end")
        self.url_box.insert("1.0", merged)
        self.log(f"[drop] added {len(urls)} URL(s)")
        return "break"

    # -- queue poll ---------------------------------------------------------
    def _poll(self):
        try:
            while True:
                kind,payload = self._mq.get_nowait()
                if kind=="log":
                    msg,tag = payload
                    self.log_txt.configure(state="normal")
                    self.log_txt.insert("end", msg+("\n" if not msg.endswith("\n") else ""), tag)
                    self.log_txt.see("end")
                    self.log_txt.configure(state="disabled")
                elif kind=="status":
                    self.status_var.set(payload)
                elif kind=="prog":
                    pass  # per-item via item_up
                elif kind=="spd":
                    bps = payload
                    self.spd_var.set(spd(bps) if bps else "")
                    self._spd_history.append((time.time(),bps))
                    if len(self._spd_history)>120: self._spd_history=self._spd_history[-120:]
                    self._draw_graph()
                elif kind=="item_up":
                    self._update_row(payload)
                elif kind=="concur":
                    active, total = payload
                    self._concur_lbl.configure(text=f"{active}/{total} active")
                elif kind=="done":
                    self._on_done()
                elif kind=="bridge_ok":
                    self._dot.configure(fg=T["GREEN"], text="● Bridge")
                elif kind=="ext_url":
                    self._recv_ext(payload)
                elif kind=="hist_add":
                    self.history.add(payload)
                    if hasattr(self,"hist_tree"): self._hist_refresh()
                elif kind=="stats_add":
                    self.stats.record(payload)
        except Q.Empty: pass
        self.root.after(80, self._poll)

    def _recv_ext(self, payload):
        url, referer = payload if isinstance(payload, tuple) else (payload, "")
        if referer: self._referers[url] = referer
        try: self.root.deiconify(); self.root.lift()
        except: pass
        self.log(f"[bridge] {url[:80]}")
        if self._is_running():
            cur = self.url_box.get("1.0","end").strip()
            if url not in cur:
                self.url_box.delete("1.0","end")
                self.url_box.insert("1.0",(cur+"\n"+url).strip() if cur else url)
                self.log("[bridge] Added to queue")
        else:
            self.url_box.delete("1.0","end")
            self.url_box.insert("1.0", url)
            self.root.update_idletasks()
            try: self.root.bell()
            except: pass
            self._start()

    # -- resume -------------------------------------------------------------
    def _check_resume(self):
        q = self.state.get("queue",[])
        if q:
            self.res_lbl.configure(
                text=f"⏸  {len(q)} download{'s' if len(q)>1 else ''} paused from last session")
            self.res_frame.pack(fill="x", padx=4, pady=(0,8))

    def _do_resume(self):
        q = self.state.get("queue",[])
        if not q: return
        urls = [i["url"] for i in q]
        self.folder_var.set(q[0].get("dir",DEFAULT_DIR))
        fk = q[0].get("fmt","4k")
        if fk not in FMTS: fk = "4k"
        self.fmt_var.set(f"{fk}: {FMTS[fk]['label']}")
        self.url_box.delete("1.0","end")
        self.url_box.insert("1.0","\n".join(urls))
        self.log(f"[resume] {len(urls)} URL(s)")
        self.res_frame.pack_forget()
        self._start()

    def _discard(self):
        self.state["queue"]=[]; jsave(STATE_PATH,self.state)
        self.res_frame.pack_forget()
        self.log("[resume] queue discarded")

    # -- start --------------------------------------------------------------
    def _is_running(self):
        return any(t.is_alive() for t in self._workers) if self._workers else False

    # -- Scheduler ----------------------------------------------------------
    def _get_sched_delay(self):
        import datetime
        v = self._sched_var.get()
        now = datetime.datetime.now()
        if v == "Now": return None
        elif v == "In 30 minutes": return 30*60
        elif v == "In 1 hour":    return 60*60
        elif v == "In 2 hours":   return 2*60*60
        elif v == "In 6 hours":   return 6*60*60
        elif v == "In 12 hours":  return 12*60*60
        elif v == "Tonight 11 PM":
            t = now.replace(hour=23, minute=0, second=0, microsecond=0)
            if t <= now: t += datetime.timedelta(days=1)
            return (t - now).total_seconds()
        elif v == "Tomorrow 6 AM":
            t = (now + datetime.timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
            return (t - now).total_seconds()
        elif v == "Tomorrow 9 AM":
            t = (now + datetime.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            return (t - now).total_seconds()
        return None

    def _fmt_countdown(self, secs):
        h,r = divmod(int(secs),3600); m,s = divmod(r,60)
        if h: return f"{h}h {m}m {s}s"
        if m: return f"{m}m {s}s"
        return f"{s}s"

    def _countdown_tick(self, target_time, urls, out, fk):
        import datetime
        remaining = (target_time - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            self._sched_lbl.configure(text="Starting now...")
            self._sched_timer = None
            self._do_start(urls, out, fk)
        else:
            self._sched_lbl.configure(text=f"⏰ Starting in {self._fmt_countdown(remaining)}")
            self._sched_timer = self.root.after(1000,
                lambda: self._countdown_tick(target_time, urls, out, fk))

    def _start(self):
        import datetime
        raw  = self.url_box.get("1.0","end")
        urls = [u.strip() for u in raw.splitlines()
                if u.strip() and URL_RE.match(u.strip())
                and not u.strip().startswith("blob:")
                and not u.strip().startswith("data:")]
        # De-dupe preserving order
        seen = set(); urls = [u for u in urls if not (u in seen or seen.add(u))]
        # Skip URLs already in history (completed previously)
        try:
            done_urls = {r.get("url","") for r in self.history.all() if r.get("status")=="done"}
            skipped = [u for u in urls if u in done_urls]
            if skipped:
                if messagebox.askyesno(APP_NAME,
                    f"{len(skipped)} URL(s) already downloaded previously.\n"
                    f"Skip them?"):
                    urls = [u for u in urls if u not in done_urls]
        except: pass
        if not urls:
            try:
                clip = self.root.clipboard_get().strip()
                if clip and URL_RE.match(clip):
                    urls = [clip]
                    self.url_box.delete("1.0","end")
                    self.url_box.insert("1.0", clip)
                else:
                    messagebox.showwarning(APP_NAME,"Paste at least one valid URL."); return
            except:
                messagebox.showwarning(APP_NAME,"Paste at least one valid URL."); return

        out = self.folder_var.get().strip() or DEFAULT_DIR
        Path(out).mkdir(parents=True, exist_ok=True)
        fk = self.fmt_var.get().split(":")[0].strip()
        if fk not in FMTS: fk="4k"

        self.cfg.update({"dir":out,"fmt":fk,"cookies":self.ck_var.get(),
                         "clip":self._clip_on.get()})
        jsave(CFG_PATH,self.cfg)

        delay = self._get_sched_delay()
        if delay and delay > 0:
            if self._sched_timer: self.root.after_cancel(self._sched_timer)
            target = datetime.datetime.now() + datetime.timedelta(seconds=delay)
            self.btn_dl.configure(state="disabled", text="Scheduled...")
            self.btn_cancel.configure(state="normal")
            self.log(f"[schedule] Download scheduled for {target.strftime('%I:%M %p')}")
            self._items = [DL(u,i+1,len(urls), self._referers.get(u,"")) for i,u in enumerate(urls)]
            self._build_rows(self._items)
            self._sched_timer = self.root.after(1000,
                lambda: self._countdown_tick(target, urls, out, fk))
            return

        self._do_start(urls, out, fk)

    def _do_start(self, urls, out, fk):
        self._stop.clear()
        self._paused      = False
        self._done_files  = []
        self._spd_history = []
        # Reuse existing items if they match the URL list (scheduler preview case).
        # Otherwise rebuild from scratch.
        existing_urls = [i.url for i in self._items] if self._items else []
        if existing_urls != urls:
            self._items = [DL(u,i+1,len(urls), self._referers.get(u,"")) for i,u in enumerate(urls)]
            self._build_rows(self._items)
        else:
            # Reset state on existing items
            for it in self._items:
                it.status = "waiting"; it.pct = 0; it.speed_v = 0; it.eta_v = None
                self._mq.put(("item_up", it))
        self.btn_dl.configure(state="disabled", text="Running...")
        self.btn_cancel.configure(state="normal")
        self.btn_pause.configure(state="normal")
        self.res_frame.pack_forget()

        self.state["queue"]=[{"url":u,"dir":out,"fmt":fk} for u in urls]
        jsave(STATE_PATH,self.state)

        # Concurrent worker pool — default 3 for visible parallelism
        max_par = max(1, min(MAX_CONCURRENT, int(self.cfg.get("concurrent",3))))
        self.log(f"[start] queue={len(self._items)} items, concurrent={max_par}")
        sem = threading.Semaphore(max_par)
        self._workers = []
        self._active_count = 0
        self._active_lock = threading.Lock()

        def runner(item):
            with sem:
                if self._stop.is_set():
                    item.status = "paused" if self._paused else "cancelled"
                    self._mq.put(("item_up", item)); return
                with self._active_lock:
                    self._active_count += 1
                    self._mq.put(("concur", (self._active_count, len(self._items))))
                try:
                    item.start_t = time.time()
                    self._run_one(item, out, fk)
                finally:
                    item.end_t = time.time()
                    with self._active_lock:
                        self._active_count -= 1
                        self._mq.put(("concur", (self._active_count, len(self._items))))
                    # Record stats + history
                    if item.status == "done":
                        self._mq.put(("hist_add", item))
                        self._mq.put(("stats_add", item))
                    # Drop from resume queue
                    self.state["queue"] = [q for q in self.state.get("queue",[])
                                            if q.get("url") != item.url]
                    jsave(STATE_PATH, self.state)

        for item in self._items:
            t = threading.Thread(target=runner, args=(item,), daemon=True)
            self._workers.append(t); t.start()

        # Watcher thread to fire done event when all complete
        def watcher():
            for t in self._workers: t.join()
            self._mq.put(("done", None))
        threading.Thread(target=watcher, daemon=True).start()

    def _do_pause(self):
        self._paused=True; self._stop.set()
        self.btn_pause.configure(state="disabled")
        self.log("[pause] pausing all active downloads...")

    def _do_cancel(self):
        self._paused=False; self._stop.set()
        if self._sched_timer:
            self.root.after_cancel(self._sched_timer)
            self._sched_timer = None
            self._sched_lbl.configure(text="")
            self.btn_dl.configure(state="normal", text="↓ Download")
            self.log("[schedule] cancelled")
        self.log("[cancel] cancelling...")

    # -- conflict resolution -----------------------------------------------
    def _resolve_conflict(self, target):
        """Return final target path or None to skip."""
        p = Path(target)
        if not p.exists(): return p
        policy = self.cfg.get("conflict","rename")
        if policy == "overwrite": return p
        if policy == "skip":     return None
        if policy == "ask":
            ans = messagebox.askyesnocancel(APP_NAME,
                f"File exists:\n{p.name}\n\nYes = overwrite, No = rename, Cancel = skip")
            if ans is True: return p
            if ans is None: return None
            policy = "rename"
        # rename
        i = 1
        while True:
            cand = p.parent / f"{p.stem} ({i}){p.suffix}"
            if not cand.exists(): return cand
            i += 1

    # -- single item run ---------------------------------------------------
    def _run_one(self, item, out, fk):
        # Apply category subfolder
        if self.cfg.get("categorize", False):
            cat = categorize(item.name)
            out = str(Path(out) / cat)
            Path(out).mkdir(parents=True, exist_ok=True)

        url = item.url
        ul = url.lower()
        if self.ck_var.get() == "none" and any(h in ul for h in ("artgrid","artlist","patreon","cms-public.artgrid")):
            self.log("[warn] Artgrid/Artlist/Patreon needs browser login for full quality. Set Cookies dropdown.")

        item.status="downloading"; self._mq.put(("item_up",item))
        self.log(f"\n[{item.idx}/{item.total}] {url[:100]}")

        mode = self.mode_var.get().split(":")[0].strip()
        kind = classify(url) if mode=="auto" else mode

        try:
            if kind=="file": self._run_file(url, out, item)
            else:            self._run_video(url, out, fk, item)
        except Exception as e:
            self.log(f"[error] {e}")
            item.status="error"
            self._mq.put(("item_up", item))

        if not self._stop.is_set() and item.status not in ("error","paused","cancelled"):
            item.status="done"; item.pct=100
            self._mq.put(("item_up", item))

    # -- ydl opts -----------------------------------------------------------
    def _ydl_opts(self, out, fk, item, url=""):
        f = FMTS[fk]
        url_l = url.lower() if url else ""
        is_youtube = any(h in url_l for h in ("youtube.com","youtu.be"))
        is_hls     = bool(url and not is_youtube and (
            ".m3u8" in url_l or "hls" in url_l or
            "artlist.io" in url_l or "artgrid.io" in url_l or
            "akamaized.net" in url_l or "cloudfront.net" in url_l or
            "cms-public" in url_l or "footage-hls" in url_l
        ))
        if is_hls:
            # HLS: pick highest available variant (Artgrid/Artlist serve only what URL allows)
            chosen = "best"
        elif is_youtube:
            chosen = f["fmt"]
        elif not self.ff and "fb" in f:
            chosen = f.get("fb", f["fmt"])
        else:
            chosen = f["fmt"]

        def hook(d):
            if self._stop.is_set():
                raise yt_dlp.utils.DownloadError("user_stop")
            s = d.get("status")
            if s=="downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done  = d.get("downloaded_bytes") or 0
                bps   = d.get("speed") or 0
                e_    = d.get("eta")
                item.pct     = (done/total*100) if total else 0
                item.speed_v = bps
                item.eta_v   = e_
                item.size_v  = total
                item.status  = "downloading"
                self._mq.put(("item_up",item))
                self._mq.put(("spd",bps))
                self._mq.put(("status",
                    f"[{item.idx}/{item.total}] {d.get('_percent_str','').strip()} "
                    f"· {spd(bps)} · ETA {eta(e_)}"))
            elif s=="finished":
                item.pct=100; self._mq.put(("item_up",item))
                self._mq.put(("status",f"[{item.idx}/{item.total}] Processing..."))
                fn = (d.get("filename") or
                      (d.get("info_dict") or {}).get("filepath") or
                      (d.get("info_dict") or {}).get("_filename") or "")
                if fn:
                    item.done_f = fn
                    item.name = Path(fn).name[:80]
                    self._mq.put(("item_up", item))

        def pp_hook(d):
            if d.get("status") != "finished": return
            info = d.get("info_dict") or {}
            fn = info.get("filepath") or d.get("filename") or ""
            if fn and Path(fn).exists():
                item.done_f = fn
                item.name = Path(fn).name[:80]
                if fn not in self._done_files:
                    self._done_files.append(fn)
                self._mq.put(("item_up", item))

        rate = int(self.cfg.get("rate_kbps",0)) * 1024
        opts = {
            "format":                     chosen,
            "outtmpl": {
                "default": str(Path(out)/"%(title).80s.%(ext)s"),
                "chapter": str(Path(out)/"%(title).60s - %(section_title)s.%(ext)s"),
            },
            "restrictfilenames":          False,
            "windowsfilenames":           False,
            "trim_file_name":             80,
            "noplaylist":                 not self.pl_var.get(),
            "writesubtitles":             self.sub_var.get(),
            "writeautomaticsub":          self.sub_var.get(),
            "subtitleslangs":             ["en","bn"] if self.sub_var.get() else [],
            "writethumbnail":             self.thumb_var.get(),
            "ignoreerrors":               True,
            "progress_hooks":             [hook],
            "postprocessor_hooks":        [pp_hook],
            "logger":                     _Log(self),
            "no_warnings":                False,
            "extractor_args":             {
                "youtube": {
                    # 'tv' + 'tv_simply' bypass YouTube PoToken — give 1080p without cookies.
                    # mweb/ios fallback. android last (heavily nerfed).
                    "player_client": ["default", "tv", "tv_simply", "mweb", "ios", "web_safari", "android"],
                    # NOTE: don't allow 'missing_pot' — those formats return 404
                    # fragments without a PoToken provider. Stick with formats
                    # that actually serve data.
                    "max_comments": ["0"],
                },
            },
            "youtube_include_dash_manifest": True,
            "format_sort":                ["res", "fps", "vcodec:h264", "acodec:aac", "size", "br"],
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "*/*",
                "Referer": self._referers.get(url, url) or url,
                "Origin":  "/".join(url.split("/")[:3]) if url and url.startswith("http") else "",
            },
            "geo_bypass":                 True,
            "age_limit":                  99,
            "hls_prefer_native":          False,
            "hls_use_mpegts":             True,
            "retries":                    15,
            "fragment_retries":           15,
            "concurrent_fragment_downloads": 4,
            "continuedl":                 True,
            "noprogress":                 False,
            # Clean up intermediate format-specific files after merge
            "keepvideo":                  False,
            "keep_fragments":             False,
            "clean_infojson":             True,
            "writeinfojson":              False,
            "writedescription":           False,
            "writeannotations":           False,
        }
        if rate > 0: opts["ratelimit"] = rate
        if self.ff:
            # Pass DIRECTORY so yt-dlp finds both ffmpeg + ffprobe
            opts["ffmpeg_location"] = str(Path(self.ff).parent)
        ck = self.ck_var.get()
        # YouTube PoToken nerf — without cookies, max 360p. Auto-try chrome
        # for YouTube even when user picked "none" (silent fallback if it fails).
        if is_youtube and (not ck or ck == "none"):
            # Auto-detect installed browser with cookies
            for browser, path in [
                ("chrome", Path.home()/"Library/Application Support/Google/Chrome"),
                ("brave",  Path.home()/"Library/Application Support/BraveSoftware/Brave-Browser"),
                ("edge",   Path.home()/"Library/Application Support/Microsoft Edge"),
                ("safari", Path.home()/"Library/Safari"),
                ("firefox",Path.home()/"Library/Application Support/Firefox"),
            ]:
                # Windows paths
                if platform.system() == "Windows":
                    wmap = {
                        "chrome": Path.home()/"AppData/Local/Google/Chrome/User Data",
                        "brave":  Path.home()/"AppData/Local/BraveSoftware/Brave-Browser/User Data",
                        "edge":   Path.home()/"AppData/Local/Microsoft/Edge/User Data",
                        "firefox":Path.home()/"AppData/Roaming/Mozilla/Firefox",
                    }
                    path = wmap.get(browser, path)
                if path.exists():
                    ck = browser
                    self.log(f"[info] YouTube HD needs cookies — auto-using {browser} cookies")
                    break
        if ck and ck != "none":
            opts["cookiesfrombrowser"] = (ck,)
        if is_youtube and (not ck or ck == "none"):
            self.log("[warn] No browser cookies found. YouTube will be 360p max. Login + try again.")
        # Merge output format (yt-dlp Merger uses -c copy — fast, no quality loss)
        if "merge" in f and not is_hls: opts["merge_output_format"]=f["merge"]
        if is_hls:
            opts["merge_output_format"] = "mp4"
            opts["final_ext"] = "mp4"
        if "audio" in f:
            opts["postprocessors"]=[{"key":"FFmpegExtractAudio",
                                     "preferredcodec":f["audio"],"preferredquality":"0"}]
        # For pp_compat: skip yt-dlp's VideoConvertor (caused hangs + triple processing).
        # _force_h264_if_needed runs single explicit ffmpeg pass after yt-dlp completes.
        if f.get("pp_compat") and self.ff:
            opts["merge_output_format"] = "mp4"
            opts["final_ext"] = "mp4"
            opts["format_sort"] = ["res", "fps", "vcodec:h264", "acodec:aac", "ext:mp4:m4a", "br"]
        return opts

    # -- video / file runners ----------------------------------------------
    def _run_video(self, url, out, fk, item):
        opts = self._ydl_opts(out, fk, item, url)

        def _try(o):
            with yt_dlp.YoutubeDL(o) as ydl: ydl.download([url])

        try:
            try:
                _try(opts)
            except yt_dlp.utils.DownloadError as e:
                emsg = str(e).lower()
                if "user_stop" in emsg:
                    raise
                # Cookie-related failures → retry without cookies
                cookie_err = any(k in emsg for k in (
                    "cookies", "cookiesfrombrowser", "could not copy chrome",
                    "permission denied", "keyring", "could not find browser"
                ))
                if cookie_err and "cookiesfrombrowser" in opts:
                    self.log("[warn] cookie read failed — retrying without cookies (HD may need login)")
                    opts2 = dict(opts); opts2.pop("cookiesfrombrowser", None)
                    _try(opts2)
                else:
                    raise
            if item.done_f: self._rename_if_uuid(item, url)
            # Force H.264 transcode for HLS sources when pp_compat selected.
            # FFmpegVideoConvertor skips if input already .mp4, even if codec is
            # not H.264. Explicit ffmpeg pass guarantees avc1 output for editors.
            if self.ff and item.done_f and FMTS.get(fk,{}).get("pp_compat"):
                self._force_h264_if_needed(item)
            # Always clean intermediate format-id files (yt-dlp keepvideo not always honored)
            if item.done_f:
                self._cleanup_intermediates(item)
            if not self._stop.is_set():
                item.status="done"; item.pct=100
                self._mq.put(("item_up",item))
        except yt_dlp.utils.DownloadError as e:
            if "user_stop" in str(e):
                item.status="paused" if self._paused else "cancelled"
            else:
                self.log(f"[error] {e}")
                item.status="error"
            self._mq.put(("item_up",item))
        except Exception as e:
            self.log(f"[error] unexpected: {e}")
            item.status="error"
            self._mq.put(("item_up",item))

    def _ffprobe_path(self):
        """Locate ffprobe binary same way as find_ff but for probe."""
        p = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
        if p and Path(p).exists(): return p
        if self.ff:
            d = Path(self.ff).parent
            for n in ("ffprobe.exe", "ffprobe"):
                cand = d / n
                if cand.exists(): return str(cand)
        return None

    def _ffprobe_duration(self, path):
        """Get duration in seconds via ffprobe, None if unavailable."""
        try:
            ffprobe = self._ffprobe_path()
            if not ffprobe: return None
            r = subprocess.run([ffprobe, "-v","error","-show_entries","format=duration",
                                "-of","default=noprint_wrappers=1:nokey=1", str(path)],
                               capture_output=True, text=True, timeout=10)
            return float((r.stdout or "0").strip() or 0) or None
        except Exception: return None

    def _ffprobe_codecs(self, path):
        """Return (video_codec, audio_codec, pix_fmt) lowercase. Empty if unknown."""
        try:
            ffprobe = self._ffprobe_path()
            if not ffprobe: return ("","","")
            r = subprocess.run([ffprobe, "-v","error",
                                "-show_entries","stream=codec_name,codec_type,pix_fmt",
                                "-of","default=noprint_wrappers=1", str(path)],
                               capture_output=True, text=True, timeout=10)
            out = (r.stdout or "").lower()
            vcodec, acodec, pix = "", "", ""
            blocks = out.split("codec_type=")
            for b in blocks:
                if b.startswith("video"):
                    for line in b.splitlines():
                        if line.startswith("codec_name="): vcodec = line.split("=",1)[1].strip()
                        elif line.startswith("pix_fmt="):  pix    = line.split("=",1)[1].strip()
                elif b.startswith("audio"):
                    for line in b.splitlines():
                        if line.startswith("codec_name="): acodec = line.split("=",1)[1].strip()
            return (vcodec, acodec, pix)
        except Exception: return ("","","")

    def _cleanup_intermediates(self, item):
        """Delete all yt-dlp + transcode intermediate files in download folder."""
        try:
            p = Path(item.done_f)
            if not p.exists(): return
            parent = p.parent
            import re as _re
            for f in parent.iterdir():
                if not f.is_file(): continue
                try:
                    if f.resolve() == p.resolve(): continue
                except: pass
                n = f.name
                if _re.search(r"\.f\d+\.(mp4|m4a|webm|mkv|mov|ts)$", n, _re.I):
                    try: f.unlink(); self.log(f"[cleanup] {n}")
                    except: pass
                elif _re.search(r"\.(h264_tmp|remux_tmp|tmp)\.mp4$", n, _re.I):
                    try: f.unlink(); self.log(f"[cleanup] {n}")
                    except: pass
                elif n.endswith((".part",".ytdl",".description",".info.json",".live_chat.json")):
                    try: f.unlink(); self.log(f"[cleanup] {n}")
                    except: pass
        except Exception as e:
            self.log(f"[warn] cleanup failed: {e}")

    def _force_h264_if_needed(self, item):
        """Smart: fast remux if already H.264+AAC, else full re-encode.
        Most YouTube/Artgrid files are already h264 → 5s remux vs minutes transcode."""
        try:
            p = Path(item.done_f)
            if not p.exists():
                self.log(f"[warn] transcode skipped: file not found {p}")
                return
            if p.suffix.lower() not in (".mp4",".mkv",".mov",".webm",".ts",".m4v",".avi"):
                return

            # Probe codec first — decide fast remux vs full re-encode
            vcodec, acodec, pix = self._ffprobe_codecs(p)
            duration = self._ffprobe_duration(p) or 0

            # Fast path: source already H.264 + AAC + yuv420p → just remux for faststart
            if vcodec in ("h264","avc1") and acodec in ("aac",) and pix in ("yuv420p",""):
                self._fast_remux(item, p, duration)
                return

            self.log(f"[transcode] {p.name}: {vcodec}/{acodec} → H.264+AAC ({duration:.0f}s)...")
            item.pct = 0
            item.status = "downloading"
            self._mq.put(("status", f"[{item.idx}/{item.total}] Transcoding to H.264..."))
            self._mq.put(("item_up", item))

            tmp = p.parent / (p.stem + ".h264_tmp.mp4")
            cmd = [self.ff, "-y",
                   "-progress", "pipe:2", "-nostats",
                   "-fflags","+genpts+igndts",
                   "-i", str(p),
                   "-map","0:v:0?","-map","0:a:0?",
                   # Video — H.264 high profile, fast preset (high quality, 3-4x faster than slow)
                   "-c:v","libx264","-profile:v","high","-level","5.1",
                   "-preset","fast","-crf","18","-pix_fmt","yuv420p",
                   # Audio — AAC stereo 48kHz, async filter to fix drift
                   "-c:a","aac","-b:a","320k","-ar","48000","-ac","2",
                   "-af","aresample=async=1000:min_hard_comp=0.100:first_pts=0",
                   # A/V sync — VFR passthrough, fix HLS negative timestamps
                   "-fps_mode","vfr",
                   "-avoid_negative_ts","make_zero",
                   # Container
                   "-movflags","+faststart","-tag:v","avc1",
                   "-max_muxing_queue_size","1024",
                   str(tmp)]

            # Stream ffmpeg progress (writes to stderr with -progress pipe:2)
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
            last_pct = -1
            t0 = time.time()
            tail = []
            for line in proc.stderr:
                tail.append(line)
                if len(tail) > 40: tail = tail[-40:]
                if self._stop.is_set():
                    proc.terminate(); break
                # ffmpeg -progress output: key=value lines, "out_time_us=12345"
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=",1)[1].strip())
                        sec = us / 1_000_000.0
                        if duration > 0:
                            pct = min(99.5, (sec / duration) * 100)
                            if int(pct) != last_pct:
                                last_pct = int(pct)
                                item.pct = pct
                                elapsed = time.time() - t0
                                rate = (sec / elapsed) if elapsed > 0 else 0
                                remaining = (duration - sec) / rate if rate > 0 else None
                                item.eta_v = int(remaining) if remaining else None
                                self._mq.put(("item_up", item))
                                self._mq.put(("status",
                                    f"[{item.idx}/{item.total}] Transcoding {pct:.0f}% · ETA {eta(remaining)}"))
                    except: pass
                elif line.startswith("progress=end"):
                    item.pct = 100
                    self._mq.put(("item_up", item))
            rc = proc.wait()
            if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
                final = p.with_suffix(".mp4")
                p.unlink(missing_ok=True)
                tmp.rename(final)
                item.done_f = str(final)
                item.name   = final.name
                item.pct = 100
                self._mq.put(("item_up", item))
                self.log(f"[done] Premiere-ready: {final.name}")
            else:
                err = "".join(tail)[-300:]
                self.log(f"[warn] re-encode failed (rc={rc}): {err}")
                tmp.unlink(missing_ok=True)
        except Exception as e:
            self.log(f"[warn] force h264 skipped: {e}")

    def _fast_remux(self, item, p, duration):
        """Fast remux — source already H.264+AAC. Just ensure MP4 + faststart + avc1 tag.
        ~5 seconds vs minutes of re-encode. Quality identical (stream copy)."""
        try:
            # If already .mp4 with faststart, skip entirely
            if p.suffix.lower() == ".mp4":
                # Check if already has faststart — quick heuristic: file starts with ftyp+moov
                try:
                    with open(p, "rb") as f:
                        head = f.read(64)
                    if b"moov" in head[:64]:
                        self.log(f"[ok] {p.name} already Premiere-ready (no remux needed)")
                        return
                except Exception: pass

            self.log(f"[remux] {p.name} → MP4+faststart (fast, no quality loss)...")
            item.pct = 0
            item.status = "downloading"
            self._mq.put(("status", f"[{item.idx}/{item.total}] Remuxing..."))
            self._mq.put(("item_up", item))

            tmp = p.parent / (p.stem + ".remux_tmp.mp4")
            cmd = [self.ff, "-y", "-progress","pipe:2","-nostats",
                   "-i", str(p),
                   "-map","0:v:0?","-map","0:a:0?",
                   "-c:v","copy","-c:a","copy",
                   "-movflags","+faststart","-tag:v","avc1",
                   str(tmp)]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
            last_pct = -1
            tail = []
            for line in proc.stderr:
                tail.append(line)
                if len(tail) > 30: tail = tail[-30:]
                if self._stop.is_set():
                    proc.terminate(); break
                if line.startswith("out_time_us=") and duration > 0:
                    try:
                        us = int(line.split("=",1)[1].strip())
                        sec = us / 1_000_000.0
                        pct = min(99.5, (sec / duration) * 100)
                        if int(pct) != last_pct:
                            last_pct = int(pct)
                            item.pct = pct
                            self._mq.put(("item_up", item))
                            self._mq.put(("status",
                                f"[{item.idx}/{item.total}] Remuxing {pct:.0f}%"))
                    except: pass
            rc = proc.wait()
            if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
                final = p.with_suffix(".mp4")
                p.unlink(missing_ok=True)
                tmp.rename(final)
                item.done_f = str(final)
                item.name = final.name
                item.pct = 100
                self._mq.put(("item_up", item))
                self.log(f"[done] {final.name}")
            else:
                err = "".join(tail)[-200:]
                self.log(f"[warn] remux failed (rc={rc}): {err}")
                tmp.unlink(missing_ok=True)
        except Exception as e:
            self.log(f"[warn] fast remux skipped: {e}")

    def _extract_slug_from_url(self, url, uuid_pat, generic_skip):
        import re as _re2, urllib.parse as _up
        parsed   = _up.urlparse(url)
        path_dec = _up.unquote(parsed.path)
        slugs = []
        for x in path_dec.split("/"):
            if not x or len(x) <= 3: continue
            if uuid_pat.match(x): continue
            if x.isdigit(): continue
            if x.lower() in generic_skip: continue
            if x.endswith(".m3u8") or x.endswith(".mpd") or x.endswith(".ts"):
                stem = x.rsplit(".",1)[0]
                stem = _re2.sub(r"_[0-9]+p.*$","",stem)
                stem = _re2.sub(r"_[0-9]+$","",stem)
                if len(stem) > 3 and not uuid_pat.match(stem):
                    slugs.append(stem)
                continue
            if "footage-hls" in x or "footage-dash" in x: continue
            slugs.append(x)
        return slugs

    def _rename_if_uuid(self, item, url):
        """Rename downloaded file to descriptive name extracted from URL or referer.
        Strategy: ALWAYS attempt rename if a good slug found in referer.
        Falls back to source URL slug or original name."""
        import re as _re, urllib.parse as _up
        if not item.done_f: return
        p = Path(item.done_f)
        if not p.exists():
            parent = p.parent; stem = p.stem; cand = None
            for ext in (".mp4",".mkv",".webm",".m4a",".mp3"):
                q = parent / f"{stem}{ext}"
                if q.exists(): cand = q; break
            if cand is None and parent.exists():
                matches = sorted(parent.glob(f"{stem}.*"))
                if matches: cand = matches[0]
            if cand is None: return
            p = cand
            item.done_f = str(p)
        name = p.stem
        uuid_pat = _re.compile("^[0-9a-f]{8}-[0-9a-f]{4}-", _re.I)
        try:
            referer = self._referers.get(url, "") or getattr(item,"referer","")
            generic_skip = {"clip","footage","video","watch","embed","play",
                            "stream","files","media","content","download",
                            "artgrid","artlist","io","com","www","cms-public",
                            "footage-hls","footage-dash"}
            slug_pool = []
            if referer:
                slug_pool += self._extract_slug_from_url(referer, uuid_pat, generic_skip)
            slug_pool += self._extract_slug_from_url(url, uuid_pat, generic_skip)
            parsed = _up.urlparse(url)
            qs = _up.parse_qs(parsed.query)
            title_q = qs.get("title", qs.get("name", qs.get("filename", [])))
            # Priority: query string title > referer slug > URL slug
            if title_q:
                new_name = title_q[0]
            elif slug_pool:
                new_name = max(slug_pool, key=lambda s: (len(s.replace("-"," ").split()), len(s)))
            else:
                return
        except Exception:
            return
        new_name = _re.sub("[^a-zA-Z0-9 _-]", " ", new_name)
        new_name = _re.sub(" +", " ", new_name).strip()[:60]
        if not new_name or len(new_name) < 3: return
        # Skip rename only if new name == current name (no point)
        if new_name.lower() == name.lower(): return
        # Apply conflict resolution
        final = self._resolve_conflict(p.parent / f"{new_name}{p.suffix}")
        if final is None: return
        try:
            p.rename(final)
            item.done_f = str(final)
            item.name   = final.name
            self._mq.put(("item_up", item))
            self.log(f"[rename] {p.name} → {final.name}")
        except Exception as e:
            self.log(f"[warn] rename failed: {e}")

    def _run_file(self, url, out, item):
        def prog(p,s,r):
            item.pct=p; item.speed_v=s; item.eta_v=r; item.status="downloading"
            self._mq.put(("item_up",item))
            self._mq.put(("spd",s))
            self._mq.put(("status",f"[{item.idx}/{item.total}] {p:.0f}% · {spd(s)} · ETA {eta(r)}"))
        rate = int(self.cfg.get("rate_kbps",0)) * 1024
        dl = FileDL(url, Path(out), n=THREADS, prog_cb=prog, log_cb=self.log,
                    cancel_fn=lambda: self._stop.is_set(), rate_limit=rate)
        res = dl.run()
        if res:
            # Apply conflict resolution
            final = self._resolve_conflict(Path(res))
            if final is None:
                Path(res).unlink(missing_ok=True)
                item.status="cancelled"
                self._mq.put(("item_up", item))
                return
            if str(final) != res:
                Path(res).rename(final); res = str(final)
            if res not in self._done_files:
                self._done_files.append(res); item.done_f=res
                # Size from disk
                try: item.size_v = Path(res).stat().st_size
                except: pass
        if not self._stop.is_set():
            item.status="done"; item.pct=100
            self._mq.put(("item_up",item))

    # -- site grabber -------------------------------------------------------
    def _site_grab_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Grab media from page")
        d.geometry("600x420")
        d.configure(bg=T["BG"])
        tk.Label(d, text="Paste page URL — app will fetch HTML and extract media links",
                 bg=T["BG"], fg=T["TEXT"], font=("Helvetica",10)).pack(pady=(14,6))
        v = tk.StringVar()
        e = self._entry(d, v); e.pack(fill="x", padx=14, pady=6); e.focus()
        result = tk.Text(d, height=14, bg=T["INPUT"], fg=T["TEXT"], relief="flat",
                         padx=10, pady=8, font=("Menlo",9))
        result.pack(fill="both", expand=True, padx=14, pady=8)

        def grab():
            page = v.get().strip()
            if not page or not URL_RE.match(page):
                result.insert("end", "Invalid URL\n"); return
            result.delete("1.0","end")
            result.insert("end", f"Fetching {page}...\n")
            d.update_idletasks()
            try:
                req = urllib.request.Request(page, headers={
                    "User-Agent":"Mozilla/5.0 (compatible; ZHDownloader/5.0)"
                })
                with urllib.request.urlopen(req, timeout=15) as r:
                    html = r.read().decode("utf-8","ignore")
            except Exception as ex:
                result.insert("end", f"Failed: {ex}\n"); return
            urls = set(URL_RE.findall(html))
            media = sorted(u for u in urls
                           if any(u.lower().endswith(e) for e in VE+FE)
                           or any(h in u.lower() for h in VH))
            result.delete("1.0","end")
            if not media:
                result.insert("end", "No media links found.\n"); return
            for u in media: result.insert("end", u+"\n")
            result.insert("end", f"\nFound {len(media)} link(s).\n")

        def add():
            txt = result.get("1.0","end").strip().splitlines()
            valid = [u for u in txt if URL_RE.match(u.strip())]
            if not valid: return
            cur = self.url_box.get("1.0","end").strip()
            self.url_box.delete("1.0","end")
            self.url_box.insert("1.0",(cur+"\n"+"\n".join(valid)).strip() if cur else "\n".join(valid))
            self.log(f"[grab] added {len(valid)} URLs from {v.get()[:60]}")
            d.destroy()

        btns = tk.Frame(d, bg=T["BG"]); btns.pack(fill="x", padx=14, pady=10)
        ttk.Button(btns, text="Grab links", style="Main.TButton", command=grab).pack(side="left", padx=(0,8))
        ttk.Button(btns, text="Add to queue", style="Ghost.TButton", command=add).pack(side="left")
        ttk.Button(btns, text="Close", style="Ghost.TButton", command=d.destroy).pack(side="right")

    # -- done ---------------------------------------------------------------
    def _on_done(self):
        self.btn_dl.configure(state="normal", text="↓ Download")
        self.btn_cancel.configure(state="disabled")
        self.btn_pause.configure(state="disabled")
        self._mq.put(("spd",0))
        done = sum(1 for it in self._items if it.status=="done")
        err  = sum(1 for it in self._items if it.status=="error")
        msg  = f"Done: {done} file(s) downloaded"
        if err:    msg+=f"  ·  {err} error"
        if self._paused: msg+="  ·  paused"
        self._mq.put(("status",msg))

        if self._paused:
            rem = [{"url":i.url,"dir":self.cfg.get("dir"),"fmt":self.cfg.get("fmt")}
                    for i in self._items if i.status in ("waiting","paused")]
            self.state["queue"] = rem
            jsave(STATE_PATH, self.state)
            if rem:
                self.res_lbl.configure(text=f"⏸ Paused: {len(rem)} items")
                self.res_frame.pack(fill="x",padx=4,pady=(0,8))
        n = len(self._done_files)
        if n>0:
            self._notify(f"Done: {n} file{'s' if n>1 else ''} downloaded",
                         Path(self._done_files[0]).name)
            if self.cfg.get("completion_sound", True): self._play_sound()
            try: self.root.bell()
            except: pass

        if done > 0 and err == 0 and not self._paused:
            self.root.after(1500, self._auto_clear)

        # Shutdown after done?
        if self.cfg.get("shutdown_after", False) and done > 0 and not self._paused:
            self._shutdown_warn()

    def _shutdown_warn(self):
        w = tk.Toplevel(self.root)
        w.title("Shutdown scheduled")
        w.geometry("400x180"); w.configure(bg=T["BG"])
        tk.Label(w, text="⚠ Shutdown in 60 seconds", bg=T["BG"], fg=T["RED"],
                 font=("Helvetica",14,"bold")).pack(pady=14)
        cnt = tk.IntVar(value=60)
        lbl = tk.Label(w, textvariable=cnt, bg=T["BG"], fg=T["TEXT"],
                       font=("Helvetica",32,"bold"))
        lbl.pack()
        cancelled = {"v":False}
        def tick():
            if cancelled["v"]: return
            cnt.set(cnt.get()-1)
            if cnt.get() <= 0:
                w.destroy()
                if   platform.system()=="Darwin":
                    subprocess.run(["osascript","-e",'tell app "System Events" to shut down'])
                elif platform.system()=="Windows":
                    subprocess.run(["shutdown","/s","/t","0"])
                else:
                    subprocess.run(["shutdown","-h","now"])
                return
            w.after(1000, tick)
        ttk.Button(w, text="Cancel shutdown", style="Danger.TButton",
                   command=lambda: (cancelled.__setitem__("v",True), w.destroy())
                   ).pack(pady=14)
        tick()

    def _play_sound(self):
        try:
            if platform.system()=="Darwin":
                subprocess.Popen(["afplay","/System/Library/Sounds/Glass.aiff"])
            elif platform.system()=="Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            else:
                subprocess.Popen(["paplay","/usr/share/sounds/freedesktop/stereo/complete.oga"])
        except: pass

    def _auto_clear(self):
        self.url_box.delete("1.0","end")
        self.log_txt.configure(state="normal")
        self.log_txt.delete("1.0","end")
        self.log_txt.configure(state="disabled")
        self.log("[ready] Paste URL and press Download")

    def _notify(self, title, body):
        try:
            if   platform.system()=="Darwin":
                subprocess.Popen(["osascript","-e",
                    f'display notification "{body}" with title "{APP_NAME}" subtitle "{title}"'])
            elif platform.system()=="Windows":
                pass  # toast omitted for brevity
            else:
                subprocess.Popen(["notify-send",APP_NAME,f"{title}\n{body}"])
        except: pass

    # -- tray icon ----------------------------------------------------------
    def _setup_tray(self):
        """Defer to after mainloop ready. Any failure here must NOT crash app."""
        self.tray = None
        if not HAS_TRAY or not HAS_PIL: return
        # Schedule tray setup 1 second after window shows
        self.root.after(1000, self._init_tray_safe)

    def _init_tray_safe(self):
        try:
            icon_path = self._r("AppIcon.ico") or self._r("AppIcon_512.png") or self._r("header-logo.png")
            if not icon_path:
                print("[tray] no icon file found"); return
            # Force-load image data BEFORE handing to pystray
            # (lazy-load can crash inside pystray's background thread)
            img = Image.open(icon_path)
            img.load()
            img = img.copy().convert("RGBA")
            # Resize for tray
            img.thumbnail((64, 64), Image.LANCZOS)

            def _safe_cb(handler):
                """Wrap callback to prevent any exception from killing pystray thread."""
                def wrapped(icon=None, item=None):
                    try: handler(icon, item)
                    except Exception as e: print(f"[tray] callback error: {e}")
                return wrapped

            menu = pystray.Menu(
                pystray.MenuItem("Show ZH Downloader", _safe_cb(self._tray_show), default=True),
                pystray.MenuItem("Pause all",          _safe_cb(self._tray_pause)),
                pystray.MenuItem("Cancel all",         _safe_cb(self._tray_cancel)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open download folder", _safe_cb(self._tray_open_folder)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",               _safe_cb(self._tray_quit)),
            )
            self.tray = pystray.Icon(APP_NAME, img, APP_NAME, menu)

            def _run_tray():
                try: self.tray.run()
                except Exception as e:
                    print(f"[tray] run failed: {e}")
                    self.tray = None
            threading.Thread(target=_run_tray, daemon=True).start()
            self.log("[tray] icon initialized")
        except Exception as e:
            print(f"[tray] init failed: {e}")
            self.tray = None

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(50, lambda: self.root.attributes("-topmost", False))
        except: pass

    def _tray_pause(self, icon=None, item=None):
        if self._is_running(): self.root.after(0, self._do_pause)

    def _tray_cancel(self, icon=None, item=None):
        if self._is_running(): self.root.after(0, self._do_cancel)

    def _tray_open_folder(self, icon=None, item=None):
        self.root.after(0, self._open_folder)

    def _tray_quit(self, icon=None, item=None):
        try:
            if self.tray: self.tray.stop()
        except: pass
        self.root.after(0, self._real_quit)

    def _real_quit(self):
        try: self.root.destroy()
        except: pass
        os._exit(0)

    def _show_help(self):
        """In-app help dialog with install guide + FAQ for students."""
        d = tk.Toplevel(self.root)
        d.title("Help — ZH Downloader")
        d.geometry("680x600"); d.configure(bg=T["BG"])
        try: d.transient(self.root)
        except: pass

        # Header
        h = tk.Frame(d, bg=T["HEADER"], height=54); h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="📖  ZH Downloader — Quick Help", bg=T["HEADER"], fg=T["ACCENT"],
                 font=("Helvetica",14,"bold")).pack(side="left", padx=18, pady=14)
        tk.Frame(d, bg=T["BORDER"], height=1).pack(fill="x")

        # Body — scrollable text
        body = tk.Frame(d, bg=T["BG"]); body.pack(fill="both", expand=True, padx=18, pady=14)
        txt = tk.Text(body, font=("Helvetica",10), bg=T["SURF"], fg=T["TEXT"],
                      relief="flat", padx=14, pady=10, wrap="word")
        txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, command=txt.yview); sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)

        for tag, col, font in [("h1", T["ACCENT"], ("Helvetica",13,"bold")),
                                ("h2", T["TEXT"],   ("Helvetica",11,"bold")),
                                ("b",  T["TEXT"],   ("Helvetica",10,"bold")),
                                ("dim",T["MUTED"],  ("Helvetica",9))]:
            txt.tag_configure(tag, foreground=col, font=font)

        sections = [
            ("h1", "Quick Start"),
            ("",   "1. Set Cookies to chrome (top of Downloads tab) for HD quality\n"
                   "2. Pick Format: 4K or HD\n"
                   "3. Paste video URL\n"
                   "4. Click Download\n\n"),
            ("h1", "Getting HD/4K downloads"),
            ("h2", "YouTube"),
            ("",   "• Open Chrome → login to YouTube (your Gmail)\n"
                   "• In app: Cookies dropdown → chrome\n"
                   "• Without cookies = max 720p; with cookies = up to 4K\n\n"),
            ("h2", "Artgrid / Artlist (subscription sites)"),
            ("",   "• Active subscription required\n"
                   "• Login in Chrome\n"
                   "• Cookies dropdown → chrome\n"
                   "• Use clip page URL, not preview .m3u8\n\n"),
            ("h1", "Premiere Pro compatibility"),
            ("",   "• Format 4K / HD auto-transcodes to H.264 + AAC MP4\n"
                   "• Drag .mp4 into Premiere — opens without re-encoding\n"
                   "• Codec: avc1 high profile, level 5.1, yuv420p\n\n"),
            ("h1", "Browser extension"),
            ("",   "1. Chrome → chrome://extensions/\n"
                   "2. Enable Developer mode (top right)\n"
                   "3. Load unpacked → select extension/ folder\n"
                   "4. Pin the ZH icon\n"
                   "5. On video pages, click floating button bottom-right\n\n"),
            ("h1", "Three ways to download"),
            ("",   "A. Paste URL in box → Download button\n"
                   "B. Browser extension floating button\n"
                   "C. Watch clipboard — copy URL, app auto-adds\n\n"),
            ("h1", "Troubleshooting"),
            ("b",  "App won't open on Mac:\n"),
            ("",   "Right-click .app in Applications → Open → Open Anyway\n\n"),
            ("b",  "Downloads at 360p:\n"),
            ("",   "Cookies = chrome + login YouTube in Chrome\n\n"),
            ("b",  "Premiere won't import:\n"),
            ("",   "Use format 4K or HD (not Audio MP3) — auto-transcodes\n\n"),
            ("b",  "App crashes:\n"),
            ("",   "Delete ~/.zhdownloader.json and relaunch\n\n"),
            ("b",  "Browser button missing:\n"),
            ("",   "Visit a video page, wait 2 seconds, button appears\n\n"),
            ("h1", "Settings"),
            ("",   "• Theme: Light/Cream/Sunset/Midnight/Forest/Mono Dark\n"
                   "• Concurrent downloads: 1-5 parallel\n"
                   "• Speed limit: KB/s throttle\n"
                   "• Auto-categorize: organize to Video/Audio folders\n"
                   "• Conflict: rename / overwrite / skip / ask\n\n"),
            ("h1", "Need more help?"),
            ("",   "Ask in your ZH Motions community group.\n"
                   "Bug reports: screenshot + send to instructor.\n\n"),
            ("dim", "ZH Motions © 2026 — Internal student use only.\n"
                    f"Version: {APP_VER}"),
        ]
        for tag, text in sections:
            if tag: txt.insert("end", text+"\n", tag)
            else:   txt.insert("end", text)
        txt.configure(state="disabled")

        # Promo banner
        promo = tk.Frame(d, bg=T["SURF"], padx=14, pady=10)
        promo.pack(fill="x", padx=18, pady=(0,10))
        tk.Label(promo, text="🎬  Become a pro editor — ZH Motions Courses",
                 bg=T["SURF"], fg=T["ACCENT"], font=("Helvetica",10,"bold")).pack(side="left")
        ttk.Button(promo, text="Visit www.zhmotions.com", style="Main.TButton",
                   command=lambda: self._open_url("https://www.zhmotions.com")
                   ).pack(side="right")

        # Footer
        ftr = tk.Frame(d, bg=T["BG"]); ftr.pack(fill="x", padx=18, pady=(0,14))
        ttk.Button(ftr, text="Open Online Guide", style="Ghost.TButton",
                   command=lambda: self._open_url(
                       "https://github.com/zhmotions/zhmotionsdownloader/blob/main/student-pack/INSTALL-STUDENTS.md"
                   )).pack(side="left", padx=(0,8))
        ttk.Button(ftr, text="Close", style="Ghost.TButton",
                   command=d.destroy).pack(side="right")

    def _open_url(self, url):
        try:
            if   platform.system()=="Darwin":  subprocess.Popen(["open", url])
            elif platform.system()=="Windows": subprocess.Popen(["cmd","/c","start",url], shell=False)
            else:                              subprocess.Popen(["xdg-open", url])
        except Exception as e:
            self.log(f"[warn] open url failed: {e}")

    def _show_about(self):
        """About dialog — branding for ZH Motions students distribution."""
        d = tk.Toplevel(self.root)
        d.title("About")
        d.geometry("440x540"); d.configure(bg=T["BG"]); d.resizable(False, False)
        try: d.transient(self.root); d.grab_set()
        except: pass

        # Logo
        lp = self._r("AppIcon_512.png") or self._r("header-logo.png")
        if lp:
            try:
                img = tk.PhotoImage(file=lp)
                # Resize down by subsample
                img = img.subsample(max(1, img.width()//120), max(1, img.height()//120))
                lbl = tk.Label(d, image=img, bg=T["BG"])
                lbl.image = img
                lbl.pack(pady=(20,10))
            except: pass

        tk.Label(d, text=APP_NAME, bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica",20,"bold")).pack()
        tk.Label(d, text=f"Version {APP_VER}", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",10)).pack(pady=(2,14))

        # Branding box
        box = tk.Frame(d, bg=T["SURF"], padx=20, pady=14)
        box.pack(fill="x", padx=24, pady=8)
        tk.Label(box, text="🎓  Licensed to ZH Motions Students",
                 bg=T["SURF"], fg=T["ACCENT"], font=("Helvetica",11,"bold")).pack(anchor="w")
        tk.Label(box, text="Internal use only — do not redistribute outside the program.",
                 bg=T["SURF"], fg=T["MUTED"], font=("Helvetica",9), wraplength=360,
                 justify="left").pack(anchor="w", pady=(4,0))

        # Credits
        cred = tk.Frame(d, bg=T["BG"]); cred.pack(fill="x", padx=24, pady=14)
        tk.Label(cred, text="Built by ZH Motions", bg=T["BG"], fg=T["TEXT"],
                 font=("Helvetica",10,"bold")).pack(anchor="w")
        tk.Label(cred, text="zhmotions.com", bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica",9,"underline"), cursor="hand2"
                 ).pack(anchor="w").bind("<Button-1>",
                 lambda e: subprocess.Popen(["open", APP_URL]) if platform.system()=="Darwin"
                 else subprocess.Popen(["xdg-open", APP_URL])) if False else None

        # 3rd party credits
        legal = tk.Frame(d, bg=T["BG"]); legal.pack(fill="x", padx=24, pady=(4,8))
        tk.Label(legal, text="Powered by:", bg=T["BG"], fg=T["MUTED"],
                 font=("Helvetica",9,"bold")).pack(anchor="w")
        for tool, lic in [("yt-dlp", "Unlicense / public domain"),
                          ("Pillow (PIL)", "HPND License"),
                          ("tkinterdnd2", "MIT License"),
                          ("pystray", "LGPL-3.0"),
                          ("ffmpeg", "LGPL-2.1+")]:
            tk.Label(legal, text=f"  • {tool} — {lic}", bg=T["BG"], fg=T["MUTED"],
                     font=("Helvetica",8)).pack(anchor="w")

        # ZH Motions promo
        promo = tk.Frame(d, bg=T["SURF"], padx=18, pady=12)
        promo.pack(fill="x", padx=24, pady=10)
        tk.Label(promo, text="🎬  Level up your video editing skills",
                 bg=T["SURF"], fg=T["ACCENT"], font=("Helvetica",11,"bold")).pack()
        tk.Label(promo, text="Premiere Pro · After Effects · Color Grading · Freelance",
                 bg=T["SURF"], fg=T["MUTED"], font=("Helvetica",9)).pack(pady=(2,8))
        ttk.Button(promo, text="🌐  Visit www.zhmotions.com", style="Main.TButton",
                   command=lambda: self._open_url("https://www.zhmotions.com")
                   ).pack()

        # Close
        ttk.Button(d, text="Close", style="Ghost.TButton",
                   command=d.destroy).pack(pady=(8,18))

    def _on_close(self):
        """Minimize-to-tray if tray available, else quit normally."""
        if self.tray is not None:
            try:
                self.root.withdraw()
                self.log("[tray] minimized to tray. Click tray icon to restore.")
            except: pass
        else:
            self._real_quit()


class _Log:
    def __init__(self,a): self.a=a
    def debug(self,m):
        if m.startswith("[debug]") or ("[download]" in m and "%" in m): return
        self.a.log(m)
    def info(self,m):    self.a.log(m)
    def warning(self,m): self.a.log(f"[warn] {m}")
    def error(self,m):   self.a.log(f"[error] {m}")


def main():
    """Staged startup so any optional feature failure can't crash app."""
    global HAS_DND

    # Stage 1: probe tkdnd binary BEFORE creating root.
    # Bundled .app may have Python wrapper but no native .dylib/.dll.
    if HAS_DND:
        try:
            _probe = tk.Tk()
            _probe.withdraw()
            _probe.tk.call('package', 'require', 'tkdnd')
            _probe.destroy()
        except Exception as e:
            print(f"[warn] tkdnd probe failed ({e}); drag-drop disabled")
            HAS_DND = False
            try: _probe.destroy()
            except: pass

    # Stage 2: build real root with chosen class
    root = None
    if HAS_DND:
        try:
            root = TkinterDnD.Tk()
        except Exception as e:
            print(f"[warn] TkinterDnD.Tk() failed ({e}); fallback to tk.Tk()")
            HAS_DND = False
    if root is None:
        root = tk.Tk()

    # Stage 3: build App with global exception guard
    try:
        App(root)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try: messagebox.showerror(APP_NAME, f"Startup failed:\n{e}")
        except: pass
        return

    root.mainloop()

if __name__=="__main__":
    main()
