"""
Phase 1: Ingestion
Pulls company financial facts from SEC EDGAR's XBRL companyfacts API
for the retail + tech peer groups, and saves raw JSON per company.

IMPORTANT: Run this on your own machine, not in a sandbox — SEC EDGAR
requires a descriptive User-Agent with a real contact email, and rate-limits
by IP (10 req/sec max). Fill in USER_AGENT below before running.
"""

import requests
import json
import time
import os

# ---- CONFIG ----
# SEC requires a descriptive User-Agent with a real contact (name/email).
# Requests without this will get blocked (403).
USER_AGENT = "Shrey - Portfolio Project (your_email@example.com)"  # <-- fill in your email

RETAIL_TICKERS = ["WMT", "TGT", "COST", "HD", "LOW", "TJX", "BBY", "KR", "JWN"]
TECH_TICKERS = ["AAPL", "MSFT", "GOOGL", "META", "ADBE", "CRM", "ORCL", "CSCO", "INTC"]

RAW_DIR = "data/raw"
TICKER_MAP_PATH = os.path.join(RAW_DIR, "company_tickers.json")

HEADERS = {"User-Agent": USER_AGENT}
REQUEST_DELAY = 0.15  # stay comfortably under SEC's 10 req/sec limit


def get_ticker_to_cik_map():
    """Download SEC's official ticker -> CIK mapping file."""
    if os.path.exists(TICKER_MAP_PATH):
        with open(TICKER_MAP_PATH) as f:
            raw = json.load(f)
    else:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json", headers=HEADERS
        )
        resp.raise_for_status()
        raw = resp.json()
        os.makedirs(RAW_DIR, exist_ok=True)
        with open(TICKER_MAP_PATH, "w") as f:
            json.dump(raw, f)

    # raw is a dict of {index: {cik_str, ticker, title}}
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}


def fetch_company_facts(cik_padded, ticker):
    """Fetch full companyfacts JSON for a single company and save raw."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS)
    time.sleep(REQUEST_DELAY)

    if resp.status_code != 200:
        print(f"  [WARN] {ticker}: HTTP {resp.status_code} — skipping")
        return None

    data = resp.json()
    out_path = os.path.join(RAW_DIR, f"{ticker}.json")
    with open(out_path, "w") as f:
        json.dump(data, f)
    return data


def main():
    os.makedirs(RAW_DIR, exist_ok=True)

    print("Fetching ticker -> CIK map...")
    ticker_map = get_ticker_to_cik_map()

    all_tickers = [("retail", t) for t in RETAIL_TICKERS] + [
        ("tech", t) for t in TECH_TICKERS
    ]

    manifest = []
    for industry, ticker in all_tickers:
        cik = ticker_map.get(ticker)
        if not cik:
            print(f"  [WARN] {ticker}: CIK not found in SEC ticker map — skipping")
            continue

        print(f"Fetching {ticker} (CIK {cik}, {industry})...")
        data = fetch_company_facts(cik, ticker)
        if data is not None:
            manifest.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "industry": industry,
                    "entity_name": data.get("entityName", ""),
                }
            )

    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. {len(manifest)}/{len(all_tickers)} companies fetched successfully.")
    print(f"Raw files saved to {RAW_DIR}/")
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
