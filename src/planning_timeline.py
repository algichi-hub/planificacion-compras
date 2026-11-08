"""Read-only, two-band ERP purchase and receipt calendar for each SC position.

The upper band represents purchasing milestones and planned dates. The lower
band represents receipts and snapshot-observed PR approval. ERP has NO dated
quality approval event: do not mislabel receipt_date as actual approval time.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import pandas as pd
import plotly.graph_objects as go

from src.normalize import date_es

SC_ORDER = "#DC2626"
ORDER_ORIGINAL = "#F59E0B"
REPLAN = "#38BDF8"
RECEIPT_WAIT = "#CBD5E1"
RECEIPT_APPROVAL = "#FACC15"
RECEIPT_APPROVED = "#16A34A"
TODAY_LINE = "#D97706"
MISSING = "#64748B"

# Vertical geometry: ~2.3 px between consecutive SC groups with 18 px rows.
ROW_PITCH = 0.55
ROW_HEIGHT_PX = 18
MIN_HEIGHT_PX = 110

# Legacy names kept for imports in independent older reports/tests, if any.
ELAPSED = SC_ORDER
REMAINING = RECEIPT_WAIT
OVERDUE = REPLAN


def as_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date_es(value)
        except ValueError:
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                return None
    return None


def _distinct_day(record, key, count_key):
    count = record.get(count_key)
    try:
        n = int(count) if count is not None and not pd.isna(count) else 0
    except (ValueError, TypeError):
        n = 0
    return (as_day(record.get(key)) if n == 1 else None), n


def _positive_number(value):
    try:
        if value is None or pd.isna(value):
            return None
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def build_timeline(source, today):
    """Build independent upper and lower event bands; disclose uncertain data."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    result = []
    for record in source.to_dict("records"):
        sc = str(record.get("sc_no") or "—")
        pos = record.get("sc_pos")
        position = "—" if pos is None or pd.isna(pos) else str(pos)
        # The axis identifies SC/position; company remains in the source data.
        label = f"{sc}/{position}"
        approval, approval_count = _distinct_day(
            record, "approval_raw", "approval_distinct"
        )
        original, original_count = _distinct_day(
            record, "original_plan_raw", "original_plan_distinct"
        )
        order_approval, order_count = _distinct_day(
            record, "po_approval_raw", "po_approval_distinct"
        )
        plan = as_day(record.get("planned_date"))
        first_receipt = as_day(record.get("first_receipt_date"))
        first_approved_pr = as_day(record.get("first_approved_pr_date"))
        first_approved_qty = _positive_number(record.get("first_approved_pr_qty"))
        requested = _positive_number(record.get("requested_qty"))
        state = record.get("workflow_state", record.get("coverage_state"))
        display_state = record.get("display_state")
        if isinstance(state, str) and state:
            complete = state in ("Completado", "Recepcion completada", "complete")
        else:
            complete = display_state in (
                "Recepcion completada", "Entregado parcial", "Entregado total"
            )
        closure = as_day(record.get("completion_date")) if complete else None
        issues = []
        if approval_count > 1:
            issues.append("Aprobaciones SC diferentes en origen")
        elif approval is None:
            issues.append("Sin fecha de aprobación SC válida")
        if order_count > 1:
            issues.append("Aprobaciones de pedido contradictorias")
        elif order_approval is None:
            issues.append("Sin fecha de aprobación del pedido válida")
        elif approval is not None and (order_approval < approval or order_approval > today):
            issues.append("Aprobación del pedido fuera de secuencia")
        if original_count > 1:
            issues.append("Planes originales contradictorios")
        elif original is None:
            issues.append("Sin plan original válido")
        elif order_approval is not None and original < order_approval:
            issues.append("Plan original anterior a aprobación del pedido")
        if plan is None:
            issues.append("Sin fecha plan actual válida")
        if approval is not None and plan is not None and plan <= approval:
            issues.append("Cronología inconsistente")
        if complete and closure is None:
            issues.append("Sin fecha verificable de recepción completada")
        if complete and closure is not None and (
            closure > today or (approval is not None and closure < approval)
        ):
            issues.append("Fecha de recepción completada inconsistente")
        if first_receipt is not None and (
            first_receipt > today or (approval is not None and first_receipt < approval)
        ):
            issues.append("Primera recepción con fecha inconsistente")
            first_receipt = None
        if first_approved_pr is not None and (
            first_receipt is None or first_approved_pr < first_receipt
            or first_approved_pr > today
            or (closure is not None and first_approved_pr > closure)
        ):
            issues.append("Primer PR aprobado con fecha inconsistente")
            first_approved_pr = None
        if closure is not None and first_receipt is not None and closure < first_receipt:
            issues.append("Cierre anterior a la primera recepción")
            closure = None
        # Never infer actual quality approval dates from the ERP snapshot.
        # The first fully-approved PR uses its recorded receipt_date.
        full_first_pr = (
            first_receipt is not None and first_approved_pr == first_receipt
            and first_approved_qty is not None and requested is not None
            and first_approved_qty >= requested and closure == first_receipt
        )
        # If an ERP-completed position lacks a verifiable close date, stop
        # at the last known receipt milestone; never extend green to today.
        cutoff = (closure if closure is not None else
                  (first_approved_pr or first_receipt or approval)
                  if complete else today)
        span = (plan - approval).days if approval and plan and plan > approval else None
        elapsed = (cutoff - approval).days if span is not None else None
        result.append({
            "label": label, "approval": approval, "po_approval": order_approval,
            "original_plan": original, "plan": plan,
            "first_receipt": first_receipt, "first_approved_pr": first_approved_pr,
            "completion": closure if complete else None, "cutoff": cutoff,
            "first_pr_full_total": full_first_pr, "complete": complete,
            "issues": issues, "issue": issues[0] if issues else None,
            "plan_changed": original != plan if original and plan else None,
            "elapsed_days": max(0, min(span,elapsed)) if span is not None else None,
            "remaining_days": max(0,span-elapsed) if span is not None and not complete
                              else 0 if span is not None else None,
            "overdue_days": max(0,(cutoff-plan).days) if plan and cutoff else None,
            "percent": 100*max(0,elapsed)/span if span is not None else None,
        })
    return result


