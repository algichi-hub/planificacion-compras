from datetime import date
from decimal import Decimal

import pandas as pd

from src.detail_view import display_value, transpose_trace


def test_numeric_and_date_formatting():
    assert display_value(Decimal("1234.500000")) == "1234,500000"
    assert display_value(date(2026, 11, 6)) == "06/11/2026"
    assert display_value(None) == "—"
    assert display_value("00012") == "00012"


def test_vertical_trace_retains_all_fields_and_every_reception():
    original=pd.DataFrame([
        {"pedido":"761258","posicion_pedido":"1","parte_recepcion":"762514",
         "cantidad_pedida":Decimal("4"),"cantidad_entregada":Decimal("1"),
         "cantidad_aprobada":Decimal("0"),"estado_vinculo":"verified"},
        {"pedido":"761258","posicion_pedido":"1","parte_recepcion":"767054",
         "cantidad_pedida":Decimal("4"),"cantidad_entregada":Decimal("4"),
         "cantidad_aprobada":Decimal("0"),"estado_vinculo":"verified"},
        {"pedido":"761258","posicion_pedido":"2","parte_recepcion":None,
         "cantidad_pedida":Decimal("24"),"cantidad_entregada":None,
         "cantidad_aprobada":None,"estado_vinculo":"verified"},
    ])
    result=transpose_trace(original)
    assert list(result.columns)==["Campo","Valor"]
    assert len(result)==len(original)*(len(original.columns)+1)
    assert result.loc[result.Campo=="Movimiento 1","Valor"].iloc[0].endswith("762514")
    assert result.loc[result.Campo=="Movimiento 2","Valor"].iloc[0].endswith("767054")
    assert result.loc[result.Campo=="Movimiento 3","Valor"].iloc[0].endswith("—")
    assert result.loc[result.Campo=="Cantidad pedida","Valor"].tolist()==["4","4","24"]
    assert result.loc[result.Campo=="Cantidad entregada","Valor"].tolist()==["1","4","—"]


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
    assert view.loc[view.Campo=="Categoría","Valor"].tolist()==["Falta Documentación","Pendiente Aprobación"]
