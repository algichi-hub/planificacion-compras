"""Presentation-only utilities for native Streamlit SC detail tables."""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from src.status_icons import status_icon


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
    """Preserve identifiers, show quantities compactly and dates in Spanish."""
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return "—"
    if isinstance(value, Decimal):
        from src.quantity_format import format_quantity
        return format_quantity(value)
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _compact_quantity(value):
    """Use the shared lossless numeric formatter for receipt movements."""
    from src.quantity_format import format_quantity
    return format_quantity(value)


def transpose_trace(trace, workflow_state=None):
    """General SC/PO detail. Each PO appears once, without receipt rows."""
    rows = []
    if workflow_state is not None and not pd.isna(workflow_state):
        rows.append({" ": status_icon(workflow_state), "Campo": "", "Valor": display_value(workflow_state)})
    seen_orders = set()
    for _, record in trace.iterrows():
        po = (record.get("pedido"), record.get("posicion_pedido"))
        if po in seen_orders:
            continue
        seen_orders.add(po)
        rows.append({"Campo": "Pedido/pos",
                     "Valor": f"{display_value(po[0])}/{display_value(po[1])}"})
        for name in ("articulo_pedido", "proveedor", "cantidad_pedida",
                     "fecha_planificada"):
            if name in trace.columns:
                rows.append({"Campo": LABELS[name],
                             "Valor": display_value(record[name])})
    return pd.DataFrame(rows, columns=[" ", "Campo", "Valor"])


def receptions_table(trace):
    """Separate vertical table of real receptions, grouped by PO position.

    Keep each original receipt movement even if its receipt number repeats.
    Omit empty PO groups, and never invent missing receipts.
    """
    rows = []
    seen_orders = set()
    counts = {}
    for _, record in trace.iterrows():
        receipt = record.get("parte_recepcion")
        if receipt is None or pd.isna(receipt) or not str(receipt).strip():
            continue
        po = (record.get("pedido"), record.get("posicion_pedido"))
        if po not in seen_orders:
            seen_orders.add(po)
            counts[po] = 0
            rows.append({"Campo": "Pedido/pos",
                         "Valor": f"{display_value(po[0])}/{display_value(po[1])}"})
        counts[po] += 1
        rows.append({
            "Campo": f"Recepción {counts[po]}",
            "Valor": (
                f"{display_value(receipt)} "
                f"({display_value(record.get('fecha_recepcion'))}, "
                f"Re: {_compact_quantity(record.get('cantidad_recibida', record.get('cantidad_entregada')) if not pd.isna(record.get('cantidad_recibida')) else record.get('cantidad_entregada'))}, "
                f"Ap: {_compact_quantity(record.get('cantidad_aprobada'))})"
            ),
        })
    return pd.DataFrame(rows, columns=["Campo", "Valor"])


def detail_row_style(row, today, workflow_state=None):
    """Style planned dates only for unreceived material, using Madrid local day.

    Past-due = red, 0..7 days = orange, 8..14 = yellow, >14 = green.
    Planned date styling is text-only (bold, no background).
    """
    campo = row.get("Campo")
    if campo == "Fecha planificada":
        if workflow_state != "Material sin recibir":
            return [""] * len(row)
        value = row.get("Valor")
        try:
            planned = datetime.strptime(str(value), "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return [""] * len(row)
        days_remaining = (planned - today).days
        if days_remaining < 0:
            color = "#B91C1C"
        elif days_remaining <= 7:
            color = "#C2410C"
        elif days_remaining <= 14:
            color = "#A16207"
        else:
            color = "#15803D"
        return [f"color: {color}; font-weight: bold"] * len(row)
    return [""] * len(row)


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
