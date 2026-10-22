"""
Seeds the two existing demo accounts (previously hardcoded client-side in
LoginScreen.tsx's DEMO_ACCOUNTS) as real tbl_system_users rows, now that
login/registration check real credentials via backend/app/api/users.py
instead of a client-side dictionary. Idempotent -- safe to re-run, skips any
email that already exists.

Run against any already-provisioned DB (local or remote):
    python seed_system_users.py

Requires bcrypt (added to requirements.txt/requirements-win.txt -- pip
install -r requirements-win.txt first if you haven't already). Hashes
directly with bcrypt, not passlib -- see the comment in
backend/app/api/users.py for why (a documented passlib/bcrypt version
compatibility bug).
"""

import bcrypt
import psycopg2

# Same connection convention as seed_active_insurance.py/seed_database.py.
DB_CONFIG = {
    "dbname": "agrisure_db",
    "user": "agrisure_admin",
    "password": "agrisure_password",
    "host": "localhost",
    "port": "5432",
}


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# Matches LoginScreen.tsx's former DEMO_ACCOUNTS exactly, so the same demo
# credentials shown on the login screen keep working end-to-end.
DEMO_USERS = [
    {
        "username": "a.reyes",
        "email": "a.reyes@pcic.gov.ph",
        "firstname": "Ana",
        "lastname": "L. Reyes",
        "role": "GIS Specialist",
        "password": "pcic1234",
    },
    {
        "username": "r.santos",
        "email": "r.santos@pcic.gov.ph",
        "firstname": "Ramon",
        "lastname": "B. Santos",
        "role": "System Administrator",
        "password": "pcic1234",
    },
]


def run():
    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    for u in DEMO_USERS:
        cur.execute("SELECT user_id FROM tbl_system_users WHERE email = %s", (u["email"],))
        if cur.fetchone():
            print(f"  Skipping {u['email']} -- already exists.")
            continue

        password_hash = _hash_password(u["password"])
        cur.execute(
            """
            INSERT INTO tbl_system_users (username, password_hash, email, firstname, lastname, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            """,
            (u["username"], password_hash, u["email"], u["firstname"], u["lastname"], u["role"]),
        )
        print(f"  Seeded {u['email']} ({u['role']}).")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    run()
