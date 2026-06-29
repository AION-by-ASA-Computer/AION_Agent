import sqlite3
import os


def init_db(db_path="data/chat_memory.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create Chainlit basic tables for SQLAlchemyDataLayer
    # This matches the standard Chainlit SQL schema for threads and steps
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        createdAt TEXT,
        name TEXT,
        userId TEXT,
        userIdentifier TEXT,
        tags TEXT,
        metadata TEXT
    );

    CREATE TABLE IF NOT EXISTS steps (
        id TEXT PRIMARY KEY,
        threadId TEXT,
        parentId TEXT,
        createdAt TEXT,
        start TEXT,
        "end" TEXT,
        type TEXT,
        name TEXT,
        input TEXT,
        output TEXT,
        isError INTEGER,
        streaming INTEGER,
        waitForAnswer INTEGER,
        defaultOpen INTEGER,
        autoCollapse INTEGER,
        showInput TEXT,
        metadata TEXT,
        generation TEXT,
        FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS elements (
        id TEXT PRIMARY KEY,
        threadId TEXT,
        type TEXT,
        url TEXT,
        chainlitKey TEXT,
        name TEXT,
        display TEXT,
        objectKey TEXT,
        size TEXT,
        page INTEGER,
        language TEXT,
        forId TEXT,
        mime TEXT,
        metadata TEXT,
        FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
    );

    -- Also include our custom AION history table for messages
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id);
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database AION inizializzato con successo: {db_path}")


if __name__ == "__main__":
    init_db()
