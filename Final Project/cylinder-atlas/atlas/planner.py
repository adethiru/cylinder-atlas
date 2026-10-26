"""Roll-up planner: deterministic buy-and-build math (no LLM).

Estimates each selected deal's revenue / EBITDA from its branch count and the
editable benchmarks, adds route-density synergies for deals close to an earlier
deal, prices deals at platform vs tuck-in multiples, and reports the bridge and
the gap to the $1bn revenue goal.
All outputs are ESTIMATES driven by the assumptions shown in the UI.
"""
from __future__ import annotations

import math

from . import db

DEFAULTS = {
    "goal_type": "revenue",          # goal is measured in revenue
    "goal_value_m": 1000.0,          # $1bn revenue
    "rev_per_location_m": 4.0,
    "ebitda_margin_pct": 22.0,
    "synergy_margin_pts": 3.0,       # route-density uplift for nearby tuck-ins
    "synergy_radius_miles": 150.0,
    "platform_multiple": 10.0,
    "tuckin_multiple": 6.0,
    "exit_multiple": 12.0,
    "default_locations": 3,          # used when a target's branch count is unknown
    "typical_tuckin_locations": 4,
    "max_platform_ev_m": 400.0,      # biggest first deal you can fund from a standing start (EV, $m)
    # returns (sponsor equity view)
    "hold_years": 5.0,
    "leverage_x": 4.5,               # acquisition debt, x entry EBITDA (capped at 60% of price)
    "debt_paydown_pct": 35.0,        # share of acquisition debt repaid from free cash flow over the hold
    "organic_growth_pct": 5.0,       # annual EBITDA growth after acquisition (price + volume)
    "fees_pct": 3.0,                 # transaction costs, % of purchase price
}


def assumptions() -> dict:
    a = dict(DEFAULTS)
    a.update(db.get_setting("planner_assumptions", {}) or {})
    a["goal_type"] = "revenue"          # the platform goal is $1bn revenue
    if a.get("goal_value_m", 0) < 500:  # old saved EBITDA goal -> reset to $1bn
        a["goal_value_m"] = 1000.0
    return a


def miles(a, b) -> float:
    r = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(d))


