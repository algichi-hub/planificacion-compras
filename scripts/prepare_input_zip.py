"""Atomic, idempotent staging of four CSVs from one password-protected ZIP.

No Neon access. A SHA-256 manifest is committed only after all four validated
files have been replaced. Failure restores previous files.
"""
import csv
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
import sys
from contextlib import contextmanager
from pathlib import Path

import pyzipper

# Resolve the project root before importing src, including direct script execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.import_history import log_event

ARCHIVE = "planificacion-compras.zip"
FILES = (
    "SC_FAS.csv",
    "INC_FAS.csv",
    "Recepciones_Sevilla.csv",
    "RecepcionesTotales.csv",
)
STATE_NAME = ".planificacion_compras_zip_state.json"
MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GiB per file
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB overall


class InputArchiveError(ValueError):
    """Archive invalid or incomplete; never start snapshot import."""


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@contextmanager
def exclusive_lock(folder):
    """Fail closed on concurrent scheduled jobs, instead of mixing CSV versions."""
    lock = folder / ".planificacion_compras_import.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise InputArchiveError(
            f"Another import (or a stale lock) exists: {lock}. "
            "Confirm no import is running before removing it."
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def _read_state(path):
    if not path.is_file():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputArchiveError("Invalid ZIP manifest: inspect before retrying") from exc
    if not isinstance(state, dict):
        raise InputArchiveError("Invalid ZIP manifest structure")
    return state


def _check_csv(path, name):
    """Quick source-header and encoding checks; existing import parser owns row validation."""
    try:
        with path.open("r", encoding="cp1252", errors="strict", newline="") as handle:
            dialect = "|" if name == "SC_FAS.csv" else ";"
            reader = csv.reader(handle, delimiter=dialect,
                                quoting=csv.QUOTE_NONE if name in
                                ("SC_FAS.csv", "RecepcionesTotales.csv")
                                else csv.QUOTE_MINIMAL)
            header = next(reader, None)
    except (UnicodeError, csv.Error, OSError) as exc:
        raise InputArchiveError(f"Invalid CSV encoding/header: {name}") from exc
    if not header:
        raise InputArchiveError(f"Empty CSV: {name}")
    header = [x.strip().lstrip("\ufeff") for x in header]
    if header[-1] == "":
        header.pop()
    if name == "SC_FAS.csv":
        from src.normalize import SC_HEADERS
        if header != SC_HEADERS:
            raise InputArchiveError("SC_FAS.csv has unexpected header or separator")
    elif name == "RecepcionesTotales.csv":
        from src.pr_approval_import import HEADER
        if tuple(header) != HEADER:
            raise InputArchiveError("RecepcionesTotales.csv has unexpected header")
    elif len(header) < 10:
        raise InputArchiveError(f"{name}: unexpected number of columns")


def _prepare_inputs(folder, password=None):
    """Synchronize exactly four CSV files from encrypted ZIP.

    Returns True only when CSVs were updated. On unchanged ZIP, ensure the
    existing CSVs still match the previous manifest; otherwise re-extract.
    """
    folder = Path(folder)
    archive = folder / ARCHIVE
    if not archive.is_file():
        raise InputArchiveError(f"Required ZIP missing: {archive}")
    with exclusive_lock(folder):
        archive_hash = digest(archive)
        manifest_file = folder / STATE_NAME
        state = _read_state(manifest_file)
        current = state.get("csv_sha256")
        if (state.get("zip_sha256") == archive_hash
                and isinstance(current, dict)
                and set(current) == set(FILES)
                and all((folder / name).is_file() and
                        digest(folder / name) == current[name] for name in FILES)):
            return False

        # No hardcoded credentials, CLI password flags or secrets in logs.
        secret = password if password is not None else os.environ.get("COMPRAS_ZIP_PASSWORD")
        if not secret:
            raise InputArchiveError("COMPRAS_ZIP_PASSWORD is required to extract the ZIP")
        if not isinstance(secret, str):
            raise InputArchiveError("ZIP password must be text")

        with tempfile.TemporaryDirectory(prefix=".zip_stage_", dir=folder) as temporary:
            stage = Path(temporary)
            hashes = {}
            try:
                with pyzipper.AESZipFile(archive) as zf:
                    members = zf.infolist()
                    names = [info.filename for info in members]
                    if len(names) != len(FILES) or set(names) != set(FILES):
                        raise InputArchiveError(
                            "ZIP must contain exactly four CSVs at its root: "
                            + ", ".join(FILES)
                        )
                    if any(info.is_dir() or not (info.flag_bits & 1) for info in members):
                        raise InputArchiveError("All four CSV entries must be encrypted files")
                    total = sum(info.file_size for info in members)
                    if (total > MAX_TOTAL_BYTES or
                            any(info.file_size > MAX_FILE_BYTES or info.file_size <= 0
                                for info in members)):
                        raise InputArchiveError("ZIP file size limit exceeded or empty member")
                    zf.setpassword(secret.encode("utf-8"))
                    for name in FILES:
                        with zf.open(name) as src, (stage / name).open("wb") as dst:
                            shutil.copyfileobj(src, dst, length=1024 * 1024)
                        _check_csv(stage / name, name)
                        hashes[name] = digest(stage / name)
            except (RuntimeError, ValueError, OSError, EOFError, zipfile.BadZipFile, NotImplementedError) as exc:
                if isinstance(exc, InputArchiveError):
                    raise
                raise InputArchiveError(
                    "ZIP cannot be decrypted or validated (wrong password, corruption, or format)"
                ) from exc

            backups = stage / "previous"
            backups.mkdir()
            existed = {}
            for name in FILES:
                old = folder / name
                existed[name] = old.exists()
                if existed[name]:
                    shutil.copy2(old, backups / name)

            replaced = []
            try:
                for name in FILES:
                    os.replace(stage / name, folder / name)
                    replaced.append(name)
                payload = json.dumps(
                    {"zip_sha256": archive_hash, "csv_sha256": hashes},
                    indent=2, sort_keys=True
                )
                staged_state = stage / STATE_NAME
                staged_state.write_text(payload, encoding="utf-8")
                os.replace(staged_state, manifest_file)
            except OSError as exc:
                for name in reversed(replaced):
                    if existed[name]:
                        os.replace(backups / name, folder / name)
                    else:
                        (folder / name).unlink(missing_ok=True)
                raise InputArchiveError("Failed to replace CSVs: previous files restored") from exc
        return True

def prepare_inputs(folder, password=None):
    """Run ZIP preflight with durable, append-only operational logging."""
    folder = Path(folder)
    log_event(folder, "ZIP_CHECK_START", archive=ARCHIVE)
    try:
        changed = _prepare_inputs(folder, password=password)
    except InputArchiveError as exc:
        # Failure reasons never contain the password, connection URI, or file data.
        log_event(folder, "ZIP_CHECK_ERROR", reason=str(exc).replace("\\n", " "))
        raise
    except Exception as exc:
        log_event(folder, "ZIP_CHECK_ERROR", error_type=type(exc).__name__)
        raise
    log_event(
        folder,
        "ZIP_UPDATED" if changed else "ZIP_UNCHANGED",
        csv_count=len(FILES),
    )
    return changed

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Validate and synchronize an encrypted procurement ZIP")
    ap.add_argument("--input", default="entrada", help="Folder containing planificacion-compras.zip")
    args = ap.parse_args()
    try:
        changed = prepare_inputs(args.input)
    except InputArchiveError as exc:
        ap.exit(1, f"ZIP preflight failed: {exc}\\n")
    print("CSV files updated" if changed else "ZIP unchanged; four CSVs verified")
