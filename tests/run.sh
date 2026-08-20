#!/bin/sh
# ZH Downloader browser-extension tests.  ./tests/run.sh
# Needs only node, python3 and Chrome — no npm install, nothing vendored.
#
#   fb_retry_test.py    drives the real App._run_video with yt-dlp stubbed: a public
#                       Facebook reel must retry WITHOUT cookies after "Cannot parse
#                       data", a private one must still retry WITH them
#   row_actions_test.py drives the 📂 / ↗ row buttons (reveal the finished file,
#                       reopen the source page) and the Text-size font helpers
#   widgets_test.py     builds the custom-drawn controls on a real (withdrawn) Tk
#                       root — both bugs here were tkinter attribute shadowing
#   bg.test.js          runs extension/background.js inside a node vm with a
#                       stubbed chrome API (sniffed-stream persistence across a
#                       service-worker restart, pending-queue TTL, hand-back of
#                       intercepted downloads, media-URL matching)
#   inject.test.html    loads extension/content.js three times in headless
#                       Chrome — fresh tab, re-inject over a LIVE copy, and
#                       re-inject over a STALE one (extension updated) — and
#                       asserts exactly one overlay pill and one live listener
#                       set survives each time
#
# Both suites also pass/fail against extension/*.bak, which is how the fixes
# were verified:  node tests/bg.test.js extension/background.js.bak
set -e
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
port=${ZH_TEST_PORT:-8731}
CHROME=${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}

echo "== app queue (_do_start row preservation) =="
python3 "$here/queue_test.py"

echo
echo "== Facebook cookie retry (_run_video) =="
python3 "$here/fb_retry_test.py"

echo
echo "== queue-row actions + font scaling =="
python3 "$here/row_actions_test.py"

echo
echo "== custom controls (RoundedButton / RoundedSelect / Switch) =="
python3 "$here/widgets_test.py"

echo
echo "== background.js (node vm + stubbed chrome API) =="
node "$here/bg.test.js" "$root/extension/background.js"

echo
echo "== content.js re-injection (headless Chrome) =="
if [ ! -x "$CHROME" ]; then
  echo "SKIP: Chrome not found at $CHROME (set CHROME=/path/to/chrome)"
  exit 0
fi
python3 -m http.server "$port" --directory "$root" >/dev/null 2>&1 &
srv=$!
trap 'kill $srv 2>/dev/null || true' EXIT INT TERM
sleep 1
out=$("$CHROME" --headless=new --disable-gpu --virtual-time-budget=6000 \
        --dump-dom "http://localhost:$port/tests/inject.test.html" 2>/dev/null |
      sed -n '/<pre id="out">/,/<\/pre>/p' | sed -e 's/<[^>]*>//g')
echo "$out"
echo "$out" | grep -q "ALL PASS"
