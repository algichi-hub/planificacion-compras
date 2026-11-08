"""Read-only SC timeline: calendar semantics, data quality and shared UX."""
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import pytest

from src.planning_timeline import (
    build_timeline, timeline_figure, as_day, ELAPSED, REMAINING, OVERDUE, TODAY_LINE
)

ROOT=Path(__file__).resolve().parents[1]
TODAY=date(2026,11,8)


def row(sc="761453",pos="10",approved="25/09/26",plan=date(2026,12,15),
        count=1,state="Material sin recibir",completion=None):
    return dict(company="210",sc_no=sc,sc_pos=pos,approval_raw=approved,
                approval_distinct=count,planned_date=plan,workflow_state=state,
                completion_date=completion)


def test_date_parsing_iso_and_source_format_and_missing():
    assert as_day("25/09/26")==date(2026,9,25)
    assert as_day("25/09/2026")==date(2026,9,25)
    assert as_day("2026-12-15")==date(2026,12,15)
    assert as_day(pd.Timestamp("2026-11-08T12:30:00"))==TODAY
    for invalid in ("99/99/26","n/a","","—",None):
        assert as_day(invalid) is None


def test_elapsed_and_remaining_are_exact_real_calendar_days():
    first=build_timeline(pd.DataFrame([row()]),TODAY)[0]
    assert first["label"]=="761453/10 · 210"
    assert first["approval"]==date(2026,9,25)
    assert first["plan"]==date(2026,12,15)
    assert first["elapsed_days"]==44
    assert first["remaining_days"]==37
    assert first["overdue_days"]==0
    assert first["percent"]==pytest.approx(100*44/81)
    assert first["issue"] is None


def test_before_approval_and_exact_boundaries():
    source=pd.DataFrame([row(approved="10/11/26",plan=date(2026,11,20))])
    pre=build_timeline(source,TODAY)[0]
    assert pre["elapsed_days"]==0
    assert pre["remaining_days"]==10
    assert pre["overdue_days"]==0
    at_start=build_timeline(source,date(2026,11,10))[0]
    assert (at_start["elapsed_days"],at_start["remaining_days"])==(0,10)
    at_end=build_timeline(source,date(2026,11,20))[0]
    assert (at_end["elapsed_days"],at_end["remaining_days"],at_end["overdue_days"])==(10,0,0)


def test_overdue_segment_starts_at_plan_not_approval_or_today():
    single=build_timeline(pd.DataFrame([row(plan=date(2026,11,1))]),TODAY)[0]
    assert single["remaining_days"]==0
    assert single["overdue_days"]==7
    assert single["elapsed_days"]==(date(2026,11,1)-date(2026,9,25)).days
    assert single["percent"]>100
    fig=timeline_figure([single],TODAY)
    red=next(t for t in fig.data if t.name=="Retraso")
    assert red.base[0]=="2026-11-01"
    assert red.x[0]==7*86400000
    assert red.marker.color==OVERDUE
    assert fig.layout.shapes[0].x0=="2026-11-08"
    assert fig.layout.shapes[0].line.color==TODAY_LINE


def test_plotly_stacked_intervals_date_axis_and_today_common():
    data=build_timeline(pd.DataFrame([
        row(pos="10",plan=date(2026,12,15)),
        row(pos="20",approved="15/10/26",plan=date(2026,11,1)),
        row(pos="30",approved="10/11/26",plan=date(2026,12,1)),
    ]),TODAY)
    fig=timeline_figure(data,TODAY)
    assert fig.layout.xaxis.type=="date"
    assert fig.layout.xaxis.tickformat=="%d/%m/%Y"
    assert fig.layout.barmode=="overlay"
    assert fig.layout.yaxis.categoryarray[0]==data[-1]["label"]
    traces={t.name:t for t in fig.data}
    assert traces["Transcurrido"].marker.color==ELAPSED
    assert traces["Restante"].marker.color==REMAINING
    assert traces["Retraso"].marker.color==OVERDUE
    assert traces["Restante"].base[0]=="2026-11-08"
    assert traces["Retraso"].base[0]=="2026-11-01"
    assert len(fig.layout.shapes)==1
    assert fig.layout.shapes[0].x0==TODAY.isoformat()
    assert all(t.type=="bar" for t in fig.data if t.name in ("Transcurrido","Restante","Retraso"))
    assert all(t.type=="bar" for t in fig.data)


