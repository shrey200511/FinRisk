"""
Retry narration only for flagged rows missing from the narratives table
(e.g. a row that timed out on the first pass). Reuses the same prompt logic
as narrate.py.
"""

import sqlite3
import time
import requests

DB_PATH = "data/finrisk.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are assisting a financial risk/audit analyst by writing short, \
plain-English explanations for statistically flagged year-over-year changes in public \
company financial statements. You are NOT determining whether something is fraud or \
an error - you are explaining, in the tone of an experienced auditor's workpaper note, \
what the flagged number means and what plausible business reasons might explain it, \
so a human reviewer knows what to look into next.

Rules:
- 2-4 sentences maximum.
- State the number and how it compares to peers, in plain English.
- Suggest 1-2 PLAUSIBLE explanations (e.g. "this could reflect X" or "may be linked to Y"), \
never a definitive claim of cause.
- If a distortion caveat is flagged (percentage change is very large), explicitly note that \
the percentage may be exaggerated by a small prior-year base, and that the dollar-level change \
matters more than the percentage in that case.
- Do not use hedging filler like "it's worth noting" or "it's important to remember" - just say \
the thing directly.
- Never claim certainty about what actually happened at the company - you only have the \
statistical signal, not the full context.
"""


def build_prompt(row):
    (ticker, industry, fy, metric, yoy, peer_count, peer_mean, peer_stdev,
     z, pctl, severity, distortion) = row
    distortion_note = (
        "\nNOTE: This change is also flagged as a possible low-base distortion "
        "(the percentage swing may be exaggerated by a small prior-year base value)."
        if distortion else ""
    )
    return f"""Company: {ticker} (industry: {industry})
Metric: {metric.replace('_', ' ')}
Fiscal year: {fy}
Year-over-year change: {yoy:.1f}%
Peer group: {peer_count} companies in the {industry} industry
Peer average YoY change for this metric: {peer_mean:.1f}%
Statistical significance: z-score = {z:.2f} (severity: {severity}){distortion_note}

Write a short auditor-style note explaining this flagged item."""


def get_missing_flags(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT f.ticker, f.industry, f.fiscal_year, f.metric, f.yoy_pct_change,
               f.peer_count, f.peer_mean_yoy, f.peer_stdev_yoy, f.z_score,
               f.percentile_rank, f.severity, f.distortion_caveat
        FROM flags f
        LEFT JOIN narratives n
          ON f.ticker = n.ticker AND f.fiscal_year = n.fiscal_year AND f.metric = n.metric
        WHERE n.ticker IS NULL
    """)
    return cur.fetchall()


def generate_narrative(row):
    prompt = build_prompt(row)
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        },
        timeout=180,  # longer timeout in case of another cold start
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def main():
    conn = sqlite3.connect(DB_PATH)
    missing = get_missing_flags(conn)

    if not missing:
        print("No missing narratives — all 21 flags already have one.")
        return

    print(f"Found {len(missing)} flagged row(s) missing a narrative. Retrying...\n")
    cur = conn.cursor()
    for row in missing:
        ticker, industry, fy, metric = row[0], row[1], row[2], row[3]
        print(f"{ticker} FY{fy} {metric}...", end=" ", flush=True)
        try:
            text = generate_narrative(row)
            cur.execute(
                "INSERT INTO narratives VALUES (?,?,?,?,?)",
                (ticker, fy, metric, text, f"ollama:{MODEL}")
            )
            conn.commit()
            print("done")
        except Exception as e:
            print(f"FAILED again: {e}")
        time.sleep(0.1)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
