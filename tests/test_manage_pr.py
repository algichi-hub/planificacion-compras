"""Manage PR functional and authorization regression; never uses a live database."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import pytest

from src.pr_hand_deliveries import (
    normalize_pr,normalize_quantity,normalize_delivery_date,
    duplicate_warning,manual_total,write_hand_delivery,
)

ROOT=Path(__file__).resolve().parents[1]
ADMIN={"is_logged_in":True,"email_verified":True,"email":"Admin@Example.com"}
TODAY=date(2026,11,8)


@pytest.mark.parametrize("raw,expected",[
    ("001234","001234"),("12","12"),(" 0008 ","0008")])
def test_pr_text_preserves_leading_zeros(raw,expected):
    assert normalize_pr(raw)==expected


@pytest.mark.parametrize("raw,expected",[
    ("1","1"),("1,25","1.25"),("0,000001","0.000001"),
    ("0001,200000","1.200000"),("123.456","123.456")])
def test_quantity_decimal_comma_no_grouping(raw,expected):
    assert normalize_quantity(raw)==Decimal(expected)


@pytest.mark.parametrize("bad",["","0","-1","1,0000001","1.2.3","1,000.00",
                                 "1 000","1e5","NaN","Infinity","a",True,
                                 "999999999999999,00"])
def test_invalid_quantity_rejected(bad):
    with pytest.raises(ValueError):
        normalize_quantity(bad)


def test_date_validation_no_future_and_iso_support():
    assert normalize_delivery_date("2026-11-06",today=TODAY)==date(2026,11,6)
    assert normalize_delivery_date(datetime(2026,11,7,12),today=TODAY)==date(2026,11,7)
    with pytest.raises(ValueError):
        normalize_delivery_date("2026-11-09",today=TODAY)
    with pytest.raises(ValueError):
        normalize_delivery_date("not-a-date",today=TODAY)


def test_partial_same_pr_multiple_dates_and_same_day_allowed():
    rows=[
        {"pr_no":"00715","quantity":Decimal("4"),"delivery_date":date(2026,11,6)},
        {"pr_no":"00715","quantity":Decimal("3"),"delivery_date":date(2026,11,7)},
        {"pr_no":"00715","quantity":Decimal("3"),"delivery_date":date(2026,11,7)},
        {"pr_no":"00716","quantity":Decimal("2"),"delivery_date":date(2026,11,7)},
        {"pr_no":"00715","quantity":Decimal("100"),"delivery_date":date(2026,11,7),
         "voided_at":datetime(2026,11,8,12)},
    ]
    assert manual_total(rows,"00715")==Decimal("10")
    assert duplicate_warning(rows,"00715","3","2026-11-07",today=TODAY)
    assert not duplicate_warning(rows,"00715","100","2026-11-07",today=TODAY)
    assert not duplicate_warning(rows,"00715","4","2026-11-07",today=TODAY)
    assert not duplicate_warning(rows,"00716","3","2026-11-07",today=TODAY)


def test_writer_identity_and_parameterized_insert_and_void(monkeypatch):
    from src import pr_hand_deliveries as pr
    calls=[]
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,sql,values): calls.append((sql,values))
        def fetchone(self): return (77,)
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def transaction(self): return self
        def cursor(self): return Cursor()
    monkeypatch.setattr(pr.psycopg,"connect",lambda *a,**kw: Conn())
    result=write_hand_delivery("writer",ADMIN,"admin@example.com","insert",
                               pr_no="000715",quantity="2,25",
                               delivery_date="2026-11-06",today=TODAY)
    assert result==77
    assert calls[0][1]==("000715",Decimal("2.25"),date(2026,11,6),
                        "admin@example.com")
    assert "%s" in calls[0][0] and "planning.pr_hand_deliveries" in calls[0][0]
    result=write_hand_delivery("writer",ADMIN,"admin@example.com","void",entry_id=77)
    assert result==77
    assert calls[1][1]==("admin@example.com",77)
    assert "voided_at IS NULL" in calls[1][0]
    assert "DELETE" not in calls[1][0].upper()
    assert all("core." not in sql and "raw." not in sql for sql,_ in calls)


def test_unauthorized_or_invalid_never_opens_writer(monkeypatch):
    from src import pr_hand_deliveries as pr
    monkeypatch.setattr(pr.psycopg,"connect",
                        lambda *a,**kw: pytest.fail("No writer access expected"))
    with pytest.raises(PermissionError):
        write_hand_delivery("writer",{},"admin@example.com","insert",
                            pr_no="7",quantity="1",delivery_date=TODAY,today=TODAY)
    with pytest.raises(PermissionError):
        write_hand_delivery("writer",{"is_logged_in":True,
             "email_verified":False,"email":"admin@example.com"},
             "admin@example.com","insert",pr_no="7",
             quantity="1",delivery_date=TODAY,today=TODAY)
    for kwargs in [
        {"pr_no":"ABC","quantity":"1","delivery_date":TODAY},
        {"pr_no":"123","quantity":"0","delivery_date":TODAY},
        {"pr_no":"123","quantity":"2","delivery_date":date(2026,11,9)},
    ]:
        with pytest.raises(ValueError):
            write_hand_delivery("writer",ADMIN,"admin@example.com","insert",
                                today=TODAY,**kwargs)
    with pytest.raises(ValueError):
        write_hand_delivery("writer",ADMIN,"admin@example.com","void",entry_id=-1)
    with pytest.raises(ValueError):
        write_hand_delivery("writer",ADMIN,"admin@example.com","oops")


def test_void_is_one_time_and_never_erases_history(monkeypatch):
    from src import pr_hand_deliveries as pr
    class Cursor:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def execute(self,*args): pass
        def fetchone(self): return None
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def transaction(self): return self
        def cursor(self): return Cursor()
    monkeypatch.setattr(pr.psycopg,"connect",lambda *a,**kw: Conn())
    with pytest.raises(ValueError,match="anulada"):
        write_hand_delivery("writer",ADMIN,"admin@example.com","void",entry_id=1)


def test_pr_sql_migration_not_snapshotted_and_minimal_grants():
    sql=(ROOT/"migrations/010_pr_hand_deliveries.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS planning.pr_hand_deliveries" in sql
    assert "quantity NUMERIC(20,6) NOT NULL CHECK (quantity > 0)" in sql
    assert "delivery_date DATE NOT NULL" in sql
    assert "created_by TEXT NOT NULL" in sql and "voided_at TIMESTAMPTZ" in sql
    assert "snapshot_id" not in sql
    assert "UNIQUE(pr_no" not in sql
    assert "GRANT SELECT ON planning.pr_hand_deliveries TO compras_reader" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON planning.pr_hand_deliveries TO bulk_sc_writer" in sql
    assert "GRANT USAGE, SELECT ON SEQUENCE planning.pr_hand_deliveries_id_seq" in sql
    for keyword in ("DELETE FROM","DROP TABLE","TRUNCATE","UPDATE core.","UPDATE raw."):
        assert keyword not in sql


def test_manage_sc_and_manage_pr_tabs_and_compact_grid():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    assert 'tab1,tab2,tab3,tab4,tab5=st.tabs([' in app
    assert '"Manage SC","Manage PR"' in app
    assert 'with tab4:\n    st.subheader("Manage SC")' in app
    pr=app.split("with tab5:",1)[1]
    assert 'st.subheader("Manage PR")' in pr
    assert 'pr_admin=is_bulk_admin(pr_identity,pr_admin_emails)' in pr
    assert 'st.secrets.get("BULK_ADMIN_DATABASE_URL")' in pr
    assert '@st.fragment' in pr
    assert "with st.form(\"pr_add_delivery\",clear_on_submit=True):" in pr
    for label in ('st.text_input("PR"','st.text_input("Qty"',
                  'st.date_input("Fecha entrega"'):
        assert label in pr
    assert 'rows.insert(0,"delete","X")' not in pr
    assert 'visible.insert(0,"delete","X")' in pr
    assert '"color":"#B91C1C"' in pr
    assert '"rowHeight":32' in pr
    assert '"editable":False' in pr
    assert 'update_on=["cellClicked"]' in pr
    assert 'hand_deliveries.clear()' in pr
    assert 'st.rerun()' in pr
    assert "query.clear()" not in pr
    assert "DELETE FROM" not in pr
    assert 'write_hand_delivery(' in pr


def test_pr_erp_reconciliation_advisory_not_mutating():
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    pr=app.split("with tab5:",1)[1]
    assert "FROM core.receipts" in pr
    assert 'WHERE snapshot_id=%s AND receipt_no=%s' in pr
    assert 'PR no encontrado' in pr
    assert 'supera la cantidad aprobada ERP' in pr
    assert 'warnings.append(' in pr
    assert 'confirm_hand_delivery(pr,qty,day,warnings)' in pr
    assert 'UPDATE core.' not in pr
