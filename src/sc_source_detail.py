"""Read-only request and purchasing detail from normalized and original SC rows.

Raw SC_FAS can contain several source rows per SC/position (one per PO).
Never mix PO-specific metadata from another order or silently select
conflicting values from duplicated source records.
"""
from datetime import date
from src.normalize import date_es
from src.detail_view import display_value
import pandas as pd

SC_FIELDS = (
    ("Artículo", "article"),
    ("Descripción", "description"),
    ("Proyecto", "project"),
    ("Centro", "centre"),
    ("Director", "project_director"),
)
SC_RAW_FIELDS = (
    ("Fecha aprobación SC", "FECHA APROBACIÓN__12", True),
    ("Fecha entrega solicitada", "FECHA ENTREGA SOLICITUD__13", True),
)
ORDER_FIELDS = (
    ("Proveedor", "NOMBRE__24", False),
    ("Comprador", "COMPRADOR__45", False),
    ("Estado compras ERP", "ESTADO COMPRAS__5", False),
    ("Fecha aprobación pedido", "FECHA APROBACIÓN DEL PEDIDO__41", True),
    ("Plan original", "FECHA PLANIFICADA__26", True),
)
MULTIPLE = "Valores distintos en origen"


def _clean(value):
    return str(value or "").strip()


def _value_from_raw(rows, key, is_date=False):
    values = {_clean(r.get(key)) for r in rows if _clean(r.get(key))}
    if not values:
        return "—"
    if len(values) != 1:
        return MULTIPLE
    value = values.pop()
    if is_date:
        try:
            return display_value(date_es(value))
        except ValueError:
            return "Fecha de origen inválida"
    return value


def request_detail(line, raw_rows):
    """Request-level data; ambiguous fields are disclosed, not guessed."""
    records = []
    for label, key in SC_FIELDS:
        records.append({"Campo": label, "Valor": display_value(line.get(key))})
    for label, key, is_date in SC_RAW_FIELDS:
        records.append({"Campo": label,
                        "Valor": _value_from_raw(raw_rows, key, is_date)})
    return pd.DataFrame(records, columns=["Campo", "Valor"])


def planning_detail(trace, raw_rows):
    """One block per distinct PO/position; no accidental receipt duplication."""
    records, seen = [], set()
    for _, order in trace.iterrows():
        po = (_clean(order.get("pedido")), _clean(order.get("posicion_pedido")))
        if po in seen:
            continue
        seen.add(po)
        matches = [r for r in raw_rows
                   if (_clean(r.get("PEDIDO__16")), _clean(r.get("POSICIÓN__17"))) == po]
        records.append({"Campo": "Pedido/Pos", "Valor": f"{po[0]}/{po[1]}"})
        for label, key, is_date in ORDER_FIELDS:
            records.append({"Campo": label,
                            "Valor": _value_from_raw(matches, key, is_date)})
        # Current plan comes from the validated core.po_lines field, not raw.
        records.append({"Campo": "Plan actual",
                        "Valor": display_value(order.get("fecha_planificada"))})
    return pd.DataFrame(records, columns=["Campo", "Valor"])
