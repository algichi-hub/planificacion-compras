"""Read-only procurement planning dashboard."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st
from src.detail_view import transpose_trace, receptions_table, detail_row_style, vertical_records
from src.sc_overview import overview_display, overview_row_style
from src.quantity_format import format_sc_quantities

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

if not connection_string():
    st.info("Configura DATABASE_URL como secreto del despliegue. No incluyas credenciales en Git.")
    st.stop()

try:
    snapshots=query("SELECT id,snapshot_date,state FROM audit.snapshots WHERE state IN ('active','validated') ORDER BY snapshot_date DESC")
except Exception as exc:
    st.error(f"No se ha podido consultar Neon: {type(exc).__name__}")
    st.stop()

if snapshots.empty:
    st.info("Base vacía. Ejecuta desde tu ordenador el importador de los tres CSV y activa el snapshot validado.")
    st.stop()

snapshots["label"]=snapshots.apply(lambda r:f"{r['snapshot_date']} · {r['state']} · #{r['id']}",axis=1)
active=snapshots[snapshots.state=="active"]
default_idx=int(active.index[0]) if not active.empty else 0
sid=int(st.sidebar.selectbox("Snapshot",snapshots["id"].tolist(),index=default_idx,
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

tab1,tab2,tab3,tab4=st.tabs(["Resumen","Seguimiento SC","REAC / Incidencias","Calidad de datos"])
has_workflow_table=query("SELECT to_regclass('planning.sc_workflow_status') IS NOT NULL AS available").iloc[0]["available"]
workflow_ready=False
if has_workflow_table:
    workflow_ready=bool(query("SELECT EXISTS(SELECT 1 FROM planning.sc_workflow_status WHERE snapshot_id=%s) AS ready",(sid,)).iloc[0]["ready"])
with tab1:
    if workflow_ready:
        states=query("SELECT workflow_state,count(*) AS n FROM planning.sc_workflow_status WHERE "+where+" GROUP BY workflow_state ORDER BY n DESC",tuple(params))
        total=int(states["n"].sum()) if not states.empty else 0
        cancelled=int(states.loc[states.workflow_state=="SC anulada","n"].sum()) if not states.empty else 0
        complete=int(states.loc[states.workflow_state=="Completado","n"].sum()) if not states.empty else 0
        uncertain=int(states.loc[states.workflow_state=="Pendiente conciliación","n"].sum()) if not states.empty else 0
        for col,(label,value) in zip(st.columns(4),[("Líneas SC",total),("Completadas",complete),("SC anuladas",cancelled),("Pendientes conciliación",uncertain)]):
            col.metric(label,value)
        st.plotly_chart(px.bar(states,x="workflow_state",y="n",title="Estado de tramitación por línea SC",labels={"workflow_state":"Estado","n":"Líneas SC"}),use_container_width=True)
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
        po_link_summary="""
          LEFT JOIN LATERAL (
              SELECT string_agg(l.po_no || '/' || l.po_pos, ', '
                                ORDER BY l.po_no,l.po_pos) AS po_positions,
                     min(p.planned_date) AS planned_date
              FROM core.sc_po_links l
              JOIN core.po_lines p
                ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=
                   (l.snapshot_id,l.company,l.po_no,l.po_pos)
              WHERE l.snapshot_id=s.snapshot_id AND l.company=s.company
                AND l.sc_no=s.sc_no AND l.sc_pos=s.sc_pos
          ) linked ON true
        """
        if workflow_ready:
            overview=query("""SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,
                    s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,
                    s.workflow_state,linked.po_positions,linked.planned_date
                    FROM planning.sc_workflow_status s
                    """+po_link_summary+"""
                    WHERE s.snapshot_id=%s AND s.sc_no=%s
                    ORDER BY s.company, CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                      THEN btrim(s.sc_pos)::numeric END NULLS LAST,s.sc_pos""",(sid,sc_number))
        else:
            overview=query("""SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,
                    s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,
                    s.coverage_state,linked.po_positions,linked.planned_date
                    FROM planning.v_sc_coverage s
                    """+po_link_summary+"""
                    WHERE s.snapshot_id=%s AND s.sc_no=%s
                    ORDER BY s.company, CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                      THEN btrim(s.sc_pos)::numeric END NULLS LAST,s.sc_pos""",(sid,sc_number))
        if overview.empty:
            st.info("No se encontraron posiciones para esa SC en el snapshot seleccionado.")
        else:
            st.caption(f"SC {sc_number} · {len(overview)} posiciones. Selecciona una fila para ver su detalle.")
            st.caption("PO/Pos muestra todos los pedidos asociados. fecha_plan corresponde a la fecha planificada más próxima entre ellos; las fechas vencidas aparecen en rojo y negrita.")
            # Preserve the original result for exact company/SC/position lookup.
            # The displayed DataFrame has exactly 11 user-requested columns.
            visible_overview=overview_display(overview)
            madrid_today=datetime.now(ZoneInfo("Europe/Madrid")).date()
            event=st.dataframe(
                format_sc_quantities(visible_overview.style).apply(
                    overview_row_style,axis=1,today=madrid_today
                ),use_container_width=True,hide_index=True,
                column_config={
                    name: st.column_config.Column(width="small")
                    for name in ("Sol", "Ped", "Rec", "Apr")
                },
                on_select="rerun",selection_mode="single-row",
                key=f"sc_overview_{sid}_{sc_number}",
            )
            selected_rows=event.selection.rows
            if selected_rows:
                line=overview.iloc[selected_rows[0]]
                st.subheader(f"Detalle SC {line['sc_no']} / posición {line['sc_pos']}")
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
                detail=transpose_trace(trace, line.get('workflow_state', line.get('coverage_state')))
                madrid_today=datetime.now(ZoneInfo("Europe/Madrid")).date()
                if trace.empty:
                    st.caption("Esta posición SC no tiene pedidos vinculados.")
                if not detail.empty:
                    st.dataframe(
                        detail.style.apply(detail_row_style,axis=1,today=madrid_today,
                                           workflow_state=line.get("workflow_state")),
                        use_container_width=True,hide_index=True,
                        column_config={"Campo": st.column_config.TextColumn(width="medium"),
                                       "Valor": st.column_config.TextColumn(width="large")},
                        height=min(720,35*(len(detail)+1)+3),
                    )
                    st.caption("Solo en estado «Material sin recibir»: fecha planificada vencida en rojo; hasta 7 días naranja; 8–14 días amarillo; más de 14 días verde. Texto en negrita, sin fondo.")
                    st.download_button(
                        "Exportar detalle CSV",
                        detail.to_csv(index=False,sep=";").encode("utf-8-sig"),
                        file_name=f"detalle_SC_{line['sc_no']}_{line['sc_pos']}.csv",
                        mime="text/csv",
                    )
                st.markdown("#### Recepciones asociadas a esta posición SC")
                receptions=receptions_table(trace)
                if receptions.empty:
                    st.caption("Sin recepciones registradas para los pedidos vinculados.")
                else:
                    st.dataframe(receptions,width="content",hide_index=True,
                                 column_config={"Campo": st.column_config.TextColumn(),
                                                "Valor": st.column_config.TextColumn()},
                                 height=min(720,35*(len(receptions)+1)+3))
                    st.caption("Recepción: número (fecha, Re: recibida, Ap: aprobada, En: entregada). El origen no separa recibido de entregado: Re y En reflejan la misma cantidad de la recepción; no se suman entre sí.")
                    st.download_button(
                        "Exportar recepciones CSV",
                        receptions.to_csv(index=False,sep=";").encode("utf-8-sig"),
                        file_name=f"recepciones_SC_{line['sc_no']}_{line['sc_pos']}.csv",
                        mime="text/csv",
                    )
                # REAC is keyed to the selected SC position; it is not an operational state.
                st.markdown("#### REAC asociados a esta posición SC")
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
                    st.dataframe(reac_vertical,use_container_width=True,hide_index=True)
                    st.caption("REAC documental: no se infiere cantidad rechazada ni estado de aprobación.")

                # INC has no company/SC identifier: link conservatively by PO/position
                # and disclose the article match instead of asserting exact SC ownership.
                st.markdown("#### Incidencias asociadas a los pedidos de esta posición SC")
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
                    st.dataframe(inc_vertical,use_container_width=True,hide_index=True)
                    st.caption("INC vinculada por pedido y posición; el fichero INC carece de compañía/SC. Revisar las coincidencias de artículo y cualquier vinculación compartida.")
with tab3:
    st.subheader("REAC asociados a SC")
    reac=query("""SELECT r.sc_no,r.sc_pos,r.po_no,r.po_pos,r.reac_no,r.reac_article
                  FROM core.reac_refs r WHERE r.snapshot_id=%s
                  ORDER BY r.sc_no,r.sc_pos LIMIT 3000""",(sid,))
    st.dataframe(reac,use_container_width=True,hide_index=True)
    st.caption("REAC referido en el extracto SC; no se asigna automáticamente una cantidad rechazada.")
    st.subheader("Incidencias de almacén")
    incidents=query("""SELECT record_no,sequence_no,po_no,po_pos,article,category,resolved,detail
                        FROM core.incidents WHERE snapshot_id=%s
                        ORDER BY record_no DESC LIMIT 3000""",(sid,))
    st.dataframe(incidents,use_container_width=True,hide_index=True)
    st.caption("Las incidencias sin posición fiable no se asignan automáticamente a una recepción.")
with tab4:
    issues=query("""SELECT source_name,line_number,severity,issue_code,details FROM audit.import_issues
                    WHERE snapshot_id=%s ORDER BY CASE severity WHEN 'error' THEN 0 ELSE 1 END,id LIMIT 5000""",(sid,))
    st.dataframe(issues,use_container_width=True,hide_index=True)
    totals=query("SELECT source_name,rows_total,rows_ok,rows_invalid FROM audit.source_files WHERE snapshot_id=%s ORDER BY source_name",(sid,))
    st.dataframe(totals,use_container_width=True,hide_index=True)
    st.download_button("Exportar incidencias de calidad",issues.to_csv(index=False,sep=";").encode("utf-8-sig"),
                       file_name="calidad_datos.csv",mime="text/csv")
