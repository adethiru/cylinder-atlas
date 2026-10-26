"""Regional strategy analytics (deterministic, from the map data).

For each region: supply of investable targets, their estimated revenue/EBITDA,
indicative entry multiples and value creation, competitive intensity (rival
consolidators, PE-owned players, companies already taken out), succession
signals and country risk, combined into a transparent attractiveness index.
Market growth figures are Grand View Research outlooks (see thesis).
"""
from __future__ import annotations

import re

from . import db, planner, ranking

UK_NAMES = {"United Kingdom", "UK", "England", "Scotland", "Wales", "Northern Ireland"}
GROWTH = {"US": 6.2, "Canada": 6.3, "Europe": 5.9, "UK": 5.4, "Rest of Europe": 6.1, "China & SEA": None, "Latin America": None, "Middle East": None}
MARKET = {"US": "$17.4bn (2023) → $26.5bn (2030)", "Canada": "$3.7bn (2023) → $5.6bn (2030)",
          "Europe": "$28.5bn (2023) → $42.6bn (2030)", "UK": "$6.5bn (2023) → $9.5bn (2030)",
          "Rest of Europe": "$22.0bn (2023) → $33.2bn (2030) (Europe less UK)", "China & SEA": "Asia Pacific → $76.6bn by 2030",
          "Latin America": "n/a", "Middle East": "n/a"}
ORDER = ["US", "Canada", "Europe", "Latin America", "Middle East", "China & SEA"]


def analyze() -> dict:
    a = planner.assumptions()
    allrows = db.q("SELECT * FROM targets")
    ranked = ranking.rank(("low", "medium", "high"))["rows"]
    by_id = {r["id"]: r for r in ranked}
    out = []
    segs = [(reg, [t for t in allrows if t["region"] == reg], False) for reg in ORDER]
    # Europe is also shown split into the UK and the rest of Europe (the combined row stays for the pillars)
    eu = [t for t in allrows if t["region"] == "Europe"]
    segs.insert(3, ("UK", [t for t in eu if (t["country"] or "") in UK_NAMES], True))
    segs.insert(4, ("Rest of Europe", [t for t in eu if (t["country"] or "") not in UK_NAMES], True))
    for reg, rows, sub in segs:
        inv = [by_id[t["id"]] for t in rows if t["id"] in by_id and by_id[t["id"]]["risk"] != "high"]
        targets = [t for t in rows if t["status"] == "target"]
        rivals = [t for t in rows if t["status"] in ("consolidator", "sponsor")]
        taken = [t for t in rows if t["status"] == "consolidated"]
        majors = [t for t in rows if t["status"] == "major"]
        meritus = [t for t in taken if "meritus" in (t["ownership"] or "").lower()]
        recent = [t for t in taken if re.search(r"202[4-6]", (t["ownership"] or "") + (t["notes"] or ""))]
        txt = lambda t: f"{t['ownership'] or ''} {t['notes'] or ''}".lower()
        succ = [t for t in targets if re.search(r"generation|family|founder|founded 19|since 19", txt(t))]
        multi = [t for t in targets if re.search(r"(second|third|fourth|2nd|3rd|4th)[- ]generation|multi-generation", txt(t))]
        rev = sum(r["est_revenue_m"] for r in inv)
        eb = sum(r["est_ebitda_m"] for r in inv)
        ev = sum(r["est_ev_m"] for r in inv)
        mult = round(ev / eb, 1) if eb else None
        hr = sum(1 for t in rows if t["id"] in by_id and by_id[t["id"]]["risk"] == "high")
        taken_share = round(100 * len(taken) / max(1, len(taken) + len(targets)))
        tpr = round(len(inv) / max(1, len(rivals)), 1)
        top = sorted(inv, key=lambda r: -r["score"])[:5]
        # attractiveness index (0-100): supply, cheapness, low competition, succession, growth, risk
        idx = 0.0
        idx += min(25, len(inv) / 6)                                   # supply of investable targets
        idx += max(0, min(20, (11 - (mult or 11)) * 5))               # lower entry multiple -> more points
        idx += max(0, 15 - taken_share / 4)                            # less already consolidated
        idx += min(15, 30 * len(succ) / max(1, len(targets)))         # succession signals
        idx += (GROWTH.get(reg) or 4) * 1.5                            # market growth
        idx -= 10 * hr / max(1, len(rows))                              # high-risk share
        out.append({"region": reg, "label": ranking.REGION_LABEL.get(reg, reg), "sub": sub, "companies": len(rows),
                    "investable": len(inv), "targets": len(targets), "rivals": len(rivals), "taken": len(taken),
                    "majors": len(majors), "meritus": len(meritus), "recent_deals": len(recent),
                    "taken_share_pct": taken_share, "targets_per_rival": tpr,
                    "succession_pct": round(100 * len(succ) / max(1, len(targets))),
                    "multigen": len(multi), "est_revenue_m": round(rev), "est_ebitda_m": round(eb), "est_ev_m": round(ev),
                    "avg_multiple": mult, "value_created_m": round(sum(r["value_created_m"] for r in inv)),
                    "growth_cagr": GROWTH.get(reg), "market": MARKET.get(reg), "high_risk_companies": hr,
                    "attractiveness": round(max(0, min(100, idx)), 1),
                    "top": [{"id": r["id"], "name": r["name"], "score": r["score"], "entry_multiple": r["entry_multiple"],
                             "est_ev_m": r["est_ev_m"], "locations": r["locations"]} for r in top]})
    sponsors = [{"name": t["name"], "ownership": t["ownership"], "region": t["region"]}
                for t in allrows if t["status"] == "sponsor"]
    # illustrative path to $1B by source of revenue (top-ranked investable targets per bucket)
    def bucket(regs, n):
        rs = sorted([r for r in ranked if r["region"] in regs and r["risk"] != "high" and r["status"] in ("target", "consolidator")],
                    key=lambda r: -r["score"])[:n]
        return {"deals": len(rs), "revenue_m": round(sum(r["est_revenue_m"] for r in rs)),
                "ev_m": round(sum(r["est_ev_m"] for r in rs)), "names": [r["name"] for r in rs[:6]]}
    path = [
        {"phase": "1 · US platform + density tuck-ins", **bucket(("US",), 14)},
        {"phase": "2 · Canada platform + tuck-ins", **bucket(("Canada",), 15)},
        {"phase": "3 · Europe (Nordics, DACH, UK)", **bucket(("Europe",), 6)},
    ]
    for p in path:
        p["multiple"] = round(p["ev_m"] / (p["revenue_m"] * a["ebitda_margin_pct"] / 100), 1) if p["revenue_m"] else None
    return {"regions": sorted(out, key=lambda r: -r["attractiveness"]), "sponsors": sponsors, "path": path, "canada": canada(ranked, allrows),
            "assumptions": {"rev_per_location_m": a["rev_per_location_m"], "ebitda_margin_pct": a["ebitda_margin_pct"],
                            "exit_multiple": a["exit_multiple"]},
            "method": ("Attractiveness index = supply of investable targets (max 25) + valuation, cheaper entry multiple "
                       "(max 20) + low share already consolidated (max 15) + succession signals (max 15) + market growth "
                       "(CAGR x 1.5) - share of high-risk countries. All inputs come from the map; estimates, not advice.")}


