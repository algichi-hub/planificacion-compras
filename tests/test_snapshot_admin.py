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


def test_confirmed_batch_rechecks_preview_and_audits_every_snapshot():
    from contextlib import contextmanager
    import hashlib

    class FakeConn:
        def __init__(self, wrong_count=False):
            self.actions=[]
            self.wrong_count=wrong_count
            self.completed=False
            self.rolled_back=False
            self.rowcount=1

        def __enter__(self): return self
        def __exit__(self,*args): return False
        @contextmanager
        def transaction(self):
            try:
                yield self
            except Exception:
                self.rolled_back=True
                raise
            else:
                self.completed=True
        def cursor(self): return self
        def execute(self,sql,params=None):
            self.actions.append((sql,params))
            if sql.startswith("DELETE FROM"):
                self.rowcount=0 if self.wrong_count else 1
            else:
                self.rowcount=1
        def fetchall(self): return [(8,),(13,)]
        def fetchone(self): return (not getattr(self,"index_missing",False),)

    plan = {"snapshots":[
        {"id":8,"date":"2026-11-06","revision":"v1","hashes":{},
         "counts":{table:1 for table in (
             __import__("scripts.manage_snapshots",fromlist=["TABLES"]).TABLES)}},
        {"id":13,"date":"2026-11-11","revision":"v1","hashes":{},
         "counts":{table:1 for table in (
             __import__("scripts.manage_snapshots",fromlist=["TABLES"]).TABLES)}},
    ],"remaining_id":11}
    token=hashlib.sha256(b"plan").hexdigest()
    user={"is_logged_in":True,"email_verified":True,"email":"Admin@Example.com"}

    conn=FakeConn()
    with patch("src.snapshot_admin.psycopg.connect",return_value=conn):
        with patch("src.snapshot_admin.deletion_plan",return_value=(plan,token)):
            output=delete_selected("postgres://x",user,"admin@example.com",(8,13),token)
    assert output["remaining_id"]==11
    assert conn.completed and not conn.rolled_back
    assert len([a for a in conn.actions if "INSERT INTO audit.snapshot_deletions" in a[0]])==2
    assert len([a for a in conn.actions if a[0].startswith("DELETE FROM audit.snapshots")])==2
    assert all(a[1][-1]=="admin@example.com" for a in conn.actions
               if "INSERT INTO audit.snapshot_deletions" in a[0])

    stale=FakeConn()
    with patch("src.snapshot_admin.psycopg.connect",return_value=stale):
        with patch("src.snapshot_admin.deletion_plan",return_value=(plan,"1"*64)):
            with pytest.raises(ValueError,match="repite la simulación"):
                delete_selected("postgres://x",user,"admin@example.com",(8,13),token)
    assert stale.rolled_back and not stale.completed
    assert not any(a[0].startswith("DELETE FROM") for a in stale.actions)

    changed=FakeConn(wrong_count=True)
    with patch("src.snapshot_admin.psycopg.connect",return_value=changed):
        with patch("src.snapshot_admin.deletion_plan",return_value=(plan,token)):
            with pytest.raises(RuntimeError,match="rollback"):
                delete_selected("postgres://x",user,"admin@example.com",(8,13),token)
    assert changed.rolled_back and not changed.completed


