from datetime import date
from decimal import Decimal

import pandas as pd

from src.sc_overview import DISPLAY_COLUMNS, overview_display, overview_row_style


def test_exact_columns_in_requested_order_and_same_row_index():
    source=pd.DataFrame([
        {"company":"210","sc_no":"00071","sc_pos":"5",
         "project":"PROJ-1","po_positions":"00321/8, 00322/1",
         "article":"A1","description":"Material","planned_date":date(2026,11,6),
         "requested_qty":Decimal("5"),"ordered_qty":Decimal("5"),
         "received_qty":Decimal("3"),"approved_qty":Decimal("2"),
         "workflow_state":"Parcialmente aprobadas"},
        {"company":"210","sc_no":"00071","sc_pos":"20",
         "project":"PROJ-2","po_positions":None,
         "article":"A2","description":"Sin pedido","planned_date":None,
         "requested_qty":Decimal("3"),"ordered_qty":Decimal("0"),
         "received_qty":Decimal("0"),"approved_qty":Decimal("0"),
         "workflow_state":"Pendiente pedido"},
    ],index=[11,16])
    view=overview_display(source)
    assert tuple(view.columns)==DISPLAY_COLUMNS
    assert DISPLAY_COLUMNS[6:10] == ("Sol","Ped","Rec","Apr")
    assert list(view.index)==[11,16]
    assert view["SC/Pos"].tolist()==["00071/5","00071/20"]
    assert view["PO/Pos"].tolist()==["00321/8, 00322/1","—"]
    assert view["fecha_plan"].tolist()==["06/11/2026","—"]
    assert view.loc[11,"Rec"]==Decimal("3")
    assert view.loc[16,"estado"]=="Pendiente pedido"
    assert all(col not in view for col in ("company","coverage_pct","workflow_issue"))


def test_styles_pastel_rows_and_overdue_date_in_red_bold():
    today=date(2026,11,7)
    view=pd.DataFrame([
        {"estado":"Material sin recibir","fecha_plan":"06/11/2026","Proyecto":"ABC"},
        {"estado":"Completado","fecha_plan":"07/11/2026","Proyecto":"XYZ"},
        {"estado":"Pendiente pedido","fecha_plan":"20/11/2026","Proyecto":"T"},
    ])
    first=overview_row_style(view.iloc[0],today)
    assert len(first)==3
    assert "#FFEDD5" in first[0] and "#FFEDD5" in first[2]
    assert "#B91C1C" in first[1] and "font-weight: bold" in first[1]
    assert "#FFEDD5" in first[1]
    second=overview_row_style(view.iloc[1],today)
    assert "font-weight" not in second[1]
    assert "#DCFCE7" in second[1]
    third=overview_row_style(view.iloc[2],today)
    assert "#FEE2E2" in third[1] and "font-weight" not in third[1]


def test_overdue_plan_is_unhighlighted_for_every_other_state():
    today=date(2026,11,7)
    for state in ("Completado", "Pendiente pedido", "Pendiente aprobación",
                  "Parcialmente aprobadas", "SC anulada", "Pendiente conciliación"):
        row=pd.Series({"Proyecto":"P", "fecha_plan":"06/11/2026", "estado":state})
        styles=overview_row_style(row,today)
        assert all("font-weight: bold" not in style for style in styles)
        assert all("#B91C1C" not in style for style in styles)
    row=pd.Series({"Proyecto":"P", "fecha_plan":"06/11/2026",
                   "estado":"Material sin recibir"})
    styles=overview_row_style(row,today)
    assert "color: #B91C1C" in styles[1]
    assert "font-weight: bold" in styles[1]


def test_unknown_states_and_invalid_dates_are_safe():
    frame=pd.DataFrame([
        {"estado":"Pendiente conciliación","fecha_plan":"—"},
        {"estado":"Pendiente conciliación","fecha_plan":"incorrecta"},
    ])
    assert overview_row_style(frame.iloc[0],date(2026,11,7))==["",""]
    assert overview_row_style(frame.iloc[1],date(2026,11,7))==["",""]


def test_legacy_coverage_fallback_preserves_exact_columns():
    source=pd.DataFrame([{
        "company":"210","sc_no":"10","sc_pos":"1",
        "project":"PROJ","po_positions":None,"planned_date":None,
        "article":"A","description":"B",
        "requested_qty":Decimal("1"),"ordered_qty":None,
        "received_qty":None,"approved_qty":None,
        "coverage_state":"no_approved_coverage",
    }])
    view=overview_display(source)
    assert tuple(view.columns)==DISPLAY_COLUMNS
    assert view.iloc[0]["estado"]=="no_approved_coverage"
