# FinRisk — Financial Statement Anomaly & Risk Narrator

An AI-augmented audit-analytics tool that flags statistically unusual year-over-year
changes in public companies' financial statements, benchmarks them against industry
peers, and uses a locally-hosted LLM to generate auditor-style plain-English
explanations for every flagged item — visualized in an interactive Power BI dashboard.

## What this is (and isn't)

The detection layer is **pure statistics** — peer z-scores and percentile ranks
computed in Python, with deterministic, documented thresholds. The AI's only job is
**narration**: explaining an already-flagged number in plain English. It never decides
what counts as anomalous. That separation is deliberate — it's the difference between
"AI detects fraud" (an overclaim that falls apart under scrutiny) and "statistical
rigor + AI-assisted communication" (defensible, auditable, and closer to how audit/risk
teams actually work).

## Data

- **Source**: SEC EDGAR XBRL company-facts API (real filings, not a pre-cleaned dataset)
- **Companies**: 17 public companies across two peer groups — 8 retail (WMT, TGT, COST,
  HD, LOW, TJX, BBY, KR) and 9 tech (AAPL, MSFT, GOOGL, META, ADBE, CRM, ORCL, CSCO, INTC)
- **Timeframe**: FY2020–FY2024 (chosen deliberately to include COVID-era disruption as
  a natural, non-hardcoded anomaly the model should catch on its own)
- **Metrics**: Revenue, Net Income, Operating Expenses, Gross Profit, Total Assets

## Pipeline

1. **`fetch_data.py`** — pulls raw company-facts JSON from SEC EDGAR for all 17 companies
2. **`normalize.py`** — extracts annual figures, resolves XBRL tag inconsistencies,
   derives missing metrics, validates, loads into SQLite
3. **`analyze.py`** — computes YoY % change per metric per company, then benchmarks
   each company against its industry peers (z-score + percentile rank)
4. **`flag.py`** — applies deterministic threshold rules (|z| ≥ 2.0) to flag
   statistically unusual items, plus a separate "distortion caveat" flag for any
   YoY change ≥ 200% (see *Data quality notes* below)
5. **`narrate.py`** — sends each flagged row's statistical context to a locally-hosted
   LLM (Llama 3.2 3B via Ollama) and stores a short auditor-style explanation
6. **Power BI dashboard** — 4 pages: Overview, Company Drill-down, Peer Benchmarking,
   and Flagged Anomalies (numbers + AI narrative side by side)

## Data quality notes (the honest part)

Real SEC data is messy, and this project treats that as something to document, not
paper over:

- **XBRL tag inconsistency**: not every company reports "Revenue" under the same tag
  (`Revenues` vs. `RevenueFromContractWithCustomerExcludingAssessedTax`, etc.). Handled
  via a fallback list per metric.
- **SEC's own `fy` field is unreliable**: a fiscal period ending in one calendar year can
  be mislabeled by SEC's API as belonging to a different `fy`. Fixed by deriving year
  buckets directly from each period's `end` date instead of trusting the `fy` field.
- **Missing Operating Expenses / Gross Profit tags**: some companies (e.g. Walmart,
  Kroger) don't report a standalone Gross Profit line; some (e.g. TJX) stopped tagging
  Operating Income mid-series. Where derivable (e.g. COGS + SG&A), a fallback is used —
  but **one consistent method is locked per company across all 5 years**, not chosen
  year-by-year. This matters: an early version of this pipeline let Microsoft's
  Operating Expenses figure silently switch from a broad derived measure to a much
  narrower direct tag between FY2022 and FY2023, producing a fake "-49.9% YoY" swing
  that wasn't a real business change — just two differently-scoped numbers being
  compared. Locking one method per company/metric prevents this.
- **Genuinely undisclosed data stays `NULL`**: Kroger and Oracle don't structurally
  report Gross Profit in a form this pipeline can derive. Rather than force a number,
  those company-years are left `NULL` and documented — a `NULL` you can explain is
  better than a number you can't defend.
- **Low-base distortion caveat**: a handful of flagged items (e.g. TJX's FY2022 net
  income showing a 3547.8% YoY increase) are mathematically correct but exaggerated by
  a near-zero prior-year base (TJX's FY2021 was a COVID trough). These are flagged with
  a separate `distortion_caveat` marker, and the AI narration layer is explicitly
  instructed to surface the dollar-level change as more meaningful than the percentage
  in these cases.

## Tech stack

Python (`requests`, `pandas`, `numpy`, `scipy`) · SQLite · Ollama (Llama 3.2 3B, local
inference — no external API dependency) · Power BI Desktop

## Repo structure

fetch_data.py Phase 1: SEC EDGAR ingestion
normalize.py Phase 2: cleaning, tag fallback, validation, SQLite load
analyze.py Phase 3: YoY deltas, peer z-scores/percentiles
flag.py Phase 4: rule-based anomaly flagging
narrate.py Phase 5: local LLM narration
requirements.txt
data/ SQLite database + raw JSON (gitignored where large)


## Running it locally

pip install -r requirements.txt
python fetch_data.py # edit USER_AGENT with your email first — SEC requires this
python normalize.py
python analyze.py
python flag.py
python narrate.py # requires Ollama running locally with llama3.2:3b pulled


Then open `FinRisk.pbix` in Power BI Desktop and refresh the data connection against
your local `data/finrisk.db`.