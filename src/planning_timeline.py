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

from src.timeline_colors import DEFAULT_COLORS

SC_ORDER = DEFAULT_COLORS["sc_order"]
ORDER_ORIGINAL = DEFAULT_COLORS["order_original"]
REPLAN = DEFAULT_COLORS["replan"]
RECEIPT_WAIT = DEFAULT_COLORS["receipt_wait"]
PARTIAL_PR = DEFAULT_COLORS["partial_pr"]
COMPLETE_PR = DEFAULT_COLORS["complete_pr"]
APPROVAL_PR = DEFAULT_COLORS["approval_pr"]
PARTIAL_HANDOVER = DEFAULT_COLORS["partial_handover"]
COMPLETE_HANDOVER = DEFAULT_COLORS["complete_handover"]
TODAY_LINE = DEFAULT_COLORS["today_line"]
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



def approval_milestones(raw_events, today):
    """Verified auxiliary dates per PR; never imply an approved quantity.

    One milestone per day, collecting partial and total PR approvals without
    multiplying source receipt rows or changing ERP completion logic.
    """
    by_day = defaultdict(list)
    seen = set()
    for event in _raw_events(raw_events):
        if not isinstance(event, dict) or event.get("pr_no") is None:
            continue
        day = as_day(event.get("pr_approval_date"))
        received = as_day(event.get("pr_date"))
        if (day is None or day > today or received is None
                or day < received or event.get("allocation_status") != "verified"):
            continue
        key = (str(event.get("pr_no")), str(event.get("po_no")),
               str(event.get("po_pos")))
        if key in seen:
            continue
        seen.add(key)
        by_day[day].append({"pr": key[0], "po": f"{key[1]}/{key[2]}",
                            "receipt_date": received})
    return [{"date": day, "entries": entries}
            for day, entries in sorted(by_day.items())]


def physical_milestones(record, ledger, receipt_links, today, erp_complete):
    """Dated physical events for unambiguous, approved ERP PRs of this SC.

    A full marker requires the already-validated Manage PR display state,
    unique PR ownership, per-PR approved quantities, and ERP full receipt.
    Never infer handovers from a snapshot or treat a PR from another SC as ours.
    """
    if ledger is None or receipt_links is None or ledger.empty or receipt_links.empty:
        return [], None, []
    key = tuple(str(record.get(field)) for field in ("company", "sc_no", "sc_pos"))
    local = [
        link for link in receipt_links.to_dict("records")
        if tuple(str(link.get(field)) for field in ("company", "sc_no", "sc_pos")) == key
    ]
    if not local:
        return [], None, []
    issues = []
    raw_by_pr = defaultdict(list)
    for item in _raw_events(record.get("receipt_events")):
        if isinstance(item, dict) and item.get("pr_no") is not None:
            raw_by_pr[str(item["pr_no"])].append(item)
    approved_by_pr = {}
    ambiguous_pr = set()
    for link in local:
        pr = str(link["receipt_no"])
        approved = _positive_number(link.get("approved_qty"))
        raw = raw_by_pr.get(pr, [])
        try:
            unique = int(link["owner_count"]) == 1 and int(link["pr_count"]) == 1
        except (ValueError, TypeError):
            unique = False
        received_day = as_day(raw[0].get("pr_date")) if len(raw) == 1 else None
        if pr in approved_by_pr or not unique or approved is None or received_day is None:
            issues.append(f"PR {pr} sin atribución o aprobación verificable")
            ambiguous_pr.add(pr)
            continue
        approved_by_pr[pr] = (approved, received_day)
    for pr in ambiguous_pr:
        approved_by_pr.pop(pr, None)
    if not approved_by_pr:
        return [], None, list(dict.fromkeys(issues))
    if len(approved_by_pr) != len(local):
        issues.append("No todos los PR están conciliados inequívocamente")

    events = defaultdict(list)
    delivered_by_pr = defaultdict(lambda: Decimal(0))
    invalid = False
    for hand in ledger.to_dict("records"):
        pr = str(hand.get("pr_no"))
        if pr not in approved_by_pr:
            continue
        voided = hand.get("voided_at")
        if voided is not None and not pd.isna(voided):
            continue
        day = as_day(hand.get("delivery_date"))
        qty = _positive_number(hand.get("quantity"))
        approved, received_day = approved_by_pr[pr]
        if day is None or day > today or day < received_day or qty is None:
            issues.append(f"Entrega física del PR {pr} con fecha o cantidad inconsistente")
            invalid = True
            continue
        if delivered_by_pr[pr] + qty > approved:
            issues.append(f"Entrega del PR {pr} excede cantidad aprobada")
            invalid = True
            continue
        delivered_by_pr[pr] += qty
        events[day].append({
            "pr": pr, "qty": qty, "nbi": hand.get("received_by_nbi"),
            "approved": approved, "id": hand.get("id"),
        })

    full_day = None
    expected = _positive_number(record.get("approved_qty"))
    state = record.get("display_state")
    if (not invalid and len(approved_by_pr) == len(local)
            and erp_complete is not None and state == "Entregado total"
            and expected is not None
            and sum((v[0] for v in approved_by_pr.values()), Decimal(0)) == expected
            and all(delivered_by_pr[pr] == approved
                    for pr, (approved, _) in approved_by_pr.items())
            and events):
        candidate = max(events)
        if candidate >= erp_complete:
            full_day = candidate
        else:
            issues.append("Entrega total anterior a recepción ERP completa")

    milestones = []
    for day, entries in sorted(events.items()):
        milestones.append({
            "date": day, "complete": full_day == day, "entries": entries,
        })
    return milestones, full_day, list(dict.fromkeys(issues))


