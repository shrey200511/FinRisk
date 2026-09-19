"""
Phase 2: Normalization + DB load
Reads raw companyfacts JSON (from Phase 1), extracts annual figures for
FY2020-FY2024, applies tag-fallback and derivation logic where direct tags
are missing, validates the result, and loads into SQLite.
"""

import json
import os
import sqlite3
from datetime import date

RAW_DIR = "data/raw"
DB_PATH = "data/finrisk.db"
YEARS = range(2020, 2025)

# Direct tag fallback lists, in preference order
TAG_CANDIDATES = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "NetIncome": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "OperatingExpenses": ["OperatingExpenses", "CostsAndExpenses"],
    "GrossProfit": ["GrossProfit"],
    "COGS": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "SGA": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
    "TotalAssets": ["Assets"],
}

# Which of the above are "instant" (point-in-time) vs "duration" (period) facts
INSTANT_METRICS = {"TotalAssets"}


def is_duration_entry(e):
    return bool(e.get("start")) and bool(e.get("end"))


def annual_entries(fact_data, metric_name, unit="USD"):
    """Return entries filtered to 10-K, full-year, correct duration/instant type.

    NOTE: We deliberately do NOT filter on SEC's own `fy` field here — it is
    unreliable (e.g. a period ending 2021-01-30 can be tagged fy=2022 if that
    figure first appeared as a prior-year comparative in a later filing).
    Instead we bucket every entry by the calendar year of its `end` date,
    which is unambiguous and always present.
    """
    entries = fact_data.get("units", {}).get(unit, [])
    out = []
    for e in entries:
        if e.get("form") != "10-K" or e.get("fp") != "FY":
            continue
        if metric_name in INSTANT_METRICS:
            if e.get("start"):  # should be instant, no start
                continue
        else:
            if not is_duration_entry(e):
                continue
            d1 = date.fromisoformat(e["start"])
            d2 = date.fromisoformat(e["end"])
            days = (d2 - d1).days
            if not (330 <= days <= 400):  # keep annual, drop quarterly/other
                continue
        out.append(e)
    return out


def year_bucket(entry):
    """Our own year bucket, derived from the period's end date rather than
    SEC's fy field. E.g. end=2022-01-29 -> bucket 2022."""
    return date.fromisoformat(entry["end"]).year


def best_value_for_fy(fact_data, metric_name, fy):
    """Get the value for a given year bucket, preferring the most recently
    filed entry if there are duplicates (e.g. restatements or the same period
    reported in multiple filings)."""
    entries = annual_entries(fact_data, metric_name)
    candidates = [e for e in entries if year_bucket(e) == fy]
    if not candidates:
        return None
    candidates.sort(key=lambda e: e.get("filed", ""), reverse=True)
    return candidates[0]["val"]


def get_metric_value(us_gaap, metric_name, fy):
    """Try each candidate tag in order, return first hit."""
    for tag in TAG_CANDIDATES[metric_name]:
        fact_data = us_gaap.get(tag)
        if not fact_data:
            continue
        val = best_value_for_fy(fact_data, metric_name, fy)
        if val is not None:
            return val, tag
    return None, None


