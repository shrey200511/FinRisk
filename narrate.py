"""
Phase 5: AI narration (Ollama / local LLM version)
For each row in the `flags` table, sends the statistical context (company,
metric, YoY change, peer comparison, severity) to a locally-running Ollama
model and gets back a short auditor-style plain-English explanation.

Requires Ollama running locally (https://ollama.com) with a model pulled,
e.g.: ollama pull llama3.1:8b

IMPORTANT — what the AI is and isn't doing here:
The detection/flagging already happened in Phase 4 using pure statistics.
The AI's ONLY job is to narrate and contextualize an already-flagged number
in plain English — it does not decide what counts as anomalous, and it is
explicitly instructed not to assert a definitive cause, only plausible
explanations a reviewer should look into. This separation is deliberate:
the flagging stays auditable and rule-based, and the AI is a communication
layer on top of it, not a black-box detector.
"""

import sqlite3
import time
import requests

DB_PATH = "data/finrisk.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"

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


def get_flags(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, industry, fiscal_year, metric, yoy_pct_change, peer_count,
               peer_mean_yoy, peer_stdev_yoy, z_score, percentile_rank, severity,
               distortion_caveat
        FROM flags
        ORDER BY fiscal_year, ticker, metric
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
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data["message"]["content"].strip()


def save_narratives(conn, narratives):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS narratives")
    cur.execute("""
        CREATE TABLE narratives (
            ticker TEXT,
            fiscal_year INTEGER,
            metric TEXT,
            narrative TEXT,
            model TEXT,
            PRIMARY KEY (ticker, fiscal_year, metric)
        )
    """)
    for n in narratives:
        cur.execute("INSERT INTO narratives VALUES (?,?,?,?,?)", n)
    conn.commit()


def main():
    # quick check that Ollama is actually running before we start
    try:
        requests.get("http://localhost:11434", timeout=5)
    except requests.exceptions.ConnectionError:
        print("ERROR: Can't reach Ollama at localhost:11434.")
        print("Make sure Ollama is installed and running, and that you've")
        print(f"pulled the model with: ollama pull {MODEL}")
        return

    conn = sqlite3.connect(DB_PATH)
    rows = get_flags(conn)
    print(f"Generating narratives for {len(rows)} flagged rows using local model '{MODEL}'...\n")

    narratives = []
    for i, row in enumerate(rows, 1):
        ticker, industry, fy, metric = row[0], row[1], row[2], row[3]
        print(f"[{i}/{len(rows)}] {ticker} FY{fy} {metric}...", end=" ", flush=True)
        try:
            text = generate_narrative(row)
            narratives.append((ticker, fy, metric, text, f"ollama:{MODEL}"))
            print("done")
        except Exception as e:
            print(f"FAILED: {e}")
        time.sleep(0.1)

    print(f"\nGenerated {len(narratives)}/{len(rows)} narratives successfully.")

    save_narratives(conn, narratives)
    conn.close()

    print("\n--- Sample narratives ---")
    for n in narratives[:3]:
        print(f"\n{n[0]} FY{n[1]} {n[2]}:\n  {n[3]}")

    print(f"\nDone. Saved to {DB_PATH}, table 'narratives'.")


if __name__ == "__main__":
    main()
