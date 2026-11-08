"""Read-only, snapshot-specific planning timeline for SC positions.

Bars represent elapsed calendar time, remaining scheduled time and overdue
calendar time, not physical delivery quantities. The first verified ERP
receipt-completion date stops the timeline, with no post-close fill.
"""
from datetime import date, datetime, timedelta
import pandas as pd
import plotly.graph_objects as go

from src.normalize import date_es

ELAPSED = "#3B82F6"
REMAINING = "#CBD5E1"
OVERDUE = "#DC2626"
TODAY_LINE = "#D97706"
MISSING = "#64748B"


def as_day(value):
    """Date only; reject malformed or out-of-domain source values."""
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


def build_timeline(source, today):
    """One position per row, preserving source order and stating date anomalies.

    approval_distinct comes from a per-position aggregate on the approved
    least-privilege source view. Never select among conflicting source dates.
    """
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    result = []
    for record in source.to_dict("records"):
        sc = str(record.get("sc_no") or "—")
        pos = record.get("sc_pos")
        position = "—" if pos is None or pd.isna(pos) else str(pos)
        company = record.get("company")
        company = "" if company is None or pd.isna(company) else str(company)
        label = f"{sc}/{position}" + (f" · {company}" if company else "")
        distinct = record.get("approval_distinct")
        try:
            distinct = int(distinct) if distinct is not None and not pd.isna(distinct) else 0
        except (TypeError, ValueError):
            distinct = 0
        approval = as_day(record.get("approval_raw")) if distinct == 1 else None
        plan = as_day(record.get("planned_date"))
        issue = None
        if distinct > 1:
            issue = "Aprobaciones SC diferentes en origen"
        elif approval is None:
            issue = "Sin fecha de aprobación SC válida"
        elif plan is None:
            issue = "Sin fecha plan actual válida"
        elif plan <= approval:
            issue = "Cronología inconsistente"
        original_distinct = record.get("original_plan_distinct")
        try:
            original_distinct = (int(original_distinct)
                                 if original_distinct is not None and not pd.isna(original_distinct)
                                 else 0)
        except (TypeError, ValueError):
            original_distinct = 0
        original_plan = (as_day(record.get("original_plan_raw"))
                         if original_distinct == 1 else None)
        # Unknown/contradictory original plans must not be mistaken for "No".
        plan_changed = (original_plan != plan
                        if original_plan is not None and plan is not None else None)
        # The delivery-in-hand status is never a closure milestone; only ERP.
        source_state = record.get("workflow_state",record.get("coverage_state"))
        visual_state = record.get("display_state")
        # The authoritative ERP workflow takes precedence over the display
        # state (which may include manually derived physical handovers).
        if isinstance(source_state,str) and source_state:
            completed = source_state in ("Completado","Recepcion completada","complete")
        else:
            completed = visual_state in (
                "Recepcion completada","Entregado parcial","Entregado total"
            )
        closure = as_day(record.get("completion_date")) if completed else None
        if issue is None and completed:
            if closure is None:
                issue = "Sin fecha verificable de recepción completada"
            elif closure < approval or closure > today:
                issue = "Fecha de recepción completada inconsistente"
        cutoff = closure if completed and issue is None else today
        span = (plan - approval).days if issue is None else None
        elapsed = (cutoff - approval).days if issue is None else None
        bounded_elapsed = max(0, min(span, elapsed)) if issue is None else None
        row = {
            "label": label, "approval": approval, "plan": plan,
            "completion": closure if completed and issue is None else None,
            "cutoff": cutoff if issue is None else None,
            "original_plan": original_plan, "plan_changed": plan_changed,
            "issue": issue, "elapsed_days": bounded_elapsed,
            "remaining_days": (0 if completed else max(0,span-bounded_elapsed))
                              if issue is None else None,
            "overdue_days": max(0,(cutoff-plan).days) if issue is None else None,
            "percent": (100*max(0,elapsed)/span) if issue is None else None,
        }
        result.append(row)
    return result


