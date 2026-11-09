"""SC planning: one date-based bar with raw ERP receipt milestones.

Only ERP received quantities determine the delivery milestones. A PR approval
state is not a dated quality event and must never influence the green marker.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json

import pandas as pd
import plotly.graph_objects as go

from src.normalize import date_es

SC_ORDER = "#DC2626"
ORDER_ORIGINAL = "#F59E0B"
REPLAN = "#F9A8D4"  # Pink pastel: planned-date extension
RECEIPT_WAIT = "#CBD5E1"
PARTIAL_PR = "#2563EB"  # Primary blue
COMPLETE_PR = "#16A34A"
TODAY_LINE = "#475569"
MISSING = "#64748B"

# Retained public aliases; no other chart's styling is changed.
ELAPSED = SC_ORDER
REMAINING = RECEIPT_WAIT
OVERDUE = REPLAN
RECEIPT_APPROVAL = PARTIAL_PR
RECEIPT_APPROVED = COMPLETE_PR

# Preserve previous compact group pitch and fixed date-chart behaviour.
ROW_PITCH = 0.55
ROW_HEIGHT_PX = 18
MIN_HEIGHT_PX = 110
BAR_WIDTH = 0.47


def as_day(value):
    """Interpret raw ERP DD/MM/YY dates and PostgreSQL/Pandas date values."""
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


def _raw_events(value):
    """Neon jsonb maps to Python lists; tolerate serialized JSON in tests."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    return value if isinstance(value, list) else []


def receipt_milestones(raw_events, today):
    """Return dated PR milestones, and close only if *all* linked POs filled.

    Compare each PR against its OWN ordered PO-position quantity, never the
    total requested SC quantity. Collate multiple PR on the same date to avoid
    overlapping vertical markers. Unverified or malformed PO data prevent a
    guessed green completion.
    """
    pos = {}
    issues = []
    for event in _raw_events(raw_events):
        if not isinstance(event, dict):
            issues.append("Movimiento PR inválido")
            continue
        no, line = event.get("po_no"), event.get("po_pos")
        if no is None or line is None:
            issues.append("Pedido/posición sin identificar")
            continue
        key = (str(no), str(line))
        qty = _positive_number(event.get("po_qty"))
        verified = event.get("allocation_status") == "verified"
        if key not in pos:
            pos[key] = {"qty": qty, "verified": verified, "receipts": []}
        elif pos[key]["qty"] != qty:
            issues.append("Cantidad de pedido contradictoria")
            pos[key]["qty"] = None
        if not verified:
            pos[key]["verified"] = False
        pr = event.get("pr_no")
        if pr is None:
            continue  # An ordered PO with no receipts must count as open.
        day = as_day(event.get("pr_date"))
        received = _positive_number(event.get("delivered_qty"))
        if day is None or day > today or received is None:
            issues.append("PR con fecha o cantidad de recepción inválida")
            pos[key]["verified"] = False
            continue
        pos[key]["receipts"].append({
            "date": day, "pr": str(pr), "qty": received,
            "source_line": event.get("source_line") or 0,
        })
    if not pos:
        return [], None, issues

    # Accumulate independently per PO. The same PR can be represented by
    # distinct source rows; each receipt event contributes its delivered qty.
    all_receipts = defaultdict(list)
    po_closures = []
    safe = True
    for key, item in pos.items():
        target = item["qty"]
        if target is None or not item["verified"]:
            safe = False
            issues.append("Línea de pedido sin cantidad o enlace verificable")
        ordered = sorted(item["receipts"],key=lambda r: (
            r["date"],r["source_line"],r["pr"]
        ))
        accumulated = Decimal(0)
        closed_at = None
        for r in ordered:
            accumulated += r["qty"]
            all_receipts[r["date"]].append({
                "po": f"{key[0]}/{key[1]}", "pr": r["pr"],
                "qty": r["qty"], "accumulated": accumulated, "target": target,
            })
            if closed_at is None and target is not None and accumulated >= target:
                closed_at = r["date"]
        if closed_at is None:
            safe = False
        else:
            po_closures.append(closed_at)

    complete_at = max(po_closures) if safe and len(po_closures)==len(pos) else None
    milestones = []
    for day, entries in sorted(all_receipts.items()):
        # Only the day at which the last PO reaches its full quantity is green.
        is_final = complete_at is not None and day == complete_at
        milestones.append({
            "date": day, "complete": is_final, "entries": entries,
        })
    return milestones, complete_at, list(dict.fromkeys(issues))


