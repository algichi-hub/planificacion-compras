"""Read-only procurement planning dashboard."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st
from st_aggrid import AgGrid, JsCode, DataReturnMode
from src.manage_grid import parse_manage_event, valid_existing_edit, apply_draft_edit
from src.detail_view import (receptions_table, detail_row_style, vertical_records,
                             linked_receipt_numbers, real_delivery_table)
from src.sc_source_detail import request_detail, planning_detail
from src.planning_timeline import build_timeline, timeline_figure
from src.timeline_visibility import sync_context, reset_timeline, toggle_timeline, timeline_visible
from src.sc_overview import overview_display, overview_row_style
from src.delivery_status import attach_delivery_status, present_state
from src.group_sc_view import group_overview, group_overview_source
from src.group_statistics import group_statistics
from src.snapshot_selection import latest_snapshot_id
from src.quantity_format import format_sc_quantities
from src.bulk_sc import is_bulk_admin, write_bulk
from src.pr_hand_deliveries import (write_hand_delivery, normalize_pr, normalize_quantity,
                                    normalize_delivery_date, normalize_nbi, duplicate_warning)
from src.pr_batch_import import parse_pr_batch, batch_digest, batch_warnings, insert_pr_batch
from src.pr_traceability import PR_RELATIONS_SQL, resolve_pr_relations

st.set_page_config(page_title="Planificación de compras",page_icon="📦",layout="wide")
st.title("Planificación de compras")
st.caption("Trazabilidad SC → pedido → recepción → unidades aprobadas · La aprobación no equivale a stock disponible")

def connection_string():
    try:
        return st.secrets["DATABASE_URL"]
    except (KeyError,FileNotFoundError):
        return os.environ.get("DATABASE_URL")

@st.cache_data(ttl=600,show_spinner=False)
def query(sql,params=()):
    dsn=connection_string()
    if not dsn:
        return pd.DataFrame()
    with psycopg.connect(dsn,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(sql,params)
            return pd.DataFrame(cur.fetchall(),columns=[col.name for col in cur.description])

@st.cache_data(ttl=600,show_spinner=False)
def group_catalogue():
    """Isolated catalogue cache: invalidations never flush ERP/snapshot data."""
    return _read_management("SELECT id,name,description FROM planning.bulk_sc_groups ORDER BY name")

@st.cache_data(ttl=600,show_spinner=False)
def group_items(group_id):
    """Isolated cache for one group's membership."""
    return _read_management(
        "SELECT id,sc_no,context_description FROM planning.bulk_sc_items "
        "WHERE group_id=%s ORDER BY sc_no", (int(group_id),)
    )

@st.cache_data(ttl=600,show_spinner=False)
def hand_deliveries():
    """Only active manual deliveries; this cache never flushes ERP queries."""
    return _read_management(
        "SELECT id,pr_no,quantity,delivery_date,received_by_nbi,created_by,created_at, "
        "erp_traceability_comment FROM planning.pr_hand_deliveries WHERE voided_at IS NULL "
        "ORDER BY delivery_date DESC,id DESC"
    )

def _receipt_links_for_sc(snapshot_id, numbers):
    """Shared cached SQL for Manage PR reconciliation and timeline milestones."""
    return query("""SELECT l.company,l.sc_no,l.sc_pos,r.receipt_no,r.approved_qty,
                  (SELECT count(*) FROM core.sc_po_links x
                   WHERE x.snapshot_id=l.snapshot_id
                     AND x.po_no=l.po_no AND x.po_pos=l.po_pos) AS owner_count,
                  (SELECT count(*) FROM core.receipts x
                   WHERE x.snapshot_id=r.snapshot_id AND x.receipt_no=r.receipt_no) AS pr_count
                  FROM core.sc_po_links l
                  JOIN core.receipts r ON r.snapshot_id=l.snapshot_id
                    AND r.po_no=l.po_no AND r.po_pos=l.po_pos
                  WHERE l.snapshot_id=%s AND l.sc_no=ANY(%s)
                  ORDER BY l.company,l.sc_no,l.sc_pos,r.receipt_no""",
                (int(snapshot_id),list(numbers)))


def enrich_delivery_status(source, snapshot_id):
    """Annotate only displayed SC positions; no writes or snapshot recomputation."""
    ledger=hand_deliveries()
    if source.empty or ledger.empty:
        return attach_delivery_status(source,pd.DataFrame(),ledger)
    numbers=tuple(sorted(set(source["sc_no"].dropna().astype(str).tolist())))
    if not numbers:
        return attach_delivery_status(source,pd.DataFrame(),ledger)
    return attach_delivery_status(source,_receipt_links_for_sc(snapshot_id,numbers),ledger)

