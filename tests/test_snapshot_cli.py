"""Safety tests for snapshot management and importer progress."""
import os
import pytest

from scripts.manage_snapshots import validate_request, build_parser, CHILD_TABLES, TABLES
from scripts.import_snapshot import count_data_lines

def test_progress_counts_lines_with_terminal_newline(tmp_path):
    path=tmp_path/"test.csv"
    path.write_bytes(b"header\na\nb\n")
    assert count_data_lines(path)==2

def test_progress_counts_lines_without_terminal_newline(tmp_path):
    path=tmp_path/"test.csv"
    path.write_bytes(b"header\na\nb")
    assert count_data_lines(path)==2

def test_progress_counts_empty_file(tmp_path):
    path=tmp_path/"test.csv"
    path.write_bytes(b"")
    assert count_data_lines(path)==0

def test_delete_is_dry_run_without_matching_confirmation():
    assert validate_request(2,None,"validated") is False
    assert validate_request(2,2,"validated") is True

@pytest.mark.parametrize("state",["active",None,"unknown"])
def test_delete_rejects_active_missing_or_unknown(state):
    with pytest.raises(ValueError):
        validate_request(2,2,state)

@pytest.mark.parametrize("snapshot_id,confirm",[(0,0),(-1,-1),(2,1)])
def test_delete_rejects_invalid_ids(snapshot_id,confirm):
    with pytest.raises(ValueError):
        validate_request(snapshot_id,confirm,"validated")

def test_delete_requires_explicit_target_in_cli():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--confirm","2"])
    assert build_parser().parse_args(["--delete","2"]).confirm is None
    args=build_parser().parse_args(["--delete","2","--confirm","2"])
    assert args.delete==args.confirm==2

def test_deletion_order_contains_dependencies_before_parents():
    assert CHILD_TABLES.index("core.sc_po_links")<CHILD_TABLES.index("core.sc_lines")
    assert CHILD_TABLES.index("core.sc_po_links")<CHILD_TABLES.index("core.po_lines")
    assert CHILD_TABLES.index("core.reac_refs")<CHILD_TABLES.index("core.sc_lines")
    assert TABLES[-1]=="audit.snapshots"

def test_reconciliation_progress_has_eight_milestones():
    import ast
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/"scripts"/"import_snapshot.py"
    tree=ast.parse(path.read_text(encoding="utf-8"))
    calls=[node for node in ast.walk(tree)
           if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
           and node.func.attr=="update"
           and isinstance(node.func.value,ast.Name)
           and node.func.value.id=="progress"]
    assert len(calls)==8
    assert all(len(call.args)==1 and isinstance(call.args[0],ast.Constant)
               and call.args[0].value==1 for call in calls)

def test_import_does_not_run_coverage_view_inside_transaction():
    import inspect
    from scripts.import_snapshot import run_import
    code=inspect.getsource(run_import)
    assert "FROM planning.v_sc_coverage" not in code
    assert "audit.import_issues" in code

def test_coverage_audit_has_bounded_timeout_and_is_read_only():
    import inspect
    from scripts.audit_snapshot import audit
    code=inspect.getsource(audit)
    assert "statement_timeout" in code
    assert "INSERT INTO" not in code
    assert "DELETE FROM" not in code
    assert "UPDATE audit." not in code

def test_sc_workflow_rules_and_snapshot_scope():
    from scripts.build_sc_workflow import QUERY, PARAMETERS
    assert PARAMETERS==6
    assert QUERY.count("%s")==PARAMETERS
    assert "WHEN requested_qty=0 THEN 'SC anulada'" in QUERY
    assert QUERY.index("WHEN requested_qty=0 THEN 'SC anulada'") < QUERY.index("WHEN linked_po=0 OR (NOT any_po_approved AND NOT (received_qty>0 OR approved_qty>0)) THEN 'Pendiente pedido'")
    assert "AND ordered_qty>0 THEN 'SC anulada con PO positivo'" in QUERY
    assert "FROM core.sc_lines s WHERE s.snapshot_id=%s" in QUERY
    assert "FROM core.receipts WHERE snapshot_id=%s" in QUERY
    assert "FROM core.incidents WHERE snapshot_id=%s" in QUERY

def test_sc_workflow_is_dry_run_by_default():
    from pathlib import Path
    code=(Path(__file__).resolve().parents[1]/"scripts"/"build_sc_workflow.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--commit",action="store_true"' in code
    assert "conn.rollback()" in code
    assert "ON CONFLICT (snapshot_id,company,sc_no,sc_pos)" in code
    assert "SELECT {cols} FROM ({QUERY}) AS classified WHERE true" in code

def test_sc_workflow_schema_is_additive():
    from pathlib import Path
    sql=(Path(__file__).resolve().parents[1]/"migrations"/"007_sc_workflow_status.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS planning.sc_workflow_status" in sql
    assert "PRIMARY KEY(snapshot_id,company,sc_no,sc_pos)" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "DELETE FROM" not in sql.upper()

def test_inc_reac_are_supplementary_not_workflow_states():
    from scripts.build_sc_workflow import QUERY
    assert "true AS has_incident" in QUERY
    assert "WHEN received_qty>0 THEN 'Pendiente aprobación'" in QUERY
    assert "WHEN approved_qty>0 THEN 'Parcialmente aprobadas'" in QUERY
    assert "WHEN approved_qty>=requested_qty THEN 'Completado'" in QUERY
    assert "WHEN has_reac OR has_incident THEN 'Pendiente conciliación'" not in QUERY
    assert "'REAC (provisional)'" not in QUERY
    assert "'Recibido con incidencia (provisional)'" not in QUERY


def test_pr_approval_dates_in_deleted_children_and_dry_run_counts():
    from scripts.manage_snapshots import CHILD_TABLES, TABLES
    assert "core.pr_approval_dates" in CHILD_TABLES
    assert CHILD_TABLES.index("core.pr_approval_dates") < len(CHILD_TABLES)
    assert TABLES[-1] == "audit.snapshots"


def test_fk_dependency_check_rejects_new_unlisted_referencing_table():
    from scripts.manage_snapshots import validate_snapshot_dependencies
    class Cursor:
        def execute(self, sql):
            assert "pg_constraint" in sql
            assert "audit.snapshots" in sql
        def fetchall(self):
            return [("core.pr_approval_dates",), ("audit.import_issues",),
                    ("core.some_new_fk_table",)]
    with pytest.raises(ValueError, match="core.some_new_fk_table"):
        validate_snapshot_dependencies(Cursor())


def test_fk_dependency_check_accepts_known_tables():
    from scripts.manage_snapshots import validate_snapshot_dependencies, CHILD_TABLES
    class Cursor:
        def execute(self, sql):
            assert "pg_constraint" in sql
        def fetchall(self):
            return [(table,) for table in CHILD_TABLES]
    validate_snapshot_dependencies(Cursor())


def test_dependency_guard_runs_before_delete_even_for_confirmed_request():
    import inspect
    from scripts.manage_snapshots import delete_snapshot
    source=inspect.getsource(delete_snapshot)
    assert source.index("validate_snapshot_dependencies(cur)") < source.index(
        "counts = count_snapshot_rows(cur, snapshot_id)"
    )
    assert source.index("validate_snapshot_dependencies(cur)") < source.index(
        'INSERT INTO audit.snapshot_deletions'
    )
