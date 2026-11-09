"""Choose the newest eligible and dated ERP snapshot for the initial dashboard view.

A user's explicit sidebar choice is preserved by Streamlit; this function only
defines the default when the selector is initialized/reinitialized.
"""
import pandas as pd

ELIGIBLE_STATES = frozenset(("active", "validated"))


def latest_snapshot_id(snapshots: pd.DataFrame) -> int:
    """Latest snapshot_date wins across both eligible states; ID breaks ties."""
    required={"id","snapshot_date","state"}
    if snapshots is None or not required.issubset(snapshots.columns):
        raise ValueError("Faltan columnas de selección de snapshots.")
    valid=snapshots.loc[snapshots["state"].isin(ELIGIBLE_STATES)].copy()
    valid["snapshot_date"]=pd.to_datetime(
        valid["snapshot_date"],errors="coerce",utc=True
    )
    valid["id"]=pd.to_numeric(valid["id"],errors="coerce")
    valid=valid.dropna(subset=["snapshot_date","id"])
    if valid.empty:
        raise ValueError("No existe ningún snapshot validado o activo con fecha.")
    newest=valid.sort_values(["snapshot_date","id"],ascending=[False,False])
    return int(newest.iloc[0]["id"])
