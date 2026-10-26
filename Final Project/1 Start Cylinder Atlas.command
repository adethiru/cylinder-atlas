#!/bin/bash
# Double-click: (re)starts Cylinder Atlas with the latest code.
# Puts your key in "Final Project/.env" (one level ABOVE the repo, exactly like the teaching staff's setup).
cd "$(dirname "$0")" || exit 1
if [ ! -s .env ] && [ -f ../.env ]; then
  grep -E '^(PORTKEY_API_KEY|OPENAI_API_KEY)=' ../.env > .env && echo "✓ Copied key into Final Project/.env (outside the repo)"
fi
# stop any older copy of the app still running on the port, so the new code is used
OLD=$(lsof -ti tcp:8765 2>/dev/null); [ -n "$OLD" ] && kill $OLD 2>/dev/null && echo "✓ Stopped the old app" && sleep 1
cd cylinder-atlas || exit 1
python3 - <<'EOF'
from atlas import config
print("Key file :", config.ENV_FILE_USED or "NOT FOUND")
print("Provider :", config.PROVIDER, "| model:", config.MODEL, "| key loaded:", bool(config.api_key()))
EOF
python3 app.py
