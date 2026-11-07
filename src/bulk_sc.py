"""Bulk SC persistence and fail-closed administrator authorization.

ERP/source tables are never written here. All mutations are parameterized,
transactional, and require a separate least-privilege connection.
"""
from datetime import datetime, timezone
import re
import psycopg

SC_PATTERN = re.compile(r"^[0-9]{1,40}$")


def is_bulk_admin(user, allowed_emails):
    """Never infer admin rights from an unverified/anonymous identity."""
    if not user or not bool(user.get("is_logged_in", False)):
        return False
    if user.get("email_verified") is not True:
        return False
    email = str(user.get("email") or "").strip().casefold()
    emails = {part.strip().casefold() for part in allowed_emails.split(",") if part.strip()}
    return bool(email and email in emails)


def normalize_sc(value):
    sc = str(value).strip()
    if not SC_PATTERN.fullmatch(sc):
        raise ValueError("El número de SC debe contener entre 1 y 40 dígitos.")
    return sc


def normalize_label(value, label, max_length):
    text = str(value).strip()
    if not 1 <= len(text) <= max_length:
        raise ValueError(f"{label}: introduce entre 1 y {max_length} caracteres.")
    return text


def write_bulk(admin_dsn, user, allowed_emails, operation, *, group_id=None,
               name=None, sc_no=None, description=None, item_id=None):
    """Validate authorization before connecting to a writer credential."""
    if not is_bulk_admin(user, allowed_emails):
        raise PermissionError("No tienes autorización para editar Bulk SC.")
    if not admin_dsn:
        raise RuntimeError("No se ha configurado BULK_ADMIN_DATABASE_URL.")
    if operation == "create_group":
        name = normalize_label(name, "Nombre", 160)
        description = str(description or "").strip()
        if len(description) > 500:
            raise ValueError("Descripción: máximo 500 caracteres.")
        statement, args = (
            "INSERT INTO planning.bulk_sc_groups (name,description) VALUES (%s,%s) RETURNING id",
            (name, description),
        )
    elif operation == "edit_group":
        name = normalize_label(name, "Nombre", 160)
        description = str(description or "").strip()
        if len(description) > 500:
            raise ValueError("Descripción: máximo 500 caracteres.")
        statement, args = (
            "UPDATE planning.bulk_sc_groups SET name=%s,description=%s,updated_at=now() "
            "WHERE id=%s RETURNING id",
            (name, description, int(group_id)),
        )
    elif operation == "remove_group":
        # The database's FK cascade affects only this user's group membership records.
        statement, args = (
            "DELETE FROM planning.bulk_sc_groups WHERE id=%s RETURNING id",
            (int(group_id),),
        )
    elif operation == "add_item":
        sc_no = normalize_sc(sc_no)
        description = normalize_label(description, "Descripción", 500)
        statement, args = (
            "INSERT INTO planning.bulk_sc_items (group_id, sc_no, context_description) "
            "VALUES (%s, %s, %s) ON CONFLICT (group_id, sc_no) DO UPDATE "
            "SET context_description = EXCLUDED.context_description, updated_at = now() "
            "RETURNING id",
            (int(group_id), sc_no, description),
        )
    elif operation == "edit_item":
        description = normalize_label(description, "Descripción", 500)
        statement, args = (
            "UPDATE planning.bulk_sc_items SET context_description=%s, "
            "updated_at=now() WHERE id=%s AND group_id=%s RETURNING id",
            (description, int(item_id), int(group_id)),
        )
    elif operation == "remove_item":
        statement, args = (
            "DELETE FROM planning.bulk_sc_items WHERE id=%s AND group_id=%s RETURNING id",
            (int(item_id), int(group_id)),
        )
    else:
        raise ValueError("Operación no permitida.")
    with psycopg.connect(admin_dsn, connect_timeout=15) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(statement, args)
                row = cur.fetchone()
                if row is None:
                    raise ValueError("La entrada ya no existe en el grupo.")
                return row[0]
