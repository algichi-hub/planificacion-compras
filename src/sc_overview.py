"""Pure presentation helpers for the searchable SC overview.

Keep the source rows intact for position-based selection and database lookup.
"""
from datetime import date, datetime
import pandas as pd
from src.sc_row_styles import STATE_COLORS

DISPLAY_COLUMNS = (
    "Proyecto", "SC/Pos", "PO/Pos", "article", "description",
    "fecha_plan", "Sol", "Ped", "Rec", "Apr", "estado",
)


def _join_id(left, right):
    if pd.isna(left) or pd.isna(right):
        return "—"
    return f"{left}/{right}"


def overview_display(source):
    """Return exactly the requested columns, retaining source row order."""
    if source.empty:
        return pd.DataFrame(columns=list(DISPLAY_COLUMNS))
    result = pd.DataFrame(index=source.index)
    result["Proyecto"] = source["project"]
    result["SC/Pos"] = [
        _join_id(no, pos) for no, pos in zip(source["sc_no"], source["sc_pos"])
    ]
    result["PO/Pos"] = source["po_positions"].fillna("—")
    result["article"] = source["article"]
    result["description"] = source["description"]
    result["fecha_plan"] = source["planned_date"].map(
        lambda value: value.strftime("%d/%m/%Y")
        if isinstance(value, (date, datetime)) and not pd.isna(value)
        else "—"
    )
    for display, raw in (
        ("Sol", "requested_qty"),
        ("Ped", "ordered_qty"),
        ("Rec", "received_qty"),
        ("Apr", "approved_qty"),
    ):
        result[display] = source[raw]
    result["estado"] = (
        source["workflow_state"]
        if "workflow_state" in source.columns
        else source["coverage_state"]
    )
    return result.loc[:, list(DISPLAY_COLUMNS)]


def overview_row_style(row, today):
    """Pastel state for every row; red overdue date only for unreceived material."""
    background = STATE_COLORS.get(row.get("estado"))
    styles = [
        f"background-color: {background}; color: #111827"
        if background else ""
    ] * len(row)
    planned = row.get("fecha_plan")
    if row.get("estado") == "Material sin recibir" and isinstance(planned, str) and planned != "—":
        try:
            planned_date = datetime.strptime(planned, "%d/%m/%Y").date()
        except ValueError:
            planned_date = None
        if planned_date is not None and planned_date < today:
            idx = row.index.get_loc("fecha_plan")
            styles[idx] = (
                f"{styles[idx]}; color: #B91C1C; font-weight: bold"
                if styles[idx] else "color: #B91C1C; font-weight: bold"
            )
    return styles
