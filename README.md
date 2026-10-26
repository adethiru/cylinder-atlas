# Cylinder Atlas

**For a private equity professional building a $1 billion global platform in industrial gas distribution through acquisitions.** The map shows about 700 real gas companies across North America, Latin America, Europe (including the Nordics), the Middle East and Africa, and Asia Pacific. Four AI agents do the work:

- **Scout:** reads each target's own website and records facts with verbatim quotes.
- **Screener:** scores the target against the acquisition thesis.
- **Analyst:** writes the investment case, a risk assessment with mitigations, and a draft letter to the owner.
- **Strategist:** sequences the acquisitions on the path to $1bn revenue.

Author: Ade Thiruchandran · MGT 409 AI Foundations final project · Model: `gpt-6-luna` via the course Portkey key.

---

## Run it (about 2 minutes, nothing to install)

You need **Python 3.9 or newer**. Check with `python3 --version`. The app uses only the Python standard library, so there is no `pip install`. The browser needs internet access to load the map.

1. **Clone the repo**
   ```bash
   git clone https://github.com/adethiru/cylinder-atlas.git
   cd cylinder-atlas
   ```
2. **Add the key.** The app looks for a `.env` file **first in this folder, then in the folder above it**. The teaching staff's `submissions/.env` therefore works as-is. If you don't have one:
   ```bash
   cp .env.example .env      # then paste your PORTKEY_API_KEY
   ```
3. **Start the app**
   ```bash
   python3 app.py
   ```
   Your browser should open http://127.0.0.1:8765. If it doesn't, open that address yourself. On a Mac you can also double-click `start.command`.
   Port in use? Run `python3 app.py --port 8800`.
4. **Try it (about 5 minutes).** The **How to Use** tab (second tab) explains every tab. Quick tour:
   - **Target List:** Top 20 / Top 50 with an indicative valuation for each company. Click a **score** to see where every point comes from; tick companies to **Compare side by side** or **Research selected** (batch deal desk, with a cost estimate first); **Import CSV** to load your own list (broker, PitchBook) and **Export CSV** for Excel.
   - **Run the deal desk:** open a company (for example *Red Ball Oxygen* or *Lampton Welding Supply*) and click **▶ Run deal desk**. The Scout reads the company's real website, the Screener scores it and the Analyst writes the case, risks with mitigations and a draft owner letter. Nothing is ever sent.
   - **Pipeline:** click **Track** (or use a company's **Deal** tab) to move it through Sourced → Contacted → Meeting → NDA → IOI/LOI → Diligence → Closed, with next steps, due dates, a deal log and your own revenue/EBITDA (which replace the estimates everywhere).
   - **Path to $1B:** **Send to Path to $1B** from the Target List, then read the revenue bridge, capital required and **returns (IRR, MOIC, value bridge, sensitivity)**. Click **Run Roll-up Strategist** for a phased plan.
   - **Strategy:** regional scorecard and **Canada white space by province**. On the map, **Competitor coverage** shades 150 miles around every rival.
   - **Tokenomics / Safety:** real token counts and dollars per run; guard tests and a live prompt-injection test against a booby-trapped fictional site.

The repo includes `data/atlas.db` with my real runs already loaded, so you can see finished analyses, token logs and guard events right away. To start from a clean database instead, run `python3 app.py --reset`.

## What's inside

| Path | What it is |
|---|---|
| `app.py` | Starts the web server |
| `atlas/agents.py` | The four agents (Scout, Screener, Analyst, Strategist) and the orchestrator |
| `atlas/tools.py` | The real tools: `fetch_page` (target's own website), `read_investor_notes`, `record_fact` |
| `atlas/safety.py` | Prompt-injection filter, domain allow-list, quote verifier, key redaction |
| `atlas/llm.py` | Portkey/OpenAI client, token and cost meter, budget kill-switch |
| `atlas/planner.py` | Roll-up maths: EBITDA bridge, synergies, multiples, gap to goal, sponsor returns (IRR, MOIC, sensitivity) |
| `atlas/ranking.py` | Transparent 0–100 pre-screen with a point-by-point breakdown, indicative valuation, country-risk tiers |
| `atlas/strategy.py` | Regional scorecard, opportunity set, Canada white space by province |
| `atlas/server.py` | JSON API, pipeline tracking, CSV export (with spreadsheet formula-injection protection) |
| `prompts/` | `thesis.md` (shared, cached prefix) plus one prompt per agent |
| `data/targets_seed.json` | The target universe. Every row cites a public source |
| `demo_site/` | A **fictional** distributor website containing hidden prompt-injection attacks (safety test) |
| `tests/test_offline.py` | Offline checks with a mock model: `python3 tests/test_offline.py` |
| `experiments/` | `cost_vs_quality.py` (page-budget experiment) and `export_evidence.py` (dumps real token logs) |

## Data

The seed file is small (about 700+ companies), so there's no separate test dataset. It combines several public sources, and every row cites one:

- **Current IWDC member directory (2026):** 150+ independent North American distributors with their listed locations, plus the 2014 directory for historical members.
- **Hand-researched rows** from company sites and trade press (gasworld, MDM, GAWDA Media).
- **International rows** from the EIGA member list and targeted research covering Europe (including the Nordics), the Middle East and Africa, Latin America, India and Asia Pacific.
- **Meritus Gas Partners' portfolio**, marked as already consolidated.
- **Private equity-owned rivals** (secondary-buyout candidates), with the sponsor and how long it has held the business.

The data is company-level only, with no personal contacts. Ownership and size are checked at run time by the Scout. Ownership and size marked "verify" are confirmed at run time by the Scout from the company's own website. You can add targets by clicking the map, and you can paste teaser or call notes into a target; the Scout treats those as trusted input.

## Keys and safety

- **Keys:** only `PORTKEY_API_KEY` (gpt-6-luna) or `OPENAI_API_KEY` is used, and keys are never written to disk or shown in the UI. `.env` is git-ignored.
- **Budget:** by default the app stops at $1.00 per day and 120,000 tokens per run. Both limits can be changed on the Tokenomics tab.
- **Outreach:** letters are drafts only; the app has no ability to send email.

## Using it for real deal work

Double-click **`6 Start my private ATLAS.command`** (in the folder above the repo). It runs a private copy at http://127.0.0.1:8766 whose database lives in `My ATLAS data/` **outside the repo**, so your pipeline, notes and figures are never uploaded to GitHub. A dated backup is saved each time it starts (last 20 kept). Or run `ATLAS_DB=/path/to/your.db python3 app.py`.
