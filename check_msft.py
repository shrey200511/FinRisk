"""
Diagnostic: check whether MSFT's operating_expenses figure switched
underlying XBRL tags between years, which would make the YoY comparison
invalid (comparing two differently-scoped numbers).
"""

import json
import sqlite3

RAW_DIR = "data/raw"
DB_PATH = "data/finrisk.db"


def dump_tag(ticker, tag):
    with open(f"{RAW_DIR}/{ticker}.json") as f:
        data = json.load(f)
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    fact_data = us_gaap.get(tag)
    print(f"\n=== {ticker} / {tag} ===")
    if not fact_data:
        print("  TAG NOT PRESENT AT ALL")
        return
    entries = fact_data.get("units", {}).get("USD", [])
    relevant = [e for e in entries if e.get("form") == "10-K" and e.get("fp") == "FY"
                and e.get("start")]
    for e in sorted(relevant, key=lambda x: x.get("end", "")):
        from datetime import date
        d1 = date.fromisoformat(e["start"])
        d2 = date.fromisoformat(e["end"])
        days = (d2 - d1).days
        if 330 <= days <= 400:
            print(f"  end={e['end']} (bucket {d2.year}) val={e['val']} filed={e['filed']}")


if __name__ == "__main__":
    print("Checking what our pipeline actually stored for MSFT:")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT fiscal_year, operating_expenses, operating_expenses_source
        FROM financials WHERE ticker = 'MSFT' ORDER BY fiscal_year
    """)
    for row in cur.fetchall():
        print(f"  FY{row[0]}: operating_expenses={row[1]:,.0f}  source={row[2]}")
    conn.close()

    dump_tag("MSFT", "OperatingExpenses")
    dump_tag("MSFT", "CostsAndExpenses")
