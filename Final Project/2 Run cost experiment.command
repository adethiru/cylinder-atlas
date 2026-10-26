#!/bin/bash
# Double-click: runs the deal desk on 4 targets at two page budgets (6000 vs 2000 chars)
# to measure whether cost cutting hurts quality. ~16 model calls per target, a few cents total.
cd "$(dirname "$0")" || exit 1
if [ ! -f .env ] && [ -f ../.env ]; then grep -E '^(PORTKEY_API_KEY|OPENAI_API_KEY)=' ../.env > .env; fi
cd cylinder-atlas || exit 1
python3 experiments/cost_vs_quality.py
python3 experiments/export_evidence.py
read -n1 -rp "Done. Press any key to close…"
