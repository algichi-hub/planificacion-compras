"""Operations log regression: append-only and independent from Neon."""
from pathlib import Path

import pytest

from src.import_history import history_path, log_event
from scripts.prepare_input_zip import InputArchiveError, prepare_inputs
from tests.test_prepare_input_zip import encrypted_zip, valid_files


def test_history_filename_and_append_only_lines(tmp_path):
    input_dir=tmp_path / "entrada"
    input_dir.mkdir()
    expected=tmp_path / "logs" / "planificacion-compras.log"
    assert history_path(input_dir)==expected
    log_event(input_dir,"ZIP_CHECK_START",archive="planificacion-compras.zip")
    log_event(input_dir,"ZIP_UNCHANGED",csv_count=4)
    lines=expected.read_text(encoding="utf-8").splitlines()
    assert len(lines)==2
    assert "ZIP_CHECK_START" in lines[0]
    assert "ZIP_UNCHANGED" in lines[1]
    assert "| " in lines[0]
    assert lines[0][:4].isdigit()


def test_zip_log_first_update_then_unchanged_no_secret(tmp_path):
    folder=tmp_path / "entrada"
    folder.mkdir()
    encrypted_zip(folder, valid_files(), "secret_for_test")
    assert prepare_inputs(folder,"secret_for_test") is True
    assert prepare_inputs(folder,"secret_for_test") is False
    lines=history_path(folder).read_text(encoding="utf-8").splitlines()
    assert len(lines)==4
    assert "ZIP_CHECK_START" in lines[0]
    assert "ZIP_UPDATED" in lines[1]
    assert "ZIP_CHECK_START" in lines[2]
    assert "ZIP_UNCHANGED" in lines[3]
    assert "secret_for_test" not in "\n".join(lines)
    assert "DATABASE_URL" not in "\n".join(lines)


def test_failed_preflight_appends_error_and_leaves_csv_untouched(tmp_path):
    folder=tmp_path / "entrada"
    folder.mkdir()
    with pytest.raises(InputArchiveError, match="Required ZIP missing"):
        prepare_inputs(folder, "secret_for_test")
    data=history_path(folder).read_text(encoding="utf-8")
    assert "ZIP_CHECK_START" in data
    assert "ZIP_CHECK_ERROR" in data
    assert "secret_for_test" not in data


def test_snapshot_cli_records_success_and_error_types_only():
    importer=(Path(__file__).resolve().parents[1]/"scripts"/"import_snapshot.py").read_text(encoding="utf-8")
    assert 'log_event(root, "SNAPSHOT_START"' in importer
    assert 'log_event(root, "SNAPSHOT_VALIDATED"' in importer
    assert 'log_event(args.input, "SNAPSHOT_FAILED"' in importer
    assert 'error_type=type(exc).__name__' in importer
    assert importer.index('log_event(root, "SNAPSHOT_VALIDATED"') > importer.index('classified_count=finalize_import(')