def _read_management(sql, params=()):
    with psycopg.connect(connection_string(),connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(sql,params)
            return pd.DataFrame(cur.fetchall(),columns=[col.name for col in cur.description])

@st.cache_data(ttl=60,show_spinner=False)
def available_snapshots():
    """Small independent metadata cache; no background polling.

    A newly validated snapshot becomes selectable on the next interaction
    after at most 60 s, without flushing expensive ERP query caches.
    """
    return _read_management(
        "SELECT id,snapshot_date,state FROM audit.snapshots "
        "WHERE state='validated' "
        "ORDER BY snapshot_date DESC NULLS LAST,id DESC"
    )

if not connection_string():
    st.info("Configura DATABASE_URL como secreto del despliegue. No incluyas credenciales en Git.")
    st.stop()

try:
    snapshots=available_snapshots()
except Exception as exc:
    st.error(f"No se ha podido consultar Neon: {type(exc).__name__}")
    st.stop()

if snapshots.empty:
    st.info("Base vacía. Ejecuta desde tu ordenador el importador de los tres CSV y activa el snapshot validado.")
    st.stop()

latest_id=latest_snapshot_id(snapshots)
snapshots["label"]=snapshots.apply(
    lambda r:f"{r['snapshot_date']} · #{r['id']}" +
             (" (Vigente)" if int(r['id'])==latest_id else ""),axis=1)
# The latest validated snapshot is the default. Streamlit preserves a user's
# explicit selection while the selector remains mounted.
snapshot_ids=snapshots["id"].astype(int).tolist()
default_idx=snapshot_ids.index(latest_id)
sid=int(st.sidebar.selectbox("Snapshot",snapshot_ids,index=default_idx,
                             format_func=lambda x:snapshots.loc[snapshots.id==x,"label"].iloc[0]))
st.sidebar.caption("Los filtros consultan únicamente el snapshot elegido.")
projects=query("SELECT DISTINCT project FROM core.sc_lines WHERE snapshot_id=%s AND project IS NOT NULL ORDER BY project",(sid,))
choices=["Todos"]+projects["project"].astype(str).tolist() if not projects.empty else ["Todos"]
project=st.sidebar.selectbox("Proyecto",choices)
where="snapshot_id=%s"
params=[sid]
if project!="Todos":
    where+=" AND project=%s"
    params.append(project)

tab1,tab2,tab3,tab4,tab5=st.tabs(["Resumen","Seguimiento SC","Group SC","Manage SC","Manage PR"])
has_workflow_table=query("SELECT to_regclass('planning.sc_workflow_status') IS NOT NULL AS available").iloc[0]["available"]
workflow_ready=False
if has_workflow_table:
    workflow_ready=bool(query("SELECT EXISTS(SELECT 1 FROM planning.sc_workflow_status WHERE snapshot_id=%s) AS ready",(sid,)).iloc[0]["ready"])
# Reuse one SC/PO reconciliation expression in individual and grouped queries.
po_link_overview="""
  LEFT JOIN LATERAL (
      SELECT string_agg(l.po_no || '/' || l.po_pos, ', '
                        ORDER BY l.po_no,l.po_pos) AS po_positions,
             min(p.planned_date) AS planned_date,
             -- Deterministic PO/position for the earliest current plan.
             (array_agg(l.po_no ORDER BY p.planned_date NULLS LAST,l.po_no,l.po_pos))[1] AS plan_po_no,
             (array_agg(l.po_pos ORDER BY p.planned_date NULLS LAST,l.po_no,l.po_pos))[1] AS plan_po_pos
      FROM core.sc_po_links l
      JOIN core.po_lines p
        ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=
           (l.snapshot_id,l.company,l.po_no,l.po_pos)
      WHERE l.snapshot_id=s.snapshot_id AND l.company=s.company
        AND l.sc_no=s.sc_no AND l.sc_pos=s.sc_pos
  ) linked ON true
"""
po_link_summary=po_link_overview+"""
  -- Indexed exact SC/position lookup, projected through the restricted view.
  -- The dates arrive in the same roundtrip as the existing overview query.
  LEFT JOIN LATERAL (
      SELECT min(NULLIF(btrim(v.fields->>'FECHA APROBACIÓN__12'),'')) AS approval_raw,
             count(DISTINCT NULLIF(btrim(v.fields->>'FECHA APROBACIÓN__12'),'')) AS approval_distinct,
             -- Compare plan dates for the SAME PO/position selected above.
             -- No second raw-source query and no cross-PO date mismatches.
             min(NULLIF(btrim(v.fields->>'FECHA PLANIFICADA__26'),'')) FILTER (
                WHERE v.fields->>'PEDIDO__16'=linked.plan_po_no
                  AND v.fields->>'POSICIÓN__17'=linked.plan_po_pos
             ) AS original_plan_raw,
             count(DISTINCT NULLIF(btrim(v.fields->>'FECHA PLANIFICADA__26'),'')) FILTER (
                WHERE v.fields->>'PEDIDO__16'=linked.plan_po_no
                  AND v.fields->>'POSICIÓN__17'=linked.plan_po_pos
             ) AS original_plan_distinct,
             min(NULLIF(btrim(v.fields->>'FECHA APROBACIÓN DEL PEDIDO__41'),'')) FILTER (
                WHERE v.fields->>'PEDIDO__16'=linked.plan_po_no
                  AND v.fields->>'POSICIÓN__17'=linked.plan_po_pos
             ) AS po_approval_raw,
             count(DISTINCT NULLIF(btrim(v.fields->>'FECHA APROBACIÓN DEL PEDIDO__41'),'')) FILTER (
                WHERE v.fields->>'PEDIDO__16'=linked.plan_po_no
                  AND v.fields->>'POSICIÓN__17'=linked.plan_po_pos
             ) AS po_approval_distinct
      FROM planning.v_sc_source_detail v
      WHERE v.snapshot_id=s.snapshot_id AND v.company=s.company
        AND v.sc_no=s.sc_no AND v.sc_pos=s.sc_pos
  ) timeline_dates ON true
  -- ERP PR milestones share one indexed lateral query per SC position.
  -- A first "approved PR" is a receipt whose positive delivered quantity
  -- equals the approved quantity in this snapshot; this is NOT a historical
  -- quality-approval timestamp.
  LEFT JOIN LATERAL (
      SELECT min(ev.receipt_date) FILTER
                (WHERE ev.delivered_qty>0 AND ev.safe) AS first_receipt_date,
             min(ev.pr_receipt_date) FILTER
                (WHERE ev.pr_fully_approved AND ev.safe) AS first_approved_pr_date,
             (array_agg(ev.pr_delivered_total ORDER BY ev.pr_receipt_date,ev.receipt_no)
               FILTER (WHERE ev.pr_fully_approved AND ev.safe))[1] AS first_approved_pr_qty,
             CASE WHEN s.requested_qty>0 AND s.approved_qty>=s.requested_qty
                   AND bool_and(ev.safe)
                   AND max(ev.cumulative_approved)>=s.requested_qty
                  THEN min(ev.receipt_date) FILTER
                         (WHERE ev.cumulative_approved>=s.requested_qty)
             END AS completion_date,
             -- Raw ERP receipt events and their own PO-line quantity; one
             -- JSON aggregate per SC, no extra database roundtrips.
             jsonb_agg(jsonb_build_object(
                 'po_no',ev.po_no,'po_pos',ev.po_pos,
                 'po_qty',ev.ordered_qty,'allocation_status',ev.allocation_status,
                 'pr_no',ev.receipt_no,'pr_date',ev.receipt_date,
                 'delivered_qty',ev.delivered_qty,'source_line',ev.source_line
             ) ORDER BY ev.receipt_date NULLS LAST,ev.source_line,ev.po_no,ev.po_pos
             ) AS receipt_events
      FROM (
          SELECT l.po_no,l.po_pos,l.allocation_status,p.ordered_qty,
                 r.source_line,r.receipt_no,r.receipt_date,r.delivered_qty,
                 sum(coalesce(r.approved_qty,0)) OVER
                    (ORDER BY r.receipt_date,r.source_line ROWS UNBOUNDED PRECEDING)
                    AS cumulative_approved,
                 (r.receipt_date IS NOT NULL AND r.approved_qty IS NOT NULL
                  AND r.approved_qty>=0 AND l.allocation_status='verified') AS safe,
                 min(r.receipt_date) OVER (PARTITION BY r.receipt_no)
                    AS pr_receipt_date,
                 sum(coalesce(r.delivered_qty,0)) OVER (PARTITION BY r.receipt_no)
                    AS pr_delivered_total,
                 (sum(coalesce(r.delivered_qty,0)) OVER (PARTITION BY r.receipt_no)>0
                  AND sum(coalesce(r.delivered_qty,0)) OVER (PARTITION BY r.receipt_no)
                   =sum(coalesce(r.approved_qty,0)) OVER (PARTITION BY r.receipt_no)
                  AND bool_and(r.approved_qty IS NOT NULL AND r.delivered_qty IS NOT NULL
                               AND r.approved_qty>=0 AND r.delivered_qty>=0)
                      OVER (PARTITION BY r.receipt_no)
                 ) AS pr_fully_approved
          FROM core.sc_po_links l
          LEFT JOIN core.po_lines p
            ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=
               (l.snapshot_id,l.company,l.po_no,l.po_pos)
          LEFT JOIN core.receipts r
            ON (r.snapshot_id,r.po_no,r.po_pos)=(l.snapshot_id,l.po_no,l.po_pos)
          WHERE l.snapshot_id=s.snapshot_id AND l.company=s.company
            AND l.sc_no=s.sc_no AND l.sc_pos=s.sc_pos
      ) ev
  ) receipt_closure ON true
"""

def overview_column_config():
    """Keep the exact same native column configuration in both SC views."""
    return {
        **{name: st.column_config.Column(width=None)
           for name in ("Sol", "Ped", "Rec", "Apr")},
        # "Ent" contains numeric Decimals and the no-data dash; explicitly
        # right-align this mixed-type column like the other quantities.
        "Ent": st.column_config.Column(width=None, alignment="right"),
        " ": st.column_config.ImageColumn("", width=38, pinned=True,
            help="Estado operativo SC"),
    }

def render_planning_timeline(source, today, key):
    """Same date-based schedule for SC and Group SC; no database reads."""
    st.markdown("#### Cronograma de planificación")
    if source.empty:
        st.caption("Sin posiciones SC para representar.")
        return
    rows=build_timeline(source,today,
                        ledger=source.attrs.get("physical_ledger"),
                        receipt_links=source.attrs.get("receipt_links"))
    # Keep hover details; hide native modebar and prevent zoom/edit actions.
    st.plotly_chart(timeline_figure(rows,today),use_container_width=True,
                    config={"displayModeBar":False,"scrollZoom":False,
                            "doubleClick":False,"editable":False},
                    key=f"{key}_planning_timeline")
    missing=sum(bool(row["issue"]) for row in rows)
    st.caption("Una barra por SC/Pos: SC → pedido (rojo), pedido → plan original "
               "(naranja), ampliación del plan (rosa pastel) y seguimiento "
               "(gris claro). Azul claro: PR parcial; azul oscuro: recepción ERP "
               "completa. Morado claro: entrega física parcial; morado oscuro: "
               "entrega física total verificada, que cierra el gris. En fechas "
               "coincidentes prevalece el hito más avanzado; el detalle muestra "
               "todos los eventos. Línea vertical: hoy (Madrid).")
    if missing:
        st.caption(f"{missing} posiciones con hitos incompletos o fechas "
                   "inconsistentes; solo se representan los tramos verificables.")

def render_sc_detail(line, sid, context):
    """Read-only SC detail shared by individual and grouped views."""
    st.subheader(f"Detalle SC {line['sc_no']} / {line['sc_pos']}")
    widget_prefix=f"{context}_{sid}_{line['company']}_{line['sc_no']}_{line['sc_pos']}"
    trace=query("""SELECT l.po_no AS pedido,l.po_pos AS posicion_pedido,
           p.article AS articulo_pedido,p.vendor AS proveedor,
           p.ordered_qty AS cantidad_pedida,p.planned_date AS fecha_planificada,
           r.receipt_no AS parte_recepcion,r.receipt_date AS fecha_recepcion,
           r.delivered_qty AS cantidad_entregada,r.approved_qty AS cantidad_aprobada
           FROM core.sc_po_links l
           JOIN core.po_lines p ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=
               (l.snapshot_id,l.company,l.po_no,l.po_pos)
           LEFT JOIN core.receipts r ON (r.snapshot_id,r.po_no,r.po_pos)=
               (l.snapshot_id,l.po_no,l.po_pos)
           WHERE l.snapshot_id=%s AND l.company=%s AND l.sc_no=%s AND l.sc_pos=%s
           ORDER BY l.po_no,l.po_pos,r.receipt_date NULLS LAST,r.receipt_no""",
                (sid,line["company"],line["sc_no"],line["sc_pos"]))
    # Fetch original SC rows only for the selected position. Multiple PO allocations
    # are preserved and joined using both PO number and PO position.
    source_rows=query("""SELECT fields FROM planning.v_sc_source_detail
                         WHERE snapshot_id=%s AND company=%s
                           AND sc_no=%s AND sc_pos=%s
                         ORDER BY source_line""",
                      (sid,line["company"],line["sc_no"],line["sc_pos"]))
    raw_records=source_rows["fields"].tolist() if not source_rows.empty else []
    sc_meta=query("""SELECT article,description,project,centre,project_director
                     FROM core.sc_lines
                     WHERE snapshot_id=%s AND company=%s AND sc_no=%s AND sc_pos=%s""",
                  (sid,line["company"],line["sc_no"],line["sc_pos"]))
    request_source=sc_meta.iloc[0] if not sc_meta.empty else line
    request=request_detail(request_source,raw_records)
    plan=planning_detail(trace,raw_records)
    madrid_today=datetime.now(ZoneInfo("Europe/Madrid")).date()
    st.markdown("#### Datos de solicitud")
    st.dataframe(request,use_container_width=True,hide_index=True,
                 column_config={"Campo":st.column_config.TextColumn(width="medium"),
                                "Valor":st.column_config.TextColumn(width="large")},
                 height=min(720,35*(len(request)+1)+3),
                 key=f"{widget_prefix}_request")
    st.markdown("#### Pedido y planificación")
    if plan.empty:
        st.caption("Esta posición SC no tiene pedidos vinculados.")
    else:
        st.dataframe(
            plan.style.apply(detail_row_style,axis=1,today=madrid_today,
                             workflow_state=line.get("workflow_state")),
            use_container_width=True,hide_index=True,
            column_config={"Campo":st.column_config.TextColumn(width="medium"),
                           "Valor":st.column_config.TextColumn(width="large")},
            height=min(720,35*(len(plan)+1)+3),
            key=f"{widget_prefix}_detail",
        )
        st.caption("Solo en estado «Material sin recibir»: plan actual vencido en rojo; entre hoy y los próximos 7 días naturales en amarillo; a más de 7 días en verde. Texto en negrita, sin fondo.")
    st.markdown("#### Recepciones")
    receptions=receptions_table(trace)
    if receptions.empty:
        st.caption("Sin recepciones registradas para los pedidos vinculados.")
    else:
        st.dataframe(receptions,width="content",hide_index=True,
                     column_config={"Campo": st.column_config.TextColumn(),
                                    "Valor": st.column_config.TextColumn()},
                     height=min(720,35*(len(receptions)+1)+3),
                     key=f"{widget_prefix}_receptions")
        st.caption("Recepción: número (fecha, Re: cantidad recibida en admisión de entrada, Ap: cantidad aprobada tras el control de calidad). La diferencia Rec − Apr corresponde a unidades que todavía no constan como aprobadas; no implica necesariamente rechazo.")
    st.markdown("#### Entrega real")
    # Reuse the same independently cached manual ledger as Manage PR. Its cache
    # is invalidated after each insertion/anulación; never modify ERP receipts.
    related_prs=linked_receipt_numbers(trace)
    real_deliveries=real_delivery_table(
        trace,hand_deliveries() if related_prs else pd.DataFrame()
    )
    if real_deliveries.empty:
        st.caption("Sin entregas reales registradas para los PR de esta posición SC.")
    else:
        st.dataframe(real_deliveries,use_container_width=True,hide_index=True,
                     height=min(720,35*(len(real_deliveries)+1)+3),
                     key=f"{widget_prefix}_real_delivery")

    # REAC is keyed to the selected SC position; it is not an operational state.
    st.markdown("#### REAC")
    reac_detail=query("""SELECT reac_no AS referencia_reac,
           reac_article AS articulo_reac,po_no AS pedido,
           po_pos AS posicion_pedido
           FROM core.reac_refs
           WHERE snapshot_id=%s AND company=%s AND sc_no=%s AND sc_pos=%s
           ORDER BY reac_no,po_no,po_pos""",
        (sid,line["company"],line["sc_no"],line["sc_pos"]))
    if reac_detail.empty:
        st.caption("Sin referencias REAC para esta posición.")
    else:
        reac_vertical=vertical_records(reac_detail,"REAC",{
            "referencia_reac":"Referencia REAC","articulo_reac":"Artículo REAC",
            "pedido":"Pedido","posicion_pedido":"Posición pedido"})
        st.dataframe(reac_vertical,use_container_width=True,hide_index=True,
                     key=f"{widget_prefix}_reac")
        st.caption("REAC documental: no se infiere cantidad rechazada ni estado de aprobación.")
    
    # INC has no company/SC identifier: link conservatively by PO/position
    # and disclose the article match instead of asserting exact SC ownership.
    st.markdown("#### Incidencias")
    inc_detail=query("""SELECT DISTINCT i.source_line AS fila_origen_inc,
           l.po_no AS pedido,l.po_pos AS posicion_pedido,
           i.record_no AS numero_incidencia,i.sequence_no AS secuencia,
           i.article AS articulo_inc,p.article AS articulo_pedido,
           CASE WHEN i.article=p.article THEN 'Coincide'
                ELSE 'Revisar' END AS coincidencia_articulo,
           i.category AS categoria,i.resolved AS resuelta,
           i.detail AS observaciones
           FROM core.sc_po_links l
           JOIN core.po_lines p ON
             (p.snapshot_id,p.company,p.po_no,p.po_pos)=
             (l.snapshot_id,l.company,l.po_no,l.po_pos)
           JOIN core.incidents i ON
             (i.snapshot_id,i.po_no,i.po_pos)=(l.snapshot_id,l.po_no,l.po_pos)
           WHERE l.snapshot_id=%s AND l.company=%s
             AND l.sc_no=%s AND l.sc_pos=%s
           ORDER BY l.po_no,l.po_pos,i.source_line,i.record_no""",
        (sid,line["company"],line["sc_no"],line["sc_pos"]))
    if inc_detail.empty:
        st.caption("Sin incidencias vinculables a sus posiciones de pedido.")
    else:
        inc_vertical=vertical_records(inc_detail,"INC",{
            "fila_origen_inc":"Fila original INC","pedido":"Pedido",
            "posicion_pedido":"Posición pedido",
            "numero_incidencia":"Número de incidencia",
            "secuencia":"Secuencia","articulo_inc":"Artículo INC",
            "articulo_pedido":"Artículo pedido",
            "coincidencia_articulo":"Coincidencia de artículo",
            "categoria":"Categoría","resuelta":"Resuelta",
            "observaciones":"Observaciones"})
        st.dataframe(inc_vertical,use_container_width=True,hide_index=True,
                     key=f"{widget_prefix}_inc")
        st.caption("INC vinculada por pedido y posición; el fichero INC carece de compañía/SC. Revisar las coincidencias de artículo y cualquier vinculación compartida.")

with tab1:
    if workflow_ready:
        states=query("SELECT workflow_state,count(*) AS n FROM planning.sc_workflow_status WHERE "+where+" GROUP BY workflow_state ORDER BY n DESC",tuple(params))
        total=int(states["n"].sum()) if not states.empty else 0
        cancelled=int(states.loc[states.workflow_state=="SC anulada","n"].sum()) if not states.empty else 0
        complete=int(states.loc[states.workflow_state=="Completado","n"].sum()) if not states.empty else 0
        uncertain=int(states.loc[states.workflow_state=="Pendiente conciliación","n"].sum()) if not states.empty else 0
        for col,(label,value) in zip(st.columns(4),[("Líneas SC",total),("Recepciones completadas",complete),("SC anuladas",cancelled),("Pendientes conciliación",uncertain)]):
            col.metric(label,value)
        states_display=states.assign(workflow_state=states["workflow_state"].map(present_state))
        st.plotly_chart(px.bar(states_display,x="workflow_state",y="n",title="Estado de tramitación por línea SC",labels={"workflow_state":"Estado","n":"Líneas SC"}),use_container_width=True)
        st.caption("Las SC anuladas no se computan como pendientes de pedido. Estados basados en evidencias del snapshot.")
    else:
        st.info("Clasificación operativa pendiente de cálculo para este snapshot. Ejecuta la migración 007 y scripts/build_sc_workflow.py --snapshot ID --commit.")
        metrics=query("SELECT count(*) AS n_sc, count(*) FILTER (WHERE coverage_state='complete') AS completas, count(*) FILTER (WHERE coverage_state='partial') AS parciales, count(*) FILTER (WHERE coverage_state='pending_reconciliation') AS inciertas FROM planning.v_sc_coverage WHERE "+where,tuple(params))
        if not metrics.empty:
            m=metrics.iloc[0]
            for col,(label,value) in zip(st.columns(4),[("Líneas SC",m.n_sc),("Cobertura completa",m.completas),("Cobertura parcial",m.parciales),("Sin conciliar",m.inciertas)]):
                col.metric(label,int(value))
with tab2:
    search=st.text_input("Buscar SC", "", key="sc_search",
                         placeholder="Número exacto de SC")
    sc_number=search.strip()
    if not sc_number:
        st.caption("Introduce un número de SC para visualizar todas sus posiciones.")
    else:
        # The sidebar project filter intentionally does not restrict SC lookup:
        # the user must see every position of the requested SC.
        # One row per SC position; PO/Pos may hold several linked orders.
        # The earliest planned PO date is used as the deadline indicator.
        if workflow_ready:
            overview=query("""SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,
                    s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,
                    s.workflow_state,linked.po_positions,linked.planned_date
                    FROM planning.sc_workflow_status s
                    """+po_link_overview+"""
                    WHERE s.snapshot_id=%s AND s.sc_no=%s
                    ORDER BY s.company, CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                      THEN btrim(s.sc_pos)::numeric END NULLS LAST,s.sc_pos""",(sid,sc_number))
        else:
            overview=query("""SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,
                    s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,
                    s.coverage_state,linked.po_positions,linked.planned_date
                    FROM planning.v_sc_coverage s
                    """+po_link_overview+"""
                    WHERE s.snapshot_id=%s AND s.sc_no=%s
                    ORDER BY s.company, CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                      THEN btrim(s.sc_pos)::numeric END NULLS LAST,s.sc_pos""",(sid,sc_number))
        if overview.empty:
            st.info("No se encontraron posiciones para esa SC en el snapshot seleccionado.")
        else:
            st.caption(f"SC {sc_number} · {len(overview)} posiciones. Selecciona una fila para ver su detalle.")
            st.caption("PO/Pos muestra todos los pedidos asociados. fecha_plan corresponde a la fecha planificada más próxima entre ellos. Para Material sin recibir: rojo si vencida, amarillo si faltan de 0 a 7 días naturales y verde si faltan más de 7 días.")
            # Preserve the original result for exact company/SC/position lookup.
            # The displayed DataFrame adds a status-symbol column without altering selection.
            overview=enrich_delivery_status(overview,sid)
            visible_overview=overview_display(overview)
            madrid_today=datetime.now(ZoneInfo("Europe/Madrid")).date()
            event=st.dataframe(
                format_sc_quantities(visible_overview.style).apply(
                    overview_row_style,axis=1,today=madrid_today
                ),use_container_width=True,hide_index=True,
                column_config=overview_column_config(),
                on_select="rerun",selection_mode="single-row",
                key=f"sc_overview_{sid}_{sc_number}",
            )
            # State belongs only to this SC and snapshot, not Group SC.
            sync_context(st.session_state,"sc",(sid,sc_number))
            st.button(
                "Ocultar cronograma" if timeline_visible(st.session_state,"sc")
                else "Mostrar cronograma",key="sc_timeline_toggle",
                on_click=toggle_timeline,args=(st.session_state,"sc")
            )
            if timeline_visible(st.session_state,"sc"):
                timeline_cached=st.session_state.get("sc_timeline_data")
                if timeline_cached is None:
                    source_table=("planning.sc_workflow_status" if workflow_ready
                                  else "planning.v_sc_coverage")
                    timeline_data=query(f"""SELECT s.company,s.sc_no,s.sc_pos,
                        timeline_dates.approval_raw,timeline_dates.approval_distinct,
                        timeline_dates.original_plan_raw,timeline_dates.original_plan_distinct,
                        timeline_dates.po_approval_raw,timeline_dates.po_approval_distinct,
                        receipt_closure.receipt_events
                        FROM {source_table} s
                        """+po_link_summary+"""
                        WHERE s.snapshot_id=%s AND s.sc_no=%s
                        ORDER BY s.company,s.sc_no,s.sc_pos""",(sid,sc_number))
                    st.session_state["sc_timeline_data"]=timeline_data
                    timeline_cached=timeline_data
                sc_timeline_source=overview.merge(
                    timeline_cached,on=["company","sc_no","sc_pos"],
                    how="left",sort=False,validate="one_to_one"
                )
                # Reuse the exact PR ownership query and cached active
                # manual ledger used by Manage PR; no write or group changes.
                sc_timeline_source.attrs["physical_ledger"]=hand_deliveries()
                sc_timeline_source.attrs["receipt_links"]=_receipt_links_for_sc(
                    sid,tuple(sorted(set(overview["sc_no"].dropna().astype(str))))
                )
                render_planning_timeline(sc_timeline_source,madrid_today,
                                         f"sc_{sid}_{sc_number}")
            selected_rows=event.selection.rows
            if selected_rows:
                line=overview.iloc[selected_rows[0]]
                render_sc_detail(line, sid, context="seguimiento")

# Shared, read-only group catalogue. Admin privileges are evaluated only in Manage.
try:
    groups=group_catalogue()
except psycopg.Error:
    groups=pd.DataFrame(columns=["id","name","description"])

with tab3:
    st.subheader("Group SC")
    st.caption("Estadística de compras, recepción y aprobación por SC. Los datos corresponden al snapshot seleccionado.")
    if groups.empty:
        st.info("Todavía no hay grupos SC disponibles.")
    else:
        group_id=int(st.selectbox(
            "Grupo SC",groups["id"].tolist(),key="group_sc_select",
            format_func=lambda x:groups.loc[groups.id==x,"name"].iloc[0],
        ))
        group_record=groups.loc[groups.id==group_id].iloc[0]
        if str(group_record["description"] or "").strip():
            st.caption(str(group_record["description"]))
        items=group_items(group_id)
        if items.empty:
            st.info("Este grupo todavía no tiene SC asociadas.")
        else:
            # No group table, detailed report or PR timeline on initial view.
            # The summary query is only made after clicking Estadística.
            group_key=(sid,group_id,tuple(items["sc_no"].astype(str).tolist()))
            stats_saved=st.session_state.get("group_statistics_result")
            stats_ready=bool(stats_saved and stats_saved[0]==group_key)
            if st.button("Estadística",type="primary",key="group_sc_statistics"):
                numbers=items["sc_no"].astype(str).tolist()
                source_table=("planning.sc_workflow_status" if workflow_ready
                              else "planning.v_sc_coverage")
                status_column="workflow_state" if workflow_ready else "coverage_state"
                group_status=query(f"""SELECT s.company,s.sc_no,s.sc_pos,s.article,
                               s.description,s.project,s.requested_qty,s.ordered_qty,
                               s.received_qty,s.approved_qty,s.{status_column},
                               linked.po_positions,linked.planned_date
                               FROM {source_table} s
                               """+po_link_overview+"""
                               WHERE s.snapshot_id=%s AND s.sc_no=ANY(%s)
                               ORDER BY s.company,s.sc_no,
                                   CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                                       THEN btrim(s.sc_pos)::numeric END NULLS LAST,
                                   s.sc_pos""",(sid,numbers))
                st.session_state["group_statistics_result"]=(group_key,group_status)
                st.session_state.pop("bulk_result",None)
                stats_saved=st.session_state["group_statistics_result"]
                stats_ready=True
            if stats_ready:
                today_madrid=datetime.now(ZoneInfo("Europe/Madrid")).date()
                stat_table=group_statistics(items,stats_saved[1],today_madrid)
                st.dataframe(
                    stat_table,hide_index=True,use_container_width=True,
                    column_config={
                        "Num SC":st.column_config.TextColumn("Num SC",width="small"),
                        "PO asociados":st.column_config.TextColumn("PO asociados",width="medium"),
                        "Descripción contextual":st.column_config.TextColumn(
                            "Descripción contextual",width="large"
                        ),
                        **{name:st.column_config.TextColumn(name,width="small")
                           for name in ("Pend PO","Pass Date","Full Received","Full Approved")},
                    },
                    key=f"group_stats_{sid}_{group_id}",
                )
                # Only this second action reveals the detailed position report.
                if st.button("Consultar grupo",key="group_sc_report"):
                    group_source=group_overview_source(items,stats_saved[1])
                    grouped=group_overview(items,stats_saved[1])
                    st.session_state["bulk_result"]=(sid,group_id,grouped,group_source)
                stored=st.session_state.get("bulk_result")
                if stored and stored[0]==sid and stored[1]==group_id:
                    group_source=enrich_delivery_status(stored[3],sid)
                    bulk_view=overview_display(group_source)
                    # Preserve identifiers of SC absent from the snapshot.
                    missing=group_source["sc_pos"].isna()
                    bulk_view.loc[missing,"SC/Pos"]=stored[2].loc[missing,"SC/Pos"]
                    st.caption(f"{len(items)} SC · {len(bulk_view)} posiciones o referencias")
                    event_group=st.dataframe(
                        format_sc_quantities(bulk_view.style).apply(
                            overview_row_style,axis=1,today=today_madrid
                        ),
                        hide_index=True,use_container_width=True,
                        column_config=overview_column_config(),
                        on_select="rerun",selection_mode="single-row",
                        key=f"group_sc_overview_{sid}_{group_id}",
                    )
                    if event_group.selection.rows:
                        selected_index=event_group.selection.rows[0]
                        line=group_source.iloc[selected_index]
                        if pd.isna(line.get("company")) or pd.isna(line.get("sc_pos")):
                            st.info("Esta SC no figura en el snapshot seleccionado; no hay detalle que consultar.")
                        else:
                            render_sc_detail(line, sid, context="group")

with tab4:
    st.subheader("Manage SC")
    st.caption("Administración de grupos y componentes SC. Requiere acceso de administrador.")
    try:
        auth_configured=bool(st.secrets.get("auth"))
        admin_emails=str(st.secrets.get("BULK_ADMIN_EMAILS",""))
        admin_dsn=st.secrets.get("BULK_ADMIN_DATABASE_URL")
    except (KeyError,FileNotFoundError):
        auth_configured=False
        admin_emails=""
        admin_dsn=None
    identity=st.user.to_dict() if auth_configured else {}
    admin=is_bulk_admin(identity,admin_emails) and bool(admin_dsn)

    if auth_configured:
        if identity.get("is_logged_in"):
            if st.button("Cerrar sesión de administrador",key="bulk_logout"):
                st.logout()
        elif st.button("Iniciar sesión con Google",key="bulk_login"):
            st.login("google")
    if not admin:
        st.info("La gestión requiere una cuenta administradora verificada y la conexión de escritura restringida.")
    else:
        with st.expander("Crear grupo"):
            with st.form("bulk_create_group"):
                new_group=st.text_input("Nombre del grupo",max_chars=160)
                new_description=st.text_area("Descripción del grupo",max_chars=500)
                if st.form_submit_button("Guardar grupo"):
                    try:
                        write_bulk(admin_dsn,identity,admin_emails,"create_group",
                                   name=new_group,description=new_description)
                        group_catalogue.clear()
                        group_items.clear()
                        st.session_state.pop("bulk_result",None)
                        st.session_state.pop("group_statistics_result",None)
                        st.rerun()
                    except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                        st.error(f"No se pudo guardar el grupo: {type(exc).__name__}")

        if not groups.empty:
            group_id_manage=int(st.selectbox(
                "Grupo para gestionar",groups["id"].tolist(),key="manage_group_select",
                format_func=lambda x:groups.loc[groups.id==x,"name"].iloc[0],
            ))
            selected_group=groups.loc[groups.id==group_id_manage].iloc[0]
            items_manage=group_items(group_id_manage)
            st.caption("Edita las celdas directamente. Se guardan al confirmar la edición.")
            draft_key=f"manage_grid_drafts_{group_id_manage}"
            revision_key=f"manage_grid_revision_{group_id_manage}"
            st.session_state.setdefault(draft_key,{})
            st.session_state.setdefault(revision_key,0)

            def _refresh_manage():
                group_items.clear()
                st.session_state.pop("bulk_result",None)
                st.session_state.pop("group_statistics_result",None)
                st.session_state[revision_key]+=1

            @st.dialog("Confirmar borrado")
            def _confirm_remove_item(item_id, sc_number):
                st.write(f"¿Eliminar la SC **{sc_number}** de este grupo?")
                st.caption("No se modificarán los registros originales del ERP.")
                cancel_col,confirm_col=st.columns(2)
                with cancel_col:
                    if st.button("Cancelar",key=f"grid_cancel_{group_id_manage}_{item_id}",
                                 use_container_width=True):
                        st.rerun()
                with confirm_col:
                    if st.button("Confirmar borrado",key=f"grid_confirm_{group_id_manage}_{item_id}",
                                 type="primary",use_container_width=True):
                        try:
                            write_bulk(admin_dsn,identity,admin_emails,"remove_item",
                                       group_id=group_id_manage,item_id=item_id)
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(f"No se pudo eliminar: {type(exc).__name__}")
                        else:
                            _refresh_manage()
                            st.rerun()

            @st.fragment
            def render_manage_grid():
                # The hidden row id is immutable; SC is text to retain leading zeros.
                items_manage=group_items(group_id_manage)
                rows=items_manage[["id","sc_no","context_description"]].copy()
                rows["id"]=rows["id"].astype(int)
                rows["sc_no"]=rows["sc_no"].astype(str)
                rows["context_description"]=rows["context_description"].astype(str)
                for draft_id,draft in st.session_state[draft_key].items():
                    rows.loc[len(rows)]=[draft_id,draft["sc_no"],draft["context_description"]]
                rows.insert(0,"delete","X")

                # AG Grid's React wrapper must receive a string, not an HTMLButtonElement.
                # Event handling stays on cellClicked (the click bubbles from the button).
                # Plain text avoids DOM/HTML escaping and React #31 in AG Grid cells.
                # The cell itself receives cellClicked; no custom renderer required.
                collect_event=JsCode("""
                    function({streamlitRerunEventTriggerName,eventData}) {
                        if (!eventData || !eventData.data) return null;
                        const row=eventData.data;
                        const col=eventData.column ? eventData.column.getColId() : '';
                        if (streamlitRerunEventTriggerName === 'cellClicked' && col === 'delete')
                            return {type:'delete',id:row.id};
                        if (streamlitRerunEventTriggerName === 'cellValueChanged'
                            && (col === 'sc_no' || col === 'context_description'))
                            return {type:'edit',id:row.id,field:col,value:String(eventData.newValue ?? '')};
                        return null;
                    }
                """)
                should_return=JsCode("""
                    function({streamlitRerunEventTriggerName,eventData}) {
                        if (!eventData || !eventData.data) return false;
                        const col=eventData.column ? eventData.column.getColId() : '';
                        return (streamlitRerunEventTriggerName === 'cellValueChanged'
                                && (col === 'sc_no' || col === 'context_description'))
                               || (streamlitRerunEventTriggerName === 'cellClicked'
                                   && col === 'delete');
                    }
                """)
                grid_options={
                    "columnDefs":[
                        {"field":"delete","headerName":"","width":38,"minWidth":38,"maxWidth":38,
                         "pinned":"left","editable":False,"sortable":False,"resizable":False,
                         "cellStyle":{"color":"#B91C1C","fontWeight":"700","textAlign":"center",
                                      "cursor":"pointer","paddingLeft":"0","paddingRight":"0"}},
                        {"field":"sc_no","headerName":"SC","minWidth":110,"width":170,
                         "editable":True,"cellDataType":"text"},
                        {"field":"context_description","headerName":"Descripción contextual",
                         "minWidth":160,"flex":1,"editable":True,"cellDataType":"text"},
                    ],
                    "defaultColDef":{"sortable":False,"filter":False,"resizable":True,
                                     "singleClickEdit":True},
                    "rowHeight":32,"headerHeight":32,
                    "getRowId":JsCode("function(p){ return String(p.data.id); }"),
                    "suppressRowClickSelection":True,
                    "stopEditingWhenCellsLoseFocus":True,
                    "ensureDomOrder":True,
                    "suppressMovableColumns":True,
                    "suppressCellFocus":False,
                }
                error_key=f"manage_grid_error_{group_id_manage}"
                if st.session_state.get(error_key):
                    st.error(st.session_state.pop(error_key))
                st.markdown("**SC del grupo**")
                grid_result=AgGrid(
                    rows,gridOptions=grid_options,
                    height=min(450,40+max(1,len(rows))*32),
                    theme="streamlit",allow_unsafe_jscode=True,
                    enable_enterprise_modules=False,
                    data_return_mode=DataReturnMode.CUSTOM,
                    custom_jscode_for_grid_return=collect_event,
                    should_grid_return=should_return,
                    update_on=["cellValueChanged","cellClicked"],
                    key=f"manage_grid_{group_id_manage}_{st.session_state[revision_key]}",
                    show_toolbar=False,show_search=False,show_download_button=False,
                    server_sync_strategy="server_wins",
                    custom_css={
                        ".ag-root-wrapper":{"borderRadius":"0px !important"},
                        ".ag-cell":{"borderRadius":"0px !important","paddingTop":"0px","paddingBottom":"0px"},
                        ".ag-row":{"borderBottom":"1px solid var(--ag-border-color)"},
                    },
                )
                event=parse_manage_event(grid_result.raw_data if hasattr(grid_result,"raw_data") else None)
                if event:
                    row_id=event["id"]
                    if event["type"]=="delete":
                        if row_id < 0:
                            st.session_state[draft_key].pop(row_id,None)
                            st.session_state[revision_key]+=1
                            st.rerun(scope="fragment")
                        matched=items_manage.loc[items_manage["id"]==row_id]
                        if len(matched)==1:
                            _confirm_remove_item(row_id,str(matched.iloc[0]["sc_no"]))
                    elif row_id < 0:
                        draft=st.session_state[draft_key].get(row_id)
                        if draft is not None:
                            draft,complete=apply_draft_edit(draft,event)
                            st.session_state[draft_key][row_id]=draft
                            if complete:
                                try:
                                    write_bulk(admin_dsn,identity,admin_emails,"insert_item",
                                               group_id=group_id_manage,sc_no=draft["sc_no"],
                                               description=draft["context_description"])
                                except ValueError as exc:
                                    st.error(str(exc))
                                except (psycopg.Error,PermissionError,RuntimeError) as exc:
                                    st.error(f"No se pudo añadir la SC: {type(exc).__name__}")
                                else:
                                    st.session_state[draft_key].pop(row_id,None)
                                    _refresh_manage()
                                    st.rerun(scope="fragment")
                    else:
                        try:
                            sc_new,desc_new,unchanged=valid_existing_edit(event,items_manage)
                            if not unchanged:
                                write_bulk(admin_dsn,identity,admin_emails,"edit_item",
                                           group_id=group_id_manage,item_id=row_id,
                                           sc_no=sc_new,description=desc_new)
                        except ValueError as exc:
                            st.session_state[error_key]=str(exc)
                            st.session_state[revision_key]+=1
                            st.rerun(scope="fragment")
                        except (psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.session_state[error_key]=f"No se pudo guardar: {type(exc).__name__}"
                            st.session_state[revision_key]+=1
                            st.rerun(scope="fragment")
                        else:
                            if not unchanged:
                                _refresh_manage()
                                st.rerun(scope="fragment")

                if st.button("Añadir nueva SC",icon=":material/add:",
                             key=f"manage_grid_add_{group_id_manage}"):
                    draft_id=-int(st.session_state.get("manage_grid_counter",0)+1)
                    st.session_state["manage_grid_counter"]=-draft_id
                    st.session_state[draft_key][draft_id]={"sc_no":"","context_description":""}
                    st.session_state[revision_key]+=1
                    st.rerun(scope="fragment")

            render_manage_grid()

            with st.expander("Modificar grupo"):
                with st.form(f"bulk_edit_group_{group_id_manage}"):
                    updated_name=st.text_input("Nombre",value=str(selected_group["name"]),max_chars=160)
                    updated_description=st.text_area(
                        "Descripción",value=str(selected_group["description"] or ""),max_chars=500
                    )
                    if st.form_submit_button("Guardar cambios"):
                        try:
                            write_bulk(admin_dsn,identity,admin_emails,"edit_group",
                                       group_id=group_id_manage,name=updated_name,
                                       description=updated_description)
                            group_catalogue.clear()
                            group_items.clear()
                            st.session_state.pop("bulk_result",None)
                            st.session_state.pop("group_statistics_result",None)
                            st.rerun()
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(f"No se pudo modificar el grupo: {type(exc).__name__}")

            with st.expander("Eliminar grupo"):
                st.warning("Eliminar el grupo también retira todas sus SC del grupo. No modifica las SC del ERP.")
                with st.form(f"bulk_remove_group_{group_id_manage}"):
                    confirmed=st.checkbox("Confirmo la eliminación del grupo y todos sus componentes")
                    if st.form_submit_button("Eliminar grupo") and confirmed:
                        try:
                            write_bulk(admin_dsn,identity,admin_emails,"remove_group",
                                       group_id=group_id_manage)
                            group_catalogue.clear()
                            group_items.clear()
                            st.session_state.pop("bulk_result",None)
                            st.session_state.pop("group_statistics_result",None)
                            st.rerun()
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(f"No se pudo eliminar el grupo: {type(exc).__name__}")



with tab5:
    st.subheader("Manage PR")
    st.caption("Entrega física en mano. Registro manual independiente del almacén y de las recepciones ERP.")
    try:
        pr_auth_configured=bool(st.secrets.get("auth"))
        pr_admin_emails=str(st.secrets.get("BULK_ADMIN_EMAILS",""))
        pr_admin_dsn=st.secrets.get("BULK_ADMIN_DATABASE_URL")
    except (KeyError,FileNotFoundError):
        pr_auth_configured=False
        pr_admin_emails=""
        pr_admin_dsn=None
    pr_identity=st.user.to_dict() if pr_auth_configured else {}
    pr_admin=is_bulk_admin(pr_identity,pr_admin_emails) and bool(pr_admin_dsn)
    if pr_auth_configured and not pr_identity.get("is_logged_in"):
        if st.button("Iniciar sesión con Google",key="pr_login"):
            st.login("google")
    if not pr_admin:
        st.info("Manage PR requiere la misma cuenta administradora verificada que Manage SC.")
    else:
        @st.dialog("Confirmar entrega física")
        def confirm_hand_delivery(pr,qty,day,nbi,warnings):
            st.write(f"Registrar **PR {pr}**, **Qty {str(qty).replace('.', ',')}**, **{day.strftime('%d/%m/%Y')}**, **NBI {nbi}**.")
            for warning in warnings:
                st.warning(warning)
            st.caption("Esta operación no modifica el ERP ni las existencias de almacén.")
            left,right=st.columns(2)
            with left:
                if st.button("Cancelar",key="pr_cancel_insert",use_container_width=True):
                    st.session_state["pr_grid_revision"]=st.session_state.get("pr_grid_revision",0)+1
                    st.rerun()
            with right:
                if st.button("Confirmar entrega",key="pr_confirm_insert",type="primary",
                             use_container_width=True):
                    try:
                        write_hand_delivery(pr_admin_dsn,pr_identity,pr_admin_emails,"insert",
                                            pr_no=pr,quantity=str(qty),delivery_date=day,
                                            received_by_nbi=nbi,
                                            today=datetime.now(ZoneInfo("Europe/Madrid")).date())
                    except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                        st.error(f"No se pudo registrar: {str(exc) if isinstance(exc,ValueError) else type(exc).__name__}")
                    else:
                        hand_deliveries.clear()
                        st.session_state["pr_grid_revision"]=st.session_state.get("pr_grid_revision",0)+1
                        st.session_state["pr_notice"]="Entrega física registrada."
                        st.rerun()

        @st.dialog("Anular entrega física")
        def confirm_void_hand_delivery(entry_id,pr,qty,day):
            st.write(f"¿Anular la entrega de **PR {pr}**, Qty **{qty}**, del **{day}**?")
            st.caption("La entrada permanecerá en el histórico de auditoría.")
            left,right=st.columns(2)
            with left:
                if st.button("Cancelar",key=f"pr_cancel_void_{entry_id}",use_container_width=True):
                    st.session_state["pr_grid_revision"]=st.session_state.get("pr_grid_revision",0)+1
                    st.rerun()
            with right:
                if st.button("Confirmar anulación",key=f"pr_confirm_void_{entry_id}",
                             type="primary",use_container_width=True):
                    try:
                        write_hand_delivery(pr_admin_dsn,pr_identity,pr_admin_emails,"void",
                                            entry_id=entry_id)
                    except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                        st.error(f"No se pudo anular: {str(exc) if isinstance(exc,ValueError) else type(exc).__name__}")
                    else:
                        hand_deliveries.clear()
                        st.session_state["pr_grid_revision"]=st.session_state.get("pr_grid_revision",0)+1
                        st.session_state["pr_notice"]="Entrega anulada; histórico conservado."
                        st.rerun()

        @st.fragment
        def render_hand_deliveries():
            from src.quantity_format import format_quantity
            if st.session_state.get("pr_notice"):
                st.success(st.session_state.pop("pr_notice"))
            today=datetime.now(ZoneInfo("Europe/Madrid")).date()
            with st.form("pr_add_delivery",clear_on_submit=True):
                a,b,c,d=st.columns([2,1,2,2],gap="small")
                with a:
                    entered_pr=st.text_input("PR",placeholder="Número de parte")
                with b:
                    entered_qty=st.text_input("Qty",placeholder="0,00")
                with c:
                    entered_date=st.date_input("Fecha entrega",value=today,
                                               format="DD/MM/YYYY",max_value=today)
                with d:
                    entered_nbi=st.text_input("Recibido por NBI",placeholder="NBI",max_chars=40)
                submitted=st.form_submit_button("Añadir entrega",icon=":material/add:")
            ledger=hand_deliveries()
            if submitted:
                try:
                    pr=normalize_pr(entered_pr)
                    qty=normalize_quantity(entered_qty)
                    day=normalize_delivery_date(entered_date,today=today)
                    nbi=normalize_nbi(entered_nbi)
                    warnings=[]
                    if duplicate_warning(ledger.to_dict("records"),pr,qty,day,today=today):
                        warnings.append("Ya existe una entrega activa con el mismo PR, Qty y fecha. Comprueba que no es un duplicado.")
                    # Snapshot-specific cross-check is advisory only; manual history
                    # must survive later imports and unknown ERP PRs.
                    erp=query("""SELECT count(*) AS n,
                                        sum(delivered_qty) AS received_qty,
                                        sum(approved_qty) AS approved_qty
                                 FROM core.receipts
                                 WHERE snapshot_id=%s AND receipt_no=%s""",(sid,pr))
                    if not erp.empty:
                        evidence=erp.iloc[0]
                        if int(evidence["n"])==0:
                            warnings.append("PR no encontrado en el snapshot seleccionado. Se registrará pendiente de conciliación.")
                        elif int(evidence["n"])>1:
                            warnings.append("PR con varios movimientos ERP; revisar antes de comparar cantidades.")
                        else:
                            from decimal import Decimal
                            registered=sum((Decimal(str(x["quantity"])) for x in ledger.to_dict("records")
                                            if str(x["pr_no"])==pr),Decimal("0"))
                            approved=evidence["approved_qty"]
                            if approved is not None and not pd.isna(approved) and registered+qty>approved:
                                warnings.append("La cantidad acumulada entregada en mano supera la cantidad aprobada ERP del snapshot. Verifica el PR.")
                    confirm_hand_delivery(pr,qty,day,nbi,warnings)
                except ValueError as exc:
                    st.error(str(exc))
            with st.expander("Importación múltiple de PR", expanded=False):
                if st.session_state.pop("pr_batch_clear_input",False):
                    st.session_state["pr_batch_input"]=""
                st.caption("Pega grupos PR;Qty;DD/MM/AAAA;NBI consecutivos, separados por punto y coma (máximo 200).")
                bulk_text=st.text_area(
                    "Lista de entregas",
                    placeholder="769071;3;06/11/2026;8579;769072;20;06/11/2026;8579",
                    height=110,key="pr_batch_input",
                )
                if st.button("Validar y ver vista previa",key="pr_batch_validate"):
                    try:
                        candidate=parse_pr_batch(bulk_text,today=today)
                        prs=sorted({record[0] for record in candidate})
                        erp_frame=query(
                            """SELECT receipt_no,count(*) AS n,
                                      sum(approved_qty) AS approved_qty
                               FROM core.receipts
                               WHERE snapshot_id=%s AND receipt_no=ANY(%s)
                               GROUP BY receipt_no""", (sid,prs),
                        )
                        erp_map={str(r["receipt_no"]):r for r in erp_frame.to_dict("records")}
                        notes=batch_warnings(candidate,ledger.to_dict("records"),erp_map)
                        st.session_state["pr_batch_preview"]={
                            "text":bulk_text,"snapshot_id":sid,"records":candidate,
                            "digest":batch_digest(candidate),"warnings":notes,
                        }
                        st.session_state["pr_batch_ack"]=False
                    except ValueError as exc:
                        st.session_state.pop("pr_batch_preview",None)
                        st.error(str(exc))
                preview=st.session_state.get("pr_batch_preview")
                if preview and (preview["text"]!=bulk_text or preview["snapshot_id"]!=sid):
                    # Never confirm changed or snapshot-mismatched input.
                    st.session_state.pop("pr_batch_preview",None)
                    preview=None
                    st.info("Texto o snapshot cambiado: vuelve a validar.")
                if preview:
                    st.markdown(f"**Vista previa · {len(preview['records'])} entregas**")
                    display=pd.DataFrame(
                        [(pr,format_quantity(qty),day.strftime("%d/%m/%Y"),nbi)
                         for pr,qty,day,nbi in preview["records"]],
                        columns=["PR","Qty","Fecha entrega","Recibido por NBI"],
                    )
                    st.dataframe(display,use_container_width=True,hide_index=True,
                                 height=min(380,38+len(display)*35))
                    notes=preview["warnings"]
                    if notes:
                        st.warning(f"{len(notes)} advertencias. Revisa los casos antes de confirmar.")
                        for note in notes[:20]:
                            st.caption("• "+note)
                        if len(notes)>20:
                            st.caption(f"Y {len(notes)-20} advertencias adicionales.")
                        acknowledge=st.checkbox("He revisado las advertencias y confirmo el lote",
                                                key="pr_batch_ack")
                    else:
                        acknowledge=True
                        st.success("Formato validado. No se han detectado advertencias.")
                    if st.button("Confirmar e importar lote",type="primary",
                                 disabled=not acknowledge,key="pr_batch_confirm"):
                        try:
                            current=parse_pr_batch(bulk_text,today=today)
                            if batch_digest(current)!=preview["digest"]:
                                raise ValueError("La lista cambió después de la vista previa.")
                            result=insert_pr_batch(
                                pr_admin_dsn,pr_identity,pr_admin_emails,current,
                                expected_digest=preview["digest"],today=today,
                            )
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(str(exc) if isinstance(exc,ValueError) else
                                     f"No se pudo importar el lote: {type(exc).__name__}")
                        else:
                            st.session_state.pop("pr_batch_preview",None)
                            st.session_state["pr_batch_clear_input"]=True
                            if result["inserted"]:
                                hand_deliveries.clear()
                                st.session_state["pr_notice"]=(
                                    f"Lote #{result['batch_id']} importado: "
                                    f"{result['count']} entregas.")
                            else:
                                st.session_state["pr_notice"]=(
                                    "Este lote ya estaba importado. No se han duplicado entregas.")
                            st.session_state["pr_grid_revision"]=st.session_state.get("pr_grid_revision",0)+1
                            st.rerun()

            st.markdown("**Entregas reales registradas**")
            if ledger.empty:
                st.caption("Sin entregas físicas registradas.")
            else:
                # Enforce newest actual delivery date first, then newest entry
                # for equal dates, even if the cached DataFrame order changes.
                visible=ledger.sort_values(
                    ["delivery_date","id"],ascending=[False,False],kind="stable"
                )[["id","pr_no","quantity","delivery_date","received_by_nbi",
                   "erp_traceability_comment"]].copy()
                # Read the latest validated ERP snapshot regardless of the user's
                # historical selection in the rest of the dashboard.
                current_erp_snapshot=latest_snapshot_id(available_snapshots())
                pr_numbers=tuple(sorted(set(visible["pr_no"].astype(str))))
                try:
                    relation_frame=query(PR_RELATIONS_SQL,(current_erp_snapshot,list(pr_numbers)))
                    resolved=resolve_pr_relations(pr_numbers,relation_frame.to_dict("records"))
                except (psycopg.Error,KeyError,ValueError):
                    st.warning("Trazabilidad no disponible; se muestran los datos manuales.")
                    resolved={pr:{"Description":"—","Proyecto":"—","Pedido/pos":"—",
                                  "Proveedor":"—","Observaciones":"Consulta de trazabilidad no disponible"}
                              for pr in pr_numbers}
                for column in ("Description","Proyecto","Pedido/pos","Proveedor","Observaciones"):
                    visible[column]=visible["pr_no"].astype(str).map(lambda pr:resolved[pr][column])
                # Retain the audited backfill annotation even when a newer snapshot
                # supplies the currently displayed purchase descriptions.
                def comments_for_row(row):
                    history=row["erp_traceability_comment"]
                    history="" if pd.isna(history) else str(history).strip()
                    current=str(row["Observaciones"] or "").strip()
                    return " · ".join(part for part in (current,history) if part)
                visible["Observaciones"]=visible.apply(comments_for_row,axis=1)
                visible=visible.drop(columns=["erp_traceability_comment"])
                visible["received_by_nbi"]=visible["received_by_nbi"].fillna("—").astype(str)
                visible["quantity"]=visible["quantity"].map(format_quantity)
                visible["delivery_date"]=visible["delivery_date"].map(lambda x:x.strftime("%d/%m/%Y"))
                visible.insert(0,"delete","X")
                event_js=JsCode("""
                    function({streamlitRerunEventTriggerName,eventData}) {
                        if (streamlitRerunEventTriggerName!=='cellClicked' || !eventData ||
                            !eventData.data || !eventData.column ||
                            eventData.column.getColId()!=='delete') return null;
                        return {id:eventData.data.id};
                    }
                """)
                should_js=JsCode("""
                    function({streamlitRerunEventTriggerName,eventData}) {
                        return streamlitRerunEventTriggerName==='cellClicked' &&
                          !!eventData && !!eventData.column &&
                          eventData.column.getColId()==='delete';
                    }
                """)
                options={
                    "columnDefs":[
                        {"field":"delete","headerName":"","width":38,"minWidth":38,"maxWidth":38,
                         "pinned":"left","sortable":False,"resizable":False,
                         "cellStyle":{"color":"#B91C1C","fontWeight":"700",
                                      "textAlign":"center","cursor":"pointer",
                                      "paddingLeft":"0","paddingRight":"0"}},
                        {"field":"pr_no","headerName":"PR","minWidth":110,"flex":2},
                        {"field":"quantity","headerName":"Qty","minWidth":90,"flex":1},
                        {"field":"Description","headerName":"Description","minWidth":280,"flex":4,
                         "tooltipField":"Description"},
                        {"field":"Proyecto","headerName":"Proyecto","minWidth":110,"flex":1},
                        {"field":"Pedido/pos","headerName":"Pedido/pos","minWidth":120,"flex":1.3},
                        {"field":"Proveedor","headerName":"Proveedor (nombre)","minWidth":230,"flex":3,
                         "tooltipField":"Proveedor"},
                        {"field":"delivery_date","headerName":"Fecha entrega","minWidth":140,"flex":2,
                         "sortable":True,"sort":"desc",
                         "comparator":JsCode("""
                            function(a,b) {
                                const order = value => {
                                    if (typeof value !== 'string') return 0;
                                    const parts = value.split('/');
                                    if (parts.length !== 3) return 0;
                                    return Number(parts[2])*10000+
                                           Number(parts[1])*100+Number(parts[0]);
                                };
                                return order(a)-order(b);
                            }
                         """)},
                        {"field":"received_by_nbi","headerName":"NBI","minWidth":95,"flex":1},
                        {"field":"Observaciones","headerName":"Observaciones","minWidth":260,"flex":3,
                         "tooltipField":"Observaciones"},
                    ],
                    "defaultColDef":{"editable":False,"filter":False,"sortable":False,
                                     "resizable":True},
                    "rowHeight":32,"headerHeight":32,
                    "getRowId":JsCode("function(p){return String(p.data.id);}"),
                    "suppressMovableColumns":True
                }
                result=AgGrid(
                    visible,gridOptions=options,
                    height=min(480,40+len(visible)*32),
                    theme="streamlit",allow_unsafe_jscode=True,
                    enable_enterprise_modules=False,
                    data_return_mode=DataReturnMode.CUSTOM,
                    custom_jscode_for_grid_return=event_js,
                    should_grid_return=should_js,
                    update_on=["cellClicked"],
                    key=f"pr_hand_delivery_grid_{st.session_state.get('pr_grid_revision',0)}",
                    show_toolbar=False,show_search=False,show_download_button=False,
                    server_sync_strategy="server_wins",
                    custom_css={".ag-root-wrapper":{"borderRadius":"0px !important"}},
                )
                selected=result.raw_data if hasattr(result,"raw_data") else None
                if isinstance(selected,dict) and str(selected.get("id","")).isdigit():
                    entry=ledger.loc[ledger["id"]==int(selected["id"])]
                    if len(entry)==1:
                        item=entry.iloc[0]
                        confirm_void_hand_delivery(int(item["id"]),str(item["pr_no"]),
                                                   format_quantity(item["quantity"]),
                                                   item["delivery_date"].strftime("%d/%m/%Y"))
        render_hand_deliveries()
