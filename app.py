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
from src.group_sc_view import group_overview, group_overview_source
from src.quantity_format import format_sc_quantities
from src.bulk_sc import is_bulk_admin, write_bulk

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

tab1,tab2,tab3,tab4=st.tabs(["Resumen","Seguimiento SC","Group SC","Manage"])
has_workflow_table=query("SELECT to_regclass('planning.sc_workflow_status') IS NOT NULL AS available").iloc[0]["available"]
workflow_ready=False
if has_workflow_table:
    workflow_ready=bool(query("SELECT EXISTS(SELECT 1 FROM planning.sc_workflow_status WHERE snapshot_id=%s) AS ready",(sid,)).iloc[0]["ready"])
# Reuse one SC/PO reconciliation expression in individual and grouped queries.
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

def overview_column_config():
    """Keep the exact same native column configuration in both SC views."""
    return {
        **{name: st.column_config.Column(width=None)
           for name in ("Sol", "Ped", "Rec", "Apr")},
        " ": st.column_config.ImageColumn("", width=38, pinned=True,
            help="Estado operativo SC"),
    }

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
            key=f"{widget_prefix}_detail",
        )
        st.caption("Solo en estado «Material sin recibir»: fechas vencidas en rojo; entre hoy y los próximos 7 días naturales en amarillo; a más de 7 días en verde. Texto en negrita, sin fondo.")
        st.download_button(
            "Exportar detalle CSV",
            detail.to_csv(index=False,sep=";").encode("utf-8-sig"),
            file_name=f"detalle_SC_{line['sc_no']}_{line['sc_pos']}.csv",
            mime="text/csv",
            key=f"{widget_prefix}_download_detail",
        )
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
        st.download_button(
            "Exportar recepciones CSV",
            receptions.to_csv(index=False,sep=";").encode("utf-8-sig"),
            file_name=f"recepciones_SC_{line['sc_no']}_{line['sc_pos']}.csv",
            mime="text/csv",
            key=f"{widget_prefix}_download_receptions",
        )
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
            st.caption("PO/Pos muestra todos los pedidos asociados. fecha_plan corresponde a la fecha planificada más próxima entre ellos. Para Material sin recibir: rojo si vencida, amarillo si faltan de 0 a 7 días naturales y verde si faltan más de 7 días.")
            # Preserve the original result for exact company/SC/position lookup.
            # The displayed DataFrame adds a status-symbol column without altering selection.
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
            selected_rows=event.selection.rows
            if selected_rows:
                line=overview.iloc[selected_rows[0]]
                render_sc_detail(line, sid, context="seguimiento")

# Shared, read-only group catalogue. Admin privileges are evaluated only in Manage.
try:
    groups=query("SELECT id,name,description FROM planning.bulk_sc_groups ORDER BY name")
except psycopg.Error:
    groups=pd.DataFrame(columns=["id","name","description"])

with tab3:
    st.subheader("Group SC")
    st.caption("Consulta e informes de grupos SC. Los estados y cantidades corresponden al snapshot seleccionado.")
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
        items=query("""SELECT id,sc_no,context_description
                       FROM planning.bulk_sc_items
                       WHERE group_id=%s ORDER BY sc_no""",(group_id,))
        st.dataframe(items[["sc_no","context_description"]].rename(columns={
            "sc_no":"SC","context_description":"Descripción contextual"
        }),hide_index=True,use_container_width=True)
        if items.empty:
            st.info("Este grupo todavía no tiene SC asociadas.")
        else:
            # Always query the selected snapshot when the user requests a report.
            # Group records are lightweight and cached with the existing 10-min TTL.
            if st.button("Consultar grupo",type="primary",key="group_sc_report"):
                numbers=items["sc_no"].astype(str).tolist()
                source_table=("planning.sc_workflow_status" if workflow_ready
                              else "planning.v_sc_coverage")
                status_column="workflow_state" if workflow_ready else "coverage_state"
                group_status=query(f"""SELECT s.company,s.sc_no,s.sc_pos,s.article,
                               s.description,s.project,s.requested_qty,s.ordered_qty,
                               s.received_qty,s.approved_qty,s.{status_column},
                               linked.po_positions,linked.planned_date
                               FROM {source_table} s
                               """+po_link_summary+"""
                               WHERE s.snapshot_id=%s AND s.sc_no=ANY(%s)
                               ORDER BY s.company,s.sc_no,
                                   CASE WHEN btrim(s.sc_pos) ~ '^[0-9]+$'
                                       THEN btrim(s.sc_pos)::numeric END NULLS LAST,
                                   s.sc_pos""",(sid,numbers))
                grouped=group_overview(items,group_status)
                group_source=group_overview_source(items,group_status)
                st.session_state["bulk_result"]=(sid,group_id,grouped,group_source)
            stored=st.session_state.get("bulk_result")
            if stored and stored[0]==sid and stored[1]==group_id:
                bulk_view=stored[2]
                st.caption(f"{len(items)} SC · {len(bulk_view)} posiciones o referencias")
                madrid_today=datetime.now(ZoneInfo("Europe/Madrid")).date()
                event_group=st.dataframe(
                    format_sc_quantities(bulk_view.style).apply(
                        overview_row_style,axis=1,today=madrid_today
                    ),
                    hide_index=True,use_container_width=True,
                    column_config=overview_column_config(),
                    on_select="rerun",selection_mode="single-row",
                    key=f"group_sc_overview_{sid}_{group_id}",
                )
                if event_group.selection.rows:
                    selected_index=event_group.selection.rows[0]
                    group_source=stored[3]
                    line=group_source.iloc[selected_index]
                    if pd.isna(line.get("company")) or pd.isna(line.get("sc_pos")):
                        st.info("Esta SC no figura en el snapshot seleccionado; no hay detalle que consultar.")
                    else:
                        render_sc_detail(line, sid, context="group")

