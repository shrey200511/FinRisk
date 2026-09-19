"""List every row in the flags table, sorted by fiscal year then |z-score|."""

import sqlite3

DB_PATH = "data/finrisk.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, industry, fiscal_year, metric, yoy_pct_change, z_score,
               percentile_rank, peer_count, statistical_flag, severity, distortion_caveat
        FROM flags
        ORDER BY fiscal_year, ABS(z_score) DESC
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"{'TICKER':8}{'IND':8}{'FY':6}{'METRIC':20}{'YoY%':>10}{'Z':>8}{'PCTL':>7}{'N':>4}  FLAGS")
    print("-" * 100)
    for r in rows:
        ticker, industry, fy, metric, yoy, z, pctl, n, stat_flag, severity, distortion = r
        flags_str = []
        if stat_flag:
            flags_str.append(f"STAT({severity})")
        if distortion:
            flags_str.append("DISTORTION")
        print(f"{ticker:8}{industry:8}{fy:<6}{metric:20}{yoy:>10.1f}{z:>8.2f}{pctl:>7.0f}{n:>4}  {', '.join(flags_str)}")

    print(f"\nTotal: {len(rows)} flagged rows")


if __name__ == "__main__":
    main()
