"""
ZH Downloader v5.1 - Universal Download Manager by ZH Motions
IDM-class features: tabs, concurrent downloads, history, stats, themes,
categories, speed limit, conflict dialog, completion actions,
drag-drop URLs, tray icon, card thumbnails.
"""

import os, sys, threading, queue as Q, json, subprocess, shutil, platform
import webbrowser
from contextlib import nullcontext
import re, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Auto-update: prefer newer yt-dlp wheel cached in user dir over bundled
_YTDLP_USER_CACHE = Path.home() / ".zhdownloader-ytdlp"
# The bundled yt-dlp is built from MASTER (its version string equals the last
# stable), so a cached STABLE of the same number would shadow newer code with
# older, broken extractors (Facebook…). Cache wins only if STRICTLY newer.
_YTDLP_BUNDLED_VER = (2026, 7, 4)
def _ytdlp_cache_is_newer():
    try:
        t = (_YTDLP_USER_CACHE / "yt_dlp" / "version.py").read_text()
        import re as _re
        v = _re.search(r"__version__\s*=\s*'([^']+)'", t).group(1)
        return tuple(int(x) for x in _re.findall(r"\d+", v))[:3] > _YTDLP_BUNDLED_VER
    except Exception:
        return False
if (_YTDLP_USER_CACHE / "yt_dlp").exists() and _ytdlp_cache_is_newer():
    sys.path.insert(0, str(_YTDLP_USER_CACHE))

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
    from tkinterdnd2 import TkinterDnD, DND_TEXT, DND_FILES, DND_ALL
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
APP_VER     = "6.6.18"
APP_AUTHOR  = "ZH Motions"
APP_URL     = "https://zhmotions.com"
BRIDGE_PORT = 9613
EXT_STORE_URL = "https://chromewebstore.google.com/detail/zh-downloader/gofeihalfifogcnhemcljpplpbkhemok"  # direct store listing — no server hop, works even if the site redirect is down

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

# SSL context with a real CA bundle — a frozen .app on a fresh client Mac can't always
# find system certs → urlopen SSL error → "Couldn't reach the license server". Bundle certifi.
import ssl
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    try: SSL_CTX = ssl.create_default_context()
    except Exception: SSL_CTX = None

# -- Licensing (free app, Pro unlocked by a key — same system as ZH MacCleaner) --
LICENSE_URL = "https://zhmotions.com/api/license/verify"   # non-www + no .php
# Buy page = the PRODUCT page (Buy Now button lives there). /downloader is the
# download/landing page — sending buyers there was a dead end (no Buy button).
BUY_URL     = "https://zhmotions.com/shop.php?p=3"
LIC_FILE    = Path.home() / ".config" / "zhdownloader" / "license.json"
GRACE_DAYS  = 14
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")   # Cloudflare blocks bot UAs

def _device_id():
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["ioreg","-rd1","-c","IOPlatformExpertDevice"],
                                 capture_output=True, text=True).stdout
            import re as _re
            m = _re.search(r'IOPlatformUUID" = "([^"]+)"', out)
            uid = m.group(1) if m else "unknown"
        else:
            # Windows: read the registry MachineGuid (stable per install, present on every Windows).
            # wmic was REMOVED in Windows 11 24H2 / recent Win10 → the old `wmic csproduct get UUID`
            # returned nothing → device_id collapsed to "unknown" for EVERY modern Windows user, so the
            # Pro key's device binding collided across machines. registry has no such dependency.
            uid = "unknown"
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as _k:
                    uid = winreg.QueryValueEx(_k, "MachineGuid")[0] or "unknown"
            except Exception:
                try:   # last resort: CIM via PowerShell (wmic replacement)
                    out = subprocess.run(["powershell","-NoProfile","-Command",
                                          "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                                         capture_output=True, text=True,
                                         creationflags=0x08000000).stdout
                    uid = out.strip() or "unknown"
                except Exception:
                    uid = "unknown"
    except Exception:
        uid = "unknown"
    import hashlib as _h
    return _h.sha256(uid.encode()).hexdigest()[:16]

def license_verify(key):
    """Return (ok|None, plan). None = couldn't reach server."""
    try:
        import urllib.request, urllib.parse
        body = urllib.parse.urlencode({"key":key,"app":"downloader",
                                       "device":_device_id(),"v":APP_VER}).encode()
        req = urllib.request.Request(LICENSE_URL, data=body, headers={
            "User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"})
        d = json.loads(urllib.request.urlopen(req, timeout=20, context=SSL_CTX).read().decode())
        return bool(d.get("valid")), (d.get("plan") or "pro"), (d.get("message") or "")
    except Exception as e:
        return None, None, str(e)

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

# Folder-organize by SITE (user request: "YouTube-er jonno YouTube folder, Artgrid alada").
# The old extension-based categorize() put EVERY video in Video/ — and at download start the
# name often has no extension yet, so YouTube videos landed in "Other".
SITE_FOLDERS = (
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"), ("googlevideo", "YouTube"),
    ("facebook.com", "Facebook"), ("fb.watch", "Facebook"), ("fbcdn", "Facebook"),
    ("instagram.com", "Instagram"), ("cdninstagram", "Instagram"),
    ("tiktok.com", "TikTok"),
    ("x.com", "Twitter"), ("twitter.com", "Twitter"), ("twimg", "Twitter"),
    ("pinterest", "Pinterest"), ("pin.it", "Pinterest"), ("pinimg", "Pinterest"),
    ("artgrid", "Artgrid"), ("artlist", "Artlist"),
    ("vimeo", "Vimeo"), ("dailymotion", "Dailymotion"),
    ("drive.google.com", "GoogleDrive"), ("dropbox.com", "Dropbox"), ("mega.nz", "Mega"),
)
def site_folder(url, referer=""):
    """Folder name for a download: known site → its name; else the domain (Capitalized); else Other.
    Sniffed CDN streams carry no site in the URL — the page referer identifies them."""
    blob = f"{url} {referer}".lower()
    for key, name in SITE_FOLDERS:
        if key in blob: return name
    for src in (url, referer):
        try:
            host = urllib.parse.urlparse(src).netloc.lower().replace("www.", "")
            parts = [p for p in host.split(".") if p]
            if len(parts) >= 2 and not re.fullmatch(r"[\d.]+", host):
                return parts[-2].capitalize()
        except Exception:
            pass
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

# Hide ffmpeg subprocess console window on Windows
# (CREATE_NO_WINDOW = 0x08000000, applied to creationflags)
_SUBPROCESS_HIDE = {"creationflags": 0x08000000} if platform.system() == "Windows" else {}

def find_ff():
    """Locate ffmpeg binary. Bundled first (PyInstaller), then PATH,
    then common install locations. Logs to stderr for debugging."""
    candidates = []

    # 1. PyInstaller bundle (_MEIPASS for onefile)
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates += [meipass/"ffmpeg.exe", meipass/"ffmpeg",
                       meipass/"bin"/"ffmpeg.exe", meipass/"bin"/"ffmpeg"]

    # 2. Executable directory (next to .exe / .app)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # macOS .app: PyInstaller puts bundled binaries in Contents/Frameworks; also check
        # Contents/MacOS and Contents/Resources. (Frameworks was missing -> ffmpeg "not found"
        # on machines without a system ffmpeg, breaking HLS/Artgrid and merged YouTube video.)
        candidates += [exe_dir/"ffmpeg.exe", exe_dir/"ffmpeg",
                       exe_dir/"bin"/"ffmpeg.exe", exe_dir/"bin"/"ffmpeg",
                       exe_dir.parent/"Frameworks"/"ffmpeg",
                       exe_dir.parent/"Frameworks"/"ffmpeg.exe",
                       exe_dir.parent/"Resources"/"ffmpeg",
                       exe_dir.parent/"Resources"/"ffmpeg.exe"]

    # 3. PATH (system-installed)
    p = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if p and Path(p).exists():
        candidates.insert(0, Path(p))  # prefer bundle, but system OK

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
            Path.home()/"scoop"/"apps"/"ffmpeg"/"current"/"bin"/"ffmpeg.exe",
        ]

    for c in candidates:
        try:
            if c.exists() and c.is_file():
                print(f"[find_ff] using: {c}", file=sys.stderr)
                return str(c)
        except Exception: pass
    print(f"[find_ff] NOT FOUND. Searched: {[str(c) for c in candidates]}", file=sys.stderr)
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
# Prefer high res first (4K→1440→1080→720), but ALWAYS end with
# "bestvideo+bestaudio/best" so we never hard-error on a video the site simply
# doesn't offer in that resolution. Two things this final fallback fixes:
#   1. Sites whose streams are video-only + a SEPARATE audio track and expose NO
#      muxed format (Pinterest/most HLS): plain "best" wants one combined file
#      and fails with "Requested format is not available" — "bestvideo+bestaudio"
#      merges the two so it works.
#   2. A clip whose max is < the requested tier (e.g. a 880p Pinterest video with
#      4K selected): instead of erroring, gracefully take the best available.
_TAIL = "/bestvideo+bestaudio/best"
_4K = (
    # "bestvideo[height>=2160]" already resolves to the single highest stream at
    # or above 2160 — so 4320p (8K) is picked automatically when the source has
    # it. The explicit >=4320 clause just documents/guarantees 8K-first.
    "bestvideo[height>=4320]+bestaudio/"
    "bestvideo[height>=2160][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height>=2160]+bestaudio/"
    "bestvideo[height>=1440][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height>=1440]+bestaudio/"
    "bestvideo[height>=1080]+bestaudio"
    + _TAIL
)
_HD = (
    # <=1080, NOT >=: "bestvideo[height>=1080]" means "best stream at or above
    # 1080" — on a 4K video that IS the 2160p stream, so picking HD still
    # downloaded 4K. <=1080 caps it; bestvideo then takes the max under the cap
    # (1080 if offered, else 720 etc.), and _TAIL still rescues tiny videos.
    "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[height<=1080]+bestaudio"
    + _TAIL
)

