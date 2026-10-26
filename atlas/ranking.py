"""Pre-screen ranking of the whole target universe (deterministic, no LLM, $0).

Every independent (status 'target') and PE-owned ('sponsor') company gets a
0-100 pre-screen score from the data on the map. When the Screener agent has
scored a company, its score is blended in (50/50). The reasons behind each
score are returned so the ranking is explainable.

Country risk tiers are INDICATIVE, based on broad OECD country-risk / income
groupings, and should be checked against a current source before any decision.
"""
from __future__ import annotations

import math
import re

from . import db, planner

LOW = {"USA", "United States", "Canada", "United Kingdom", "UK", "Ireland", "Germany", "France", "Italy", "Spain", "Portugal",
       "Netherlands", "Belgium", "Luxembourg", "Austria", "Switzerland", "Denmark", "Sweden", "Norway", "Finland", "Iceland",
       "Poland", "Czechia", "Czech Republic", "Slovakia", "Slovenia", "Estonia", "Latvia", "Lithuania", "Hungary", "Greece",
       "Malta", "Japan", "South Korea", "Korea", "Australia", "New Zealand", "Singapore", "Israel", "Taiwan", "Puerto Rico"}
MEDIUM = {"Mexico", "Chile", "Brazil", "Colombia", "Peru", "Uruguay", "Costa Rica", "Panama", "Malaysia", "Thailand", "China",
          "India", "Indonesia", "Philippines", "Vietnam", "Saudi Arabia", "UAE", "United Arab Emirates", "Qatar", "Kuwait", "Oman",
          "Bahrain", "Romania", "Bulgaria", "Croatia", "Serbia", "South Africa", "Morocco", "Jordan", "Trinidad and Tobago",
          "Guatemala", "Dominican Republic", "Hong Kong", "Cyprus"}
RISK_NOTE = ("Indicative country-risk tiers: Low = OECD high-income markets (US, Canada, Western & Northern Europe, Japan, Korea, "
             "Australia/NZ, Singapore); Medium = investment-grade-style emerging markets (Mexico, Chile, GCC, Malaysia, China, India, "
             "South Africa...); High = elevated political, currency or transfer risk (e.g. Turkey, Egypt, Nigeria, Kenya, Pakistan, "
             "Argentina, Ukraine). Verify against a current OECD / export-credit risk source.")
VAL_NOTE = ("Indicative valuation: est. EBITDA = branches x revenue/branch x margin; entry multiple by size band "
            "(<=5 branches 5.5x, 6-15 6.5x, 16-30 8x, 31+ 10x), +1x for PE-owned (auction) or scaled consolidators, "
            "-1x/-2x for medium/high country risk. Value created = EBITDA x (exit multiple - entry multiple). "
            "Benchmarks from the thesis (tuck-ins ~5-7x, platforms ~9-11x); verify with comps and broker data.")
REGION_BONUS = {"Canada": 14, "US": 10, "Europe": 6, "Latin America": 3, "Middle East": 2, "China & SEA": 2}
REGION_LABEL = {"US": "North America (US)", "Canada": "Canada", "Europe": "Europe", "Latin America": "Latin America",
                "Middle East": "Middle East & Africa", "China & SEA": "Asia Pacific"}


def country_risk(country: str) -> str:
    c = (country or "").strip()
    if c in LOW:
        return "low"
    if c in MEDIUM:
        return "medium"
    return "high"


def valuation(t: dict, a: dict) -> dict:
    """Indicative entry multiple (EV / EBITDA) by size band, adjusted for ownership and country risk.
    Bands follow the thesis benchmarks: tuck-ins ~5-7x, scaled platforms ~9-11x. Editable estimates, not quotes."""
    locs = t.get("locations") or a["default_locations"]
    rev = locs * a["rev_per_location_m"]
    ebitda = rev * a["ebitda_margin_pct"] / 100
    basis = "estimated"
    if t.get("known_revenue_m"):            # your own figures (CIM / teaser / call) override the estimate
        rev = float(t["known_revenue_m"]); ebitda = rev * a["ebitda_margin_pct"] / 100; basis = "your revenue"
    if t.get("known_ebitda_m"):
        ebitda = float(t["known_ebitda_m"]); basis = "your figures"
        if not t.get("known_revenue_m"):
            rev = ebitda / (a["ebitda_margin_pct"] / 100)
    if locs <= 5:
        m, band = 5.5, "small tuck-in"
    elif locs <= 15:
        m, band = 6.5, "tuck-in"
    elif locs <= 30:
        m, band = 8.0, "large tuck-in / mini-platform"
    else:
        m, band = 10.0, "platform"
    adj = []
    if t["status"] == "sponsor":
        m += 1.0; adj.append("+1.0x sponsor auction")
    if t["status"] == "consolidator":
        m += 1.0; adj.append("+1.0x scarcity (scaled consolidator)")
    risk = country_risk(t.get("country"))
    if risk == "medium":
        m -= 1.0; adj.append("-1.0x country risk")
    if risk == "high":
        m -= 2.0; adj.append("-2.0x country risk")
    ev = ebitda * m
    exit_m = a.get("exit_multiple", 12.0)
    return {"entry_multiple": round(m, 1), "band": band, "adjustments": adj, "est_ebitda_m": round(ebitda, 1),
            "est_revenue_m": round(rev, 1), "fin_basis": basis,
            "est_ev_m": round(ev, 1), "arbitrage_x": round(exit_m - m, 1),
            "value_created_m": round(ebitda * (exit_m - m), 1)}