def compute(plan_ids: list[str] | None = None) -> dict:
    a = assumptions()
    order = plan_ids if plan_ids is not None else (db.get_setting("plan_order", []) or [])
    rows = {t["id"]: t for t in db.q("SELECT * FROM targets")}
    deals, prior = [], []
    for i, tid in enumerate([t for t in order if t in rows]):
        t = rows[tid]
        locs_known = t["locations"] is not None
        locs = int(t["locations"]) if locs_known else int(a["default_locations"])
        rev = locs * a["rev_per_location_m"]
        ebitda = rev * a["ebitda_margin_pct"] / 100
        reported = False
        if t.get("known_revenue_m"):
            rev = float(t["known_revenue_m"]); ebitda = rev * a["ebitda_margin_pct"] / 100; reported = True
        if t.get("known_ebitda_m"):
            ebitda = float(t["known_ebitda_m"]); reported = True
            if not t.get("known_revenue_m"):
                rev = ebitda / (a["ebitda_margin_pct"] / 100)
        near = None
        if prior:
            near = min(prior, key=lambda p: miles(p, t))
            dist = miles(near, t)
        else:
            dist = None
        syn = rev * a["synergy_margin_pts"] / 100 if (dist is not None and dist <= a["synergy_radius_miles"]) else 0.0
        role = "platform" if i == 0 else "tuck-in"
        mult = a["platform_multiple"] if role == "platform" else a["tuckin_multiple"]
        deals.append({
            "id": tid, "name": t["name"], "region": t["region"], "status": t["status"], "role": role,
            "locations": locs, "locations_estimated": not locs_known and not reported, "reported": reported,
            "deal_stage": t.get("deal_stage") or "",
            "revenue_m": round(rev, 1), "ebitda_m": round(ebitda, 1), "synergy_m": round(syn, 1),
            "nearest_prior": near["name"] if near else None, "miles_to_nearest": round(dist) if dist is not None else None,
            "multiple": mult, "price_m": round(ebitda * mult, 1),
        })
        prior.append(t)
    tot_rev = sum(d["revenue_m"] for d in deals)
    tot_e = sum(d["ebitda_m"] for d in deals)
    tot_syn = sum(d["synergy_m"] for d in deals)
    capital = sum(d["price_m"] for d in deals)
    pro_forma_e = tot_e + tot_syn
    goal = a["goal_value_m"]
    achieved = tot_rev if a["goal_type"] == "revenue" else pro_forma_e
    gap = max(0.0, goal - achieved)
    tuck_rev = a["typical_tuckin_locations"] * a["rev_per_location_m"]
    tuck_e = tuck_rev * (a["ebitda_margin_pct"] + a["synergy_margin_pts"]) / 100
    more_deals = math.ceil(gap / (tuck_rev if a["goal_type"] == "revenue" else tuck_e)) if gap > 0 else 0
    # what the whole independent universe on the map could add (excluding consolidated/majors)
    avail = [t for t in rows.values() if t["status"] in ("target", "sponsor", "consolidator") and t["id"] not in order]
    avail_rev = sum((t["locations"] or a["default_locations"]) * a["rev_per_location_m"] for t in avail)
    ret = returns(capital, pro_forma_e, tot_e, a)
    return {
        "assumptions": a, "deals": deals, "returns": ret,
        "totals": {
            "revenue_m": round(tot_rev, 1), "ebitda_m": round(tot_e, 1), "synergy_m": round(tot_syn, 1),
            "pro_forma_ebitda_m": round(pro_forma_e, 1), "capital_m": round(capital, 1),
            "blended_multiple": round(capital / tot_e, 2) if tot_e else None,
            "exit_value_m": round(pro_forma_e * a["exit_multiple"], 1),
            "value_created_m": round(pro_forma_e * a["exit_multiple"] - capital, 1),
            "locations": sum(d["locations"] for d in deals),
        },
        "goal": {"type": a["goal_type"], "value_m": goal, "achieved_m": round(achieved, 1),
                 "pct": round(100 * achieved / goal, 1) if goal else 0, "gap_m": round(gap, 1),
                 "additional_tuckins_needed": more_deals,
                 "tuckin_size_note": f"{a['typical_tuckin_locations']} branches = ~${tuck_rev:.0f}m revenue each"},
        "universe": {"independent_targets_not_in_plan": len(avail), "their_est_revenue_m": round(avail_rev, 1)},
    }


def _equity(capital, pf_ebitda, entry_ebitda, a, exit_multiple=None, growth=None):
    """Simple sponsor returns: all capital deployed at t0, debt = leverage x entry EBITDA,
    EBITDA grows organically over the hold, part of the debt is repaid, exit at the exit multiple."""
    exit_multiple = a["exit_multiple"] if exit_multiple is None else exit_multiple
    growth = a["organic_growth_pct"] if growth is None else growth
    hold = max(1.0, a["hold_years"])
    debt = min(a["leverage_x"] * entry_ebitda, capital * 0.60)          # lenders rarely fund >60% of price
    equity_in = capital * (1 + a["fees_pct"] / 100) - debt
    exit_ebitda = pf_ebitda * (1 + growth / 100) ** hold
    exit_ev = exit_ebitda * exit_multiple
    net_debt_exit = debt * (1 - a["debt_paydown_pct"] / 100)
    equity_out = exit_ev - net_debt_exit
    moic = equity_out / equity_in if equity_in > 0 else None
    irr = (moic ** (1 / hold) - 1) * 100 if moic and moic > 0 else None
    return {"debt_m": round(debt, 1), "equity_in_m": round(equity_in, 1), "exit_ebitda_m": round(exit_ebitda, 1),
            "exit_ev_m": round(exit_ev, 1), "net_debt_exit_m": round(net_debt_exit, 1), "equity_out_m": round(equity_out, 1),
            "moic": round(moic, 2) if moic else None, "irr_pct": round(irr, 1) if irr is not None else None}


