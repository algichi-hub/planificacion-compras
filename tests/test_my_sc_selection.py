"""Mis SC two-level selection: no initial preselection and isolated detail."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.my_sc_selection import sync_my_sc_context, reset_my_sc_selection
from src.group_sc_view import group_overview_source
from src.sc_overview import overview_display


def test_context_and_refresh_always_rotate_widget_keys():
    state = {}
    context = (11, 7, ("761452", "761488"))
    first = sync_my_sc_context(state, context)
    assert first >= 1
    assert sync_my_sc_context(state, context) == first
    refreshed = reset_my_sc_selection(state)
    assert refreshed == first + 1
    assert sync_my_sc_context(state, context) == refreshed
    assert sync_my_sc_context(state, (11, 8, ("761452",))) > refreshed
    assert sync_my_sc_context(state, (12, 8, ("761452",))) > refreshed + 1


def test_group_selection_filters_only_target_sc_and_keeps_missing_references():
    items = pd.DataFrame([
        dict(sc_no="000761452",context_description="uno"),
        dict(sc_no="761488",context_description="dos"),
        dict(sc_no="999999",context_description="sin snapshot"),
    ])
    status = pd.DataFrame([
        dict(company="210",sc_no="000761452",sc_pos="10",project="P",
             article="A",description="A",po_positions="762087/1",
             pr_numbers="768896",planned_date=date(2026,11,7),
             requested_qty=Decimal("2.5"),ordered_qty=Decimal("2.5"),
             received_qty=Decimal("1"),approved_qty=Decimal("1"),
             workflow_state="Parcialmente aprobadas"),
        dict(company="210",sc_no="761488",sc_pos="20",project="P",
             article="B",description="B",po_positions="762088/2",
             pr_numbers=None,planned_date=None,
             requested_qty=Decimal("3"),ordered_qty=Decimal("0"),
             received_qty=Decimal("0"),approved_qty=Decimal("0"),
             workflow_state="Pendiente pedido"),
    ])
    chosen = "000761452"
    rows=group_overview_source(items.loc[items.sc_no.eq(chosen)],
                               status.loc[status.sc_no.eq(chosen)])
    view=overview_display(rows)
    assert len(rows)==len(view)==1
    assert view.iloc[0]["SC/Pos"]=="000761452/10"
    assert view.iloc[0]["PRs"]=="768896"
    absent=group_overview_source(items.loc[items.sc_no.eq("999999")],
                                 status.iloc[:0])
    assert len(absent)==1
    assert absent.iloc[0].sc_no=="999999"
    assert pd.isna(absent.iloc[0].sc_pos)


def test_ui_two_widget_keys_are_independent_and_detail_is_child_only():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    group=app.split("with tab3:",1)[1].split("if tab8.open:",1)[0]
    shared=app.split("def render_sc_collection(",1)[1].split("with tab1:",1)[0]
    assert '["Resumen","Seguimiento SC","Seguimiento PR","Proyectos","Mis SC","Manage SC","Manage PR","Snapshots"]' in app
    assert 'st.subheader("Mis SC")' in group
    assert 'st.button("Resumen"' not in group
    assert 'st.selectbox("Grupo SC"' not in group
    assert "Consultar grupo" not in group
    assert 'render_sc_collection(items,stats_saved[1],"my_sc",group_id,allow_multi=True)' in group
    assert 'sc_event=st.dataframe(' in shared
    assert 'event_group=st.dataframe(' in shared
    assert 'on_select="rerun",selection_mode="multi-row" if allow_multi else "single-row"' in shared
    assert shared.count('on_select="rerun",selection_mode="single-row"')==1
    assert 'key=f"{scope}_summary_{sid}_{collection_id}_{revision}"' in shared
    assert 'key=f"{scope}_positions_{sid}_{collection_id}_{revision}_{selected_sc}"' in shared
    assert 'if sc_event.selection.rows:' in shared
    assert 'if event_group.selection.rows:' in shared
    assert 'render_sc_detail(line,sid,context="group")' in shared
    assert shared.index('if sc_event.selection.rows:') < shared.index('if event_group.selection.rows:')
    assert shared.index('if event_group.selection.rows:') < shared.index('render_sc_detail(line,sid,context="group")')
    assert 'chosen_status=status.loc[' in shared
    assert '.isin(selected_scs)' in shared
    assert 'selected_sc=";".join(selected_scs)' in shared
    assert 'group_source=group_overview_source(chosen_items,chosen_status)' in shared
    assert 'sc_export_button(' in shared
    assert "query(" not in shared


def test_multi_selection_aggregates_in_favorite_order_without_duplicate_positions():
    items=pd.DataFrame([
        {"sc_no":"300","context_description":"third"},
        {"sc_no":"100","context_description":"first"},
        {"sc_no":"200","context_description":"second"},
        {"sc_no":"999","context_description":"missing"},
    ])
    status=pd.DataFrame([
        {"company":"210","sc_no":"100","sc_pos":"10","workflow_state":"Completado"},
        {"company":"210","sc_no":"100","sc_pos":"20","workflow_state":"Completado"},
        {"company":"210","sc_no":"300","sc_pos":"10","workflow_state":"Completado"},
        {"company":"210","sc_no":"200","sc_pos":"10","workflow_state":"Completado"},
    ])
    selected_scs=("300","100","999")
    chosen_items=items.loc[items["sc_no"].astype(str).isin(selected_scs)]
    chosen_status=status.loc[status["sc_no"].astype(str).isin(selected_scs)]
    result=group_overview_source(chosen_items,chosen_status)
    assert list(zip(result["sc_no"],result["sc_pos"].fillna("—")))==[
        ("300","10"),("100","10"),("100","20"),("999","—")
    ]
    assert "200" not in result["sc_no"].tolist()
    assert not result.loc[result["sc_no"].eq("999"),"sc_pos"].notna().any()


def test_multi_selection_isolated_from_projects_and_lazy_db_calls():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    shared=app.split("def render_sc_collection(",1)[1].split("with tab1:",1)[0]
    mis=app.split("with tab3:",1)[1].split("if tab8.open:",1)[0]
    proj=app.split("if tab8.open:",1)[1].split("with tab4:",1)[0]
    assert "allow_multi=False" in app
    assert 'render_sc_collection(items,stats_saved[1],"my_sc",group_id,allow_multi=True)' in mis
    assert 'project_items,project_status,"project_sc",chosen_project' in proj
    assert "allow_multi=True" not in proj
    assert 'selected_scs=tuple(stat_table.iloc[sorted(sc_event.selection.rows)]' in shared
    assert 'key=f"{scope}_positions_{sid}_{collection_id}_{revision}_{selected_sc}"' in shared
    assert 'render_my_sc_timeline_control(' in shared
    assert "query(" not in shared
    helper=app.split("def render_my_sc_timeline_control(",1)[1].split("def render_planning_timeline(",1)[0]
    assert 's.sc_no=ANY(%s)' in helper
    assert 'sc_number.split(";")' in helper
    assert helper.index('if not timeline_visible(') < helper.index('timeline_cached=query(')