def opportunity() -> dict:
    """Scale and quality of the investable opportunity set (low/medium country risk)."""
    a = planner.assumptions()
    rk = ranking.rank(("low", "medium"))
    rows = rk["rows"]
    alln = db.q("SELECT status, region FROM targets")
    bands = [("Platform-scale", "31+ branches", lambda l: l and l > 30), ("Large tuck-in", "16–30", lambda l: l and 16 <= l <= 30),
             ("Tuck-in", "6–15", lambda l: l and 6 <= l <= 15), ("Small / unverified", "≤5 or unknown", lambda l: not l or l <= 5)]
    tiers = []
    for name, rng, f in bands:
        sel = [r for r in rows if f(r["locations"])]
        tiers.append({"name": name, "range": rng, "count": len(sel), "revenue_m": round(sum(r["est_revenue_m"] for r in sel)),
                      "multiple": round(sum(r["est_ev_m"] for r in sel) / max(1e-9, sum(r["est_ebitda_m"] for r in sel)), 1) if sel else None})
    txt = {t["id"]: f"{t['ownership'] or ''} {t['notes'] or ''}".lower() for t in db.q("SELECT id, ownership, notes FROM targets")}
    fam = sum(1 for r in rows if re.search(r"generation|family|founder|founded 19|since 19", txt.get(r["id"], "")))
    fill = sum(1 for r in rows if re.search(r"fill plant|filling|fill facility|asu|air separation|transfill|fills ", txt.get(r["id"], "")))
    known = sum(1 for r in rows if r["locations"])
    reg_rev = {}
    for r in rows:
        k = r["region"] if r["region"] in ("US", "Canada", "Europe") else "Other"
        reg_rev[k] = reg_rev.get(k, 0) + r["est_revenue_m"]
    total_rev = sum(r["est_revenue_m"] for r in rows)
    t50 = rk["tiers"]["top50"]
    return {
        "investable": len(rows), "mapped": len(alln), "excluded": sum(1 for t in alln if t["status"] in ("consolidated", "major")),
        "revenue_m": round(total_rev), "ebitda_m": round(sum(r["est_ebitda_m"] for r in rows)),
        "coverage_x": round(total_rev / a["goal_value_m"], 1),
        "tiers": tiers, "family_pct": round(100 * fam / max(1, len(rows))), "fill_count": fill, "known_branches_pct": round(100 * known / max(1, len(rows))),
        "low_risk_pct": round(100 * sum(1 for r in rows if r["risk"] == "low") / max(1, len(rows))),
        "sponsors": sum(1 for r in rows if r["status"] == "sponsor"), "platforms": sum(1 for r in rows if (r["locations"] or 0) > 30),
        "top50": t50, "exit_multiple": a["exit_multiple"],
        "region_revenue_m": {k: round(v) for k, v in reg_rev.items()}, "deals_to_goal": rk["deals_to_goal"],
    }


