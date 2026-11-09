"""Review and safely delete snapshots, including the latest when an older validated fallback exists.

Usage:
    python scripts/manage_snapshots.py --list
    python scripts/manage_snapshots.py --delete 2          # dry-run, no write
    python scripts/manage_snapshots.py --delete 2 --confirm 2
"""
import argparse
import json
import os
from datetime import date
from pathlib import Path

import psycopg

# Order respects the actual foreign-key dependencies.
CHILD_TABLES = (
    "planning.sc_workflow_status",
    "core.sc_po_links",
    "core.reac_refs",
    "core.receipts",
    "core.incidents",
    "raw.source_rows",
    "audit.import_issues",
    "audit.source_files",
    "core.sc_lines",
    "core.po_lines",
)
TABLES = (*CHILD_TABLES, "audit.snapshots")


def validate_request(snapshot_id, confirmation, state):
    if not isinstance(snapshot_id, int) or snapshot_id < 1:
        raise ValueError("snapshot ID must be a positive integer")
    if state is None:
        raise ValueError(f"snapshot {snapshot_id} does not exist")
    if state not in ("validated", "rejected", "loading"):
        raise ValueError(f"unsupported snapshot state: {state}")
    if confirmation is not None and confirmation != snapshot_id:
        raise ValueError("--confirm must match --delete exactly")
    return confirmation == snapshot_id


def count_snapshot_rows(cur, snapshot_id):
    counts = {}
    for table in TABLES:
        col = "id" if table == "audit.snapshots" else "snapshot_id"
        cur.execute(f"SELECT count(*) FROM {table} WHERE {col}=%s", (snapshot_id,))
        counts[table] = cur.fetchone()[0]
    return counts


def show_plan(snapshot_id, meta, counts):
    date_value, state, importer_revision, _hashes = meta
    print(f"Snapshot #{snapshot_id} | {date_value} | {state} | {importer_revision}")
    for table, count in counts.items():
        print(f"  {table:28s} {count:>10,} rows")
    print(f"  Total rows to remove: {sum(counts.values()):,}")


def delete_snapshot(conn, snapshot_id, confirmation=None):
    """One transaction: re-check state under lock, audit, then delete children."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """SELECT snapshot_date,state,importer_revision,source_hashes
                   FROM audit.snapshots WHERE id=%s FOR UPDATE""",
                (snapshot_id,),
            )
            meta = cur.fetchone()
            execute = validate_request(snapshot_id, confirmation, meta[1] if meta else None)
            cur.execute("SELECT id FROM audit.snapshots WHERE state='validated' "
                        "ORDER BY snapshot_date DESC,id DESC LIMIT 1")
            latest=cur.fetchone()
            is_latest=bool(latest and latest[0]==snapshot_id)
            if is_latest:
                cur.execute("SELECT id FROM audit.snapshots "
                            "WHERE state='validated' AND id<>%s "
                            "ORDER BY snapshot_date DESC,id DESC LIMIT 1", (snapshot_id,))
                replacement=cur.fetchone()
            else:
                replacement=None
            counts = count_snapshot_rows(cur, snapshot_id)
            show_plan(snapshot_id, meta, counts)
            if is_latest:
                print(f"After deletion, latest validated snapshot: "
                      f"#{replacement[0]}" if replacement else
                      "WARNING: deletion would leave no validated snapshot.")
            if not execute:
                print("DRY RUN ONLY — no records were deleted.")
                return False
            if is_latest and replacement is None:
                raise ValueError("Cannot delete the only validated snapshot; "
                                 "a validated fallback is required.")

            # Store the audit in a table that does not reference the deleted snapshot.
            cur.execute(
                """INSERT INTO audit.snapshot_deletions
                   (deleted_snapshot_id,snapshot_date,importer_revision,source_hashes,removed_rows)
                   VALUES (%s,%s,%s,%s::jsonb,%s::jsonb)""",
                (snapshot_id, meta[0], meta[2], json.dumps(meta[3]),
                 json.dumps(counts)),
            )
            for table in CHILD_TABLES:
                cur.execute(f"DELETE FROM {table} WHERE snapshot_id=%s", (snapshot_id,))
                if cur.rowcount != counts[table]:
                    raise RuntimeError(f"Unexpected deletion count in {table}; transaction rolled back")
            cur.execute("DELETE FROM audit.snapshots WHERE id=%s", (snapshot_id,))
            if cur.rowcount != 1:
                raise RuntimeError("Snapshot state changed; deletion rolled back")
    print(f"Snapshot #{snapshot_id} deleted. Audit retained in audit.snapshot_deletions.")
    return True


def list_snapshots(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id,snapshot_date,state,importer_revision
               FROM audit.snapshots ORDER BY id DESC"""
        )
        rows = cur.fetchall()
    if not rows:
        print("No snapshots.")
    else:
        for sid, snap_date, state, revision in rows:
            print(f"#{sid} | {snap_date} | {state} | {revision}")


def build_parser():
    parser = argparse.ArgumentParser(description="Inspect or delete snapshots safely")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List available snapshots")
    mode.add_argument("--delete", type=int, metavar="ID",
                      help="Preview deletion of this ID (always dry-run unless --confirm ID)")
    parser.add_argument("--confirm", type=int, metavar="ID",
                        help="Actually delete only when identical to --delete ID")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.confirm is not None and args.delete is None:
        raise SystemExit("--confirm is only allowed with --delete")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not configured")
    with psycopg.connect(dsn) as conn:
        if args.list:
            list_snapshots(conn)
        else:
            delete_snapshot(conn, args.delete, args.confirm)


if __name__ == "__main__":
    main()
