"""
Debug helper: dumps every raw entry for a given ticker + tag, so we can see
exactly what SEC returned for the years that failed extraction.
"""

import json
import os

RAW_DIR = "data/raw"


def dump(ticker, tags):
    path = os.path.join(RAW_DIR, f"{ticker}.json")
    with open(path) as f:
        data = json.load(f)
    us_gaap = data.get("facts", {}).get("us-gaap", {})

    for tag in tags:
        fact_data = us_gaap.get(tag)
        print(f"\n=== {ticker} / {tag} ===")
        if not fact_data:
            print("  TAG NOT PRESENT AT ALL")
            continue
        entries = fact_data.get("units", {}).get("USD", [])
        # only show 10-K, FY entries to keep it readable
        relevant = [e for e in entries if e.get("form") == "10-K" and e.get("fp") == "FY"]
        for e in sorted(relevant, key=lambda x: (x.get("fy", 0), x.get("filed", ""))):
            print(f"  fy={e.get('fy')} start={e.get('start')} end={e.get('end')} "
                  f"val={e.get('val')} filed={e.get('filed')} form={e.get('form')} fp={e.get('fp')}")


if __name__ == "__main__":
    print("########## REVENUE ISSUES ##########")
    dump("TJX", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"])
    dump("BBY", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"])
    dump("KR", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"])

    print("\n\n########## NET INCOME ISSUE (TGT) ##########")
    dump("TGT", ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"])

    print("\n\n########## TJX OPERATING EXPENSES ##########")
    dump("TJX", ["OperatingIncomeLoss", "SellingGeneralAndAdministrativeExpense",
                 "CostOfGoodsAndServicesSold", "CostOfRevenue", "GrossProfit",
                 "CostsAndExpenses"])
