import sqlite3
import os
import logging
from typing import List, Dict, Optional
import json
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "prom_agent_memory.db")


class ChatMemory:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database table if it doesn't exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL DEFAULT 'default',
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        metadata TEXT
                    )
                """)
                # Index for faster retrieval by session
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_id ON chat_messages(session_id)"
                )

                # Check if metadata column exists (migration for existing db schema evolution)
                cursor.execute("PRAGMA table_info(chat_messages)")
                columns = [info[1] for info in cursor.fetchall()]
                if "metadata" not in columns:
                    cursor.execute("ALTER TABLE chat_messages ADD COLUMN metadata TEXT")

                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize chat database: {e}")

    def save_message(
        self,
        role: str,
        content: str,
        session_id: str = "default",
        metadata: Optional[Dict] = None,
    ) -> bool:
        """Save a message to the database and ensure limit is respected."""
        try:
            metadata_json = json.dumps(metadata) if metadata else None

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content, metadata)
                    VALUES (?, ?, ?, ?)
                """,
                    (session_id, role, content, metadata_json),
                )
                conn.commit()

            # Auto-cleanup after save (Keeping last 50 messages)
            self.cleanup_session(session_id, max_messages=50)
            return True
        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
            return False

    def cleanup_session(self, session_id: str, max_messages: int = 50):
        """Delete oldest messages if count exceeds max_messages."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Check current count
                cursor.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?",
                    (session_id,),
                )
                count = cursor.fetchone()[0]

                # Delete excess oldest messages if count exceeds max_messages
                if count > max_messages:
                    excess_count = count - max_messages
                    cursor.execute(
                        """
                        DELETE FROM chat_messages 
                        WHERE id IN (
                            SELECT id FROM chat_messages 
                            WHERE session_id = ? 
                            ORDER BY id ASC 
                            LIMIT ?
                        )
                    """,
                        (session_id, excess_count),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Error cleaning up session: {e}")

    def get_history(
        self, session_id: str = "default", limit: int = 10
    ) -> List[Dict[str, str]]:
        """
        Retrieve recent messages for a session.
        Returns a list of dicts: {'role': ..., 'content': ..., 'charts': ...}
        Order: Oldest first (for context window), but retrieved via DESC limit.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT role, content, metadata 
                    FROM chat_messages 
                    WHERE session_id = ? 
                    ORDER BY id DESC 
                    LIMIT ?
                """,
                    (session_id, limit),
                )

                rows = cursor.fetchall()
                history = []
                for db_row in rows:
                    msg = {"role": db_row["role"], "content": db_row["content"]}
                    if db_row["metadata"]:
                        try:
                            meta = json.loads(db_row["metadata"])
                            if meta:
                                msg.update(meta)
                        except json.JSONDecodeError:
                            pass
                    history.append(msg)

                # Reverse to get chronological order (Oldest -> Newest)
                return history[::-1]
        except Exception as e:
            logger.error(f"Error fetching chat history: {e}")
            return []

    def clear_session(self, session_id: str = "default") -> bool:
        """Clear all messages for a specific session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error clearing chat session: {e}")
            return False


# Global instance for easy import
chat_memory = ChatMemory()
