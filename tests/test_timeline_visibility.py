"""Functional state-machine regression for independent lazy timeline controls."""
from src.timeline_visibility import (
    sync_context,reset_timeline,toggle_timeline,timeline_visible,
)


def test_both_charts_start_hidden_and_independent():
    state={}
    sync_context(state,"sc",(8,"761488"))
    sync_context(state,"group",(8,42))
    assert not timeline_visible(state,"sc")
    assert not timeline_visible(state,"group")
    assert not state.get("sc_timeline_data")
    assert not state.get("group_timeline_data")

    assert toggle_timeline(state,"sc") is True
    assert timeline_visible(state,"sc") is True
    assert timeline_visible(state,"group") is False
    state["sc_timeline_data"]=["cached SC receipts"]

    assert toggle_timeline(state,"group") is True
    assert timeline_visible(state,"group") is True
    state["group_timeline_data"]=["cached group receipts"]
    assert toggle_timeline(state,"sc") is False
    assert timeline_visible(state,"group") is True
    assert state["sc_timeline_data"]==["cached SC receipts"]

    assert toggle_timeline(state,"sc") is True
    assert state["sc_timeline_data"]==["cached SC receipts"]
    assert state["group_timeline_data"]==["cached group receipts"]


def test_group_consult_reset_only_affects_group_not_followup_sc():
    state={}
    sync_context(state,"sc",(8,"761488"))
    sync_context(state,"group",(8,42))
    toggle_timeline(state,"sc")
    toggle_timeline(state,"group")
    state["sc_timeline_data"]=["SC"]
    state["group_timeline_data"]=["Group"]

    reset_timeline(state,"group")  # Click Consultar grupo again.
    assert not timeline_visible(state,"group")
    assert "group_timeline_data" not in state
    assert timeline_visible(state,"sc")
    assert state["sc_timeline_data"]==["SC"]


def test_switching_snapshot_sc_or_group_is_hidden_by_default():
    state={}
    sync_context(state,"sc",(8,"761488"))
    sync_context(state,"group",(8,42))
    toggle_timeline(state,"sc")
    toggle_timeline(state,"group")
    state["sc_timeline_data"]=["SC"]
    state["group_timeline_data"]=["Group"]

    sync_context(state,"sc",(8,"761488"))  # same SC, table selection
    assert timeline_visible(state,"sc")
    assert state["sc_timeline_data"]==["SC"]

    sync_context(state,"sc",(8,"761489"))
    assert not timeline_visible(state,"sc")
    assert "sc_timeline_data" not in state
    assert timeline_visible(state,"group")
    assert state["group_timeline_data"]==["Group"]

    sync_context(state,"group",(8,43))
    assert not timeline_visible(state,"group")
    assert "group_timeline_data" not in state

    toggle_timeline(state,"sc")
    toggle_timeline(state,"group")
    sync_context(state,"group",(9,43))
    assert not timeline_visible(state,"group")
    assert timeline_visible(state,"sc")


def test_no_query_or_plot_until_visible_in_both_sections():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    sc=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]

    assert 'sync_context(st.session_state,"sc",(sid,sc_number))' in sc
    assert '"Ocultar cronograma" if timeline_visible(st.session_state,"sc")' in sc
    assert 'else "Mostrar cronograma",key="sc_timeline_toggle"' in sc
    assert 'toggle_timeline(st.session_state,"sc")' in sc
    assert sc.count("po_link_overview")==2
    assert sc.count("po_link_summary")==1
    assert sc.index('if timeline_visible(st.session_state,"sc"):') < sc.index(
        'timeline_data=query(f"""SELECT s.company,s.sc_no,s.sc_pos,'
    )
    before_toggle=sc.split('if timeline_visible(st.session_state,"sc"):',1)[0]
    assert "po_link_summary" not in before_toggle
    assert "render_planning_timeline(" not in before_toggle

    assert 'sync_context(st.session_state,"group",(sid,group_id))' in group
    assert '"Consultar grupo",type="primary",key="group_sc_report"' in group
    assert '"Ocultar cronograma" if group_showing else "Mostrar cronograma"' in group
    assert "disabled=not report_ready" in group
    assert 'reset_timeline(st.session_state,"group")' in group
    assert 'toggle_timeline(st.session_state,"group")' in group
    assert group.count("po_link_overview")==1
    assert group.count("po_link_summary")==1
    assert group.index('st.session_state["bulk_result"]=(sid,group_id,grouped,group_source)') < group.index(
        'report_ready=bool(stored and stored[0]==sid and stored[1]==group_id)'
    ) < group.index('with col_timeline:')
    assert group.index('if timeline_visible(st.session_state,"group") and report_ready') < group.index(
        'timeline_data=query(f"""SELECT s.company,s.sc_no,s.sc_pos,'
    )
    assert "render_planning_timeline(" in group
    assert group.count("render_planning_timeline(")==1
    assert 'render_sc_detail(line, sid, context="group")' in group
    assert 'render_sc_detail(line, sid, context="seguimiento")' in sc



def test_sc_lightweight_sql_has_no_dangling_select_comma():
    """Regression: SC 761452 crashed with SQL syntax error near FROM.

    The lazy timeline split must preserve syntactically valid SELECT lists
    for both workflow and legacy coverage branches.
    """
    import re
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(
        encoding="utf-8"
    )
    sc=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    statements=re.findall(
        r'overview=query\("""SELECT (.*?)"""\+po_link_overview\+"""',
        sc,re.DOTALL
    )
    assert len(statements)==2  # Workflow and fallback coverage.
    for statement in statements:
        assert "linked.po_positions,linked.planned_date" in statement
        assert not re.search(r",\s*FROM\s+",statement,re.IGNORECASE)
        assert re.search(
            r"linked\.planned_date\s*FROM\s+planning\.",
            statement,re.IGNORECASE
        )
        assert "receipt_closure" not in statement
        assert "timeline_dates" not in statement


def test_group_lightweight_sql_does_not_have_dangling_comma():
    from pathlib import Path
    import re
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(
        encoding="utf-8"
    )
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    overview=group.split("if consult_requested:",1)[1].split(
        "grouped=group_overview(",1
    )[0]
    assert re.search(
        r"linked\.planned_date\s*FROM\s+\{source_table\}",
        overview,re.IGNORECASE
    )
    assert not re.search(r",\s*FROM\s+",overview,re.IGNORECASE)
