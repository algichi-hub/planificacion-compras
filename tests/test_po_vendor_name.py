"""Supplier names are read from native SC exports and normalized once per PO."""
from decimal import Decimal
from pathlib import Path

from src.reconcile import parse_sc, summarize_po


def row(vendor_name="PROVEEDOR INDUSTRIAL, S.L."):
    values=[""]*52
    values[0]="210"
    values[6]="761488"
    values[7]="140"
    values[8]="123456"
    values[9]="Condensador"
    values[11]="3"
    values[16]="762087"
    values[17]="14"
    values[19]="3"
    values[23]="N00452"
    values[24]=vendor_name
    return parse_sc(values)


def test_supplier_name_is_imported_from_native_field_24():
    item=row("  PROVEEDOR INDUSTRIAL, S.L.  ")
    assert item["vendor_name"]=="PROVEEDOR INDUSTRIAL, S.L."


def test_unique_supplier_name_aggregates_repeated_source_lines():
    results=list(summarize_po([row(),row()]))
    assert len(results)==1
    key,sample,qty,status=results[0]
    assert key==("210","762087","14")
    assert sample["vendor_name"]=="PROVEEDOR INDUSTRIAL, S.L."
    assert sample["vendor_name_count"]==1
    assert qty==Decimal("3")
    assert status=="verified"


def test_conflicting_supplier_names_do_not_invent_value():
    rows=[row("Proveedor A"),row("Proveedor B")]
    _,sample,qty,status=next(iter(summarize_po(rows)))
    assert sample["vendor_name"] is None
    assert sample["vendor_name_count"]==2
    assert qty==Decimal("3") and status=="verified"


def test_absent_supplier_name_is_safe():
    _,sample,_,_=next(iter(summarize_po([row(""),row(None)])))
    assert sample["vendor_name"] is None
    assert sample["vendor_name_count"]==0


def test_import_and_migration_support_normalized_names():
    root=Path(__file__).resolve().parents[1]
    importer=(root/"scripts"/"import_snapshot.py").read_text(encoding="utf-8")
    migration=(root/"migrations"/"016_po_vendor_name.sql").read_text(encoding="utf-8")
    assert '"vendor_name","vendor_name_count"' in importer
    assert "ADD COLUMN IF NOT EXISTS vendor_name TEXT" in migration
    assert "vendor_name_count::bigint" in migration
    assert "p.vendor_name AS supplier_name" in migration
    assert "raw.source_rows" in migration
    assert "GRANT SELECT ON raw.source_rows" not in migration
    assert "DROP TABLE" not in migration
