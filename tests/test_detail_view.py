from datetime import date
from decimal import Decimal

import pandas as pd

from src.detail_view import display_value, transpose_trace, receptions_table, detail_row_style


def test_numeric_and_date_formatting():
    assert display_value(Decimal("1234.500000")) == "1234,500000"
    assert display_value(date(2026, 11, 6)) == "06/11/2026"
    assert display_value(None) == "—"
    assert display_value("00012") == "00012"


def test_vertical_trace_groups_two_receipts_and_order_without_receipt():
    original=pd.DataFrame([
        {"pedido":"761258","posicion_pedido":"1","articulo_pedido":"2540901522",
         "proveedor":"N00540","cantidad_pedida":Decimal("4.000000"),
         "fecha_planificada":date(2026,9,28),"parte_recepcion":"762514",
         "fecha_recepcion":date(2026,10,1),
         "cantidad_entregada":Decimal("1.000000"),
         "cantidad_aprobada":Decimal("0.000000"),
         "estado_recepcion":"old","estado_vinculo":"verified"},
        {"pedido":"761258","posicion_pedido":"1","articulo_pedido":"2540901522",
         "proveedor":"N00540","cantidad_pedida":Decimal("4.000000"),
         "fecha_planificada":date(2026,9,28),"parte_recepcion":"767054",
         "fecha_recepcion":date(2026,10,5),
         "cantidad_entregada":Decimal("4.000000"),
         "cantidad_aprobada":Decimal("0.000000"),
         "estado_recepcion":"old","estado_vinculo":"verified"},
        {"pedido":"761258","posicion_pedido":"2","articulo_pedido":"2540901522",
         "proveedor":"N00540","cantidad_pedida":Decimal("24.000000"),
         "fecha_planificada":date(2026,11,15),"parte_recepcion":None,
         "fecha_recepcion":None,"cantidad_entregada":None,
         "cantidad_aprobada":None,"estado_recepcion":None,"estado_vinculo":"verified"},
    ])
    view=transpose_trace(original,"Pendiente aprobación")
    assert list(view.columns)==["Campo","Valor"]
    assert view.iloc[0].to_dict()=={"Campo":"Estado SC","Valor":"Pendiente aprobación"}
    assert view.loc[view.Campo=="Pedido/pos","Valor"].tolist()==["761258/1","761258/2"]
    assert view.loc[view.Campo=="Cantidad pedida","Valor"].tolist()==["4,000000","24,000000"]
    receptions=receptions_table(original)
    assert receptions.loc[receptions.Campo=="Recepción 1","Valor"].tolist()==[
        "762514 (01/10/2026, Re: —, Ap: 0, En: 1)"]
    assert receptions.loc[receptions.Campo=="Recepción 2","Valor"].tolist()==[
        "767054 (05/10/2026, Re: —, Ap: 0, En: 4)"]
    assert "Movimiento 1" not in view.Campo.tolist()
    assert "Estado recepción" not in view.Campo.tolist()
    assert "Estado vínculo" not in view.Campo.tolist()
    assert "Parte de recepción" not in view.Campo.tolist()
    assert not view.Campo.str.startswith("Recepción").any()
    assert receptions.loc[receptions.Campo=="Pedido/pos","Valor"].tolist()==["761258/1"]


def test_single_and_repeated_receipt_number_are_not_merged():
    frame=pd.DataFrame([
        {"pedido":"10","posicion_pedido":"20","parte_recepcion":"000123",
         "fecha_recepcion":date(2026,11,6),
         "cantidad_aprobada":Decimal("100.000000"),
         "cantidad_entregada":Decimal("120.500000")},
        {"pedido":"10","posicion_pedido":"20","parte_recepcion":"000123",
         "fecha_recepcion":date(2026,11,7),
         "cantidad_aprobada":Decimal("0.000000"),
         "cantidad_entregada":Decimal("10.250000")},
    ])
    view=receptions_table(frame)
    assert view.loc[view.Campo=="Recepción 1","Valor"].iloc[0]==(
        "000123 (06/11/2026, Re: —, Ap: 100, En: 120,5)")
    assert view.loc[view.Campo=="Recepción 2","Valor"].iloc[0]==(
        "000123 (07/11/2026, Re: —, Ap: 0, En: 10,25)")
    assert len(view.loc[view.Campo.str.startswith("Recepción")])==2
    assert len(receptions_table(frame.iloc[:1]).loc[
        lambda df: df.Campo.str.startswith("Recepción")])==1


def test_no_reception_yields_only_po_fields():
    frame=pd.DataFrame([{"pedido":"10","posicion_pedido":"20",
                         "parte_recepcion":None,"fecha_recepcion":None,
                         "cantidad_aprobada":None,"cantidad_entregada":None}])
    view=transpose_trace(frame,"Material sin recibir")
    assert view.iloc[0]["Valor"]=="Material sin recibir"
    assert not view.Campo.str.startswith("Recepción").any()
    assert receptions_table(frame).empty


