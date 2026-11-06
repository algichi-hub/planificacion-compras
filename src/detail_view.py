"""Presentation-only utilities for native Streamlit SC detail tables."""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd


LABELS = {
    "pedido": "Pedido",
    "posicion_pedido": "Posición pedido",
    "articulo_pedido": "Artículo pedido",
    "proveedor": "Proveedor",
    "cantidad_pedida": "Cantidad pedida",
    "fecha_planificada": "Fecha planificada",
    "parte_recepcion": "Parte de recepción",
    "fecha_recepcion": "Fecha recepción",
    "cantidad_entregada": "Cantidad entregada",
    "cantidad_aprobada": "Cantidad aprobada",
    "estado_recepcion": "Estado recepción",
    "estado_vinculo": "Estado vínculo",
    "referencias_reac": "Referencias REAC",
    "numero_incidencias": "Número de incidencias",
}


def display_value(value):
    """Keep identifiers intact, display decimals with comma for Spanish users."""
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return "—"
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", ",")
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _compact_quantity(value):
    """Preserve decimal precision without unnecessary trailing zeros."""
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, Decimal):
        return (format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")).replace(".", ",")
    return str(value).replace(".", ",") if isinstance(value, float) else str(value)


def transpose_trace(trace, workflow_state=None):
    """One vertical SC-status row, PO fields once, then one row per receipt.

    The source query is ordered by PO and receipt date. All actual receipt
    movements are preserved, including repeated receipt numbers. Rows with
    no receipt are not mistakenly counted as a reception.
    """
    rows = []
    if workflow_state is not None and not pd.isna(workflow_state):
        rows.append({"Campo": "Estado SC", "Valor": display_value(workflow_state)})
    seen_orders = set()
    receipt_count = {}
    for _, record in trace.iterrows():
        po = (record.get("pedido"), record.get("posicion_pedido"))
        if po not in seen_orders:
            seen_orders.add(po)
            receipt_count[po] = 0
            rows.append({"Campo": "Pedido", "Valor": display_value(po[0])})
            for name in ("posicion_pedido", "articulo_pedido", "proveedor",
                         "cantidad_pedida", "fecha_planificada"):
                if name in trace.columns:
                    rows.append({
                        "Campo": LABELS[name],
                        "Valor": display_value(record[name]),
                    })
        receipt = record.get("parte_recepcion")
        if receipt is not None and not pd.isna(receipt) and str(receipt).strip():
            receipt_count[po] += 1
            rows.append({
                "Campo": f"Recepción {receipt_count[po]}",
                "Valor": (
                    f"{display_value(receipt)} "
                    f"({display_value(record.get('fecha_recepcion'))}, "
                    f"{_compact_quantity(record.get('cantidad_aprobada'))}, "
                    f"{_compact_quantity(record.get('cantidad_entregada'))})"
                ),
            })
    return pd.DataFrame(rows, columns=["Campo", "Valor"])


def vertical_records(frame, title, labels=None):
    """Render independent INC/REAC records vertically, without merging distinct events."""
    labels = labels or {}
    entries = []
    for number, (_, record) in enumerate(frame.iterrows(), start=1):
        entries.append({"Campo": f"{title} {number}", "Valor": ""})
        for field, value in record.items():
            entries.append({
                "Campo": labels.get(field, field.replace("_", " ").capitalize()),
                "Valor": display_value(value),
            })
    return pd.DataFrame(entries, columns=["Campo", "Valor"])
