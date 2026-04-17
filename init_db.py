import sqlite3
import pandas as pd
import os

DB_PATH = 'production.db'
CSV_PATH = 'data.csv'

def init_database():
    print(f"Initializing database at {DB_PATH}...")
    
    # Connect to SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Clean slate for agent log
    cursor.execute("DROP TABLE IF EXISTS agent_events;")
    cursor.execute("""
        CREATE TABLE agent_events (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            agent_name TEXT NOT NULL,
            severity TEXT CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
            order_id TEXT,
            facility_id TEXT,
            message TEXT NOT NULL,
            confidence_pct NUMERIC(5,2),
            action_taken TEXT
        );
    """)
    
    # 2. Ingest CSV data directly
    print("Loading data.csv...")
    try:
        # We try to coerce the timestamps immediately so there are no Invalid format string errors
        df = pd.read_csv(CSV_PATH)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
        # Drop rows with invalid unparseable dates
        df = df.dropna(subset=['Timestamp'])
        df = df.sort_values(by='Timestamp').reset_index(drop=True)
        
        print("Writing production_events to SQLite...")
        # This will DROP the table if it exists and recreate it flat
        df.to_sql('production_events', conn, if_exists='replace', index=False)
        
        print(f"Successfully loaded {len(df)} rows into 'production_events' table.")
    except Exception as e:
        print(f"Error loading CSV data: {e}")
        
    conn.commit()
    conn.close()
    print("Database initialization complete.")

if __name__ == "__main__":
    init_database()
