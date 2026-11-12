import pandas as pd

from src.sc_row_styles import STATE_COLORS, sc_row_style


def test_each_requested_state_has_distinct_pastel_background():
    expected={
        "Completado":"#DCFCE7",
        "Pendiente pedido":"#FEE2E2",
        "Material sin recibir":"#FFEDD5",
        "Pendiente aprobación":"#FEF9C3",
        "Parcialmente aprobadas":"#DBEAFE",
        "SC anulada":"#F3F4F6",
    }
    assert STATE_COLORS==expected
    assert len(set(STATE_COLORS.values()))==6
    for state,color in expected.items():
        row=pd.Series({"sc_pos":"10","workflow_state":state,"requested_qty":2})
        values=sc_row_style(row)
        assert len(values)==len(row)
        assert all(f"background-color: {color}" in value for value in values)
        assert all("color: #111827" in value for value in values)


def test_unresolved_and_unknown_states_remain_uncolored():
    for state in ("Pendiente conciliación",None,""):
        row=pd.Series({"sc_pos":"20","workflow_state":state})
        assert sc_row_style(row)==["",""]


def test_pandas_styler_preserves_data_and_position_order():
    frame=pd.DataFrame([
        {"sc_pos":"10","workflow_state":"Completado"},
        {"sc_pos":"20","workflow_state":"Pendiente pedido"},
    ])
    styled=frame.style.apply(sc_row_style,axis=1)
    assert styled.data.equals(frame)
    ctx=styled._compute().ctx
    assert any("background-color" in str(v) for v in ctx[(0,0)])
    assert any("background-color" in str(v) for v in ctx[(1,1)])
