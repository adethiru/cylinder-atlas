"""Central configuration. Standard library only.

Keys: the app looks for a .env file FIRST in this repo's folder, THEN in the
folder above it (the teaching staff keep theirs one level up). Only
PORTKEY_API_KEY (course key, gpt-6-luna) or OPENAI_API_KEY is used.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"
STATIC_DIR = ROOT / "static"
DEMO_SITE_DIR = ROOT / "demo_site"
DB_PATH = Path(os.environ.get("ATLAS_DB", DATA_DIR / "atlas.db"))
SEED_PATH = DATA_DIR / "targets_seed.json"


def _parse_env_file(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip().strip('"').strip("'")
        out[k] = v
    return out


ENV_FILE_USED = None
for _candidate in (ROOT / ".env", ROOT.parent / ".env"):
    if _candidate.exists():
        for _k, _v in _parse_env_file(_candidate).items():
            os.environ.setdefault(_k, _v)
        ENV_FILE_USED = str(_candidate)
        break

# ---- Model -----------------------------------------------------------------
# Course key -> Portkey + gpt-6-luna only. Own OpenAI key -> api.openai.com.
if os.environ.get("PORTKEY_API_KEY"):
    PROVIDER = "portkey"
    API_KEY_NAME = "PORTKEY_API_KEY"
    BASE_URL = "https://api.portkey.ai/v1"
    MODEL = "gpt-6-luna"
elif os.environ.get("OPENAI_API_KEY"):
    PROVIDER = "openai"
    API_KEY_NAME = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com/v1"
    MODEL = os.environ.get("ATLAS_OPENAI_MODEL", "gpt-6-luna")
else:
    PROVIDER = "none"
    API_KEY_NAME = "PORTKEY_API_KEY"
    BASE_URL = ""
    MODEL = "gpt-6-luna"

MOCK = os.environ.get("ATLAS_MOCK", "0") == "1"   # offline tests only


def api_key() -> str:
    return os.environ.get(API_KEY_NAME, "")


# ---- Prices (USD per 1M tokens). Source: course Lecture 11 / OpenAI Standard
# short-context pricing for gpt-6-luna. Input is billed as uncached input +
# cached input; output separately.
PRICES = {
    "gpt-6-luna": {"input": 0.10, "cached": 0.01, "output": 0.50},
}
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing (via MGT 409 Lecture 11)"

# ---- Guardrails --------------------------------------------------------------
MAX_SCOUT_STEPS = int(os.environ.get("ATLAS_MAX_SCOUT_STEPS", 8))      # LLM turns in the tool loop
MAX_PAGES_PER_RUN = int(os.environ.get("ATLAS_MAX_PAGES", 4))          # web pages per Scout run
PAGE_CHAR_BUDGET = int(os.environ.get("ATLAS_PAGE_CHARS", 6000))       # chars kept per page (cost lever)
MAX_FACTS = 12
RUN_TOKEN_CAP = int(os.environ.get("ATLAS_RUN_TOKEN_CAP", 120_000))    # hard stop per run
DAILY_USD_CAP = float(os.environ.get("ATLAS_DAILY_USD_CAP", 1.00))     # hard stop per day
MAX_OUTPUT_TOKENS = 2500
HTTP_TIMEOUT = 45
PORT = int(os.environ.get("ATLAS_PORT", 8765))
