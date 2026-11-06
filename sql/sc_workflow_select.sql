-- Snapshot-specific read-only classification. Parameter: snapshot_id (BIGINT).
WITH src AS (
 SELECT s.snapshot_id,s.company,s.sc_no,s.sc_pos,s.article,s.description,s.project,
        s.requested_qty,s.qty_status
 FROM core.sc_lines s WHERE s.snapshot_id=%s
), raw_status AS (
 SELECT r.fields->>'COMPAÑÍA__0' company,r.fields->>'SOLICITUD__6' sc_no,r.fields->>'POSICIÓN__7' sc_pos,
        bool_or(NULLIF(btrim(r.fields->>'FECHA APROBACIÓN DEL PEDIDO__41'),'') IS NOT NULL
          AND NULLIF(btrim(r.fields->>'PEDIDO__16'),'') IS NOT NULL
          AND btrim(r.fields->>'PEDIDO__16') NOT IN ('0','000000')) AS any_po_approved
 FROM raw.source_rows r
 WHERE r.snapshot_id=%s AND r.source_name='SC_FAS.csv'
 GROUP BY 1,2,3
), reac AS (
 SELECT company,sc_no,sc_pos,true AS has_reac
 FROM core.reac_refs WHERE snapshot_id=%s GROUP BY 1,2,3
), po_receipts AS (
 SELECT po_no,po_pos,sum(coalesce(delivered_qty,0)) received,
        sum(coalesce(approved_qty,0)) approved,
        bool_or(delivered_qty IS NULL OR approved_qty IS NULL) null_receipt
 FROM core.receipts WHERE snapshot_id=%s GROUP BY 1,2
), po_incidents AS (
 SELECT po_no,po_pos,
        bool_or(lower(btrim(coalesce(resolved,''))) IN ('no','')) AS incident_open,
        bool_or(lower(btrim(coalesce(resolved,''))) IN ('no','') AND
          category IN ('Falta Documentación','Pendiente Aprobación','Documentación Errónea',
                       'Codificación errónea','Otros(Ver Observaciones)')) AS possible_arrival
 FROM core.incidents WHERE snapshot_id=%s GROUP BY 1,2
), links AS (
 SELECT l.company,l.sc_no,l.sc_pos,l.po_no,l.po_pos,
        count(*) OVER(PARTITION BY l.po_no,l.po_pos) AS owner_count,
        l.allocation_status,coalesce(p.ordered_qty,0) ordered,
        coalesce(r.received,0) received,coalesce(r.approved,0) approved,
        coalesce(r.null_receipt,false) null_receipt,
        coalesce(i.incident_open,false) incident_open,
        coalesce(i.possible_arrival,false) possible_arrival
 FROM core.sc_po_links l
 JOIN core.po_lines p ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=
                         (l.snapshot_id,l.company,l.po_no,l.po_pos)
 LEFT JOIN po_receipts r ON (r.po_no,r.po_pos)=(l.po_no,l.po_pos)
 LEFT JOIN po_incidents i ON (i.po_no,i.po_pos)=(l.po_no,l.po_pos)
 WHERE l.snapshot_id=%s
), po_by_sc AS (
 SELECT company,sc_no,sc_pos,count(*) linked_po,
        sum(ordered) ordered_qty,sum(received) received_qty,sum(approved) approved_qty,
        bool_or(owner_count>1 OR allocation_status <> 'verified' OR null_receipt) ambiguous,
        bool_or(incident_open) incident_open,
        bool_or(possible_arrival) possible_arrival
 FROM links GROUP BY 1,2,3
), facts AS (
 SELECT s.*,coalesce(p.linked_po,0) linked_po,
        coalesce(p.ordered_qty,0) ordered_qty,coalesce(p.received_qty,0) received_qty,
        coalesce(p.approved_qty,0) approved_qty,coalesce(p.ambiguous,false) ambiguous,
        coalesce(p.incident_open,false) incident_open,
        coalesce(p.possible_arrival,false) possible_arrival,
        coalesce(r.any_po_approved,false) any_po_approved,
        coalesce(x.has_reac,false) has_reac
 FROM src s
 LEFT JOIN po_by_sc p ON (p.company,p.sc_no,p.sc_pos)=(s.company,s.sc_no,s.sc_pos)
 LEFT JOIN raw_status r ON (r.company,r.sc_no,r.sc_pos)=(s.company,s.sc_no,s.sc_pos)
 LEFT JOIN reac x ON (x.company,x.sc_no,x.sc_pos)=(s.company,s.sc_no,s.sc_pos)
)
SELECT snapshot_id,company,sc_no,sc_pos,article,description,project,
       requested_qty,ordered_qty,received_qty,approved_qty,
       linked_po,has_reac,incident_open,
       CASE
        WHEN requested_qty=0 THEN 'SC anulada'
        WHEN requested_qty IS NULL OR requested_qty<0 OR qty_status NOT IN ('verified','verified_allocated_sum')
             OR ambiguous OR approved_qty>received_qty OR approved_qty<0
             THEN 'Pendiente conciliación'
        WHEN linked_po=0 OR NOT any_po_approved THEN 'Pendiente pedido'
        WHEN approved_qty>=requested_qty THEN 'Completado'
        WHEN approved_qty>0 THEN 'Parcialmente aprobadas'
        WHEN received_qty>0 AND has_reac THEN 'REAC (provisional)'
        WHEN received_qty>0 THEN 'Pendiente aprobación'
        WHEN incident_open AND possible_arrival THEN 'Recibido con incidencia (provisional)'
        WHEN has_reac OR incident_open THEN 'Pendiente conciliación'
        ELSE 'Material sin recibir'
       END AS workflow_state,
       CASE
        WHEN requested_qty=0 AND linked_po>0 AND ordered_qty>0 THEN 'SC anulada con PO positivo'
        WHEN requested_qty=0 THEN 'Cantidad solicitada cero'
        WHEN requested_qty IS NULL OR requested_qty<0 OR qty_status NOT IN ('verified','verified_allocated_sum') THEN 'Cantidad SC invalida o ambigua'
        WHEN ambiguous THEN 'Vinculo SC-PO o recepcion ambigua'
        WHEN approved_qty>received_qty OR approved_qty<0 THEN 'Cantidades inconsistentes'
        WHEN linked_po=0 OR NOT any_po_approved THEN 'Sin PO aprobado'
        WHEN received_qty=0 AND has_reac THEN 'REAC sin recepcion formal'
        WHEN received_qty=0 AND incident_open AND NOT possible_arrival THEN 'Incidencia sin llegada acreditada'
        ELSE NULL END AS workflow_issue
FROM facts