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
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert '["Resumen","Seguimiento SC","Seguimiento PR","Mis SC","Manage SC","Manage PR"]' in app
    assert 'st.subheader("Mis SC")' in group
    assert 'st.button("Resumen"' not in group
    assert 'if not stats_ready:' in group
    assert 'st.selectbox("Grupo SC"' not in group
    assert "Consultar grupo" not in group
    assert 'sc_event=st.dataframe(' in group
    assert 'event_group=st.dataframe(' in group
    assert group.count('on_select="rerun",selection_mode="single-row"')==2
    assert 'key=f"my_sc_summary_{sid}_{group_id}_{selection_revision}"' in group
    assert 'key=f"my_sc_positions_{sid}_{group_id}_{selection_revision}_{selected_sc}"' in group
    assert 'if sc_event.selection.rows:' in group
    assert 'if event_group.selection.rows:' in group
    assert 'render_sc_detail(line, sid, context="group")' in group
    assert group.index('if sc_event.selection.rows:') < group.index('if event_group.selection.rows:')
    assert group.index('if event_group.selection.rows:') < group.index('render_sc_detail(line, sid, context="group")')
    assert 'chosen_status=stats_saved[1].loc[' in group
    assert 'group_source=group_overview_source(chosen_items,chosen_status)' in group
    assert 'sc_export_button(' in group
    assert group.count('query(')==1
