"""Tiny JSON API + static file server (standard library http.server)."""
from __future__ import annotations

import json
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import agents, config, db, llm, planner, ranking, safety, safetytests, strategy
from urllib.parse import parse_qs

EDITABLE = ("website", "locations", "investor_notes", "status", "ownership", "notes", "name", "city", "country", "region", "lat", "lon",
            "deal_stage", "next_step", "next_date", "known_revenue_m", "known_ebitda_m", "deal_contact_role")
DEAL_FIELDS = ("deal_stage", "next_step", "next_date", "known_revenue_m", "known_ebitda_m", "deal_contact_role")


def _num(v):
    try:
        return float(v) if str(v).strip() not in ("", "None", "null") else None
    except ValueError:
        return None


def pipeline() -> dict:
    a = planner.assumptions()
    rows = db.q("SELECT * FROM targets WHERE deal_stage IS NOT NULL AND deal_stage != ''")
    out = []
    for t in rows:
        v = ranking.valuation(t, a)
        out.append({"id": t["id"], "name": t["name"], "city": t["city"], "region_state": t["region_state"], "country": t["country"],
                    "region": t["region"], "status": t["status"], "locations": t["locations"], "deal_stage": t["deal_stage"],
                    "next_step": t["next_step"] or "", "next_date": t["next_date"] or "", "deal_contact_role": t["deal_contact_role"] or "",
                    "stage_changed": t["stage_changed"], "score": t["score"], "outreach_status": t["outreach_status"],
                    "prob": db.STAGE_PROB.get(t["deal_stage"], 0), "fin_basis": v["fin_basis"],
                    "est_revenue_m": v["est_revenue_m"], "est_ebitda_m": v["est_ebitda_m"], "est_ev_m": v["est_ev_m"],
                    "entry_multiple": v["entry_multiple"], "log": json.loads(t["deal_log"] or "[]")[-3:]})
    live = [r for r in out if r["deal_stage"] not in ("Passed",)]
    return {"stages": db.DEAL_STAGES, "prob": db.STAGE_PROB, "rows": out, "goal_m": a["goal_value_m"],
            "totals": {"active": sum(1 for r in live if r["deal_stage"] != "Closed"), "closed": sum(1 for r in out if r["deal_stage"] == "Closed"),
                       "revenue_m": round(sum(r["est_revenue_m"] for r in live), 1),
                       "weighted_revenue_m": round(sum(r["est_revenue_m"] * r["prob"] for r in live), 1),
                       "closed_revenue_m": round(sum(r["est_revenue_m"] for r in out if r["deal_stage"] == "Closed"), 1),
                       "weighted_ev_m": round(sum(r["est_ev_m"] * r["prob"] for r in live), 1)}}


