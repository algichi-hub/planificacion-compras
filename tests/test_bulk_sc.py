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


def test_fixed_my_sc_dashboard_and_existing_editor_are_kept():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert '["Resumen","Seguimiento SC","Mis SC","Manage SC","Manage PR"]' in app
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    manage=app.split("with tab4:",1)[1].split("with tab5:",1)[0]
    assert 'group_id=MY_SC_GROUP_ID' in group
    assert 'if not stats_ready:' in group
    assert 'st.button("Resumen"' not in group
    assert 'st.selectbox("Grupo SC"' not in group
    assert "render_sc_detail(line, sid, context=\"group\")" in group
    assert "group_id_manage=MY_SC_GROUP_ID" in manage
    assert "Grupo para gestionar" not in manage
    for label in ("Crear grupo","Modificar grupo","Eliminar grupo"):
        assert label not in manage
    for operation in ('"insert_item"', '"edit_item"', '"remove_item"'):
        assert operation in manage
    assert 'render_manage_grid()' in manage
    assert 'admin=is_bulk_admin(identity,admin_emails) and bool(admin_dsn)' in app
    assert 'st.login("google")' in app and 'st.logout()' in app


def test_streamlit_oidc_auth_extra_and_dependencies_installed():
    import importlib.util
    dependencies=(ROOT/"requirements.txt").read_text(encoding="utf-8")
    assert "streamlit[auth]>=" in dependencies
    assert importlib.util.find_spec("authlib") is not None
    assert importlib.util.find_spec("httpx") is not None


def test_group_management_operations_are_blocked_before_connect(monkeypatch):
    from src import bulk_sc
    monkeypatch.setattr(bulk_sc.psycopg,"connect",
                        lambda *a,**kw: pytest.fail("No connection allowed for group writes"))
    user={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    for operation,kwargs in [
        ("create_group",{"name":"Grupo A"}),
        ("edit_group",{"group_id":1,"name":"New name"}),
        ("remove_group",{"group_id":1}),
    ]:
        with pytest.raises(ValueError,match="deshabilitada"):
            write_bulk("test-dsn",user,"admin@example.com",operation,**kwargs)


def test_existing_item_operations_keep_parameterized_sql(monkeypatch):
    from src import bulk_sc
    executed=[]
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,sql,params): executed.append((sql,params))
        def fetchone(self): return (7,)
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def transaction(self): return self
        def cursor(self): return Cursor()
    monkeypatch.setattr(bulk_sc.psycopg,"connect",lambda *a,**kw: Conn())
    user={"is_logged_in":True,"email_verified":True,"email":"admin@example.com"}
    assert write_bulk("test-dsn",user,"admin@example.com","edit_item",
                      group_id=1,item_id=3,sc_no="000421",
                      description="Componente cambiado")==7
    assert executed == [(
        "UPDATE planning.bulk_sc_items SET sc_no=%s,context_description=%s, "
        "updated_at=now() WHERE id=%s AND group_id=%s RETURNING id",
        ("000421","Componente cambiado",3,1),
    )]
    with pytest.raises(ValueError,match="Mis SC"):
        write_bulk("test-dsn",user,"admin@example.com","edit_item",
                   group_id=2,item_id=3,description="Incorrect")


def test_my_sc_group_privileges_revoked_without_modifying_items():
    migration=(ROOT/"migrations/017_freeze_my_sc_group.sql").read_text(encoding="utf-8")
    assert "REVOKE INSERT, DELETE ON TABLE planning.bulk_sc_groups" in migration
    assert "REVOKE UPDATE (name,description,updated_at)" in migration
    assert "DELETE FROM" not in migration and "UPDATE planning.bulk_sc_items" not in migration


def test_group_sc_report_does_not_render_status_counts_summary():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    group_part=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert 'format_sc_quantities(bulk_view.style).apply(' in group_part
    assert 'overview_row_style,axis=1,today=today_madrid' in group_part
    assert 'column_config=overview_column_config()' in group_part
    assert 'group_source=group_overview_source(chosen_items,chosen_status)' in group_part
    assert 'linked.po_positions,linked.planned_date' in group_part
    assert 'counts.rename_axis("Estado")' not in group_part
    assert 'value_counts()' not in group_part


