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

from src.normalize import repair_extra_fields

def test_repair_sc_description_delimiter():
    fields=[""]*53
    fields[9]="LLAVE DE VASO"
    fields[10]=" RESTO DE TEXTO"
    fields[12]="10,0000"
    fields[13]="23/02/24"
    repaired=repair_extra_fields(fields,52,"|","SC_FAS.csv")
    assert repaired is not None
    assert repaired[9]=="LLAVE DE VASO| RESTO DE TEXTO"

def test_repair_receipt_text_delimiter():
    fields=[""]*29
    fields[20]="3"
    fields[21]="3"
    fields[26]="Todo aprobado"
    fields[27]="observación"
    fields[28]=" adicional"
    repaired=repair_extra_fields(fields,28,";","Recepciones_Sevilla.csv")
    assert repaired and repaired[27]=="observación; adicional"

def test_reject_unsafe_receipt_repair():
    fields=[""]*29
    fields[20]="3"
    fields[21]="3"
    fields[26]="unknown status"
    assert repair_extra_fields(fields,28,";","Recepciones_Sevilla.csv") is None

def _allocation(sc_qty, po_qty, po_pos, article="A", po="P"):
    return dict(company="210",sc_no="1",sc_pos="10",article=article,
                requested=Decimal(str(sc_qty)),ordered=Decimal(str(po_qty)),
                po_no=po,po_pos=po_pos)

def test_split_variable_sc_quantities_sum_without_duplication():
    result=list(summarize_sc([_allocation(2,2,"17"),_allocation(1,1,"18")]))[0]
    assert result[2]==Decimal("3")
    assert result[3]=="verified_allocated_sum"

def test_split_equal_sc_quantities_sum_when_po_positions_distinct():
    result=list(summarize_sc([_allocation(2,2,"17"),_allocation(2,2,"18")]))[0]
    assert result[2]==Decimal("4")
    assert result[3]=="verified_allocated_sum"

def test_repeated_identical_po_position_is_not_double_counted():
    result=list(summarize_sc([_allocation(2,2,"17"),_allocation(2,2,"17")]))[0]
    assert result[2]==Decimal("2")
    assert result[3]=="verified"

def test_conflicting_article_does_not_auto_aggregate():
    result=list(summarize_sc([_allocation(2,2,"17"),_allocation(1,1,"18",article="B")]))[0]
    assert result[2] is None
    assert result[3]=="ambiguous_requested_qty"

def test_different_order_qty_does_not_auto_aggregate():
    result=list(summarize_sc([_allocation(2,3,"17"),_allocation(1,1,"18")]))[0]
    assert result[2] is None
    assert result[3]=="ambiguous_requested_qty"

def test_negative_allocation_does_not_auto_aggregate():
    result=list(summarize_sc([_allocation(-2,-2,"17"),_allocation(1,1,"18")]))[0]
    assert result[2] is None
    assert result[3]=="ambiguous_requested_qty"

def test_missing_po_identifier_does_not_auto_aggregate():
    result=list(summarize_sc([_allocation(2,2,"17",po="0"),_allocation(1,1,"18")]))[0]
    assert result[2] is None
    assert result[3]=="ambiguous_requested_qty"