# approximate centroids used to place imported companies when no coordinates are given
CENTROIDS = {
    "AL": (32.8, -86.8), "AK": (61.4, -152.3), "AZ": (34.2, -111.7), "AR": (34.9, -92.4), "CA": (37.2, -119.5), "CO": (39.0, -105.5),
    "CT": (41.6, -72.7), "DE": (39.0, -75.5), "FL": (28.6, -82.4), "GA": (32.7, -83.4), "HI": (20.8, -156.3), "ID": (44.4, -114.6),
    "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.1, -93.5), "KS": (38.5, -98.4), "KY": (37.5, -85.3), "LA": (31.1, -92.0),
    "ME": (45.4, -69.2), "MD": (39.0, -76.8), "MA": (42.3, -71.8), "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7),
    "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8), "NV": (39.3, -116.6), "NH": (43.7, -71.6), "NJ": (40.2, -74.7),
    "NM": (34.4, -106.1), "NY": (42.9, -75.5), "NC": (35.6, -79.4), "ND": (47.5, -100.5), "OH": (40.3, -82.8), "OK": (35.6, -97.5),
    "OR": (43.9, -120.6), "PA": (40.9, -77.8), "RI": (41.7, -71.5), "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.9, -86.4),
    "TX": (31.5, -99.3), "UT": (39.3, -111.7), "VT": (44.1, -72.7), "VA": (37.5, -78.9), "WA": (47.4, -120.5), "WV": (38.6, -80.6),
    "WI": (44.6, -89.9), "WY": (43.0, -107.6),
    "ON": (44.5, -79.5), "QC": (46.8, -71.5), "BC": (49.5, -123.0), "AB": (52.5, -114.0), "MB": (50.0, -97.5), "SK": (51.5, -105.5),
    "NS": (45.0, -63.0), "NB": (46.3, -66.2), "PE": (46.3, -63.2), "NL": (47.6, -53.0),
    "USA": (39.5, -98.4), "United States": (39.5, -98.4), "Canada": (45.5, -75.0), "Mexico": (23.6, -102.5), "United Kingdom": (52.5, -1.5),
    "UK": (52.5, -1.5), "Ireland": (53.3, -7.7), "Germany": (51.2, 10.4), "France": (46.6, 2.3), "Italy": (42.8, 12.6), "Spain": (40.2, -3.6),
    "Portugal": (39.6, -8.0), "Netherlands": (52.2, 5.5), "Belgium": (50.6, 4.6), "Switzerland": (46.8, 8.2), "Austria": (47.6, 14.1),
    "Denmark": (56.0, 9.5), "Sweden": (59.3, 15.5), "Norway": (60.5, 9.0), "Finland": (62.0, 25.7), "Poland": (52.1, 19.4),
    "Czechia": (49.8, 15.5), "Australia": (-33.0, 147.0), "New Zealand": (-41.0, 174.0), "Japan": (36.2, 138.3), "Singapore": (1.35, 103.8),
    "Brazil": (-15.8, -47.9), "Chile": (-33.4, -70.6), "Colombia": (4.6, -74.1), "UAE": (24.4, 54.4), "Saudi Arabia": (24.7, 46.7),
    "South Africa": (-26.2, 28.0), "India": (21.0, 78.0), "Malaysia": (3.1, 101.7), "Thailand": (13.7, 100.5), "China": (31.2, 121.5),
}
EUROPE = {"United Kingdom", "UK", "Ireland", "Germany", "France", "Italy", "Spain", "Portugal", "Netherlands", "Belgium", "Switzerland",
          "Austria", "Denmark", "Sweden", "Norway", "Finland", "Poland", "Czechia", "Czech Republic", "Luxembourg", "Iceland", "Estonia",
          "Latvia", "Lithuania", "Hungary", "Greece", "Slovakia", "Slovenia", "Romania", "Bulgaria", "Croatia", "Serbia", "Malta", "Cyprus"}
LATAM = {"Mexico", "Brazil", "Chile", "Colombia", "Peru", "Argentina", "Uruguay", "Costa Rica", "Panama", "Guatemala", "Dominican Republic", "Ecuador"}
MEA = {"UAE", "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Oman", "Bahrain", "South Africa", "Egypt", "Nigeria", "Kenya",
       "Morocco", "Jordan", "Turkey", "Israel", "Pakistan"}


def _region_for(country: str) -> str:
    c = (country or "").strip()
    if c in ("USA", "United States", "US", "Puerto Rico", ""):
        return "US"
    if c == "Canada":
        return "Canada"
    if c in EUROPE:
        return "Europe"
    if c in LATAM:
        return "Latin America"
    if c in MEA:
        return "Middle East"
    return "China & SEA"


def import_targets(rows: list[dict]) -> dict:
    """Bulk-add companies you sourced elsewhere (e.g. a PitchBook / broker list). Needs at least a name.
    Companies whose name already exists are skipped. Location falls back to the state/province or country centroid."""
    import random
    existing = {t["name"].strip().lower() for t in db.q("SELECT name FROM targets")}
    added, skipped = [], []
    for r in rows[:500]:
        g = lambda *ks: next((str(r[k]).strip() for k in r if k and k.strip().lower() in ks and r[k] not in (None, "")), "")
        name = g("name", "company", "company name", "target")[:120]
        if not name or name.lower() in existing:
            skipped.append(name or "(no name)")
            continue
        country = g("country") or "USA"
        country = {"US": "USA", "United States of America": "USA", "CA": "Canada"}.get(country, country)
        state = g("state", "province", "state/province", "region_state").upper()[:3]
        try:
            lat, lon = float(g("lat", "latitude")), float(g("lon", "lng", "longitude"))
        except ValueError:
            c = CENTROIDS.get(state) or CENTROIDS.get(country) or (0.0, 0.0)
            lat, lon = c[0] + random.uniform(-0.6, 0.6), c[1] + random.uniform(-0.6, 0.6)
        locs = g("branches", "locations", "sites")
        tid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] + "_" + str(int(time.time() * 1000) % 100000)
        stage = g("deal stage", "stage")
        db.x("INSERT INTO targets (id,name,website,city,region_state,country,region,lat,lon,status,ownership,locations,notes,source,updated,deal_stage)"
             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (tid, name, g("website", "url", "web"), g("city", "hq city"), state, country, _region_for(country), lat, lon, "target",
              g("ownership", "owner type") or "Unknown - run the Scout", int(float(locs)) if re.match(r"^\d+(\.0)?$", locs) else None,
              g("notes", "description")[:2000], "imported by user", time.time(), stage if stage in db.DEAL_STAGES else ""))
        for k, col in (("revenue", "known_revenue_m"), ("revenue $m", "known_revenue_m"), ("ebitda", "known_ebitda_m"), ("ebitda $m", "known_ebitda_m")):
            v = g(k)
            if v:
                try:
                    db.x(f"UPDATE targets SET {col}=? WHERE id=?", (float(v.replace(",", "").replace("$", "")), tid))
                except ValueError:
                    pass
        existing.add(name.lower())
        added.append(tid)
    return {"added": len(added), "skipped": skipped[:50], "skipped_n": len(skipped), "ids": added}


