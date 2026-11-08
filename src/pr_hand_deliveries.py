"""Physical hand-delivery ledger: strictly distinct from ERP receipts/stock.

The existing verified-admin allowlist and restricted writer DSN are reused.
Records are never deleted; a correction voids the previous event.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
import psycopg
from src.bulk_sc import is_bulk_admin, normalize_sc

QTY_RE = re.compile(r"^(?:[0-9]{1,14})(?:[.,][0-9]{1,6})?$")


def normalize_pr(value):
    return normalize_sc(value)


def normalize_quantity(value):
    """Spanish decimal comma or decimal dot; never interpret grouping marks."""
    if isinstance(value, bool):
        raise ValueError("Qty debe ser un número positivo.")
    raw = str(value).strip()
    if not QTY_RE.fullmatch(raw):
        raise ValueError("Qty: número positivo, sin separador de miles, máximo 6 decimales.")
    try:
        qty = Decimal(raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Qty no válida.") from exc
    if not qty.is_finite() or qty <= 0:
        raise ValueError("Qty debe ser mayor que cero.")
    return qty


def normalize_delivery_date(value, *, today=None):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Fecha de entrega no válida.") from exc
    if not isinstance(value, date):
        raise ValueError("Fecha de entrega no válida.")
    if value > (today or date.today()):
        raise ValueError("Una entrega real no puede tener fecha futura.")
    return value


def _authorized_email(user, allowed_emails):
    if not is_bulk_admin(user, allowed_emails):
        raise PermissionError("Se requiere una cuenta administradora verificada.")
    return str(user["email"]).strip().casefold()


def write_hand_delivery(admin_dsn, user, allowed_emails, operation, *,
                        pr_no=None, quantity=None, delivery_date=None, entry_id=None,
                        today=None):
    """Validate before connecting; one parameterized transactional mutation."""
    actor = _authorized_email(user, allowed_emails)
    if not admin_dsn:
        raise RuntimeError("No se ha configurado la conexión de escritura.")
    if operation == "insert":
        pr = normalize_pr(pr_no)
        qty = normalize_quantity(quantity)
        handover_date = normalize_delivery_date(delivery_date, today=today)
        statement = (
            "INSERT INTO planning.pr_hand_deliveries "
            "(pr_no,quantity,delivery_date,created_by) VALUES (%s,%s,%s,%s) "
            "RETURNING id"
        )
        values = (pr, qty, handover_date, actor)
    elif operation == "void":
        if isinstance(entry_id, bool) or not str(entry_id).isdigit() or int(entry_id) <= 0:
            raise ValueError("Identificador de entrega inválido.")
        statement = (
            "UPDATE planning.pr_hand_deliveries SET voided_at=now(),voided_by=%s "
            "WHERE id=%s AND voided_at IS NULL RETURNING id"
        )
        values = (actor, int(entry_id))
    else:
        raise ValueError("Operación de entrega no permitida.")
    with psycopg.connect(admin_dsn, connect_timeout=15) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(statement, values)
                result = cur.fetchone()
                if result is None:
                    raise ValueError("La entrega ya fue anulada o no existe.")
                return result[0]


def manual_total(rows, pr_no):
    """Sum active partial deliveries by PR; no snapshot dependency."""
    return sum((Decimal(str(r["quantity"])) for r in rows
                if str(r["pr_no"]) == str(pr_no) and not r.get("voided_at")),
               Decimal("0"))


def duplicate_warning(rows, pr_no, quantity, delivery_date, *, today=None):
    """Do not silently collapse same-day events; require human confirmation."""
    qty=normalize_quantity(quantity)
    day=normalize_delivery_date(delivery_date,today=today)
    return any(str(r["pr_no"]) == str(pr_no)
               and Decimal(str(r["quantity"])) == qty
               and r["delivery_date"] == day
               and not r.get("voided_at") for r in rows)
