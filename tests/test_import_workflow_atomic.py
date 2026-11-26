"""Regression checks for the importer workflow-finalization boundary."""
from pathlib import Path

import pytest

from scripts import import_snapshot


class FakeCursor:
    def __init__(self, n):
        self.n = n
        self.statements = []

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return (self.n,)


def test_finalize_calculates_before_transaction_can_commit(monkeypatch):
    cursor = FakeCursor(17)
    connection = object()
    calls = []

    def fake_classify(db, sid, commit=False):
        assert db is connection
        assert sid == 12
        assert commit is True
        assert cursor.statements[-1][0].startswith("UPDATE audit.snapshots")
        calls.append(sid)
        return {"Completado": 12, "Pendiente pedido": 5}

    monkeypatch.setattr(import_snapshot, "classify", fake_classify)
    assert import_snapshot.finalize_import(connection, cursor, 12) == 17
    assert calls == [12]


def test_finalize_rejects_empty_snapshot_before_publication(monkeypatch):
    cursor = FakeCursor(0)
    monkeypatch.setattr(import_snapshot, "classify", lambda *a, **kw: pytest.fail("unexpected classify"))
    with pytest.raises(ValueError, match="without SC positions"):
        import_snapshot.finalize_import(object(), cursor, 12)
    assert not any(sql.startswith("UPDATE") for sql, _ in cursor.statements)


def test_finalize_rejects_incomplete_derived_classification(monkeypatch):
    cursor = FakeCursor(17)
    monkeypatch.setattr(import_snapshot, "classify", lambda *a, **kw: {"Completado": 16})
    with pytest.raises(ValueError, match="cardinality mismatch"):
        import_snapshot.finalize_import(object(), cursor, 12)


def test_finalize_propagates_sql_failure_for_transaction_rollback(monkeypatch):
    cursor = FakeCursor(17)

    def fail(*_args, **_kwargs):
        raise RuntimeError("SQL classification failed")

    monkeypatch.setattr(import_snapshot, "classify", fail)
    with pytest.raises(RuntimeError, match="classification failed"):
        import_snapshot.finalize_import(object(), cursor, 12)


def test_import_finishes_workflow_inside_transaction():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "import_snapshot.py").read_text(encoding="utf-8")
    assert "with db.transaction():" in source
    assert source.index("with db.transaction():") < source.index("classified_count=finalize_import(db,cur,sid)")
    assert source.index("classified_count=finalize_import(db,cur,sid)") < source.index('print("Validated snapshot"')
    assert "from scripts.build_sc_workflow import classify" in source
