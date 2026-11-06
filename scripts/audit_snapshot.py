"""Bounded, read-only post-import coverage audit.

Run AFTER an import commits, never inside the import transaction.
A query timeout does not invalidate or roll back the already saved snapshot.
"""
import argparse
import os
import psycopg

def audit(snapshot_id, timeout_ms=30000):
    if snapshot_id < 1 or timeout_ms < 1000 or timeout_ms > 120000:
        raise ValueError("Invalid snapshot ID or timeout")
    dsn=os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not configured")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = %s",(timeout_ms,))
            cur.execute("SELECT snapshot_date,state,importer_revision,sc_approved_from FROM audit.snapshots WHERE id=%s",(snapshot_id,))
            snap=cur.fetchone()
            if not snap:
                raise SystemExit(f"Snapshot #{snapshot_id} does not exist")
            print(f"Snapshot #{snapshot_id}: {snap}",flush=True)
            try:
                cur.execute("""
                    SELECT coverage_state,count(*) FROM planning.v_sc_coverage
                    WHERE snapshot_id=%s GROUP BY coverage_state ORDER BY coverage_state
                """,(snapshot_id,))
                print("Coverage:",cur.fetchall(),flush=True)
                cur.execute("""
                    SELECT count(*) FROM planning.v_sc_coverage
                    WHERE snapshot_id=%s AND approved_qty>requested_qty
                """,(snapshot_id,))
                print("P2 excess SC:",cur.fetchone()[0],flush=True)
            except psycopg.errors.QueryCanceled:
                print("AUDIT INCOMPLETE: coverage query exceeded timeout; snapshot remains unchanged.")
                return False
    return True

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--snapshot",type=int,required=True)
    parser.add_argument("--timeout",type=int,default=30,help="Maximum seconds per query (default 30)")
    args=parser.parse_args()
    if not audit(args.snapshot,args.timeout*1000):
        raise SystemExit(2)
