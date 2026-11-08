"""Single-bar ERP purchase/PR timeline: date semantics and regression."""
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal
import json

import pandas as pd
import pytest

from src.planning_timeline import (
    as_day, build_timeline, receipt_milestones, timeline_figure,
    SC_ORDER, ORDER_ORIGINAL, REPLAN, RECEIPT_WAIT,
    PARTIAL_PR, COMPLETE_PR, TODAY_LINE, ROW_PITCH, BAR_WIDTH,
)

ROOT=Path(__file__).resolve().parents[1]
TODAY=date(2026,11,8)


def event(po="760274",pos="1",qty=20,pr=None,day=None,received=None,
          source_line=1,verified=True):
    return dict(
        po_no=po,po_pos=pos,po_qty=qty,pr_no=pr,pr_date=day,
        delivered_qty=received,source_line=source_line,
        allocation_status="verified" if verified else "uncertain",
    )


def record(pos="10",plan=date(2026,12,15),original="30/11/26",
           order="10/10/26",approval="25/09/26",events=None,**other):
    data={
        "company":"210","sc_no":"761453","sc_pos":pos,
        "approval_raw":approval,"approval_distinct":1,
        "po_approval_raw":order,"po_approval_distinct":1,
        "original_plan_raw":original,"original_plan_distinct":1,
        "planned_date":plan,
        "receipt_events":events if events is not None else
              [event()], # An open PO without PR still counts.
    }
    data.update(other)
    return data


def model(*data):
    return build_timeline(pd.DataFrame(data),TODAY)


def bars(fig,name):
    return [t for t in fig.data if t.type=="bar" and t.name==name]


def pr_lines(fig,complete):
    target="Recepción completa" if complete else "Recepción parcial"
    return [t for t in fig.data if t.type=="scatter" and t.name==target]


def test_dates():
    assert as_day("25/09/26")==date(2026,9,25)
    assert as_day("2026-09-25")==date(2026,9,25)
    assert as_day(pd.Timestamp("2026-11-08T12:00:00"))==TODAY
    for value in ("",None,"99/99/26","bad"):
        assert as_day(value) is None


def test_purchasing_intervals_and_pink_extension():
    r=model(record())[0]
    fig=timeline_figure([r],TODAY)
    red=bars(fig,"SC → Pedido aprobado")[0]
    orange=bars(fig,"Pedido → Plan original")[0]
    pink=bars(fig,"Plan original → Plan actual")[0]
    assert red.marker.color==SC_ORDER=="#DC2626"
    assert orange.marker.color==ORDER_ORIGINAL=="#F59E0B"
    assert pink.marker.color==REPLAN=="#F9A8D4"
    assert red.base[0]=="2026-09-25"
    assert red.x[0]==15*86400000
    assert orange.base[0]=="2026-10-10"
    assert orange.x[0]==51*86400000
    assert pink.base[0]=="2026-11-30"
    assert pink.x[0]==15*86400000
    assert "Desde: 30/11/2026" in pink.customdata[0]


def test_advanced_current_plan_never_shows_pink():
    fig=timeline_figure(model(record(plan=date(2026,11,12))),TODAY)
    assert not bars(fig,"Plan original → Plan actual")


def test_same_current_and_original_no_pink():
    assert not bars(timeline_figure(model(record(plan=date(2026,11,30))),TODAY),
                    "Plan original → Plan actual")


def test_open_order_grey_to_today_if_plan_already_passed():
    data=model(record(plan=date(2026,10,20),original="15/10/26"))[0]
    fig=timeline_figure([data],TODAY)
    gray=bars(fig,"Pendiente de recepción")[0]
    assert gray.marker.color==RECEIPT_WAIT=="#CBD5E1"
    assert gray.base[0]=="2026-10-20"
    assert gray.x[0]==19*86400000
    assert data["completion"] is None


def test_future_plan_has_no_grey_backward_fill():
    assert not bars(timeline_figure(model(record()),TODAY),"Pendiente de recepción")


