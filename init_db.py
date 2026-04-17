"""
init_db.py — Bootstrap the SQLite database.

Run once (or any time you need a clean slate):
    python init_db.py

What it does:
  1. Loads data.csv into production_events table (replace strategy)
  2. Recreates agent_events table (agent activity log)
  3. Creates hitl_queue table (HITL approval items)
  4. Creates monthly_spend table (Finance Agent spend tracking)
"""

import sqlite3
import pandas as pd
import os

DB_PATH  = 'production.db'
CSV_PATH = 'data.csv'


def init_database():
    print(f"Initializing database at {DB_PATH}...")
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── 1. Agent events log ─────────────────────────────────────────────────
    cursor.execute("DROP TABLE IF EXISTS agent_events;")
    cursor.execute("""
        CREATE TABLE agent_events (
            log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            agent_name     TEXT     NOT NULL,
            severity       TEXT     CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
            order_id       TEXT,
            facility_id    TEXT,
            message        TEXT     NOT NULL,
            confidence_pct NUMERIC(5,2),
            action_taken   TEXT
        );
    """)
    print("  [OK] agent_events table created")

    # ── 2. HITL approval queue ───────────────────────────────────────────────
    cursor.execute("DROP TABLE IF EXISTS hitl_queue;")
    cursor.execute("""
        CREATE TABLE hitl_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME,
            item_type   TEXT NOT NULL,          -- 'ops' or 'finance'
            source      TEXT NOT NULL,          -- agent name that escalated
            payload     TEXT NOT NULL,          -- JSON blob of the decision context
            status      TEXT DEFAULT 'pending'  -- pending / approved / rejected
        );
    """)
    print("  [OK] hitl_queue table created")

    # ── 3. Monthly spend tracker (Finance Agent) ─────────────────────────────
    cursor.execute("DROP TABLE IF EXISTS monthly_spend;")
    cursor.execute("""
        CREATE TABLE monthly_spend (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            amount_usd  REAL     NOT NULL,
            description TEXT,
            cleared_by  TEXT     -- clearance token UUID from ApprovalRouter
        );
    """)
    print("  [OK] monthly_spend table created")

    # ── 4. Ingest CSV → production_events ───────────────────────────────────
    print("  Loading " + CSV_PATH + " ...")
    try:
        df = pd.read_csv(CSV_PATH)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        df = df.dropna(subset=['Timestamp'])
        df = df.sort_values(by='Timestamp').reset_index(drop=True)
        df.to_sql('production_events', conn, if_exists='replace', index=False)
        print("  [OK] production_events: " + str(len(df)) + " rows loaded")
    except Exception as e:
        print("  [ERR] Error loading CSV: " + str(e))

    conn.commit()
    conn.close()
    print("Database initialization complete.")


if __name__ == "__main__":
    init_database()
