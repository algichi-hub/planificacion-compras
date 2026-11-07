"""Official Google Material Symbols Outlined glyphs for Streamlit ImageColumn.

Source: google/material-design-icons (Apache License 2.0).
SVG data URIs need no external fonts, network calls or unsafe HTML.
"""
from urllib.parse import quote

PATHS = {
    "check_circle": "m424-296 282-282-56-56-226 226-114-114-56 56 170 170Zm56 216q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z",
    "note_stack": "M280-160v-441q0-33 24-56t57-23h439q33 0 56.5 23.5T880-600v320L680-80H360q-33 0-56.5-23.5T280-160ZM81-710q-6-33 13-59.5t52-32.5l434-77q33-6 59.5 13t32.5 52l10 54h-82l-7-40-433 77 40 226v279q-16-9-27.5-24T158-276L81-710Zm279 110v440h280v-160h160v-280H360Zm220 220Z",
    "package_2": "M440-183v-274L200-596v274l240 139Zm80 0 240-139v-274L520-457v274Zm-80 92L160-252q-19-11-29.5-29T120-321v-318q0-22 10.5-40t29.5-29l280-161q19-11 40-11t40 11l280 161q19 11 29.5 29t10.5 40v318q0 22-10.5 40T800-252L520-91q-19 11-40 11t-40-11Zm200-528 77-44-237-137-78 45 238 136Zm-160 93 78-45-237-137-78 45 237 137Z",
    "search": "M784-120 532-372q-30 24-69 38t-83 14q-109 0-184.5-75.5T120-580q0-109 75.5-184.5T380-840q109 0 184.5 75.5T640-580q0 44-14 83t-38 69l252 252-56 56ZM380-400q75 0 127.5-52.5T560-580q0-75-52.5-127.5T380-760q-75 0-127.5 52.5T200-580q0 75 52.5 127.5T380-400Z",
    "clock_loader_10": "M480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-64-24-123t-69-104L480-480v-320q-134 0-227 93t-93 227q0 134 93 227t227 93Z",
    "close": "m256-200-56-56 224-224-224-224 56-56 224 224 224-224 56 56-224 224 224 224-56 56-224-224-224 224Z",
    "gpp_maybe": "M480-320q17 0 28.5-11.5T520-360q0-17-11.5-28.5T480-400q-17 0-28.5 11.5T440-360q0 17 11.5 28.5T480-320Zm-40-160h80v-200h-80v200Zm40 400q-139-35-229.5-159.5T160-516v-244l320-120 320 120v244q0 152-90.5 276.5T480-80Zm0-84q104-33 172-132t68-220v-189l-240-90-240 90v189q0 121 68 220t172 132Zm0-316Z",
}
STATUS_SYMBOLS = {
    "Completado": ("check_circle", "#15803D"),
    "Pendiente pedido": ("note_stack", "#B91C1C"),
    "Material sin recibir": ("package_2", "#EA580C"),
    "Pendiente aprobación": ("search", "#EAB308"),
    "Parcialmente aprobadas": ("clock_loader_10", "#2563EB"),
    "SC anulada": ("close", "#6B7280"),
    "Pendiente conciliación": ("gpp_maybe", "#6B7280"),
    "complete": ("check_circle", "#15803D"),
    "partial": ("clock_loader_10", "#2563EB"),
    "no_approved_coverage": ("search", "#EAB308"),
    "pending_reconciliation": ("gpp_maybe", "#6B7280"),
}

def status_icon(state):
    """Encode outlined status icon as inline SVG URL, or None if unknown."""
    if not isinstance(state, str) or state not in STATUS_SYMBOLS:
        return None
    name, color = STATUS_SYMBOLS[state]
    # Keep an enlarged viewBox to preserve 30% visual padding even when
    # Streamlit scales the SVG image to fill the grid cell.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-206 -1166 1372 1372" '
        f'width="24" height="24" fill="{color}">'
        f'<path d="{PATHS[name]}"/></svg>'
    )
    return "data:image/svg+xml;utf8," + quote(svg, safe="")
