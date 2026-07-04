from sqlalchemy import text
from database import engine

def migrate():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE telegram_user_states ADD COLUMN last_notified_count INTEGER DEFAULT 0"))
            print("Migration successful.")
        except Exception as e:
            print("Migration failed:", e)

if __name__ == "__main__":
    migrate()
