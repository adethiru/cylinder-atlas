"""SQLite storage (standard library). One file: data/atlas.db, created from the
seed JSON on first run. Delete it (or use the Reset button) to start fresh."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date

from . import config

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
  id TEXT PRIMARY KEY, name TEXT, website TEXT, city TEXT, region_state TEXT,
  country TEXT, region TEXT, lat REAL, lon REAL, status TEXT, ownership TEXT,
  locations INTEGER, notes TEXT, source TEXT, investor_notes TEXT DEFAULT '',
  stage TEXT DEFAULT 'new', score REAL, screen_json TEXT, analysis_json TEXT,
  outreach_status TEXT DEFAULT 'none', in_plan INTEGER DEFAULT 0, updated REAL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT, field TEXT, value TEXT,
  quote TEXT, source_url TEXT, verified INTEGER, created REAL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, target_id TEXT, status TEXT,
  started REAL, finished REAL, summary TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, ts REAL, agent TEXT,
  kind TEXT, title TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, ts REAL, day TEXT,
  agent TEXT, model TEXT, input_tokens INTEGER, cached_tokens INTEGER,
  output_tokens INTEGER, cost_usd REAL
);
CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id INTEGER, kind TEXT,
  target_id TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
"""

# Deal-tracking fields the investor maintains (never touched by the seed refresh or the agents)
DEAL_STAGES = ["Sourced", "Contacted", "Meeting held", "NDA signed", "IOI / LOI", "Diligence", "Closed", "Passed"]
STAGE_PROB = {"Sourced": 0.05, "Contacted": 0.10, "Meeting held": 0.20, "NDA signed": 0.30, "IOI / LOI": 0.50,
              "Diligence": 0.75, "Closed": 1.0, "Passed": 0.0}
DEAL_COLS = {"deal_stage": "TEXT DEFAULT ''", "next_step": "TEXT DEFAULT ''", "next_date": "TEXT DEFAULT ''",
             "deal_log": "TEXT DEFAULT '[]'", "known_revenue_m": "REAL", "known_ebitda_m": "REAL",
             "deal_contact_role": "TEXT DEFAULT ''", "stage_changed": "REAL"}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init(reset: bool = False) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if reset and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    fresh = not config.DB_PATH.exists()
    with _LOCK, connect() as c:
        c.executescript(SCHEMA)
        # migrations: deal-tracking columns (your own pipeline data)
        have = {r[1] for r in c.execute("PRAGMA table_info(targets)").fetchall()}
        for col, decl in DEAL_COLS.items():
            if col not in have:
                c.execute(f"ALTER TABLE targets ADD COLUMN {col} {decl}")
        if True:  # add any seed rows not yet in the DB (keeps your research on existing rows)
            raw = config.SEED_PATH.read_text(encoding="utf-8")
            seed = json.loads(raw)["targets"]
            import hashlib
            h = hashlib.sha1(raw.encode()).hexdigest()
            row = c.execute("SELECT v FROM settings WHERE k='seed_hash'").fetchone()
            if row is None or json.loads(row[0]) != h:
                # seed file changed: refresh seed fields on rows you have not researched yet
                for t in seed:
                    c.execute("UPDATE targets SET name=?,website=?,city=?,region_state=?,country=?,region=?,lat=?,lon=?,status=?,ownership=?,locations=?,notes=?,source=?"
                              " WHERE id=? AND stage='new'",
                              (t["name"], t.get("website", ""), t.get("city", ""), t.get("region_state", ""), t.get("country", ""), t["region"],
                               t["lat"], t["lon"], t["status"], t.get("ownership", ""), t.get("locations"), t.get("notes", ""), t.get("source", ""), t["id"]))
            c.execute("INSERT OR REPLACE INTO settings (k,v) VALUES ('seed_hash',?)", (json.dumps(h),))
            for t in seed:
                c.execute(
                    "INSERT OR IGNORE INTO targets (id,name,website,city,region_state,country,region,lat,lon,status,ownership,locations,notes,source,updated)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t["id"], t["name"], t.get("website", ""), t.get("city", ""), t.get("region_state", ""),
                     t.get("country", ""), t["region"], t["lat"], t["lon"], t["status"], t.get("ownership", ""),
                     t.get("locations"), t.get("notes", ""), t.get("source", ""), time.time()))


def q(sql: str, args=()) -> list[dict]:
    with _LOCK, connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def x(sql: str, args=()) -> int:
    with _LOCK, connect() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def today() -> str:
    return date.today().isoformat()


def get_setting(k: str, default=None):
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    return json.loads(r[0]["v"]) if r else default


def set_setting(k: str, v) -> None:
    x("INSERT OR REPLACE INTO settings (k,v) VALUES (?,?)", (k, json.dumps(v)))


def add_step(run_id, agent, kind, title, detail="") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, indent=2, default=str)
    x("INSERT INTO steps (run_id,ts,agent,kind,title,detail) VALUES (?,?,?,?,?,?)",
      (run_id, time.time(), agent, kind, title, detail[:6000]))


def security_event(kind, detail, run_id=None, target_id=None) -> None:
    x("INSERT INTO security_events (ts,run_id,kind,target_id,detail) VALUES (?,?,?,?,?)",
      (time.time(), run_id, kind, target_id, str(detail)[:2000]))