def test_actual_multi_pr_partial_blue_and_final_green():
    events=[
        event(pr="757008",day="2026-04-27",received=6,source_line=21993),
        event(pr="759676",day="2026-06-05",received=14,source_line=21994),
    ]
    rows=model(record(approval="01/02/26",order="11/02/26",
                      original="08/04/26",plan=date(2026,4,8),events=events))
    line=rows[0]
    assert line["completion"]==date(2026,6,5)
    assert [(m["date"],m["complete"]) for m in line["milestones"]]==[
        (date(2026,4,27),False),(date(2026,6,5),True)
    ]
    fig=timeline_figure(rows,TODAY)
    partial=pr_lines(fig,False)[0]
    green=pr_lines(fig,True)[0]
    assert partial.line.color==PARTIAL_PR=="#2563EB"
    assert green.line.color==COMPLETE_PR=="#16A34A"
    assert partial.line.width==green.line.width==4
    assert list(partial.x[:2])==["2026-04-27","2026-04-27"]
    assert list(green.x[:2])==["2026-06-05","2026-06-05"]
    assert "PR 757008" in partial.customdata[0]
    assert "recibido 6" in partial.customdata[0]
    assert "acumulado 6 / 20" in partial.customdata[0]
    assert "PR 759676" in green.customdata[0]
    gray=bars(fig,"Pendiente de recepción")[0]
    assert gray.base[0]=="2026-04-08"
    assert gray.x[0]==58*86400000


def test_two_pr_same_day_collapse_into_one_green_marker():
    events=[
        event(po="741637",pos="29",qty=21,pr="755180",
              day="2026-03-24",received=15,source_line=20517),
        event(po="741637",pos="29",qty=21,pr="755181",
              day="2026-03-24",received=6,source_line=20518),
    ]
    rows=model(record(approval="01/02/26",order="23/03/26",
             original="23/03/26",plan=date(2026,3,23),events=events))
    line=rows[0]
    assert line["completion"]==date(2026,3,24)
    assert len(line["milestones"])==1
    assert line["milestones"][0]["complete"]
    fig=timeline_figure(rows,TODAY)
    assert not pr_lines(fig,False)
    green=pr_lines(fig,True)[0]
    assert len(green.x)==3  # Only one vertical line, plus separator
    assert "PR 755180" in green.customdata[0]
    assert "PR 755181" in green.customdata[0]


def test_one_single_full_pr_gives_only_green():
    events=[event(pr="P100",day="2026-10-19",received=20)]
    rows=model(record(original="10/10/26",plan=date(2026,10,12),
             events=events))
    assert rows[0]["completion"]==date(2026,10,19)
    fig=timeline_figure(rows,TODAY)
    assert not pr_lines(fig,False)
    assert len(pr_lines(fig,True))==1
    assert bars(fig,"Pendiente de recepción")[0].x[0]==7*86400000


def test_partial_order_stays_open_and_grey_to_today():
    rows=model(record(original="10/10/26",plan=date(2026,10,12),
             events=[event(pr="P100",day="2026-10-19",received=6)]))
    assert rows[0]["completion"] is None
    assert len(pr_lines(timeline_figure(rows,TODAY),False))==1
    gray=bars(timeline_figure(rows,TODAY),"Pendiente de recepción")[0]
    assert gray.x[0]==27*86400000


def test_all_multiple_po_lines_must_be_fully_received_to_go_green():
    events=[
        event(po="PO1",qty=10,pr="A",day="2026-10-10",received=10),
        event(po="PO2",qty=6,pr="B",day="2026-10-20",received=2),
        event(po="PO2",qty=6,pr="C",day="2026-11-02",received=4,source_line=2),
    ]
    rows=model(record(original="10/10/26",plan=date(2026,10,12),events=events))
    assert rows[0]["completion"]==date(2026,11,2)
    assert [(m["date"],m["complete"]) for m in rows[0]["milestones"]]==[
        (date(2026,10,10),False),(date(2026,10,20),False),
        (date(2026,11,2),True)
    ]
    assert len(pr_lines(timeline_figure(rows,TODAY),False))==1


def test_multi_po_with_any_unreceived_po_no_green():
    events=[
        event(po="PO1",qty=10,pr="A",day="2026-10-10",received=10),
        event(po="PO2",qty=6),
    ]
    rows=model(record(events=events))
    assert rows[0]["completion"] is None
    assert not pr_lines(timeline_figure(rows,TODAY),True)


def test_not_quality_approval_date_ever():
    events=[{**event(pr="P1",day="2026-10-17",received=20),
             "approved_qty":0,"erp_status":"Libre"}]
    rows=model(record(events=events))
    assert rows[0]["completion"]==date(2026,10,17)
    assert len(pr_lines(timeline_figure(rows,TODAY),True))==1


def test_invalid_qty_unverified_or_undated_never_force_green():
    variants=[
        [event(qty=None,pr="X",day="2026-10-17",received=20)],
        [event(qty=20,pr="X",day="2026-10-17",received=20,verified=False)],
        [event(qty=20,pr="X",day="bad",received=20)],
        [event(qty=20,pr="X",day="2026-10-17",received=None)],
    ]
    for events in variants:
        markers,closed,issues=receipt_milestones(events,TODAY)
        assert closed is None
        assert issues
        assert not any(m["complete"] for m in markers)