def test_conflicting_approval_missing_invalid_and_inverted_dates():
    source=pd.DataFrame([
        row(pos="10",count=2),
        row(pos="20",approved=None,count=0),
        row(pos="30",approved="31/02/26"),
        row(pos="40",plan=None),
        row(pos="50",approved="15/12/26",plan=date(2026,12,15)),
        row(pos="60",approved="16/12/26",plan=date(2026,12,15)),
    ])
    result=build_timeline(source,TODAY)
    assert len(result)==6
    assert result[0]["issue"]=="Aprobaciones SC diferentes en origen"
    assert result[1]["issue"]=="Sin fecha de aprobación SC válida"
    assert result[2]["issue"]=="Sin fecha de aprobación SC válida"
    assert result[3]["issue"]=="Sin fecha plan actual válida"
    assert result[4]["issue"]=="Cronología inconsistente"
    assert result[5]["issue"]=="Cronología inconsistente"
    assert all(item["percent"] is None for item in result)
    fig=timeline_figure(result,TODAY)
    assert len(fig.data)==1
    assert fig.data[0].type=="scatter"
    assert list(fig.data[0].y)==[r["label"] for r in result]
    assert fig.layout.yaxis.type is None or fig.layout.yaxis.type=="category"


def test_group_reference_missing_from_snapshot_has_its_own_row():
    source=pd.DataFrame([row(),{"sc_no":"760000","sc_pos":None,
                               "company":None,"approval_distinct":None,
                               "approval_raw":None,"planned_date":None}])
    rows=build_timeline(source,TODAY)
    assert rows[1]["label"]=="760000/—"
    assert rows[1]["issue"]
    fig=timeline_figure(rows,TODAY)
    assert len(fig.layout.yaxis.categoryarray)==2


def test_completed_erp_and_delivered_total_have_same_visual_schedule():
    base=row(completion=date(2026,10,20))
    a=build_timeline(pd.DataFrame([{**base,"workflow_state":"Recepcion completada"}]),TODAY)
    b=build_timeline(pd.DataFrame([{**base,"workflow_state":"Completado",
                                     "display_state":"Entregado total"}]),TODAY)
    assert a==b
    assert timeline_figure(a,TODAY).to_plotly_json()["data"]==timeline_figure(b,TODAY).to_plotly_json()["data"]


def test_empty_frame_supported_without_query_or_division():
    assert build_timeline(pd.DataFrame(),TODAY)==[]
    assert len(timeline_figure([],TODAY).layout.shapes)==1
    with pytest.raises(ValueError):
        build_timeline(pd.DataFrame(),"bad date")


def test_same_approval_for_multiple_po_rows_is_one_sc_date():
    # Source aggregate is count(distinct), not count(*): multiple PO lines
    # with the same date are not treated as conflicts.
    assert build_timeline(pd.DataFrame([row(count=1)]),TODAY)[0]["issue"] is None
    assert build_timeline(pd.DataFrame([row(count=2)]),TODAY)[0]["issue"] is not None


