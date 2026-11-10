"""Group SC KPI counting and UI regression, with ERP-style Decimal quantities."""
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from src.group_statistics import COLUMNS, group_statistics

TODAY=date(2026,11,9)


def entry(sc, pos, status, ordered, received, requested, approved, plan=None,
          company="210"):
    return dict(
        sc_no=sc, company=company,sc_pos=pos,workflow_state=status,
        ordered_qty=Decimal(str(ordered)) if ordered is not None else None,
        received_qty=Decimal(str(received)) if received is not None else None,
        requested_qty=Decimal(str(requested)) if requested is not None else None,
        approved_qty=Decimal(str(approved)) if approved is not None else None,
        planned_date=plan,
    )


def items(*scs):
    return pd.DataFrame([
        {"sc_no":sc,"context_description":f"Descripción {sc}"} for sc in scs
    ])


def test_all_four_kpis_count_sc_positions_as_integers():
    source=pd.DataFrame([
        entry("761451","10","Pendiente pedido",0,0,10,0),
        entry("761451","20","Material sin recibir",10,0,10,0,date(2026,11,8)),
        entry("761451","30","Pendiente aprobación",10,10,10,0,date(2026,11,8)),
        entry("761451","40","Completado",10,10,10,10,date(2026,11,1)),
        entry("761451","50","SC anulada",0,0,0,0,date(2026,10,1)),
        entry("761451","60","Parcialmente aprobadas",10,5,10,3,date(2026,11,9)),
    ])
    result=group_statistics(items("761451"),source,TODAY)
    assert list(result.columns)==list(COLUMNS)
    assert result.iloc[0].to_dict()=={
        "Num SC":"761451","PO asociados":"—","Descripción contextual":"Descripción 761451",
        "Pend PO":"1/6","Pass Date":"1/6",
        "Full Received":"2/6","Full Approved":"1/6",
    }
    assert all(isinstance(result.iloc[0][col],str) for col in COLUMNS[3:])


def test_full_receipt_independent_of_approval_and_zero_qty():
    source=pd.DataFrame([
        entry("1","10","Pendiente aprobación",10,10,10,0),
        entry("1","20","Completado",10,10,10,10),
        entry("1","30","SC anulada",0,0,0,0),
        entry("1","40","Material sin recibir",0,0,1,0),
        entry("1","50","Pendiente pedido",None,None,1,0),
    ])
    result=group_statistics(items("1"),source,TODAY).iloc[0]
    assert result["Full Received"]=="2/5"
    assert result["Full Approved"]=="1/5"
    assert result["Pend PO"]=="1/5"


def test_pass_date_strictly_older_than_today_and_open_for_reception():
    source=pd.DataFrame([
        entry("1","1","Material sin recibir",10,0,10,0,date(2026,11,8)),
        entry("1","2","Material sin recibir",10,0,10,0,date(2026,11,9)),
        entry("1","3","Material sin recibir",10,0,10,0,date(2026,11,10)),
        entry("1","4","Pendiente aprobación",10,10,10,0,date(2026,11,8)),
        entry("1","5","SC anulada",10,0,10,0,date(2026,11,8)),
        entry("1","6","Pendiente pedido",0,0,10,0,date(2026,11,8)),
        entry("1","7","Material sin recibir",10,0,10,0),
        entry("1","8","Material sin recibir",10,3,10,0,date(2026,11,8)),
    ])
    result=group_statistics(items("1"),source,TODAY).iloc[0]
    assert result["Pass Date"]=="2/8"


def test_no_snapshot_reference_shows_dashes_instead_of_zero_div_zero():
    source=pd.DataFrame([
        entry("2","10","Pendiente pedido",0,0,5,0),
    ])
    result=group_statistics(items("1","2","3"),source,TODAY)
    assert result["Num SC"].tolist()==["1","2","3"]
    assert result["PO asociados"].tolist()==["—","—","—"]
    for i in (0,2):
        assert [result.iloc[i][col] for col in COLUMNS[3:]]==["—"]*4
    assert result.iloc[1]["Pend PO"]=="1/1"


def test_shared_group_uses_unique_company_and_position_grain():
    source=pd.DataFrame([
        entry("1","10","Material sin recibir",10,0,10,0,company="210"),
        entry("1","10","Material sin recibir",10,0,10,0,company="230"),
    ])
    assert group_statistics(items("1"),source,TODAY).iloc[0]["Pend PO"]=="0/2"
    repeated=pd.concat([source,source.iloc[[0]]],ignore_index=True)
    with pytest.raises(ValueError,match="duplicada"):
        group_statistics(items("1"),repeated,TODAY)


def test_preserve_sc_identifiers_and_description_and_no_double_count():
    group=items("000761488","761452")
    source=pd.DataFrame([
        entry("000761488","10","Pendiente pedido",0,0,5,0),
        entry("761452","20","Completado",4,4,4,4),
    ])
    result=group_statistics(group,source,TODAY)
    assert result["Num SC"].tolist()==["000761488","761452"]
    assert result["Descripción contextual"].tolist()==[
        "Descripción 000761488","Descripción 761452"
    ]
    assert result.iloc[0]["Pend PO"]=="1/1"


