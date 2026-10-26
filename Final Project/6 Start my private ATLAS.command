#!/bin/bash
# Double-click: your PRIVATE copy of ATLAS for real deal work.
# Your pipeline, notes and figures live in "Final Project/My ATLAS data" - OUTSIDE the repo,
# so they are never uploaded to GitHub. A dated backup is taken every time you start it.
cd "$(dirname "$0")" || exit 1
if [ ! -s .env ] && [ -f ../.env ]; then
  grep -E '^(PORTKEY_API_KEY|OPENAI_API_KEY)=' ../.env > .env && echo "✓ Copied key into Final Project/.env (outside the repo)"
fi
DATA="$(pwd)/My ATLAS data"
mkdir -p "$DATA/backups"
if [ -f "$DATA/atlas.db" ]; then
  cp "$DATA/atlas.db" "$DATA/backups/atlas-$(date +%Y-%m-%d_%H%M).db" && echo "✓ Backup saved in My ATLAS data/backups"
  ls -1t "$DATA/backups"/atlas-*.db 2>/dev/null | tail -n +21 | while read -r f; do rm -f "$f"; done   # keep the last 20
fi
OLD=$(lsof -ti tcp:8766 2>/dev/null); [ -n "$OLD" ] && kill $OLD 2>/dev/null && sleep 1
cd cylinder-atlas || exit 1
echo "Private workspace: $DATA/atlas.db"
ATLAS_DB="$DATA/atlas.db" python3 app.py --port 8766
