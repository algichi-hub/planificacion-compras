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