PROVINCES = {"ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
             "NS": "Nova Scotia", "NB": "New Brunswick", "PE": "Prince Edward Island", "NL": "Newfoundland & Labrador",
             "YT": "Yukon", "NT": "Northwest Territories", "NU": "Nunavut"}
# Provincial GDP share (Statistics Canada, approx.) - a proxy for industrial gas demand
GDP_SHARE = {"ON": 38.5, "QC": 19.6, "AB": 15.0, "BC": 13.4, "SK": 3.6, "MB": 3.1, "NS": 2.0, "NB": 1.6, "NL": 1.4, "PE": 0.4, "YT": 0.1}


def canada(ranked=None, allrows=None) -> dict:
    """White space in Canada by province: supply of investable independents vs demand (GDP share)
    and dependence on the majors (dealer agreements)."""
    ranked = ranked if ranked is not None else ranking.rank(("low", "medium", "high"))["rows"]
    allrows = allrows if allrows is not None else db.q("SELECT * FROM targets")
    txt = {t["id"]: f"{t['ownership'] or ''} {t['notes'] or ''}".lower() for t in allrows if t["region"] == "Canada"}
    inv = [r for r in ranked if r["region"] == "Canada"]
    total_rev = sum(r["est_revenue_m"] for r in inv) or 1
    out = []
    for code, name in PROVINCES.items():
        rs = [r for r in inv if (r["region_state"] or "").upper() == code]
        if not rs and code not in GDP_SHARE:
            continue
        rev = sum(r["est_revenue_m"] for r in rs)
        eb = sum(r["est_ebitda_m"] for r in rs); ev = sum(r["est_ev_m"] for r in rs)
        dealers = sum(1 for r in rs if "dealer" in txt.get(r["id"], "") or re.search(r"air liquide|linde|praxair|messer", txt.get(r["id"], "")))
        supply_share = 100 * rev / total_rev
        gdp = GDP_SHARE.get(code, 0)
        out.append({"code": code, "name": name, "targets": len(rs), "est_revenue_m": round(rev), "avg_multiple": round(ev / eb, 1) if eb else None,
                    "gdp_share_pct": gdp, "supply_share_pct": round(supply_share, 1),
                    "white_space": round(gdp - supply_share, 1),      # + = demand larger than the independent supply we can buy
                    "dealer_share_pct": round(100 * dealers / len(rs)) if rs else None,
                    "top": [{"id": r["id"], "name": r["name"], "score": r["score"], "locations": r["locations"]} for r in sorted(rs, key=lambda r: -r["score"])[:4]]})
    out.sort(key=lambda r: -r["gdp_share_pct"])
    return {"provinces": out, "targets": len(inv), "est_revenue_m": round(total_rev),
            "note": ("Supply share = province's share of the estimated revenue of investable Canadian targets on the map. "
                     "Demand proxy = share of Canadian GDP (Statistics Canada, approx.). Positive white space = demand "
                     "bigger than the independents we have found: harder to build density by acquisition there, so source "
                     "harder or enter via a platform. Negative = rich supply of targets relative to the economy. Dealer share "
                     "= targets whose notes mention a major (Air Liquide, Linde, Praxair, Messer) - check supply contracts.")}
