from decimal import Decimal
import math

import pandas as pd
import pytest

from src.quantity_format import SC_QUANTITY_COLUMNS, format_quantity, format_sc_quantities
from src.detail_view import display_value, receptions_table, transpose_trace


@pytest.mark.parametrize("original,expected", [
    (Decimal("0.000000"),"0"),
    (Decimal("-0.000000"),"0"),
    (Decimal("4.000000"),"4"),
    (Decimal("4.250000"),"4,25"),
    (Decimal("0.000001"),"0,000001"),
    (Decimal("1000000.000000"),"1000000"),
    (Decimal("-17.500000"),"-17,5"),
    (Decimal("1234.123450"),"1234,12345"),
    (Decimal("1E+3"),"1000"),
    (0,"0"),
    (7,"7"),
    (3.5,"3,5"),
    (None,"—"),
    (float("nan"),"—"),
])
def test_exact_compact_spanish_display(original, expected):
    assert format_quantity(original)==expected


def test_styler_format_preserves_source_precision_dtype_and_order():
    frame=pd.DataFrame({
        "solicitado":[Decimal("4.000000"),Decimal("2.250000")],
        "pedido":[Decimal("0.000000"),Decimal("4.123456")],
        "recibido":[Decimal("0.000001"),Decimal("123456.000000")],
        "aprobado":[None,Decimal("1.000000")],
        "estado":["Material sin recibir","Completado"],
    },index=[5,9])
    original=frame.copy(deep=True)
    styled=format_sc_quantities(frame.style)
    assert styled.data.equals(original)
    assert list(styled.data.index)==[5,9]
    assert all(styled.data[col].equals(original[col]) for col in SC_QUANTITY_COLUMNS)
    # These are exactly the display functions used by pandas Styler.
    column_position={col: frame.columns.get_loc(col) for col in SC_QUANTITY_COLUMNS}
    expected={
        (0,"solicitado"):"4",
        (1,"solicitado"):"2,25",
        (0,"recibido"):"0,000001",
        (1,"recibido"):"123456",
        (1,"pedido"):"4,123456",
        (0,"aprobado"):"—",
    }
    for (row,column),formatted in expected.items():
        assert styled._display_funcs[(row,column_position[column])](
            frame.iloc[row][column])==formatted
    assert frame.equals(original)


def test_display_is_compact_without_mutating_receipt_numbers():
    receipt=pd.DataFrame([{
        "pedido":"000123","posicion_pedido":"07",
        "parte_recepcion":"000042",
        "fecha_recepcion":pd.Timestamp("2026-11-06"),
        "cantidad_entregada":Decimal("12.500000"),
        "cantidad_aprobada":Decimal("10.000000"),
    }])
    view=receptions_table(receipt)
    assert view.loc[view.Campo=="Pedido/pos","Valor"].tolist()==["000123/07"]
    assert view.loc[view.Campo=="Recepción 1","Valor"].iloc[0]==(
        "000042 (06/11/2026, Re: 12,5, Ap: 10, En: 12,5)")
    assert receipt.loc[0,"cantidad_entregada"]==Decimal("12.500000")


def test_detail_quantity_fract_preserved():
    trace=pd.DataFrame([{
        "pedido":"01","posicion_pedido":"1",
        "cantidad_pedida":Decimal("123.000010"),
        "parte_recepcion":None
    }])
    view=transpose_trace(trace,"Material sin recibir")
    assert view.loc[view.Campo=="Cantidad pedida","Valor"].iloc[0]=="123,00001"
