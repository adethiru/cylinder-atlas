"""Minimal OpenAI-compatible chat client (urllib only) + token metering + budget guard.

Every call records input / cached-input / output tokens and USD cost in the
`usage` table, so the UI can show real token counts per agent and per run.
Before every call the budget guard checks the per-run token cap and the daily
USD cap; if either is hit the run stops with BudgetExceeded.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config, db
from .net import ssl_context


class BudgetExceeded(Exception):
    pass


class LLMError(Exception):
    pass


def cost_usd(model: str, input_tokens: int, cached: int, output: int) -> float:
    p = config.PRICES.get(model, config.PRICES["gpt-6-luna"])
    uncached = max(0, input_tokens - cached)
    return (uncached * p["input"] + cached * p["cached"] + output * p["output"]) / 1_000_000


def spend_today() -> float:
    r = db.q("SELECT COALESCE(SUM(cost_usd),0) s FROM usage WHERE day=?", (db.today(),))
    return float(r[0]["s"])


def run_tokens(run_id) -> int:
    r = db.q("SELECT COALESCE(SUM(input_tokens+output_tokens),0) s FROM usage WHERE run_id=?", (run_id,))
    return int(r[0]["s"])


def check_budget(run_id) -> None:
    cap = float(db.get_setting("daily_usd_cap", config.DAILY_USD_CAP))
    if spend_today() >= cap:
        db.security_event("budget_stop", f"Daily cap ${cap:.2f} reached", run_id)
        raise BudgetExceeded(f"Daily spend cap of ${cap:.2f} reached - run stopped before calling the model.")
    tcap = int(db.get_setting("run_token_cap", config.RUN_TOKEN_CAP))
    if run_id is not None and run_tokens(run_id) >= tcap:
        db.security_event("budget_stop", f"Run token cap {tcap} reached", run_id)
        raise BudgetExceeded(f"Run token cap of {tcap:,} tokens reached - run stopped.")


def _post(body: dict) -> dict:
    req = urllib.request.Request(
        config.BASE_URL + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {config.api_key()}", "Content-Type": "application/json", "Accept": "application/json",
                 # Portkey sits behind Cloudflare, which rejects the default "Python-urllib" agent (error 1010)
                 "User-Agent": "CylinderAtlas/1.0 (OpenAI-compatible client; python)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_context()) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="ignore")[:800]
        raise LLMError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"Network error: {e.reason}") from None


def chat(messages: list, *, agent: str, run_id=None, tools=None, json_mode=False) -> dict:
    """Returns the assistant message dict ({content, tool_calls?})."""
    check_budget(run_id)
    if config.MOCK:
        from .mock import mock_reply
        msg, usage = mock_reply(agent, messages, tools)
    else:
        if not config.api_key():
            raise LLMError("No API key found. Put PORTKEY_API_KEY in a .env file in this folder or the folder above.")
        body = {"model": config.MODEL, "messages": messages,
                "max_completion_tokens": config.MAX_OUTPUT_TOKENS,
                "reasoning_effort": "none"}  # required for tool calls on gpt-6-luna chat; also cheaper/faster
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.time()
        try:
            data = _post(body)
        except LLMError as e:
            if json_mode and "response_format" in str(e):
                body.pop("response_format")
                data = _post(body)
            else:
                raise
        msg = data["choices"][0]["message"]
        u = data.get("usage") or {}
        cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        usage = {"input": u.get("prompt_tokens", 0), "cached": cached,
                 "output": u.get("completion_tokens", 0), "latency": round(time.time() - t0, 2)}
    c = cost_usd(config.MODEL, usage["input"], usage["cached"], usage["output"])
    db.x("INSERT INTO usage (run_id,ts,day,agent,model,input_tokens,cached_tokens,output_tokens,cost_usd) VALUES (?,?,?,?,?,?,?,?,?)",
         (run_id, time.time(), db.today(), agent, config.MODEL, usage["input"], usage["cached"], usage["output"], c))
    msg["_usage"] = {**usage, "cost_usd": c}
    return msg


def parse_json(text: str) -> dict:
    """Parse a JSON object from model text (tolerates ```json fences)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise LLMError("Model did not return JSON.")
    return json.loads(t[s:e + 1])
