"""Initialize the local SQLite database and first Admin account."""
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("Meetbrief database is ready. Admin credentials come from ADMIN_USERNAME/ADMIN_PASSWORD.")
