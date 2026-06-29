from chat_memory import chat_memory
import sqlite3
import os


def reset_db():
    db_path = chat_memory.db_path
    print(f"Targeting Database: {db_path}")

    if not os.path.exists(db_path):
        print("Database file does not exist.")
        return

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            print("Dropping table 'chat_messages'...")
            cursor.execute("DROP TABLE IF EXISTS chat_messages")
            conn.commit()
            print("Table dropped.")

        print("Re-initializing database schema...")
        chat_memory._init_db()
        print("Database reset complete. All history deleted.")

    except Exception as e:
        print(f"Error resetting database: {e}")


if __name__ == "__main__":
    confirm = input("Are you sure you want to delete ALL chat history? (y/n): ")
    if confirm.lower() == "y":
        reset_db()
    else:
        print("Operation cancelled.")
