"""The four agents and the orchestrator.

Deal desk (per target):   Scout --facts--> Screener --score--> Analyst --analysis + draft letter
Roll-up (whole pipeline): Planner math (code) --> Strategist (sequencing, risks, gap plan)

Every agent's messages start with the SAME long thesis system prompt (stable
prefix) so the provider can serve it from the prompt cache on repeat calls.
"""
from __future__ import annotations

import json
import threading
import time
import traceback

from . import config, db, llm, planner, safety
from .tools import TOOL_SPECS, ScoutSession

WEIGHTS = {"recurring_revenue": 1.5, "end_market_defensiveness": 1.0, "succession_opportunity": 1.5,
           "scale_and_platform_fit": 1.0, "geographic_fit": 1.0, "supplier_independence": 0.75,
           "safety_and_compliance": 0.75}


def _prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _base(role: str) -> list:
    return [{"role": "system", "content": _prompt("thesis")},
            {"role": "system", "content": _prompt(role)}]


def _target(tid: str) -> dict:
    r = db.q("SELECT * FROM targets WHERE id=?", (tid,))
    if not r:
        raise ValueError(f"Unknown target {tid}")
    return r[0]


def _record(t: dict) -> dict:
    keep = ("id", "name", "website", "city", "region_state", "country", "region", "status",
            "ownership", "locations", "notes", "source")
    return {k: t[k] for k in keep}


def _verified_facts(tid: str) -> list[dict]:
    return db.q("SELECT field,value,quote,source_url FROM facts WHERE target_id=? AND verified=1 ORDER BY id", (tid,))


def _usage_line(m: dict) -> str:
    u = m.get("_usage", {})
    return f"in {u.get('input', 0):,} (cached {u.get('cached', 0):,}) / out {u.get('output', 0):,} tokens, ${u.get('cost_usd', 0):.5f}"


def _redact(s: str) -> str:
    return safety.redact(s, [config.api_key()])


# ----------------------------------------------------------------------------- Scout
def scout(run_id: int, tid: str, page_chars: int | None = None) -> str:
    t = _target(tid)
    if not t["website"]:
        db.add_step(run_id, "scout", "info", "No website on file", "Add a website (or paste notes) to research this target.")
    db.x("DELETE FROM facts WHERE target_id=?", (tid,))   # fresh research each run
    s = ScoutSession(t, run_id, page_chars)
    msgs = _base("scout") + [{"role": "user", "content":
        "Research this target. Start with its home page, then 1-3 more useful pages from the links you see. "
        "Also call read_investor_notes once. If the company's own site cannot be fetched (errors or blocked), "
        "fetch the record's `source` URL instead (a public directory or trade-press page) and record what it supports.\nTARGET RECORD:\n" + json.dumps(_record(t), indent=2)}]
    summary = ""
    for step in range(config.MAX_SCOUT_STEPS):
        m = llm.chat(msgs, agent="scout", run_id=run_id, tools=TOOL_SPECS)
        calls = m.get("tool_calls") or []
        if not calls:
            summary = m.get("content") or ""
            db.add_step(run_id, "scout", "answer", "Scout finished - " + _usage_line(m), _redact(summary))
            break
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "fetch_page":
                out = s.fetch_page(str(args.get("url", "")))
                title = f"fetch_page({args.get('url', '')})"
            elif name == "read_investor_notes":
                out = s.read_investor_notes()
                title = "read_investor_notes()"
            elif name == "record_fact":
                out = s.record_fact(args.get("field", ""), args.get("value", ""), args.get("quote", ""), args.get("source_url", ""))
                title = f"record_fact({args.get('field', '')} = {str(args.get('value', ''))[:80]})"
            else:
                out = f"Unknown tool {name}"
                title = name
            db.add_step(run_id, "scout", "tool", title + "  [" + _usage_line(m) + "]", _redact(out[:1500]))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    else:
        db.security_event("loop_stop", f"Scout hit the {config.MAX_SCOUT_STEPS}-step limit", run_id, tid)
        db.add_step(run_id, "guard", "blocked", f"Loop guard stopped the Scout after {config.MAX_SCOUT_STEPS} steps", "")
        summary = "Stopped by step limit."
    db.x("UPDATE targets SET stage='researched', updated=? WHERE id=?", (time.time(), tid))
    db.add_step(run_id, "scout", "info", f"Facts saved: {s.facts_saved}, rejected by verifier: {s.rejected}, pages read: {s.pages_used}")
    db.x("UPDATE runs SET summary=? WHERE id=?", (json.dumps({"facts_saved": s.facts_saved, "facts_rejected": s.rejected,
                                                             "pages": s.pages_used, "page_chars": s.page_chars}), run_id))
    return summary


