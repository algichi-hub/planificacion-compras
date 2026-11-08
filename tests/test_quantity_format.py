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
        "Sol":[Decimal("4.000000"),Decimal("2.250000")],
        "Ped":[Decimal("0.000000"),Decimal("4.123456")],
        "Rec":[Decimal("0.000001"),Decimal("123456.000000")],
        "Apr":[None,Decimal("1.000000")],
        "Ent":[None,Decimal("0.250000")],
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
        (0,"Sol"):"4",
        (1,"Sol"):"2,25",
        (0,"Rec"):"0,000001",
        (1,"Rec"):"123456",
        (1,"Ped"):"4,123456",
        (0,"Apr"):"—",
        (0,"Ent"):"—",
        (1,"Ent"):"0,25",
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
        "000042 (06/11/2026, Re: 12,5, Ap: 10)")
    assert receipt.loc[0,"cantidad_entregada"]==Decimal("12.500000")


def test_detail_quantity_fract_preserved():
    trace=pd.DataFrame([{
        "pedido":"01","posicion_pedido":"1",
        "cantidad_pedida":Decimal("123.000010"),
        "parte_recepcion":None
    }])
    view=transpose_trace(trace,"Material sin recibir")
    assert view.loc[view.Campo=="Cantidad pedida","Valor"].iloc[0]=="123,00001"


def test_overview_auto_sizes_only_quantity_columns_without_overriding_number_format():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert 'name: st.column_config.Column(width=None)' in app
    assert 'for name in ("Sol", "Ped", "Rec", "Apr")' in app
    assert '"Ent": st.column_config.Column(width=None, alignment="right")' in app
    assert 'format_sc_quantities(visible_overview.style)' in app
    assert 'st.column_config.NumberColumn(width="small")' not in app
    # No explicit widths for the other seven columns.
    assert app.count('st.column_config.Column(width=None)') == 1