def _csv(rows: list[dict], cols: list[tuple[str, str]]) -> bytes:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for h, _ in cols])
    for r in rows:
        vals = []
        for _, k in cols:
            v = r.get(k)
            if isinstance(v, list):
                v = "; ".join(str(x) for x in v)
            v = "" if v is None else str(v)
            if v[:1] in ("=", "+", "-", "@") and not re.match(r"^-?[\d.]+$", v):   # block spreadsheet formula injection
                v = "'" + v
            vals.append(v)
        w.writerow(vals)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")



def status() -> dict:
    return {
        "provider": config.PROVIDER, "model": config.MODEL, "has_key": bool(config.api_key()) or config.MOCK,
        "mock": config.MOCK,
        "env_file": ("this folder" if config.ENV_FILE_USED and config.ENV_FILE_USED.startswith(str(config.ROOT) + "/.env")
                     else ("parent folder" if config.ENV_FILE_USED else "none found")),
        "prices": config.PRICES, "price_source": config.PRICE_SOURCE,
        "daily_usd_cap": float(db.get_setting("daily_usd_cap", config.DAILY_USD_CAP)),
        "run_token_cap": int(db.get_setting("run_token_cap", config.RUN_TOKEN_CAP)),
        "spend_today": round(llm.spend_today(), 6),
        "limits": {"max_scout_steps": config.MAX_SCOUT_STEPS, "max_pages": config.MAX_PAGES_PER_RUN,
                   "page_chars": config.PAGE_CHAR_BUDGET, "max_facts": config.MAX_FACTS},
    }


def run_detail(run_id: int) -> dict:
    r = db.q("SELECT * FROM runs WHERE id=?", (run_id,))
    if not r:
        return {}
    steps = db.q("SELECT * FROM steps WHERE run_id=? ORDER BY id", (run_id,))
    use = db.q("SELECT agent, COUNT(*) calls, SUM(input_tokens) input, SUM(cached_tokens) cached, SUM(output_tokens) output,"
               " SUM(cost_usd) cost FROM usage WHERE run_id=? GROUP BY agent ORDER BY MIN(id)", (run_id,))
    return {"run": r[0], "steps": steps, "usage": use}


def usage_summary() -> dict:
    by_agent = db.q("SELECT agent, COUNT(*) calls, SUM(input_tokens) input, SUM(cached_tokens) cached, SUM(output_tokens) output,"
                    " SUM(cost_usd) cost FROM usage GROUP BY agent")
    runs = db.q("SELECT r.id, r.kind, r.target_id, r.status, r.started, r.finished, t.name,"
                " (SELECT SUM(input_tokens) FROM usage u WHERE u.run_id=r.id) input,"
                " (SELECT SUM(cached_tokens) FROM usage u WHERE u.run_id=r.id) cached,"
                " (SELECT SUM(output_tokens) FROM usage u WHERE u.run_id=r.id) output,"
                " (SELECT COUNT(*) FROM usage u WHERE u.run_id=r.id) calls,"
                " (SELECT SUM(cost_usd) FROM usage u WHERE u.run_id=r.id) cost"
                " FROM runs r LEFT JOIN targets t ON t.id=r.target_id ORDER BY r.id DESC LIMIT 50")
    tot = db.q("SELECT COUNT(*) calls, SUM(input_tokens) input, SUM(cached_tokens) cached, SUM(output_tokens) output, SUM(cost_usd) cost FROM usage")[0]
    return {"by_agent": by_agent, "runs": runs, "total": tot, "spend_today": llm.spend_today()}