# -------------------------------------------------------------------------- Screener
def screener(run_id: int, tid: str) -> dict:
    t = _target(tid)
    facts = _verified_facts(tid)
    msgs = _base("screener") + [{"role": "user", "content":
        "TARGET RECORD:\n" + json.dumps(_record(t), indent=2) +
        "\nVERIFIED FACTS (quotes checked against the source):\n" + json.dumps(facts, indent=2)}]
    m = llm.chat(msgs, agent="screener", run_id=run_id, json_mode=True)
    res = llm.parse_json(m.get("content", ""))
    scores = res.get("scores", {})
    num = den = 0.0
    for k, w in WEIGHTS.items():
        v = scores.get(k, {}).get("score", 3)
        try:
            v = max(1, min(5, float(v)))
        except (TypeError, ValueError):
            v = 3
        num += v * w
        den += w
    score = round(20 * num / den, 1)
    if t["status"] in ("consolidated", "major"):   # hard rule in code, not just prompt
        score = min(score, 20.0)
        res["role_in_rollup"] = "not a fit"
        res["headline"] = "Excluded: already owned by a roll-up or a Tier-1 major. " + res.get("headline", "")
    res["score"] = score
    loc = res.get("estimated_locations")
    if t["locations"] is None and isinstance(loc, int) and any(f["field"] == "locations" for f in facts):
        db.x("UPDATE targets SET locations=? WHERE id=?", (loc, tid))
    db.x("UPDATE targets SET score=?, screen_json=?, stage='screened', updated=? WHERE id=?",
         (score, json.dumps(res), time.time(), tid))
    db.add_step(run_id, "screener", "answer", f"Score {score}/100 - {res.get('role_in_rollup', '')} - " + _usage_line(m),
                json.dumps(res, indent=2))
    return res


# --------------------------------------------------------------------------- Analyst
def analyst(run_id: int, tid: str) -> dict:
    t = _target(tid)
    msgs = _base("analyst") + [{"role": "user", "content":
        "TARGET RECORD:\n" + json.dumps(_record(t), indent=2) +
        "\nVERIFIED FACTS:\n" + json.dumps(_verified_facts(tid), indent=2) +
        "\nSCREEN RESULT:\n" + (t["screen_json"] or "{}")}]
    m = llm.chat(msgs, agent="analyst", run_id=run_id, json_mode=True)
    res = llm.parse_json(m.get("content", ""))
    letter = res.get("outreach_letter", "")
    if any(w in letter.lower() for w in ("has been sent", "i have sent", "we have sent", "i've emailed")):
        db.security_event("claim_blocked", "Analyst letter claimed it was sent - rewritten as draft", run_id, tid)
        res["outreach_letter"] = "[DRAFT - NOT SENT]\n" + letter
    db.x("UPDATE targets SET analysis_json=?, stage='analysis ready', outreach_status='draft', updated=? WHERE id=?",
         (json.dumps(res), time.time(), tid))
    db.add_step(run_id, "analyst", "answer", f"Analysis ready ({len(res.get('risks', []))} risks assessed) - " + _usage_line(m),
                json.dumps(res, indent=2))
    return res


# ------------------------------------------------------------------------ Strategist
def strategist(run_id: int) -> dict:
    plan = planner.compute()
    ts = db.q("SELECT id,name,region,status,locations,score,lat,lon FROM targets")
    by = {}
    for t in ts:
        by.setdefault(t["region"], {}).setdefault(t["status"], 0)
        by[t["region"]][t["status"]] += 1
    shortlist = sorted([t for t in ts if t["status"] == "target" and t["id"] not in [d["id"] for d in plan["deals"]]],
                       key=lambda t: -(t["score"] or 0))[:12]
    from . import strategy as _st
    sa = _st.analyze()
    payload = {"planner": plan, "universe_counts": by,
               "regional_scorecard": [{k: r[k] for k in ("label", "attractiveness", "investable", "est_revenue_m", "avg_multiple",
                                       "taken_share_pct", "targets_per_rival", "meritus", "succession_pct", "growth_cagr")} for r in sa["regions"]],
               "sponsor_owned": sa["sponsors"],
               "unplanned_independent_targets": [{k: t[k] for k in ("id", "name", "region", "locations", "score")} for t in shortlist],
               "rival_footprint": [t["name"] + " (" + t["region"] + ")" for t in ts if t["status"] in ("consolidator", "consolidated")],
               "returns": {k: v for k, v in (plan.get("returns") or {}).items() if k in ("irr_pct", "moic", "equity_in_m", "value_bridge")},
               "investor_pipeline": [{"id": t["id"], "name": t["name"], "stage": t["deal_stage"], "next_step": t["next_step"]}
                                     for t in db.q("SELECT id,name,deal_stage,next_step FROM targets WHERE deal_stage NOT IN ('','Passed') AND deal_stage IS NOT NULL")],
               "passed_on": [t["name"] for t in db.q("SELECT name FROM targets WHERE deal_stage='Passed'")]}
    msgs = _base("strategist") + [{"role": "user", "content": json.dumps(payload, indent=1)}]
    m = llm.chat(msgs, agent="strategist", run_id=run_id, json_mode=True)
    res = llm.parse_json(m.get("content", ""))
    valid = {t["id"] for t in ts}
    for ph in res.get("phases", []):           # drop any invented ids
        bad = [d for d in ph.get("deals", []) if d not in valid]
        if bad:
            db.security_event("invented_ids_removed", f"{bad}", run_id)
        ph["deals"] = [d for d in ph.get("deals", []) if d in valid]
    db.set_setting("strategy", {"result": res, "plan_snapshot": plan["totals"], "goal": plan["goal"], "ts": time.time()})
    db.add_step(run_id, "strategist", "answer", "Roll-up strategy ready - " + _usage_line(m), json.dumps(res, indent=2))
    return res


