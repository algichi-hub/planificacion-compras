"""Latest eligible snapshot is always the dashboard default by validated import ID, not source date."""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.snapshot_selection import latest_snapshot_id, ELIGIBLE_STATES

ROOT=Path(__file__).resolve().parents[1]


def snap(*rows):
    return pd.DataFrame(rows,columns=["id","snapshot_date","state"])


def test_latest_validated_date_wins():
    records=snap(
        (4,date(2026,11,1),"validated"),
        (9,date(2026,11,8),"validated"),
        (8,date(2026,11,6),"validated"),
    )
    assert latest_snapshot_id(records)==9


def test_latest_date_wins():
    records=snap(
        (10,date(2026,11,9),"validated"),
        (9,date(2026,11,8),"validated"),
    )
    assert latest_snapshot_id(records)==10


def test_latest_import_id_wins_even_if_source_date_is_older():
    records=snap(
        (11,date(2026,11,1),"validated"),
        (8,date(2026,11,6),"validated"),
        (9,date(2026,11,8),"validated"),
    )
    assert latest_snapshot_id(records)==11


def test_same_day_tie_uses_largest_id_consistently():
    records=snap(
        (12,date(2026,11,8),"validated"),
        (9,date(2026,11,8),"validated"),
        (14,date(2026,11,8),"validated"),
    )
    assert latest_snapshot_id(records)==14


def test_draft_or_rejected_is_never_used_even_if_newer():
    records=snap(
        (15,date(2026,11,15),"loading"),
        (13,date(2026,11,13),"rejected"),
        (9,date(2026,11,8),"validated"),
    )
    assert latest_snapshot_id(records)==9


def test_dates_may_be_python_date_datetime_string_or_pandas_timestamp():
    records=snap(
        (1,"2026-11-05","validated"),
        (8,datetime(2026,11,6,23,50),"validated"),
        (9,pd.Timestamp("2026-11-08"),"validated"),
    )
    assert latest_snapshot_id(records)==9


def test_invalid_missing_dates_and_ids_are_ignored_not_selected():
    records=snap(
        (22,None,"validated"),
        ("oops","2026-11-13","validated"),
        (9,"2026-11-08","validated"),
    )
    assert latest_snapshot_id(records)==9


@pytest.mark.parametrize("records", [
    snap((10,date(2026,11,9),"loading")),
    snap((8,None,"validated")),
    pd.DataFrame(columns=["id","snapshot_date","state"]),
])
def test_no_eligible_snapshot_fails_closed(records):
    with pytest.raises(ValueError,match="No existe"):
        latest_snapshot_id(records)


def test_eligible_states_are_explicit():
    assert ELIGIBLE_STATES==frozenset(("validated",))
    with pytest.raises(ValueError,match="columnas"):
        latest_snapshot_id(pd.DataFrame([{"id":9}]))


def test_app_uses_latest_validated_id_order_with_manual_sidebar_control():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "ORDER BY id DESC" in app
    assert "snapshot_ids.index(latest_id)" in app
    assert "sid=int(st.sidebar.selectbox(\"Snapshot\",snapshot_ids,index=default_idx," in app
    assert "snapshots[snapshots.state==\"active\"]" not in app
    assert "default_idx=int(active.index[0])" not in app
    assert "WHERE state='validated'" in app
    assert 'WHERE snapshot_id=%s' in app
    assert '(" (Vigente)" if int(r[\'id\'])==latest_id else "")' in app


def test_snapshot_selection_does_not_modify_db_or_change_erp():
    code=(ROOT/"src/snapshot_selection.py").read_text(encoding="utf-8")
    assert "psycopg" not in code
    assert "SELECT" not in code and "UPDATE " not in code
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert 'render_planning_timeline(sc_timeline_source,madrid_today' in app
    assert 'stat_table=group_statistics(items,stats_saved[1],today_madrid)' in app



def test_snapshot_metadata_refresh_is_isolated_from_erp_cache():
    """The default can discover a newly validated snapshot without a 10m lag."""
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert '@st.cache_data(ttl=60,show_spinner=False)\ndef available_snapshots():' in app
    metadata=app.split("def available_snapshots():",1)[1].split(
        "if not connection_string():",1
    )[0]
    assert "_read_management(" in metadata
    assert "ORDER BY id DESC" in metadata
    assert "state='validated'" in metadata
    assert "query(" not in metadata
    assert "query.clear()" not in app
    assert "st_autorefresh" not in app
    assert "snapshots=available_snapshots()" in app