def _segments(row, today):
    """Yield (band, name, start, finish, color), preserving known milestones."""
    start = row["approval"]
    if start is None:
        return
    order = row["po_approval"]
    original = row["original_plan"]
    plan = row["plan"]
    cutoff = row["cutoff"]
    # Purchasing stage dates belong to the earliest-planned linked PO.
    if order is not None and start <= order <= today:
        if order > start:
            yield ("upper", "SC → Pedido aprobado", start, order, SC_ORDER)
        if original is not None and original >= order:
            if original > order:
                yield ("upper", "Pedido → Plan original", order, original, ORDER_ORIGINAL)
            if plan is not None and plan > original:
                yield ("upper", "Plan original → Plan actual", original, plan, REPLAN)
    received = row["first_receipt"]
    approved = row["first_approved_pr"]
    if received is None:
        if not row["complete"] and cutoff > start:
            yield ("lower", "Hasta primera recepción", start, cutoff, RECEIPT_WAIT)
        return
    if received > start:
        yield ("lower", "Hasta primera recepción", start, received, RECEIPT_WAIT)
    if approved is None:
        if cutoff > received:
            yield ("lower", "Pendiente aprobación PR", received, cutoff, RECEIPT_APPROVAL)
        return
    if approved > received:
        yield ("lower", "Hasta primer PR íntegramente aprobado",
               received, approved, RECEIPT_APPROVAL)
    if cutoff > approved:
        yield ("lower", "Desde primer PR aprobado", approved, cutoff, RECEIPT_APPROVED)


def timeline_figure(rows, today):
    """Exactly two adjacent half-height bands for each SC on one date axis."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    fig = go.Figure()
    traces = {}
    bounds = [today]
    n = len(rows)
    for i, row in enumerate(rows):
        y = ROW_PITCH * (n - i - 1)
        for band, name, left, right, color in _segments(row, today):
            if right <= left:
                continue
            bounds.extend((left,right))
            trace_key = (name, color)
            detail = (
                f"{row['label']}<br>{name}<br>"
                f"Desde: {left:%d/%m/%Y}<br>Hasta: {right:%d/%m/%Y}"
            )
            traces.setdefault(trace_key,[]).append((
                y + (0.13 if band == "upper" else -0.13),
                left.isoformat(),(right-left).days*86400000, detail,
            ))
        if row["approval"]:
            bounds.append(row["approval"])
        if row["plan"]:
            bounds.append(row["plan"])
        # A one-day/full-quantity PR is an instantaneous green middle-thick
        # vertical line rather than a fabricated green-duration interval.
        if row["first_pr_full_total"] and row["first_receipt"] is not None:
            d=row["first_receipt"].isoformat()
            fig.add_trace(go.Scatter(
                x=[d,d], y=[y-0.235,y-0.015], mode="lines",
                line={"width":3.5,"color":RECEIPT_APPROVED},
                name="Aprobación total en primer PR", showlegend=False,
                hovertemplate=(
                    f"{row['label']}<br>Primer PR aprobado totalmente<br>"
                    f"Recepción: {row['first_receipt']:%d/%m/%Y}<extra></extra>"
                ),
            ))
    for (name,color), data in traces.items():
        fig.add_trace(go.Bar(
            y=[v[0] for v in data], x=[v[2] for v in data],
            base=[v[1] for v in data], orientation="h", width=0.22,
            marker={"color":color}, name=name,
            customdata=[v[3] for v in data],
            hovertemplate="%{customdata}<extra></extra>",
        ))
    fig.add_shape(
        type="line",xref="x",yref="paper",
        x0=today.isoformat(),x1=today.isoformat(),y0=0,y1=1,
        line={"color":TODAY_LINE,"width":2,"dash":"dash"},
    )
    fig.add_annotation(
        x=today.isoformat(),y=1.025,xref="x",yref="paper",
        text="Hoy",showarrow=False,font={"color":TODAY_LINE,"size":11},
        yanchor="bottom",
    )
    first=min(bounds)
    last=max(bounds)
    if first == last:
        first=today-timedelta(days=7)
        last=today+timedelta(days=7)
    padding=max(2,(last-first).days//25)
    fig.update_layout(
        barmode="overlay",height=max(MIN_HEIGHT_PX,72+ROW_HEIGHT_PX*n),
        margin={"l":10,"r":20,"t":32,"b":40},
        showlegend=False,
        hovermode="closest",
        xaxis={
            "type":"date","tickformat":"%d/%m/%Y",
            "range":[(first-timedelta(days=padding)).isoformat(),
                     (last+timedelta(days=padding)).isoformat()],
            "showgrid":True,"gridcolor":"rgba(148,163,184,0.18)","title":None,
        },
        yaxis={
            "type":"linear","tickvals":[ROW_PITCH*(n-i-1) for i in range(n)],
            "ticktext":[row["label"] for row in rows],
            "range":[-ROW_PITCH/2,ROW_PITCH*(n-0.5)],
            "automargin":True,"title":None,
            "showgrid":False,"zeroline":False,
        },
    )
    return fig