with tab4:
    st.subheader("Manage")
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
                        query.clear()
                        st.session_state.pop("bulk_result",None)
                        st.rerun()
                    except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                        st.error(f"No se pudo guardar el grupo: {type(exc).__name__}")

        if not groups.empty:
            group_id_manage=int(st.selectbox(
                "Grupo para gestionar",groups["id"].tolist(),key="manage_group_select",
                format_func=lambda x:groups.loc[groups.id==x,"name"].iloc[0],
            ))
            selected_group=groups.loc[groups.id==group_id_manage].iloc[0]
            items_manage=query("""SELECT id,sc_no,context_description
                                  FROM planning.bulk_sc_items
                                  WHERE group_id=%s ORDER BY sc_no""",(group_id_manage,))
            st.caption("Edita directamente la SC o la descripción y sal de la celda para guardar. "
                       "Las altas se guardan cuando ambos campos están completos.")
            st.markdown("""
                <style>
                [class*="st-key-manage_delete_"] button {
                    color: #B91C1C !important;
                    border: 1px solid #B91C1C !important;
                    background: transparent !important;
                }
                [class*="st-key-manage_delete_"] button:hover {
                    background: #FEF2F2 !important;
                }
                </style>
            """, unsafe_allow_html=True)

            def _invalidate_group_report():
                query.clear()
                st.session_state.pop("bulk_result", None)

            def _save_existing_item(item_id, original_sc, original_description):
                key_sc=f"manage_sc_{group_id_manage}_{item_id}"
                key_desc=f"manage_desc_{group_id_manage}_{item_id}"
                message_key=f"manage_status_{group_id_manage}_{item_id}"
                sc_value=st.session_state[key_sc]
                desc_value=st.session_state[key_desc]
                if sc_value == original_sc and desc_value == original_description:
                    st.session_state.pop(message_key, None)
                    return
                try:
                    write_bulk(admin_dsn,identity,admin_emails,"edit_item",
                               group_id=group_id_manage,item_id=item_id,
                               sc_no=sc_value,description=desc_value)
                except ValueError as exc:
                    st.session_state[message_key]=str(exc)
                except (psycopg.Error, PermissionError, RuntimeError):
                    st.session_state[message_key]="Error de guardado. Revisa la conexión y vuelve a editar la celda."
                else:
                    _invalidate_group_report()
                    st.session_state[message_key]="Guardado"

            draft_key=f"manage_drafts_{group_id_manage}"
            st.session_state.setdefault(draft_key, [])

            def _add_blank_sc():
                counter=int(st.session_state.get("manage_draft_counter",0))+1
                st.session_state["manage_draft_counter"]=counter
                st.session_state[draft_key].append(counter)

            def _save_new_item(draft_id):
                key_sc=f"manage_new_sc_{group_id_manage}_{draft_id}"
                key_desc=f"manage_new_desc_{group_id_manage}_{draft_id}"
                message_key=f"manage_new_status_{group_id_manage}_{draft_id}"
                sc_value=st.session_state[key_sc].strip()
                desc_value=st.session_state[key_desc].strip()
                if not sc_value or not desc_value:
                    st.session_state.pop(message_key,None)
                    return  # Incomplete drafts must never be written to Neon.
                try:
                    write_bulk(admin_dsn,identity,admin_emails,"insert_item",
                               group_id=group_id_manage,sc_no=sc_value,
                               description=desc_value)
                except ValueError as exc:
                    st.session_state[message_key]=str(exc)
                except (psycopg.Error, PermissionError, RuntimeError):
                    st.session_state[message_key]="Error de guardado. Revisa la conexión e inténtalo de nuevo."
                else:
                    st.session_state[draft_key].remove(draft_id)
                    st.session_state.pop(message_key,None)
                    _invalidate_group_report()

            @st.dialog("Confirmar borrado")
            def _confirm_remove_item(item_id, sc_number):
                st.write(f"¿Borrar la SC **{sc_number}** de este grupo?")
                st.caption("La eliminación no modifica los datos originales del ERP.")
                cancel_col, confirm_col=st.columns(2)
                with cancel_col:
                    if st.button("Cancelar",key=f"manage_cancel_{item_id}",use_container_width=True):
                        st.rerun()
                with confirm_col:
                    if st.button("Confirmar borrado",type="primary",
                                 key=f"manage_confirm_{item_id}",use_container_width=True):
                        try:
                            write_bulk(admin_dsn,identity,admin_emails,"remove_item",
                                       group_id=group_id_manage,item_id=item_id)
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(f"No se pudo borrar la SC: {type(exc).__name__}")
                        else:
                            _invalidate_group_report()
                            for prefix in ("manage_sc_","manage_desc_","manage_status_"):
                                st.session_state.pop(f"{prefix}{group_id_manage}_{item_id}",None)
                            st.rerun()

            st.markdown("**SC del grupo**")
            h_sc,h_desc,h_action=st.columns([2,5,1.35],vertical_alignment="center")
            h_sc.caption("SC")
            h_desc.caption("Descripción contextual")
            h_action.caption("Acción")
            for item in items_manage.itertuples(index=False):
                item_id=int(item.id)
                sc_before=str(item.sc_no)
                desc_before=str(item.context_description)
                sc_key=f"manage_sc_{group_id_manage}_{item_id}"
                desc_key=f"manage_desc_{group_id_manage}_{item_id}"
                st.session_state.setdefault(sc_key,sc_before)
                st.session_state.setdefault(desc_key,desc_before)
                c_sc,c_desc,c_action=st.columns([2,5,1.35],vertical_alignment="bottom")
                with c_sc:
                    st.text_input("SC",key=sc_key,max_chars=40,
                                  label_visibility="collapsed",
                                  on_change=_save_existing_item,
                                  args=(item_id,sc_before,desc_before))
                with c_desc:
                    st.text_input("Descripción contextual",key=desc_key,max_chars=500,
                                  label_visibility="collapsed",
                                  on_change=_save_existing_item,
                                  args=(item_id,sc_before,desc_before))
                with c_action:
                    if st.button("Borrar",key=f"manage_delete_{group_id_manage}_{item_id}",
                                 use_container_width=True):
                        _confirm_remove_item(item_id,sc_before)
                status=st.session_state.get(f"manage_status_{group_id_manage}_{item_id}")
                if status and status != "Guardado":
                    st.error(f"SC {sc_before}: {status}")
                elif status:
                    st.caption(f"SC {sc_before}: ✓ Guardado")
            for draft_id in list(st.session_state[draft_key]):
                sc_key=f"manage_new_sc_{group_id_manage}_{draft_id}"
                desc_key=f"manage_new_desc_{group_id_manage}_{draft_id}"
                d_sc,d_desc,d_action=st.columns([2,5,1.35],vertical_alignment="bottom")
                with d_sc:
                    st.text_input("Nueva SC",key=sc_key,max_chars=40,
                                  label_visibility="collapsed",placeholder="Número SC",
                                  on_change=_save_new_item,args=(draft_id,))
                with d_desc:
                    st.text_input("Nueva descripción",key=desc_key,max_chars=500,
                                  label_visibility="collapsed",placeholder="Descripción contextual",
                                  on_change=_save_new_item,args=(draft_id,))
                with d_action:
                    if st.button("Cancelar",key=f"manage_cancel_draft_{group_id_manage}_{draft_id}",
                                 use_container_width=True):
                        st.session_state[draft_key].remove(draft_id)
                        st.rerun()
                status=st.session_state.get(f"manage_new_status_{group_id_manage}_{draft_id}")
                if status:
                    st.error(f"Nueva SC: {status}")
            st.button("Añadir nueva SC",icon=":material/add:",on_click=_add_blank_sc,
                      key=f"manage_add_row_{group_id_manage}")

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
                            query.clear()
                            st.session_state.pop("bulk_result",None)
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
                            query.clear()
                            st.session_state.pop("bulk_result",None)
                            st.rerun()
                        except (ValueError,psycopg.Error,PermissionError,RuntimeError) as exc:
                            st.error(f"No se pudo eliminar el grupo: {type(exc).__name__}")

