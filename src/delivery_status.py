"""Snapshot-scoped, conservative PR-to-SC hand-delivery reconciliation.

The manual ledger is global and historical; ERP links must be evaluated against
the selected snapshot. Never assign a PR to two SC positions or duplicate
partial handovers by joining to ERP rows.
"""
from decimal import Decimal, InvalidOperation
import pandas as pd

RECEIPT_COMPLETE = "Recepcion completada"
PARTIAL = "Entregado parcial"
TOTAL = "Entregado total"
COMPLETE_SOURCE = frozenset(("Completado", "Recepcion completada", "complete"))


def _decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        n = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return n if n.is_finite() else None


def present_state(raw_state):
    """Rename the ERP completion label in presentation, never alter snapshots."""
    if raw_state in COMPLETE_SOURCE:
        return RECEIPT_COMPLETE
    return raw_state


def attach_delivery_status(source, receipt_links, ledger):
    """Attach En and derived state to each SC position without mutating inputs.

    PRs with shared PO ownership, reused PR IDs or inconsistent approved
    quantities are not attributed automatically. A full handover is recognized
    only when all approved units match physically delivered units exactly
    AND the ERP receipt itself is complete.
    """
    result = source.copy()
    if result.empty:
        result["hand_qty"] = pd.Series(dtype="object")
        result["display_state"] = pd.Series(dtype="object")
        return result
    raw_states = result["workflow_state"] if "workflow_state" in result else result["coverage_state"]
    result["display_state"] = raw_states.map(present_state)
    result["hand_qty"] = None
    if receipt_links.empty or ledger.empty:
        return result
    required_link_cols={"company","sc_no","sc_pos","receipt_no","approved_qty","owner_count","pr_count"}
    if not required_link_cols.issubset(receipt_links.columns):
        raise ValueError("Columnas incompletas en las asociaciones PR del ERP.")
    if not {"pr_no","quantity"}.issubset(ledger.columns):
        raise ValueError("Columnas incompletas en las entregas manuales.")
    active = ledger.copy()
    if "voided_at" in active.columns:
        active = active.loc[active["voided_at"].isna()]
    totals = {}
    for pr, group in active.groupby("pr_no",sort=False):
        quantities = [_decimal(value) for value in group["quantity"]]
        if all(x is not None and x > 0 for x in quantities):
            totals[str(pr)] = sum(quantities, Decimal(0))
    linked = {}
    for rec in receipt_links.to_dict("records"):
        key=(str(rec["company"]),str(rec["sc_no"]),str(rec["sc_pos"]))
        linked.setdefault(key,[]).append(rec)
    for index, row in result.iterrows():
        if any(pd.isna(row.get(col)) for col in ("company","sc_no","sc_pos")):
            continue
        key=tuple(str(row[col]) for col in ("company","sc_no","sc_pos"))
        receipts=linked.get(key,[])
        if not receipts:
            continue
        # Distinct receipt numbers protect against duplicated joins/ERP events.
        seen=set()
        eligible=[]
        ambiguous=False
        for rec in receipts:
            pr=str(rec["receipt_no"])
            if pr in seen:
                ambiguous=True
                continue
            seen.add(pr)
            if int(rec["owner_count"])!=1 or int(rec["pr_count"])!=1:
                ambiguous=True
                continue
            eligible.append(rec)
        total_manual=sum((totals.get(str(rec["receipt_no"]),Decimal(0))
                          for rec in eligible),Decimal(0))
        if total_manual>0:
            result.at[index,"hand_qty"]=total_manual
        state=result.at[index,"display_state"]
        if state != RECEIPT_COMPLETE or ambiguous or total_manual<=0:
            continue
        approved=_decimal(row.get("approved_qty"))
        if approved is None or approved<=0:
            continue
        expected=sum((_decimal(rec["approved_qty"]) or Decimal(0)
                      for rec in eligible),Decimal(0))
        if expected != approved:
            continue
        # Excess against any individual PR is an anomaly, not a completed handover.
        if any(totals.get(str(rec["receipt_no"]),Decimal(0)) >
               (_decimal(rec["approved_qty"]) or Decimal(0)) for rec in eligible):
            continue
        if total_manual == approved:
            result.at[index,"display_state"]=TOTAL
        elif total_manual < approved:
            result.at[index,"display_state"]=PARTIAL
    return result
