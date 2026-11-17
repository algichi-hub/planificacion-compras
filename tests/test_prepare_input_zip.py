"""Encrypted input ZIP: AES, preflight, atomic replacement and idempotency."""
import csv
import json
import os
import zipfile
from pathlib import Path

import pytest
import pyzipper

from scripts.prepare_input_zip import (
    ARCHIVE, FILES, STATE_NAME, InputArchiveError, prepare_inputs
)
from src.normalize import SC_HEADERS
from src.pr_approval_import import HEADER


def valid_files(tag="A"):
    def encode(values, sep):
        return (sep.join(values) + "\r\n" + sep.join([""] * len(values)) + "\r\n").encode("cp1252")
    return {
        "SC_FAS.csv": encode(SC_HEADERS, "|"),
        "INC_FAS.csv": encode(["INC"] + ["C" + str(i) for i in range(27)], ";"),
        "Recepciones_Sevilla.csv": encode(["RECEPCION"] + ["C" + str(i) for i in range(27)], ";"),
        "RecepcionesTotales.csv": encode(HEADER, ";"),
    }


def encrypted_zip(folder, contents, password="example-secret"):
    with pyzipper.AESZipFile(folder / ARCHIVE, "w",
                            compression=zipfile.ZIP_DEFLATED,
                            encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode("utf-8"))
        for name, data in contents.items():
            zf.writestr(name, data)


def test_first_extract_second_idempotent_and_state_has_no_password(tmp_path):
    payload=valid_files()
    encrypted_zip(tmp_path,payload)
    assert prepare_inputs(tmp_path,"example-secret") is True
    assert {p.name for p in tmp_path.glob("*.csv")} == set(FILES)
    for name,data in payload.items():
        assert (tmp_path/name).read_bytes()==data
    state=json.loads((tmp_path/STATE_NAME).read_text(encoding="utf-8"))
    assert len(state["zip_sha256"])==64
    assert set(state["csv_sha256"])==set(FILES)
    assert "example-secret" not in json.dumps(state)
    assert prepare_inputs(tmp_path,"example-secret") is False
    assert prepare_inputs(tmp_path) is False  # no password needed on unchanged archive


def test_modified_zip_overwrites_all_four_and_updates_hash(tmp_path):
    first=valid_files()
    encrypted_zip(tmp_path,first)
    assert prepare_inputs(tmp_path,"example-secret")
    old=json.loads((tmp_path/STATE_NAME).read_text())["zip_sha256"]
    second={name:data+b"UPDATED\r\n" for name,data in first.items()}
    encrypted_zip(tmp_path,second)
    assert prepare_inputs(tmp_path,"example-secret") is True
    assert all((tmp_path/name).read_bytes()==second[name] for name in FILES)
    assert json.loads((tmp_path/STATE_NAME).read_text())["zip_sha256"]!=old


def test_changed_or_deleted_csv_is_healed_even_when_zip_unchanged(tmp_path):
    payload=valid_files()
    encrypted_zip(tmp_path,payload)
    prepare_inputs(tmp_path,"example-secret")
    (tmp_path/FILES[0]).write_bytes(b"BROKEN")
    (tmp_path/FILES[1]).unlink()
    assert prepare_inputs(tmp_path,"example-secret") is True
    assert all((tmp_path/name).read_bytes()==payload[name] for name in FILES)


@pytest.mark.parametrize("bad", [
    {"missing": "RecepcionesTotales.csv"},
    {"extra": "extra.csv"},
    {"traversal": "../SC_FAS.csv"},
])
def test_reject_incomplete_extra_or_path_traversal_without_overwrites(tmp_path,bad):
    original=valid_files()
    encrypted_zip(tmp_path,original)
    prepare_inputs(tmp_path,"example-secret")
    original_state=(tmp_path/STATE_NAME).read_bytes()
    damaged=dict(original)
    if "missing" in bad:
        damaged.pop(bad["missing"])
    if "extra" in bad:
        damaged[bad["extra"]]=b"bad"
    if "traversal" in bad:
        damaged[bad["traversal"]]=damaged.pop("SC_FAS.csv")
    encrypted_zip(tmp_path,damaged)
    with pytest.raises(InputArchiveError,match="exactly four"):
        prepare_inputs(tmp_path,"example-secret")
    assert (tmp_path/STATE_NAME).read_bytes()==original_state
    assert all((tmp_path/name).read_bytes()==original[name] for name in FILES)