def build_timeline(source, today, ledger=None, receipt_links=None):
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
        approval_marks = approval_milestones(record.get("receipt_events"), today)
        hand_milestones, hand_complete, hand_issues = physical_milestones(
            record, ledger, receipt_links, today, complete_at
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
        issues.extend(hand_issues)
        # Only fully reconciled physical delivery closes the grey follow-up.
        cutoff = hand_complete if hand_complete is not None else today
        span = (plan-approval).days if plan and approval and plan>approval else None
        elapsed = (cutoff-approval).days if span is not None else None
        result.append({
            "label":label,"approval":approval,"po_approval":order,
            "original_plan":original,"plan":plan,"milestones":milestones,
            "physical_milestones":hand_milestones,
            "approval_milestones":approval_marks,
            "completion":complete_at,"handover_completion":hand_complete,
            "cutoff":cutoff,
            "plan_changed":original != plan if original and plan else None,
            "issues":issues,"issue":issues[0] if issues else None,
            "elapsed_days":max(0,min(span,elapsed)) if span is not None else None,
            "remaining_days":max(0,span-elapsed) if span is not None
                             and hand_complete is None else 0 if span is not None else None,
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
    # Grey closes only on verified physical handover, otherwise at today.
    # Do not paint backwards in time.
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
        end = row["handover_completion"] or today
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


def _handover_hover(row, marker):
    details = [
        f"{row['label']}<br>",
        f"{'Entrega física total' if marker['complete'] else 'Entrega física parcial'}"
        f" · {marker['date']:%d/%m/%Y}<br>",
    ]
    for item in marker["entries"]:
        nbi = f" · NBI {item['nbi']}" if item.get("nbi") else ""
        details.append(
            f"PR {item['pr']}: entrega {item['qty']} / "
            f"aprobado {item['approved']}{nbi}<br>"
        )
    return "".join(details)



def _approval_hover(row, marker):
    details = [f"{row['label']}<br>Aprobación PR · {marker['date']:%d/%m/%Y}<br>"]
    for item in marker["entries"]:
        details.append(
            f"Pedido/Pos {item['po']} · PR {item['pr']}"
            f" · recepción {item['receipt_date']:%d/%m/%Y}<br>"
        )
    return "".join(details)


def timeline_figure(rows, today):
    """Fixed single-band timeline; deduplicate same-day ERP and handover markers."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    fig=go.Figure()
    traces=defaultdict(list)
    kinds=(
        ("Recepción parcial",PARTIAL_PR),
        ("Recepción completa",COMPLETE_PR),
        ("Aprobación PR",APPROVAL_PR),
        ("Entrega física parcial",PARTIAL_HANDOVER),
        ("Entrega física total",COMPLETE_HANDOVER),
    )
    marker_traces={
        name: {"x":[],"y":[],"tip":[]} for name,_ in kinds
    }
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
        # Group all same-day ERP and physical movements into a single hito.
        # The visible color is the most advanced stage; hover retains all.
        dated = defaultdict(list)
        for marker in row.get("milestones",[]):
            name = "Recepción completa" if marker["complete"] else "Recepción parcial"
            dated[marker["date"]].append((name,_milestone_hover(row,marker)))
        for marker in row.get("physical_milestones",[]):
            name = "Entrega física total" if marker["complete"] else "Entrega física parcial"
            dated[marker["date"]].append((name,_handover_hover(row,marker)))
        for marker in row.get("approval_milestones",[]):
            dated[marker["date"]].append(("Aprobación PR",_approval_hover(row,marker)))
        priority = {name: i for i,(name,_) in enumerate(kinds)}
        for day,events in sorted(dated.items()):
            if row.get("approval") and day < row["approval"]:
                continue
            dates.append(day)
            primary_events = [e for e in events if e[0] != "Aprobación PR"]
            approval_events = [e for e in events if e[0] == "Aprobación PR"]
            tooltip = "<br><br>".join(text for _,text in sorted(
                events,key=lambda e:priority[e[0]]
            ))
            if primary_events:
                visible = max(primary_events,key=lambda e:priority[e[0]])[0]
                d=marker_traces[visible]
                d["x"].extend((day.isoformat(),day.isoformat(),None))
                d["y"].extend((y-BAR_WIDTH/2,y+BAR_WIDTH/2,None))
                d["tip"].extend((tooltip,tooltip,None))
            if approval_events:
                # On coincident dates, yellow occupies only the upper half:
                # existing blue/purple ERP/handover line remains visible below.
                d=marker_traces["Aprobación PR"]
                d["x"].extend((day.isoformat(),day.isoformat(),None))
                d["y"].extend((y if primary_events else y-BAR_WIDTH/2,
                               y+BAR_WIDTH/2,None))
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
    for title,color in kinds:
        values=marker_traces[title]
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
