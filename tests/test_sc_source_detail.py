"""Read-only SC detail from source CSV: normalization, PO pairing and UX."""
from datetime import date
import pandas as pd

from src.sc_source_detail import request_detail, planning_detail, MULTIPLE
from src.detail_view import detail_row_style


def sample_line():
    return {
        "article":"3040900280","description":"CILINDRO COMPACTO HIDRAULICO",
        "project":"11327","centre":"984",
        "project_director":"500010 MODERNIZACIÓN PIZARRO",
    }


def sample_raw():
    return {
        "FECHA APROBACIÓN__12":"25/09/26",
        "FECHA ENTREGA SOLICITUD__13":"05/11/26",
        "PEDIDO__16":"762070", "POSICIÓN__17":"1",
        "NOMBRE__24":"E.R. HIDRAULICA, SL",
        "COMPRADOR__45":"8389-WELSCH, THOMAS",
        "ESTADO COMPRAS__5":"Transferida",
        "FECHA APROBACIÓN DEL PEDIDO__41":"13/10/26",
        "FECHA PLANIFICADA__26":"30/11/26",
        "FECHA PLANIFICADA ACTUAL__27":"15/12/26",
        "IMPORTE__21":"3038,5200", "PRECIO €__20":"253,2100",
    }


def test_request_block_761453_and_original_dates():
    view=request_detail(sample_line(),[sample_raw()])
    mapping=dict(zip(view.Campo,view.Valor))
    assert mapping=={
        "Artículo":"3040900280",
        "Descripción":"CILINDRO COMPACTO HIDRAULICO",
        "Proyecto":"11327","Centro":"984",
        "Director":"500010 MODERNIZACIÓN PIZARRO",
        "Fecha aprobación SC":"25/09/2026",
        "Fecha entrega solicitada":"05/11/2026",
    }


def test_planning_block_preserves_current_plan_from_core():
    trace=pd.DataFrame([{"pedido":"762070","posicion_pedido":"1",
                         "fecha_planificada":date(2026,12,15),
                         "parte_recepcion":None}])
    view=planning_detail(trace,[sample_raw()])
    mapping=dict(zip(view.Campo,view.Valor))
    assert mapping=={
        "Pedido/Pos":"762070/1",
        "Proveedor":"E.R. HIDRAULICA, SL",
        "Comprador":"8389-WELSCH, THOMAS",
        "Estado compras ERP":"Transferida",
        "Fecha aprobación pedido":"13/10/2026",
        "Plan original":"30/11/2026",
        "Plan actual":"15/12/2026",
    }
    assert "precio" not in " ".join(view.Campo).lower()
    assert not view.astype(str).apply(lambda x:x.str.contains("3038|253,21")).any().any()
    assert all("#15803D" in s for s in detail_row_style(
        view.loc[view.Campo=="Plan actual"].iloc[0],date(2026,11,7),
        "Material sin recibir"))


def test_multiple_pos_each_gets_own_po_fields_without_cross_pollution():
    raw1=sample_raw()
    raw2={**sample_raw(),"PEDIDO__16":"00002","POSICIÓN__17":"3",
          "NOMBRE__24":"PROVEEDOR B",
          "FECHA PLANIFICADA__26":"30/01/27"}
    trace=pd.DataFrame([
        {"pedido":"762070","posicion_pedido":"1","fecha_planificada":date(2026,12,15),
         "parte_recepcion":"A"},
        {"pedido":"762070","posicion_pedido":"1","fecha_planificada":date(2026,12,15),
         "parte_recepcion":"B"},
        {"pedido":"00002","posicion_pedido":"3","fecha_planificada":date(2027,2,1),
         "parte_recepcion":None},
    ])
    view=planning_detail(trace,[raw1,raw2])
    assert view.loc[view.Campo=="Pedido/Pos","Valor"].tolist()==["762070/1","00002/3"]
    assert view.loc[view.Campo=="Proveedor","Valor"].tolist()==[
        "E.R. HIDRAULICA, SL","PROVEEDOR B"]
    assert view.loc[view.Campo=="Plan original","Valor"].tolist()==[
        "30/11/2026","30/01/2027"]
    assert view.loc[view.Campo=="Plan actual","Valor"].tolist()==[
        "15/12/2026","01/02/2027"]


def test_conflicting_origin_values_are_not_guessed_and_empty_safe():
    source=sample_raw()
    conflict={**source,"COMPRADOR__45":"Otro comprador",
              "FECHA PLANIFICADA__26":"01/12/26"}
    trace=pd.DataFrame([{"pedido":"762070","posicion_pedido":"1",
                         "fecha_planificada":date(2026,12,15)}])
    view=planning_detail(trace,[source,conflict])
    assert view.loc[view.Campo=="Comprador","Valor"].iloc[0]==MULTIPLE
    assert view.loc[view.Campo=="Plan original","Valor"].iloc[0]==MULTIPLE
    assert view.loc[view.Campo=="Plan actual","Valor"].iloc[0]=="15/12/2026"
    assert request_detail(sample_line(),[]).iloc[-1]["Valor"]=="—"
    assert planning_detail(pd.DataFrame(),[]).empty


def test_invalid_source_date_is_disclosed():
    source={**sample_raw(),"FECHA APROBACIÓN__12":"99/99/26"}
    view=request_detail(sample_line(),[source])
    assert view.loc[view.Campo=="Fecha aprobación SC","Valor"].iloc[0]=="Fecha de origen inválida"


def test_both_sc_tabs_share_new_detail_without_economic_data():
    from pathlib import Path
    app=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
    shared=app.split("def render_sc_detail(line, sid, context):",1)[1].split("with tab1:",1)[0]
    assert 'st.markdown("#### Datos de solicitud")' in shared
    assert 'st.markdown("#### Pedido y planificación")' in shared
    assert "raw.source_rows" in shared
    assert "source_name='SC_FAS.csv'" in shared
    assert '"COMPAÑÍA__0"' not in shared or "COMPAÑÍA__0" in shared
    assert 'request_detail(line,raw_records)' in shared
    assert 'planning_detail(trace,raw_records)' in shared
    assert 'export[["Sección","Campo","Valor"]]' in shared
    assert "st.markdown(\"#### Recepciones\")" in shared
    assert "st.markdown(\"#### REAC\")" in shared
    assert "st.markdown(\"#### Incidencias\")" in shared
    assert 'render_sc_detail(line, sid, context="seguimiento")' in app
    assert 'render_sc_detail(line, sid, context="group")' in app
    assert '"Precio unitario"' not in shared
    assert '"Importe"' not in shared
