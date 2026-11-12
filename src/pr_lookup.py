"""Exact snapshot-scoped PR → SC lookup; no inferred or ambiguous ownership."""

PR_LOOKUP_SQL = """
SELECT DISTINCT r.po_no,r.po_pos,l.company,l.sc_no,l.sc_pos,
       l.allocation_status,s.workflow_state
FROM core.receipts r
LEFT JOIN core.sc_po_links l
  ON (l.snapshot_id,l.po_no,l.po_pos)=(r.snapshot_id,r.po_no,r.po_pos)
LEFT JOIN planning.sc_workflow_status s
  ON (s.snapshot_id,s.company,s.sc_no,s.sc_pos)=
     (l.snapshot_id,l.company,l.sc_no,l.sc_pos)
WHERE r.snapshot_id=%s AND r.receipt_no=%s
ORDER BY r.po_no,r.po_pos,l.company,l.sc_no,l.sc_pos,l.allocation_status,s.workflow_state
"""


def resolve_pr(rows):
    """Return (verified SC row, diagnostic); never guess among multiple links."""
    if not rows:
        return None, "PR no encontrado en el snapshot seleccionado."
    paths = {(r["po_no"],r["po_pos"],r["company"],r["sc_no"],r["sc_pos"])
             for r in rows}
    if len(paths) != 1:
        return None, "PR con varias asociaciones PO/SC; requiere verificar su trazabilidad."
    row = rows[0]
    if (any(r["allocation_status"] != "verified" for r in rows)
            or not all(row.get(k) for k in ("company","sc_no","sc_pos"))):
        return None, "No hay un vínculo SC/PO único y verificado para este PR."
    return row, None
