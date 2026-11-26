"""Parse and persist manually pasted PR handovers. No ERP/source-table mutations."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re

import psycopg

from src.pr_hand_deliveries import (
    _authorized_email, normalize_pr, normalize_nbi,
    normalize_quantity, normalize_delivery_date,
)

MAX_ROWS = 200
MAX_CHARACTERS = 32000
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def parse_pr_batch(text, *, today=None):
    """Strict groups of PR;Qty;DD/MM/YYYY;NBI, with optional terminal ';'."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Pega al menos una entrega.")
    if len(text) > MAX_CHARACTERS:
        raise ValueError("Texto demasiado largo para una carga: máximo 32000 caracteres.")
    parts = [part.strip() for part in text.strip().split(";")]
    if parts[-1] == "":
        parts.pop()
    if not parts or len(parts) % 4:
        raise ValueError("Cada entrega necesita exactamente cuatro campos: PR;Qty;Fecha;NBI.")
    if len(parts) // 4 > MAX_ROWS:
        raise ValueError(f"Máximo {MAX_ROWS} entregas por lote.")
    records = []
    for index in range(0, len(parts), 4):
        line = index // 4 + 1
        pr, qty, raw_date, nbi = parts[index:index + 4]
        try:
            if not DATE_RE.fullmatch(raw_date):
                raise ValueError("fecha: usa DD/MM/AAAA.")
            day = datetime.strptime(raw_date, "%d/%m/%Y").date()
            records.append((
                normalize_pr(pr),
                normalize_quantity(qty),
                normalize_delivery_date(day, today=today),
                normalize_nbi(nbi),
            ))
        except ValueError as exc:
            raise ValueError(f"Fila {line}: {exc}") from exc
    return tuple(records)


def batch_digest(records):
    """Stable digest for equivalent decimal representations and date spellings."""
    # Sorting makes a re-paste in a different order the same logical batch,
    # while retaining duplicate rows (multiplicity) in the digest.
    normalized = sorted(
        [pr, str(qty.normalize()), day.isoformat(), nbi]
        for pr, qty, day, nbi in records
    )
    encoded = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def batch_warnings(records, ledger, erp):
    """Advisory checks; existing partial deliveries may be legitimate."""
    warnings = []
    keys = Counter((pr, qty, day, nbi) for pr, qty, day, nbi in records)
    for (pr, _qty, _day, _nbi), n in keys.items():
        if n > 1:
            warnings.append(f"PR {pr}: {n} filas idénticas dentro del lote.")
    existing = Counter(
        (str(r["pr_no"]), Decimal(str(r["quantity"])),
         r["delivery_date"], str(r.get("received_by_nbi") or ""))
        for r in ledger
        if not r.get("voided_at")
    )
    for key in keys:
        if existing[key]:
            warnings.append(f"PR {key[0]}: ya existe una entrega activa idéntica.")
    totals = defaultdict(lambda: Decimal("0"))
    for r in ledger:
        if not r.get("voided_at"):
            totals[str(r["pr_no"])] += Decimal(str(r["quantity"]))
    for pr, qty, _day, _nbi in records:
        totals[pr] += qty
    for pr in sorted({r[0] for r in records}):
        evidence = erp.get(pr)
        if evidence is None or int(evidence["n"]) == 0:
            warnings.append(f"PR {pr}: no encontrado en el snapshot seleccionado.")
        elif int(evidence["n"]) > 1:
            warnings.append(f"PR {pr}: tiene varios movimientos ERP; revisa el acumulado.")
        elif evidence["approved_qty"] is not None and totals[pr] > Decimal(str(evidence["approved_qty"])):
            warnings.append(f"PR {pr}: las entregas acumuladas superarían la cantidad aprobada ERP.")
    return warnings


def insert_pr_batch(admin_dsn, user, allowed_emails, records, *, expected_digest, today=None):
    """One authorized, atomic and idempotent write for the entire confirmed lot."""
    actor = _authorized_email(user, allowed_emails)
    if not admin_dsn:
        raise RuntimeError("No se ha configurado la conexión de escritura.")
    if not records or len(records) > MAX_ROWS:
        raise ValueError("Número de entregas fuera del límite permitido.")
    # Never trust the dataframe or preview stored in client session state.
    checked = tuple((
        normalize_pr(pr), normalize_quantity(qty),
        normalize_delivery_date(day, today=today), normalize_nbi(nbi)
    ) for pr, qty, day, nbi in records)
    digest = batch_digest(checked)
    if digest != expected_digest:
        raise ValueError("El contenido ha cambiado después de la vista previa: vuelve a validarlo.")
    with psycopg.connect(admin_dsn, connect_timeout=15) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO planning.pr_hand_delivery_batches "
                    "(digest,item_count,created_by) VALUES (%s,%s,%s) "
                    "ON CONFLICT (digest) DO NOTHING RETURNING id",
                    (digest, len(checked), actor),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "SELECT id,item_count FROM planning.pr_hand_delivery_batches "
                        "WHERE digest=%s", (digest,),
                    )
                    found = cur.fetchone()
                    if found is None or found[1] != len(checked):
                        raise RuntimeError("No se pudo comprobar el lote existente.")
                    return {"inserted": False, "count": found[1], "batch_id": found[0]}
                batch_id = row[0]
                # All rows live or roll back together (including the batch identity).
                cur.executemany(
                    "INSERT INTO planning.pr_hand_deliveries "
                    "(pr_no,quantity,delivery_date,received_by_nbi,created_by,batch_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    [(pr, qty, day, nbi, actor, batch_id)
                     for pr, qty, day, nbi in checked],
                )
                return {"inserted": True, "count": len(checked), "batch_id": batch_id}
