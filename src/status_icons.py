"""Material-style outlined status symbols for native Streamlit ImageColumn.

SVG data URIs need no external fonts, network calls or unsafe HTML.
"""
from urllib.parse import quote

PATHS = {
    "check_circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6L16.5 9"/>',
    "shopping_cart": '<circle cx="9" cy="20" r="1"/><circle cx="19" cy="20" r="1"/><path d="M2.5 4H5l2.2 11h12.2l2-8H6"/>',
    "inventory_2": '<path d="M4 9h16v12H4zM3 4h18v5H3zM10 13h4"/>',
    "pending": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "pie_chart": '<path d="M11 3a9 9 0 1 0 10 10h-10zM14 3v7h7a9 9 0 0 0-7-7z"/>',
    "cancel": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.4 9a2.8 2.8 0 1 1 4.5 2.2c-1.3.9-1.9 1.3-1.9 2.8M12 17h.01"/>',
}
STATUS_SYMBOLS = {
    "Completado": ("check_circle", "#15803D"),
    "Pendiente pedido": ("shopping_cart", "#B91C1C"),
    "Material sin recibir": ("inventory_2", "#C2410C"),
    "Pendiente aprobación": ("pending", "#A16207"),
    "Parcialmente aprobadas": ("pie_chart", "#2563EB"),
    "SC anulada": ("cancel", "#6B7280"),
    "Pendiente conciliación": ("help", "#6B7280"),
    "complete": ("check_circle", "#15803D"),
    "partial": ("pie_chart", "#2563EB"),
    "no_approved_coverage": ("pending", "#A16207"),
    "pending_reconciliation": ("help", "#6B7280"),
}


def status_icon(state):
    """Encode outlined status icon as inline SVG URL, or None if unknown."""
    if not isinstance(state, str) or state not in STATUS_SYMBOLS:
        return None
    name, color = STATUS_SYMBOLS[state]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="24" height="24" fill="none" stroke="{color}" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f'{PATHS[name]}</svg>'
    )
    return "data:image/svg+xml;utf8," + quote(svg, safe="")
