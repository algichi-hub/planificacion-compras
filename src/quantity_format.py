"""Lossless quantity display for Spanish Streamlit tables.

Only display text is changed: PostgreSQL NUMERIC/Decimal source values and
the pandas DataFrame remain numeric and are never rounded or mutated.
"""
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
import pandas as pd

SC_QUANTITY_COLUMNS = ("Sol", "Ped", "Rec", "Apr")


def format_quantity(value):
    """No thousands separator; comma decimal; trim only trailing fractional zeros."""
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, Integral):
        number = Decimal(int(value))
    elif isinstance(value, Real):
        # Decimal(str()) avoids binary float formatting artefacts.
        number = Decimal(str(value))
    else:
        return str(value)
    if not number.is_finite():
        return str(number)
    raw = format(number, "f")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    if raw in ("-0", ""):
        raw = "0"
    return raw.replace(".", ",")


def format_sc_quantities(styler):
    """Apply per-cell formatting without changing quantity dtypes or row order."""
    return styler.format({column: format_quantity for column in SC_QUANTITY_COLUMNS
                          if column in styler.data.columns})
