"""
Phase 4: Flagging logic
Applies deterministic, auditable rules to the peer-benchmark z-scores from
Phase 3. No AI/ML here on purpose — this layer needs to be traceable by hand,
the same way an auditor would want to verify "why was this flagged."

Rules (documented, not hidden):
  - STATISTICAL FLAG: |z_score| >= Z_THRESHOLD (peer-relative outlier)
  - DISTORTION CAVEAT: |yoy_pct_change| >= DISTORTION_THRESHOLD_PCT
    (a huge % swing that may just reflect a tiny prior-year base, not a
    real magnitude of change - flagged as a caveat, not suppressed)
"""

import sqlite3

DB_PATH = "data/finrisk.db"

Z_THRESHOLD = 2.0            # |z| >= this -> statistically unusual vs peers
Z_HIGH_SEVERITY = 2.5        # |z| >= this -> "high" severity tier
DISTORTION_THRESHOLD_PCT = 200  # |YoY %| >= this -> flag possible low-base distortion
MIN_PEER_COUNT = 3           # already enforced in Phase 3, re-checked here for safety


def severity_tier(z):
    az = abs(z)
    if az >= Z_HIGH_SEVERITY:
        return "high"
    elif az >= Z_THRESHOLD:
        return "medium"
    return None


def load_analysis(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, industry, fiscal_year, metric, yoy_pct_change,
               peer_count, peer_mean_yoy, peer_stdev_yoy, z_score, percentile_rank
        FROM metrics_analysis
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def apply_flags(rows):
    flagged = []
    for r in rows:
        if r["peer_count"] < MIN_PEER_COUNT:
            continue  # not enough peers to trust the benchmark

        z = r["z_score"]
        severity = severity_tier(z)
        statistical_flag = severity is not None

        distortion_caveat = abs(r["yoy_pct_change"]) >= DISTORTION_THRESHOLD_PCT

        # We keep a row if it's a statistical flag, a distortion caveat, or both.
        # A distortion caveat alone (big % swing but NOT a peer outlier) is
        # still worth surfacing since a reader might otherwise assume any
        # huge % change is automatically suspicious - here we're explicit
        # that it wasn't flagged as statistically unusual vs peers.
        if not statistical_flag and not distortion_caveat:
            continue

        flagged.append({
            **r,
            "statistical_flag": statistical_flag,
            "severity": severity,
            "distortion_caveat": distortion_caveat,
        })
    return flagged


def save_flags(conn, flagged):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS flags")
    cur.execute("""
        CREATE TABLE flags (
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
            statistical_flag INTEGER,
            severity TEXT,
            distortion_caveat INTEGER,
            PRIMARY KEY (ticker, fiscal_year, metric)
        )
    """)
    for r in flagged:
        cur.execute("""
            INSERT INTO flags VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["ticker"], r["industry"], r["fiscal_year"], r["metric"],
            r["yoy_pct_change"], r["peer_count"], r["peer_mean_yoy"],
            r["peer_stdev_yoy"], r["z_score"], r["percentile_rank"],
            int(r["statistical_flag"]), r["severity"], int(r["distortion_caveat"])
        ))
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading Phase 3 analysis...")
    rows = load_analysis(conn)
    print(f"Loaded {len(rows)} company-year-metric rows.")

    print(f"\nApplying flagging rules:")
    print(f"  Statistical flag: |z-score| >= {Z_THRESHOLD} (high severity >= {Z_HIGH_SEVERITY})")
    print(f"  Distortion caveat: |YoY %| >= {DISTORTION_THRESHOLD_PCT}%")

    flagged = apply_flags(rows)
    print(f"\n{len(flagged)} rows flagged out of {len(rows)} total ({len(flagged)/len(rows)*100:.1f}%).")

    stat_only = sum(1 for f in flagged if f["statistical_flag"] and not f["distortion_caveat"])
    distortion_only = sum(1 for f in flagged if f["distortion_caveat"] and not f["statistical_flag"])
    both = sum(1 for f in flagged if f["statistical_flag"] and f["distortion_caveat"])
    print(f"  Statistical flag only: {stat_only}")
    print(f"  Distortion caveat only: {distortion_only}")
    print(f"  Both: {both}")

    high_sev = [f for f in flagged if f["severity"] == "high"]
    print(f"\n--- High severity flags ({len(high_sev)}) ---")
    for f in sorted(high_sev, key=lambda x: abs(x["z_score"]), reverse=True):
        caveat = " [DISTORTION CAVEAT]" if f["distortion_caveat"] else ""
        print(f"  {f['ticker']} FY{f['fiscal_year']} {f['metric']}: "
              f"YoY={f['yoy_pct_change']:.1f}%  z={f['z_score']:.2f}  "
              f"(industry={f['industry']}, n={f['peer_count']}){caveat}")

    print("\nSaving flags table...")
    save_flags(conn, flagged)
    conn.close()
    print(f"Done. {len(flagged)} flags saved to data/finrisk.db, table 'flags'.")


if __name__ == "__main__":
    main()
