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
    assert 'on_click=toggle_timeline,args=(st.session_state,"sc")' in sc
    assert 'if st.button(' not in sc.split('# State belongs only to this SC',1)[1].split('if timeline_visible(st.session_state,"sc"):',1)[0]
    assert sc.count("po_link_overview")==2
    assert sc.count("po_link_summary")==1
    assert sc.index('if timeline_visible(st.session_state,"sc"):') < sc.index(
        'timeline_data=query(f"""SELECT s.company,s.sc_no,s.sc_pos,'
    )
    before_toggle=sc.split('if timeline_visible(st.session_state,"sc"):',1)[0]
    assert "po_link_summary" not in before_toggle
    assert "render_planning_timeline(" not in before_toggle

    # Group SC computes its summary automatically, while position details stay lazy.
    assert 'st.button("Resumen"' not in group
    assert "if not stats_ready:" in group
    assert 'if stats_ready:' in group
    assert 'if sc_event.selection.rows:' in group
    assert 'st.session_state["group_statistics_result"]=(group_key,group_status)' in group
    assert group.count("po_link_overview")==1
    assert "po_link_summary" not in group
    assert "render_planning_timeline(" not in group
    assert 'render_my_sc_timeline_control(group_source,sid,group_id,' in group
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
            r"linked\.planned_date,linked\.pr_numbers\s*FROM\s+planning\.",
            statement,re.IGNORECASE
        )
        assert "receipt_closure" not in statement
        assert "timeline_dates" not in statement


def test_group_statistics_sql_does_not_have_dangling_comma():
    from pathlib import Path
    import re
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(
        encoding="utf-8"
    )
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    overview=group.split('if not stats_ready:',1)[1].split(
        'st.session_state["group_statistics_result"]',1
    )[0]
    assert "linked.po_positions,linked.planned_date" in overview
    assert "FROM {source_table} s" in overview
    assert not re.search(r",\\s*FROM\\s+",overview,re.IGNORECASE)


def test_button_caption_matches_visible_state_on_every_callback():
    """Streamlit on_click runs before label evaluation on the rerun."""
    def caption(state,scope):
        return "Ocultar cronograma" if timeline_visible(state,scope) else "Mostrar cronograma"

    state={}
    sync_context(state,"sc",(8,"761452"))
    sync_context(state,"group",(8,42))
    for scope in ("sc","group"):
        assert caption(state,scope)=="Mostrar cronograma"
        toggle_timeline(state,scope)  # click: callback executes before widget renders
        assert caption(state,scope)=="Ocultar cronograma"
        toggle_timeline(state,scope)
        assert caption(state,scope)=="Mostrar cronograma"
        toggle_timeline(state,scope)
        assert caption(state,scope)=="Ocultar cronograma"
    reset_timeline(state,"group")
    assert caption(state,"group")=="Mostrar cronograma"
    assert caption(state,"sc")=="Ocultar cronograma"


def test_my_sc_context_hidden_until_selected_and_independent_from_followup():
    state={}
    sync_context(state,"sc",(12,"761452"))
    sync_context(state,"my_sc",(12,1,1,"761452"))
    assert not timeline_visible(state,"sc")
    assert not timeline_visible(state,"my_sc")
    assert "sc_timeline_data" not in state
    assert "my_sc_timeline_data" not in state

    toggle_timeline(state,"my_sc")
    state["my_sc_timeline_data"]=["cached events"]
    assert toggle_timeline(state,"my_sc") is False
    assert state["my_sc_timeline_data"]==["cached events"]
    assert toggle_timeline(state,"my_sc") is True
    sync_context(state,"my_sc",(12,1,1,"761453"))
    assert not timeline_visible(state,"my_sc")
    assert "my_sc_timeline_data" not in state
    assert not timeline_visible(state,"sc")

    toggle_timeline(state,"sc")
    state["sc_timeline_data"]=["followup events"]
    sync_context(state,"my_sc",(13,1,2,"761453"))
    assert timeline_visible(state,"sc")
    assert state["sc_timeline_data"]==["followup events"]


def test_same_source_fields_and_renderer_for_both_lazy_views():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    helper=app.split("def render_my_sc_timeline_control(",1)[1].split(
        "def render_planning_timeline(",1)[0]
    sc=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    end="ORDER BY s.company,s.sc_no,s.sc_pos"
    sc_query=sc.split('timeline_data=query(f"""',1)[1].split(end,1)[0]
    my_query=helper.split('timeline_cached=query(f"""',1)[1].split(end,1)[0]
    assert ''.join(sc_query.split())==''.join(my_query.split())
    assert 'if not timeline_visible(st.session_state,"my_sc"):\n        return' in helper
    assert helper.index('if not timeline_visible(') < helper.index("timeline_cached=query(")
    assert 'render_planning_timeline(timeline_source,today,' in helper
    assert 'render_planning_timeline(sc_timeline_source,madrid_today,' in sc
    assert 'render_planning_timeline(' not in group
    assert 'st.button("Resumen"' not in group