# ---------------------------------------------------------------------- Orchestrator
def run_deal_desk_sync(tid: str, page_chars: int | None = None) -> int:
    """Blocking version used by experiments/ (same agents, same guards)."""
    rid = start_deal_desk(tid, page_chars)
    while db.q("SELECT status FROM runs WHERE id=?", (rid,))[0]["status"] == "running":
        time.sleep(0.5)
    return rid


def _run(kind: str, target_id, fn) -> int:
    run_id = db.x("INSERT INTO runs (kind,target_id,status,started) VALUES (?,?,?,?)", (kind, target_id, "running", time.time()))

    def work():
        try:
            fn(run_id)
            db.x("UPDATE runs SET status='done', finished=? WHERE id=?", (time.time(), run_id))
        except llm.BudgetExceeded as e:
            db.add_step(run_id, "guard", "blocked", "Budget guard stopped the run", str(e))
            db.x("UPDATE runs SET status='stopped', finished=?, error=? WHERE id=?", (time.time(), str(e), run_id))
        except Exception as e:  # noqa: BLE001
            db.add_step(run_id, "system", "error", "Run failed", _redact(f"{e}\n{traceback.format_exc()[-1500:]}"))
            db.x("UPDATE runs SET status='error', finished=?, error=? WHERE id=?", (time.time(), _redact(str(e)), run_id))

    threading.Thread(target=work, daemon=True).start()
    return run_id


def start_deal_desk(tid: str, page_chars: int | None = None) -> int:
    def fn(run_id):
        db.add_step(run_id, "orchestrator", "info", f"Deal desk started for {_target(tid)['name']}",
                    "Scout -> Screener -> Analyst")
        scout(run_id, tid, page_chars)
        screener(run_id, tid)
        analyst(run_id, tid)
    return _run("deal_desk", tid, fn)


def start_strategy() -> int:
    def fn(run_id):
        db.add_step(run_id, "orchestrator", "info", "Roll-up strategist started", "Planner math (code) -> Strategist")
        strategist(run_id)
    return _run("strategy", None, fn)


# ---------------------------------------------------------------- batch research
_BATCH_LOCK = threading.Lock()


def batch_status() -> dict:
    return db.get_setting("batch", {"status": "idle", "ids": [], "done": [], "current": None}) or {}


def start_batch(ids: list[str]) -> dict:
    """Research several targets one after another (same agents, same guards). Stops cleanly
    if the daily budget cap is reached. At most 10 targets per batch."""
    with _BATCH_LOCK:
        cur = batch_status()
        if cur.get("status") == "running":
            return cur
        valid = {t["id"] for t in db.q("SELECT id FROM targets")}
        ids = [i for i in ids if i in valid][:10]
        st = {"status": "running", "ids": ids, "done": [], "current": None, "started": time.time(), "note": ""}
        db.set_setting("batch", st)

    def work():
        st = batch_status()
        for tid in ids:
            cap = float(db.get_setting("daily_usd_cap", config.DAILY_USD_CAP))
            if llm.spend_today() >= cap:
                st["note"] = "Stopped: daily budget cap reached"
                break
            st["current"] = tid
            db.set_setting("batch", st)
            try:
                rid = run_deal_desk_sync(tid)
                st["done"].append({"id": tid, "run_id": rid, "status": db.q("SELECT status FROM runs WHERE id=?", (rid,))[0]["status"]})
            except Exception as e:  # noqa: BLE001
                st["done"].append({"id": tid, "status": "error", "error": str(e)[:200]})
            db.set_setting("batch", st)
        st["status"], st["current"], st["finished"] = "done", None, time.time()
        db.set_setting("batch", st)

    threading.Thread(target=work, daemon=True).start()
    return st
