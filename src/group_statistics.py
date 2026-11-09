"""Group SC purchasing/warehouse KPIs, with one row per SC.

No database access here. The caller passes snapshot lines and the group's
ordered membership. ERP quantities remain Decimals; only line counts become
integers. Unknown/missing SC never masquerades as 0/0.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

COLUMNS = ("Num SC", "Descripción contextual", "Pend PO", "Pass Date",
           "Full Received", "Full Approved")
CANCELLED = frozenset(("SC anulada", "Línea SC anulada", "cancelled"))
PENDING_PO = frozenset(("Pendiente pedido", "pending_order", "no_approved_coverage"))
APPROVED = frozenset(("Completado", "complete"))


def _qty(raw):
    if raw is None or pd.isna(raw):
        return None
    try:
        value = Decimal(str(raw))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return value if value.is_finite() else None


def _day(raw):
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def group_statistics(items: pd.DataFrame, source: pd.DataFrame, today: date) -> pd.DataFrame:
    """Count unique SC lines per status; retain not-found group members."""
    if items.empty:
        return pd.DataFrame(columns=COLUMNS)
    today = _day(today)
    if today is None:
        raise ValueError("Fecha actual no válida para Pass Date.")
    needed = {"sc_no", "company", "sc_pos", "ordered_qty", "received_qty",
              "approved_qty", "requested_qty", "planned_date"}
    if not source.empty and not needed.issubset(source.columns):
        raise ValueError("Datos incompletos para estadísticas de Group SC.")
    state_field = ("workflow_state" if "workflow_state" in source
                   else "coverage_state" if "coverage_state" in source else None)
    if not source.empty and state_field is None:
        raise ValueError("Falta estado operativo en estadísticas de Group SC.")

    lines = {}
    if not source.empty:
        # Multi-PO links must already be reconciled at one row per SC line.
        # Do not inflate a denominator by joining receipt-level rows.
        for data in source.to_dict("records"):
            if any(pd.isna(data.get(key)) for key in ("sc_no", "company", "sc_pos")):
                continue
            key = (str(data["sc_no"]),str(data["company"]),str(data["sc_pos"]))
            if key in lines:
                raise ValueError(f"Posición SC duplicada en estadísticas: {key}")
            lines[key] = data
    by_sc = {}
    for (sc, _, _), data in lines.items():
        by_sc.setdefault(sc, []).append(data)

    output = []
    seen_sc = set()
    for member in items.to_dict("records"):
        sc = str(member["sc_no"])
        if sc in seen_sc:
            continue
        seen_sc.add(sc)
        desc = member.get("context_description")
        row = {"Num SC":sc,
               "Descripción contextual": "" if desc is None or pd.isna(desc) else str(desc)}
        scoped = by_sc.get(sc, [])
        if not scoped:
            row.update({name:"—" for name in COLUMNS[2:]})
            output.append(row)
            continue
        counts = dict.fromkeys(COLUMNS[2:], 0)
        total = len(scoped)
        for record in scoped:
            status = record[state_field]
            status = "" if status is None or pd.isna(status) else str(status)
            cancelled = status in CANCELLED
            ordered = _qty(record["ordered_qty"])
            received = _qty(record["received_qty"])
            requested = _qty(record["requested_qty"])
            approved = _qty(record["approved_qty"])
            # An ERP PO with 0 quantity is a cancellation, never full receipt.
            full_received = bool(
                not cancelled and ordered is not None and ordered > 0
                and received is not None and received >= ordered
            )
            full_approved = bool(
                not cancelled and status in APPROVED
                and requested is not None and requested > 0
                and approved is not None and approved >= requested
            )
            if not cancelled and status in PENDING_PO:
                counts["Pend PO"] += 1
            # No outstanding reception after the full received quantity.
            plan_date = _day(record["planned_date"])
            if (not cancelled and not full_received and ordered is not None
                    and ordered > 0 and plan_date is not None
                    and plan_date < today):
                counts["Pass Date"] += 1
            counts["Full Received"] += int(full_received)
            counts["Full Approved"] += int(full_approved)
        row.update({label:f"{count}/{total}" for label,count in counts.items()})
        output.append(row)
    return pd.DataFrame(output, columns=COLUMNS)
