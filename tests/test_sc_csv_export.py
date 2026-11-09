"""Regression: exact PR list and Spanish CSV shared by Seguimiento/Group SC."""
import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pandas as pd

from src.sc_csv_export import sc_overview_csv
from src.sc_overview import overview_display, DISPLAY_COLUMNS


def fixture():
    return pd.DataFrame([
        dict(company="210", sc_no="000761452", sc_pos="10", project="P",
             po_positions="000762087/01, 762088/20",pr_numbers="00051, 00052",
             article="A",description='Conector; \"tipo A\"',
             planned_date=date(2026,11,9),requested_qty=Decimal("1234.250000"),
             ordered_qty=Decimal("1234.250000"),received_qty=Decimal("2.000001"),
             approved_qty=Decimal("2"),hand_qty=Decimal("1.250000"),
             workflow_state="Completado"),
        dict(company="210", sc_no="000761452", sc_pos="20",project="P",
             po_positions=None,pr_numbers=None,article="B",
             description="=CMD()",planned_date=None,requested_qty=Decimal("0"),
             ordered_qty=Decimal("0"),received_qty=Decimal("0"),
             approved_qty=Decimal("0"),hand_qty=None,workflow_state="Pendiente pedido"),
    ])


def test_pr_last_column_and_no_data_preserves_identifiers_and_decimals():
    source=fixture()
    original=source.copy(deep=True)
    shown=overview_display(source)
    assert tuple(shown.columns)==DISPLAY_COLUMNS
    assert shown.columns[-1]=="PRs"
    assert shown["PRs"].tolist()==["00051, 00052","—"]
    assert shown["SC/Pos"].tolist()==["000761452/10","000761452/20"]
    assert isinstance(shown.loc[0,"Sol"],Decimal)
    assert source.equals(original)


def test_csv_excel_roundtrip_all_rows_columns_and_special_characters():
    view=overview_display(fixture())
    raw=sc_overview_csv(view)
    assert raw.startswith(b"\xef\xbb\xbf")
    parsed=list(csv.DictReader(StringIO(raw.decode("utf-8-sig")),delimiter=";"))
    assert len(parsed)==2
    assert list(parsed[0])==[x for x in DISPLAY_COLUMNS if x!=" "]
    assert parsed[0]["SC/Pos"]=="000761452/10"
    assert parsed[0]["PO/Pos"]=="000762087/01, 762088/20"
    assert parsed[0]["PRs"]=="00051, 00052"
    assert parsed[0]["description"]=='Conector; "tipo A"'
    assert parsed[0]["Sol"]=="1234,25"
    assert parsed[0]["Rec"]=="2,000001"
    assert parsed[0]["Ent"]=="1,25"
    assert parsed[0]["fecha_plan"]=="09/11/2026"
    assert parsed[1]["description"]=="'=CMD()"
    assert parsed[1]["PRs"]=="—"
    assert b"\r\n" in raw
    assert view.loc[0,"Sol"]==Decimal("1234.250000")


def test_empty_csv_keeps_headers():
    raw=sc_overview_csv(overview_display(pd.DataFrame()))
    parsed=list(csv.reader(StringIO(raw.decode("utf-8-sig")),delimiter=";"))
    assert parsed==[[x for x in DISPLAY_COLUMNS if x!=" "]]


def test_both_views_share_pr_projection_export_and_selection():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    sc=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert app.count("linked.po_positions,linked.planned_date,linked.pr_numbers")==3
    assert app.count("GROUP BY r.receipt_no")==1
    assert "r.snapshot_id=lr.snapshot_id" in app
    assert "lr.sc_no=s.sc_no AND lr.sc_pos=s.sc_pos" in app
    assert "r.po_no=lr.po_no AND r.po_pos=lr.po_pos" in app
    assert "sc_export_button(visible_overview," in sc
    assert "sc_export_button(bulk_view," in group
    assert sc.index("sc_export_button") > sc.index("event=st.dataframe(")
    assert group.index("sc_export_button") > group.index("event_group=st.dataframe(")
    assert 'selection_mode="single-row"' in sc
    assert 'selection_mode="single-row"' in group
    assert "render_sc_detail(line, sid" in sc
    assert "render_sc_detail(line, sid" in group
    assert "data=sc_overview_csv(view)" in app
