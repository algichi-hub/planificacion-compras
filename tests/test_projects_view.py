"""Project-scoped SC browsing reuses the Mis SC UI and business logic."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import pandas as pd

from src.group_statistics import group_statistics
from src.group_sc_view import group_overview_source
from src.my_sc_selection import sync_my_sc_context
from src.timeline_visibility import sync_context, timeline_visible, toggle_timeline

APP=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")


def test_projects_tab_position_and_lazy_catalogue_reuse():
    assert '"Seguimiento PR","Proyectos","Mis SC"' in APP
    assert 'if tab8.open:' in APP
    assert 'project_options=projects["project"].astype(str).tolist()' in APP
    assert 'key=f"project_sc_select_{sid}"' in APP
    assert '"Proyecto",project_options,index=None,' in APP
    assert 'if chosen_project is not None:' in APP
    assert APP.index('if chosen_project is not None:') < APP.index('sid,project_name=chosen_project')
    projects=APP.split("if tab8.open:",1)[1].split("with tab4:",1)[0]
    assert "SELECT DISTINCT project" not in projects
    assert "load_sc_collection_status(" in projects
    assert 'sid,project_name=chosen_project' in projects
    assert 'render_sc_collection(' in projects
    assert ',"project_sc",chosen_project' in projects
    assert "write_bulk(" not in projects


def test_single_parameterized_project_filter_and_reuse_of_common_projection():
    source=APP.split("def load_sc_collection_status(",1)[1].split(
        "def render_sc_collection(",1)[0]
    assert 'condition = "s.sc_no=ANY(%s)" if numbers is not None else "s.project=%s"' in source
    assert 'WHERE s.snapshot_id=%s AND {condition}' in source
    assert 'linked.po_positions,linked.planned_date,linked.pr_numbers' in source
    assert '"planning.sc_workflow_status" if workflow_ready' in source
    assert "return query(" in source
    assert "psycopg.connect(" not in source


def test_common_renderer_has_two_independent_sc_selectors_and_detail():
    shared=APP.split("def render_sc_collection(",1)[1].split("with tab1:",1)[0]
    assert shared.count('on_select="rerun",selection_mode="single-row"')==2
    assert 'key=f"{scope}_summary_' in shared
    assert 'key=f"{scope}_positions_' in shared
    assert 'render_sc_detail(line,sid,context="group")' in shared
    assert "group_overview_source(chosen_items,chosen_status)" in shared
    assert "group_statistics(items,status,today_madrid)" in shared
    assert "sc_export_button(" in shared
    assert "render_my_sc_timeline_control(" in shared
    assert "query(" not in shared


def test_project_selection_does_not_clear_mis_sc_or_timeline():
    state={}
    m=sync_my_sc_context(state,(13,1,("760948",)),scope="my_sc")
    p=sync_my_sc_context(state,(13,"21401",("760948",)),scope="project_sc")
    assert sync_my_sc_context(state,(13,1,("760948",)),scope="my_sc")==m
    assert sync_my_sc_context(state,(13,"21401",("760948",)),scope="project_sc")==p
    assert sync_my_sc_context(state,(13,"21405",("760948",)),scope="project_sc")>p
    assert sync_my_sc_context(state,(11,"21405",("760948",)),scope="project_sc")>p
    assert sync_my_sc_context(state,(13,1,("760948",)),scope="my_sc")==m
    sync_context(state,"project_sc",(13,"21401",1,"760948"))
    toggle_timeline(state,"project_sc")
    assert timeline_visible(state,"project_sc")
    sync_context(state,"project_sc",(13,"21405",2,"760948"))
    assert not timeline_visible(state,"project_sc")


def test_project_position_isolation_even_when_erp_has_cross_project_sc():
    rows=pd.DataFrame([
        dict(company="210",sc_no="760948",sc_pos="10",project="21401",
             description="A",po_positions="900/1",planned_date=None,
             requested_qty=Decimal("2"),ordered_qty=Decimal("2"),
             received_qty=Decimal("2"),approved_qty=Decimal("2"),
             workflow_state="Completado"),
        dict(company="210",sc_no="760948",sc_pos="20",project="21405",
             description="B",po_positions="901/1",planned_date=None,
             requested_qty=Decimal("5"),ordered_qty=Decimal("0"),
             received_qty=Decimal("0"),approved_qty=Decimal("0"),
             workflow_state="Pendiente pedido"),
    ])
    first=rows.loc[rows.project.eq("21401")].copy()
    members=first[["sc_no","description"]].drop_duplicates("sc_no").rename(
        columns={"description":"context_description"})
    summary=group_statistics(members,first,date(2026,11,16))
    assert summary.iloc[0]["Full Approved"]=="1/1"
    assert summary.iloc[0]["Pend PO"]=="0/1"
    details=group_overview_source(members,first)
    assert details["sc_pos"].tolist()==["10"]


def test_timeline_helper_default_scope_is_defined_at_import_time():
    import ast
    tree=ast.parse(APP)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef)
               and n.name=="render_my_sc_timeline_control"]
    assert len(functions)==1
    defaults=functions[0].args.defaults
    assert len(defaults)==1
    assert isinstance(defaults[0],ast.Constant) and defaults[0].value=="my_sc"
    assert 'sync_context(st.session_state,scope,' in APP
    assert 'timeline_visible(st.session_state,scope)' in APP
