import sqlite3
import os

def migrate():
    db_path = os.getenv("AION_DB_PATH", "data/aion.db")
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}, skipping migration.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Add trace_id to messages
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN trace_id TEXT;")
        cursor.execute("CREATE INDEX idx_messages_trace ON messages(trace_id);")
        print("Added trace_id to messages.")
    except sqlite3.OperationalError as e:
        print(f"messages: {e}")

    # Add trace_id to steps (tool calls)
    try:
        cursor.execute("ALTER TABLE steps ADD COLUMN trace_id TEXT;")
        cursor.execute("CREATE INDEX idx_steps_trace ON steps(trace_id);")
        print("Added trace_id to steps.")
    except sqlite3.OperationalError as e:
        print(f"steps: {e}")

    # Add trace_id to audit_log
    try:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN trace_id TEXT;")
        cursor.execute("CREATE INDEX idx_audit_log_trace ON audit_log(trace_id);")
        print("Added trace_id to audit_log.")
    except sqlite3.OperationalError as e:
        print(f"audit_log: {e}")

    conn.commit()
    conn.close()
    print("Migration V3 complete.")

if __name__ == "__main__":
    migrate()