FMTS = {
    "4k":      {"label":"4K / 8K (max)", "fmt":_4K, "merge":"mp4", "fb":"best", "pp_compat":True},
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
        self.fk      = None    # per-item quality; None = pool default (self._fk)
        self.stop_ev   = threading.Event()  # per-item stop — pause/cancel ONE row, not the pool
        self.stop_mode = ""                 # "pause" | "cancel" when stop_ev fires
        self.tok       = 0                  # worker generation — a resume bumps it so a stale
                                            # worker (still blocked on the pool slot from BEFORE
                                            # the pause) exits instead of double-downloading
        self.pct     = 0.0
        self.speed_v = 0
        self.eta_v   = None
        self.size_v  = 0
        self.done_f  = ""
        self.dl_files = set()  # every basename yt-dlp touched for THIS item — cleanup
                               # deletes ONLY these (folder-wide sweep killed other
                               # live jobs' .part files under concurrent downloads)
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
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
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
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
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
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
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
    def _origin_ok(self):
        """Only the browser extension may trigger downloads. The browser sets
        Origin itself (a web page cannot forge it), so we block any real website
        (http/https origin) and allow extension origins or no-origin (cli)."""
        o = (self.headers.get("Origin") or "").lower()
        return not (o.startswith("http://") or o.startswith("https://"))
    def _c(self):
        o = self.headers.get("Origin") or ""
        # echo extension origin back (so it can read the reply); never wildcard a site
        self.send_header("Access-Control-Allow-Origin", o if o.startswith(("chrome-extension://","moz-extension://")) else "null")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
    def do_OPTIONS(self):
        self.send_response(204); self._c(); self.end_headers()
    def do_GET(self):
        if self.path=="/ping":
            # The extension's popup pings constantly — THAT is detection. It
            # used to be marked only on the first actual send, so the app's
            # dialog said "Not detected" even with the extension connected.
            o = self.headers.get("Origin", "") or ""
            if o.startswith(("chrome-extension://", "moz-extension://", "safari-web-extension://")):
                try: type(self).app._ext_seen = True
                except Exception: pass
            self.send_response(200); self._c()
            self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"app":APP_NAME,"version":APP_VER,"ok":True}).encode())
        elif self.path=="/show":
            # A second launch (double-click / zhdownloader:// deep link) asks the running instance to
            # come to the front, then exits — instead of killing it (which aborted live downloads).
            try: type(self).app._mq.put(("basket_show", None))
            except Exception: pass
            self.send_response(200); self._c()
            self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404); self._c(); self.end_headers()
    def do_POST(self):
        if self.path!="/download":
            self.send_response(404); self._c(); self.end_headers(); return
        if not self._origin_ok():                       # block websites
            self.send_response(403); self._c(); self.end_headers()
            self.wfile.write(b'{"ok":false,"err":"forbidden"}'); return
        try:
            n = int(self.headers.get("Content-Length","0"))
            d = json.loads(self.rfile.read(n) or b"{}")
        except: d={}
        url     = (d.get("url")     or "").strip()
        referer = (d.get("referer") or "").strip()
        fmt     = (d.get("fmt")     or "").strip()   # optional quality from the video overlay
        title   = (d.get("title")   or "").strip()   # page title — names sniffed raw streams
        if not url:
            self.send_response(400); self._c(); self.end_headers()
            self.wfile.write(b'{"ok":false}'); return
        # Real ACK for the extension: report duplicate vs queued so the pill can
        # say "Already added" instead of a blind "Sent". (Same tokenless key the
        # app's dedup uses; read-only peek — _recv_ext still enforces.)
        status = "queued"
        try:
            k = self.app._dedup_key(url)
            if (time.time() - self.app._recent_sends.get(k, 0)) < 90:
                status = "duplicate"
        except Exception:
            pass
        self.app._mq.put(("ext_url", (url, referer, fmt, title)))
        self.send_response(200); self._c()
        self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "status": status}).encode())

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
            "autostart":True,
        })
        # Apply theme
        self.set_theme(self.cfg.get("theme","Light"), refresh=False)
        self.state     = jload(STATE_PATH,{"queue":[]})
        self.history   = HistoryStore()
        self.stats     = StatsStore()
        self.lic       = {"key":"", "plan":"free", "valid":False, "checked":0}
        self._load_license()
        self._mq       = Q.Queue()
        self._stop     = threading.Event()
        self._paused   = False
        self._workers  = []
        self._items    = []
        self._done_files = []
        self._clip_last  = ""
        self._clip_on    = tk.BooleanVar(value=self.cfg.get("clip",True))
        # Premiere-ready MP4 = transcode to H.264/AAC after download. OFF = keep
        # the original codec (VP9/AV1 4K finishes instantly — no transcode wait).
        self._premiere_on = tk.BooleanVar(value=self.cfg.get("premiere",True))
        self._spd_history = []
        self._sched_time  = None
        self._sched_timer = None
        self._referers    = {}
        self._ext_titles  = {}   # url -> page title hint from the browser extension
        self._recent_sends = {}  # dedup-key -> ts of last bridge send (repeat-click guard)
        self.ff           = find_ff()
        self._row_widgets = {}   # item.id -> dict of widget refs

        root.title(f"{APP_NAME} v{APP_VER}")
        # Bump Tk font scaling ~25% — on a retina display Tk renders true point sizes, which looked
        # small next to the old non-retina build. Multiply the current scaling so it stays sensible
        # on both retina and non-retina screens.
        try:
            _sc = float(root.tk.call("tk", "scaling"))
            root.tk.call("tk", "scaling", _sc * 1.25)
        except Exception: pass
        root.geometry("1200x860")
        root.minsize(940,660)
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
        self.root.after(600, self._restore_basket_if_on)
        self._setup_tray()
        # Background update check (10s after startup, once per session)
        root.after(10000, self._check_for_updates_async)
        root.after(2000, self._reverify_license)   # refresh Pro status online
        # HARD license gate — key-only app, no free tier. Shown once the main
        # window is up; blocks everything until a key activates.
        root.after(800, lambda: (None if self._licensed() else self._license_gate()))
        # Apply autostart preference (idempotent — won't duplicate entry)
        if self.cfg.get("autostart", True):
            root.after(3000, lambda: self._apply_autostart(True))

        # First launch after install: offer the browser extension once (button opens
        # the Chrome Web Store via zhmotions.com/extension). Never repeats.
        if not self.cfg.get("ext_prompted"):
            self.cfg["ext_prompted"] = True
            jsave(CFG_PATH, self.cfg)
            root.after(4500, self._ext_first_run)

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
        tk.Label(tx, text=f"v{APP_VER}  ·  by ZH Motions",
                 bg=T["HEADER"], fg=T["MUTED"], font=("Helvetica",9)).pack(anchor="w")
        # Right side info pills
        right = tk.Frame(hi, bg=T["HEADER"]); right.pack(side="right")
        self._pro_btn = tk.Button(right, text=("⭐ Pro ✓" if self.is_pro() else "⭐ Upgrade"),
                                  command=self._open_pro, bd=0, relief="flat", cursor="hand2",
                                  bg=T["HEADER"], fg=T["ACCENT"], activebackground=T["HEADER"],
                                  font=("Helvetica", 10, "bold"))
        self._pro_btn.pack(side="right", padx=(0,12))
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
                self.url_box.drop_target_register(DND_ALL)
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
                    (self.pl_var,"Full Playlist"),(self._clip_on,"Watch clipboard"),
                    (self._premiere_on,"Premiere MP4")]:
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
        ttk.Button(btns, text="◎ Basket", style="Ghost.TButton",
                   command=self._toggle_basket).pack(side="left", padx=(6,0))
        ttk.Button(btns, text="🧩 Extension", style="Ghost.TButton",
                   command=self._ext_dialog).pack(side="left", padx=(6,0))
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
        self.concur_var = tk.IntVar(value=self.cfg.get("concurrent",3))
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
        self._add_setting(body, 3, "Auto-organize into site folders (YouTube / Facebook / Artgrid …)",
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

        # Auto-launch on system startup
        self.auto_var = tk.BooleanVar(value=self.cfg.get("autostart", True))
        self._add_setting(body, 7, "Launch automatically when computer starts",
            lambda r: ttk.Checkbutton(r, variable=self.auto_var,
                command=lambda: (self._save_setting("autostart", self.auto_var.get()),
                                 self._apply_autostart(self.auto_var.get()))))

        # Subtitle languages (used when the Subtitles checkbox is on)
        SUB_LANG_OPTS = ["en,bn", "en", "bn", "hi", "ar", "es", "en,bn,hi", "all"]
        self.slang_var = tk.StringVar(value=str(self.cfg.get("sub_langs", "en,bn")))
        self._add_setting(body, 8, "Subtitle languages (when Subtitles is ticked)",
            lambda r: tk.OptionMenu(r, self.slang_var, *SUB_LANG_OPTS,
                                    command=lambda v: self._save_setting("sub_langs", v)))

        # Software update
        self._add_setting(body, 9, f"Software update (installed: v{APP_VER})",
            lambda r: ttk.Button(r, text="⬇ Check & Update Now", style="Main.TButton",
                                 command=self._update_now))

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

    def _apply_autostart(self, enable):
        """Add/remove app from OS startup. macOS: Login Items via osascript.
        Windows: registry HKCU Run key."""
        try:
            sys_name = platform.system()
            if sys_name == "Darwin":
                # Resolve app path. For .app bundle use the bundle root; for source skip.
                app_path = "/Applications/ZH Downloader.app"
                if not Path(app_path).exists():
                    # Try Applications elsewhere or skip
                    self.log("[autostart] app not in /Applications — skip (run from .pkg install)")
                    return
                name = "ZH Downloader"
                if enable:
                    script = (f'tell application "System Events" to '
                              f'make login item at end with properties '
                              f'{{name:"{name}", path:"{app_path}", hidden:false}}')
                    subprocess.run(["osascript", "-e",
                                    f'tell application "System Events" to '
                                    f'if not (exists login item "{name}") then '
                                    f'{script}'],
                                   capture_output=True, timeout=10)
                    self.log("[autostart] enabled — app will launch on login")
                else:
                    subprocess.run(["osascript", "-e",
                                    f'tell application "System Events" to delete login item "{name}"'],
                                   capture_output=True, timeout=10)
                    self.log("[autostart] disabled")

            elif sys_name == "Windows":
                # Registry HKCU\Software\Microsoft\Windows\CurrentVersion\Run
                exe = sys.executable
                if not getattr(sys, "frozen", False):
                    self.log("[autostart] not running from .exe bundle — skip")
                    return
                try:
                    import winreg
                except ImportError:
                    self.log("[autostart] winreg unavailable")
                    return
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
                try:
                    if enable:
                        winreg.SetValueEx(key, "ZHDownloader", 0, winreg.REG_SZ, f'"{exe}"')
                        self.log("[autostart] enabled (registry Run key)")
                    else:
                        try: winreg.DeleteValue(key, "ZHDownloader")
                        except FileNotFoundError: pass
                        self.log("[autostart] disabled")
                finally:
                    winreg.CloseKey(key)
            else:
                self.log("[autostart] platform not supported")
        except Exception as e:
            self.log(f"[warn] autostart toggle failed: {e}")

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
        # Mirror to a small on-disk log so problems are diagnosable after the
        # fact (the UI pane vanishes with the app). Trimmed at ~500 KB.
        try:
            lp = Path.home() / ".zhdownloader-log.txt"
            if lp.exists() and lp.stat().st_size > 500_000:
                keep = lp.read_text(errors="ignore")[-200_000:]
                lp.write_text(keep)
            with open(lp, "a") as f:
                f.write(time.strftime("%H:%M:%S ") + msg.rstrip() + "\n")
        except Exception:
            pass

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
        # Re-apply each item's REAL status: _build_card renders the default ⏳ icon, so any rebuild
        # (a live-enqueued new download re-lists everything) made FINISHED rows show "waiting" again —
        # and a done item never gets another item_up event to correct it.
        for item in items:
            try: self._update_row(item)
            except Exception: pass

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

        # Right: per-item action menu — ⏸/▶ pauses/resumes THIS row only,
        # ✕ cancels (first click) then removes (second click).
        act = tk.Frame(inner, bg=T["SURF"])
        act.grid(row=0, column=mid_col+2, rowspan=2, padx=(0,6))
        pbtn = ttk.Button(act, text="⏸", style="Ghost.TButton",
                          command=lambda i=item: self._pause_item(i),
                          width=2)
        # Initial state mirrors the item (kept done-rows from the previous run
        # were showing an enabled ⏸ until their first status update).
        if item.status == "paused": pbtn.configure(text="▶")
        elif item.status not in ("waiting", "downloading"): pbtn.configure(state="disabled")
        pbtn.pack(pady=(0,2))
        ttk.Button(act, text="✕", style="Ghost.TButton",
                   command=lambda i=item: self._remove_item(i),
                   width=2).pack()

        self._row_widgets[item.id] = {
            "card":card,"icon":ico,"name":name,"meta":meta,"prog":prog,"thumb":thumb,
            "pbtn":pbtn,
        }
        item.row = card
        item._lbl_icon = ico; item._lbl_name = name; item._lbl_meta = meta; item._prog = prog
        item._btn_pause = pbtn

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
                with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
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

    # ── Per-item pause / resume / cancel ────────────────────────────────
    def _pause_item(self, item):
        if item.status in ("downloading", "waiting"):
            item.stop_mode = "pause"; item.stop_ev.set()
            item.status = "paused" if item.status == "waiting" else item.status
            self._mq.put(("item_up", item))
            self.log(f"[pause] {getattr(item,'name',item.url)[:55]}")
        elif item.status == "paused":
            self._resume_item(item)

    def _resume_item(self, item):
        # Fresh event — the old one stays set for the worker that's still exiting.
        # Bump the generation FIRST: a stale worker from before the pause may still
        # be blocked on the pool slot; without this it wakes to the fresh (unset)
        # stop_ev and downloads the item AGAIN alongside the new worker.
        item.tok = getattr(item, "tok", 0) + 1
        item.stop_ev = threading.Event(); item.stop_mode = ""
        # A previous GLOBAL cancel/pause leaves self._stop set; a solo resume
        # would instantly re-pause off it. Clear it when no pool is running.
        if not self._is_running():
            self._stop.clear(); self._paused = False
        if not hasattr(self, "_out"): self._out = self.cfg.get("dir", DEFAULT_DIR)
        if not hasattr(self, "_fk"):  self._fk  = self.cfg.get("fmt", "4k")
        if getattr(self, "_workers", None) is None: self._workers = []
        item.status = "waiting"
        self._mq.put(("item_up", item))
        # yt-dlp continues the .part file — no bytes lost.
        t = threading.Thread(target=self._runner, args=(item,), daemon=True)
        self._workers.append(t); t.start()
        self.log(f"[resume] {getattr(item,'name',item.url)[:55]}")

    def _remove_item(self, item):
        if item.status in ("downloading", "waiting") and not getattr(item, "_prev_run", False):
            # First ✕ = cancel just this row (worker exits at the next chunk).
            # A second ✕ removes the now-cancelled row.
            item.stop_mode = "cancel"; item.stop_ev.set()
            self.log(f"[cancel] {getattr(item,'name',item.url)[:55]}")
            return
        self._items = [i for i in self._items if i.id != item.id]
        w = self._row_widgets.pop(item.id, None)
        if w and w["card"].winfo_exists(): w["card"].destroy()
        for i, it in enumerate(self._items, 1):
            it.idx = i; it.total = len(self._items)
        # Drop it from the resume queue too, or the next session revives it.
        self.state["queue"] = [q for q in self.state.get("queue", [])
                               if q.get("url") != item.url]
        jsave(STATE_PATH, self.state)

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
        # ⏸ ↔ ▶ follows the row's state; dead rows lose the button.
        pb = getattr(item, "_btn_pause", None)
        if pb:
            try:
                if item.status == "paused":
                    pb.configure(text="▶", state="normal")
                elif item.status in ("waiting", "downloading"):
                    pb.configure(text="⏸", state="normal")
                else:
                    pb.configure(state="disabled")
            except Exception: pass
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
    def _kill_port_holder(self, port):
        """Kill whatever old ZH Downloader instance is squatting on the bridge
        port. Windows MSI upgrades don't close the running app, and autostart
        relaunches old versions — the stale instance kept the port, the new
        app silently ran WITHOUT a bridge, and every extension click died in
        a 'app not running' notification."""
        me = os.getpid()
        try:
            if os.name == "nt":
                out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                     text=True, **_SUBPROCESS_HIDE).stdout
                for ln in out.splitlines():
                    if f":{port}" in ln and "LISTENING" in ln:
                        pid = int(ln.split()[-1])
                        if pid != me:
                            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                           capture_output=True, **_SUBPROCESS_HIDE)
                            self.log(f"[bridge] closed old instance (pid {pid})")
            else:
                out = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                                     capture_output=True, text=True).stdout
                for tok in out.split():
                    pid = int(tok)
                    if pid != me:
                        try:
                            os.kill(pid, 9)
                            self.log(f"[bridge] closed old instance (pid {pid})")
                        except Exception: pass
        except Exception as e:
            self.log(f"[bridge] takeover failed: {e}", "warn")

    def _start_bridge(self):
        Bridge.app = self
        srv = None
        for attempt in (1, 2, 3):
            try:
                srv = ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), Bridge)
                break
            except OSError:
                if attempt == 1:
                    # Who holds the port? A HEALTHY same-version instance means WE are the accidental
                    # duplicate (double-click / zhdownloader:// relaunch) — surface it and exit quietly.
                    # Killing it (the old behaviour) aborted its live downloads. Only a dead/old-version
                    # holder gets killed and taken over (MSI upgrades leave the old app running).
                    try:
                        import urllib.request as _ur
                        d = json.loads(_ur.urlopen(f"http://127.0.0.1:{BRIDGE_PORT}/ping",
                                                   timeout=2).read().decode())
                        if d.get("ok") and d.get("app") == APP_NAME and d.get("version") == APP_VER:
                            try: _ur.urlopen(f"http://127.0.0.1:{BRIDGE_PORT}/show", timeout=2).read()
                            except Exception: pass
                            os._exit(0)   # duplicate launch — the real instance is now in front
                    except Exception:
                        pass
                    self.log("[bridge] port busy — an old ZH Downloader is still running; taking the port over")
                    self._kill_port_holder(BRIDGE_PORT)
                time.sleep(0.7)
        if srv is None:
            self.log("[warn] bridge unavailable — quit the other ZH Downloader (check the system tray) and reopen this app", "warn")
            return
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
                elif kind=="basket_click":
                    self._basket_click()
                elif kind=="basket_drop":
                    self._native_basket_drop(payload)
                elif kind=="basket_show":
                    self._restore_window()
                elif kind=="basket_toggle":
                    self._toggle_basket()
                elif kind=="basket_xy":
                    self._native_basket_save_xy(*payload)
                elif kind=="ext_url":
                    self._recv_ext(payload)
                elif kind=="hist_add":
                    self.history.add(payload)
                    if hasattr(self,"hist_tree"): self._hist_refresh()
                elif kind=="stats_add":
                    self.stats.record(payload)
        except Q.Empty: pass
        self.root.after(80, self._poll)

    def _dedup_key(self, u):
        """Identity for dedup. Raw CDN streams (.m3u8/.mp4/.ts…) carry rotating
        signed tokens in the query → strip it. Page/extractor URLs put the video
        id IN the query (youtube ?v=, facebook ?v=, ?story_fbid=) → KEEP it, else
        every youtube.com/watch collapses to one key and the 2nd video is wrongly
        rejected as 'already added'."""
        base = (u or "").split("#", 1)[0]
        path = base.split("?", 1)[0]
        if re.search(r"\.(m3u8|mpd|mp4|ts|m4s|webm|mov|mkv)$", path, re.I):
            return path
        return base

    def _recv_ext(self, payload):
        """Background receive — no window jump, no bell."""
        fmt = ""; title = ""
        if isinstance(payload, tuple):
            if   len(payload) == 4: url, referer, fmt, title = payload
            elif len(payload) == 3: url, referer, fmt = payload
            else: url, referer = payload
        else:
            url, referer = payload, ""
        self._ext_seen = True
        if not self._licensed():
            self.log("[license] activation key required — download blocked")
            self._restore_window()
            try: self.root.after(0, self._license_gate)
            except Exception: pass
            return
        # Guard: YouTube LIST pages (search results / home / feeds) aren't videos —
        # yt-dlp treats them as "playlist: 0 items" and downloads only a thumbnail.
        try:
            from urllib.parse import urlparse as _upr, parse_qs as _pqs
            _pu = _upr(url)
            if "youtube.com" in _pu.netloc and \
               (_pu.path in ("/", "/results") or _pu.path.startswith("/feed")):
                self.log("[bridge] skipped: that's a YouTube search/home page, not a video — open the video first")
                return
            # X/Twitter: only /status/ pages hold a video; search/home/profile
            # feeds hit yt-dlp's generic extractor and die on "Unsupported URL".
            if _pu.netloc.replace("www.", "") in ("x.com", "twitter.com") and "/status/" not in _pu.path:
                self.log("[bridge] skipped: open the tweet itself (click its timestamp), then send — feeds/search pages have no downloadable video URL")
                return
            # Facebook: watch/reel/videos URLs work; bare feeds/search don't.
            if "facebook.com" in _pu.netloc:
                _ok = ("/videos/" in _pu.path or "/reel" in _pu.path or "/watch" in _pu.path and bool(_pqs(_pu.query).get("v")) or "/share/v/" in _pu.path or "story.php" in _pu.path)
                if not _ok:
                    self.log("[bridge] skipped: open the Facebook video itself (its /watch?v= or /reel/ page), then send")
                    return
        except Exception:
            pass
        # Repeat-send guard. Dedup by URL WITHOUT the query string: Artgrid/CDN
        # stream URLs carry signed tokens that change between sniffs, so the
        # exact-URL check saw "new" URLs and the same clip downloaded again and
        # again — piling up "name (1).mp4 / (2).mp4". Also swallows double-clicks
        # and re-clicks right after a finished run (90s window).
        key = self._dedup_key(url)
        now = time.time()
        self._recent_sends = {k: t for k, t in self._recent_sends.items() if now - t < 90}
        if key in self._recent_sends:
            self.log("[bridge] same video sent moments ago — skipped (wait 90s to re-download)")
            return
        self._recent_sends[key] = now
        # Quality from the overlay menu is ONE-SHOT: apply for this download,
        # then restore the dropdown. It used to stick — one "Audio MP3" pick and
        # every later plain click quietly downloaded mp3 instead of video.
        prev_fmt = None
        if fmt in FMTS:
            prev_fmt = self.fmt_var.get()
            self.fmt_var.set(f"{fmt}: {FMTS[fmt]['label']}")
            self.log(f"[bridge] quality: {FMTS[fmt]['label']} (this download only)")
        if referer: self._referers[url] = referer
        # Page title from the extension — used to name sniffed raw streams
        # (Artlist/Pinterest m3u8) that carry no metadata title of their own.
        if title: self._ext_titles[url] = title
        self.log(f"[bridge] {url[:80]}")
        # Bring the window up so the user SEES the download land. It used to receive silently ("no window
        # jump"), so on Windows a minimised/tray app looked like nothing happened after the extension's
        # "Sent" — the classic "download click → Sent → but app-e ashe na, download hoy na" report.
        self._restore_window()
        if self._is_running() and getattr(self, "_sem", None) is not None:
            # Live-enqueue into the running pool. Do NOT also add to url_box —
            # it is already downloading; re-adding doubles it on the next Start.
            # fmt rides on the item: the pool default used to override it here.
            if self._enqueue_live(url, referer, fmt):
                self.log("[bridge] Added to live queue"
                         + (f" at {FMTS[fmt]['label']}" if fmt in FMTS else ""))
            else:
                self.log("[bridge] Already in queue — skipped")
        else:
            # Not running: download ONLY the clicked URL. Do NOT inherit whatever
            # is sitting in the box — the clipboard watcher (on by default) and
            # leftovers from earlier quietly stage URLs there, and inheriting
            # them re-downloaded old/unrelated videos alongside the clicked one.
            self.url_box.delete("1.0","end")
            self.url_box.insert("1.0", url)
            self.root.update_idletasks()
            self._start()
        # Restore the dropdown after the one-shot override (workers captured
        # their format at start; this only resets the UI default).
        if prev_fmt:
            try: self.fmt_var.set(prev_fmt)
            except Exception: pass

    # -- resume -------------------------------------------------------------
    def _restore_basket_if_on(self):
        if self.cfg.get("basket"):
            try: self._make_basket()
            except Exception: pass

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


    # ── Browser extension helper ─────────────────────────────────────────
    def _ext_first_run(self):
        # Skip if the extension already pinged the bridge (user has it installed).
        if getattr(self, "_ext_seen", False):
            return
        try: self._ext_dialog()
        except Exception: pass

    def _ext_dialog(self):
        w = tk.Toplevel(self.root); w.title("Browser integration")
        w.configure(bg=T["BG"]); w.geometry("520x300"); w.transient(self.root)
        tk.Label(w, text="🧩 Browser extension", bg=T["BG"], fg=T["TEXT"],
                 font=("Helvetica", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(w, text=("The extension adds the ⬇ Download button on top of videos\n"
                          "(IDM style) and catches downloads from the browser."),
                 bg=T["BG"], fg=T["MUTED"], justify="left",
                 font=("Helvetica", 11)).pack(anchor="w", padx=16)
        stat_lbl = tk.Label(w, text="", bg=T["BG"], font=("Helvetica", 11, "bold"))
        stat_lbl.pack(anchor="w", padx=16, pady=(8, 2))
        def _stat_tick():
            if not w.winfo_exists(): return
            seen = getattr(self, "_ext_seen", False)
            stat_lbl.configure(
                text="Status: " + ("✅ Connected" if seen else "○ Not detected yet — open the extension popup once"),
                fg=T["GREEN"] if seen else T["MUTED"])
            w.after(1000, _stat_tick)
        _stat_tick()
        fr = tk.Frame(w, bg=T["BG"]); fr.pack(fill="x", padx=16, pady=(10, 4))
        def open_store():
            webbrowser.open(EXT_STORE_URL or "https://zhmotions.com/downloader#extension")
        ttk.Button(fr, text="Install from Chrome Web Store", style="Main.TButton",
                   command=open_store).pack(side="left")
        def open_manual():
            webbrowser.open("chrome://extensions") if False else webbrowser.open("https://zhmotions.com/downloader#extension")
        tk.Label(w, text=("Manual install (any Chromium browser):\n"
                          "1. Open chrome://extensions   2. Turn on Developer mode\n"
                          "3. \u201cLoad unpacked\u201d \u2192 pick the app\u2019s \u2018extension\u2019 folder"),
                 bg=T["BG"], fg=T["MUTED"], justify="left",
                 font=("Menlo", 10)).pack(anchor="w", padx=16, pady=(12, 0))
        ttk.Button(w, text="Close", style="Ghost.TButton", command=w.destroy).pack(anchor="e", padx=16, pady=12)

    # ── Playlist picker (choose items before downloading) ───────────────
    def _looks_playlist(self, url):
        u = url.lower()
        return any(k in u for k in ("list=", "/playlist", "/channel/", "/@", "/user/",
                                    "/c/", "/sets/", "/album/"))

    def _playlist_flow(self, url, out, fk):
        """Probe playlist entries in a worker thread, then open the picker dialog."""
        self.log("[playlist] Reading playlist…")
        self.btn_dl.configure(state="disabled", text="Reading…")
        def probe():
            entries = []
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                       "extract_flat": "in_playlist", "skip_download": True}) as y:
                    info = y.extract_info(url, download=False)
                for e in (info.get("entries") or []):
                    if not e: continue
                    u = e.get("url") or e.get("webpage_url") or ""
                    if u and not u.startswith("http"):
                        u = f"https://www.youtube.com/watch?v={u}"
                    dur = e.get("duration")
                    entries.append({"title": e.get("title") or u, "url": u,
                                    "dur": f"{int(dur//60)}:{int(dur%60):02d}" if dur else ""})
            except Exception as ex:
                self.log(f"[playlist] probe failed: {ex}", "warn")
            def done():
                self.btn_dl.configure(state="normal", text="↓ Download")
                if not entries:
                    # not really a playlist (or probe failed) → normal single download
                    self._do_start([url], out, fk)
                else:
                    self._playlist_picker(entries, out, fk)
            self.root.after(0, done)
        threading.Thread(target=probe, daemon=True).start()

    def _playlist_picker(self, entries, out, fk):
        w = tk.Toplevel(self.root); w.title(f"Playlist — {len(entries)} items")
        w.configure(bg=T["BG"]); w.geometry("620x520"); w.transient(self.root)
        tk.Label(w, text=f"Select what to download ({len(entries)} items found)",
                 bg=T["BG"], fg=T["TEXT"], font=("Helvetica", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        # scrollable checkbox list
        body = tk.Frame(w, bg=T["BG"]); body.pack(fill="both", expand=True, padx=14)
        cv = tk.Canvas(body, bg=T["BG"], highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=T["BG"])
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        vars_ = []
        for i, e in enumerate(entries):
            v = tk.BooleanVar(value=True); vars_.append(v)
            row = tk.Frame(inner, bg=T["BG"]); row.pack(fill="x", pady=1)
            ttk.Checkbutton(row, variable=v).pack(side="left")
            t = e["title"] if len(e["title"]) <= 68 else e["title"][:65] + "…"
            tk.Label(row, text=f"{i+1:>3}. {t}", bg=T["BG"], fg=T["TEXT"], anchor="w",
                     font=("Helvetica", 11)).pack(side="left", fill="x", expand=True)
            if e["dur"]:
                tk.Label(row, text=e["dur"], bg=T["BG"], fg=T["MUTED"],
                         font=("Menlo", 10)).pack(side="right", padx=(0, 6))
        # footer: select all/none, count, quality, download
        foot = tk.Frame(w, bg=T["BG"]); foot.pack(fill="x", padx=14, pady=10)
        cnt = tk.Label(foot, text="", bg=T["BG"], fg=T["ACCENT"], font=("Helvetica", 10, "bold"))
        def refresh_cnt(*_):
            cnt.config(text=f"{sum(v.get() for v in vars_)} selected")
        for v in vars_: v.trace_add("write", refresh_cnt)
        refresh_cnt()
        def set_all(val):
            for v in vars_: v.set(val)
        ttk.Button(foot, text="All", style="Ghost.TButton", command=lambda: set_all(True)).pack(side="left")
        ttk.Button(foot, text="None", style="Ghost.TButton", command=lambda: set_all(False)).pack(side="left", padx=(6, 10))
        cnt.pack(side="left")
        qv = tk.StringVar(value=f"{fk}: {FMTS[fk]['label']}")
        qm = tk.OptionMenu(foot, qv, *[f"{k}: {v['label']}" for k, v in FMTS.items()])
        self._style_menu(qm); qm.pack(side="left", padx=(14, 0))
        def go():
            picked = [e["url"] for e, v in zip(entries, vars_) if v.get() and e["url"]]
            if not picked:
                messagebox.showwarning(APP_NAME, "Nothing selected."); return
            kf = qv.get().split(":")[0].strip()
            if kf not in FMTS: kf = fk
            if not self.is_pro() and len(picked) > 1:
                self.log(f"[pro] Batch is a Pro feature — downloading 1 of {len(picked)}. ⭐ Upgrade for batch.")
                picked = picked[:1]
            if not self.is_pro() and kf == "4k":
                kf = "hd"; self.log("[pro] 4K is a Pro feature — using 1080p.")
            self.pl_var.set(False)   # entries are direct video URLs — stop re-expansion
            self.url_box.delete("1.0", "end"); self.url_box.insert("1.0", "\n".join(picked))
            w.destroy()
            self._do_start(picked, out, kf)
        ttk.Button(foot, text="↓ Download selected", style="Main.TButton", command=go).pack(side="right")

    # ── Floating drop basket (IDM-style drop target) ─────────────────────
    def _basket_alive(self):
        nb = getattr(self, "_nbasket", None)
        if nb is not None:
            try: return bool(nb.isVisible())
            except Exception: return False
        tb = getattr(self, "_basket", None)
        return bool(tb and tb.winfo_exists())

    def _toggle_basket(self):
        if self._basket_alive():
            nb = getattr(self, "_nbasket", None)
            if nb is not None:
                try: nb.orderOut_(None)
                except Exception: pass
                self._nbasket = None
            tb = getattr(self, "_basket", None)
            if tb and tb.winfo_exists(): tb.destroy()
            self._basket = None
            self.cfg["basket"] = False
        else:
            self._make_basket()
            self.cfg["basket"] = True
        jsave(CFG_PATH, self.cfg)

    def _make_native_basket(self):
        """Real AppKit floating panel (macOS). Tk-free: OS-level drag-drop via
        NSDraggingDestination, clicks via mouseDown — the APIs every native
        app uses. Callbacks hop back into Tk with root.after (same thread:
        Tk and AppKit share the main runloop on macOS)."""
        import objc
        from AppKit import (NSPanel, NSView, NSColor, NSTextField, NSFont,
                            NSBackingStoreBuffered, NSMakeRect,
                            NSFloatingWindowLevel, NSDragOperationCopy,
                            NSWindowStyleMaskBorderless)
        app = self

        if getattr(App, "_ZHDropViewCls", None) is None:
            class _ZHDropView(NSView):
                def initWithFrame_(self, frame):
                    zelf = objc.super(_ZHDropView, self).initWithFrame_(frame)
                    if zelf is None: return None
                    zelf.registerForDraggedTypes_([
                        "public.url", "public.file-url",
                        "public.utf8-plain-text", "NSStringPboardType",
                        "Apple URL pasteboard type"])
                    zelf._moved = False
                    return zelf
                # ── drag destination ──
                def draggingEntered_(self, sender):
                    return NSDragOperationCopy
                def prepareForDragOperation_(self, sender):
                    return True
                def performDragOperation_(self, sender):
                    try:
                        pb = sender.draggingPasteboard()
                        txt = ""
                        for t in ("public.url", "public.file-url",
                                  "public.utf8-plain-text", "NSStringPboardType",
                                  "Apple URL pasteboard type"):
                            v = pb.stringForType_(t)
                            if v: txt = str(v); break
                        if not txt:
                            arr = pb.propertyListForType_("NSURLPboardType")
                            if arr: txt = str(arr[0] if isinstance(arr, (list, tuple)) else arr)
                        app._mq.put(("basket_drop", txt))
                    except Exception:
                        pass
                    return True
                # ── click / drag-to-move ──
                def mouseDown_(self, ev):
                    self._moved = False
                    self._downOrigin = self.window().frame().origin
                    self._downLoc = ev.locationInWindow()
                def mouseDragged_(self, ev):
                    try:
                        w = self.window()
                        sc = ev.locationInWindow()
                        dx = sc.x - self._downLoc.x; dy = sc.y - self._downLoc.y
                        if abs(dx) > 4 or abs(dy) > 4: self._moved = True
                        if self._moved:
                            f = w.frame()
                            w.setFrameOrigin_((f.origin.x + dx, f.origin.y + dy))
                    except Exception: pass
                def mouseUp_(self, ev):
                    try:
                        if ev.clickCount() >= 2:
                            app._mq.put(("basket_show", None)); return
                        if not self._moved:
                            app._mq.put(("basket_click", None))
                        else:
                            f = self.window().frame()
                            app._mq.put(("basket_xy", (int(f.origin.x), int(f.origin.y))))
                    except Exception: pass
                def rightMouseDown_(self, ev):
                    app._mq.put(("basket_toggle", None))
            App._ZHDropViewCls = _ZHDropView

        # panel geometry: cfg stores Tk coords (top-left origin); AppKit is bottom-left
        from AppKit import NSScreen
        scr = NSScreen.mainScreen().frame()
        tx, ty = self.cfg.get("basket_xy", [int(scr.size.width) - 130, 90])
        nx, ny = float(tx), float(scr.size.height - ty - 74)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(nx, ny, 74, 74), NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.83, 0.63, 0.09, 0.95))   # brand gold
        panel.setHasShadow_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        view = App._ZHDropViewCls.alloc().initWithFrame_(NSMakeRect(0, 0, 74, 74))
        lbl = NSTextField.labelWithString_("\u2b07")
        lbl.setFont_(NSFont.boldSystemFontOfSize_(34))
        lbl.setTextColor_(NSColor.blackColor())
        lbl.sizeToFit()
        lf = lbl.frame()
        lbl.setFrameOrigin_(((74 - lf.size.width) / 2, (74 - lf.size.height) / 2))
        view.addSubview_(lbl)
        panel.setContentView_(view)
        panel.orderFrontRegardless()
        self._nbasket = panel
        self._basket = None
        self.log("[basket] native panel ready — drag links onto it or click it")

    def _native_basket_drop(self, txt):
        self.log("[basket] drop received (native)")
        urls = [u for u in URL_RE.findall(txt or "") if not u.startswith(("blob:", "data:"))]
        if not urls:
            self.log("[basket] no URL in drop", "warn"); return
        if sys.platform == "darwin":
            try: subprocess.Popen(["open", "-b", "com.zhmotions.downloader"])
            except Exception: pass
        self._quick_add(urls)

    def _native_basket_save_xy(self, x, y):
        try:
            from AppKit import NSScreen
            sh = NSScreen.mainScreen().frame().size.height
            self.cfg["basket_xy"] = [int(x), int(sh - y - 74)]
            jsave(CFG_PATH, self.cfg)
        except Exception: pass

    def _attach_windows_drop(self, b):
        """Windows: register the basket window as a native OLE drop target
        (RegisterDragDrop — the API every real Windows app uses). tkdnd is
        skipped for the basket here; two registrations on one HWND fail."""
        import pythoncom, win32gui
        from win32com.server import util as com_util

        app = self
        DROPEFFECT_COPY, CF_UNICODETEXT, CF_TEXT = 1, 13, 1

        class _ZHDrop:
            _com_interfaces_ = [pythoncom.IID_IDropTarget]
            _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]
            def DragEnter(self, dataobj, keystate, pt, effect):
                return DROPEFFECT_COPY
            def DragOver(self, keystate, pt, effect):
                return DROPEFFECT_COPY
            def DragLeave(self):
                return None
            def Drop(self, dataobj, keystate, pt, effect):
                txt = ""
                for cf, dec in ((CF_UNICODETEXT, "utf-16-le"), (CF_TEXT, "mbcs")):
                    try:
                        stg = dataobj.GetData((cf, None, 1, -1, 1))  # DVASPECT_CONTENT, TYMED_HGLOBAL
                        raw = stg.data
                        txt = (raw.decode(dec, "ignore") if isinstance(raw, bytes) else str(raw)).split("\x00")[0]
                        if txt.strip(): break
                    except Exception:
                        continue
                app._mq.put(("basket_drop", txt))
                return DROPEFFECT_COPY

        try: pythoncom.OleInitialize()
        except Exception: pass
        hwnd = 0
        try: hwnd = win32gui.GetParent(b.winfo_id()) or b.winfo_id()
        except Exception: hwnd = b.winfo_id()
        pythoncom.RegisterDragDrop(hwnd, com_util.wrap(_ZHDrop(), pythoncom.IID_IDropTarget))
        b._zh_drop_hwnd = hwnd
        b.bind("<Destroy>", lambda e: self._detach_windows_drop(hwnd), add="+")
        self.log("[basket] ready — native Windows drop target registered")

    def _detach_windows_drop(self, hwnd):
        try:
            import pythoncom
            pythoncom.RevokeDragDrop(hwnd)
        except Exception: pass

    def _make_basket(self, plain=None):
        # macOS: NATIVE AppKit panel first — Tk's drag-and-drop (tkdnd) proved
        # completely dead on this OS (registered, mapped, zero events), and
        # borderless Tk windows get no mouse events either. The pyobjc panel
        # uses the same NSDraggingDestination API every real Mac app uses.
        if sys.platform == "darwin" and plain is None:
            try:
                self._make_native_basket()
                return
            except Exception as e:
                self.log(f"[basket] native panel failed ({e}) — using Tk window", "warn")
        # macOS Tk fallback DEFAULTS to the plain titled mini window: field logs proved the
        # styled NSPanel maps and registers ([basket] ready/visible) yet never
        # receives a single mouse event on some systems — visible but dead.
        # A normal titled window is the same class as the main window, which
        # demonstrably gets clicks and drops. The tiny title bar is the price.
        if plain is None:
            plain = (sys.platform == "darwin")
        b = tk.Toplevel(self.root)
        b.withdraw()   # window class/flag changes must land BEFORE the first map
        # REBUILT (was overrideredirect on every platform): on macOS an
        # overrideredirect window renders but often receives NO mouse events —
        # the basket sat there as an unclickable "ghost" and drops fell through.
        # A real NSPanel via MacWindowStyle (floating + noTitleBar) looks the
        # same and actually gets clicks, drags and tkdnd drops. Windows/Linux
        # keep overrideredirect, which behaves fine there.
        # plain=True → last-resort mini window WITH a title bar: nothing exotic,
        # events guaranteed. Auto-chosen when the styled panel fails to map.
        if plain:
            b.title("⬇ ZH")
            try: b.resizable(False, False)
            except Exception: pass
        elif sys.platform == "darwin":
            try:
                b.tk.call("::tk::unsupported::MacWindowStyle", "style", b._w,
                          "floating", "noTitleBar")
            except Exception:
                b.overrideredirect(True)   # ancient Tk fallback
        else:
            b.overrideredirect(True)
        b.attributes("-topmost", True)
        try: b.attributes("-alpha", 0.92)
        except Exception: pass
        # Belt-and-braces: re-assert topmost every 2s (covers Windows focus
        # steals + macOS Spaces switches where even floating panels dip).
        # Single keeper loop — toggling the basket off/on used to stack loops.
        def keep_top():
            if not (getattr(self, "_basket", None) and self._basket.winfo_exists()):
                self._basket_keeper = False
                return
            try:
                self._basket.lift()
                self._basket.attributes("-topmost", True)
            except Exception: pass
            self.root.after(2000, keep_top)
        if not getattr(self, "_basket_keeper", False):
            self._basket_keeper = True
            self.root.after(2000, keep_top)
        sw = b.winfo_screenwidth()
        x, y = self.cfg.get("basket_xy", [sw - 130, 90])
        b.geometry(f"74x74+{int(x)}+{int(y)}")
        b.configure(bg=T["ACCENT"])
        lbl = tk.Label(b, text="⬇", bg=T["ACCENT"], fg="#0a0606", font=("Helvetica", 30, "bold"))
        lbl.pack(fill="both", expand=True)
        # drag to move · CLICK to add a link (clipboard auto-fill) · double-click restore
        def press(e):
            b._off = (e.x, e.y); b._orig = (e.x_root, e.y_root); b._moved = False
            self.log("[basket] press")
        def move(e):
            ox, oy = getattr(b, "_off", (37, 37))
            gx, gy = getattr(b, "_orig", (e.x_root, e.y_root))
            if abs(e.x_root - gx) > 5 or abs(e.y_root - gy) > 5: b._moved = True
            if b._moved:
                b.geometry(f"+{e.x_root - ox}+{e.y_root - oy}")
        def release(_e):
            try:
                geo = b.geometry().split("+")
                self.cfg["basket_xy"] = [int(geo[1]), int(geo[2])]; jsave(CFG_PATH, self.cfg)
            except Exception: pass
            # Plain click (no drag): open the add popup — the basket was drop-only,
            # and a click did NOTHING, which read as "broken". Delayed past the
            # double-click window so restore-window still works.
            if not getattr(b, "_moved", False):
                b._click_job = self.root.after(280, self._basket_click)
        def dbl(_e):
            job = getattr(b, "_click_job", None)
            if job:
                try: self.root.after_cancel(job)
                except Exception: pass
                b._click_job = None
            self._restore_window()
        # Bind on the TOPLEVEL only: label events reach it through bindtag
        # propagation, so binding both widgets fired every handler TWICE —
        # two stacked popups per click (the top one still blank).
        b.bind("<ButtonPress-1>", press); b.bind("<B1-Motion>", move)
        b.bind("<ButtonRelease-1>", release)
        b.bind("<Double-Button-1>", dbl)
        b.bind("<Button-3>", lambda e: self._toggle_basket())
        b.bind("<Button-2>", lambda e: self._toggle_basket())
        b.deiconify()   # map first — DND must register on a LIVE NSView
        b.lift()
        b.update_idletasks()
        # accept dropped links — AFTER the window is mapped: registering while
        # withdrawn lands on a not-yet-created native view, silently does
        # nothing, and the OS then refuses every drop (drag snaps back).
        if os.name == "nt":
            # tkdnd proved unreliable for the floating basket; use the real
            # OLE drop-target API instead (same story as the Mac NSPanel).
            try:
                self._attach_windows_drop(b)
            except Exception as e:
                self.log(f"[basket] native drop failed ({e}) — falling back to tkdnd", "warn")
                if HAS_DND:
                    try:
                        b.drop_target_register(DND_ALL)
                        b.dnd_bind("<<Drop>>", self._basket_drop)
                    except Exception as e2:
                        self.log(f"[basket] tkdnd register: {e2}", "warn")
        elif HAS_DND:
            def _reg_dnd(_e=None):
                ok = 0
                for tgt in (lbl, b):
                    try:
                        tgt.drop_target_register(DND_ALL)   # '*': URL-only drags don't match text/files types
                        ok += 1
                    except Exception as e:
                        self.log(f"[basket] dnd register ({tgt.winfo_class()}): {e}", "warn")
                try: b.dnd_bind("<<Drop>>", self._basket_drop)   # handler ONCE — lbl's event propagates here
                except Exception: pass
                if ok:
                    self.log("[basket] ready — drop links on the gold box or click it")
                else:
                    self.log("[basket] drag-and-drop unavailable — drop links on the app's URL box instead", "warn")
            _reg_dnd()
            # Native views can be (re)created at map time — register again then,
            # or the OS never learns this window accepts drags.
            b.bind("<Map>", _reg_dnd, add="+")
        self._basket = b
        # Self-check: on some macOS/Tk combos the styled panel never maps or
        # never receives events. If it isn't viewable shortly after deiconify,
        # rebuild once as a plain titled mini window (boring but bulletproof).
        if not plain:
            def _verify_visible():
                try:
                    if not (b.winfo_exists() and b.winfo_viewable()):
                        self.log("[basket] styled panel failed to map — using mini window instead", "warn")
                        try: b.destroy()
                        except Exception: pass
                        self._make_basket(plain=True)
                    else:
                        self.log(f"[basket] visible ({b.geometry()})")
                except Exception: pass
            self.root.after(700, _verify_visible)

    def _basket_click(self):
        # Click path into the same add popup the drop uses — works even where
        # drag-and-drop onto the floating panel isn't delivered by the OS.
        self.log("[basket] click")
        # The click usually lands while ANOTHER app is frontmost. On macOS a
        # background Tk app's new window opens BEHIND the frontmost app and
        # focus_force is ignored (focus-stealing protection) — the popup existed
        # but the user never saw it. Activating our own bundle first brings the
        # popup to the real front. No permissions needed for self-activation.
        if sys.platform == "darwin":
            try: subprocess.Popen(["open", "-b", "com.zhmotions.downloader"])
            except Exception: pass
        url = ""
        try:
            clip = self.root.clipboard_get().strip()
            if URL_RE.match(clip): url = clip
        except Exception: pass
        self._quick_add([url] if url else [])

    def _basket_drop(self, event):
        self.log("[basket] drop received")
        if sys.platform == "darwin":
            try: subprocess.Popen(["open", "-b", "com.zhmotions.downloader"])
            except Exception: pass
        raw = (event.data or "").replace("{", " ").replace("}", " ")
        urls = [u for u in URL_RE.findall(raw) if not u.startswith(("blob:", "data:"))]
        if not urls:
            self.log("[basket] no URL in drop", "warn"); return
        # DEFER the popup out of the tkdnd callback. Building a Toplevel inside
        # the <<Drop>> handler kept the drag transaction open — the browser's
        # drag never completed and the popup sat behind it as an unclickable
        # "ghost". Return first so the drop finishes, then open the popup.
        self.root.after(30, lambda u=urls: self._quick_add(u))
        return "copy"

    # ── IDM-style quick-add popup ────────────────────────────────────────
    def _quick_add(self, urls):
        # Singleton: a second basket click/drop REFRESHES the open popup with
        # the new link instead of stacking another window (the old one kept
        # showing the first link forever).
        qa = getattr(self, "_qa", None)
        if qa and qa.get("win") is not None:
            try:
                if qa["win"].winfo_exists():
                    if urls and urls[0]:
                        qa["uvar"].set(urls[0])
                    qa["win"].lift(); qa["win"].focus_force()
                    self.log("[basket] popup refreshed with the new link")
                    return
            except Exception:
                pass
        self.log("[basket] add popup opening")
        w = tk.Toplevel(self.root); w.title("Add download")
        w.withdraw()   # build everything FIRST — mapping an empty toplevel painted a white box
        w.configure(bg=T["BG"]); w.attributes("-topmost", True)
        # Open NEXT TO the basket (that's where the user's eyes/mouse are),
        # clamped on-screen; fall back to center when the basket is off.
        geo = "460x250"
        try:
            bk = getattr(self, "_basket", None)
            if bk and bk.winfo_exists():
                sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
                x = min(max(bk.winfo_x() - 470, 8), sw - 470)
                y = min(max(bk.winfo_y(), 8), sh - 280)
                geo = f"460x250+{x}+{y}"
        except Exception: pass
        w.geometry(geo)
        # Force it to the front even while the browser still owns focus after
        # the drag — otherwise it opened BEHIND and looked like nothing happened.
        try:
            w.lift(); w.focus_force()
            w.after(80, lambda: (w.lift(), w.attributes("-topmost", True)))
        except Exception: pass
        first = urls[0] if urls else ""
        tk.Label(w, text="New download", bg=T["BG"], fg=T["TEXT"],
                 font=("Helvetica", 13, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        # Editable URL row — basket CLICK opens this popup with the clipboard URL
        # (or empty, ready to paste); drops land with the URL already filled.
        uvar = tk.StringVar(value=first)
        ue = tk.Entry(w, textvariable=uvar, font=("Menlo", 10),
                      bg=T["SURF"], fg=T["TEXT"], insertbackground=T["TEXT"],
                      relief="flat", highlightthickness=1,
                      highlightbackground=T["BORDER"], highlightcolor=T["ACCENT"])
        ue.pack(fill="x", padx=16, ipady=5)
        if not first:
            ue.focus_set()
        ue.bind("<Return>", lambda e: dl_now())
        if len(urls) > 1:
            tk.Label(w, text=f"+{len(urls)-1} more link(s) from the drop", bg=T["BG"],
                     fg=T["MUTED"], font=("Helvetica", 9)).pack(anchor="w", padx=16)
        def _final_urls():
            u = [x for x in ([uvar.get().strip()] + list(urls[1:])) if URL_RE.match(x or "")]
            seen = set(); return [x for x in u if not (x in seen or seen.add(x))]
        row = tk.Frame(w, bg=T["BG"]); row.pack(fill="x", padx=16, pady=(12, 4))
        self._lbl(row, "Quality").pack(side="left", padx=(0, 6))
        cur = self.fmt_var.get().split(":")[0].strip()
        if cur not in FMTS: cur = "hd"
        qv = tk.StringVar(value=f"{cur}: {FMTS[cur]['label']}")
        qm = tk.OptionMenu(row, qv, *[f"{k}: {v['label']}" for k, v in FMTS.items()])
        self._style_menu(qm); qm.configure(width=18); qm.pack(side="left")
        sv = tk.BooleanVar(value=self.sub_var.get())
        ttk.Checkbutton(row, text="Subtitles", variable=sv).pack(side="left", padx=(14, 0))
        btns = tk.Frame(w, bg=T["BG"]); btns.pack(fill="x", padx=16, pady=(14, 12))
        def apply_common():
            final = _final_urls()
            if not final:
                messagebox.showwarning(APP_NAME, "Paste a valid link first.", parent=w)
                return False
            self.fmt_var.set(qv.get()); self.sub_var.set(sv.get())
            cur_txt = self.url_box.get("1.0", "end").strip()
            merged = (cur_txt + "\n" if cur_txt else "") + "\n".join(final)
            self.url_box.delete("1.0", "end"); self.url_box.insert("1.0", merged)
            return True
        def dl_now():
            prev = self.fmt_var.get()
            if not apply_common(): return
            w.destroy()
            self._restore_window()
            self._start()
            # One-shot: the picker's quality applies to THIS add only. Leaving it
            # in the dropdown is the old sticky-mp3 trap — one Audio pick and every
            # later plain click quietly downloaded mp3. _start also persisted the
            # picker quality into cfg["fmt"], so restore that too or the next app
            # launch (and the next plain click) comes back as the picked format.
            if qv.get() != prev:
                try:
                    self.fmt_var.set(prev)
                    pk = prev.split(":")[0].strip()
                    if pk in FMTS:
                        self.cfg["fmt"] = pk; jsave(CFG_PATH, self.cfg)
                except Exception: pass
        def queue_only():
            if not apply_common(): return
            w.destroy()
            self.log("[basket] link(s) added to the box — press Download when ready.")
        ttk.Button(btns, text="↓ Download now", style="Main.TButton", command=dl_now).pack(side="left")
        ttk.Button(btns, text="Add only", style="Ghost.TButton", command=queue_only).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Cancel", style="Ghost.TButton", command=w.destroy).pack(side="right")
        self._qa = {"win": w, "uvar": uvar}
        w.bind("<Destroy>", lambda e: setattr(self, "_qa", None), add="+")
        w.deiconify()   # fully built — now show, painted in one shot
        try:
            w.lift(); w.focus_force(); w.update_idletasks()
        except Exception: pass

    # ── Licensing (key-only — NO free tier) ─────────────────────────────
    def is_pro(self):
        return self._licensed()

    def _licensed(self):
        """Hard gate: app usable ONLY with an activated key. valid=True comes
        from a server verify; _load_license flips it off when the last check
        is older than GRACE_DAYS (offline grace window)."""
        l = self.lic or {}
        return bool(l.get("key")) and bool(l.get("valid"))

    def _license_gate(self):
        """BLOCKING activation window. Closing it quits the app — there is no
        free mode. Re-shown if the server later reports the key invalid."""
        if self._licensed(): return
        if getattr(self, "_gate_win", None):
            try: self._gate_win.lift(); self._gate_win.focus_force(); return
            except Exception: self._gate_win = None
        T = THEMES.get(self.cfg.get("theme","Light"), THEMES["Light"])
        w = tk.Toplevel(self.root); self._gate_win = w
        w.title("Activate ZH Downloader")
        w.configure(bg=T["BG"]); w.resizable(False, False)
        w.transient(self.root)
        def quit_app():
            try: self.root.destroy()
            finally: os._exit(0)
        w.protocol("WM_DELETE_WINDOW", quit_app)
        tk.Label(w, text="🔑 License required", font=("Helvetica", 18, "bold"),
                 bg=T["BG"], fg=T["TEXT"]).pack(padx=30, pady=(24, 6))
        tk.Label(w, text="ZH Downloader needs an activation key.\nPaste the key from your purchase message to continue.",
                 bg=T["BG"], fg=T["MUTED"], justify="center").pack(padx=30)
        ent = tk.Entry(w, width=34, font=("Menlo", 13), justify="center")
        ent.pack(padx=30, pady=14, ipady=5); ent.focus_set()
        msg = tk.Label(w, text="", bg=T["BG"], fg=T["RED"]); msg.pack()
        btns = tk.Frame(w, bg=T["BG"]); btns.pack(pady=(6, 22))
        def do_activate():
            key = ent.get().strip()
            if not key: msg.config(text="Enter your key first.", fg=T["RED"]); return
            msg.config(text="Checking…", fg=T["MUTED"]); w.update_idletasks()
            def run():
                ok, plan, m = license_verify(key)
                def done():
                    if ok:
                        self.lic.update({"key": key, "valid": True,
                                         "plan": plan or "pro", "checked": time.time()})
                        self._save_license(); self._refresh_pro_badge()
                        self.log("[license] activated ✓")
                        self._gate_win = None
                        try: w.destroy()
                        except Exception: pass
                    elif ok is None:
                        msg.config(text="Can't reach the license server — check your internet.", fg=T["RED"])
                    else:
                        msg.config(text=m or "Invalid key.", fg=T["RED"])
                try: self.root.after(0, done)
                except Exception: pass
            threading.Thread(target=run, daemon=True).start()
        ent.bind("<Return>", lambda e: do_activate())
        tk.Button(btns, text="Activate", command=do_activate).pack(side="left", padx=6)
        tk.Button(btns, text="Buy a key", command=lambda: webbrowser.open(BUY_URL)).pack(side="left", padx=6)
        tk.Button(btns, text="Quit", command=quit_app).pack(side="left", padx=6)
        try:
            w.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - w.winfo_reqwidth()) // 2
            y = self.root.winfo_y() + 160
            w.geometry(f"+{max(0,x)}+{max(0,y)}")
            w.grab_set(); w.lift(); w.focus_force()
            w.attributes("-topmost", True)
        except Exception: pass

    def _load_license(self):
        try:
            d = json.loads(LIC_FILE.read_text())
            self.lic.update(d)
            if self.lic.get("valid") and (time.time() - self.lic.get("checked",0)) > GRACE_DAYS*86400:
                self.lic["valid"] = False
        except Exception:
            pass

    def _save_license(self):
        try:
            LIC_FILE.parent.mkdir(parents=True, exist_ok=True)
            LIC_FILE.write_text(json.dumps(self.lic))
        except Exception:
            pass

    def _reverify_license(self):
        key = self.lic.get("key")
        if not key: return
        def run():
            ok, plan, _ = license_verify(key)
            if ok is None: return
            self.lic.update({"valid":bool(ok), "plan":plan or "free", "checked":time.time()})
            self._save_license()
            try: self.root.after(0, self._refresh_pro_badge)
            except Exception: pass
            if not ok:
                # Server explicitly rejected the key — re-lock the app.
                self.log("[license] key no longer valid — activation required")
                try: self.root.after(0, self._license_gate)
                except Exception: pass
        threading.Thread(target=run, daemon=True).start()

    def _refresh_pro_badge(self):
        if hasattr(self, "_pro_btn"):
            self._pro_btn.configure(text=("⭐ Pro ✓" if self.is_pro() else "⭐ Upgrade"))

    def _open_pro(self):
        win = tk.Toplevel(self.root); win.title("ZH Downloader Pro")
        win.configure(bg=T["BG"]); win.geometry("440x420"); win.resizable(False, False)
        tk.Label(win, text="ZH Downloader Pro", bg=T["BG"], fg=T["ACCENT"],
                 font=("Helvetica", 18, "bold")).pack(anchor="w", padx=18, pady=(16,2))
        status = tk.Label(win, bg=T["BG"], font=("Helvetica", 12, "bold"))
        status.pack(anchor="w", padx=18)
        feats = ("✓  4K / 8K downloads", "✓  Batch & playlists (many URLs at once)",
                 "✓  Scheduler", "✓  Faster concurrent downloads",
                 "✓  HLS / DASH protected streams")
        for f in feats:
            tk.Label(win, text="   "+f, bg=T["BG"], fg=T["TEXT"], anchor="w").pack(fill="x", padx=18)
        tk.Label(win, text="License key", bg=T["BG"], fg=T["TEXT"], anchor="w",
                 font=("Helvetica", 11, "bold")).pack(fill="x", padx=18, pady=(14,2))
        row = tk.Frame(win, bg=T["BG"]); row.pack(fill="x", padx=18)
        entry = tk.Entry(row, font=("Menlo", 12)); entry.pack(side="left", fill="x", expand=True, ipady=4)
        def do_activate():
            key = entry.get().strip()
            if not key: messagebox.showinfo("License","Enter your key."); return
            status.configure(text="Verifying…", fg=T["MUTED"])
            def run():
                ok, plan, msg = license_verify(key)
                def done():
                    if ok is None: messagebox.showwarning("License","Couldn't reach server. Check internet.")
                    elif ok:
                        self.lic.update({"key":key,"valid":True,"plan":plan or "pro","checked":time.time()})
                        self._save_license(); self._refresh_pro_badge(); _set_status()
                        messagebox.showinfo("License","✅ Pro unlocked. Thank you!")
                    else:
                        messagebox.showwarning("License", msg or "Invalid or inactive key.")
                self.root.after(0, done)
            threading.Thread(target=run, daemon=True).start()
        tk.Button(row, text="Activate", command=do_activate).pack(side="right", padx=(8,0))
        def deactivate():
            if not messagebox.askyesno("Deactivate","Remove license from this device?"): return
            self.lic = {"key":"","plan":"free","valid":False,"checked":0}
            try: LIC_FILE.unlink()
            except Exception: pass
            self._save_license(); self._refresh_pro_badge(); _set_status()
        def _set_status():
            if self.is_pro():
                k = self.lic.get("key",""); masked = (k[:9]+"••••-"+k[-4:]) if len(k)>13 else k
                status.configure(text="● PRO active ✓", fg=T["GREEN"])
                entry.delete(0,"end"); entry.insert(0, masked)
            else:
                status.configure(text="○ Free version", fg=T["MUTED"])
        link = tk.Label(win, text="Buy a key → zhmotions.com/shop", bg=T["BG"], fg=T["ACCENT"],
                        cursor="hand2", font=("Helvetica", 11, "underline"))
        link.pack(anchor="w", padx=18, pady=(12,0))
        link.bind("<Button-1>", lambda e: webbrowser.open(BUY_URL))
        tk.Button(win, text="Deactivate", command=deactivate).pack(anchor="w", padx=18, pady=12)
        _set_status()

    def _start(self):
        if not self._licensed():
            self._license_gate(); return
        import datetime
        raw  = self.url_box.get("1.0","end")
        # findall handles newline, space, comma, tab separated URLs (browser drag often inlines them)
        urls = [u for u in URL_RE.findall(raw)
                if not u.startswith("blob:") and not u.startswith("data:")]
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

        # Pool already running (basket "Download now", stray Start): live-enqueue
        # instead of rebuilding. _do_start mid-run orphaned in-flight workers —
        # their rows vanished, self._workers/_sem were replaced, and self._fk
        # flipped under items that were still downloading.
        if self._is_running() and getattr(self, "_sem", None) is not None:
            fk = self.fmt_var.get().split(":")[0].strip()
            if fk not in FMTS: fk = "4k"
            added = sum(1 for u in urls if self._enqueue_live(u, "", fk))
            try: self.url_box.delete("1.0", "end")
            except Exception: pass
            self.log(f"[queue] {added} of {len(urls)} URL(s) joined the running queue at {FMTS[fk]['label']}")
            return

        out = self.folder_var.get().strip() or DEFAULT_DIR
        Path(out).mkdir(parents=True, exist_ok=True)
        fk = self.fmt_var.get().split(":")[0].strip()
        if fk not in FMTS: fk="4k"

        # ── Free / Pro gate ──  Free = 1 URL, up to 1080p, no scheduler.
        if not self.is_pro():
            if len(urls) > 1:
                self.log(f"[pro] Batch is a Pro feature — downloading 1 of {len(urls)}. ⭐ Upgrade for batch.")
                urls = urls[:1]
            if fk == "4k":
                fk = "hd"
                self.fmt_var.set(f"hd: {FMTS['hd']['label']}")
                self.log("[pro] 4K is a Pro feature — using 1080p. ⭐ Upgrade for 4K.")

        self.cfg.update({"dir":out,"fmt":fk,"cookies":self.ck_var.get(),
                         "clip":self._clip_on.get(),
                         "premiere":self._premiere_on.get()})
        jsave(CFG_PATH,self.cfg)

        # Playlist PICKER: one playlist URL + "Full Playlist" on → choose items instead of
        # blindly downloading everything (IDM/4K-Downloader style).
        if len(urls) == 1 and self.pl_var.get() and self._looks_playlist(urls[0]):
            self._playlist_flow(urls[0], out, fk)
            return

        delay = self._get_sched_delay()
        if (not self.is_pro()) and delay and delay > 0:
            self.log("[pro] Scheduler is a Pro feature. ⭐ Upgrade to schedule.")
            messagebox.showinfo("ZH Downloader Pro", "Scheduling is a Pro feature.\nUpgrade in ⭐ Pro to schedule downloads.")
            delay = 0
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
            # IDM-style persistent queue view: finished rows from the previous
            # run stay visible (last 20). They're display-only — workers spawn
            # only for the NEW items (self._run_items).
            kept = [it for it in self._items if it.status == "done"][-20:]
            for it in kept: it._prev_run = True
            new_items = [DL(u, 0, 0, self._referers.get(u,"")) for u in urls]
            self._items = kept + new_items
            for i, it in enumerate(self._items, 1):
                it.idx = i; it.total = len(self._items)
            self._run_items = new_items
            self._build_rows(self._items)
        else:
            # Reset state on existing items (incl. per-item stop flags — a leftover
            # set stop_ev would instantly re-pause the fresh run).
            for it in self._items:
                it.status = "waiting"; it.pct = 0; it.speed_v = 0; it.eta_v = None
                it.stop_ev = threading.Event(); it.stop_mode = ""
                it.tok = getattr(it, "tok", 0) + 1   # orphan any stale blocked worker
                self._mq.put(("item_up", it))
            self._run_items = list(self._items)
        # URLs are now captured as items — clear the box so a later Start /
        # scheduler / bridge add can't re-download the same links.
        try: self.url_box.delete("1.0", "end")
        except Exception: pass
        self.btn_dl.configure(state="disabled", text="Running...")
        self.btn_cancel.configure(state="normal")
        self.btn_pause.configure(state="normal")
        self.res_frame.pack_forget()

        self.state["queue"]=[{"url":u,"dir":out,"fmt":fk} for u in urls]
        jsave(STATE_PATH,self.state)

        # Concurrent worker pool — default 3 for visible parallelism
        # Get concurrent from UI slider if exists, else cfg, default 3
        cfg_val = 3
        if hasattr(self, "concur_var"):
            try: cfg_val = int(self.concur_var.get())
            except Exception: pass
        else:
            cfg_val = int(self.cfg.get("concurrent", 3))
        max_par = max(1, min(MAX_CONCURRENT, cfg_val))
        if not self.is_pro(): max_par = 1   # Free = single concurrent; Pro = parallel
        self.cfg["concurrent"] = max_par
        jsave(CFG_PATH, self.cfg)
        self.log(f"[start] queue={len(getattr(self,'_run_items',self._items))} new, concurrent={max_par}")
        # Store pool state on self so _recv_ext can live-enqueue mid-run
        self._sem = threading.Semaphore(max_par)
        self._pp_sem = threading.Semaphore(1)   # transcodes one-at-a-time (see _runner)
        self._out = out
        self._fk  = fk
        self._workers = []
        self._active_count = 0
        self._active_lock = threading.Lock()

        for item in self._run_items:
            t = threading.Thread(target=self._runner, args=(item,), daemon=True)
            self._workers.append(t); t.start()

        # Watcher polls workers list (includes any live-enqueued late additions).
        # Self-healing: if all threads die but items are still "waiting" (a worker
        # crashed, or a live-enqueue lost its slot), respawn workers for the
        # leftovers instead of leaving the queue frozen. Bounded so a genuinely
        # undownloadable item can't loop forever — after 2 respawns it's errored.
        self._heal_tries = {}
        def watcher():
            while True:
                time.sleep(0.4)
                if any(t.is_alive() for t in self._workers): continue
                time.sleep(0.6)   # grace for late _recv_ext additions
                if any(t.is_alive() for t in self._workers): continue
                if self._stop.is_set(): break
                # Pool idle — rescue any item left mid-flight.
                stragglers = [it for it in self._items
                              if it.status in ("waiting", "downloading")
                              and not getattr(it, "_prev_run", False)]
                if not stragglers: break
                revived = False
                for it in stragglers:
                    n = self._heal_tries.get(id(it), 0)
                    if n >= 2:
                        it.status = "error"
                        self.log(f"[error] gave up on: {getattr(it,'name',it.url)[:60]}")
                        self._mq.put(("item_up", it)); continue
                    self._heal_tries[id(it)] = n + 1
                    it.status = "waiting"; it.pct = 0
                    self._mq.put(("item_up", it))
                    self.log(f"[recover] restarting stuck item: {getattr(it,'name',it.url)[:60]}")
                    t = threading.Thread(target=self._runner, args=(it,), daemon=True)
                    self._workers.append(t); t.start()
                    revived = True
                if not revived: break
            self._sem = None
            self._mq.put(("done", None))
        threading.Thread(target=watcher, daemon=True).start()

    def _runner(self, item):
        # Phase 1: DOWNLOAD (semaphore-limited so YouTube/network isn't hammered).
        # Capture the semaphore locally + null-guard it: the watcher may set
        # self._sem = None right as a late (live-enqueued) worker starts, and
        # `with None:` used to raise AttributeError BEFORE the try — the thread
        # died and the item froze at "waiting" forever (0 active, stuck queue).
        my_tok = getattr(item, "tok", 0)
        sem = self._sem or nullcontext()
        with sem:
            if getattr(item, "tok", 0) != my_tok:
                return   # superseded: item was paused+resumed while this worker waited for a slot
            if self._stop.is_set() or item.stop_ev.is_set():
                m = getattr(item, "stop_mode", "")
                if   m == "pause":  item.status = "paused"
                elif m == "cancel": item.status = "cancelled"
                else: item.status = "paused" if self._paused else "cancelled"
                self._mq.put(("item_up", item)); return
            with self._active_lock:
                self._active_count += 1
                self._mq.put(("concur", (self._active_count, len(self._items))))
            try:
                item.start_t = time.time()
                # Per-item quality (overlay ▾ pick / basket pick) wins over the
                # pool default — self._fk can even change mid-run on a later Start.
                item_fk = getattr(item, "fk", None) or self._fk
                self._run_download_only(item, self._out, item_fk)
            except Exception as e:
                self.log(f"[error] {e}")
                item.status = "error"
                self._mq.put(("item_up", item))
            with self._active_lock:
                self._active_count -= 1
                self._mq.put(("concur", (self._active_count, len(self._items))))
        # Phase 2: POSTPROCESS (slot freed — next download already started).
        # Serialized by its own semaphore: with concurrent=5, five near-together
        # finishes used to kick off five SIMULTANEOUS 4K transcodes — the hw
        # encoder + CPU saturate and every one crawls. One at a time is faster
        # in wall-clock and keeps the machine responsive while downloads flow.
        if item.status not in ("error","paused","cancelled"):
            pp_sem = getattr(self, "_pp_sem", None)
            item_fk = getattr(item, "fk", None) or self._fk
            try:
                if pp_sem is not None:
                    with pp_sem: self._postprocess(item, item_fk)
                else:
                    self._postprocess(item, item_fk)
            except Exception as e: self.log(f"[warn] postprocess: {e}")
        item.end_t = time.time()
        if item.status == "done":
            self._mq.put(("hist_add", item))
            self._mq.put(("stats_add", item))
        self.state["queue"] = [q for q in self.state.get("queue",[])
                                if q.get("url") != item.url]
        jsave(STATE_PATH, self.state)

    def _enqueue_live(self, url, referer="", fmt=""):
        """Add URL to in-flight queue. Spawns worker that uses existing semaphore pool.
        fmt: per-item quality from the overlay ▾ / basket pick — the pool's format
        (self._fk) used to silently win here, so an HD/MP3 click while anything
        was running still downloaded at the pool default (usually 4K)."""
        # Same identity rule as the bridge dedup (raw streams stripped, page URLs
        # kept) so two different YouTube videos aren't treated as one.
        _k = self._dedup_key
        if any(_k(it.url) == _k(url) for it in self._items): return False
        if referer: self._referers[url] = referer
        idx = len(self._items) + 1
        item = DL(url, idx, idx, self._referers.get(url, ""))
        if fmt in FMTS: item.fk = fmt
        self._items.append(item)
        for i, it in enumerate(self._items, 1):
            it.idx = i; it.total = len(self._items)
        self._build_rows(self._items)
        self.state.setdefault("queue", []).append(
            {"url": url, "dir": self._out, "fmt": item.fk or self._fk})
        jsave(STATE_PATH, self.state)
        t = threading.Thread(target=self._runner, args=(item,), daemon=True)
        self._workers.append(t); t.start()
        return True

    def _do_pause(self):
        self._paused=True; self._stop.set()
        self.btn_pause.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        self.status_var.set("Pausing… (finishing current chunk)")   # instant feedback
        self.log("[pause] pausing all active downloads...")

    def _do_cancel(self):
        self._paused=False; self._stop.set()
        self.btn_cancel.configure(state="disabled")
        self.btn_pause.configure(state="disabled")
        self.status_var.set("Cancelling… (stopping downloads)")      # instant feedback
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
        # A modal from a worker thread hangs Tk on macOS (freezes the whole pool).
        # Conflict resolution always runs in a worker → never show the dialog
        # here; fall through to auto-rename.
        if policy == "ask" and threading.current_thread() is not threading.main_thread():
            policy = "rename"
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
    def _run_download_only(self, item, out, fk):
        """Phase 1: yt-dlp download only. Transcode deferred to _postprocess."""
        if self.cfg.get("categorize", False):
            # SITE-based folders (YouTube/, Artgrid/, …) — extension-based categorize() ran before
            # the file existed, so almost everything fell into "Other".
            cat = site_folder(item.url, getattr(item, "referer", "") or "")
            out = str(Path(out) / cat)
            Path(out).mkdir(parents=True, exist_ok=True)
        # Stash out dir on item for postprocess phase
        item._out_dir = out

        url = item.url
        ul = url.lower()
        if self.ck_var.get() == "none" and any(h in ul for h in ("artgrid","artlist","patreon","cms-public.artgrid")):
            self.log("[warn] Artgrid/Artlist/Patreon needs browser login for full quality. Set Cookies dropdown.")

        item.status="downloading"; self._mq.put(("item_up",item))
        self.log(f"\n[{item.idx}/{item.total}] {url[:100]}")

        mode = self.mode_var.get().split(":")[0].strip()
        kind = classify(url) if mode=="auto" else mode

        # Mark this as download-only phase (skip transcode inside _run_video)
        item._skip_transcode = True
        try:
            if kind=="file": self._run_file(url, out, item)
            else:            self._run_video(url, out, fk, item)
        finally:
            item._skip_transcode = False

    def _postprocess(self, item, fk):
        """Phase 2: rename + transcode + cleanup. Runs OUTSIDE semaphore so
        next download can start immediately."""
        if not item.done_f: return
        # Mark transcoding status visually
        item.status = "downloading"  # keep as active to show progress
        self._mq.put(("item_up", item))
        # Rename UUID/manifest filenames to descriptive (already partially done)
        self._rename_if_uuid(item, item.url)
        # Transcode if needed (pp_compat formats)
        if self.ff and FMTS.get(fk,{}).get("pp_compat"):
            self._force_h264_if_needed(item)
        # Cleanup intermediate format files
        self._cleanup_intermediates(item)
        # Mark done
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
            if self._stop.is_set() or item.stop_ev.is_set():
                # DownloadCancelled, NOT DownloadError: the HLS fragment
                # downloader treats a DownloadError from the hook as a fragment
                # failure and RETRIES it forever — pause/cancel never actually
                # stopped m3u8 downloads. DownloadCancelled propagates straight out.
                raise yt_dlp.utils.DownloadCancelled("user_stop")
            for _k in ("filename", "tmpfilename"):
                _fv = d.get(_k)
                if _fv:
                    try: item.dl_files.add(Path(_fv).name)
                    except Exception: pass
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
            if fn:
                try: item.dl_files.add(Path(fn).name)
                except Exception: pass
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
            "subtitleslangs":             ([l.strip() for l in str(self.cfg.get("sub_langs","en,bn")).split(",") if l.strip()]
                                           if self.sub_var.get() else []),
            "writethumbnail":             self.thumb_var.get(),
            "ignoreerrors":               True,
            "js_runtimes":                _js_runtimes_opt(),
            "progress_hooks":             [hook],
            "postprocessor_hooks":        [pp_hook],
            "logger":                     _Log(self),
            "no_warnings":                False,
            "extractor_args":             {
                "youtube": {
                    # android_vr bypasses PoToken/SABR — gives full 4K without
                    # cookies, Node.js, or PoToken provider. Tested working 2025-10+.
                    # tv_simply/tv/mweb as fallback for edge cases.
                    "player_client": ["android_vr", "tv_simply", "tv", "mweb", "default"],
                    "max_comments": ["0"],
                },
            },
            "youtube_include_dash_manifest": True,
            "format_sort":                ["res", "fps", "vcodec:h264", "acodec:aac", "size", "br"],
            # Custom headers ONLY for raw sniffed streams (Artgrid/Artlist m3u8 —
            # their CDNs demand the page Referer). On extractor sites the pinned
            # stale Chrome/122 UA made Facebook serve markup the extractor can't
            # read ("Cannot parse data" even with perfect cookies) — yt-dlp's own
            # per-site UA handling is strictly better there.
            "http_headers": ({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "*/*",
                "Referer": self._referers.get(url, url) or url,
                "Origin":  "/".join(url.split("/")[:3]) if url and url.startswith("http") else "",
            } if re.search(r"\.(m3u8|mpd|mp4|ts|m4s|webm|mov|mkv)(\?|$)", url or "", re.I)
              else {"Accept-Language": "en-US,en;q=0.9"}),
            "geo_bypass":                 True,
            "age_limit":                  99,
            # True = yt-dlp's native HLS downloader. False delegated to ffmpeg,
            # which chokes (exit 234 = EINVAL) when browser cookies are set —
            # the huge -cookies blob is an invalid arg. Native FD also gives
            # .part resume (pause feature) + real progress %.
            "hls_prefer_native":          True,
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
        # YouTube: DON'T pass cookies — kills android_vr/tv_simply which bypass
        # PoToken. yt-dlp skips those clients when cookies set, falls to mweb/tv
        # which need PoToken + n-challenge JS runtime. Result: no formats.
        # Without cookies, android_vr serves 4K directly. For age-gated/private
        # videos that need auth, _run_video has retry-with-cookies logic.
        if is_youtube:
            self.log("[info] YouTube: using android_vr client (no cookies = works without PoToken)")
        else:
            if ck and ck != "none":
                # Sniffed Artgrid/Artlist CDN m3u8 is public — cookies are
                # useless there and only add failure modes (Chrome-locked
                # keychain, ffmpeg arg limits). Skip for those raw streams.
                if any(h in url_l for h in ("cms-public", "footage-hls")):
                    self.log("[info] public CDN stream — browser cookies not needed, skipping")
                else:
                    opts["cookiesfrombrowser"] = (ck,)
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

        def _is_cookie_err(emsg):
            return any(k in emsg for k in (
                "cookies", "cookiesfrombrowser", "could not copy chrome",
                "permission denied", "keyring", "could not find browser",
                "failed to load cookies", "could not copy cookie database",
            ))

        try:
            try:
                _try(opts)
            except yt_dlp.utils.DownloadError as e:
                emsg = str(e).lower()
                if "user_stop" in emsg: raise
                if _is_cookie_err(emsg) and "cookiesfrombrowser" in opts:
                    self.log("[warn] cookie read failed — retrying without cookies")
                    opts2 = dict(opts); opts2.pop("cookiesfrombrowser", None)
                    _try(opts2)
                elif ("cannot parse" in emsg or "login required" in emsg or "log in" in emsg) \
                        and "facebook" in url.lower() and "cookiesfrombrowser" not in opts:
                    # Facebook's markup only parses for logged-in sessions these
                    # days — a cookie-less run dies with "Cannot parse data".
                    self.log("[warn] Facebook needs login cookies — retrying with Chrome cookies (stay logged in to facebook.com in Chrome)")
                    opts2 = dict(opts); opts2["cookiesfrombrowser"] = ("chrome",)
                    _try(opts2)
                else: raise
            except Exception as e:
                # Catch CookieLoadError + other non-DownloadError cookie failures
                emsg = str(e).lower()
                if _is_cookie_err(emsg) and "cookiesfrombrowser" in opts:
                    self.log("[warn] cookie read failed (Chrome may be running — close it) — retrying without cookies")
                    opts2 = dict(opts); opts2.pop("cookiesfrombrowser", None)
                    _try(opts2)
                else: raise
            # Sanity check: if YouTube returned error response (tiny file), bail loudly
            if item.done_f and Path(item.done_f).exists():
                fsize = Path(item.done_f).stat().st_size
                if fsize < 51200:  # <50 KB = error page, not video
                    self.log(f"[error] download too small ({fsize} bytes) — YouTube blocked or sign-in needed")
                    self.log(f"[error] try: set Cookies dropdown → chrome + login YouTube in Chrome")
                    try: Path(item.done_f).unlink()
                    except: pass
                    item.status = "error"
                    self._mq.put(("item_up", item))
                    return
            # ignoreerrors=True means an unsupported/failed URL does NOT raise —
            # yt-dlp just logs and returns. The item then sat at "Waiting"
            # forever and the self-heal watcher pointlessly re-ran the same
            # failing extraction twice before giving up. No file = error, now.
            if not item.done_f and item.status in ("waiting", "downloading") \
               and not self._stop.is_set() and not item.stop_ev.is_set():
                item.status = "error"
                self.log(f"[error] no media found at: {url[:70]} — open the actual video/tweet page and try again")
                self._mq.put(("item_up", item))
                return
            # Skip rename + transcode if running in download-only phase.
            # _postprocess will handle them outside semaphore.
            if getattr(item, "_skip_transcode", False):
                return
            if item.done_f: self._rename_if_uuid(item, url)
            if self.ff and item.done_f and FMTS.get(fk,{}).get("pp_compat"):
                self._force_h264_if_needed(item)
            if item.done_f:
                self._cleanup_intermediates(item)
            if not self._stop.is_set():
                item.status="done"; item.pct=100
                self._mq.put(("item_up",item))
        except yt_dlp.utils.DownloadCancelled:
            # Pause/cancel (hook raises DownloadCancelled — NOT a DownloadError
            # subclass, so it needs its own arm or the generic handler below
            # would mark the row "error").
            m = getattr(item, "stop_mode", "")
            if   m == "pause":  item.status = "paused"
            elif m == "cancel": item.status = "cancelled"
            else: item.status = "paused" if self._paused else "cancelled"
            self._mq.put(("item_up",item))
        except yt_dlp.utils.DownloadError as e:
            if "user_stop" in str(e):
                # Legacy path (older bundled yt-dlp wrapped the cancel).
                m = getattr(item, "stop_mode", "")
                if   m == "pause":  item.status = "paused"
                elif m == "cancel": item.status = "cancelled"
                else: item.status = "paused" if self._paused else "cancelled"
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
                               capture_output=True, text=True, timeout=10, **_SUBPROCESS_HIDE)
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
                               capture_output=True, text=True, timeout=10, **_SUBPROCESS_HIDE)
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
        """Delete THIS item's yt-dlp + transcode intermediates ONLY.
        NEVER folder-wide: with concurrent downloads the old blanket sweep
        deleted another live job's .part mid-download → yt-dlp crashed with
        [Errno 2] No such file. Ownership = basenames captured in item.dl_files
        by the progress/pp hooks, plus the final file's stem."""
        try:
            p = Path(item.done_f)
            if not p.exists(): return
            parent = p.parent
            own = set(getattr(item, "dl_files", ()) or ())
            own.add(p.name)
            stems = {Path(n).stem for n in own} | {p.stem}
            import re as _re
            for f in parent.iterdir():
                if not f.is_file(): continue
                try:
                    if f.resolve() == p.resolve(): continue
                except: pass
                n = f.name
                # ownership check: exact hook-seen basename, or derived from an
                # owned stem (title.f303.mp4 / uuid.mp4.part / title.h264_tmp.mp4)
                if n not in own and not any(n.startswith(s + ".") for s in stems):
                    continue
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

    def _pick_hw_encoder(self):
        """Pick fastest available H.264 encoder. Returns (codec_name, args_list).
        Cached to avoid repeated ffmpeg probes."""
        if hasattr(self, "_hw_enc_cache"):
            return self._hw_enc_cache
        # Probe available encoders via ffmpeg -encoders
        encoders_out = ""
        try:
            r = subprocess.run([self.ff, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, timeout=10, **_SUBPROCESS_HIDE)
            encoders_out = (r.stdout or "") + (r.stderr or "")
        except Exception: pass

        # Quality-first hardware encoder preference
        candidates = []
        if platform.system() == "Darwin":
            # Apple VideoToolbox — Apple Silicon hardware encoder
            candidates.append(("h264_videotoolbox", [
                "-profile:v","high","-level","5.1",
                "-b:v","20M","-maxrate","30M","-bufsize","40M",
                "-allow_sw","1",  # fallback to software if HW busy
                "-realtime","0",  # quality over speed
            ]))
        elif platform.system() == "Windows":
            # NVIDIA NVENC first (best)
            candidates.append(("h264_nvenc", [
                "-profile:v","high","-level","5.1",
                "-preset","p5","-tune","hq","-rc","vbr",
                "-cq","19","-b:v","20M","-maxrate","30M",
            ]))
            # Intel QSV
            candidates.append(("h264_qsv", [
                "-profile:v","high","-level","5.1",
                "-preset","slow","-global_quality","19","-look_ahead","1",
            ]))
            # AMD AMF
            candidates.append(("h264_amf", [
                "-profile:v","high","-level","5.1",
                "-quality","quality","-rc","cqp","-qp_i","19","-qp_p","19",
            ]))
        # Software fallback (always available)
        candidates.append(("libx264", [
            "-profile:v","high","-level","5.1",
            "-preset","fast","-crf","18",
        ]))

        for codec, args in candidates:
            if codec in encoders_out:
                self._hw_enc_cache = (codec, args)
                return self._hw_enc_cache
        # Shouldn't happen — libx264 always present
        self._hw_enc_cache = ("libx264", ["-preset","fast","-crf","18"])
        return self._hw_enc_cache

    def _force_h264_if_needed(self, item):
        """Smart: fast remux if already H.264+AAC, else full re-encode.
        Most YouTube/Artgrid files are already h264 → 5s remux vs minutes transcode."""
        # "Premiere MP4" toggle OFF = keep the original codec, finish instantly.
        # (cfg dict read — thread-safe enough; written at Start.)
        if not self.cfg.get("premiere", True):
            self.log("[skip] Premiere MP4 off — keeping original codec (no transcode)")
            return
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

            # Hardware encoder = 5-10x faster than software libx264.
            # macOS: VideoToolbox (Apple Silicon hw accel)
            # Windows: NVENC (NVIDIA) > QSV (Intel) > AMF (AMD) > libx264
            hw_encoder, hw_args = self._pick_hw_encoder()
            self.log(f"[transcode] {p.name}: {vcodec}/{acodec} → H.264 via {hw_encoder} ({duration:.0f}s)...")
            item.pct = 0
            item.status = "downloading"
            self._mq.put(("status", f"[{item.idx}/{item.total}] Transcoding ({hw_encoder})..."))
            self._mq.put(("item_up", item))

            tmp = p.parent / (p.stem + ".h264_tmp.mp4")
            cmd = [self.ff, "-y",
                   "-progress", "pipe:2", "-nostats",
                   "-fflags","+genpts+igndts",
                   "-i", str(p),
                   "-map","0:v:0?","-map","0:a:0?",
                   # Video encoder (hardware if available, fallback libx264)
                   "-c:v", hw_encoder,
                   *hw_args,
                   "-pix_fmt","yuv420p",
                   # Audio
                   "-c:a","aac","-b:a","320k","-ar","48000","-ac","2",
                   "-af","aresample=async=1000:min_hard_comp=0.100:first_pts=0",
                   # A/V sync
                   "-fps_mode","vfr",
                   "-avoid_negative_ts","make_zero",
                   # Container
                   "-movflags","+faststart","-tag:v","avc1",
                   "-max_muxing_queue_size","1024",
                   str(tmp)]

            # Stream ffmpeg progress (writes to stderr with -progress pipe:2)
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, bufsize=1,
                                    **_SUBPROCESS_HIDE)
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
                                    stderr=subprocess.PIPE, text=True, bufsize=1,
                                    **_SUBPROCESS_HIDE)
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
            # Priority: extension page-title hint > query-string title > referer
            # slug > URL slug. The extension hint is best for sniffed raw streams
            # (Artlist/Pinterest m3u8) whose URL/referer have no readable name.
            ext_title = self._ext_titles.get(url) or self._ext_titles.get(getattr(item, "url", ""), "")
            if ext_title:
                new_name = ext_title
            elif title_q:
                new_name = title_q[0]
            elif slug_pool:
                new_name = max(slug_pool, key=lambda s: (len(s.replace("-"," ").split()), len(s)))
            else:
                return
        except Exception:
            return
        # A title that is itself a FILENAME ("ZHDownloader-macOS.pkg") must lose its extension FIRST —
        # sanitizing turned the dot into a space and the real suffix re-appended: "… pkg.pkg".
        if p.suffix and new_name.lower().endswith(p.suffix.lower()):
            new_name = new_name[: -len(p.suffix)]
        new_name = _re.sub(r"\.[A-Za-z0-9]{2,5}$", "", new_name)
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
                    cancel_fn=lambda: self._stop.is_set() or item.stop_ev.is_set(),
                    rate_limit=rate)
        res = dl.run()
        if item.stop_ev.is_set():
            m = getattr(item, "stop_mode", "")
            item.status = "paused" if m == "pause" else "cancelled"
            self._mq.put(("item_up", item)); return
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
                with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
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
        # Reconcile: the pool has ended, so NOTHING should still read "waiting" or
        # "downloading". If such a row has a real file on disk, it finished but
        # missed its done-flag → mark done; otherwise it truly failed → error.
        # Guarantees the queue never shows a stuck "Waiting" after a run.
        if not self._paused and not self._stop.is_set():
            for it in self._items:
                if getattr(it, "_prev_run", False): continue
                if it.status in ("waiting", "downloading"):
                    f = getattr(it, "done_f", "")
                    if f and Path(f).exists() and Path(f).stat().st_size > 51200:
                        it.status = "done"; it.pct = 100
                    else:
                        it.status = "error"
                    self._mq.put(("item_up", it))
        self._mq.put(("spd",0))
        done = sum(1 for it in self._items if it.status=="done" and not getattr(it,"_prev_run",False))
        err  = sum(1 for it in self._items if it.status=="error" and not getattr(it,"_prev_run",False))
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
        # Keep url_box intact so user can re-reference / re-download. Only clear log.
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
                pystray.MenuItem("➕ Add from clipboard", _safe_cb(self._tray_add_clip)),
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

    def _tray_add_clip(self, icon=None, item=None):
        # Menu-bar path into the same add popup — works even where the floating
        # basket can't receive OS events. Copy a link, pick this menu item.
        self.root.after(0, self._basket_click)

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
            ("",   "Easiest: zhmotions.com/extension → Add to Chrome (Web Store, auto-updates)\n"
                   "Manual:\n"
                   "1. Chrome → chrome://extensions/\n"
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
                   "• Auto-organize: per-site folders (YouTube / Artgrid …)\n"
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

    def _check_for_updates_async(self):
        """Background: check app + yt-dlp updates."""
        threading.Thread(target=self._update_app_check, daemon=True).start()
        threading.Thread(target=self._update_ytdlp_silent, daemon=True).start()

    # ── One-click updater (Settings → "Check & Update Now") ─────────────
    @staticmethod
    def _ver_tuple(v):
        try: return tuple(int(x) for x in re.findall(r"\d+", v)[:4])
        except Exception: return (0,)

    def _update_now(self):
        if getattr(self, "_updating", False):
            messagebox.showinfo(APP_NAME, "An update is already downloading — progress is in the log.")
            return
        self._updating = True
        self._mq.put(("status", "Checking for updates…"))
        self.log("[update] checking latest version…")
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        latest, err = "", ""
        try:
            body = self._http_get(
                "https://api-relay-2.zhmotionspanel.workers.dev/api.php?action=app_version&app=zhdownloader",
                "application/json")
            data = json.loads(body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body))
            latest = str(data.get("version", "")).strip()
        except Exception as e:
            err = str(e)
        # All dialogs on the Tk thread — the button click must always end in
        # something VISIBLE (it used to only write to the log, which reads as
        # "stuck, nothing happened" from the Settings tab).
        def ui():
            if err or not latest:
                self._updating = False
                self._mq.put(("status", ""))
                messagebox.showwarning(APP_NAME, "Couldn't check for updates.\n"
                                       f"{err or 'No version info from the server.'}\n\n"
                                       "Check your internet connection and try again.")
                return
            if self._ver_tuple(latest) <= self._ver_tuple(APP_VER):
                self._updating = False
                self._mq.put(("status", ""))
                self.log(f"[update] you're on the latest version (v{APP_VER}) ✓")
                messagebox.showinfo(APP_NAME, f"You're up to date ✓\n\nZH Downloader v{APP_VER} is the latest version.")
                return
            if messagebox.askyesno(APP_NAME,
                    f"Update available: v{latest}\nYou're on v{APP_VER}\n\n"
                    "Download the installer now? (~100 MB — takes a minute or two)"):
                self._mq.put(("status", f"Downloading v{latest} installer…"))
                threading.Thread(target=self._update_download_worker, args=(latest,), daemon=True).start()
            else:
                self._updating = False
                self._mq.put(("status", ""))
        self.root.after(0, ui)

    def _update_download_worker(self, latest):
        try:
            self.log(f"[update] v{latest} available — downloading installer…")
            if sys.platform == "darwin":
                url, fname = "https://zhmotions.com/downloader/ZHDownloader-macOS.pkg", f"ZHDownloader-{latest}.pkg"
            elif os.name == "nt":
                url, fname = "https://zhmotions.com/downloader/ZHDownloader-Setup.msi", f"ZHDownloader-Setup-{latest}.msi"
            else:
                self.root.after(0, lambda: messagebox.showinfo(APP_NAME,
                    "Auto-install isn't supported on this OS — get it from zhmotions.com/downloader"))
                return
            dest = Path.home() / "Downloads" / fname
            p = subprocess.run(["curl", "-fSL", "--retry", "2", "-m", "600", "-A", _UA,
                                "-o", str(dest), url], capture_output=True, **_SUBPROCESS_HIDE)
            if p.returncode != 0 or not dest.exists() or dest.stat().st_size < 5_000_000:
                try: dest.unlink(missing_ok=True)
                except Exception: pass
                self.log("[update] download failed")
                self.root.after(0, lambda: messagebox.showwarning(APP_NAME,
                    "The download failed.\n\nGet the installer manually from\nzhmotions.com/downloader"))
                return
            mb = dest.stat().st_size // 1048576
            self.log(f"[update] downloaded {dest.name} ({mb} MB) — opening installer")
            def done():
                messagebox.showinfo(APP_NAME,
                    f"Installer downloaded ({mb} MB) ✓\n\n"
                    "It will open now — finish the install, then reopen ZH Downloader.")
                try:
                    if sys.platform == "darwin": subprocess.Popen(["open", str(dest)])
                    else: os.startfile(str(dest))  # noqa — Windows only
                except Exception as e:
                    messagebox.showwarning(APP_NAME, f"Open it from your Downloads folder: {dest.name}\n({e})")
            self.root.after(0, done)
        except Exception as e:
            self.log(f"[update] {e}")
        finally:
            self._updating = False
            self._mq.put(("status", ""))

    def _http_get(self, url, accept="*/*"):
        """GET a URL, returning bytes. Tries curl FIRST.

        Hostinger's lsrecaptcha firewall 403s Python's urllib TLS fingerprint
        (any User-Agent) but lets curl through. curl ships on macOS and on
        Windows 10 1803+, so it's the reliable path. urllib is the fallback for
        hosts where curl is missing (rare) or not firewalled (e.g. GitHub).
        """
        try:
            p = subprocess.run(
                ["curl", "-fsSL", "-m", "12", "-A", _UA, "-H", f"Accept: {accept}", url],
                capture_output=True, **_SUBPROCESS_HIDE)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout
        except Exception:
            pass
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
            return r.read()

    def _update_app_check(self):
        """Check new release. Tries zhmotions.com FIRST (custom server), GitHub as fallback.

        Custom server expected to host JSON at:
          https://www.zhmotions.com/zhdownloader/version.json
        Format:
          {"version": "6.3.6", "download_url": "https://.../ZHDownloader.zip",
           "notes": "release notes here"}
        """
        # Fetch through the Cloudflare Worker relay, NOT zhmotions.com directly.
        # Hostinger's lsrecaptcha firewall intermittently 403s any direct fetch of
        # version.json (blocks Python's urllib TLS fingerprint AND challenges curl).
        # The relay (a Cloudflare Worker) forwards /api.php to the origin server-
        # side, so it never trips the firewall. api.php?action=app_version reads
        # the same zhdownloader/version.json → one source of truth.
        # The old direct "zhmotions.com/zhdownloader/version.json" and shop-html
        # scrape were dropped — both 403 on every launch.
        sources = [
            ("relay-json", "https://api-relay-2.zhmotionspanel.workers.dev/api.php?action=app_version&app=zhdownloader", self._parse_zhm_json, "application/json"),
            ("github",     "https://api.github.com/repos/zhmotions/zhmotionsdownloader/releases/latest", self._parse_gh_json, "application/json"),
        ]
        for name, url, parser, accept in sources:
            try:
                body = self._http_get(url, accept)
                if accept.startswith("application/json"):
                    txt = (body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body)).strip()
                    # Old api.php (no app_version action) answers "ok" for unknown
                    # actions; GitHub rate-limit returns an error page. Neither is
                    # JSON — skip quietly instead of dumping a parse traceback.
                    if not txt or txt[0] not in "{[":
                        self.log(f"[update] {name}: no update info (skipped)")
                        continue
                    data = json.loads(txt)
                else:
                    data = body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body)
                latest, html_url, notes = parser(data)
                if not latest:
                    self.log(f"[update] {name}: empty version field")
                    continue
                def parse(v): return tuple(int(x) for x in v.split(".") if x.isdigit())
                if parse(latest) <= parse(APP_VER):
                    self.log(f"[update] v{APP_VER} is latest ({name}: v{latest})")
                    return
                self.log(f"[update] NEW VERSION v{latest} (you have v{APP_VER}) — source: {name}")
                self.root.after(0, lambda l=latest, u=html_url: self._show_update_prompt(l, u))
                return
            except Exception as e:
                self.log(f"[update] {name} check failed: {e}")
        # No source had newer version info — normal, not an error.
        self.log("[update] no update info available (you're likely on the latest)")

    def _parse_zhm_shop_html(self, html):
        """Scrape product page HTML for version + download URL.

        Looks for these markers (in priority order):
        1. <meta name="zhd-version" content="6.3.6">
        2. <meta name="zhd-download" content="https://...zip">
        3. data-zhd-version="6.3.6" attribute on any tag
        4. Free text pattern like 'Version 6.3.6' or 'v6.3.6'
        5. First <a href> ending in .zip / .pkg / .msi as download URL
        """
        import re as _re
        # Version detection
        version = ""
        m = _re.search(r'<meta\s+name="zhd-version"\s+content="([^"]+)"', html, _re.I)
        if m: version = m.group(1).strip().lstrip("v")
        if not version:
            m = _re.search(r'data-zhd-version=["\']([^"\']+)', html, _re.I)
            if m: version = m.group(1).strip().lstrip("v")
        if not version:
            m = _re.search(r'(?:version\s*[:\s]+|v)(\d+\.\d+\.\d+)', html, _re.I)
            if m: version = m.group(1)
        # Download URL detection
        download = ""
        m = _re.search(r'<meta\s+name="zhd-download"\s+content="([^"]+)"', html, _re.I)
        if m: download = m.group(1).strip()
        if not download:
            m = _re.search(r'href="([^"]+\.(zip|pkg|msi|exe|dmg))"', html, _re.I)
            if m: download = m.group(1).strip()
        return (version, download or "https://zhmotions.com/shop?p=3", "")

    def _parse_zhm_json(self, data):
        return (
            (data.get("version","") or "").lstrip("v").strip(),
            data.get("download_url") or data.get("url") or "https://www.zhmotions.com",
            data.get("notes",""),
        )

    def _parse_gh_json(self, data):
        return (
            (data.get("tag_name","") or "").lstrip("v").strip(),
            data.get("html_url", "https://github.com/zhmotions/zhmotionsdownloader/releases/latest"),
            data.get("body",""),
        )

    def _update_ytdlp_silent(self):
        """Auto-download latest yt-dlp wheel → cache to user dir.
        Picked up on NEXT app launch via sys.path prepend.
        Silent — no UI prompts."""
        try:
            cache = _YTDLP_USER_CACHE
            current_ver = getattr(yt_dlp.version, "__version__", "0")
            # Query PyPI for latest
            req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json",
                headers={"User-Agent": f"ZHDownloader/{APP_VER}"})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
                data = json.loads(r.read())
            latest_ver = data.get("info",{}).get("version","")
            if not latest_ver: return
            # Numeric compare — PyPI zero-pads ("2026.07.04") while installed
            # reports "2026.7.4"; string != re-downloaded the SAME version on
            # every launch. Tuple of ints treats them as equal.
            def _vt(v):
                try: return tuple(int(x) for x in re.findall(r"\d+", v)[:4])
                except Exception: return (0,)
            if _vt(latest_ver) <= _vt(current_ver): return
            # Find wheel URL
            wheel_url = None
            for f in data.get("urls", []):
                if f.get("packagetype") == "bdist_wheel" and "py3-none-any" in f.get("filename",""):
                    wheel_url = f["url"]; break
            if not wheel_url: return
            self.log(f"[update] yt-dlp {current_ver} → {latest_ver} (background)")
            # Download wheel
            tmp = cache.parent / f".ytdlp-{latest_ver}.whl"
            with urllib.request.urlopen(wheel_url, timeout=60, context=SSL_CTX) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            # Extract wheel (.whl is zip) to cache dir
            import zipfile
            cache.mkdir(parents=True, exist_ok=True)
            # Clear old contents
            for child in cache.iterdir():
                if child.is_dir(): shutil.rmtree(child, ignore_errors=True)
                else: child.unlink(missing_ok=True)
            with zipfile.ZipFile(tmp) as z: z.extractall(cache)
            tmp.unlink(missing_ok=True)
            self.log(f"[update] yt-dlp {latest_ver} cached — restart app to activate")
        except Exception as e:
            print(f"[ytdlp-update] {e}", file=sys.stderr)

    def _show_update_prompt(self, new_ver, url):
        """Modal asking user to update. Only one per session."""
        if getattr(self, "_update_prompted", False): return
        self._update_prompted = True
        ans = messagebox.askyesno(
            APP_NAME,
            f"Update available: v{new_ver}\n"
            f"You're on v{APP_VER}\n\n"
            f"Download v{new_ver} now?",
            icon="info"
        )
        if ans:
            self._open_url(url)

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
        tk.Label(box, text="ZH Downloader — by ZH Motions",
                 bg=T["SURF"], fg=T["ACCENT"], font=("Helvetica",11,"bold")).pack(anchor="w")
        tk.Label(box, text="Free desktop app. Only download content you own or are permitted to download.",
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


def _js_runtimes_opt():
    """yt-dlp needs a JavaScript runtime for Facebook/YouTube extraction now.
    Prefer the bundled QuickJS (2 MB, shipped in the app); fall back to any
    system deno/node. Without this, cookie-perfect Facebook runs still died
    with "Cannot parse data" because no runtime was configured at all."""
    rt = {}
    dirs = []
    if hasattr(sys, "_MEIPASS"): dirs.append(Path(sys._MEIPASS))
    if getattr(sys, "frozen", False): dirs.append(Path(sys.executable).parent)
    dirs.append(Path(__file__).resolve().parent / "vendor")
    for d in dirs:
        for n in ("qjs", "qjs.exe", "qjs-darwin"):
            p = d / n
            if p.exists():
                rt["quickjs"] = {"path": str(p)}
                break
        if rt: break
    rt.setdefault("deno", {})
    rt.setdefault("node", {})
    return rt


def _prepend_bundled_bins_to_path():
    """Add PyInstaller bundle dir to PATH so bundled node/ffmpeg/ffprobe
    are findable by yt-dlp + bgutil-pot plugin subprocess calls."""
    bundle_dirs = []
    if hasattr(sys, "_MEIPASS"):
        bundle_dirs.append(str(Path(sys._MEIPASS)))
    if getattr(sys, "frozen", False):
        bundle_dirs.append(str(Path(sys.executable).parent))
    if not bundle_dirs: return
    sep = ";" if platform.system() == "Windows" else ":"
    current = os.environ.get("PATH", "")
    extra = sep.join(d for d in bundle_dirs if d and d not in current)
    if extra:
        os.environ["PATH"] = extra + sep + current

def _register_url_scheme_windows():
    """Register zhdownloader:// in HKCU at startup (Windows). The MSI writes this, but the
    PORTABLE .exe never did — so with the app closed, the extension's zhdownloader:// launch
    silently did nothing and queued downloads never arrived. HKCU needs no admin; re-writing
    also repairs the path after the exe is moved."""
    if os.name != "nt" or not getattr(sys, "frozen", False): return
    try:
        import winreg
        base = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\zhdownloader")
        winreg.SetValueEx(base, None, 0, winreg.REG_SZ, "URL:ZH Downloader Protocol")
        winreg.SetValueEx(base, "URL Protocol", 0, winreg.REG_SZ, "")
        cmd = winreg.CreateKey(base, r"shell\open\command")
        winreg.SetValueEx(cmd, None, 0, winreg.REG_SZ, f'"{sys.executable}" "%1"')
        winreg.CloseKey(cmd); winreg.CloseKey(base)
    except Exception:
        pass

def main():
    """Staged startup so any optional feature failure can't crash app."""
    global HAS_DND

    # Make bundled binaries findable (node for YouTube PoToken, etc)
    _prepend_bundled_bins_to_path()
    _register_url_scheme_windows()

    # Build the root with TkinterDnD directly — it configures tkdnd's package
    # path itself and raises if the native library is missing, so it IS the
    # probe. The old "stage 1" probed with a PLAIN tk.Tk(), whose auto_path
    # never contains tkdnd — `package require tkdnd` failed every time, HAS_DND
    # went False, and drag-and-drop (basket + URL box) was silently disabled in
    # every build even though the library was present and loadable.
    root = None
    if HAS_DND:
        try:
            root = TkinterDnD.Tk()
        except Exception as e:
            print(f"[warn] TkinterDnD.Tk() failed ({e}); drag-drop disabled")
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
