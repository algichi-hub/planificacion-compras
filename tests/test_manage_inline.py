"""Inline Manage SC UI and persistence regression gates."""
from pathlib import Path

import pytest

from src.bulk_sc import write_bulk

ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"is_logged_in": True, "email_verified": True, "email": "admin@example.com"}


def test_manage_is_inline_and_legacy_sc_forms_are_gone():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    manage = app.split("with tab4:", 1)[1]
    assert 'st.button("Añadir nueva SC"' in manage
    assert 'st.button("X",help="Borrar esta SC del grupo",key=f"manage_delete_' in manage
    assert '@st.dialog("Confirmar borrado")' in manage
    assert '"Confirmar borrado",type="primary"' in manage
    assert "on_change=_save_existing_item" in manage
    assert "on_change=_save_new_item" in manage
    assert 'write_bulk(admin_dsn,identity,admin_emails,"insert_item"' in manage
    assert 'write_bulk(admin_dsn,identity,admin_emails,"remove_item"' in manage
    assert '"Añadir o actualizar SC"' not in manage
    assert '"Editar o retirar una SC"' not in manage
    assert 'st.form(f"bulk_edit_{item_id}' not in manage
    assert "if not sc_value or not desc_value:" in manage
    assert 'st.session_state.pop("bulk_result", None)' in manage
    assert 'with st.expander("Modificar grupo"):' in manage
    assert 'with st.expander("Eliminar grupo"):' in manage


def test_insert_item_parameterized_preserves_leading_zeros(monkeypatch):
    from src import bulk_sc
    executed = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, statement, values): executed.append((statement, values))
        def fetchone(self): return (42,)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def transaction(self): return self
        def cursor(self): return Cursor()

    monkeypatch.setattr(bulk_sc.psycopg, "connect", lambda *a, **kw: Conn())
    result = write_bulk("writer", ADMIN, "admin@example.com",
                        "insert_item", group_id=3, sc_no="000761452",
                        description="Material A")
    assert result == 42
    sql, params = executed[0]
    assert "ON CONFLICT (group_id,sc_no) DO NOTHING" in sql
    assert "planning.bulk_sc_items" in sql
    assert params == (3, "000761452", "Material A")
    assert "core." not in sql


def test_duplicate_insert_fails_without_overwriting(monkeypatch):
    from src import bulk_sc

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, statement, values): pass
        def fetchone(self): return None

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def transaction(self): return self
        def cursor(self): return Cursor()

    monkeypatch.setattr(bulk_sc.psycopg, "connect", lambda *a, **kw: Conn())
    with pytest.raises(ValueError, match="ya existe"):
        write_bulk("writer", ADMIN, "admin@example.com",
                   "insert_item", group_id=3, sc_no="761452",
                   description="Otro contenido")


@pytest.mark.parametrize("sc,description", [
    ("abc", "Material A"), ("", "Material A"),
    ("123", ""), ("123", "x" * 501),
])
def test_invalid_new_item_never_connects_to_neon(monkeypatch, sc, description):
    from src import bulk_sc
    monkeypatch.setattr(bulk_sc.psycopg, "connect",
                        lambda *a, **kw: pytest.fail("No DB connection expected"))
    with pytest.raises(ValueError):
        write_bulk("writer", ADMIN, "admin@example.com",
                   "insert_item", group_id=1, sc_no=sc, description=description)


def test_new_item_permissions_fail_closed(monkeypatch):
    from src import bulk_sc
    monkeypatch.setattr(bulk_sc.psycopg, "connect",
                        lambda *a, **kw: pytest.fail("No unauthorized DB connection"))
    with pytest.raises(PermissionError):
        write_bulk("writer", {}, "admin@example.com", "insert_item",
                   group_id=1, sc_no="123", description="Compra")


def test_group_sc_reporting_retains_read_only_and_selection():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    group_view = app.split("with tab3:", 1)[1].split("with tab4:", 1)[0]
    assert "write_bulk(" not in group_view
    assert 'selection_mode="single-row"' in group_view
    assert "format_sc_quantities(bulk_view.style).apply(" in group_view


def test_manage_compact_grid_only_scoped_css():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    manage = app.split("with tab4:", 1)[1]
    assert 'with st.container(key="manage_sc_grid"):' in manage
    assert 'c_action,c_sc,c_desc=st.columns([0.5,2,5],gap=None,vertical_alignment="center")' in manage
    assert '.st-key-manage_sc_grid [data-testid="stVerticalBlock"]' in manage
    assert 'gap: 1px !important;' in manage
    assert 'height: 34px !important;' in manage
    assert 'border-radius: 0 !important;' in manage
    assert '[class*="st-key-manage_delete_"] button' in manage
    assert 'background: #FEF2F2 !important;' in manage
    # No global input overrides affecting Seguimiento SC or Group SC.
    assert 'input {' not in app.split("with tab4:", 1)[0]


def test_delete_is_left_of_sc_and_rows_cannot_wrap():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    manage = app.split("with tab4:", 1)[1]
    assert 'grid-template-columns: 38px minmax(100px, 2fr) minmax(140px, 5fr)' in manage
    assert 'display: grid !important;' in manage
    assert '[data-testid="stColumn"]' in manage
    row = manage.split('c_action,c_sc,c_desc=st.columns(',1)[1].split(
        'status=st.session_state.get(f"manage_status_',1)[0]
    assert row.index('with c_action:') < row.index('with c_sc:') < row.index('with c_desc:')
    assert 'st.button("X",help="Borrar esta SC del grupo"' in row
    assert 'st.button("Borrar"' not in manage
    draft = manage.split('d_action,d_sc,d_desc=st.columns(',1)[1].split(
        'status=st.session_state.get(f"manage_new_status_',1)[0]
    assert draft.index('with d_action:') < draft.index('with d_sc:') < draft.index('with d_desc:')
    assert 'st.button("X",help="Descartar fila nueva"' in draft
    assert '[data-baseweb="input"]' in manage
    assert '[data-baseweb="base-input"]' in manage
