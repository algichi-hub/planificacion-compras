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


def test_only_three_tabs_and_admin_gate_before_mutation():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert '["Resumen","Seguimiento SC","Bulk SC"]' in app
    assert '"REAC / Incidencias","Calidad de datos"' not in app
    assert "admin=is_bulk_admin(identity,admin_emails) and bool(admin_dsn)" in app
    assert 'with st.expander("Crear grupo Bulk SC"):' in app
    assert 'if admin:' in app
    assert "write_bulk(admin_dsn,identity,admin_emails" in app
    assert "st.login()" in app and "st.logout()" in app
