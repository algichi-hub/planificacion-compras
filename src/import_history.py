"""Append-only local operations history for the procurement ZIP and snapshot importer.

No secrets, ZIP passwords, DSNs or CSV contents are recorded. Each event is
one UTF-8 line; concurrent Windows task runs use independent append handles.
"""
from datetime import datetime
from pathlib import Path

LOG_FILENAME = "planificacion-compras.log"


def history_path(input_dir):
    folder = Path(input_dir).resolve()
    # Standard repo layout: ./entrada -> ./logs.
    base = folder.parent if folder.name.lower() == "entrada" else folder
    return base / "logs" / LOG_FILENAME


def log_event(input_dir, event, **details):
    """Append a structured, human-readable event with local timezone timestamp.

    Callers must supply only whitelisted operational facts (never credentials,
    exception traces or raw CSV data).
    """
    path = history_path(input_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    fields = " | ".join(f"{key}={value}" for key, value in details.items())
    entry = f"{timestamp} | {event}"
    if fields:
        entry += " | " + fields
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(entry + "\n")
    return path
