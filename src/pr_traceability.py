"""Read-only enrichment of hand-delivered PRs from the selected ERP snapshot.

No historical description is stored: the current snapshot is authoritative.
Every PR resolves to exactly one verified PO/SC path or receives a diagnostic.
"""

PR_RELATIONS_SQL = """
SELECT pr_no,po_no,po_pos,company,sc_no,sc_pos,
       allocation_status,description,project,supplier_name,name_count
FROM planning.v_pr_delivery_relations
WHERE snapshot_id=%s AND pr_no=ANY(%s)
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
