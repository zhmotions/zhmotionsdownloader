#!/usr/bin/env bash
# ZH Downloader — Linux launcher
# Run: bash ZH-Downloader-Linux.sh
# Or make executable: chmod +x ZH-Downloader-Linux.sh && ./ZH-Downloader-Linux.sh

cd "$(dirname "$0")"

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
  echo " [!] Python not found. Install it:"
  echo ""
  echo "     Ubuntu/Debian:  sudo apt install python3 python3-venv python3-tk"
  echo "     Fedora:         sudo dnf install python3 python3-tkinter"
  echo "     Arch:           sudo pacman -S python python-tkinter"
  echo ""
  read -rp " Press Enter after installing Python, then run this script again..."
  exit 1
fi

echo " [OK] Found: $($PY --version 2>&1)"

# Check tkinter
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo ""
  echo " [!] Python tkinter is missing. Install it:"
  echo "     Ubuntu/Debian:  sudo apt install python3-tk"
  echo "     Fedora:         sudo dnf install python3-tkinter"
  echo "     Arch:           sudo pacman -S tk"
  echo ""
  read -rp " Press Enter after installing, then run this script again..."
  exit 1
fi

# ── Step 2: Setup venv ───────────────────────────────────────────
echo ""
echo " [2/4] Checking dependencies..."

if [ ! -d ".venv" ]; then
  echo " [!] First time setup — installing packages (1-2 min)..."
  
  "$PY" -m venv .venv
  if [ $? -ne 0 ]; then
    echo " [ERROR] Could not create virtual environment."
    echo "         Try: sudo apt install python3-venv"
    exit 1
  fi
  
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  
  if [ $? -ne 0 ]; then
    echo " [ERROR] Package installation failed. Check your internet connection."
    exit 1
  fi
  
  echo " [OK] Packages installed!"
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo " [OK] Dependencies ready."
fi

# ── Step 3: Check ffmpeg ─────────────────────────────────────────
echo ""
echo " [3/4] Checking ffmpeg..."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo " [!] ffmpeg not found. Install it:"
  echo "     Ubuntu/Debian:  sudo apt install ffmpeg"
  echo "     Fedora:         sudo dnf install ffmpeg"
  echo "     Arch:           sudo pacman -S ffmpeg"
  echo ""
  echo "     App will still work for basic downloads. Continuing in 5 seconds..."
  sleep 5
else
  echo " [OK] ffmpeg: $(command -v ffmpeg)"
fi

# ── Step 4: Launch ───────────────────────────────────────────────
echo ""
echo " [4/4] Launching ZH Downloader..."
echo ""

python zh_downloader.py

