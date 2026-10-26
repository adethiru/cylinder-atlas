#!/bin/bash
# Double-click AFTER uploading: clones the public repo into a brand-new folder, puts .env ONE LEVEL ABOVE
# it (exactly like the teaching staff), and starts the app on port 8810 by following the README.
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"; DRY="$HOME/Desktop/cylinder-dryrun"
rm -rf "$DRY"; mkdir -p "$DRY"; cd "$DRY" || exit 1
git clone https://github.com/adethiru/cylinder-atlas.git || { echo "git clone failed - is the repo public?"; read -n1; exit 1; }
grep -E '^(PORTKEY_API_KEY|OPENAI_API_KEY)=' "$ROOT/.env" "$ROOT/../.env" 2>/dev/null | head -1 | cut -d: -f2- > "$DRY/.env"
echo "✓ Cloned to $DRY, .env placed one level above the repo"
cd cylinder-atlas && python3 app.py --port 8810
