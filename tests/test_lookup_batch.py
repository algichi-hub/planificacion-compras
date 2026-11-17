"""Batch SC/PR input, verified ownership and UI query regression."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.lookup_batch import (parse_identifiers, ordered_sc_rows,
                              resolve_pr_batch, matched_pr_positions)
from src.pr_lookup import PR_LOOKUP_BATCH_SQL, PR_LOOKUP_SQL
from src.sc_overview import overview_display
from src.sc_csv_export import sc_overview_csv

APP=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")


def test_input_parsing_preserves_order_identifiers_and_removes_duplicates():
    assert parse_identifiers(" 000761452 ; 761488; 000761452 ")==("000761452","761488")
    assert parse_identifiers("768896")==("768896",)


@pytest.mark.parametrize("invalid",["", " ", "1;", ";1", "1;;2","1;a","-1","1,2",
                                    "1 ;  2 ; ","1"*31, ";".join(str(i) for i in range(51))])
def test_batch_rejects_invalid_search_without_query(invalid):
    with pytest.raises(ValueError):
        parse_identifiers(invalid)


def test_reordered_sc_positions_keep_numeric_order_within_each_sc():
    rows=pd.DataFrame([
        {"sc_no":"1","sc_pos":"10"},
        {"sc_no":"1","sc_pos":"20"},
        {"sc_no":"2","sc_pos":"10"},
        {"sc_no":"2","sc_pos":"20"},
    ])
    result=ordered_sc_rows(rows,("2","1"))
    assert list(zip(result.sc_no,result.sc_pos))==[
        ("2","10"),("2","20"),("1","10"),("1","20")]
    assert ordered_sc_rows(rows.iloc[:0],("2",)).empty


def linked(receipt_no, **kwargs):
    result=dict(receipt_no=receipt_no,company="210",sc_no="761488",
                sc_pos="130",po_no="762087",po_pos="13",
                allocation_status="verified",workflow_state="Completado")
    result.update(kwargs)
    return result


def test_verified_batch_preserves_pr_order_and_does_not_guess_ambiguous():
    owners,issues=resolve_pr_batch(("009","007","008","006"),[
        linked("007"),linked("008",po_pos="99"),
        linked("008",po_pos="100"),linked("009",sc_pos="10")
    ])
    assert [row["PR"] for row in owners]==["009","007"]
    assert len(issues)==2
    assert any("008" in issue and "varias" in issue for issue in issues)
    assert any("006" in issue and "no encontrado" in issue for issue in issues)


def test_same_sc_position_can_appear_for_multiple_distinct_prs():
    owners,issues=resolve_pr_batch(("2","1"),[linked("1"),linked("2")])
    assert not issues
    frame=pd.DataFrame([dict(company="210",sc_no="761488",sc_pos="130",
         project="P",article="A",description="A",po_positions="762087/13",
         pr_numbers="1, 2",planned_date=date(2026,11,1),
         requested_qty=Decimal("2.25"),ordered_qty=Decimal("2.25"),
         received_qty=Decimal("2.25"),approved_qty=Decimal("2.25"),
         workflow_state="Completado")])
    resolved=matched_pr_positions(owners,frame)
    assert resolved["PR"].tolist()==["2","1"]
    view=overview_display(resolved)
    view.insert(0,"PR",resolved["PR"].to_numpy())
    view=view.drop(columns="PRs")
    assert view.columns[0]=="PR" and "PRs" not in view.columns
    assert view["SC/Pos"].tolist()==["761488/130"]*2
    assert view.loc[0,"Sol"]==Decimal("2.25")
    exported=sc_overview_csv(view)
    assert exported.startswith(b"\xef\xbb\xbf")
    assert exported.decode("utf-8-sig").splitlines()[0].startswith("PR;Proyecto;")


def test_batch_sql_is_parameterized_and_keeps_strict_pr_ownership():
    assert "r.receipt_no=ANY(%s)" in PR_LOOKUP_BATCH_SQL
    assert "r.receipt_no=%s" in PR_LOOKUP_SQL
    assert "SELECT DISTINCT r.receipt_no,r.po_no" in PR_LOOKUP_BATCH_SQL
    assert "core.sc_po_links" in PR_LOOKUP_BATCH_SQL
    assert "PR_LOOKUP_BATCH_SQL" in APP


def test_ui_sc_queries_once_on_submit_and_pr_uses_two_batched_reads():
    sc=APP.split("with tab2:",1)[1].split("# Shared, read-only group catalogue.",1)[0]
    pr=APP.split("with tab6:",1)[1].split("# Lazy administration:",1)[0]
    assert 'with st.form("sc_lookup_form"):' in sc
    assert 'st.form_submit_button("Consultar SC")' in sc
    assert 's.sc_no=ANY(%s)' in sc
    assert sc.count("overview=query(")==2  # exclusive workflow/legacy branches
    assert "ordered_sc_rows(overview,sc_numbers)" in sc
    assert "sync_context(st.session_state,\"sc\",(sid,sc_numbers))" in sc
    assert 'on_select="rerun",selection_mode="single-row"' in sc
    assert 'with st.form("pr_lookup_form"):' in pr
    assert 'st.form_submit_button("Consultar PR")' in pr
    assert 'matches=query(PR_LOOKUP_BATCH_SQL,(sid,list(pr_numbers)))' in pr
    assert "positions=load_sc_collection_status(sid,numbers=list(sc_numbers))" in pr
    assert pr.count("query(")==1
    assert "matched_pr_positions(owners,positions)" in pr
    assert 'visible_overview.insert(0,"PR",resolved["PR"].to_numpy())' in pr
    assert 'visible_overview=visible_overview.drop(columns="PRs")' in pr
    assert 'selection_mode="single-row"' in pr
    assert 'render_sc_detail(line,sid,context="pr")' in pr
    assert "sc_export_button(" in pr
