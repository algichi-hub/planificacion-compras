"""Pure multi-identifier search helpers; no Neon reads."""
import pandas as pd

from src.pr_lookup import resolve_pr


def parse_identifiers(text, limit=50):
    """Validate exact numeric identifiers, retaining order and leading zeroes."""
    parts = [part.strip() for part in text.split(";")]
    if not text.strip() or any(not part or not part.isascii() or not part.isdigit()
                               or len(part)>30 for part in parts):
        raise ValueError("Introduce números válidos separados por ; (sin elementos vacíos).")
    unique = tuple(dict.fromkeys(parts))
    if len(unique)>limit:
        raise ValueError(f"Máximo {limit} identificadores distintos por consulta.")
    return unique


def ordered_sc_rows(rows, identifiers):
    """Order SC positions by user input without touching original SQL quantities."""
    if rows.empty:
        return rows
    rank = {value: idx for idx,value in enumerate(identifiers)}
    return rows.iloc[sorted(range(len(rows)),key=lambda i: rank[str(rows.iloc[i]["sc_no"])])].reset_index(drop=True)


def resolve_pr_batch(identifiers, relations):
    """Reuse strict single-PR verification; return ordered owners and diagnostics."""
    grouped = {}
    for relation in relations:
        grouped.setdefault(str(relation["receipt_no"]),[]).append(relation)
    owners, issues = [], []
    for pr in identifiers:
        row, issue = resolve_pr(grouped.get(pr,[]))
        if issue:
            issues.append(f"PR {pr}: {issue}")
        else:
            owners.append({"PR":pr,"company":str(row["company"]),
                           "sc_no":str(row["sc_no"]),"sc_pos":str(row["sc_pos"])})
    return owners, issues


def matched_pr_positions(owners, positions):
    """One row per requested verified PR/SC position, including repeated SC rows."""
    if not owners or positions.empty:
        return positions.iloc[:0].copy()
    keys = ("company","sc_no","sc_pos")
    matches = pd.DataFrame(owners)
    return matches.merge(positions,on=list(keys),how="inner",sort=False,
                         validate="many_to_one").reset_index(drop=True)