def timeline_figure(rows, today):
    """Plotly horizontal temporal stacked intervals on one common date scale."""
    today = as_day(today)
    if today is None:
        raise ValueError("Fecha actual inválida.")
    fig = go.Figure()
    spans = {"Transcurrido": [], "Restante": [], "Retraso": []}
    starts, ends = [today], [today]
    labels = [row["label"] for row in rows]
    issues = []
    for row in rows:
        if row["issue"]:
            issues.append(row)
            continue
        start, plan = row["approval"], row["plan"]
        cutoff = row.get("cutoff",today)
        closed = row.get("completion") is not None
        starts.append(start)
        ends.extend([plan, today])
        # Intervals are non-overlapping; all bases and end dates are real dates.
        segments = (
            ("Transcurrido", start, min(max(cutoff, start), plan)),
            ("Restante", max(start, min(cutoff, plan)),
             plan if not closed else max(start, min(cutoff, plan))),
            ("Retraso", plan, max(cutoff, plan)),
        )
        for kind, left, right in segments:
            if right > left:
                details = (
                    f"{row['label']}<br>"
                    f"Aprobación SC: {start:%d/%m/%Y}<br>"
                    f"Plan actual: {plan:%d/%m/%Y}<br>"
                    f"Hoy: {today:%d/%m/%Y}<br>"
                    + (f"Recepción completada: {cutoff:%d/%m/%Y}<br>" if closed else "")
                    + f"Plazo consumido: {row['percent']:.1f}%<br>"
                    f"Días de retraso: {row['overdue_days']}"
                )
                spans[kind].append((row["label"], left.isoformat(),
                                    (right-left).days*86400000, details))
    for kind,color in (("Transcurrido",ELAPSED),("Restante",REMAINING),("Retraso",OVERDUE)):
        data = spans[kind]
        if data:
            fig.add_trace(go.Bar(
                y=[v[0] for v in data], x=[v[2] for v in data],
                base=[v[1] for v in data], orientation="h",
                width=0.55, marker_color=color, name=kind,
                customdata=[v[3] for v in data],
                hovertemplate="%{customdata}<extra></extra>",
            ))
    # A warning is reserved for VERIFIED late ERP completion; an open overdue
    # position keeps its red segment but never receives this icon.
    warnings = [r for r in rows if not r["issue"]
                and r.get("completion") is not None and r["overdue_days"] > 0]
    if warnings:
        def warning_hover(row):
            changed = row.get("plan_changed")
            answer = ("Sí" if changed is True else "No" if changed is False
                      else "No disponible")
            original = row.get("original_plan")
            original_date = (original.strftime("%d/%m/%Y")
                             if original is not None else "No disponible")
            return (
                f"{row['label']}<br>"
                f"Recepción completada fuera de plazo<br>"
                f"Plan original: {original_date}<br>"
                f"Plan actual: {row['plan']:%d/%m/%Y}<br>"
                f"Recepción completada: {row['completion']:%d/%m/%Y}<br>"
                f"Retraso: {row['overdue_days']} días naturales<br>"
                f"Plan modificado respecto al original: {answer}"
            )
        # Small, resolution-independent outlined warning-like triangle with
        # white exclamation point, hoverable at the actual closure date.
        fig.add_trace(go.Scatter(
            x=[r["completion"].isoformat() for r in warnings],
            y=[r["label"] for r in warnings],
            mode="markers+text",
            marker={"symbol":"triangle-up","size":19,"color":OVERDUE},
            text=["!" for _ in warnings],
            textfont={"color":"#FFFFFF","size":11},
            textposition="middle center",
            name="Recepción fuera de plazo",
            showlegend=False,
            customdata=[warning_hover(r) for r in warnings],
            hovertemplate="%{customdata}<extra></extra>",
            cliponaxis=False,
        ))
    # Include invalid positions as their own row; never fabricate dates.
    if issues:
        fig.add_trace(go.Scatter(
            x=[today.isoformat() for _ in issues],
            y=[r["label"] for r in issues],
            mode="markers+text", name="Datos no disponibles",
            text=[r["issue"] for r in issues], textposition="middle right",
            marker={"symbol":"circle-open","size":8,"color":MISSING},
            textfont={"size":10,"color":MISSING},
            cliponaxis=False,
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        ))
    fig.add_shape(
        type="line", xref="x", yref="paper",
        x0=today.isoformat(), x1=today.isoformat(), y0=0, y1=1,
        line={"color":TODAY_LINE,"width":2,"dash":"dash"},
    )
    fig.add_annotation(
        x=today.isoformat(), y=1.025, xref="x", yref="paper",
        text="Hoy", showarrow=False, font={"color":TODAY_LINE,"size":11},
        yanchor="bottom",
    )
    left=min(starts)
    right=max(ends)
    if right <= left:
        left=today-timedelta(days=7)
        right=today+timedelta(days=7)
    pad=max(2,(right-left).days//25)
    fig.update_layout(
        barmode="overlay", height=max(260,110+36*len(rows)),
        margin={"l":10,"r":130 if issues else 20,"t":20,"b":38},
        legend={"orientation":"h","y":1.13,"x":0,"font":{"size":11}},
        hovermode="closest", showlegend=True,
        xaxis={
            "type":"date","tickformat":"%d/%m/%Y","range":[
                (left-timedelta(days=pad)).isoformat(),
                (right+timedelta(days=pad)).isoformat(),
            ],
            "showgrid":True,"gridcolor":"rgba(148,163,184,0.18)",
            "title":None,
        },
        yaxis={
            "categoryorder":"array","categoryarray":list(reversed(labels)),
            "automargin":True,"title":None,
        },
    )
    return fig