def test_wrong_password_and_bad_header_fail_without_overwrite(tmp_path):
    original=valid_files()
    encrypted_zip(tmp_path,original)
    prepare_inputs(tmp_path,"example-secret")
    state=(tmp_path/STATE_NAME).read_bytes()
    encrypted_zip(tmp_path,{n:b for n,b in original.items()},password="other")
    with pytest.raises(InputArchiveError):
        prepare_inputs(tmp_path,"example-secret")
    assert (tmp_path/STATE_NAME).read_bytes()==state
    broken=dict(original)
    broken["SC_FAS.csv"]=b"incorrect|columns\r\n1|2\r\n"
    encrypted_zip(tmp_path,broken)
    with pytest.raises(InputArchiveError,match="SC_FAS.csv"):
        prepare_inputs(tmp_path,"example-secret")
    assert all((tmp_path/name).read_bytes()==original[name] for name in FILES)


def test_reject_unencrypted_archive_and_lock(tmp_path):
    with zipfile.ZipFile(tmp_path/ARCHIVE,"w") as zf:
        for name,data in valid_files().items():
            zf.writestr(name,data)
    with pytest.raises(InputArchiveError,match="encrypted"):
        prepare_inputs(tmp_path,"example-secret")
    (tmp_path/".planificacion_compras_import.lock").write_text("12345")
    with pytest.raises(InputArchiveError,match="lock"):
        prepare_inputs(tmp_path,"example-secret")


def test_missing_password_or_missing_zip_never_modifies_existing_files(tmp_path,monkeypatch):
    monkeypatch.delenv("COMPRAS_ZIP_PASSWORD",raising=False)
    with pytest.raises(InputArchiveError,match="ZIP missing"):
        prepare_inputs(tmp_path)
    encrypted_zip(tmp_path,valid_files())
    with pytest.raises(InputArchiveError,match="COMPRAS_ZIP_PASSWORD"):
        prepare_inputs(tmp_path)
    assert not list(tmp_path.glob("*.csv"))


def test_snapshot_import_preflights_before_all_database_side_effects():
    code=(Path(__file__).resolve().parents[1]/"scripts/import_snapshot.py").read_text(encoding="utf-8")
    assert "changed=prepare_inputs(root)" in code
    assert code.index("changed=prepare_inputs(root)") < code.index("with psycopg.connect(connstr) as db:")
    assert "raise SystemExit(f\"Input ZIP preflight failed: {exc}\")" in code
    bat=(Path(__file__).resolve().parents[1]/"scripts/snapshot_semanal_windows.bat").read_text()
    assert "COMPRAS_ZIP_PASSWORD" in bat
    assert "scripts\\import_snapshot.py" in bat


def test_failed_second_replacement_restores_all_previous_csv_and_manifest(tmp_path,monkeypatch):
    from scripts import prepare_input_zip as manager
    original=valid_files()
    encrypted_zip(tmp_path,original)
    prepare_inputs(tmp_path,"example-secret")
    previous_manifest=(tmp_path/STATE_NAME).read_bytes()
    changed={name:data+b"NEW\\r\\n" for name,data in original.items()}
    encrypted_zip(tmp_path,changed)
    real_replace=manager.os.replace
    interrupted={"yes":False}

    def fail_once(src,dst):
        if Path(dst).name == "INC_FAS.csv" and not interrupted["yes"]:
            interrupted["yes"]=True
            raise OSError("simulated Windows file lock")
        return real_replace(src,dst)

    monkeypatch.setattr(manager.os,"replace",fail_once)
    with pytest.raises(InputArchiveError,match="previous files restored"):
        prepare_inputs(tmp_path,"example-secret")
    assert interrupted["yes"] is True
    assert all((tmp_path/name).read_bytes()==data for name,data in original.items())
    assert (tmp_path/STATE_NAME).read_bytes()==previous_manifest
