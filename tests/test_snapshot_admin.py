"""Snapshot-admin security, batch-atomicity and UI regression guards."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.snapshot_admin import deletion_plan, delete_selected, snapshot_ids, INVENTORY_SQL


class PlanCursor:
    def __init__(self, *, new_dependency=False, no_fallback=False):
        self.statement = ""
        self.new_dependency = new_dependency
        self.no_fallback = no_fallback

    def execute(self, sql, params=None):
        self.statement = sql
        self.params = params

    def fetchall(self):
        if "pg_constraint" in self.statement:
            from scripts.manage_snapshots import CHILD_TABLES
            tables = list(CHILD_TABLES)
            if self.new_dependency:
                tables.append("core.future_table")
            return [(name,) for name in tables]
        if "FROM audit.snapshots WHERE id=ANY" in self.statement:
            return [(13, date(2026,11,11),"validated","revision",{"SC_FAS.csv":"a"})]
        raise AssertionError(self.statement)

    def fetchone(self):
        if "state='validated'" in self.statement:
            return None if self.no_fallback else (11,date(2026,11,8))
        if "count(*)" in self.statement:
            return (3,)
        raise AssertionError(self.statement)


@pytest.mark.parametrize("bad", [[],[0],[-2],[True],[1,1],["12"],[1,"2"]])
def test_ids_fail_closed(bad):
    with pytest.raises((ValueError,TypeError)):
        snapshot_ids(bad)


def test_selected_ids_are_sorted_and_not_duplicated():
    assert snapshot_ids([13,8,11])==(8,11,13)


def test_preview_exact_rows_and_replacement():
    plan,token=deletion_plan(PlanCursor(),[13])
    assert plan["remaining_id"]==11
    assert plan["remaining_date"]=="2026-11-08"
    assert plan["total_rows"]>0
    assert len(token)==64
    again,token2=deletion_plan(PlanCursor(),[13])
    assert token==token2 and plan==again


def test_preview_blocks_last_validated():
    with pytest.raises(ValueError,match="todos los snapshots validados"):
        deletion_plan(PlanCursor(no_fallback=True),[13])


def test_preview_aborts_if_new_table_dependent_on_snapshot_appears():
    with pytest.raises(ValueError,match="core.future_table"):
        deletion_plan(PlanCursor(new_dependency=True),[13])


def test_delete_rejects_unauthorized_before_connection():
    with patch("src.snapshot_admin.psycopg.connect") as connect:
        with pytest.raises(PermissionError):
            delete_selected("postgres://x",{}, "admin@example.com",(13,), "0"*64)
        connect.assert_not_called()


def test_delete_rejects_unconfigured_writer_before_connection():
    user={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    with patch("src.snapshot_admin.psycopg.connect") as connect:
        with pytest.raises(PermissionError):
            delete_selected(None,user,"admin@example.com",(13,),"0"*64)
        connect.assert_not_called()


def test_delete_requires_valid_preview_token():
    user={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    with patch("src.snapshot_admin.psycopg.connect") as connect:
        with pytest.raises(ValueError):
            delete_selected("postgres://x",user,"admin@example.com",(13,),"")
        connect.assert_not_called()


def test_inventory_is_read_only_and_bounded_to_selected_tab():
    path=Path(__file__).resolve().parents[1]/"app.py"
    app=path.read_text(encoding="utf-8")
    assert 'key="main_sections",on_change="rerun"' in app
    assert "if tab7.open:" in app
    assert "snapshot_admin_inventory()" in app
    assert "SNAPSHOT_ADMIN_DATABASE_URL" in app
    assert "is_bulk_admin(snap_identity, snap_emails)" in app
    assert 'st.session_state.pop("snapshot_admin_plan",None)' in app
    assert 'available_snapshots.clear()' in app
    assert "query.clear()" not in app
    assert "DELETE FROM " not in INVENTORY_SQL.upper()
    assert "UPDATE " not in INVENTORY_SQL.upper()


def test_batch_deletion_explicit_atomic_transaction_and_audit():
    import inspect
    code=inspect.getsource(delete_selected)
    assert "with conn.transaction()" in code
    assert "pg_advisory_xact_lock" in code
    assert "FOR UPDATE" in code
    assert code.index("deletion_plan(cur,ids)") < code.index(
        "INSERT INTO audit.snapshot_deletions")
    assert code.index("token!=expected_token") < code.index("INSERT INTO audit.snapshot_deletions")
    assert "cur.rowcount!=row[\"counts\"][table]" in code
    assert "deleted_by" in code
    assert "st." not in code
