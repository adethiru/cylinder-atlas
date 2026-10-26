"""Cost-cutting experiment: does trimming each web page to fewer characters
(the main input-token lever) hurt research quality?

Runs the full deal desk on the same targets at two page budgets and records
tokens, cost, facts verified, facts rejected and the screen score.

    python3 experiments/cost_vs_quality.py                # default targets, 6000 vs 2000 chars
    python3 experiments/cost_vs_quality.py redball lampton

Writes output/cost_vs_quality.json. Uses the real model (needs the key).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas import config, db, agents  # noqa: E402

TARGETS = sys.argv[1:] or ["demo_evergreen", "redball", "lampton", "centralmcgowan"]
BUDGETS = [6000, 2000]


def main():
    db.init()
    rows = []
    for tid in TARGETS:
        for pc in BUDGETS:
            rid = agents.run_deal_desk_sync(tid, pc)
            run = db.q("SELECT * FROM runs WHERE id=?", (rid,))[0]
            u = db.q("SELECT SUM(input_tokens) i, SUM(cached_tokens) c, SUM(output_tokens) o, SUM(cost_usd) usd, COUNT(*) n FROM usage WHERE run_id=?", (rid,))[0]
            summ = json.loads(run["summary"] or "{}")
            t = db.q("SELECT score FROM targets WHERE id=?", (tid,))[0]
            row = {"target": tid, "page_chars": pc, "run_id": rid, "status": run["status"], "calls": u["n"],
                   "input": u["i"], "cached": u["c"], "output": u["o"], "cost_usd": round(u["usd"] or 0, 6),
                   "facts_verified": summ.get("facts_saved"), "facts_rejected": summ.get("facts_rejected"),
                   "pages": summ.get("pages"), "score": t["score"]}
            rows.append(row)
            print(row)
    out = config.ROOT / "output"
    out.mkdir(exist_ok=True)
    (out / "cost_vs_quality.json").write_text(json.dumps(rows, indent=2))
    print("\nSaved output/cost_vs_quality.json")
    for pc in BUDGETS:
        sel = [r for r in rows if r["page_chars"] == pc and r["status"] == "done"]
        if sel:
            n = len(sel)
            print(f"page_chars={pc}: avg input {sum(r['input'] or 0 for r in sel)/n:,.0f} tokens, "
                  f"avg cost ${sum(r['cost_usd'] for r in sel)/n:.5f}, avg facts {sum(r['facts_verified'] or 0 for r in sel)/n:.1f}, "
                  f"avg score {sum(r['score'] or 0 for r in sel)/n:.1f}")


if __name__ == "__main__":
    main()
