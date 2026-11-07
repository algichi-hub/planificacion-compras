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
    assert DISPLAY_COLUMNS[7:11] == ("Sol","Ped","Rec","Apr")
    assert DISPLAY_COLUMNS[0] == " "
    assert view.loc[11," "].startswith("data:image/svg+xml;utf8,")
    assert list(view.index)==[11,16]
    assert view["SC/Pos"].tolist()==["00071/5","00071/20"]
    assert view["PO/Pos"].tolist()==["00321/8, 00322/1","—"]
    assert view["fecha_plan"].tolist()==["06/11/2026","—"]
    assert view.loc[11,"Rec"]==Decimal("3")
    assert view.loc[16,"estado"]=="Pendiente pedido"
    assert all(col not in view for col in ("company","coverage_pct","workflow_issue"))


def test_styles_have_no_backgrounds_and_overdue_date_in_red_bold():
    today=date(2026,11,7)
    view=pd.DataFrame([
        {"estado":"Material sin recibir","fecha_plan":"06/11/2026","Proyecto":"ABC"},
        {"estado":"Completado","fecha_plan":"07/11/2026","Proyecto":"XYZ"},
        {"estado":"Pendiente pedido","fecha_plan":"20/11/2026","Proyecto":"T"},
    ])
    first=overview_row_style(view.iloc[0],today)
    assert len(first)==3
    assert all("background" not in x for x in first)
    assert "#B91C1C" in first[1] and "font-weight: bold" in first[1]
    assert all("background" not in x for x in first)
    second=overview_row_style(view.iloc[1],today)
    assert "font-weight" not in second[1]
    assert all(x == "" for x in second)
    third=overview_row_style(view.iloc[2],today)
    assert all(x == "" for x in third)


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


def test_symbol_icons_are_distinct_and_unknowns_are_safe():
    from src.status_icons import status_icon
    states=("Completado","Pendiente pedido","Material sin recibir",
            "Pendiente aprobación","Parcialmente aprobadas","SC anulada",
            "Pendiente conciliación")
    icons=[status_icon(s) for s in states]
    assert len(set(icons))==len(states)
    assert all(icon.startswith("data:image/svg+xml;utf8,") for icon in icons)
    assert all("background" not in icon for icon in icons)
    assert status_icon("not a known state") is None


def test_material_and_approval_icons_use_requested_orange_and_basic_yellow():
    from urllib.parse import unquote
    from src.status_icons import status_icon
    orange=unquote(status_icon("Material sin recibir"))
    yellow=unquote(status_icon("Pendiente aprobación"))
    assert 'fill="#EA580C"' in orange
    assert 'fill="#EAB308"' in yellow


def test_status_icons_are_70_percent_and_native_column_is_pinned():
    from urllib.parse import unquote
    from pathlib import Path
    from src.status_icons import status_icon
    svg=unquote(status_icon("Completado"))
    # Streamlit scales image columns, so the SVG viewBox—not width—sets glyph size.
    assert 'viewBox="-206 -1166 1372 1372"' in svg
    assert 'width="24" height="24"' in svg
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert 'ImageColumn("", width=38, pinned=True' in app
    assert 'selection_mode="single-row"' in app


def test_exact_requested_google_material_symbols_for_each_state():
    from urllib.parse import unquote
    from src.status_icons import PATHS, STATUS_SYMBOLS, status_icon
    required={
        "Completado":"check_circle",
        "Pendiente pedido":"note_stack",
        "Material sin recibir":"package_2",
        "Pendiente aprobación":"search",
        "Parcialmente aprobadas":"clock_loader_10",
        "SC anulada":"close",
        "Pendiente conciliación":"gpp_maybe",
    }
    for state, glyph in required.items():
        assert STATUS_SYMBOLS[state][0]==glyph
        svg=unquote(status_icon(state))
        assert f'<path d="{PATHS[glyph]}"/>' in svg
        assert 'viewBox="-206 -1166 1372 1372"' in svg
    assert STATUS_SYMBOLS["no_approved_coverage"][0]=="search"


def test_planned_date_semaphore_on_main_and_group_overview():
    from datetime import date, timedelta
    import pandas as pd
    today=date(2026,11,7)
    for delta,color in [
        (-1,"#B91C1C"), (0,"#CA8A04"), (1,"#CA8A04"),
        (7,"#CA8A04"), (8,"#15803D"), (30,"#15803D"),
    ]:
        planned=(today+timedelta(days=delta)).strftime("%d/%m/%Y")
        row=pd.Series({"Proyecto":"P","fecha_plan":planned,"estado":"Material sin recibir"})
        style=overview_row_style(row,today)
        assert f"color: {color}" in style[1]
        assert "font-weight: bold" in style[1]
        assert all("background" not in item for item in style)
        for state in ("Completado","Pendiente pedido","Pendiente aprobación",
                      "Parcialmente aprobadas","SC anulada","Pendiente conciliación",
                      "No encontrada"):
            other=row.copy()
            other["estado"]=state
            assert overview_row_style(other,today)==["","",""]
