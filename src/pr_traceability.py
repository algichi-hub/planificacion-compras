"""Read-only enrichment of hand-delivered PRs from the selected ERP snapshot.

No historical description is stored: the current snapshot is authoritative.
Every PR resolves to exactly one verified PO/SC path or receives a diagnostic.
"""

PR_RELATIONS_SQL = """
WITH settings AS (SELECT %s::bigint AS sid, %s::text[] AS prs),
receipt_keys AS (
    SELECT DISTINCT r.receipt_no, r.po_no, r.po_pos
    FROM core.receipts r
    WHERE r.snapshot_id=(SELECT sid FROM settings)
      AND r.receipt_no IN (SELECT unnest(prs) FROM settings)
),
po_keys AS (
    SELECT DISTINCT p.company,p.po_no,p.po_pos
    FROM receipt_keys r
    JOIN core.po_lines p ON p.snapshot_id=(SELECT sid FROM settings)
        AND p.po_no=r.po_no AND p.po_pos=r.po_pos
),
vendor_names AS (
    SELECT sr.fields->>'COMPAÑÍA__0' AS company,
           sr.fields->>'PEDIDO__16' AS po_no,
           sr.fields->>'POSICIÓN__17' AS po_pos,
           min(NULLIF(btrim(sr.fields->>'NOMBRE__24'),'')) AS supplier_name,
           count(DISTINCT NULLIF(btrim(sr.fields->>'NOMBRE__24'),'')) AS name_count
    FROM raw.source_rows sr
    JOIN po_keys k ON k.company=sr.fields->>'COMPAÑÍA__0'
        AND k.po_no=sr.fields->>'PEDIDO__16'
        AND k.po_pos=sr.fields->>'POSICIÓN__17'
    WHERE sr.snapshot_id=(SELECT sid FROM settings)
      AND sr.source_name='SC_FAS.csv'
    GROUP BY 1,2,3
)
SELECT DISTINCT r.receipt_no AS pr_no,r.po_no,r.po_pos,
       p.company,l.sc_no,l.sc_pos,l.allocation_status,
       s.description,s.project,v.supplier_name,v.name_count
FROM receipt_keys r
LEFT JOIN core.po_lines p
    ON p.snapshot_id=(SELECT sid FROM settings)
    AND p.po_no=r.po_no AND p.po_pos=r.po_pos
LEFT JOIN core.sc_po_links l
    ON l.snapshot_id=(SELECT sid FROM settings)
    AND l.company=p.company AND l.po_no=p.po_no AND l.po_pos=p.po_pos
LEFT JOIN core.sc_lines s
    ON s.snapshot_id=(SELECT sid FROM settings)
    AND s.company=l.company AND s.sc_no=l.sc_no AND s.sc_pos=l.sc_pos
LEFT JOIN vendor_names v
    ON v.company=p.company AND v.po_no=p.po_no AND v.po_pos=p.po_pos
ORDER BY pr_no,po_no,po_pos
"""

EMPTY = {
    "Description": "—", "Proyecto": "—", "Pedido/pos": "—",
    "Proveedor": "—",
}


def resolve_pr_relations(pr_numbers, relations):
    """One row per PR. Ambiguous/missing traceability never exposes guessed data."""
    grouped = {str(pr): [] for pr in pr_numbers}
    for row in relations:
        pr = str(row["pr_no"])
        if pr in grouped:
            grouped[pr].append(row)
    result = {}
    for pr, matches in grouped.items():
        reason = None
        if not matches:
            reason = "PR no encontrado en el snapshot vigente"
        else:
            po = {(r["po_no"], r["po_pos"]) for r in matches}
            sc = {(r["company"],r["sc_no"],r["sc_pos"]) for r in matches
                  if r.get("sc_no") is not None}
            if len(po) != 1:
                reason = "PR asociado a varias posiciones PO"
            elif any(r.get("company") is None for r in matches):
                reason = "Pedido no encontrado en el snapshot vigente"
            elif len(sc) != 1:
                reason = ("PR asociado a varias posiciones SC" if len(sc)>1
                          else "Sin vínculo SC/PO en el snapshot vigente")
            elif any(r.get("allocation_status") != "verified" for r in matches):
                reason = "Conciliación SC/PO no verificada"
            elif any(r.get("name_count") != 1 for r in matches):
                reason = "Proveedor sin nombre único en los datos originales"
            elif any(not str(r.get(k) or "").strip()
                     for r in matches for k in ("description","project","supplier_name")):
                reason = "Faltan datos de descripción, proyecto o proveedor"
            elif len({(r["description"],r["project"],r["supplier_name"])
                      for r in matches}) != 1:
                reason = "Datos descriptivos contradictorios"
        if reason:
            result[pr] = {**EMPTY, "Observaciones": reason}
        else:
            row = matches[0]
            result[pr] = {
                "Description": row["description"].strip(),
                "Proyecto": row["project"].strip(),
                "Pedido/pos": f"{row['po_no']}/{row['po_pos']}",
                "Proveedor": row["supplier_name"].strip(),
                "Observaciones": "",
            }
    return result