def test_cov_fallback_statuses_and_invalid_numbers():
    source=pd.DataFrame([
        {**entry("1","1","Pendiente pedido",0,0,2,0),
         "coverage_state":"no_approved_coverage"},
        {**entry("1","2","Completado",2,2,2,2),"coverage_state":"complete"},
    ]).drop(columns=["workflow_state"])
    result=group_statistics(items("1"),source,TODAY).iloc[0]
    assert result["Pend PO"]=="1/2"
    assert result["Full Approved"]=="1/2"
    for invalid in ("NaN","Infinity","abc"):
        s=pd.DataFrame([{**entry("1","1","Pendiente aprobación",0,10,10,0),
                         "ordered_qty":invalid}])
        assert group_statistics(items("1"),s,TODAY).iloc[0]["Full Received"]=="0/1"


def test_empty_and_incomplete_data_rejected_without_manufactured_counts():
    empty=pd.DataFrame(columns=["sc_no"])
    assert group_statistics(items(),empty,TODAY).empty
    assert group_statistics(items("1"),empty,TODAY).iloc[0]["Pass Date"]=="—"
    with pytest.raises(ValueError,match="incompletos"):
        group_statistics(items("1"),pd.DataFrame([{"sc_no":"1"}]),TODAY)
    with pytest.raises(ValueError,match="Fecha"):
        group_statistics(items("1"),pd.DataFrame(),None)


def test_group_frontend_has_stats_only_and_sc_timeline_unchanged():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    sc=app.split("with tab2:",1)[1].split("with tab3:",1)[0]
    assert "st.button(\"Resumen\"" in group
    assert 'stat_table=group_statistics(items,stats_saved[1],today_madrid)' in group
    assert group.index("if stats_ready:") < group.index("sc_event=st.dataframe(")
    assert group.index("sc_event=st.dataframe(") < group.index("event_group=st.dataframe(")
    assert "render_planning_timeline(" not in group
    assert "timeline_visible(" not in group
    assert "group_timeline" not in group
    assert 'render_planning_timeline(sc_timeline_source,madrid_today' in sc
    assert 'key="sc_timeline_toggle"' in sc
    assert 'render_sc_detail(line, sid, context="group")' in group
    assert 'render_sc_detail(line, sid, context="seguimiento")' in sc
    assert group.count("query(")==1
    assert 'st.session_state["group_statistics_result"]=(group_key,group_status)' in group
    assert "stats_saved[0]==group_key" in group


def test_pass_date_does_not_mark_operatively_completed_line_as_overdue():
    # Contradictory ERP totals require audit, but "completed" must not
    # become an open reception deadline simply because a source qty differs.
    source=pd.DataFrame([
        entry("1","10","Completado",10,5,10,10,date(2026,11,1)),
        entry("1","20","Material sin recibir",10,5,10,0,date(2026,11,1)),
    ])
    row=group_statistics(items("1"),source,TODAY).iloc[0]
    assert row["Pass Date"]=="1/2"
    assert row["Full Received"]=="0/2"
    assert row["Full Approved"]=="1/2"


def test_associated_po_deduplicates_across_positions_and_sorts():
    group=items("761451","761452","999999")
    source=pd.DataFrame([
        {**entry("761451","10","Completado",2,2,2,2),
         "po_positions":"762087/14, 761956/2"},
        {**entry("761451","20","Completado",3,3,3,3),
         "po_positions":"762087/15, 762087/18"},
        {**entry("761452","10","Pendiente pedido",0,0,1,0),
         "po_positions":None},
    ])
    result=group_statistics(group,source,TODAY)
    assert list(result.columns)==list(COLUMNS)
    assert result["PO asociados"].tolist()==["761956, 762087","—","—"]
    assert result["Pend PO"].tolist()==["0/2","1/1","—"]
    assert result["Descripción contextual"].tolist()==[
        "Descripción 761451","Descripción 761452","Descripción 999999"
    ]


def test_associated_po_ignores_cancelled_and_non_po_identifiers():
    source=pd.DataFrame([
        {**entry("1","10","SC anulada",0,0,0,0),
         "po_positions":"000000/0, 0/0, 762087/1"},
    ])
    row=group_statistics(items("1"),source,TODAY).iloc[0]
    assert row["PO asociados"]=="762087"
    assert row["Full Approved"]=="0/1"


def test_group_stats_po_is_second_column_without_extra_neon_query():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    group=app.split("with tab3:",1)[1].split("with tab4:",1)[0]
    assert '"PO asociados":st.column_config.TextColumn' in group
    assert "linked.po_positions,linked.planned_date" in group
    assert group.count("query(")==1
