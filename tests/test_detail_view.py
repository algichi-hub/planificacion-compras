from datetime import date
from decimal import Decimal

import pandas as pd

from src.detail_view import display_value, transpose_trace


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
    assert view.loc[view.Campo=="Pedido","Valor"].tolist()==["761258","761258"]
    assert view.loc[view.Campo=="Cantidad pedida","Valor"].tolist()==["4,000000","24,000000"]
    assert view.loc[view.Campo=="Recepción 1","Valor"].tolist()==[
        "762514 (01/10/2026, 0, 1)"]
    assert view.loc[view.Campo=="Recepción 2","Valor"].tolist()==[
        "767054 (05/10/2026, 0, 4)"]
    assert "Movimiento 1" not in view.Campo.tolist()
    assert "Estado recepción" not in view.Campo.tolist()
    assert "Estado vínculo" not in view.Campo.tolist()
    assert "Parte de recepción" not in view.Campo.tolist()


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
    view=transpose_trace(frame,"Parcialmente aprobadas")
    assert view.loc[view.Campo=="Recepción 1","Valor"].iloc[0]==(
        "000123 (06/11/2026, 100, 120,5)")
    assert view.loc[view.Campo=="Recepción 2","Valor"].iloc[0]==(
        "000123 (07/11/2026, 0, 10,25)")
    assert len(view.loc[view.Campo.str.startswith("Recepción")])==2
    assert len(transpose_trace(frame.iloc[:1],"Completado").loc[
        lambda df: df.Campo.str.startswith("Recepción")])==1


def test_no_reception_yields_only_po_fields():
    frame=pd.DataFrame([{"pedido":"10","posicion_pedido":"20",
                         "parte_recepcion":None,"fecha_recepcion":None,
                         "cantidad_aprobada":None,"cantidad_entregada":None}])
    view=transpose_trace(frame,"Material sin recibir")
    assert view.iloc[0]["Valor"]=="Material sin recibir"
    assert not view.Campo.str.startswith("Recepción").any()


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
