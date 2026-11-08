"""Regression for SC/PO handover states and exact PR attribution."""
from datetime import date
from decimal import Decimal
from urllib.parse import unquote
from pathlib import Path
import pandas as pd
from src.delivery_status import (
    attach_delivery_status,present_state,RECEIPT_COMPLETE,PARTIAL,TOTAL
)
from src.sc_overview import overview_display,DISPLAY_COLUMNS
from src.group_sc_view import group_overview
from src.quantity_format import format_sc_quantities
from src.status_icons import status_icon,STATUS_SYMBOLS

ROOT=Path(__file__).resolve().parents[1]


def base_rows():
    return pd.DataFrame([
        {"company":"210","sc_no":"00071","sc_pos":"10","project":"P",
         "article":"A","description":"Material","po_positions":"999/1",
         "planned_date":date(2026,11,9),
         "requested_qty":Decimal("10"),"ordered_qty":Decimal("10"),
         "received_qty":Decimal("10"),"approved_qty":Decimal("10"),
         "workflow_state":"Completado"},
        {"company":"210","sc_no":"00071","sc_pos":"20","project":"P",
         "article":"B","description":"Material 2","po_positions":"999/2",
         "planned_date":date(2026,11,9),
         "requested_qty":Decimal("10"),"ordered_qty":Decimal("10"),
         "received_qty":Decimal("4"),"approved_qty":Decimal("4"),
         "workflow_state":"Parcialmente aprobadas"},
    ])


def links():
    return pd.DataFrame([
        {"company":"210","sc_no":"00071","sc_pos":"10",
         "receipt_no":"000501","approved_qty":Decimal("6"),
         "owner_count":1,"pr_count":1},
        {"company":"210","sc_no":"00071","sc_pos":"10",
         "receipt_no":"000502","approved_qty":Decimal("4"),
         "owner_count":1,"pr_count":1},
        {"company":"210","sc_no":"00071","sc_pos":"20",
         "receipt_no":"000503","approved_qty":Decimal("4"),
         "owner_count":1,"pr_count":1},
    ])


def ledger(prs):
    return pd.DataFrame([
        {"pr_no":pr,"quantity":Decimal(qty),"delivery_date":date(2026,11,8)}
        for pr,qty in prs
    ])


def test_no_manual_data_keeps_dash_and_renames_erp_state():
    result=attach_delivery_status(base_rows(),links(),pd.DataFrame())
    visible=overview_display(result)
    assert list(visible.columns)==list(DISPLAY_COLUMNS)
    assert DISPLAY_COLUMNS[-2:]==("En","estado")
    assert visible["En"].tolist()==["—","—"]
    assert visible["estado"].tolist()==[RECEIPT_COMPLETE,"Parcialmente aprobadas"]
    assert "color: #15803D" not in unquote(visible.iloc[0][" "])


def test_partial_handover_across_two_prs_and_partial_same_pr():
    handed=ledger([("000501","2.5"),("000501","1.5"),("000502","1")])
    result=attach_delivery_status(base_rows(),links(),handed)
    assert result.iloc[0]["hand_qty"]==Decimal("5")
    assert result.iloc[0]["display_state"]==PARTIAL
    assert result.iloc[1]["hand_qty"] is None
    visible=overview_display(result)
    assert visible.iloc[1]["En"]=="—"
    assert visible.iloc[0]["En"]==Decimal("5")
    assert visible.iloc[0]["estado"]==PARTIAL
    assert "color" not in visible.iloc[0]["estado"]
    assert format_sc_quantities(visible.style)._display_funcs[(0,visible.columns.get_loc("En"))](Decimal("5"))=="5"


def test_total_only_when_all_approved_units_physically_handed_over():
    handed=ledger([("000501","6"),("000502","4"),("000503","2")])
    result=attach_delivery_status(base_rows(),links(),handed)
    assert result.iloc[0]["hand_qty"]==Decimal("10")
    assert result.iloc[0]["display_state"]==TOTAL
    assert result.iloc[1]["hand_qty"]==Decimal("2")
    # ERP line isn't reception-complete: do not override ERP status.
    assert result.iloc[1]["display_state"]=="Parcialmente aprobadas"