def test_preview_uses_admin_connection_and_read_only_transaction():
    from contextlib import contextmanager
    from src.snapshot_admin import preview_selected
    class Cursor:
        def __init__(self): self.queries=[]
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,sql): self.queries.append(sql)
    class Connection:
        def __init__(self): self.cur=Cursor()
        def __enter__(self): return self
        def __exit__(self,*args): return False
        @contextmanager
        def transaction(self):
            yield self
        def cursor(self): return self.cur
    conn=Connection()
    admin={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    plan=({"remaining_id":11}, "abc")
    with patch("src.snapshot_admin.psycopg.connect",return_value=conn) as connect:
        with patch("src.snapshot_admin.deletion_plan",return_value=plan) as resolver:
            assert preview_selected("postgres://admin",admin,"admin@example.com",(13,))==plan
    connect.assert_called_once_with("postgres://admin",connect_timeout=15)
    resolver.assert_called_once_with(conn.cur,(13,))
    assert conn.cur.queries[0]=="SET TRANSACTION READ ONLY"
    assert not any("DELETE " in q or "INSERT " in q for q in conn.cur.queries)


def test_preview_fails_closed_without_admin_or_management_secret():
    from src.snapshot_admin import preview_selected
    admin={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    with patch("src.snapshot_admin.psycopg.connect") as connect:
        with pytest.raises(PermissionError):
            preview_selected("postgres://admin",{},"admin@example.com",(1,))
        with pytest.raises(PermissionError,match="SNAPSHOT_ADMIN_DATABASE_URL"):
            preview_selected(None,admin,"admin@example.com",(1,))
        connect.assert_not_called()


def test_app_snapshot_simulation_never_uses_readonly_dashboard_connection():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "preview_selected, delete_selected" in app
    assert "plan,token = preview_selected(" in app
    assert "snap_writer,snap_identity,snap_emails,chosen" in app
    assert "psycopg.connect(connection_string(),connect_timeout=15) as conn:" not in app.split(
        'if st.button("Simular eliminación"',1)[1].split("preflight =",1)[0]


def test_missing_snapshot_secret_is_diagnosed_before_preflight():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    admin_section=app.split("if tab7.open:",1)[1]
    assert 'st.secrets.get("SNAPSHOT_ADMIN_DATABASE_URL")' in admin_section
    assert 'os.environ.get("SNAPSHOT_ADMIN_DATABASE_URL")' in admin_section
    assert 'misplaced_snap_secret' in admin_section
    assert 'disabled=not chosen or not snap_writer' in admin_section
    assert 'SNAPSHOT_ADMIN_DATABASE_URL no está disponible' in admin_section


def test_po_fk_index_migration_matches_actual_constraint():
    script=(Path(__file__).resolve().parents[1]/"migrations"/
            "019_sc_po_links_po_fk_index.sql").read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS ix_sc_po_links_by_po_fk" in script
    assert "ON core.sc_po_links(snapshot_id,company,po_no,po_pos)" in script


def test_missing_po_fk_index_aborts_without_any_deletion():
    from contextlib import contextmanager
    class Conn:
        def __init__(self): self.queries=[]; self.aborted=False
        def __enter__(self): return self
        def __exit__(self,*args): return False
        @contextmanager
        def transaction(self):
            try: yield self
            except Exception:
                self.aborted=True
                raise
        def cursor(self): return self
        def execute(self,sql,params=None): self.queries.append(sql)
        def fetchall(self): return [(1,)]
        def fetchone(self): return (False,)
    conn=Conn()
    admin={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    plan={"snapshots":[{"id":1}],"remaining_id":8}
    with patch("src.snapshot_admin.psycopg.connect",return_value=conn):
        with patch("src.snapshot_admin.deletion_plan",return_value=(plan,"x"*64)):
            with pytest.raises(RuntimeError,match="migración 019"):
                delete_selected("postgres://admin",admin,"admin@example.com",(1,),"x"*64)
    assert conn.aborted
    assert not any(q.startswith("DELETE FROM") for q in conn.queries)
    assert not any("INSERT INTO audit.snapshot_deletions" in q for q in conn.queries)


def test_snapshot_inventory_omits_unwanted_main_table_counts():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    display=app.split('display = pd.DataFrame({',1)[-1].split('})',1)[0]
    for key in ('"SC":', '"Pos. SC":', '"Pos. PO":', '"PR":'):
        assert key not in display
    for subquery in ("AS sc,", "AS sc_positions,", "AS po_positions,",
                     "AS links,", "AS receptions,"):
        assert subquery not in INVENTORY_SQL
    for key in ('"Vigente":', '"Aprobaciones":', '"Incidencias":'):
        assert key not in display
    assert "AS approvals" not in INVENTORY_SQL
    assert "AS incidents" not in INVENTORY_SQL


def test_snapshot_delete_button_disables_during_transaction():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    dialog=app.split('def confirm_snapshot_deletion():',1)[1].split('if st.button("Eliminar seleccionados"',1)[0]
    assert "confirm_button = st.empty()" in dialog
    assert 'confirm_button.button("Eliminar definitivamente"' in dialog
    assert 'confirm_button.button("Eliminando...",disabled=True' in dialog
    assert dialog.index('confirm_button.button("Eliminando..." '.rstrip()) < dialog.index("result = delete_selected(")
    assert "snapshot_admin_plan" in dialog



def test_inventory_and_deletion_fallback_use_newest_validated_id():
    from src.snapshot_admin import INVENTORY_SQL
    from scripts import manage_snapshots
    import inspect
    assert "ORDER BY s.id DESC" in INVENTORY_SQL
    assert "ORDER BY id DESC LIMIT 1" in inspect.getsource(manage_snapshots.delete_snapshot)
    assert "ORDER BY id DESC LIMIT 1" in inspect.getsource(__import__("src.snapshot_admin",fromlist=["deletion_plan"]).deletion_plan)
