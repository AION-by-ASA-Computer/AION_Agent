import sqlite3
import os

def migrate():
    db_path = os.getenv("AION_DB_PATH", "data/aion.db")
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}, skipping migration.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # EvalRun
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eval_runs (
        id TEXT PRIMARY KEY,
        dataset_name TEXT NOT NULL,
        profile_name TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        overall_score REAL,
        metadata TEXT DEFAULT '{}'
    );
    """)

    # EvalResult
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eval_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        input_text TEXT NOT NULL,
        expected_output TEXT,
        actual_output TEXT,
        score REAL NOT NULL,
        reasoning TEXT,
        latency_sec REAL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES eval_runs(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()
    print("Migration V3 (Eval Tables) complete.")

if __name__ == "__main__":
    migrate()