def test_app_reuses_indexed_projected_source_in_existing_query():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "FROM planning.v_sc_source_detail v" in app
    assert "v.snapshot_id=s.snapshot_id AND v.company=s.company" in app
    assert "v.sc_no=s.sc_no AND v.sc_pos=s.sc_pos" in app
    assert "count(DISTINCT NULLIF(btrim(v.fields->>'FECHA APROBACIÓN__12'),''))" in app
    assert "timeline_dates.approval_raw,timeline_dates.approval_distinct" in app
    assert app.count("timeline_dates.approval_raw,timeline_dates.approval_distinct")==3
    assert "def render_planning_timeline(source, today, key):" in app
    assert 'render_planning_timeline(overview,madrid_today,f"sc_{sid}_{sc_number}")' in app
    assert 'render_planning_timeline(group_source,madrid_today,' in app
    assert "rows=build_timeline(source,today)" in app
    assert "timeline_figure(rows,today)" in app
    # No new SQL query inside the timeline renderer or plot functions.
    block=app.split("def render_planning_timeline(",1)[1].split("def render_sc_detail",1)[0]
    assert "query(" not in block
    assert "psycopg" not in block
    assert "st.plotly_chart" in block
    assert "st.download_button(" not in block
    # Source-view security: only approved projected fields, no economics.
    migration=(ROOT/"migrations/009_sc_source_detail_view.sql").read_text(encoding="utf-8")
    assert "ix_sc_source_rows_lookup" in migration
    assert "GRANT SELECT ON planning.v_sc_source_detail TO compras_reader" in migration


def test_position_selection_and_manage_sc_not_modified():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert app.count('on_select="rerun",selection_mode="single-row"')==2
    assert app.count('render_sc_detail(line, sid, context=')==2
    assert 'with tab4:' in app and 'with tab5:' in app
    assert "hand_deliveries.clear()" in app
    assert "UPDATE core." not in app


def test_completed_early_stops_at_erp_date_and_keeps_later_time_empty():
    completed=build_timeline(pd.DataFrame([
        row(state="Completado",completion=date(2026,10,20))
    ]),TODAY)[0]
    assert completed["completion"]==date(2026,10,20)
    assert completed["cutoff"]==date(2026,10,20)
    assert completed["elapsed_days"]==25
    assert completed["remaining_days"]==0
    assert completed["overdue_days"]==0
    fig=timeline_figure([completed],TODAY)
    assert {t.name for t in fig.data}=={"Transcurrido"}
    blue=fig.data[0]
    assert blue.base[0]=="2026-09-25"
    assert blue.x[0]==25*86400000
    assert fig.layout.shapes[0].x0=="2026-11-08"
    assert "Recepción completada: 20/10/2026" in blue.customdata[0]


def test_late_completion_red_ends_at_actual_receipt_date_not_today():
    completed=build_timeline(pd.DataFrame([
        row(plan=date(2026,10,15),state="Completado",
            completion=date(2026,10,20))
    ]),TODAY)[0]
    assert completed["overdue_days"]==5
    assert completed["percent"]>100
    fig=timeline_figure([completed],TODAY)
    red=next(t for t in fig.data if t.name=="Retraso")
    assert red.base[0]=="2026-10-15"
    assert red.x[0]==5*86400000
    assert "Restante" not in {t.name for t in fig.data}
    assert fig.layout.shapes[0].x0==TODAY.isoformat()


def test_completed_on_plan_date_and_today_or_before_approval():
    on_plan=build_timeline(pd.DataFrame([
        row(plan=date(2026,10,20),state="Completado",
            completion=date(2026,10,20))
    ]),TODAY)[0]
    assert on_plan["issue"] is None and on_plan["overdue_days"]==0
    assert on_plan["remaining_days"]==0
    assert "Retraso" not in {t.name for t in timeline_figure([on_plan],TODAY).data}
    for bad in (date(2026,9,24),date(2026,11,9),None):
        line=build_timeline(pd.DataFrame([
            row(state="Completado",completion=bad)
        ]),TODAY)[0]
        assert line["issue"] is not None
        assert line["cutoff"] is None
        assert all(t.name not in ("Transcurrido","Restante","Retraso")
                   for t in timeline_figure([line],TODAY).data)


