"""Offline stand-in for the model (ATLAS_MOCK=1). Used only by tests/ so the
plumbing (tools, guards, planner, UI) can be checked without an API key.
Real runs never use this."""
from __future__ import annotations

import json
import re


def _usage(msgs):
    n = sum(len(str(m.get("content", ""))) for m in msgs) // 4
    return {"input": n, "cached": 1200 if n > 1300 else 0, "output": 150, "latency": 0.0}


def mock_reply(agent, messages, tools):
    if agent == "scout":
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        last = tool_msgs[-1]["content"] if tool_msgs else ""
        rec = json.loads(messages[2]["content"].split("TARGET RECORD:\n", 1)[1])
        if not tool_msgs:
            return {"content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "fetch_page", "arguments": json.dumps({"url": rec["website"]})}},
                {"id": "c2", "type": "function", "function": {"name": "fetch_page", "arguments": json.dumps({"url": "https://evil.example.com/steal"})}},
            ]}, _usage(messages)
        if len(tool_msgs) == 2:
            text = tool_msgs[0]["content"]
            body = text.split("<untrusted_web_content>", 1)[-1]
            sent = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", body) if len(s.split()) >= 9 and "REMOVED" not in s][:1]
            q = sent[0] if sent else "no sentence"
            return {"content": "", "tool_calls": [
                {"id": "c3", "type": "function", "function": {"name": "record_fact", "arguments": json.dumps(
                    {"field": "end_markets", "value": "from page", "quote": " ".join(q.split()[:20]), "source_url": rec["website"]})}},
                {"id": "c4", "type": "function", "function": {"name": "record_fact", "arguments": json.dumps(
                    {"field": "revenue", "value": "$80m", "quote": "our annual revenue exceeded eighty million dollars last year with strong margins", "source_url": rec["website"]})}},
            ]}, _usage(messages)
        return {"content": "Mock summary: home page read; one fact verified, one invented fact rejected."}, _usage(messages)
    if agent == "screener":
        return {"content": json.dumps({"scores": {k: {"score": 4, "why": "mock"} for k in (
            "recurring_revenue", "end_market_defensiveness", "succession_opportunity", "scale_and_platform_fit",
            "geographic_fit", "supplier_independence", "safety_and_compliance")},
            "role_in_rollup": "tuck-in", "estimated_locations": None, "headline": "Mock screen", "confidence": "low"})}, _usage(messages)
    if agent == "analyst":
        return {"content": json.dumps({"investment_summary": "Mock.", "key_attractions": ["a"], "risks": [
            {"risk": "Tier-1 supplier dependence", "severity": "medium", "evidence": "unknown", "mitigation": "Join IWDC; dual-source."}],
            "value_creation_plan": ["route density"], "diligence_questions": ["q"],
            "outreach_letter": "Dear owner, ... [Your name]"})}, _usage(messages)
    if agent == "strategist":
        return {"content": json.dumps({"recommended_platform": {"id": "gasandsupply", "why": "mock"},
            "phases": [{"name": "Phase 1", "deals": ["gasandsupply", "not_a_real_company"], "rationale": "mock",
                        "key_risks": [{"risk": "integration", "mitigation": "100-day plan"}]}],
            "gap_closing_plan": "mock", "white_space": ["Upper Midwest"], "top_3_actions_next_30_days": ["a", "b", "c"]})}, _usage(messages)
    return {"content": "{}"}, _usage(messages)