def test_group_overview_matches_individual_sc_columns_and_icons():
    from datetime import date
    from decimal import Decimal
    import pandas as pd
    from src.group_sc_view import group_overview
    from src.sc_overview import DISPLAY_COLUMNS, overview_display, overview_row_style

    items=pd.DataFrame([
        {"sc_no":"00012","context_description":"Compra estratégica"},
        {"sc_no":"00099","context_description":"Pendiente de aparecer"},
    ])
    source=pd.DataFrame([
        {"company":"210","sc_no":"00012","sc_pos":"1","article":"A1",
         "description":"Primer artículo","project":"P1","po_positions":"001/1",
         "planned_date":date(2026,11,5),"requested_qty":Decimal("2"),
         "ordered_qty":Decimal("2"),"received_qty":Decimal("0"),
         "approved_qty":Decimal("0"),"workflow_state":"Material sin recibir"},
        {"company":"210","sc_no":"00012","sc_pos":"2","article":"A2",
         "description":"Segundo artículo","project":"P2","po_positions":"001/2, 002/1",
         "planned_date":date(2026,12,5),"requested_qty":Decimal("3"),
         "ordered_qty":Decimal("3"),"received_qty":Decimal("3"),
         "approved_qty":Decimal("3"),"workflow_state":"Completado"},
    ])
    grouped=group_overview(items,source)
    original=overview_display(source)
    assert list(grouped.columns)==list(original.columns)==list(DISPLAY_COLUMNS)
    assert len(grouped)==3
    pd.testing.assert_frame_equal(grouped.iloc[:2].reset_index(drop=True),original)
    assert grouped["SC/Pos"].tolist()==["00012/1","00012/2","00099"]
    assert grouped["PO/Pos"].tolist()==["001/1","001/2, 002/1","—"]
    assert grouped["fecha_plan"].tolist()==["05/11/2026","05/12/2026","—"]
    assert grouped["estado"].tolist()==["Material sin recibir","Recepcion completada","No encontrada"]
    assert pd.isna(grouped.iloc[-1][" "])
    style=overview_row_style(grouped.iloc[0],date(2026,11,7))
    assert "color: #B91C1C" in style[grouped.columns.get_loc("fecha_plan")]
    assert all("background" not in x for x in style)


def test_group_overview_supports_empty_results_and_legacy_statuses():
    import pandas as pd
    from src.group_sc_view import group_overview
    from src.sc_overview import DISPLAY_COLUMNS
    items=pd.DataFrame([{"sc_no":"0001","context_description":"C"}])
    status=pd.DataFrame(columns=[
        "company","sc_no","sc_pos","article","description","project",
        "requested_qty","ordered_qty","received_qty","approved_qty",
        "po_positions","planned_date","coverage_state",
    ])
    view=group_overview(items,status)
    assert tuple(view.columns)==DISPLAY_COLUMNS
    assert view.iloc[0]["SC/Pos"]=="0001"
    assert view.iloc[0]["estado"]=="No encontrada"
    assert view.iloc[0]["PO/Pos"]=="—"
    assert group_overview(items.iloc[:0],status).empty


def test_group_sc_reuses_selected_sc_detail_sections():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    shared=app.split("def render_sc_detail(line, sid, context):",1)[1].split("\nwith tab1:",1)[0]
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    individual=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    assert 'render_sc_detail(line, sid, context="seguimiento")' in individual
    assert 'render_sc_detail(line, sid, context="group")' in group
    assert 'selection_mode="single-row"' in group
    assert 'on_select="rerun"' in group
    assert 'group_source.iloc[selected_index]' in group
    assert 'pd.isna(line.get("company"))' in group
    assert 'widget_prefix=f"{context}_' in shared
    assert "st.download_button(" not in shared
    assert 'st.subheader(f"Detalle SC {line[\'sc_no\']} / {line[\'sc_pos\']}")' in shared
    for heading in (
        'st.markdown("#### Recepciones")',
        'st.markdown("#### REAC")',
        'st.markdown("#### Incidencias")',
    ):
        assert heading in shared
    assert "#### Recepciones asociadas" not in shared
    assert "#### REAC asociados" not in shared
    assert "#### Incidencias asociadas" not in shared
    for source in ('core.sc_po_links','core.receipts','core.reac_refs','core.incidents'):
        assert source in shared