def build_records(manifest):
    records = []
    issues = []
    methods_used = {}  # ticker -> {"operating_expenses": method, "gross_profit": method}

    for entry in manifest:
        ticker = entry["ticker"]
        industry = entry["industry"]
        with open(os.path.join(RAW_DIR, f"{ticker}.json")) as f:
            data = json.load(f)
        us_gaap = data.get("facts", {}).get("us-gaap", {})

        # Pass 1: gather every raw candidate value per year, don't decide yet.
        year_data = {}
        for fy in YEARS:
            year_data[fy] = {
                "revenue": get_metric_value(us_gaap, "Revenue", fy)[0],
                "net_income": get_metric_value(us_gaap, "NetIncome", fy)[0],
                "op_income": get_metric_value(us_gaap, "OperatingIncome", fy)[0],
                "op_exp_direct": get_metric_value(us_gaap, "OperatingExpenses", fy)[0],
                "gross_profit_direct": get_metric_value(us_gaap, "GrossProfit", fy)[0],
                "cogs": get_metric_value(us_gaap, "COGS", fy)[0],
                "sga": get_metric_value(us_gaap, "SGA", fy)[0],
                "total_assets": get_metric_value(us_gaap, "TotalAssets", fy)[0],
            }

        # Pass 2: pick ONE method per metric for this company, based on which
        # gives the most complete 5-year coverage. Locking to a single method
        # prevents silently mixing differently-scoped tags across years
        # (e.g. a narrow "OperatingExpenses" tag in later years vs. a broad
        # Revenue-OperatingIncome derivation in earlier years), which would
        # produce fake YoY swings that aren't real business changes.
        op_exp_methods = [
            ("direct", lambda yd: yd["op_exp_direct"]),
            ("derived_from_operating_income",
             lambda yd: yd["revenue"] - yd["op_income"] if yd["revenue"] is not None and yd["op_income"] is not None else None),
            ("derived_from_cogs_plus_sga",
             lambda yd: yd["cogs"] + yd["sga"] if yd["cogs"] is not None and yd["sga"] is not None else None),
        ]
        op_exp_name, op_exp_fn, op_exp_coverage = None, None, -1
        for name, fn in op_exp_methods:
            coverage = sum(1 for fy in YEARS if fn(year_data[fy]) is not None)
            if coverage > op_exp_coverage:
                op_exp_name, op_exp_fn, op_exp_coverage = name, fn, coverage

        gp_methods = [
            ("direct", lambda yd: yd["gross_profit_direct"]),
            ("derived_from_cogs",
             lambda yd: yd["revenue"] - yd["cogs"] if yd["revenue"] is not None and yd["cogs"] is not None else None),
        ]
        gp_name, gp_fn, gp_coverage = None, None, -1
        for name, fn in gp_methods:
            coverage = sum(1 for fy in YEARS if fn(year_data[fy]) is not None)
            if coverage > gp_coverage:
                gp_name, gp_fn, gp_coverage = name, fn, coverage

        methods_used[ticker] = {
            "operating_expenses": f"{op_exp_name} ({op_exp_coverage}/{len(YEARS)} years)",
            "gross_profit": f"{gp_name} ({gp_coverage}/{len(YEARS)} years)",
        }

        # Pass 3: build records using the single chosen method per metric
        for fy in YEARS:
            yd = year_data[fy]
            revenue = yd["revenue"]
            if revenue is None:
                issues.append(f"{ticker} FY{fy}: no revenue found at all — skipping year")
                continue

            op_exp = op_exp_fn(yd) if op_exp_coverage > 0 else None
            op_exp_source = op_exp_name if op_exp is not None else None
            if op_exp is None:
                issues.append(f"{ticker} FY{fy}: OperatingExpenses unavailable under company's chosen method ({op_exp_name})")

            gross_profit = gp_fn(yd) if gp_coverage > 0 else None
            gp_source = gp_name if gross_profit is not None else None
            if gross_profit is None:
                issues.append(f"{ticker} FY{fy}: GrossProfit unavailable under company's chosen method ({gp_name}) — will be NULL")

            records.append({
                "ticker": ticker,
                "industry": industry,
                "fiscal_year": fy,
                "revenue": revenue,
                "net_income": yd["net_income"],
                "operating_expenses": op_exp,
                "operating_expenses_source": op_exp_source,
                "gross_profit": gross_profit,
                "gross_profit_source": gp_source,
                "total_assets": yd["total_assets"],
            })

    return records, issues, methods_used


def validate(records):
    """Loud validation checks — same discipline as RetailPulse's load_to_db.py."""
    problems = []

    for r in records:
        # Missing critical fields
        if r["revenue"] is None or r["revenue"] <= 0:
            problems.append(f"[CRITICAL] {r['ticker']} FY{r['fiscal_year']}: invalid revenue ({r['revenue']})")
        if r["net_income"] is None:
            problems.append(f"[WARN] {r['ticker']} FY{r['fiscal_year']}: missing net income")
        if r["total_assets"] is None or r["total_assets"] <= 0:
            problems.append(f"[CRITICAL] {r['ticker']} FY{r['fiscal_year']}: invalid total assets ({r['total_assets']})")
        if r["operating_expenses"] is not None and r["operating_expenses"] < 0:
            problems.append(f"[WARN] {r['ticker']} FY{r['fiscal_year']}: negative operating expenses ({r['operating_expenses']}) — verify")

    # Coverage check: every ticker should have all 5 years
    by_ticker = {}
    for r in records:
        by_ticker.setdefault(r["ticker"], []).append(r["fiscal_year"])
    for ticker, years in by_ticker.items():
        missing_years = set(YEARS) - set(years)
        if missing_years:
            problems.append(f"[WARN] {ticker}: missing fiscal years {sorted(missing_years)}")

    return problems


def load_to_db(records):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS financials")
    cur.execute("""
        CREATE TABLE financials (
            ticker TEXT,
            industry TEXT,
            fiscal_year INTEGER,
            revenue REAL,
            net_income REAL,
            operating_expenses REAL,
            operating_expenses_source TEXT,
            gross_profit REAL,
            gross_profit_source TEXT,
            total_assets REAL,
            PRIMARY KEY (ticker, fiscal_year)
        )
    """)

    for r in records:
        cur.execute("""
            INSERT INTO financials VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            r["ticker"], r["industry"], r["fiscal_year"], r["revenue"],
            r["net_income"], r["operating_expenses"], r["operating_expenses_source"],
            r["gross_profit"], r["gross_profit_source"], r["total_assets"]
        ))

    conn.commit()
    conn.close()


def main():
    with open(os.path.join(RAW_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    print("Building records from raw data...")
    records, issues, methods_used = build_records(manifest)

    print(f"\nBuilt {len(records)} company-year records.")

    print("\n--- Method chosen per company (locked across all years) ---")
    for ticker, methods in methods_used.items():
        print(f"  {ticker}: operating_expenses={methods['operating_expenses']}, "
              f"gross_profit={methods['gross_profit']}")

    if issues:
        print(f"\n--- {len(issues)} extraction issues ---")
        for i in issues:
            print(" ", i)

    print("\nRunning validation...")
    problems = validate(records)
    if problems:
        print(f"\n--- {len(problems)} validation flags ---")
        for p in problems:
            print(" ", p)
    else:
        print("No validation issues found.")

    print("\nLoading to SQLite...")
    load_to_db(records)
    print(f"Done. Database written to {DB_PATH}")


if __name__ == "__main__":
    main()
