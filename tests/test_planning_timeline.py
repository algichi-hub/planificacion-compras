"""Two stacked SC calendar bands: ERP milestones, data quality and regression."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.planning_timeline import (
    as_day, build_timeline, timeline_figure,
    SC_ORDER, ORDER_ORIGINAL, REPLAN,
    RECEIPT_WAIT, RECEIPT_APPROVAL, RECEIPT_APPROVED, TODAY_LINE,
)

ROOT=Path(__file__).resolve().parents[1]
TODAY=date(2026,11,8)


def row(pos="10", plan=date(2026,12,15), state="Material sin recibir",
        completion=None, **overrides):
    result=dict(
        company="210",sc_no="761453",sc_pos=pos,
        approval_raw="25/09/26",approval_distinct=1,
        po_approval_raw="10/10/26",po_approval_distinct=1,
        original_plan_raw="30/11/26",original_plan_distinct=1,
        planned_date=plan,workflow_state=state,
        first_receipt_date=None,first_approved_pr_date=None,
        first_approved_pr_qty=None,requested_qty=Decimal("100"),
        completion_date=completion,
    )
    result.update(overrides)
    return result


def model(*records):
    return build_timeline(pd.DataFrame(records),TODAY)


def spans(fig, title):
    return [t for t in fig.data if t.type=="bar" and t.name==title]


def test_date_parse_and_empty_invalid():
    assert as_day("25/09/26")==date(2026,9,25)
    assert as_day("25/09/2026")==date(2026,9,25)
    assert as_day("2026-12-15")==date(2026,12,15)
    assert as_day(pd.Timestamp("2026-11-08T12:30:00"))==TODAY
    for bad in (None,"","—","99/99/26","not a date"):
        assert as_day(bad) is None


def test_upper_band_red_is_stronger_than_pastel_and_periods_are_exact():
    data=model(row())[0]
    assert data["po_approval"]==date(2026,10,10)
    assert data["original_plan"]==date(2026,11,30)
    fig=timeline_figure([data],TODAY)
    red=spans(fig,"SC → Pedido aprobado")[0]
    orange=spans(fig,"Pedido → Plan original")[0]
    dark=spans(fig,"Plan original → Plan actual")[0]
    assert red.marker.color==SC_ORDER=="#DC2626"
    assert orange.marker.color==ORDER_ORIGINAL
    assert dark.marker.color==REPLAN
    assert red.base[0]=="2026-09-25"
    assert red.x[0]==15*86400000
    assert orange.base[0]=="2026-10-10"
    assert orange.x[0]==51*86400000
    assert dark.base[0]=="2026-11-30"
    assert dark.x[0]==15*86400000


def test_plan_advance_omits_dark_orange_entirely():
    fig=timeline_figure(model(row(plan=date(2026,11,12))),TODAY)
    assert not spans(fig,"Plan original → Plan actual")
    assert len(spans(fig,"Pedido → Plan original"))==1


def test_identical_original_and_current_plan_has_no_dark_orange():
    fig=timeline_figure(model(row(plan=date(2026,11,30))),TODAY)
    assert not spans(fig,"Plan original → Plan actual")


def test_order_approval_missing_conflicted_or_after_original_not_faked():
    for overrides in (
        {"po_approval_raw":None,"po_approval_distinct":0},
        {"po_approval_raw":"10/10/26","po_approval_distinct":2},
        {"po_approval_raw":"01/12/26"},
        {"po_approval_raw":"20/11/26","original_plan_raw":"01/11/26"},
    ):
        fig=timeline_figure(model(row(**overrides)),TODAY)
        assert not spans(fig,"SC → Pedido aprobado") or overrides.get("po_approval_raw")=="20/11/26"
        assert not spans(fig,"Pedido → Plan original")


def test_two_bands_share_one_sc_label_with_exactly_half_thickness():
    fig=timeline_figure(model(row()),TODAY)
    bar_traces=[t for t in fig.data if t.type=="bar"]
    assert bar_traces
    assert all(t.width==0.22 for t in bar_traces)
    assert set(fig.layout.yaxis.ticktext)=={"761453/10"}
    assert fig.layout.yaxis.tickvals==(0,)
    upper=spans(fig,"SC → Pedido aprobado")[0]
    lower=spans(fig,"Hasta primera recepción")[0]
    assert upper.y[0]==0.13
    assert lower.y[0]==-0.13
    assert 0 < upper.y[0]-upper.width/2-(lower.y[0]+lower.width/2) <= 0.05
    assert fig.layout.xaxis.type=="date"
    assert fig.layout.shapes[0].x0==TODAY.isoformat()
    assert fig.layout.shapes[0].line.color==TODAY_LINE


def test_no_receipts_gray_from_sc_approval_until_today():
    fig=timeline_figure(model(row()),TODAY)
    gray=spans(fig,"Hasta primera recepción")[0]
    assert gray.marker.color==RECEIPT_WAIT
    assert gray.base[0]=="2026-09-25"
    assert gray.x[0]==44*86400000
    assert not spans(fig,"Pendiente aprobación PR")
    assert not spans(fig,"Desde primer PR aprobado")


def test_first_pr_received_but_not_approved_yellow_through_today():
    data=model(row(first_receipt_date=date(2026,10,15)))[0]
    fig=timeline_figure([data],TODAY)
    gray=spans(fig,"Hasta primera recepción")[0]
    yellow=spans(fig,"Pendiente aprobación PR")[0]
    assert gray.x[0]==20*86400000
    assert yellow.marker.color==RECEIPT_APPROVAL
    assert yellow.base[0]=="2026-10-15"
    assert yellow.x[0]==24*86400000
    assert not spans(fig,"Desde primer PR aprobado")


def test_first_unapproved_pr_then_later_fully_approved_partial_pr():
    data=model(row(
        first_receipt_date=date(2026,10,1),
        first_approved_pr_date=date(2026,10,12),
        first_approved_pr_qty=Decimal("20"),
    ))[0]
    fig=timeline_figure([data],TODAY)
    yellow=spans(fig,"Hasta primer PR íntegramente aprobado")[0]
    green=spans(fig,"Desde primer PR aprobado")[0]
    assert yellow.marker.color==RECEIPT_APPROVAL
    assert yellow.base[0]=="2026-10-01"
    assert yellow.x[0]==11*86400000
    assert green.marker.color==RECEIPT_APPROVED
    assert green.base[0]=="2026-10-12"
    assert green.x[0]==27*86400000


def test_multiple_partial_pr_completed_green_ends_at_verified_closure():
    data=model(row(
        state="Completado",completion=date(2026,10,20),
        first_receipt_date=date(2026,10,1),
        first_approved_pr_date=date(2026,10,1),
        first_approved_pr_qty=Decimal("30"),
    ))[0]
    assert data["first_pr_full_total"] is False
    assert data["cutoff"]==date(2026,10,20)
    fig=timeline_figure([data],TODAY)
    green=spans(fig,"Desde primer PR aprobado")[0]
    assert green.base[0]=="2026-10-01"
    assert green.x[0]==19*86400000
    assert not any(t.type=="scatter" and t.name=="Aprobación total en primer PR"
                   for t in fig.data)


def test_unique_single_pr_fully_approved_is_medium_vertical_green_line():
    data=model(row(
        state="Completado",completion=date(2026,10,20),
        first_receipt_date=date(2026,10,20),
        first_approved_pr_date=date(2026,10,20),
        first_approved_pr_qty=Decimal("100"),
    ))[0]
    assert data["first_pr_full_total"] is True
    fig=timeline_figure([data],TODAY)
    lines=[t for t in fig.data if t.type=="scatter" and
           t.name=="Aprobación total en primer PR"]
    assert len(lines)==1
    assert lines[0].line.color==RECEIPT_APPROVED
    assert lines[0].line.width==3.5
    assert list(lines[0].x)==["2026-10-20","2026-10-20"]
    assert not spans(fig,"Desde primer PR aprobado")
    assert not spans(fig,"Pendiente aprobación PR")


def test_single_pr_partially_approved_not_claimed_approved():
    fig=timeline_figure(model(row(
        first_receipt_date=date(2026,10,20),
        first_approved_pr_date=None,
        first_approved_pr_qty=None,
    )),TODAY)
    assert spans(fig,"Pendiente aprobación PR")
    assert not spans(fig,"Desde primer PR aprobado")


def test_erp_complete_with_missing_closure_does_not_extend_green_to_today():
    data=model(row(
        state="Completado",completion=None,
        first_receipt_date=date(2026,10,1),
        first_approved_pr_date=date(2026,10,1),
        first_approved_pr_qty=Decimal("30"),
    ))[0]
    assert "Sin fecha verificable de recepción completada" in data["issues"]
    assert data["cutoff"]==date(2026,10,1)
    fig=timeline_figure([data],TODAY)
    assert not spans(fig,"Desde primer PR aprobado")
    assert not spans(fig,"Pendiente aprobación PR")


def test_completed_erp_stops_receipt_band_but_not_upper_planning_dates():
    data=model(row(
        state="Completado",completion=date(2026,10,20),
        first_receipt_date=date(2026,10,1),
        first_approved_pr_date=date(2026,10,1),
        first_approved_pr_qty=Decimal("30"),
    ))[0]
    fig=timeline_figure([data],TODAY)
    assert spans(fig,"Plan original → Plan actual")
    green=spans(fig,"Desde primer PR aprobado")[0]
    assert date.fromisoformat(green.base[0])==date(2026,10,1)
    assert green.x[0]==19*86400000


def test_inconsistent_or_missing_source_dates_never_fabricated():
    frames=[
        row(approval_raw=None,approval_distinct=0),
        row(approval_raw="25/09/26",approval_distinct=2),
        row(po_approval_raw="01/12/26",original_plan_raw="01/11/26"),
        row(first_receipt_date=date(2026,9,1)),
        row(first_receipt_date=date(2026,10,10),
            first_approved_pr_date=date(2026,10,1)),
        row(plan=None),
    ]
    results=model(*frames)
    assert results[0]["issue"]=="Sin fecha de aprobación SC válida"
    assert results[1]["issue"]=="Aprobaciones SC diferentes en origen"
    assert "Primera recepción con fecha inconsistente" in results[3]["issues"]
    assert "Primer PR aprobado con fecha inconsistente" in results[4]["issues"]
    fig=timeline_figure(results,TODAY)
    assert not any(t.name in ("Aviso de retraso","Recepción fuera de plazo")
                   for t in fig.data)


def test_group_missing_position_is_rendered_without_invented_bar():
    result=model(row(),{"sc_no":"700000","sc_pos":None,"company":None,
                        "approval_distinct":None,"approval_raw":None})
    assert result[1]["label"]=="700000/—"
    fig=timeline_figure(result,TODAY)
    assert len(fig.layout.yaxis.tickvals)==2
    assert all(t.y[0]!=-0.87 for t in fig.data if t.type=="bar")


def test_erp_workflow_precedes_manually_derived_handover_status():
    a=model(row(state="Completado",completion=date(2026,10,20),
                first_receipt_date=date(2026,10,1),
                first_approved_pr_date=date(2026,10,1),
                first_approved_pr_qty=Decimal("30")))[0]
    b=model({**row(state="Completado",completion=date(2026,10,20),
                first_receipt_date=date(2026,10,1),
                first_approved_pr_date=date(2026,10,1),
                first_approved_pr_qty=Decimal("30")),
             "display_state":"Entregado total"})[0]
    assert a==b
    assert timeline_figure([a],TODAY).to_plotly_json()["data"]==timeline_figure([b],TODAY).to_plotly_json()["data"]


def test_empty_render_and_invalid_today():
    assert build_timeline(pd.DataFrame(),TODAY)==[]
    assert len(timeline_figure([],TODAY).layout.shapes)==1
    with pytest.raises(ValueError):
        build_timeline(pd.DataFrame(),"bad")
    with pytest.raises(ValueError):
        timeline_figure([],"bad")


def test_sql_source_efficiency_and_read_only_roles():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    sql=app.split('po_link_summary="""',1)[1].split('"""',1)[0]
    assert sql.count("FROM planning.v_sc_source_detail v")==1
    assert "v.snapshot_id=s.snapshot_id AND v.company=s.company" in sql
    assert "v.sc_no=s.sc_no AND v.sc_pos=s.sc_pos" in sql
    assert "ix_sc_source_rows_lookup" in (ROOT/"migrations/009_sc_source_detail_view.sql").read_text()
    assert "v.fields->>'FECHA APROBACIÓN DEL PEDIDO__41'" in sql
    assert "v.fields->>'PEDIDO__16'=linked.plan_po_no" in sql
    assert "v.fields->>'POSICIÓN__17'=linked.plan_po_pos" in sql
    assert "PARTITION BY r.receipt_no" in sql
    assert "r.delivered_qty" in sql and "r.approved_qty" in sql
    assert "s.approved_qty>=s.requested_qty" in sql
    assert app.count("receipt_closure.first_receipt_date,receipt_closure.first_approved_pr_date")==3
    assert app.count("timeline_dates.po_approval_raw,timeline_dates.po_approval_distinct")==3
    assert "query(" not in app.split("def render_planning_timeline(",1)[1].split("def render_sc_detail(",1)[0]
    assert "UPDATE core." not in app
    assert 'render_planning_timeline(overview,madrid_today' in app
    assert 'render_planning_timeline(group_source,madrid_today' in app


def test_other_views_and_selection_remain_unchanged():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert app.count('on_select="rerun",selection_mode="single-row"')==2
    assert app.count('render_sc_detail(line, sid, context=')==2
    assert 'with tab4:' in app and 'with tab5:' in app
    assert 'hand_deliveries.clear()' in app
    code=(ROOT/"src/planning_timeline.py").read_text(encoding="utf-8")
    for forbidden in ("triangle-up","warning_hover","icon_offset_days","Aviso de retraso"):
        assert forbidden not in code



def test_new_celeste_and_light_gray_with_no_legend_and_compact_height():
    assert REPLAN == "#38BDF8"
    assert RECEIPT_WAIT == "#CBD5E1"
    rows=model(
        row(pos="10",first_receipt_date=date(2026,10,1),
            first_approved_pr_date=date(2026,10,12),
            first_approved_pr_qty=Decimal("20")),
        row(pos="20",plan=date(2026,12,20)),
        row(pos="30",plan=date(2026,12,22)),
    )
    fig=timeline_figure(rows,TODAY)
    assert fig.layout.showlegend is False
    assert list(fig.layout.yaxis.ticktext)==["761453/10","761453/20","761453/30"]
    blue=spans(fig,"Plan original → Plan actual")[0]
    gray=spans(fig,"Hasta primera recepción")[0]
    assert blue.marker.color==REPLAN
    assert gray.marker.color==RECEIPT_WAIT
    assert fig.layout.height==max(152,114+18*len(rows))
    assert all(t.width==0.22 for t in fig.data if t.type=="bar")
    upper=spans(fig,"SC → Pedido aprobado")[0]
    # Two bands separated by 0.04 units; not overlapping, minimal visual gap.
    gap=upper.y[0]-upper.width/2-(gray.y[0]+gray.width/2)
    assert gap==pytest.approx(0.04)
    assert " · " not in " ".join(fig.layout.yaxis.ticktext)
    assert fig.layout.xaxis.type=="date"
    assert fig.layout.shapes[0].x0==TODAY.isoformat()


def test_no_company_in_axis_even_when_source_company_differs():
    data=model(row(pos="10",company="210"),row(pos="20",company="310"))
    fig=timeline_figure(data,TODAY)
    assert list(fig.layout.yaxis.ticktext)==["761453/10","761453/20"]
    assert all(" · " not in r["label"] for r in data)
    assert len(data)==2


def test_shared_app_caption_tracks_new_colors_without_sql_or_selection_changes():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "ampliación del plan (azul celeste)" in app
    assert "(gris claro)" in app
    assert "naranja oscuro" not in app.split("def render_planning_timeline(",1)[1].split("def render_sc_detail(",1)[0]
    assert "query(" not in app.split("def render_planning_timeline(",1)[1].split("def render_sc_detail(",1)[0]
    assert app.count('on_select="rerun",selection_mode="single-row"')==2



@pytest.mark.parametrize("positions", [2, 3, 8, 20])
def test_inter_sc_group_gap_is_only_a_few_pixels(positions):
    """Bar groups remain distinct, with ~2-3 px between adjacent SCs."""
    rows=model(*(row(pos=str(10*(i+1))) for i in range(positions)))
    fig=timeline_figure(rows,TODAY)
    assert fig.layout.height==max(152,114+18*positions)
    assert fig.layout.margin.t==32
    assert fig.layout.margin.b==82
    pitch=fig.layout.yaxis.tickvals[0]-fig.layout.yaxis.tickvals[1]
    assert pitch==pytest.approx(0.55)
    assert len(fig.layout.yaxis.tickvals)==positions
    red=spans(fig,"SC → Pedido aprobado")[0]
    gray=spans(fig,"Hasta primera recepción")[0]
    # Two bands per position are packed almost edge-to-edge.
    for index in range(positions):
        assert red.y[index]==pytest.approx(gray.y[index]+0.26)
        assert red.width==gray.width==0.22
        intra=red.y[index]-red.width/2-(gray.y[index]+gray.width/2)
        assert intra==pytest.approx(0.04)
    # Distance between lower edge of group i and upper edge of group i+1.
    group_gap=gray.y[0]-gray.width/2 - (red.y[1]+red.width/2)
    assert group_gap==pytest.approx(0.07)
    chart_pixels=fig.layout.height-fig.layout.margin.t-fig.layout.margin.b
    axis_span=fig.layout.yaxis.range[1]-fig.layout.yaxis.range[0]
    gap_pixels=group_gap*chart_pixels/axis_span
    assert 1.5<=gap_pixels<=3.5
    assert fig.layout.showlegend is False


def test_slim_single_row_and_approval_line_maintain_correct_y_coordinates():
    single=model(row(
        state="Completado",completion=date(2026,10,20),
        first_receipt_date=date(2026,10,20),
        first_approved_pr_date=date(2026,10,20),
        first_approved_pr_qty=Decimal("100"),
    ))
    fig=timeline_figure(single,TODAY)
    assert fig.layout.height==152
    assert list(fig.layout.yaxis.tickvals)==[0]
    assert list(fig.layout.yaxis.ticktext)==["761453/10"]
    approval=next(t for t in fig.data if t.name=="Aprobación total en primer PR")
    assert list(approval.y)==[-0.235,-0.015]
    assert fig.layout.yaxis.range[0]<approval.y[0]<approval.y[1]<fig.layout.yaxis.range[1]



@pytest.mark.parametrize("positions", [1, 3, 20])
def test_timeline_native_plotly_navigation_is_locked_but_hover_remains(positions):
    figure=timeline_figure(
        model(*(row(pos=str(i+1)) for i in range(positions))),TODAY
    )
    assert figure.layout.dragmode is False
    assert figure.layout.xaxis.fixedrange is True
    assert figure.layout.yaxis.fixedrange is True
    assert figure.layout.hovermode=="closest"
    assert figure.layout.showlegend is False
    bars=[trace for trace in figure.data if trace.type=="bar"]
    assert bars and all(trace.hovertemplate=="%{customdata}<extra></extra>"
                        for trace in bars)
    assert figure.layout.shapes[0].x0==TODAY.isoformat()


def test_only_shared_timeline_plotly_chart_uses_locked_config():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    block=app.split("def render_planning_timeline(",1)[1].split(
        "def render_sc_detail(",1
    )[0]
    assert 'config={"displayModeBar":False,"scrollZoom":False,' in block
    assert '"doubleClick":False,"editable":False' in block
    assert 'key=f"{key}_planning_timeline"' in block
    assert 'render_planning_timeline(overview,madrid_today' in app
    assert 'render_planning_timeline(group_source,madrid_today' in app
    assert app.count('config={"displayModeBar":False,"scrollZoom":False,')==1
    assert "query(" not in block
    assert "st.plotly_chart" in block



@pytest.mark.parametrize("positions", [1, 3, 20])
def test_date_ticks_are_vertical_with_room_and_same_plot_area(positions):
    fig=timeline_figure(
        model(*(row(pos=str(i+1)) for i in range(positions))),TODAY
    )
    assert fig.layout.xaxis.tickangle==90
    assert fig.layout.xaxis.tickformat=="%d/%m/%Y"
    assert fig.layout.xaxis.fixedrange is True
    assert fig.layout.yaxis.fixedrange is True
    assert fig.layout.dragmode is False
    assert fig.layout.margin.b==82
    # Increased overall height exactly compensates the larger bottom margin:
    # no compression of the preexisting dense SC bars.
    old_chart_height=max(110,72+18*positions)-32-40
    new_chart_height=fig.layout.height-fig.layout.margin.t-fig.layout.margin.b
    assert new_chart_height==old_chart_height
    assert fig.layout.showlegend is False