def test_group_source_keeps_selection_index_and_company_position_keys():
    import pandas as pd
    from src.group_sc_view import group_overview_source, group_overview
    items=pd.DataFrame([{"sc_no":"00022"},{"sc_no":"00042"}])
    status=pd.DataFrame([
        {"company":"210","sc_no":"00022","sc_pos":"1","project":"P","article":"A",
         "description":"B","requested_qty":1,"ordered_qty":1,"received_qty":0,
         "approved_qty":0,"workflow_state":"Pendiente aprobación",
         "po_positions":"200/1","planned_date":None},
        {"company":"230","sc_no":"00022","sc_pos":"2","project":"P","article":"A",
         "description":"B","requested_qty":2,"ordered_qty":2,"received_qty":0,
         "approved_qty":0,"workflow_state":"Pendiente aprobación",
         "po_positions":"201/1","planned_date":None},
    ])
    source=group_overview_source(items,status)
    view=group_overview(items,status)
    assert len(source)==len(view)==3
    assert source["company"].iloc[:2].tolist()==["210","230"]
    assert source["sc_pos"].iloc[:2].tolist()==["1","2"]
    assert pd.isna(source.iloc[2]["company"])
    assert view.iloc[2]["SC/Pos"]=="00042"



def test_group_metadata_write_privileges_are_not_used():
    writer=(ROOT/"src/bulk_sc.py").read_text(encoding="utf-8")
    assert 'if operation in ("create_group", "edit_group", "remove_group")' in writer
    assert "INSERT INTO planning.bulk_sc_groups" not in writer
    assert "UPDATE planning.bulk_sc_groups" not in writer
    assert "DELETE FROM planning.bulk_sc_groups" not in writer


def test_group_sc_statistics_and_detail_are_explicitly_requested():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    block=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert 'st.button("Resumen"' not in block
    assert 'if not stats_ready:' in block
    assert "Consultar grupo" not in block
    assert block.index('if not stats_ready:') < block.index('sc_event=st.dataframe(')
    assert block.index('sc_event=st.dataframe(') < block.index('event_group=st.dataframe(')
    assert 'stat_table=group_statistics(items,stats_saved[1],today_madrid)' in block
    assert 'st.session_state["group_statistics_result"]=(group_key,group_status)' in block
    assert 'stats_ready=bool(stats_saved and stats_saved[0]==group_key)' in block
    assert 'selected_sc=str(stat_table.iloc[sc_event.selection.rows[0]]["Num SC"])' in block
    assert "chosen_items=items.loc[" in block
    assert "po_link_overview" in block
    for forbidden in ("po_link_summary","receipt_closure.","timeline_dates.",
                      "render_planning_timeline(","Cargar cronograma",
                      "Mostrar cronograma","Ocultar cronograma",
                      "group_timeline_data","group_sc_timeline_toggle"):
        assert forbidden not in block
    assert 'on_select="rerun",selection_mode="single-row"' in block
    assert 'render_sc_detail(line, sid, context="group")' in block
    assert "write_bulk(" not in block


def test_group_sql_is_split_without_changing_other_timeline_queries():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    head=app.split('po_link_overview="""',1)[1].split('"""',1)[0]
    tail=app.split('po_link_summary=po_link_overview+"""',1)[1].split('"""',1)[0]
    assert "core.sc_po_links" in head
    assert "core.po_lines" in head
    assert "timeline_dates" not in head
    assert "receipt_closure" not in head
    assert "planning.v_sc_source_detail" in tail
    assert "core.receipts" in tail
    assert app.count("po_link_summary+")==2  # Both views defer PR events until opened
