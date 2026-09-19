"""
Phase 1.5: Tag inspection
Checks which XBRL us-gaap tags each company actually has data for, across a
shortlist of candidate tags per metric. Run this after fetch_data.py.

This does NOT hit the network — it only reads the raw JSON files you already
downloaded. Output is meant to be pasted back so Phase 2's tag-fallback logic
can be written against your real data.
"""

import json
import os

RAW_DIR = "data/raw"

# Candidate tags to check per metric (most-preferred first).
# We're just checking presence here, not correctness.
CANDIDATE_TAGS = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "NetIncome": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "OperatingExpenses": [
        "OperatingExpenses",
        "CostsAndExpenses",
        "OperatingCostsAndExpenses",
    ],
    "GrossProfit": [
        "GrossProfit",
    ],
    "TotalAssets": [
        "Assets",
    ],
}


def main():
    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    with open(manifest_path) as f:
        manifest = json.load(f)

    results = {}

    for entry in manifest:
        ticker = entry["ticker"]
        path = os.path.join(RAW_DIR, f"{ticker}.json")
        with open(path) as f:
            data = json.load(f)

        us_gaap = data.get("facts", {}).get("us-gaap", {})
        available_tags = set(us_gaap.keys())

        row = {}
        for metric, candidates in CANDIDATE_TAGS.items():
            found = None
            for tag in candidates:
                if tag in available_tags:
                    found = tag
                    break
            row[metric] = found if found else "NONE FOUND"

        results[ticker] = row

    # Print a compact table
    metrics = list(CANDIDATE_TAGS.keys())
    header = "TICKER".ljust(8) + "".join(m.ljust(45) for m in metrics)
    print(header)
    print("-" * len(header))
    for ticker, row in results.items():
        line = ticker.ljust(8) + "".join(row[m].ljust(45) for m in metrics)
        print(line)

    # Also flag any company missing ANY metric entirely
    print("\n--- Companies with at least one missing metric ---")
    any_missing = False
    for ticker, row in results.items():
        missing = [m for m, tag in row.items() if tag == "NONE FOUND"]
        if missing:
            any_missing = True
            print(f"{ticker}: missing {missing}")
    if not any_missing:
        print("None — all companies have at least one candidate tag per metric.")


if __name__ == "__main__":
    main()
