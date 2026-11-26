"""Unified text-only planned-date traffic light for unreceived SC materials."""

from datetime import datetime


def planned_date_style(value, today, state):
    """Red overdue, yellow today through 7 calendar days, green from day 8."""
    if state != "Material sin recibir":
        return ""
    try:
        planned = datetime.strptime(str(value), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return ""
    remaining = (planned - today).days
    if remaining < 0:
        color = "#B91C1C"
    elif remaining <= 7:
        color = "#CA8A04"
    else:
        color = "#15803D"
    return f"color: {color}; font-weight: bold"
