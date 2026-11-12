"""Read-only snapshot inventory and authenticated, atomic bulk deletion.

No schema migration: uses existing audit tables. The writer connection is only
opened after verified administrator authorization. A preview token binds the
explicit confirmation to the exact server-side deletion plan.
"""
import hashlib
import json

import psycopg

from scripts.manage_snapshots import CHILD_TABLES, count_snapshot_rows, validate_snapshot_dependencies
from src.bulk_sc import is_bulk_admin

INVENTORY_SQL = """
SELECT s.id,s.snapshot_date,s.sc_approved_from,s.state,s.created_at,
       s.importer_revision,
       (SELECT count(DISTINCT (company,sc_no)) FROM core.sc_lines WHERE snapshot_id=s.id) AS sc,
       (SELECT count(*) FROM core.sc_lines WHERE snapshot_id=s.id) AS sc_positions,
       (SELECT count(*) FROM core.po_lines WHERE snapshot_id=s.id) AS po_positions,
       (SELECT count(*) FROM core.sc_po_links WHERE snapshot_id=s.id) AS links,
       (SELECT count(*) FROM core.receipts WHERE snapshot_id=s.id) AS receptions,
       (SELECT count(*) FROM core.pr_approval_dates WHERE snapshot_id=s.id) AS approvals,
       (SELECT count(*) FROM core.incidents WHERE snapshot_id=s.id) AS incidents,
       (SELECT count(*) FROM audit.source_files WHERE snapshot_id=s.id) AS files,
       (SELECT count(*) FROM audit.import_issues WHERE snapshot_id=s.id
        AND severity='warning') AS warnings,
       (SELECT count(*) FROM audit.import_issues WHERE snapshot_id=s.id
        AND severity='error') AS errors
FROM audit.snapshots s
ORDER BY s.snapshot_date DESC,s.id DESC
"""

DETAIL_SQL = """
SELECT source_name,sha256,rows_total,rows_ok,rows_invalid
FROM audit.source_files WHERE snapshot_id=%s ORDER BY source_name
"""
ISSUES_SQL = """
SELECT source_name,line_number,severity,issue_code,details
FROM audit.import_issues WHERE snapshot_id=%s ORDER BY severity,source_name,line_number
"""
STATES_SQL = """
SELECT workflow_state,count(*) AS positions
FROM planning.sc_workflow_status WHERE snapshot_id=%s
GROUP BY workflow_state ORDER BY positions DESC
"""


def snapshot_ids(values):
    """Canonical, duplicate-free positive integer IDs; no bool or coercion."""
    ids = tuple(sorted(values))
    if not ids or any(type(value) is not int or value <= 0 for value in ids):
        raise ValueError("Selecciona identificadores de snapshots válidos.")
    if len(set(ids)) != len(ids):
        raise ValueError("La selección contiene IDs duplicados.")
    return ids


def deletion_plan(cur, ids):
    """Build an exact preflight from Neon, including the replacement snapshot."""
    ids = snapshot_ids(ids)
    validate_snapshot_dependencies(cur)
    cur.execute(
        "SELECT id,snapshot_date,state,importer_revision,source_hashes "
        "FROM audit.snapshots WHERE id=ANY(%s) ORDER BY id", (list(ids),)
    )
    metas = cur.fetchall()
    if tuple(row[0] for row in metas) != ids:
        raise ValueError("La selección ha cambiado: existe un snapshot inexistente.")
    cur.execute(
        "SELECT id,snapshot_date FROM audit.snapshots "
        "WHERE state='validated' AND id<>ALL(%s) "
        "ORDER BY snapshot_date DESC NULLS LAST,id DESC LIMIT 1", (list(ids),)
    )
    replacement = cur.fetchone()
    if replacement is None:
        raise ValueError("No se pueden eliminar todos los snapshots validados.")
    rows = []
    for sid,date,state,revision,hashes in metas:
        counts = count_snapshot_rows(cur,sid)
        rows.append({"id":sid,"date":date.isoformat(),"state":state,
                     "revision":revision,"hashes":hashes,"counts":counts})
    result = {"snapshots":rows,"remaining_id":replacement[0],
              "remaining_date":replacement[1].isoformat(),
              "total_rows":sum(sum(item["counts"].values()) for item in rows)}
    token = hashlib.sha256(
        json.dumps(result,sort_keys=True,default=str).encode("utf-8")
    ).hexdigest()
    return result,token


def delete_selected(admin_dsn, user, allowed_emails, ids, expected_token):
    """All-or-nothing deletion; fail closed on stale preview or concurrent writes."""
    if not is_bulk_admin(user,allowed_emails):
        raise PermissionError("Administrador autenticado y verificado requerido.")
    if not admin_dsn:
        raise PermissionError("No se ha configurado la credencial de eliminación.")
    ids = snapshot_ids(ids)
    if not isinstance(expected_token,str) or len(expected_token)!=64:
        raise ValueError("Es obligatoria una simulación válida antes de eliminar.")
    with psycopg.connect(admin_dsn,connect_timeout=15) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '120s'")
                # All delete operations through this service serialize. Lock
                # metadata rows as well, in stable order, before recalculation.
                cur.execute("SELECT pg_advisory_xact_lock(760711, 1)")
                cur.execute("SELECT id FROM audit.snapshots ORDER BY id FOR UPDATE")
                cur.fetchall()
                plan,token = deletion_plan(cur,ids)
                if token!=expected_token:
                    raise ValueError("Los datos han cambiado: repite la simulación.")
                for row in plan["snapshots"]:
                    cur.execute(
                        "INSERT INTO audit.snapshot_deletions "
                        "(deleted_snapshot_id,snapshot_date,importer_revision,"
                        "source_hashes,removed_rows,deleted_by) "
                        "VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s)",
                        (row["id"],row["date"],row["revision"],
                         json.dumps(row["hashes"]),json.dumps(row["counts"]),
                         str(user["email"]).strip().casefold()),
                    )
                    for table in CHILD_TABLES:
                        cur.execute(f"DELETE FROM {table} WHERE snapshot_id=%s",(row["id"],))
                        if cur.rowcount!=row["counts"][table]:
                            raise RuntimeError("Datos alterados durante el borrado; rollback.")
                    cur.execute("DELETE FROM audit.snapshots WHERE id=%s",(row["id"],))
                    if cur.rowcount!=1:
                        raise RuntimeError("Snapshot modificado durante el borrado; rollback.")
    return plan
