# scripts/load_schema.py — creates the capstone tables in RDS and inserts the starter rows.
# Run ONCE from the project root:  python scripts/load_schema.py
import os
import psycopg2
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("RDS_HOST"), port=int(os.getenv("RDS_PORT")),
    dbname=os.getenv("RDS_DATABASE"), user=os.getenv("RDS_USER"),
    password=os.getenv("RDS_PASSWORD"),
    sslmode="require"   # RDS rejects unencrypted connections by default
)

with open("data/schema.sql") as f:
    sql = f.read()

# "with conn" makes this one transaction: it commits if everything succeeds and
# rolls back if anything fails, so the database is never left half-built.
with conn, conn.cursor() as cur:
    cur.execute(sql)
    for table in ["clients", "projects", "consultants", "invoices"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cur.fetchone()[0]} rows")

conn.close()