def test_po_qty_conflict_prevents_green():
    events=[
        event(qty=20,pr="A",day="2026-10-17",received=10),
        event(qty=30,pr="B",day="2026-10-20",received=20,source_line=2),
    ]
    _,done,problems=receipt_milestones(events,TODAY)
    assert done is None and "Cantidad de pedido contradictoria" in problems


def test_receipt_before_planning_horizon_stays_on_true_date():
    events=[event(pr="P0",day="2026-10-10",received=20)]
    rows=model(record(original="30/11/26",plan=date(2026,12,15),events=events))
    fig=timeline_figure(rows,TODAY)
    assert rows[0]["completion"]==date(2026,10,10)
    assert pr_lines(fig,True)[0].x[0]=="2026-10-10"
    assert not bars(fig,"Pendiente de recepción")


def test_json_string_or_native_jsonb_events_equal():
    events=[event(pr="P1",day="2026-10-17",received=20)]
    native=receipt_milestones(events,TODAY)
    encoded=receipt_milestones(json.dumps(events),TODAY)
    assert native==encoded


def test_date_source_conflicts_reported_without_invented_buy_segments():
    rows=model(record(po_approval_distinct=2,original_plan_distinct=2),
               record(pos="20",approval_raw=None,approval_distinct=0))
    assert "Aprobaciones de pedido contradictorias" in rows[0]["issues"]
    assert "Planes originales contradictorios" in rows[0]["issues"]
    assert rows[1]["issue"]=="Sin fecha de aprobación SC válida"
    fig=timeline_figure(rows,TODAY)
    assert not bars(fig,"SC → Pedido aprobado")


def test_plotly_same_compact_appearance_and_axis_180_without_year():
    rows=model(*(record(pos=str(10*i)) for i in range(1,9)))
    fig=timeline_figure(rows,TODAY)
    assert fig.layout.showlegend is False
    assert fig.layout.dragmode is False
    assert fig.layout.xaxis.fixedrange is True
    assert fig.layout.yaxis.fixedrange is True
    # Plotly normalizes +180 to -180; these are the same orientation.
    assert fig.layout.xaxis.tickangle==-180
    assert fig.layout.xaxis.tickformat=="%d/%m"
    assert fig.layout.xaxis.type=="date"
    assert len(fig.layout.yaxis.ticktext)==8
    assert list(fig.layout.yaxis.ticktext)==[
        f"761453/{10*i}" for i in range(1,9)
    ]
    assert fig.layout.height==max(152,114+18*8)
    assert fig.layout.yaxis.tickvals[0]-fig.layout.yaxis.tickvals[1]==pytest.approx(ROW_PITCH)
    red=bars(fig,"SC → Pedido aprobado")[0]
    assert red.width==BAR_WIDTH==0.47
    chart_px=fig.layout.height-fig.layout.margin.t-fig.layout.margin.b
    gap=(ROW_PITCH-BAR_WIDTH)*chart_px / (
        fig.layout.yaxis.range[1]-fig.layout.yaxis.range[0]
    )
    assert 1.5<=gap<=3.5
    assert fig.layout.shapes[0].x0==TODAY.isoformat()
    assert fig.layout.shapes[0].line.color==TODAY_LINE
    assert fig.layout.hovermode=="closest"


def test_sc_missing_from_group_keeps_empty_row():
    rows=model(record(),{"sc_no":"999999","sc_pos":None,
                         "approval_raw":None,"approval_distinct":None})
    assert rows[1]["label"]=="999999/—"
    fig=timeline_figure(rows,TODAY)
    assert len(fig.layout.yaxis.ticktext)==2


def test_empty_and_invalid_today():
    assert build_timeline(pd.DataFrame(),TODAY)==[]
    assert len(timeline_figure([],TODAY).layout.shapes)==1
    with pytest.raises(ValueError):
        build_timeline(pd.DataFrame(),"date invalid")


