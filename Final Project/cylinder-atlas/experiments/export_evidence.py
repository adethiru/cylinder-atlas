"""Dump real run evidence (token counts, costs, traces, guard events, plan) to
output/evidence.json for the report.   python3 experiments/export_evidence.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas import config, db, planner  # noqa: E402
from atlas.server import usage_summary, run_detail  # noqa: E402

db.init()
ev = {
    "usage": usage_summary(),
    "runs": [run_detail(r["id"]) for r in db.q("SELECT id FROM runs ORDER BY id")],
    "security_events": db.q("SELECT * FROM security_events ORDER BY id"),
    "targets_worked": db.q("SELECT id,name,status,score,stage,outreach_status,screen_json,analysis_json FROM targets WHERE stage!='new'"),
    "facts": db.q("SELECT * FROM facts ORDER BY id"),
    "plan": planner.compute(),
    "strategy": db.get_setting("strategy"),
    "model": config.MODEL, "prices": config.PRICES,
}
out = config.ROOT / "output"
out.mkdir(exist_ok=True)
(out / "evidence.json").write_text(json.dumps(ev, indent=1, default=str))
print(f"Saved output/evidence.json  ({len(ev['runs'])} runs, {ev['usage']['total']['calls']} model calls)")