def returns(capital, pf_ebitda, entry_ebitda, a) -> dict | None:
    if capital <= 0 or entry_ebitda <= 0:
        return None
    base = _equity(capital, pf_ebitda, entry_ebitda, a)
    exits = [a["exit_multiple"] + d for d in (-3, -2, -1, 0, 1)]
    growths = [max(0.0, a["organic_growth_pct"] + d) for d in (-3, 0, 3)]
    grid = [{"exit_multiple": round(em, 1), "cells": [{"growth": g, **{k: v for k, v in _equity(capital, pf_ebitda, entry_ebitda, a, em, g).items() if k in ("moic", "irr_pct")}} for g in growths]} for em in exits]
    # what drives value: EBITDA growth (organic + synergies) vs multiple arbitrage vs debt paydown
    blended = capital / entry_ebitda
    ebitda_growth = (base["exit_ebitda_m"] - entry_ebitda) * blended
    arbitrage = base["exit_ebitda_m"] * (a["exit_multiple"] - blended)
    paydown = base["debt_m"] - base["net_debt_exit_m"]
    fees = capital * a["fees_pct"] / 100
    return {**base, "hold_years": a["hold_years"], "growth_cols": growths, "grid": grid,
            "value_bridge": {"ebitda_growth_m": round(ebitda_growth, 1), "multiple_arbitrage_m": round(arbitrage, 1),
                             "debt_paydown_m": round(paydown, 1), "fees_m": round(-fees, 1)},
            "debt_note": "Debt = leverage x entry EBITDA, capped at 60% of the purchase price.", "note": "Simplified: all capital deployed at t0, no interim dividends, no management equity, pre-tax. A screening view, not a model."}


ENTRY_OK = ("Platform candidate", "Tuck-in")


def sequence(rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Order a ranked shortlist into a buy-and-build: the best-scoring company you can afford as a
    first deal becomes the platform (#1); rival roll-ups and companies too large to buy from a
    standing start are left out (reported back so the UI can explain why)."""
    ok = [r for r in rows if r.get("entry_role") in ENTRY_OK]
    skipped = [{"id": r["id"], "name": r["name"], "why": r.get("entry_role")} for r in rows if r.get("entry_role") not in ENTRY_OK]
    if not ok:
        return [], skipped
    plats = [r for r in ok if r["entry_role"] == "Platform candidate"] or ok
    best = max(r["score"] for r in plats)
    # among the near-top scorers (within 3 points), the largest makes the strongest platform
    platform = max([r for r in plats if r["score"] >= best - 3], key=lambda r: (r["locations"] or 0, r["score"]))
    rest = [r["id"] for r in sorted(ok, key=lambda r: r["rank"]) if r["id"] != platform["id"]]
    return [platform["id"]] + rest, skipped


def auto_build(current: list[str]) -> tuple[list[str], list[dict]]:
    """Platform + nearest high-scoring tuck-ins in the US and Canada until the revenue goal is covered."""
    from . import ranking
    a = assumptions()
    rows = ranking.rank(("low", "medium"), ("US", "Canada"))["rows"]
    by = {r["id"]: r for r in rows}
    ok = [r for r in rows if r["entry_role"] in ENTRY_OK]
    order = [i for i in current if i in by]
    if not order:
        first, _ = sequence(ok)
        order = first[:1]
    rev = sum(by[i]["est_revenue_m"] for i in order)
    allt = {t["id"]: t for t in db.q("SELECT id, lat, lon FROM targets")}
    while rev < a["goal_value_m"] and len(order) < 60:
        chosen = [allt[i] for i in order if i in allt]
        pool = [r for r in ok if r["id"] not in order]
        if not pool:
            break
        # nearest to the existing footprint, nudged towards higher scores (route density first)
        nxt = min(pool, key=lambda r: min(miles(c, allt[r["id"]]) for c in chosen) - 4 * r["score"] - 3 * r["est_revenue_m"])
        order.append(nxt["id"])
        rev += nxt["est_revenue_m"]
    skipped = [{"id": r["id"], "name": r["name"], "why": r["entry_role"]} for r in rows[:30] if r["entry_role"] not in ENTRY_OK]
    return order, skipped