def test_overdelivery_or_per_pr_excess_never_becomes_total():
    for handed in (
        ledger([("000501","11")]),
        ledger([("000501","7"),("000502","3")]),
        ledger([("000501","6"),("000502","5")]),
    ):
        result=attach_delivery_status(base_rows(),links(),handed)
        assert result.iloc[0]["display_state"]==RECEIPT_COMPLETE
        assert result.iloc[0]["hand_qty"]>0


def test_shared_po_or_reused_pr_is_not_assigned_twice():
    source=base_rows()
    for field in ("owner_count","pr_count"):
        unsafe=links()
        unsafe.loc[unsafe.receipt_no=="000501",field]=2
        result=attach_delivery_status(source,unsafe,ledger([("000501","4"),("000502","2")]))
        assert result.iloc[0]["hand_qty"]==Decimal("2")
        assert result.iloc[0]["display_state"]==RECEIPT_COMPLETE


def test_inconsistent_or_duplicate_erp_receipts_do_not_mark_total():
    duplicated=pd.concat([links(),links().iloc[[0]]],ignore_index=True)
    result=attach_delivery_status(base_rows(),duplicated,ledger([("000501","6"),("000502","4")]))
    assert result.iloc[0]["display_state"]==RECEIPT_COMPLETE
    mismatch=links().copy()
    mismatch.loc[mismatch.receipt_no=="000502","approved_qty"]=Decimal("3")
    result=attach_delivery_status(base_rows(),mismatch,ledger([("000501","6"),("000502","4")]))
    assert result.iloc[0]["display_state"]==RECEIPT_COMPLETE


def test_voided_events_and_leading_zero_prs_and_other_sc_filtered():
    record=ledger([("000501","2"),("501","9"),("000502","4")])
    record["voided_at"]=[None,None,pd.Timestamp("2026-11-08")]
    result=attach_delivery_status(base_rows(),links(),record)
    assert result.iloc[0]["hand_qty"]==Decimal("2")
    assert result.iloc[0]["display_state"]==PARTIAL


def test_group_overview_inherits_en_and_states_without_changing_keys():
    source=attach_delivery_status(base_rows(),links(),ledger([("000501","6"),("000502","4")]))
    items=pd.DataFrame([{"sc_no":"00071"},{"sc_no":"00099"}])
    group=group_overview(items,source)
    assert group["SC/Pos"].tolist()==["00071/10","00071/20","00099"]
    assert group["En"].iloc[0]==Decimal("10")
    assert group["estado"].iloc[0]==TOTAL
    assert group["estado"].iloc[2]=="No encontrada"
    assert group["En"].iloc[2]=="—"


def test_status_glyphs_use_thumb_up_with_distinct_pink_and_purple():
    assert STATUS_SYMBOLS[PARTIAL]==("thumb_up","#DB2777")
    assert STATUS_SYMBOLS[TOTAL]==("thumb_up","#7C3AED")
    pink=unquote(status_icon(PARTIAL))
    purple=unquote(status_icon(TOTAL))
    assert 'fill="#DB2777"' in pink
    assert 'fill="#7C3AED"' in purple
    assert "thumb_up" in STATUS_SYMBOLS[PARTIAL][0]
    assert status_icon(RECEIPT_COMPLETE)==status_icon("Completado")


def test_app_reconciles_at_view_time_and_does_not_write_erp():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert "def enrich_delivery_status(source, snapshot_id):" in app
    assert "l.sc_no=ANY(%s)" in app
    assert "x.receipt_no=r.receipt_no" in app
    assert "x.po_no=l.po_no AND x.po_pos=l.po_pos" in app
    assert "overview=enrich_delivery_status(overview,sid)" in app
    assert "group_source=enrich_delivery_status(stored[3],sid)" in app
    assert "bulk_view=overview_display(group_source)" in app
    assert "format_sc_quantities(visible_overview.style)" in app
    assert "format_sc_quantities(bulk_view.style)" in app
    assert '"En"' in app
    assert 'st.session_state["bulk_result"]=(sid,group_id,grouped,group_source)' in app
    assert "UPDATE core." not in app
    assert "query.clear()" not in app
