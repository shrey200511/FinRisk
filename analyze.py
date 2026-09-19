"""
Phase 3: Statistical analysis
Computes YoY % change per metric per company, then benchmarks each company's
YoY change against its industry peer group (z-score + percentile rank) for
each metric, for each year.

Output: a `metrics_analysis` table in the same SQLite DB, one row per
company-year-metric, ready for Phase 4's flagging logic.
"""

import sqlite3
import statistics

DB_PATH = "data/finrisk.db"
METRICS = ["revenue", "net_income", "operating_expenses", "gross_profit", "total_assets"]


def load_financials(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, industry, fiscal_year, revenue, net_income,
               operating_expenses, gross_profit, total_assets
        FROM financials
        ORDER BY ticker, fiscal_year
    """)
    rows = cur.fetchall()
    # organize as {ticker: {fiscal_year: {metric: value}}}
    data = {}
    industries = {}
    for r in rows:
        ticker, industry, fy, revenue, net_income, op_exp, gross_profit, assets = r
        industries[ticker] = industry
        data.setdefault(ticker, {})[fy] = {
            "revenue": revenue,
            "net_income": net_income,
            "operating_expenses": op_exp,
            "gross_profit": gross_profit,
            "total_assets": assets,
        }
    return data, industries


def compute_yoy(data):
    """Returns {ticker: {fiscal_year: {metric: pct_change}}}. First year per
    company has no prior year, so it's skipped (no YoY possible)."""
    yoy = {}
    for ticker, years in data.items():
        sorted_years = sorted(years.keys())
        yoy[ticker] = {}
        for i in range(1, len(sorted_years)):
            prev_fy, cur_fy = sorted_years[i - 1], sorted_years[i]
            # only compute YoY if years are consecutive (no gap)
            if cur_fy - prev_fy != 1:
                continue
            yoy[ticker][cur_fy] = {}
            for metric in METRICS:
                prev_val = years[prev_fy].get(metric)
                cur_val = years[cur_fy].get(metric)
                if prev_val is None or cur_val is None or prev_val == 0:
                    yoy[ticker][cur_fy][metric] = None
                else:
                    yoy[ticker][cur_fy][metric] = (cur_val - prev_val) / abs(prev_val) * 100
    return yoy


def percentile_rank(value, population):
    """% of population strictly below `value`, standard percentile rank."""
    if not population:
        return None
    below = sum(1 for v in population if v < value)
    return (below / len(population)) * 100


def compute_peer_benchmarks(yoy, industries):
    """For each (industry, fiscal_year, metric), compute peer mean/stdev,
    then for each company compute z-score and percentile rank vs peers."""
    results = []  # list of dicts, one per company-year-metric

    # group tickers by industry
    by_industry = {}
    for ticker, industry in industries.items():
        by_industry.setdefault(industry, []).append(ticker)

    all_years = set()
    for ticker_years in yoy.values():
        all_years.update(ticker_years.keys())

    for industry, tickers in by_industry.items():
        for fy in sorted(all_years):
            for metric in METRICS:
                # gather peer YoY values for this industry/year/metric
                peer_values = {}
                for t in tickers:
                    v = yoy.get(t, {}).get(fy, {}).get(metric)
                    if v is not None:
                        peer_values[t] = v

                if len(peer_values) < 3:
                    # not enough peers to benchmark meaningfully this year
                    continue

                values_list = list(peer_values.values())
                mean = statistics.mean(values_list)
                stdev = statistics.stdev(values_list) if len(values_list) > 1 else 0

                for ticker, val in peer_values.items():
                    z = (val - mean) / stdev if stdev > 0 else 0.0
                    pct_rank = percentile_rank(val, values_list)
                    results.append({
                        "ticker": ticker,
                        "industry": industry,
                        "fiscal_year": fy,
                        "metric": metric,
                        "yoy_pct_change": val,
                        "peer_count": len(peer_values),
                        "peer_mean_yoy": mean,
                        "peer_stdev_yoy": stdev,
                        "z_score": z,
                        "percentile_rank": pct_rank,
                    })

    return results


def save_results(conn, results):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS metrics_analysis")
    cur.execute("""
        CREATE TABLE metrics_analysis (
            ticker TEXT,
            industry TEXT,
            fiscal_year INTEGER,
            metric TEXT,
            yoy_pct_change REAL,
            peer_count INTEGER,
            peer_mean_yoy REAL,
            peer_stdev_yoy REAL,
            z_score REAL,
            percentile_rank REAL,
            PRIMARY KEY (ticker, fiscal_year, metric)
        )
    """)
    for r in results:
        cur.execute("""
            INSERT INTO metrics_analysis VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            r["ticker"], r["industry"], r["fiscal_year"], r["metric"],
            r["yoy_pct_change"], r["peer_count"], r["peer_mean_yoy"],
            r["peer_stdev_yoy"], r["z_score"], r["percentile_rank"]
        ))
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading financials...")
    data, industries = load_financials(conn)
    print(f"Loaded {len(data)} companies.")

    print("Computing YoY changes...")
    yoy = compute_yoy(data)

    print("Computing peer benchmarks (z-score + percentile rank)...")
    results = compute_peer_benchmarks(yoy, industries)
    print(f"Computed {len(results)} company-year-metric benchmark rows.")

    print("Saving to database...")
    save_results(conn, results)

    # Quick sanity summary: biggest positive and negative z-scores overall
    if results:
        sorted_by_z = sorted(results, key=lambda r: r["z_score"])
        print("\n--- Most negative z-scores (biggest underperformers vs peers) ---")
        for r in sorted_by_z[:5]:
            print(f"  {r['ticker']} FY{r['fiscal_year']} {r['metric']}: "
                  f"YoY={r['yoy_pct_change']:.1f}%  z={r['z_score']:.2f}  "
                  f"(peer mean={r['peer_mean_yoy']:.1f}%, n={r['peer_count']})")
        print("\n--- Most positive z-scores (biggest outperformers vs peers) ---")
        for r in sorted_by_z[-5:]:
            print(f"  {r['ticker']} FY{r['fiscal_year']} {r['metric']}: "
                  f"YoY={r['yoy_pct_change']:.1f}%  z={r['z_score']:.2f}  "
                  f"(peer mean={r['peer_mean_yoy']:.1f}%, n={r['peer_count']})")

    conn.close()
    print(f"\nDone. Results saved to {DB_PATH}, table 'metrics_analysis'.")


if __name__ == "__main__":
    main()