def prescreen(t: dict, a: dict, detail: bool = False):
    """0-100 pre-screen score. Returns (score, reasons) or, with detail=True,
    (score, reasons, parts) where parts = [{factor, label, pts}] explains every point."""
    why, parts = [], []

    def add(pts, factor, label, show=True):
        parts.append({"factor": factor, "label": label, "pts": round(pts, 1)})
        if show:
            why.append(label)

    txt = f"{t.get('ownership') or ''} {t.get('notes') or ''}".lower()
    if t["status"] == "target":
        add(30, "Ownership", "independent")
    elif t["status"] == "consolidator":
        add(24, "Ownership", "independent consolidator - platform candidate")
    else:
        add(22, "Ownership", "PE-owned (secondary-buyout)")
        m = re.search(r"~?([\d.]+)\s*yrs? held", txt)
        if m and float(m.group(1)) >= 4:
            add(6, "Exit window", f"sponsor hold ~{float(m.group(1)):.0f} yrs (exit window)")
    locs = t.get("locations")
    if locs:
        add(min(25.0, 6 * math.log2(1 + locs)), "Scale", f"{locs} locations" + (" - platform scale" if locs >= 25 else ""))
    else:
        add(9, "Scale", "branch count unknown")
    if re.search(r"(second|third|fourth|fifth|2nd|3rd|4th|5th)[- ]generation|multi-generation", txt):
        add(12, "Succession", "multi-generation family (succession)")
    elif re.search(r"family|founder|founded 19|since 19|employee-owned|esop", txt):
        add(8, "Succession", "family / founder-owned")
    risk = country_risk(t.get("country"))
    add({"low": 15, "medium": 7, "high": 0}[risk], "Country risk", f"{risk} country risk")
    rb = REGION_BONUS.get(t.get("region"), 0)
    if rb:
        add(rb, "Focus market", "Canada focus market" if t.get("region") == "Canada" else f"{REGION_LABEL.get(t.get('region'), t.get('region'))} market",
            show=t.get("region") == "Canada")
    if re.search(r"medical|hospital|beverage|co2|food|specialty|lab", txt):
        add(4, "End markets", "defensive end markets")
    if re.search(r"largest independent", txt):
        add(5, "Market position", "self-described largest independent")
    if re.search(r"fill plant|filling plant|fill facility|asu|air separation|cryogenic|bulk|transfill|fills ", txt):
        add(3, "Assets", "own fill / production")
    if t.get("website"):
        add(2, "Data quality", "website to research", show=False)
    if "low fit" in txt:
        add(-10, "Fit", "may not sell gas (low fit)")
    if "not listed in the 2026 iwdc" in txt:
        add(-6, "Data check", "missing from 2026 IWDC list (check if acquired)")
    if "dealer" in txt and ("air liquide" in txt or "linde" in txt or "praxair" in txt):
        add(-4, "Supply", "dealer of a major (supply contract)")
    v = valuation(t, a)
    add(max(0.0, min(6.0, v["arbitrage_x"] * 1.0)), "Valuation",
        f"entry ~{v['entry_multiple']}x vs exit {a.get('exit_multiple', 12)}x ({v['arbitrage_x']:+.1f}x arbitrage)")
    # entry fit: can you actually buy it from a standing start?
    cap = float(a.get("max_platform_ev_m", 400.0))
    ev = v["est_ev_m"]
    if t["status"] == "consolidator" and (locs or 0) >= 30:
        add(-8, "Entry fit", "rival roll-up: later-stage merger or exit buyer, not a first deal")
    if ev > 2 * cap:
        add(-20, "Entry fit", f"too large for a first deal (EV ~${ev:,.0f}m vs ${cap:,.0f}m platform budget)")
    elif ev > cap:
        add(-10, "Entry fit", f"large for a first deal (EV ~${ev:,.0f}m vs ${cap:,.0f}m platform budget)")
    score = max(0.0, min(100.0, sum(x["pts"] for x in parts)))
    return (score, why, parts) if detail else (score, why)