def test_empty_trace_is_two_column_dataframe():
    result=transpose_trace(pd.DataFrame(columns=["pedido","parte_recepcion"]))
    assert list(result.columns)==["Campo","Valor"]
    assert result.empty



def test_vertical_supplementary_records_preserve_each_incident():
    from src.detail_view import vertical_records
    frame=pd.DataFrame([
        {"numero_incidencia":"INC-A","categoria":"Falta Documentación","resuelta":"No"},
        {"numero_incidencia":"INC-B","categoria":"Pendiente Aprobación","resuelta":"Sí"},
    ])
    view=vertical_records(frame,"INC",{"numero_incidencia":"Número INC"})
    assert list(view.columns)==["Campo","Valor"]
    assert view.loc[view.Campo=="Número INC","Valor"].tolist()==["INC-A","INC-B"]
    assert view.loc[view.Campo=="INC 1"].shape[0]==1
    assert view.loc[view.Campo=="INC 2"].shape[0]==1
    assert view.loc[view.Campo=="Categoria","Valor"].tolist()==["Falta Documentación","Pendiente Aprobación"]


def test_detail_state_uses_same_pastel_as_sc_general():
    from src.sc_row_styles import STATE_COLORS
    for state, color in STATE_COLORS.items():
        row=pd.Series({"Campo":"Estado SC","Valor":state})
        result=detail_row_style(row,date(2026,11,6))
        assert len(result)==2
        assert all(f"background-color: {color}" in x for x in result)


def test_planned_date_text_only_semantic_colors_on_boundaries():
    today=date(2026,11,6)
    cases=[
        ("05/11/2026", "#B91C1C"), # overdue
        ("06/11/2026", "#C2410C"), # today: <=7 days
        ("12/11/2026", "#C2410C"), # 6 days
        ("13/11/2026", "#C2410C"), # 7 days
        ("14/11/2026", "#A16207"), # 8 days
        ("20/11/2026", "#A16207"), # 14 days
        ("21/11/2026", "#15803D"), # 15 days
        ("22/12/2026", "#15803D"), # far away
    ]
    for value,color in cases:
        styles=detail_row_style(pd.Series({"Campo":"Fecha planificada","Valor":value}), today)
        assert len(styles)==2
        assert all(f"color: {color}" in x and "font-weight: bold" in x
                   and "background" not in x for x in styles)
    assert detail_row_style(pd.Series({"Campo":"Fecha planificada","Valor":"—"}),today)==["",""]
    assert detail_row_style(pd.Series({"Campo":"Proveedor","Valor":"05/11/2026"}),today)==["",""]


def test_optional_received_quantity_is_never_guessed_from_delivered():
    frame=pd.DataFrame([
        {"pedido":"X","posicion_pedido":"1","parte_recepcion":"RX",
         "fecha_recepcion":date(2026,11,6),"cantidad_entregada":Decimal("12"),
         "cantidad_aprobada":Decimal("8")},
        {"pedido":"X","posicion_pedido":"1","parte_recepcion":"RY",
         "fecha_recepcion":date(2026,11,7),"cantidad_recibida":Decimal("10,5".replace(",",".")),
         "cantidad_entregada":Decimal("12"),"cantidad_aprobada":Decimal("8")}
    ])
    result=receptions_table(frame)
    assert result.loc[result.Campo=="Recepción 1","Valor"].iloc[0] == (
        "RX (06/11/2026, Re: —, Ap: 8, En: 12)")
    assert result.loc[result.Campo=="Recepción 2","Valor"].iloc[0] == (
        "RY (07/11/2026, Re: 10,5, Ap: 8, En: 12)")


def test_receipts_group_by_po_and_retain_duplicate_numbers():
    frame=pd.DataFrame([
        {"pedido":"A","posicion_pedido":"10","parte_recepcion":"00001",
         "fecha_recepcion":date(2026,11,1),"cantidad_aprobada":Decimal("0"),
         "cantidad_entregada":Decimal("10")},
        {"pedido":"A","posicion_pedido":"10","parte_recepcion":"00001",
         "fecha_recepcion":date(2026,11,2),"cantidad_aprobada":Decimal("4"),
         "cantidad_entregada":Decimal("6")},
        {"pedido":"B","posicion_pedido":"20","parte_recepcion":"00002",
         "fecha_recepcion":date(2026,11,3),"cantidad_aprobada":Decimal("2"),
         "cantidad_entregada":Decimal("2")},
    ])
    view=receptions_table(frame)
    assert view.Campo.tolist()==["Pedido/pos","Recepción 1","Recepción 2","Pedido/pos","Recepción 1"]
    assert view.loc[view.Campo=="Pedido/pos","Valor"].tolist()==["A/10","B/20"]
    assert view.loc[view.Campo=="Recepción 2","Valor"].tolist()==["00001 (02/11/2026, Re: —, Ap: 4, En: 6)"]
