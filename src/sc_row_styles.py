"""Color-coded operational SC states, independent from business classification."""

STATE_COLORS = {
    "Completado": "#DCFCE7",                # pastel green
    "Pendiente pedido": "#FEE2E2",          # pastel red
    "Material sin recibir": "#FFEDD5",      # pastel orange
    "Pendiente aprobación": "#FEF9C3",      # pastel yellow
    "Parcialmente aprobadas": "#DBEAFE",    # pastel blue
    "SC anulada": "#F3F4F6",                # light grey
}


def sc_row_style(row):
    """Apply a solid, accessible pastel to every cell of a single SC row.

    Unresolved/unclassified states remain theme-native rather than being
    assigned a potentially misleading status color.
    """
    background = STATE_COLORS.get(row.get("workflow_state"))
    if not background:
        return [""] * len(row)
    return [f"background-color: {background}; color: #111827"] * len(row)
