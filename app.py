"""Read-only procurement planning dashboard."""
import os
from datetime import datetime
import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st

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
    search=st.text_input("Buscar SC, artículo o pedido","",key="sc_search",placeholder="Número SC o artículo")
    conditions="s.snapshot_id=%s"
    values=[sid]
    if project!="Todos":
        conditions+=" AND s.project=%s";values.append(project)
    if search.strip():
        conditions+=" AND (s.sc_no ILIKE %s OR s.article ILIKE %s OR EXISTS (SELECT 1 FROM core.sc_po_links l WHERE l.snapshot_id=s.snapshot_id AND l.company=s.company AND l.sc_no=s.sc_no AND l.sc_pos=s.sc_pos AND l.po_no ILIKE %s))"
        values.extend(["%"+search.strip()+"%"]*3)
    if workflow_ready:
        overview=query("SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,s.workflow_state,s.workflow_issue FROM planning.sc_workflow_status s WHERE "+conditions+" ORDER BY s.sc_no,s.sc_pos LIMIT 2000",tuple(values))
    else:
        overview=query("SELECT s.company,s.sc_no,s.sc_pos,s.article,s.description,s.project,s.requested_qty,s.ordered_qty,s.received_qty,s.approved_qty,s.coverage_state,s.coverage_pct FROM planning.v_sc_coverage s WHERE "+conditions+" ORDER BY s.sc_no,s.sc_pos LIMIT 2000",tuple(values))
    st.dataframe(overview,use_container_width=True,hide_index=True)
    if len(overview)==2000:
        st.warning("Se muestran las primeras 2.000 líneas. Refina la búsqueda para ver el resto.")
    if not overview.empty:
        options=list(range(len(overview)))
        selected=st.selectbox("Examinar trazabilidad de una línea SC",options,format_func=lambda i:f"{overview.iloc[i]['sc_no']} / {overview.iloc[i]['sc_pos']} · {overview.iloc[i]['article']}")
        line=overview.iloc[selected]
        trace=query("""SELECT l.po_no,l.po_pos,p.vendor,p.ordered_qty,p.planned_date,
               r.receipt_no,r.receipt_date,r.delivered_qty,r.approved_qty,r.erp_status,l.allocation_status
               FROM core.sc_po_links l
               JOIN core.po_lines p ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=(l.snapshot_id,l.company,l.po_no,l.po_pos)
               LEFT JOIN core.receipts r ON (r.snapshot_id,r.po_no,r.po_pos)=(l.snapshot_id,l.po_no,l.po_pos)
               WHERE l.snapshot_id=%s AND l.company=%s AND l.sc_no=%s AND l.sc_pos=%s
               ORDER BY l.po_no,l.po_pos,r.receipt_date,r.receipt_no""",
               (sid,line["company"],line["sc_no"],line["sc_pos"]))
        st.dataframe(trace,use_container_width=True,hide_index=True)
        st.caption("Las cantidades de PO pueden repetirse por cada recepción en el detalle; no sumarlas desde esta tabla.")
        st.download_button("Exportar trazabilidad CSV",trace.to_csv(index=False,sep=";",decimal=",").encode("utf-8-sig"),
                           file_name="trazabilidad_sc.csv",mime="text/csv")
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
