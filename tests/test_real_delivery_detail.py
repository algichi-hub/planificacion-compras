"""Physical hand-deliveries in both selected SC detail views."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import pandas as pd
from src.detail_view import linked_receipt_numbers, real_delivery_table

ROOT=Path(__file__).resolve().parents[1]


def test_selected_position_shows_only_its_prs_and_preserves_partial_deliveries():
    # Two receipts for the selected position, one repeated on the trace.
    trace=pd.DataFrame([
        {"parte_recepcion":"000715","pedido":"100","posicion_pedido":"1"},
        {"parte_recepcion":"000715","pedido":"100","posicion_pedido":"1"},
        {"parte_recepcion":"000724","pedido":"100","posicion_pedido":"1"},
        {"parte_recepcion":None,"pedido":"100","posicion_pedido":"1"},
    ])
    ledger=pd.DataFrame([
        {"id":4,"pr_no":"000715","quantity":Decimal("3.500000"),
         "delivery_date":date(2026,11,7),"voided_at":None},
        {"id":2,"pr_no":"000715","quantity":Decimal("4"),
         "delivery_date":date(2026,11,6),"voided_at":None},
        {"id":6,"pr_no":"000715","quantity":Decimal("3.500000"),
         "delivery_date":date(2026,11,7),"voided_at":None},
        {"id":9,"pr_no":"000724","quantity":Decimal("0.250000"),
         "delivery_date":date(2026,11,8),"voided_at":None},
        {"id":5,"pr_no":"000715","quantity":Decimal("10"),
         "delivery_date":date(2026,11,6),"voided_at":datetime(2026,11,8,9)},
        {"id":7,"pr_no":"999999","quantity":Decimal("90"),
         "delivery_date":date(2026,11,8),"voided_at":None},
    ])
    assert linked_receipt_numbers(trace)==("000715","000724")
    result=real_delivery_table(trace,ledger)
    assert list(result.columns)==["PR","Qty","Fecha entrega","Recibido por NBI"]
    assert result.to_dict("records")==[
        {"PR":"000715","Qty":"4","Fecha entrega":"06/11/2026","Recibido por NBI":"—"},
        {"PR":"000715","Qty":"3,5","Fecha entrega":"07/11/2026","Recibido por NBI":"—"},
        {"PR":"000715","Qty":"3,5","Fecha entrega":"07/11/2026","Recibido por NBI":"—"},
        {"PR":"000724","Qty":"0,25","Fecha entrega":"08/11/2026","Recibido por NBI":"—"},
    ]


def test_no_receipt_or_no_matching_manual_entry_yields_empty_three_column_table():
    ledger=pd.DataFrame([{"id":1,"pr_no":"PR-A","quantity":Decimal("1"),
                          "delivery_date":date(2026,11,7)}])
    no_receipt=pd.DataFrame([{"parte_recepcion":None},
                             {"parte_recepcion":""},{"parte_recepcion":"   "}])
    for trace in (pd.DataFrame(),no_receipt):
        result=real_delivery_table(trace,ledger)
        assert result.empty
        assert result.columns.tolist()==["PR","Qty","Fecha entrega","Recibido por NBI"]
        assert linked_receipt_numbers(trace)==()
    different=pd.DataFrame([{"parte_recepcion":"00012"}])
    assert real_delivery_table(different,ledger).empty
    assert real_delivery_table(different,pd.DataFrame()).empty


def test_cross_position_prs_never_leak_into_selected_detail():
    ledger=pd.DataFrame([
        {"id":1,"pr_no":"001","quantity":Decimal("1"),"delivery_date":date(2026,11,6)},
        {"id":2,"pr_no":"002","quantity":Decimal("2"),"delivery_date":date(2026,11,7)},
    ])
    assert real_delivery_table(pd.DataFrame([{"parte_recepcion":"001"}]),ledger)["PR"].tolist()==["001"]
    assert real_delivery_table(pd.DataFrame([{"parte_recepcion":"002"}]),ledger)["PR"].tolist()==["002"]


def test_both_sc_views_share_real_delivery_section_without_download_or_write():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    shared=app.split("def render_sc_detail(line, sid, context):",1)[1].split("\nwith tab1:",1)[0]
    individual=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    grouped=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert 'render_sc_detail(line, sid, context="seguimiento")' in individual
    assert 'render_sc_detail(line, sid, context="group")' in grouped
    assert 'st.markdown("#### Entrega real")' in shared
    assert 'related_prs=linked_receipt_numbers(trace)' in shared
    assert 'hand_deliveries() if related_prs else pd.DataFrame()' in shared
    assert "real_delivery_table(" in shared
    assert 'st.dataframe(real_deliveries,use_container_width=True,hide_index=True' in shared
    assert 'key=f"{widget_prefix}_real_delivery"' in shared
    assert shared.index('st.markdown("#### Recepciones")') < shared.index('st.markdown("#### Entrega real")')
    assert shared.index('st.markdown("#### Entrega real")') < shared.index('st.markdown("#### REAC")')
    assert "write_hand_delivery(" not in shared
    assert "st.download_button(" not in shared


def test_delivery_cache_is_independent_and_invalidated_by_manage_pr():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    cache=app.split("def hand_deliveries():",1)[1].split("def _read_management",1)[0]
    pr=app.split("with tab5:",1)[1]
    assert "FROM planning.pr_hand_deliveries WHERE voided_at IS NULL" in cache
    assert "hand_deliveries.clear()" in pr
    assert "query.clear()" not in pr
    assert "UPDATE core." not in pr


def test_nbi_always_in_real_delivery_both_views_with_missing_legacy_values():
    trace=pd.DataFrame([{"parte_recepcion":"000715"}])
    ledger=pd.DataFrame([
        {"id":1,"pr_no":"000715","quantity":Decimal("2"),
         "delivery_date":date(2026,11,7),"received_by_nbi":"00042"},
        {"id":2,"pr_no":"000715","quantity":Decimal("3"),
         "delivery_date":date(2026,11,8),"received_by_nbi":None},
    ])
    displayed=real_delivery_table(trace,ledger)
    assert displayed.to_dict("records")==[
        {"PR":"000715","Qty":"2","Fecha entrega":"07/11/2026","Recibido por NBI":"00042"},
        {"PR":"000715","Qty":"3","Fecha entrega":"08/11/2026","Recibido por NBI":"—"},
    ]
    code=(ROOT/"app.py").read_text(encoding="utf-8")
    assert 'render_sc_detail(line, sid, context="seguimiento")' in code
    assert 'render_sc_detail(line, sid, context="group")' in code
    assert 'st.dataframe(real_deliveries,use_container_width=True,hide_index=True' in code
