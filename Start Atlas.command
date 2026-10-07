#!/bin/bash
# Double-click this file to open the atlas in Chrome.
# Leave the Terminal window that appears open while you use the atlas.
# Closing that window stops the atlas; double-click again to bring it back.

cd "$(dirname "$0")/site" || { echo "Could not find the site folder."; exit 1; }
PORT=4600

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "The atlas is already running."
else
  python3 -m http.server $PORT >/dev/null 2>&1 &
  sleep 1
fi

open -a "Google Chrome" "http://localhost:$PORT" 2>/dev/null || open "http://localhost:$PORT"
echo "Atlas is at http://localhost:$PORT"
echo "Keep this window open. Close it when you are done."
wait
