"""Daily snapshot scheduling: file date, rolling period, and idempotent import."""
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.import_snapshot import (
    build_parser, resolve_import_dates, matching_validated_snapshot,
)


def options(**kw):
    return SimpleNamespace(date=None,from_date=None,period=None,**kw)


def test_daily_cli_without_fixed_dates():
    args=build_parser().parse_args(["--period","365","--input","entrada"])
    assert args.date is None
    assert args.from_date is None
    assert args.period==365


def test_rolling_cutoff_is_from_system_day_not_zip_day(tmp_path):
    archive=tmp_path/"planificacion-compras.zip"
    archive.write_bytes(b"ZIP")
    args=SimpleNamespace(date="2026-11-11",from_date=None,period=365)
    snapshot,cutoff=resolve_import_dates(args,archive,today=date(2026,11,12))
    assert snapshot=="2026-11-11"
    assert cutoff==date(2026,11,12)-timedelta(days=365)


def test_default_date_uses_filesystem_creation_or_mtime(tmp_path,monkeypatch):
    archive=tmp_path/"planificacion-compras.zip"
    archive.write_bytes(b"ZIP")
    import scripts.import_snapshot as mod
    class Fake:
        st_birthtime=datetime(2026,11,10,8,35).timestamp()
        st_mtime=datetime(2026,11,11,8,35).timestamp()
    monkeypatch.setattr(Path,"stat",lambda self:Fake())
    snapshot,cutoff=resolve_import_dates(
        SimpleNamespace(date=None,from_date=None,period=365),
        archive,today=date(2026,11,12))
    assert snapshot=="2026-11-10"
    assert cutoff==date(2025,11,12)


def test_explicit_from_compatible_and_period_mutually_exclusive(tmp_path):
    archive=tmp_path/"planificacion-compras.zip"
    archive.write_bytes(b"ZIP")
    args=build_parser().parse_args([
        "--date","2026-11-11","--from","2026-01-01",
    ])
    assert resolve_import_dates(args,archive)[1]==date(2026,1,1)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--from","2026-01-01","--period","365"])
    with pytest.raises(ValueError):
        resolve_import_dates(
            SimpleNamespace(date="2026-11-11",from_date=None,period=0),archive)


class FakeCursor:
    def __init__(self,row):
        self.row=row
        self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql):
        self.calls.append(sql)
    def fetchone(self):return self.row


class FakeConn:
    def __init__(self,row):self.cursor_obj=FakeCursor(row)
    def cursor(self):return self.cursor_obj


def test_only_latest_validated_matching_sources_skips():
    from scripts.import_snapshot import IMPORTER_REVISION
    hashes={"SC_FAS.csv":"one","INC_FAS.csv":"two",
            "Recepciones_Sevilla.csv":"three","RecepcionesTotales.csv":"four"}
    db=FakeConn((12,hashes,IMPORTER_REVISION))
    assert matching_validated_snapshot(db,hashes)==12
    assert "state='validated'" in db.cursor_obj.calls[0]
    assert matching_validated_snapshot(FakeConn(None),hashes) is None
    assert matching_validated_snapshot(FakeConn((12,dict(hashes,**{"INC_FAS.csv":"new"}),IMPORTER_REVISION)),hashes) is None
    assert matching_validated_snapshot(FakeConn((12,hashes,"old-importer")),hashes) is None


def test_skip_gate_before_any_snapshot_insert_or_csv_parsing():
    code=(Path(__file__).resolve().parents[1]/"scripts/import_snapshot.py").read_text(encoding="utf-8")
    fn=code.split("def run_import(args):",1)[1].split("def build_parser():",1)[0]
    assert fn.index("previous=matching_validated_snapshot(db,hashes)") < fn.index("selected_sc_keys,conflicts=")
    assert fn.index("return None") < fn.index("INSERT INTO audit.snapshots")
    assert "SNAPSHOT_SKIPPED" in fn
    assert "SNAPSHOT_VALIDATED" in fn


def test_identical_sources_skip_before_writes_or_csv_scan(tmp_path,monkeypatch):
    from scripts import import_snapshot as mod
    archive=tmp_path/"planificacion-compras.zip"
    archive.write_bytes(b"encrypted")
    for name in (*mod.SOURCES,"RecepcionesTotales.csv"):
        (tmp_path/name).write_bytes(name.encode())
    monkeypatch.setattr(mod,"prepare_inputs",lambda folder:False)
    monkeypatch.setattr(mod,"sha256",lambda path:str(path.name))
    monkeypatch.setenv("DATABASE_URL","fake")
    events=[]
    monkeypatch.setattr(mod,"log_event",lambda *args,**kwargs:events.append((args,kwargs)))
    snapshot_hashes={name:name for name in (*mod.SOURCES,"RecepcionesTotales.csv")}
    from scripts.import_snapshot import IMPORTER_REVISION
    class Connection(FakeConn):
        def __enter__(self):return self
        def __exit__(self,*args):return False
    conn=Connection((13,snapshot_hashes,IMPORTER_REVISION))
    monkeypatch.setattr(mod.psycopg,"connect",lambda dsn:conn)
    monkeypatch.setattr(mod,"approved_sc_selection",
                        lambda *args:pytest.fail("CSV should not be parsed"))
    args=SimpleNamespace(date=None,from_date=None,period=365,input=str(tmp_path))
    assert mod.run_import(args) is None
    assert len(conn.cursor_obj.calls)==1
    assert any(a[1]=="SNAPSHOT_SKIPPED" for a,k in events)
