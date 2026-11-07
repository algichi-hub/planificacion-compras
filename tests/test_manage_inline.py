"""Inline Manage SC UI and persistence regression gates."""
from pathlib import Path

import pytest

from src.bulk_sc import write_bulk

ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"is_logged_in": True, "email_verified": True, "email": "admin@example.com"}


def test_manage_is_aggrid_not_form_matrix():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    manage=app.split("with tab4:",1)[1]
    assert "AgGrid(" in manage
    assert 'DataReturnMode.CUSTOM' in manage
    assert 'update_on=["cellValueChanged","cellClicked"]' in manage
    assert 'rowHeight":32' in manage
    assert 'headerHeight":32' in manage
    assert 'grid-template-columns' not in manage
    assert 'with st.container(key="manage_sc_grid"):' not in manage
    assert 'st.text_input("SC",key=sc_key' not in manage
    assert 'st.text_input("Descripción contextual",key=desc_key' not in manage
    assert 'st.button("Añadir nueva SC"' in manage
    assert '@st.dialog("Confirmar borrado")' in manage
    assert '"Confirmar borrado",key=f"grid_confirm_' in manage
    assert 'write_bulk(admin_dsn,identity,admin_emails,"insert_item"' in manage
    assert 'write_bulk(admin_dsn,identity,admin_emails,"edit_item"' in manage
    assert 'write_bulk(admin_dsn,identity,admin_emails,"remove_item"' in manage
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


def test_aggrid_layout_pin_and_delete_column():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    manage=app.split("with tab4:",1)[1]
    assert "return '<button type=" in manage
    assert "document.createElement('button')" not in manage
    assert "return b;" not in manage
    assert 'border-radius:0' in manage
    assert '"field":"delete"' in manage
    assert '"pinned":"left"' in manage
    assert '"editable":False' in manage
    assert 'min(450,40+max(1,len(rows))*32)' in manage
    assert '"theme="streamlit"' not in manage  # explicit kwarg below
    assert 'theme="streamlit"' in app
    assert 'enable_enterprise_modules=False' in manage
    assert 'server_sync_strategy="server_wins"' in manage
    assert 'key=f"manage_grid_{group_id_manage}_{st.session_state[revision_key]}"' in manage


def test_aggrid_events_validate_and_preserve_text():
    import pandas as pd
    from src.manage_grid import parse_manage_event, valid_existing_edit, apply_draft_edit
    items=pd.DataFrame([{"id":5,"sc_no":"000761452","context_description":"A"}])
    parsed=parse_manage_event({"type":"edit","id":5,"field":"context_description","value":"B"})
    assert valid_existing_edit(parsed,items)==("000761452","B",False)
    parsed=parse_manage_event({"type":"edit","id":5,"field":"sc_no","value":"000761453"})
    assert valid_existing_edit(parsed,items)==("000761453","A",False)
    assert valid_existing_edit(parse_manage_event({
        "type":"edit","id":5,"field":"sc_no","value":"000761452"}),items)[2] is True
    draft={"sc_no":"","context_description":""}
    draft,ready=apply_draft_edit(draft,parse_manage_event({
        "type":"edit","id":-3,"field":"sc_no","value":"00001"}))
    assert not ready and draft["sc_no"]=="00001"
    draft,ready=apply_draft_edit(draft,parse_manage_event({
        "type":"edit","id":-3,"field":"context_description","value":"Material"}))
    assert ready and draft=={"sc_no":"00001","context_description":"Material"}
    assert parse_manage_event({"type":"delete","id":5})=={"type":"delete","id":5}


@pytest.mark.parametrize("event", [
    None, {}, {"type":"sorting","id":1},
    {"type":"edit","id":0,"field":"sc_no","value":"123"},
    {"type":"edit","id":1,"field":"id","value":"2"},
    {"type":"edit","id":1,"field":"sc_no","value":123},
    {"type":"delete","id":"oops"},
])
def test_malformed_grid_events_are_ignored(event):
    from src.manage_grid import parse_manage_event
    assert parse_manage_event(event) is None


def test_invalid_grid_edits_do_not_pass_validation():
    import pandas as pd
    from src.manage_grid import parse_manage_event, valid_existing_edit
    items=pd.DataFrame([{"id":7,"sc_no":"00011","context_description":"A"}])
    for field,value in [("sc_no","a11"),("context_description","")]:
        with pytest.raises(ValueError):
            valid_existing_edit(parse_manage_event(
                {"type":"edit","id":7,"field":field,"value":value}),items)
    with pytest.raises(ValueError):
        valid_existing_edit(parse_manage_event(
            {"type":"edit","id":999,"field":"sc_no","value":"1"}),items)


def test_delete_renderer_returns_html_string_not_dom_element():
    """Regression for React #31: HTMLButtonElement cannot be rendered as a child."""
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    renderer=app.split('delete_renderer=JsCode("""',1)[1].split('""")',1)[0]
    assert "return '<button type=" in renderer
    assert "type=\"button\"" in renderer
    assert "border-radius:0" in renderer
    assert "document.createElement" not in renderer
    assert "return b" not in renderer
    assert "cellClicked" in app
