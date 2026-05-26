#!/usr/bin/env bash
# ZH Downloader — macOS launcher
# Double-click this file to run.

cd "$(dirname "$0")"

show_dialog() {
  osascript -e "display dialog \"$1\" buttons {\"$2\"} default button \"$2\" with title \"ZH Downloader\" with icon caution" 2>/dev/null
}

show_info() {
  osascript -e "display notification \"$1\" with title \"ZH Downloader\"" 2>/dev/null
}

clear
echo ""
echo " ============================================================"
echo "   ZH Downloader — by ZH Motions"
echo "   zhmotions.com"
echo " ============================================================"
echo ""

# ── Step 1: Check Python ─────────────────────────────────────────
echo " [1/4] Checking Python..."

PY=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo " [!] Python not found."
  show_dialog "Python 3 is not installed.\n\nPlease:\n1. Go to https://www.python.org/downloads/\n2. Download and install Python 3\n3. Run this file again." "Open Download Page"
  open "https://www.python.org/downloads/"
  exit 1
fi

PYVER=$($PY --version 2>&1)
echo " [OK] Found: $PYVER"

# Verify tkinter
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo " [!] Python found but tkinter is missing."
  show_dialog "Your Python installation is missing tkinter (the GUI library).\n\nFix with:\n  brew install python-tk@3.12\n\nOr download Python from python.org (it includes tkinter)." "OK"
  exit 1
fi

# ── Step 2: Setup venv ───────────────────────────────────────────
echo ""
echo " [2/4] Checking dependencies..."

need_install=0
if [ ! -d ".venv" ]; then
  need_install=1
else
  # Re-install if requirements.txt newer than venv marker
  if [ "requirements.txt" -nt ".venv/.installed" ] 2>/dev/null; then
    need_install=1
    echo " [!] requirements.txt updated — refreshing deps"
  fi
fi

if [ "$need_install" = "1" ]; then
  echo " [!] Setup — installing packages (1-3 min, larger first time)..."
  show_info "Setting up ZH Downloader. Please wait..."

  if [ ! -d ".venv" ]; then
    "$PY" -m venv .venv
    if [ $? -ne 0 ]; then
      show_dialog "Could not create Python environment.\nTry reinstalling Python from python.org." "OK"
      exit 1
    fi
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --quiet --upgrade pip
  # Core deps (must succeed)
  pip install --quiet yt-dlp
  if [ $? -ne 0 ]; then
    show_dialog "Failed to install yt-dlp (required).\nCheck your internet connection." "OK"
    exit 1
  fi
  # Optional deps (best effort — app degrades gracefully if any fail)
  pip install --quiet Pillow tkinterdnd2 pystray 2>/dev/null || true
  # macOS tray needs PyObjC
  pip install --quiet "pyobjc-framework-Cocoa>=10.0" "pyobjc-framework-Quartz>=10.0" 2>/dev/null || true
  # YouTube PoToken plugin — needs Node.js
  pip install --quiet "bgutil-ytdlp-pot-provider>=1.1.0" 2>/dev/null || true
  touch .venv/.installed
  echo " [OK] Packages installed!"
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo " [OK] Dependencies ready."
fi

# ── Step 2b: Node.js for YouTube PoToken ─────────────────────────
echo ""
echo " [2b] Checking Node.js (for YouTube downloads)..."
if ! command -v node >/dev/null 2>&1; then
  echo " [!] Node.js missing — YouTube downloads may not work."
  if command -v brew >/dev/null 2>&1; then
    echo "      Installing Node.js via Homebrew (1-2 min)..."
    brew install -q node 2>/dev/null || true
  else
    show_dialog "Node.js missing — YouTube limited.\n\nInstall manually: https://nodejs.org/\n\nApp still works for Vimeo, Artgrid, etc." "Continue Anyway"
  fi
fi
if command -v node >/dev/null 2>&1; then
  echo " [OK] Node.js: $(node --version)"
fi

# ── Step 3: Check ffmpeg ─────────────────────────────────────────
echo ""
echo " [3/4] Checking ffmpeg..."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo " [!] ffmpeg not found — some features may not work."
  show_dialog "ffmpeg is not installed.\n\nTo enable audio extraction and HD video merging, install it:\n\n  brew install ffmpeg\n\n(Open Terminal, paste the command above)\n\nApp will still work for basic downloads. Continuing..." "Continue Anyway"
else
  echo " [OK] ffmpeg: $(command -v ffmpeg)"
fi

# ── Step 4: Launch ───────────────────────────────────────────────
echo ""
echo " [4/4] Launching ZH Downloader..."
echo ""

python zh_downloader.py

