"""Read-only Group SC report using the exact Seguimiento SC presentation.

Preserve group references absent from the selected snapshot; never infer their
quantities, PO positions, dates or operational status.
"""
import pandas as pd

from src.sc_overview import overview_display


def group_overview(items, status):
    """Create SC overview rows in group order, including unmatched references."""
    if items.empty:
        return overview_display(pd.DataFrame())
    status_column = "workflow_state" if "workflow_state" in status.columns else "coverage_state"
    # One group SC may have several SC positions (and potentially companies).
    joined = items[["sc_no"]].merge(
        status, on="sc_no", how="left", sort=False, indicator=True
    )
    missing = joined["_merge"].eq("left_only")
    joined.loc[missing, status_column] = "No encontrada"
    result = overview_display(joined)
    # For a group reference not in the snapshot, retain the original SC number
    # instead of a fabricated position.
    result.loc[missing, "SC/Pos"] = joined.loc[missing, "sc_no"]
    return result
