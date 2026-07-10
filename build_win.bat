@echo off
REM Build ZH Downloader .exe + .msi installer for Windows.
REM Usage (PowerShell or cmd): build_win.bat
REM Requires: Python 3.9+ on PATH. Optional: WiX Toolset (for MSI).

setlocal
cd /d "%~dp0"

set APP_NAME=ZHDownloader
set APP_DISPLAY=ZH Downloader
set APP_VERSION=1.1.0
set APP_AUTHOR=ZH Motions
set PY_SCRIPT=zh_downloader.py
set ICON=assets\AppIcon.ico
set VERINFO=assets\version_info.txt

echo ==^> 1/5 Setup virtualenv
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo ==^> 2/5 Install build deps
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

echo ==^> 3/5 Locate ffmpeg
where ffmpeg >nul 2>&1
if %errorlevel%==0 (
  for /f "delims=" %%i in ('where ffmpeg') do set FFMPEG_BIN=%%i
  echo     Using %FFMPEG_BIN%
  set ADD_BINARY=--add-binary "%FFMPEG_BIN%;."
) else (
  echo     ffmpeg not found on PATH. Install via: choco install ffmpeg
  echo     Build will continue without bundled ffmpeg.
  set ADD_BINARY=
)

set ICON_OPT=
if exist "%ICON%" set ICON_OPT=--icon="%ICON%"
set VERSION_OPT=
if exist "%VERINFO%" set VERSION_OPT=--version-file="%VERINFO%"

echo ==^> 4/5 PyInstaller build .exe
rmdir /s /q build dist 2>nul
pyinstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name "%APP_NAME%" ^
  %ICON_OPT% ^
  %VERSION_OPT% ^
  --add-data "assets;assets" ^
  %ADD_BINARY% ^
  "%PY_SCRIPT%"

if not exist "dist\%APP_NAME%.exe" (
  echo PyInstaller failed — dist\%APP_NAME%.exe missing.
  exit /b 1
)

echo ==^> 5/5 Build MSI (requires WiX Toolset on PATH)
where candle.exe >nul 2>&1
if %errorlevel% neq 0 (
  echo     WiX Toolset not found. Skipping MSI build.
  echo     Install via: choco install wixtoolset  ^(then restart shell^)
  echo     Or download: https://wixtoolset.org/releases/
  echo.
  echo Built: %cd%\dist\%APP_NAME%.exe
  goto :done
)

REM Generate MSI via WiX
candle.exe -nologo -arch x64 ^
  -dAppName="%APP_DISPLAY%" ^
  -dAppVersion=%APP_VERSION% ^
  -dAppAuthor="%APP_AUTHOR%" ^
  -dExePath="dist\%APP_NAME%.exe" ^
  -dIconPath="%ICON%" ^
  -out dist\installer.wixobj ^
  installer.wxs

if %errorlevel% neq 0 (
  echo     WiX candle failed.
  exit /b 1
)

light.exe -nologo -ext WixUIExtension ^
  -cultures:en-us ^
  -out "dist\%APP_NAME%-Setup.msi" ^
  dist\installer.wixobj

if %errorlevel% neq 0 (
  echo     WiX light failed.
  exit /b 1
)

echo.
echo Built: %cd%\dist\%APP_NAME%.exe
echo Built: %cd%\dist\%APP_NAME%-Setup.msi  ^(professional installer^)
echo.
echo Share the MSI: double-click on receiver PC ^> Next ^> Install ^> Done.
echo Adds Start Menu entry + uninstaller entry in Control Panel.

:done
endlocal
