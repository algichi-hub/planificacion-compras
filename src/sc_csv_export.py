"""Spanish Excel-compatible CSV for the shared SC position overviews.

Export only visible business fields, not the SVG data-URI status icon.
Preserve Decimal source values, row order and textual identifiers.
"""
import csv
from io import StringIO

import pandas as pd

from src.quantity_format import SC_QUANTITY_COLUMNS, format_quantity


def sc_overview_csv(view):
    """Return UTF-8 BOM CSV bytes; one cell per displayed business column."""
    columns = [name for name in view.columns if name != " "]
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", quotechar='"', lineterminator="\r\n")
    writer.writerow(columns)
    for values in view.loc[:, columns].itertuples(index=False, name=None):
        row = []
        for col, value in zip(columns, values):
            if col in SC_QUANTITY_COLUMNS:
                row.append(format_quantity(value))
            elif value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                row.append("—")
            else:
                value = str(value)
                # Prevent untrusted ERP descriptions from executing as formulas
                # when the CSV is opened directly in Excel.
                if value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                row.append(value)
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")
