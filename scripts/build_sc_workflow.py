"""Compute SC material states per snapshot, without altering imported source tables.

Default is a read-only simulation. --commit explicitly refreshes the derived
planning.sc_workflow_status cache, which requires migration 007.
"""
import argparse
import os
from pathlib import Path
import psycopg

QUERY=(Path(__file__).resolve().parents[1]/"sql"/"sc_workflow_select.sql").read_text(encoding="utf-8")
PARAMETERS=6

def classify(conn, snapshot_id, commit=False):
    if snapshot_id < 1:
        raise ValueError("snapshot id must be positive")
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM audit.snapshots WHERE id=%s",(snapshot_id,))
        row=cur.fetchone()
        if not row or row[0] not in ("validated","active"):
            raise ValueError("Snapshot must exist and be validated or active")
        args=(snapshot_id,)*PARAMETERS
        if commit:
            cols=("snapshot_id,company,sc_no,sc_pos,article,description,project,"
                  "requested_qty,ordered_qty,received_qty,approved_qty,linked_po,"
                  "has_reac,incident_open,workflow_state,workflow_issue")
            updated=("article,description,project,requested_qty,ordered_qty,received_qty,"
                     "approved_qty,linked_po,has_reac,incident_open,workflow_state,workflow_issue")
            updates=", ".join(f"{col}=EXCLUDED.{col}" for col in updated.split(","))
            cur.execute(f"""
              INSERT INTO planning.sc_workflow_status ({cols})
              SELECT {cols} FROM ({QUERY}) AS classified WHERE true
              ON CONFLICT (snapshot_id,company,sc_no,sc_pos)
              DO UPDATE SET {updates},computed_at=now()
            """,args)
            print("Derived SC status cache updated:",cur.rowcount,flush=True)
            cur.execute("""SELECT workflow_state,count(*) FROM planning.sc_workflow_status
                           WHERE snapshot_id=%s GROUP BY 1 ORDER BY 2 DESC""",(snapshot_id,))
        else:
            cur.execute(f"SELECT workflow_state,count(*) FROM ({QUERY}) AS classified GROUP BY 1 ORDER BY 2 DESC",args)
        groups=cur.fetchall()
        cur.execute("SELECT count(*) FROM core.sc_lines WHERE snapshot_id=%s",(snapshot_id,))
        expected=cur.fetchone()[0]
        actual=sum(n for _,n in groups)
        if actual != expected:
            raise ValueError(f"Classification cardinality mismatch: {actual} vs {expected}")
        for state,count in groups:
            print(f"{state}: {count}")
        print(f"TOTAL: {actual}")
        return dict(groups)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--snapshot",type=int,required=True)
    parser.add_argument("--commit",action="store_true",help="Explicitly write only derived status rows")
    args=parser.parse_args()
    dsn=os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    with psycopg.connect(dsn) as conn:
        classify(conn,args.snapshot,args.commit)
        if not args.commit:
            conn.rollback()
            print("DRY RUN: no data changed")

if __name__=="__main__":
    main()
