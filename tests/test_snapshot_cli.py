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
