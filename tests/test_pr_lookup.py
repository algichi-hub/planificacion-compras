"""Exact PR lookup regression: no guessing, no initial Neon read."""
from pathlib import Path

from src.pr_lookup import PR_LOOKUP_SQL, resolve_pr

ROOT=Path(__file__).resolve().parents[1]


def relation(**changes):
    row={"po_no":"762087","po_pos":"13","company":"210",
         "sc_no":"761488","sc_pos":"130",
         "allocation_status":"verified","workflow_state":"Completado"}
    row.update(changes)
    return row


def test_unique_verified_pr_returns_full_sc_context():
    row=relation()
    found,issue=resolve_pr([row])
    assert found==row and issue is None


def test_same_verified_path_multiple_erp_receipt_rows_not_ambiguous():
    row=relation()
    found,issue=resolve_pr([row,row.copy()])
    assert found==row and issue is None


def test_missing_pr_never_falls_back_to_other_snapshots():
    row,issue=resolve_pr([])
    assert row is None and "no encontrado" in issue


def test_multiple_po_or_sc_owners_are_ambiguous():
    for other in (relation(po_pos="14"),relation(sc_pos="140"),
                  relation(company="211")):
        row,issue=resolve_pr([relation(),other])
        assert row is None and "varias asociaciones" in issue


def test_nonverified_or_missing_sc_never_exposes_guessed_detail():
    for other in (relation(allocation_status="uncertain"),
                  relation(company=None,sc_no=None,sc_pos=None)):
        row,issue=resolve_pr([other])
        assert row is None and "verificado" in issue
    row,issue=resolve_pr([relation(),relation(allocation_status="uncertain")])
    assert row is None and "verificado" in issue


def test_sql_exact_parameterized_and_includes_non_manual_pr():
    assert "r.snapshot_id=%s AND r.receipt_no=%s" in PR_LOOKUP_SQL
    assert "core.receipts" in PR_LOOKUP_SQL
    assert "core.sc_po_links" in PR_LOOKUP_SQL
    assert "pr_hand_deliveries" not in PR_LOOKUP_SQL
    assert "v_pr_delivery_relations" not in PR_LOOKUP_SQL


def test_pr_tab_form_is_strictly_lazy_and_detail_is_shared():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    pr=app.split("with tab6:",1)[1]
    assert 'with st.form("pr_lookup_form"):' in pr
    assert 'st.form_submit_button("Consultar PR")' in pr
    assert pr.index('if selected and selected[0]==sid:') < pr.index(
        'matches=query(PR_LOOKUP_SQL,(sid,pr_number))')
    assert pr.index('if selected and selected[0]==sid:') < pr.index(
        'render_sc_detail(line,sid,context="pr")')
    assert 'st.session_state["pr_lookup_selected"]' in pr
    assert 'pr_input.strip()' in pr
    assert 'pr_number.isascii() and pr_number.isdigit()' in pr
    assert 'render_sc_detail(line,sid,context="pr")' in pr
    assert app.count("def render_sc_detail(")==1
    assert 'tab1,tab2,tab6,tab3,tab4,tab5,tab7=st.tabs(' in app
