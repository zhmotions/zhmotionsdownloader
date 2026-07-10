@echo off
title ZH Downloader — Setup
color 0A
cls

echo.
echo  ============================================================
echo    ZH Downloader — by ZH Motions
echo    zhmotions.com
echo  ============================================================
echo.

cd /d "%~dp0"

REM ── Step 1: Check Python ──────────────────────────────────────
echo  [1/4] Checking Python...

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [!] Python is NOT installed on this computer.
  echo.
  echo  Please follow these steps:
  echo    1. Open your browser and go to: https://www.python.org/downloads/
  echo    2. Click the big yellow "Download Python" button
  echo    3. Run the installer
  echo    4. IMPORTANT: Check the box that says "Add Python to PATH"
  echo    5. Click "Install Now"
  echo    6. After install is done, run this file again
  echo.
  echo  ============================================================
  echo   Press any key to open the Python download page...
  echo  ============================================================
  pause >nul
  start "" "https://www.python.org/downloads/"
  exit /b 1
)

REM Get Python version for display
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Found: %PYVER%

REM ── Step 2: Check/Create venv ─────────────────────────────────
echo.
echo  [2/4] Checking dependencies...

if not exist .venv (
  echo  [!] First time setup — installing required packages.
  echo      This only happens ONCE and takes 1-2 minutes.
  echo      Please wait...
  echo.
  
  python -m venv .venv >nul 2>&1
  if errorlevel 1 (
    echo  [ERROR] Could not create virtual environment.
    echo  Try running as Administrator, or reinstall Python.
    pause
    exit /b 1
  )
  
  call .venv\Scripts\activate.bat
  
  echo  Installing packages (yt-dlp)...
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  
  if errorlevel 1 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Check your internet connection and try again.
    pause
    exit /b 1
  )
  
  echo  [OK] All packages installed successfully!
) else (
  call .venv\Scripts\activate.bat
  echo  [OK] Dependencies ready.
)

REM ── Step 3: Check ffmpeg ──────────────────────────────────────
echo.
echo  [3/4] Checking ffmpeg...

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo  [!] ffmpeg not found — audio extraction and HD video merging
  echo      may not work. To fix this:
  echo        Option A: Install via Chocolatey: choco install ffmpeg
  echo        Option B: Download from https://www.gyan.dev/ffmpeg/builds/
  echo                  Extract and add the "bin" folder to your PATH.
  echo.
  echo  App will still work for most downloads. Continuing in 5 seconds...
  timeout /t 5 >nul
) else (
  for /f "tokens=*" %%f in ('where ffmpeg') do set FFPATH=%%f
  echo  [OK] ffmpeg found: %FFPATH%
)

REM ── Step 4: Launch ───────────────────────────────────────────
echo.
echo  [4/4] Launching ZH Downloader...
echo.

REM Use pythonw to launch without a console window
where pythonw >nul 2>&1
if errorlevel 1 (
  start "" python zh_downloader.py
) else (
  start "" pythonw zh_downloader.py
)

echo  App is starting — this window will close in 3 seconds.
timeout /t 3 >nul
exit /b 0