class Handler(BaseHTTPRequestHandler):
    server_version = "CylinderAtlas/1.0"

    def log_message(self, *a):  # quiet console
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _static(self, rel: str):
        base = config.STATIC_DIR.resolve()
        f = (base / rel).resolve()
        if not str(f).startswith(str(base)) or not f.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p in ("/", "/index.html"):
                return self._static("index.html")
            if p.startswith("/static/"):
                return self._static(p[len("/static/"):])
            if p.startswith("/demo/"):
                m = re.match(r"^/demo/([a-z]+)/?([a-z]*)$", p)
                if m:
                    f = config.DEMO_SITE_DIR / m.group(1) / ((m.group(2) or "index") + ".html")
                    if f.is_file():
                        html = f.read_text().replace('href="local:', 'href="/demo/').replace("local:evergreen", "/demo/evergreen")
                        return self._send(200, html.encode(), "text/html")
                return self._send(404, {"error": "not found"})
            if p == "/api/ranking":
                qs = parse_qs(urlparse(self.path).query)
                risks = tuple((qs.get("risk", ["low,medium"])[0] or "low,medium").split(","))
                regs = qs.get("region", [""])[0]
                lim = qs.get("limit", [""])[0]
                return self._send(200, ranking.rank(risks, tuple(regs.split(",")) if regs else None, int(lim) if lim.isdigit() else None))
            if p == "/api/pipeline":
                return self._send(200, pipeline())
            if p == "/api/batch":
                b = agents.batch_status()
                avg = db.q("SELECT AVG(c) a FROM (SELECT SUM(u.cost_usd) c FROM usage u JOIN runs r ON r.id=u.run_id WHERE r.kind='deal_desk' GROUP BY u.run_id)")[0]["a"]
                b["avg_cost_per_target"] = round(avg, 5) if avg else None
                b["spend_today"] = round(llm.spend_today(), 5)
                b["daily_usd_cap"] = float(db.get_setting("daily_usd_cap", config.DAILY_USD_CAP))
                return self._send(200, b)
            if p in ("/api/export/targets.csv", "/api/export/pipeline.csv"):
                qs = parse_qs(urlparse(self.path).query)
                if p.endswith("targets.csv"):
                    risks = tuple((qs.get("risk", ["low,medium"])[0] or "low,medium").split(","))
                    regs = qs.get("region", [""])[0]
                    rows = ranking.rank(risks, tuple(regs.split(",")) if regs else None)["rows"]
                    cols = [("Rank", "rank"), ("Company", "name"), ("City", "city"), ("State/Province", "region_state"), ("Country", "country"),
                            ("Region", "region_label"), ("Type", "status"), ("Country risk", "risk"), ("Branches", "locations"),
                            ("Est. revenue $m", "est_revenue_m"), ("Est. EBITDA $m", "est_ebitda_m"), ("Financials basis", "fin_basis"),
                            ("Entry multiple x", "entry_multiple"), ("Est. EV $m", "est_ev_m"), ("Value created $m", "value_created_m"),
                            ("Cumulative revenue $m", "cum_revenue_m"), ("Score", "score"), ("Agent score", "agent_score"),
                            ("Why", "why"), ("Ownership", "ownership"), ("Deal stage", "deal_stage"), ("Next step", "next_step"),
                            ("Next date", "next_date"), ("Website", "website")]
                    name = "atlas_targets.csv"
                else:
                    rows = pipeline()["rows"]
                    for r in rows:
                        r["last_note"] = r["log"][-1]["text"] if r["log"] else ""
                    cols = [("Company", "name"), ("City", "city"), ("State/Province", "region_state"), ("Country", "country"),
                            ("Stage", "deal_stage"), ("Probability", "prob"), ("Next step", "next_step"), ("Next date", "next_date"),
                            ("Contact (role)", "deal_contact_role"), ("Est. revenue $m", "est_revenue_m"), ("Est. EBITDA $m", "est_ebitda_m"),
                            ("Financials basis", "fin_basis"), ("Entry multiple x", "entry_multiple"), ("Est. EV $m", "est_ev_m"), ("Last note", "last_note")]
                    name = "atlas_pipeline.csv"
                data = _csv(rows, cols)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if p == "/api/opportunity":
                return self._send(200, strategy.opportunity())
            if p == "/api/strategy":
                return self._send(200, strategy.analyze())
            if p == "/api/excluded":
                f = config.DATA_DIR / "excluded.json"
                ex = json.loads(f.read_text(encoding="utf-8"))["excluded"] if f.exists() else []
                mapped = db.q("SELECT name, ownership, country, region FROM targets WHERE status IN ('consolidated','major')")
                return self._send(200, {"excluded_research": ex, "on_map": mapped})
            if p == "/api/letter-template":
                return self._send(200, {"template": db.get_setting("letter_template") or "", "default": True if not db.get_setting("letter_template") else False})
            if p == "/api/outreach":
                return self._send(200, db.q("SELECT id,name,city,region_state,country,region,score,outreach_status,analysis_json,updated FROM targets WHERE analysis_json IS NOT NULL ORDER BY updated DESC"))
            if p == "/api/thesis":
                return self._send(200, {"markdown": (config.PROMPTS_DIR / "thesis.md").read_text(encoding="utf-8")})
            if p == "/api/status":
                return self._send(200, status())
            if p == "/api/targets":
                rows = db.q("SELECT t.*, (SELECT COUNT(*) FROM facts f WHERE f.target_id=t.id AND f.verified=1) facts_n FROM targets t")
                return self._send(200, rows)
            m = re.match(r"^/api/targets/([\w\-]+)$", p)
            if m:
                tid = m.group(1)
                t = db.q("SELECT * FROM targets WHERE id=?", (tid,))
                if not t:
                    return self._send(404, {"error": "unknown target"})
                facts = db.q("SELECT * FROM facts WHERE target_id=? ORDER BY id", (tid,))
                runs = db.q("SELECT id,status,started FROM runs WHERE target_id=? ORDER BY id DESC LIMIT 5", (tid,))
                return self._send(200, {"target": t[0], "facts": facts, "runs": runs})
            if p == "/api/plan":
                return self._send(200, {"plan": planner.compute(), "order": db.get_setting("plan_order", []),
                                        "strategy": db.get_setting("strategy")})
            m = re.match(r"^/api/runs/(\d+)$", p)
            if m:
                return self._send(200, run_detail(int(m.group(1))))
            if p == "/api/usage":
                return self._send(200, usage_summary())
            if p == "/api/security":
                return self._send(200, db.q("SELECT * FROM security_events ORDER BY id DESC LIMIT 100"))
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": safety.redact(str(e), [config.api_key()])})

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        p = urlparse(self.path).path
        if self.headers.get("Origin") and "127.0.0.1" not in self.headers["Origin"] and "localhost" not in self.headers["Origin"]:
            return self._send(403, {"error": "cross-origin request blocked"})
        try:
            b = self._body()
            if p == "/api/targets":
                name = (b.get("name") or "").strip()
                if not name:
                    return self._send(400, {"error": "name required"})
                tid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] + "_" + str(int(time.time()) % 10000)
                db.x("INSERT INTO targets (id,name,website,city,region_state,country,region,lat,lon,status,ownership,locations,notes,source,updated)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (tid, name, b.get("website", ""), b.get("city", ""), "", b.get("country", ""), b.get("region", "US"),
                      float(b["lat"]), float(b["lon"]), "target", b.get("ownership", "Unknown - run the Scout"),
                      int(b["locations"]) if str(b.get("locations", "")).strip().isdigit() else None,
                      b.get("notes", ""), "added by user", time.time()))
                return self._send(200, {"id": tid})
            m = re.match(r"^/api/targets/([\w\-]+)/(update|run|approve|reject|plan|log)$", p)
            if m:
                tid, action = m.groups()
                if not db.q("SELECT id FROM targets WHERE id=?", (tid,)):
                    return self._send(404, {"error": "unknown target"})
                if action == "update":
                    cur = db.q("SELECT deal_stage, deal_log FROM targets WHERE id=?", (tid,))[0]
                    for k, v in b.items():
                        if k in EDITABLE:
                            if k == "locations":
                                v = int(v) if str(v).strip().isdigit() else None
                            if k in ("known_revenue_m", "known_ebitda_m"):
                                v = _num(v)
                            if k == "deal_stage":
                                v = v if v in db.DEAL_STAGES else ""
                            if k in ("next_step", "deal_contact_role"):
                                v = str(v)[:300]
                            if k == "next_date" and v and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
                                v = ""
                            db.x(f"UPDATE targets SET {k}=?, updated=? WHERE id=?", (v, time.time(), tid))
                    if "deal_stage" in b and (b["deal_stage"] or "") != (cur["deal_stage"] or ""):
                        log = json.loads(cur["deal_log"] or "[]")
                        log.append({"ts": time.time(), "text": f"Stage: {cur['deal_stage'] or 'not tracked'} → {b['deal_stage'] or 'not tracked'}", "auto": True})
                        db.x("UPDATE targets SET deal_log=?, stage_changed=? WHERE id=?", (json.dumps(log[-200:]), time.time(), tid))
                    return self._send(200, {"ok": True})
                if action == "log":
                    text = str(b.get("text", "")).strip()[:2000]
                    if not text:
                        return self._send(400, {"error": "empty note"})
                    log = json.loads(db.q("SELECT deal_log FROM targets WHERE id=?", (tid,))[0]["deal_log"] or "[]")
                    log.append({"ts": time.time(), "text": text})
                    db.x("UPDATE targets SET deal_log=?, updated=? WHERE id=?", (json.dumps(log[-200:]), time.time(), tid))
                    return self._send(200, {"log": log})
                if action == "run":
                    pc = b.get("page_chars")
                    return self._send(200, {"run_id": agents.start_deal_desk(tid, int(pc) if pc else None)})
                if action == "approve":
                    db.x("UPDATE targets SET outreach_status='approved', stage='outreach approved' WHERE id=?", (tid,))
                    return self._send(200, {"ok": True})
                if action == "reject":
                    db.x("UPDATE targets SET outreach_status='rejected' WHERE id=?", (tid,))
                    return self._send(200, {"ok": True})
                if action == "plan":
                    order = db.get_setting("plan_order", []) or []
                    if b.get("add", True) and tid not in order:
                        order.append(tid)
                    if not b.get("add", True):
                        order = [x for x in order if x != tid]
                    db.set_setting("plan_order", order)
                    return self._send(200, {"order": order})
            if p == "/api/batch/start":
                return self._send(200, agents.start_batch([str(x) for x in b.get("ids", [])]))
            if p == "/api/targets/import":
                return self._send(200, import_targets(b.get("rows", [])))
            if p == "/api/plan/order":
                db.set_setting("plan_order", [str(x) for x in b.get("order", [])])
                return self._send(200, {"ok": True})
            if p == "/api/plan/top":
                n = int(b.get("n", 20))
                risks = tuple(b.get("risk", ["low", "medium"]))
                regs = tuple(b["regions"]) if b.get("regions") else None
                rows = ranking.rank(risks, regs)["rows"][:n]
                order, skipped = planner.sequence(rows)
                db.set_setting("plan_order", order)
                return self._send(200, {"order": order, "skipped": skipped})
            if p == "/api/plan/auto":
                order, skipped = planner.auto_build(db.get_setting("plan_order", []) or [])
                db.set_setting("plan_order", order)
                return self._send(200, {"order": order, "skipped": skipped})
            if p == "/api/plan/assumptions":
                cur = planner.assumptions()
                for k, v in b.items():
                    if k in planner.DEFAULTS:
                        cur[k] = v if k == "goal_type" else float(v)
                db.set_setting("planner_assumptions", cur)
                return self._send(200, planner.compute())
            if p == "/api/test-model":
                try:
                    m = llm.chat([{"role": "user", "content": "Reply with exactly: connection OK"}], agent="health")
                    return self._send(200, {"ok": True, "reply": m.get("content"), "usage": m.get("_usage")})
                except Exception as e:  # noqa: BLE001
                    return self._send(200, {"ok": False, "error": safety.redact(str(e), [config.api_key()])})
            if p == "/api/strategy/run":
                return self._send(200, {"run_id": agents.start_strategy()})
            if p == "/api/settings":
                if "daily_usd_cap" in b:
                    db.set_setting("daily_usd_cap", max(0.0, float(b["daily_usd_cap"])))
                if "letter_template" in b:
                    db.set_setting("letter_template", str(b["letter_template"])[:6000])
                if "run_token_cap" in b:
                    db.set_setting("run_token_cap", max(1000, int(b["run_token_cap"])))
                return self._send(200, status())
            if p == "/api/safety-tests":
                return self._send(200, safetytests.run_all(live=bool(b.get("live"))))
            if p == "/api/reset":
                db.init(reset=True)
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": safety.redact(str(e), [config.api_key()])})


def serve(port: int) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.serve_forever()
