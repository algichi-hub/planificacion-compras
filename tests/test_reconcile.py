from decimal import Decimal
from src.normalize import decimal_es,date_es
from src.reconcile import summarize_sc

def test_spanish_decimal():
    assert decimal_es("  12,5000") == Decimal("12.5000")
    assert date_es("03/11/26").isoformat()=="2026-11-03"

def test_ambiguous_sc_quantity_not_summed():
    rows=[
        dict(company="210",sc_no="1",sc_pos="10",requested=Decimal("50")),
        dict(company="210",sc_no="1",sc_pos="10",requested=Decimal("70")),
    ]
    result=list(summarize_sc(rows))
    assert result[0][2] is None
    assert result[0][3]=="ambiguous_requested_qty"
