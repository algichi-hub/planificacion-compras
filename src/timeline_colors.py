"""Versioned default palette shared by all procurement timelines.

Add future schemes here; the renderer only imports the active palette.
"""
DEFAULT_TIMELINE_PALETTE = "compras_pastel_v1"
TIMELINE_PALETTES = {
    "compras_pastel_v1": {
        "sc_order": "#FAD4CF",
        "order_original": "#E9E1D8",
        "replan": "#FAD4CF",
        "receipt_wait": "#E9ECEF",
        "partial_pr": "#93C5FD",
        "complete_pr": "#005CFF",
        "approval_pr": "#FFFF00",
        "partial_handover": "#86D76B",
        "complete_handover": "#008000",
        "today_line": "#475569",
    }
}
DEFAULT_COLORS = TIMELINE_PALETTES[DEFAULT_TIMELINE_PALETTE]
