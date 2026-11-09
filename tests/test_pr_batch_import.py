"""Bulk hand-delivery parser, preview warnings and transactional guardrails."""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from src.pr_batch_import import (
    parse_pr_batch, batch_digest, batch_warnings, insert_pr_batch, MAX_ROWS,
)

TODAY = date(2026, 11, 9)
EXAMPLE = (
    "769071;3;06/11/2026;8579;"
    "769072;20;06/11/2026;8579;"
    "769073;10;06/11/2026;8579;"
    "769074;10;06/11/2026;8579;"
    "769076;20;06/11/2026;8579;"
    "769077;20;06/11/2026;8579;"
    "769078;10;06/11/2026;8579"
)


def test_example_seven_rows_preserves_order_and_exact_values():
    rows = parse_pr_batch(EXAMPLE, today=TODAY)
    assert len(rows) == 7
    assert rows[0] == ("769071", Decimal("3"), date(2026, 11, 6), "8579")
    assert rows[-1] == ("769078", Decimal("10"), date(2026, 11, 6), "8579")


def test_numeric_identifiers_are_strings_and_decimal_comma_is_supported():
    rows = parse_pr_batch("000001;0,75;09/11/2026;0008579;", today=TODAY)
    assert rows == (("000001", Decimal("0.75"), TODAY, "0008579"),)
    assert batch_digest(rows) == batch_digest(parse_pr_batch(
        "000001;0.750;09/11/2026;0008579", today=TODAY))


@pytest.mark.parametrize("payload, error", [
    ("", "Pega"),
    ("111;2;06/11/2026", "cuatro campos"),
    ("111;2;;8579", "fecha"),
    ("111;2;31/02/2026;8579", "day is out of range"),
    ("111;-2;06/11/2026;8579", "Qty"),
    ("111;0;06/11/2026;8579", "Qty"),
    ("111;2;10/11/2026;8579", "futura"),
    ("111;2;2026-11-06;8579", "DD/MM/AAAA"),
    ("111;2;06/11/2026;abc", "NBI"),
    ("abc;2;06/11/2026;8579", "SC"),
    ("111;2;06/11/2026;8579;;", "cuatro campos"),
])
def test_rejects_bad_payload_without_partial_parse(payload, error):
    with pytest.raises(ValueError, match=error):
        parse_pr_batch(payload, today=TODAY)


def test_max_limit_and_oversized_input():
    assert len(parse_pr_batch("111;1;06/11/2026;1;" * MAX_ROWS, today=TODAY)) == 200
    with pytest.raises(ValueError, match="Máximo"):
        parse_pr_batch("111;1;06/11/2026;1;" * (MAX_ROWS + 1), today=TODAY)
    with pytest.raises(ValueError, match="demasiado largo"):
        parse_pr_batch("a" * 32001, today=TODAY)


def test_preview_warns_duplicates_and_missing_erp():
    rows = parse_pr_batch("111;3;06/11/2026;8579;111;3;06/11/2026;8579", today=TODAY)
    existing = [{"pr_no": "111", "quantity": Decimal("3"),
                 "delivery_date": date(2026, 11, 6), "received_by_nbi": "8579"}]
    warnings = batch_warnings(rows, existing, {})
    assert any("2 filas idénticas" in w for w in warnings)
    assert any("entrega activa idéntica" in w for w in warnings)
    assert any("no encontrado" in w for w in warnings)


def test_voids_do_not_count_towards_totals():
    rows = parse_pr_batch("111;2;06/11/2026;8579", today=TODAY)
    voided = [{"pr_no": "111", "quantity": Decimal("99"),
               "delivery_date": date(2026, 11, 6), "received_by_nbi": "8579",
               "voided_at": TODAY}]
    assert batch_warnings(rows, voided,
                          {"111": {"n": 1, "approved_qty": Decimal("3")}}) == []


def test_no_privilege_no_connection(monkeypatch):
    from src import pr_batch_import as mod
    monkeypatch.setattr(mod.psycopg, "connect",
                        lambda *a, **kw: pytest.fail("connected without permission"))
    rows = parse_pr_batch("111;2;06/11/2026;8579", today=TODAY)
    with pytest.raises(PermissionError):
        insert_pr_batch("fake", {}, "allowed@example.com", rows,
                        expected_digest=batch_digest(rows), today=TODAY)


def test_previously_reviewed_rows_cannot_be_swapped(monkeypatch):
    from src import pr_batch_import as mod
    monkeypatch.setattr(mod.psycopg, "connect",
                        lambda *a, **kw: pytest.fail("connected with stale preview"))
    user = {"is_logged_in": True, "email_verified": True, "email": "allowed@example.com"}
    rows = parse_pr_batch("111;2;06/11/2026;8579", today=TODAY)
    with pytest.raises(ValueError, match="cambiado"):
        insert_pr_batch("fake", user, "allowed@example.com", rows,
                        expected_digest="0" * 64, today=TODAY)


def test_app_has_preview_confirm_and_preserves_existing_grid_order():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    assert "parse_pr_batch(bulk_text,today=today)" in app
    assert 'st.button("Confirmar e importar lote"' in app
    assert 'ledger.sort_values(' in app
    assert '["delivery_date","id"],ascending=[False,False]' in app
    assert 'confirm_void_hand_delivery(' in app
    assert 'hand_deliveries.clear()' in app


def test_migration_provides_idempotent_batch_identity():
    from pathlib import Path
    sql=(Path(__file__).resolve().parents[1]/"migrations"/"013_pr_hand_delivery_batches.sql").read_text(encoding="utf-8")
    assert "digest TEXT NOT NULL UNIQUE" in sql
    assert "ADD COLUMN IF NOT EXISTS batch_id" in sql
    assert "GRANT SELECT, INSERT" in sql
    assert "DROP TABLE" not in sql