def test_sql_source_preserves_single_read_per_overview():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    sql=app.split('po_link_summary=po_link_overview+"""',1)[1].split('"""',1)[0]
    assert "jsonb_agg(jsonb_build_object(" in sql
    assert "'po_qty',ev.ordered_qty" in sql
    assert "'delivered_qty',ev.delivered_qty" in sql
    assert "LEFT JOIN core.po_lines p" in sql
    assert "LEFT JOIN core.receipts r" in sql
    assert sql.count("FROM planning.v_sc_source_detail v")==1
    assert "v.snapshot_id=s.snapshot_id AND v.company=s.company" in sql
    assert app.count("receipt_closure.receipt_events")==2  # SC + Group, both on demand
    assert "query(" not in app.split("def render_planning_timeline(",1)[1].split(
        "def render_sc_detail(",1
    )[0]
    assert "UPDATE core." not in app


def test_shared_renderer_and_locked_plotly_config():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    block=app.split("def render_planning_timeline(",1)[1].split(
        "def render_sc_detail(",1
    )[0]
    assert "ampliación del plan (rosa pastel)" in block
    assert "Hitos azules: PR parciales" in block
    assert "config={\"displayModeBar\":False,\"scrollZoom\":False," in block
    assert "\"doubleClick\":False,\"editable\":False" in block
    assert 'render_planning_timeline(sc_timeline_source,madrid_today' in app
    assert 'render_planning_timeline(timeline_source,madrid_today' in app
    assert app.count('on_select="rerun",selection_mode="single-row"')==2
    assert app.count('render_sc_detail(line, sid, context=')==2
    assert "hand_deliveries.clear()" in app
    code=(ROOT/"src/planning_timeline.py").read_text(encoding="utf-8")
    assert "triangle-up" not in code and "warning_hover" not in code


def test_advanced_plan_never_overlays_original_orange_with_grey():
    rows=model(record(original="31/10/26",plan=date(2026,10,20),
                      events=[event()]))
    fig=timeline_figure(rows,TODAY)
    orange=bars(fig,"Pedido → Plan original")[0]
    grey=bars(fig,"Pendiente de recepción")[0]
    assert orange.base[0]=="2026-10-10"
    assert orange.x[0]==21*86400000
    assert grey.base[0]=="2026-10-31"
    assert grey.x[0]==8*86400000
    assert not bars(fig,"Plan original → Plan actual")


@pytest.mark.parametrize("position", ["10","20","30","40","50","60"])
def test_sc_761488_real_erp_dates_keep_all_13_red_days_uncovered(position):
    # Snapshot 8 actual raw ERP values: approval 01/10, order 14/10,
    # original and current plan 05/10 (plan predates order).
    rows=model(record(
        pos=position, approval="01/10/26", order="14/10/26",
        original="05/10/26", plan=date(2026,10,5),
        events=[event(po="762087",pos=str(int(position)//10),qty=20)]
    ))
    row=rows[0]
    assert "Plan original anterior a aprobación del pedido" in row["issues"]
    fig=timeline_figure(rows,TODAY)
    red=bars(fig,"SC → Pedido aprobado")[0]
    grey=bars(fig,"Pendiente de recepción")[0]
    assert red.base[0]=="2026-10-01"
    assert red.x[0]==13*86400000
    assert grey.base[0]=="2026-10-14"
    assert grey.x[0]==25*86400000
    assert not bars(fig,"Pedido → Plan original")
    assert not bars(fig,"Plan original → Plan actual")
    assert fig.layout.showlegend is False
    assert fig.layout.dragmode is False
    assert fig.layout.xaxis.fixedrange is True
    assert fig.layout.xaxis.tickformat=="%d/%m"
    assert fig.layout.xaxis.tickangle==-180


def test_grey_never_overlays_valid_purchasing_segments_across_date_patterns():
    cases=[
        # Earlier plan than PO approval, as shown by the user's screenshot.
        ("01/10/26","14/10/26","05/10/26",date(2026,10,5)),
        # Original plan after PO approval but current plan accelerated.
        ("01/10/26","14/10/26","31/10/26",date(2026,10,20)),
        # Original plan and current plan both after PO approval.
        ("01/10/26","14/10/26","31/10/26",date(2026,11,1)),
        # Current plan after PO approval but original plan before it.
        ("01/10/26","14/10/26","05/10/26",date(2026,10,20)),
    ]
    for sc_date,po_date,orig_date,plan in cases:
        fig=timeline_figure(model(record(
            approval=sc_date,order=po_date,original=orig_date,plan=plan
        )),TODAY)
        grey=bars(fig,"Pendiente de recepción")[0]
        grey_start=date.fromisoformat(grey.base[0])
        for trace in fig.data:
            if trace.type!="bar" or trace.name=="Pendiente de recepción":
                continue
            finish=(date.fromisoformat(trace.base[0])
                    + timedelta(milliseconds=int(trace.x[0])))
            assert grey_start >= finish
