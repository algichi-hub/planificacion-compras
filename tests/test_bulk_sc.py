"""Bulk SC authorization and schema isolation regression checks."""
from pathlib import Path

import pytest

from src.bulk_sc import is_bulk_admin, normalize_sc, normalize_label, write_bulk

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("person,allowed,expected", [
    ({}, "admin@example.com", False),
    ({"is_logged_in":True,"email":"admin@example.com"}, "admin@example.com", False),
    ({"is_logged_in":True,"email_verified":False,"email":"admin@example.com"}, "admin@example.com", False),
    ({"is_logged_in":True,"email_verified":True,"email":"other@example.com"}, "admin@example.com", False),
    ({"is_logged_in":True,"email_verified":True,"email":"ADMIN@example.com"}, "admin@example.com", True),
    ({"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}, "", False),
])
def test_verified_admin_allowlist(person, allowed, expected):
    assert is_bulk_admin(person, allowed) is expected


@pytest.mark.parametrize("value,expected", [
    ("000761451","000761451"),(" 761451 ","761451")
])
def test_sc_identifier_preserves_leading_zeros(value,expected):
    assert normalize_sc(value)==expected


@pytest.mark.parametrize("value", ["", "SC-1", "abc", "12 34", "0"*41])
def test_invalid_sc_rejected(value):
    with pytest.raises(ValueError):
        normalize_sc(value)


def test_no_database_connection_for_unauthorized_write(monkeypatch):
    from src import bulk_sc
    monkeypatch.setattr(bulk_sc.psycopg, "connect",
                        lambda *a,**kw: pytest.fail("Never connect for anonymous user"))
    with pytest.raises(PermissionError):
        write_bulk("should-not-be-used",{},"admin@example.com",
                   "add_item",group_id=1,sc_no="761451",description="Circuito A")
    with pytest.raises(PermissionError):
        write_bulk("should-not-be-used",
                   {"is_logged_in":True,"email_verified":True,"email":"unknown@example.com"},
                   "admin@example.com","create_group",name="Material")


def test_migration_keeps_user_lists_separate_from_erp():
    sql=(ROOT/"migrations/008_bulk_sc_groups.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists planning.bulk_sc_groups" in sql
    assert "create table if not exists planning.bulk_sc_items" in sql
    assert "unique(group_id, sc_no)" in sql
    assert "context_description" in sql
    for word in ("drop table","truncate","delete from core.","update core.","alter table core."):
        assert word not in sql


def test_separate_group_reporting_and_manage_tab_with_admin_gate():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert '["Resumen","Seguimiento SC","Group SC","Manage"]' in app
    assert "with tab3:" in app and "with tab4:" in app
    group_part=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    manage_part=app.split("with tab4:",1)[1]
    assert "Consultar grupo" in group_part
    assert "write_bulk(" not in group_part
    assert "write_bulk(" in manage_part
    assert "remove_group" in manage_part and "edit_group" in manage_part
    assert '"REAC / Incidencias","Calidad de datos"' not in app
    assert "admin=is_bulk_admin(identity,admin_emails) and bool(admin_dsn)" in app
    assert 'with st.expander("Crear grupo"):' in app
    assert 'if not admin:' in manage_part and '    else:\n        with st.expander("Crear grupo"):' in manage_part
    assert "write_bulk(admin_dsn,identity,admin_emails" in app
    assert 'st.login("google")' in app and "st.logout()" in app


def test_streamlit_oidc_auth_extra_and_dependencies_installed():
    import importlib.util
    dependencies=(ROOT/"requirements.txt").read_text(encoding="utf-8")
    assert "streamlit[auth]>=" in dependencies
    assert importlib.util.find_spec("authlib") is not None
    assert importlib.util.find_spec("httpx") is not None


def test_group_writes_authorized_parameterized_and_restricted_to_user_tables(monkeypatch):
    from src import bulk_sc
    executed=[]
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,sql,params):
            executed.append((sql,params))
        def fetchone(self): return (7,)
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def transaction(self): return self
        def cursor(self): return Cursor()
    monkeypatch.setattr(bulk_sc.psycopg,"connect",lambda *a,**kw: Conn())
    user={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    for operation,kwargs in [
        ("create_group",{"name":"Grupo A","description":"Descripción A"}),
        ("edit_group",{"group_id":7,"name":"Grupo B","description":"Descripción B"}),
        ("remove_group",{"group_id":7}),
        ("edit_item",{"group_id":7,"item_id":3,"sc_no":"000421","description":"Componente cambiado"}),
    ]:
        assert write_bulk("test-dsn",user,"admin@example.com",operation,**kwargs)==7
    assert len(executed)==4
    assert all("%s" in sql for sql,_ in executed)
    assert all("planning.bulk_sc_groups" in sql for sql,_ in executed[:3])
    assert "planning.bulk_sc_items" in executed[3][0]
    assert executed[0][1]==("Grupo A","Descripción A")
    assert executed[1][1]==("Grupo B","Descripción B",7)
    assert executed[2][1]==(7,)
    assert executed[3][1]==("000421","Componente cambiado",3,7)
    assert all("core." not in sql and "raw." not in sql for sql,_ in executed)


def test_group_sc_report_does_not_render_status_counts_summary():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    group_part=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert 'st.dataframe(format_sc_quantities(bulk_view.style)' in group_part
    assert 'counts.rename_axis("Estado")' not in group_part
    assert 'value_counts()' not in group_part
