# ZH Downloader

<p align="center">
  <img src="assets/AppIcon-source.png" width="100" alt="ZH Downloader">
</p>

<p align="center">
  <strong>Universal Download Manager by ZH Motions</strong><br>
  Video · Audio · Any File · 1800+ Sites
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-6.3.4-d4a13a?style=flat-square" alt="version">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-5b1a1f?style=flat-square" alt="platform">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="python">
  <img src="https://github.com/zhmotions/zhmotionsdownloader/actions/workflows/build-win.yml/badge.svg" alt="build">
</p>

---

## Download

| Platform | File | Notes |
|----------|------|-------|
| **Windows** | [ZHDownloader.exe](https://github.com/zhmotions/zhmotionsdownloader/releases/latest) | Double-click to run |
| **macOS** | [ZHDownloader.pkg](https://github.com/zhmotions/zhmotionsdownloader/releases/latest) | Double-click → Continue → Install |
| **macOS** | [ZHDownloader.dmg](https://github.com/zhmotions/zhmotionsdownloader/releases/latest) | Drag to Applications |

> **No Python required.** Just download and run.

---

## Features

- **1800+ sites** — YouTube, Vimeo, Instagram, TikTok, Twitter/X, Facebook, Twitch, SoundCloud, Bilibili and more
- **Concurrent downloads** — configurable 1-5 parallel
- **Drag-drop URLs** — drop links from any browser tab onto the window (v5.1)
- **Tray icon** — minimize to tray, control from menu (v5.1)
- **Card thumbnails** — visual preview for queue items (v5.1)
- **Tabbed UI** — Downloads / History / Stats / Settings
- **6 themes** — Light (default), Cream, Sunset, Midnight, Forest, Mono Dark
- **HD/4K only formats** — no low-res clutter (4K/1080p Premiere + raw + audio)
- **Download history** — persistent across sessions, search + re-download
- **Lifetime statistics** — total files, data, time, peak speed, per-category charts
- **Auto-categorize folders** — Video / Audio / Documents / Archives
- **Speed limiter** — throttle bandwidth (KB/s slider)
- **Conflict resolution** — rename / overwrite / skip / ask per file
- **Site grabber** — extract all media links from any page URL
- **Scheduler** — preset times (30 min / 1h / Tonight 11 PM / Tomorrow)
- **Shutdown after done** — auto-power-off when queue completes
- **Completion sound** — system audio on finish
- **Multi-thread file downloads** — 8 parallel connections per file
- **Resume support** — interrupted downloads continue
- **Browser extension** — one-click send from Chrome/Edge/Brave
- **Clipboard detection** — copy link, auto-add
- **Premiere Pro compat** — force H.264/avc1 transcode for editor import
- **Cookie support** — Chrome/Safari/Firefox/Edge/Brave for auth sites

---

## Installation

### Windows
1. Download `ZHDownloader.exe`
2. Double-click to run
3. Windows may show a security warning — click **More info → Run anyway**

### macOS
1. Download `ZHDownloader.pkg`
2. Double-click → **Continue → Install → Enter password → Done**
3. First launch: right-click the app → **Open → Open** (one-time Gatekeeper bypass)

### Linux
```bash
git clone https://github.com/zhmotions/zhmotionsdownloader.git
cd ZHDownloader-v4
bash ZH-Downloader-Linux.sh
```

---

## Browser Extension

Works with Chrome, Edge, and Brave.

### Install
1. Go to `chrome://extensions/`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder
5. Pin the ZH icon to your toolbar

### Use
- Visit any page with video or files
- Gold badge shows count of detected items
- Click icon → see list → **Save** (direct download) or **App** (send to desktop app)
- **Page** button sends the current page URL to the app for yt-dlp processing

---

## ffmpeg

ffmpeg is needed for merging HD video + audio (1080p, 4K) and audio extraction.

| Platform | Install command |
|----------|----------------|
| macOS | `brew install ffmpeg` |
| Windows | `choco install ffmpeg` |
| Ubuntu | `sudo apt install ffmpeg` |

The pre-built `.exe` and `.pkg` already include ffmpeg — no separate install needed.

---

## Run from source

```bash
# Clone
git clone https://github.com/zhmotions/zhmotionsdownloader.git
cd ZHDownloader-v4

# Windows
ZH-Downloader-Win.bat

# macOS
open ZH-Downloader-Mac.command

# Linux
bash ZH-Downloader-Linux.sh
```

The launcher scripts automatically:
- Check Python is installed
- Create a virtual environment
- Install dependencies
- Launch the app

---

## Build from source

### Windows → .exe
```cmd
build_win.bat
```

### macOS → .dmg + .pkg
```bash
chmod +x build_mac.sh && ./build_mac.sh
```

### GitHub Actions (auto-build)
Push to `main` branch → GitHub automatically builds `.exe` and `.pkg`.
Find files under **Actions → latest run → Artifacts**.

To create a release with all files attached:
```bash
git tag v6.3.4
git push origin v6.3.4
```

---

## Supported Sites

YouTube · Vimeo · Instagram · TikTok · Twitter/X · Facebook · Twitch · SoundCloud · Reddit · Dailymotion · Pinterest · Bilibili · Rumble · Streamable · Patreon · Artgrid · Artlist · and **1800+ more** via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

---

## Notes

- Personal use only. Internal tool for ZH Motions students.
- Respect copyright. Do not redistribute downloaded material commercially without rights.
- Keep yt-dlp updated for best compatibility:
  ```
  pip install --upgrade yt-dlp
  ```

---

<p align="center">
  Made with ♥ by <a href="https://zhmotions.com">ZH Motions</a>
</p>