def build_timeline(source, today):
    """One row per SC/position, preserving ordered ERP evidence and warnings."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    result = []
    for record in source.to_dict("records"):
        sc = str(record.get("sc_no") or "—")
        p = record.get("sc_pos")
        label = f"{sc}/{'—' if p is None or pd.isna(p) else p}"
        approval, approval_count = _distinct_day(
            record,"approval_raw","approval_distinct"
        )
        original, original_count = _distinct_day(
            record,"original_plan_raw","original_plan_distinct"
        )
        order, order_count = _distinct_day(
            record,"po_approval_raw","po_approval_distinct"
        )
        plan = as_day(record.get("planned_date"))
        milestones, complete_at, problems = receipt_milestones(
            record.get("receipt_events"), today
        )
        issues = []
        if approval_count > 1:
            issues.append("Aprobaciones SC diferentes en origen")
        elif approval is None:
            issues.append("Sin fecha de aprobación SC válida")
        if order_count > 1:
            issues.append("Aprobaciones de pedido contradictorias")
        elif order is None:
            issues.append("Sin fecha de aprobación del pedido válida")
        elif approval and (order < approval or order > today):
            issues.append("Aprobación del pedido fuera de secuencia")
        if original_count > 1:
            issues.append("Planes originales contradictorios")
        elif original is None:
            issues.append("Sin plan original válido")
        elif order and original < order:
            issues.append("Plan original anterior a aprobación del pedido")
        if plan is None:
            issues.append("Sin fecha plan actual válida")
        elif approval and plan <= approval:
            issues.append("Cronología inconsistente")
        issues.extend(problems)
        # Never construct a closure from approved_qty or manually entered data.
        cutoff = complete_at if complete_at is not None else today
        span = (plan-approval).days if plan and approval and plan>approval else None
        elapsed = (cutoff-approval).days if span is not None else None
        result.append({
            "label":label,"approval":approval,"po_approval":order,
            "original_plan":original,"plan":plan,"milestones":milestones,
            "completion":complete_at,"cutoff":cutoff,
            "plan_changed":original != plan if original and plan else None,
            "issues":issues,"issue":issues[0] if issues else None,
            "elapsed_days":max(0,min(span,elapsed)) if span is not None else None,
            "remaining_days":max(0,span-elapsed) if span is not None
                             and complete_at is None else 0 if span is not None else None,
            "overdue_days":max(0,(cutoff-plan).days) if plan else None,
            "percent":100*max(0,elapsed)/span if span is not None else None,
        })
    return result


def _segments(row, today):
    """One bar, nonoverlapping dated segments and no invented intervals."""
    start = row["approval"]
    if start is None:
        return
    order, original, plan = row["po_approval"],row["original_plan"],row["plan"]
    if order is not None and start <= order <= today:
        if order>start:
            yield ("SC → Pedido aprobado",start,order,SC_ORDER)
        if original is not None and original>=order:
            if original>order:
                yield ("Pedido → Plan original",order,original,ORDER_ORIGINAL)
            if plan is not None and plan>original:
                yield ("Plan original → Plan actual",original,plan,REPLAN)
    # Grey is a single background, reaching only the last required PR if
    # delivered, or today for a still-open PO. Do not paint backwards in time.
    if plan is not None:
        # When the plan moves earlier, the orange original-plan segment stays
        # visible. Begin grey after that segment, never paint over orange.
        grey_start = plan
        # Plotly overlay draws grey after red/orange/pink. Never start grey
        # before the right edge of an existing purchasing segment, otherwise
        # it visually hides real SC-to-PO days (e.g. SC 761488: 01-14 Oct).
        if order is not None and start <= order <= today:
            grey_start = max(grey_start, order)
            if original is not None and original >= order:
                grey_start = max(grey_start, original)
        end = row["completion"] or today
        if end > grey_start:
            yield ("Pendiente de recepción",grey_start,end,RECEIPT_WAIT)


def _milestone_hover(row, marker):
    details = [
        f"{row['label']}<br>",
        f"{'Recepción completa' if marker['complete'] else 'Recepción parcial'}"
        f" · {marker['date']:%d/%m/%Y}<br>",
    ]
    for item in marker["entries"]:
        target = item["target"]
        suffix = f" / {target}" if target is not None else " / sin cantidad válida"
        details.append(
            f"Pedido/Pos {item['po']} · PR {item['pr']}: "
            f"recibido {item['qty']}, acumulado {item['accumulated']}{suffix}<br>"
        )
    return "".join(details)


def timeline_figure(rows, today):
    """Fixed Plotly single-band timeline; primary-blue partial and green final PR."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    fig=go.Figure()
    traces=defaultdict(list)
    marker_traces={False:{"x":[],"y":[],"tip":[]},
                   True:{"x":[],"y":[],"tip":[]}}
    dates=[today]
    n=len(rows)
    for i,row in enumerate(rows):
        y=ROW_PITCH*(n-i-1)
        for name,left,right,color in _segments(row,today):
            if right<=left:
                continue
            dates.extend((left,right))
            hover=(f"{row['label']}<br>{name}<br>"
                   f"Desde: {left:%d/%m/%Y}<br>Hasta: {right:%d/%m/%Y}")
            traces[(name,color)].append((
                y,left.isoformat(),(right-left).days*86400000,hover
            ))
        for marker in row.get("milestones",[]):
            day=marker["date"]
            if row.get("approval") and day<row["approval"]:
                # Keep original PR date in the record; do not depict an
                # impossible receipt before SC approval.
                continue
            dates.append(day)
            category=marker["complete"]
            d=marker_traces[category]
            tooltip=_milestone_hover(row,marker)
            d["x"].extend((day.isoformat(),day.isoformat(),None))
            d["y"].extend((y-BAR_WIDTH/2,y+BAR_WIDTH/2,None))
            d["tip"].extend((tooltip,tooltip,None))
        if row["approval"]:
            dates.append(row["approval"])
        if row["plan"]:
            dates.append(row["plan"])

    for (name,color),values in traces.items():
        fig.add_trace(go.Bar(
            y=[v[0] for v in values],x=[v[2] for v in values],
            base=[v[1] for v in values],orientation="h",width=BAR_WIDTH,
            marker={"color":color},name=name,
            customdata=[v[3] for v in values],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        ))
    for is_final,color,title in (
        (False,PARTIAL_PR,"Recepción parcial"),
        (True,COMPLETE_PR,"Recepción completa"),
    ):
        values=marker_traces[is_final]
        if not values["x"]:
            continue
        fig.add_trace(go.Scatter(
            x=values["x"],y=values["y"],mode="lines",
            line={"color":color,"width":4},
            name=title,showlegend=False,connectgaps=False,
            customdata=values["tip"],
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
    left=min(dates)
    right=max(dates)
    if left==right:
        left=today-timedelta(days=7)
        right=today+timedelta(days=7)
    pad=max(2,(right-left).days//25)
    fig.update_layout(
        barmode="overlay",height=max(MIN_HEIGHT_PX+42,114+ROW_HEIGHT_PX*n),
        margin={"l":10,"r":20,"t":32,"b":82},
        showlegend=False,hovermode="closest",
        dragmode=False,
        xaxis={
            "type":"date","tickformat":"%d/%m","tickangle":0,"fixedrange":True,
            "range":[(left-timedelta(days=pad)).isoformat(),
                     (right+timedelta(days=pad)).isoformat()],
            "showgrid":True,"gridcolor":"rgba(148,163,184,0.18)",
            "title":None,
        },
        yaxis={
            "type":"linear","fixedrange":True,
            "tickvals":[ROW_PITCH*(n-i-1) for i in range(n)],
            "ticktext":[row["label"] for row in rows],
            "range":[-ROW_PITCH/2,ROW_PITCH*(n-0.5)],
            "automargin":True,"title":None,"showgrid":False,"zeroline":False,
        },
    )
    return fig
