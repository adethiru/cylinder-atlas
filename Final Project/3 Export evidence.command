#!/bin/bash
# Double-click after using the app: saves real token counts, traces and guard events to
# cylinder-atlas/output/evidence.json (used to write the report).
cd "$(dirname "$0")/cylinder-atlas" || exit 1
python3 experiments/export_evidence.py
python3 -m atlas.safetytests > output/safety_tests.txt && cat output/safety_tests.txt
read -n1 -rp "Done. Press any key to close…"