def entry_role(t: dict, v: dict, a: dict) -> str:
    """How the company fits a buy-and-build that starts from zero."""
    cap = float(a.get("max_platform_ev_m", 400.0))
    locs = t.get("locations") or 0
    if t["status"] == "consolidator" and locs >= 30:
        return "Later stage"          # a rival roll-up: merger partner or exit buyer once you have scale
    if v["est_ev_m"] > cap:
        return "Too large for entry"
    if locs >= 10 and v["est_ev_m"] >= 40:
        return "Platform candidate"
    return "Tuck-in"


def rank(risks=("low", "medium"), regions=None, limit=None) -> dict:
    a = planner.assumptions()
    rows = [t for t in db.q("SELECT * FROM targets WHERE status IN ('target','sponsor','consolidator')")
            if t["status"] != "consolidator" or not re.search(r"listed|sponsor|pag|stake|nyse|euronext|sse|szse|aea", (t.get("ownership") or "").lower())]
    facts_n = {r["target_id"]: r["n"] for r in db.q("SELECT target_id, COUNT(*) n FROM facts WHERE verified=1 GROUP BY target_id")}
    out = []
    for t in rows:
        if (t.get("deal_stage") or "") == "Passed":       # you passed on it: drop from the ranking
            continue
        risk = country_risk(t.get("country"))
        if risks and risk not in risks:
            continue
        if regions and t["region"] not in regions:
            continue
        ps, why, parts = prescreen(t, a, detail=True)
        # blend in the Screener agent's score only as far as it is backed by verified facts:
        # 0 facts -> ignored (an "unknown" screen should not push a company down), 5+ facts -> 50/50
        nf = facts_n.get(t["id"], 0)
        w = min(0.5, 0.1 * nf) if t.get("score") is not None else 0.0
        score = round((1 - w) * ps + w * (t["score"] or 0), 1)
        val = valuation(t, a)
        out.append({**val, "entry_role": entry_role(t, val, a), "id": t["id"], "name": t["name"], "city": t["city"], "region_state": t["region_state"], "country": t["country"],
                    "region": t["region"], "region_label": REGION_LABEL.get(t["region"], t["region"]), "status": t["status"],
                    "risk": risk, "locations": t["locations"],
                    "prescreen": round(ps, 1), "agent_score": t.get("score"), "agent_weight": w, "verified_facts": nf, "score": score, "why": why, "parts": parts,
                    "stage": t["stage"], "outreach_status": t["outreach_status"], "website": t["website"],
                    "deal_stage": t.get("deal_stage") or "", "next_step": t.get("next_step") or "", "next_date": t.get("next_date") or "",
                    "ownership": t.get("ownership") or "", "lat": t["lat"], "lon": t["lon"]})
    out.sort(key=lambda r: (-r["score"], -(r["locations"] or 0)))
    cum = cap = 0.0
    for i, r in enumerate(out, 1):
        cum += r["est_revenue_m"]; cap += r["est_ev_m"]
        r["rank"], r["cum_revenue_m"], r["cum_ev_m"] = i, round(cum, 1), round(cap, 1)

    def tier(n):
        sel = out[:n]
        rev = sum(r["est_revenue_m"] for r in sel)
        eb = sum(r["est_ebitda_m"] for r in sel); ev = sum(r["est_ev_m"] for r in sel)
        return {"n": len(sel), "revenue_m": round(rev, 1), "ebitda_m": round(eb, 1), "ev_m": round(ev, 1),
                "blended_multiple": round(ev / eb, 1) if eb else None, "value_created_m": round(sum(r["value_created_m"] for r in sel), 1),
                "pct_of_goal": round(100 * rev / a["goal_value_m"], 1), "locations": sum((r["locations"] or a["default_locations"]) for r in sel)}

    n_to_goal = next((r["rank"] for r in out if r["cum_revenue_m"] >= a["goal_value_m"]), None)
    return {"exit_multiple": a.get("exit_multiple", 12.0), "valuation_note": VAL_NOTE, "rows": out[:limit] if limit else out, "total": len(out), "tiers": {"top20": tier(20), "top50": tier(50), "all": tier(len(out))},
            "deals_to_goal": n_to_goal, "goal_m": a["goal_value_m"], "rev_per_location_m": a["rev_per_location_m"],
            "default_locations": a["default_locations"], "risk_note": RISK_NOTE}
