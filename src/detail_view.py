"""Presentation-only utilities for native Streamlit SC detail tables."""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd


LABELS = {
    "pedido": "Pedido",
    "posicion_pedido": "Posición pedido",
    "articulo_pedido": "Artículo pedido",
    "proveedor": "Proveedor",
    "cantidad_pedida": "Cantidad pedida",
    "fecha_planificada": "Fecha planificada",
    "parte_recepcion": "Parte de recepción",
    "fecha_recepcion": "Fecha recepción",
    "cantidad_entregada": "Cantidad entregada",
    "cantidad_aprobada": "Cantidad aprobada",
    "estado_recepcion": "Estado recepción",
    "estado_vinculo": "Estado vínculo",
    "referencias_reac": "Referencias REAC",
    "numero_incidencias": "Número de incidencias",
}


def display_value(value):
    """Keep identifiers intact, display decimals with comma for Spanish users."""
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return "—"
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", ",")
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value)


def transpose_trace(trace):
    """Turn all trace records into two columns, with a separate block per movement.

    Preserve every source field and record, including rows without a reception.
    A single table remains selectable and copyable in Streamlit.
    """
    entries = []
    for index, (_, record) in enumerate(trace.iterrows(), start=1):
        receipt = display_value(record.get("parte_recepcion"))
        po = display_value(record.get("pedido"))
        position = display_value(record.get("posicion_pedido"))
        entries.append({
            "Campo": f"Movimiento {index}",
            "Valor": f"Pedido {po}/{position} · Recepción {receipt}",
        })
        for column, value in record.items():
            entries.append({"Campo": LABELS.get(column, column.replace("_", " ").capitalize()),
                            "Valor": display_value(value)})
    return pd.DataFrame(entries, columns=["Campo", "Valor"])
