"""Apply versioned PostgreSQL migrations to a new or existing database."""
import os
from pathlib import Path
import psycopg

ROOT=Path(__file__).resolve().parents[1]
MIGRATIONS=ROOT/"migrations"

def main():
    dsn=os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL missing")
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS audit")
                cur.execute("""CREATE TABLE IF NOT EXISTS audit.schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )""")
                cur.execute("LOCK TABLE audit.schema_migrations IN EXCLUSIVE MODE")
                cur.execute("SELECT name FROM audit.schema_migrations")
                applied={row[0] for row in cur.fetchall()}
                for path in sorted(MIGRATIONS.glob("*.sql")):
                    if path.name in applied:
                        print("SKIP",path.name)
                        continue
                    # These migrations contain plain DDL and do not embed semicolons in strings.
                    for statement in path.read_text(encoding="utf-8").split(";"):
                        if statement.strip():
                            cur.execute(statement)
                    cur.execute("INSERT INTO audit.schema_migrations(name) VALUES (%s)",(path.name,))
                    print("APPLIED",path.name)
    print("Database schema current.")

if __name__=="__main__":
    main()