def test_physical_delivery_or_incomplete_erp_never_ends_timeline():
    source=pd.DataFrame([{
        **row(state="Material sin recibir",completion=date(2026,10,20)),
        "display_state":"Entregado parcial",
    }])
    line=build_timeline(source,TODAY)[0]
    assert line["completion"] is None
    assert line["cutoff"]==TODAY
    assert line["remaining_days"]==37


def test_multiple_erp_movements_first_threshold_not_last_day_in_query():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "receipt_closure.completion_date" in app
    assert app.count("receipt_closure.completion_date")==3
    assert "sum(coalesce(r.approved_qty,0)) OVER" in app
    assert "r.receipt_date,r.source_line" in app
    assert "min(ev.receipt_date) FILTER" in app
    assert "ev.cumulative_approved>=s.requested_qty" in app
    assert "l.allocation_status='verified'" in app
    assert "r.approved_qty IS NOT NULL" in app
    assert "s.approved_qty>=s.requested_qty" in app
    assert "LEFT JOIN core.receipts r" in app
    block=app.split('def render_planning_timeline(',1)[1].split('def render_sc_detail(',1)[0]
    assert "query(" not in block



def test_multiple_positions_and_po_plan_comparison_share_single_overview_query():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    sql=app.split('po_link_summary="""',1)[1].split('"""',1)[0]
    assert "(array_agg(l.po_no ORDER BY p.planned_date NULLS LAST,l.po_no,l.po_pos))[1]" in sql
    assert "(array_agg(l.po_pos ORDER BY p.planned_date NULLS LAST,l.po_no,l.po_pos))[1]" in sql
    assert "v.fields->>'PEDIDO__16'=linked.plan_po_no" in sql
    assert "v.fields->>'POSICIÓN__17'=linked.plan_po_pos" in sql
    assert "v.fields->>'FECHA PLANIFICADA__26'" in sql
    assert sql.count("FROM planning.v_sc_source_detail v")==1
    assert app.count("timeline_dates.original_plan_raw,timeline_dates.original_plan_distinct")==3
    assert app.count("render_planning_timeline(")==3
    assert "query(" not in app.split("def render_planning_timeline(",1)[1].split("def render_sc_detail(",1)[0]
    assert "UPDATE core." not in app



def test_no_warning_marker_or_offset_for_overdue_open_and_completed():
    lines=build_timeline(pd.DataFrame([
        row(pos="10",plan=date(2026,11,1),state="Material sin recibir"),
        row(pos="20",plan=date(2026,10,15),state="Completado",
            completion=date(2026,10,20)),
        row(pos="30",plan=date(2026,12,15)),
    ]),TODAY)
    figure=timeline_figure(lines,TODAY)
    assert {trace.name for trace in figure.data} == {"Transcurrido","Restante","Retraso"}
    assert all(trace.type=="bar" for trace in figure.data)
    assert not any(trace.name=="Aviso de retraso" for trace in figure.data)
    assert not any(trace.name=="Recepción fuera de plazo" for trace in figure.data)
    assert len(figure.layout.shapes)==1
    assert figure.layout.shapes[0].x0==TODAY.isoformat()
    red=next(trace for trace in figure.data if trace.name=="Retraso")
    assert list(red.y)==[lines[0]["label"],lines[1]["label"]]
    assert list(red.x)==[7*86400000,5*86400000]
    # No displaced warning should extend the date-axis range beyond schedule.
    assert date.fromisoformat(figure.layout.xaxis.range[1])<=date(2026,12,20)


def test_all_warning_specific_plot_code_removed_without_db_changes():
    source=(ROOT/"src/planning_timeline.py").read_text(encoding="utf-8")
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    for fragment in ('warning_hover','icon_offset_days','icon_dates',
                     'triangle-up','Aviso de retraso','Recepción fuera de plazo'):
        assert fragment not in source
    assert 'render_planning_timeline(overview,madrid_today' in app
    assert 'render_planning_timeline(group_source,madrid_today' in app
    assert 'query(' not in app.split('def render_planning_timeline(',1)[1].split('def render_sc_detail(',1)[0]
