"""Manage SC grid event validation, independent of Streamlit UI."""
from src.bulk_sc import normalize_sc, normalize_label


def parse_manage_event(payload):
    """Only accept recognized, scalar AG Grid cell events."""
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if kind not in ("edit", "delete"):
        return None
    try:
        row_id = int(payload["id"])
    except (TypeError, ValueError, KeyError):
        return None
    if row_id == 0:
        return None
    if kind == "delete":
        return {"type": "delete", "id": row_id}
    field = payload.get("field")
    if field not in ("sc_no", "context_description"):
        return None
    value = payload.get("value")
    if not isinstance(value, str):
        return None
    return {"type": "edit", "id": row_id, "field": field, "value": value}


def valid_existing_edit(event, items):
    """Validate a single edit against its immutable primary key."""
    if event is None or event["type"] != "edit" or event["id"] <= 0:
        raise ValueError("Edición no válida.")
    matches = items.loc[items["id"] == event["id"]]
    if len(matches) != 1:
        raise ValueError("La SC ya no existe en este grupo.")
    previous = matches.iloc[0]
    if event["field"] == "sc_no":
        sc = normalize_sc(event["value"])
        description = str(previous["context_description"])
    else:
        sc = str(previous["sc_no"])
        description = normalize_label(event["value"], "Descripción", 500)
    return sc, description, sc == str(previous["sc_no"]) and description == str(previous["context_description"])


def apply_draft_edit(draft, event):
    """Preserve incomplete new SC rows without writing them to the database."""
    if event is None or event["type"] != "edit" or event["id"] >= 0:
        raise ValueError("Fila nueva no válida.")
    result = dict(draft)
    result[event["field"]] = event["value"]
    if result["sc_no"].strip() and result["context_description"].strip():
        return result, True
    return result, False
