"""Regression tests for live-ERP descriptive enrichment of manual PR deliveries."""
from pathlib import Path

from src.pr_traceability import PR_RELATIONS_SQL, resolve_pr_relations


def relation(pr="769071",po="762087",pos="14",sc="761488",sc_pos="140",
             description="Condensador",project="19244F",supplier="Proveedor SL",
             status="verified",names=1,company="210"):
    return dict(pr_no=pr,po_no=po,po_pos=pos,company=company,
                sc_no=sc,sc_pos=sc_pos,allocation_status=status,
                description=description,project=project,
                supplier_name=supplier,name_count=names)


def test_verified_relation_shows_description_project_po_and_supplier():
    result=resolve_pr_relations(["769071"],[relation()])["769071"]
    assert result=={
        "Description":"Condensador","Proyecto":"19244F","Pedido/pos":"762087/14",
        "Proveedor":"Proveedor SL","Observaciones":"",
    }


def test_repeated_receipt_movement_does_not_create_false_ambiguity():
    # Multiple receipt movements for the SAME PO/SC are valid.
    row=relation()
    assert resolve_pr_relations(["769071"],[row,row])["769071"]["Observaciones"]==""


def test_missing_pr_is_safe_and_explained():
    result=resolve_pr_relations(["999999"],[])["999999"]
    assert result["Description"]=="—"
    assert "no encontrado" in result["Observaciones"]


def test_multi_po_wipes_all_descriptive_fields_and_explains_error():
    data=[relation(),relation(po="762088",pos="2")]
    record=resolve_pr_relations(["769071"],data)["769071"]
    assert record["Observaciones"]=="PR asociado a varias posiciones PO"
    assert all(record[key]=="—" for key in ("Description","Proyecto","Pedido/pos","Proveedor"))


def test_multi_sc_is_not_assigned_arbitrarily():
    data=[relation(),relation(sc="761489",sc_pos="20")]
    record=resolve_pr_relations(["769071"],data)["769071"]
    assert "varias posiciones SC" in record["Observaciones"]
    assert record["Pedido/pos"]=="—"


def test_missing_link_or_po_is_reported():
    r=relation()
    r.update(sc_no=None,sc_pos=None,allocation_status=None,description=None,project=None)
    assert "Sin vínculo" in resolve_pr_relations(["769071"],[r])["769071"]["Observaciones"]
    r["company"]=None
    assert "Pedido no encontrado" in resolve_pr_relations(["769071"],[r])["769071"]["Observaciones"]


def test_unverified_link_never_exposes_description():
    record=resolve_pr_relations(["769071"],[relation(status="ambiguous")])["769071"]
    assert "no verificada" in record["Observaciones"]
    assert record["Description"]=="—"


def test_missing_conflicting_supplier_name_reported():
    assert "sin nombre único" in resolve_pr_relations(
        ["769071"],[relation(names=2)])["769071"]["Observaciones"]
    assert "sin nombre único" in resolve_pr_relations(
        ["769071"],[relation(supplier=None,names=0)])["769071"]["Observaciones"]


def test_missing_description_or_project_reported():
    assert "Faltan datos" in resolve_pr_relations(
        ["769071"],[relation(description="")])["769071"]["Observaciones"]


def test_description_conflict_in_multiple_source_records_is_not_silenced():
    record=resolve_pr_relations(["769071"],[
        relation(description="Material A"),relation(description="Material B"),
    ])["769071"]
    assert record["Observaciones"]=="Datos descriptivos contradictorios"


def test_sql_only_reads_erp_tables_with_selected_snapshot_and_no_writes():
    assert PR_RELATIONS_SQL.count("%s")==2
    assert "planning.v_pr_delivery_relations" in PR_RELATIONS_SQL
    assert "WHERE snapshot_id=%s" in PR_RELATIONS_SQL
    assert "pr_no=ANY(%s)" in PR_RELATIONS_SQL
    assert "raw.source_rows" not in PR_RELATIONS_SQL
    for verb in ("INSERT INTO","UPDATE ","DELETE FROM","DROP TABLE"):
        assert verb not in PR_RELATIONS_SQL.upper()
    migration=(Path(__file__).resolve().parents[1]/"migrations"/"014_pr_lineage_backfill.sql").read_text(encoding="utf-8")
    assert "GRANT SELECT ON planning.v_pr_delivery_relations TO compras_reader" in migration
    assert "GRANT SELECT ON raw.source_rows" not in migration
    assert "Se rellenan campos faltantes desde snapshot #11" in migration
    assert "m.voided_at IS NULL" in migration


def test_app_uses_latest_validated_snapshot_and_keeps_manual_sort_and_void():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "current_erp_snapshot=latest_snapshot_id(available_snapshots())" in app
    assert "query(PR_RELATIONS_SQL,(current_erp_snapshot,list(pr_numbers)))" in app
    assert '["delivery_date","id"],ascending=[False,False]' in app
    assert "confirm_void_hand_delivery" in app
    assert 'hand_deliveries.clear()' in app
    # visible columns in required order; the delete X is an unlabeled first column.
    columns=app.split('{"field":"pr_no","headerName":"PR"',1)[-1]
    start=columns.rfind('{"field":"pr_no","headerName":"PR"')
    grid=app[app.rfind('{"field":"pr_no","headerName":"PR"'):]
    for name in ('"quantity"','"Description"','"Proyecto"','"Pedido/pos"',
                 '"Proveedor"','"delivery_date"','"received_by_nbi"','"Observaciones"'):
        assert name in grid
    assert grid.index('"Description"')<grid.index('"Proyecto"')<grid.index('"Pedido/pos"')
    assert grid.index('"Pedido/pos"')<grid.index('"Proveedor"')<grid.index('"delivery_date"')


def test_backfill_audit_comment_is_shown_with_dynamic_current_description():
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "erp_traceability_comment FROM planning.pr_hand_deliveries" in app
    assert 'visible["Observaciones"]=visible.apply(comments_for_row,axis=1)' in app
    assert 'visible=visible.drop(columns=["erp_traceability_comment"])' in app
