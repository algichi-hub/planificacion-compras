"""Read-only Group SC report using the exact Seguimiento SC presentation.

Preserve group references absent from the selected snapshot; never infer their
quantities, PO positions, dates or operational status.
"""
import pandas as pd

from src.sc_overview import overview_display


def group_overview_source(items, status):
    """Return snapshot rows aligned to the report, retaining exact SC keys."""
    if items.empty:
        return status.iloc[:0].copy()
    status_column = "workflow_state" if "workflow_state" in status.columns else "coverage_state"
    joined = items[["sc_no"]].merge(
        status, on="sc_no", how="left", sort=False, indicator=True
    )
    missing = joined["_merge"].eq("left_only")
    joined.loc[missing, status_column] = "No encontrada"
    return joined.drop(columns=["_merge"])


def group_overview(items, status):
    """Create SC overview rows in group order, including unmatched references."""
    if items.empty:
        return overview_display(pd.DataFrame())
    joined = group_overview_source(items, status)
    result = overview_display(joined)
    missing = joined["sc_pos"].isna()
    result.loc[missing, "SC/Pos"] = joined.loc[missing, "sc_no"]
    return result
