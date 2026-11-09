-- Limit read-only PR lineage to the newest validated snapshot.
-- Existing backfilled #11 values and manual ledger rows remain untouched.
-- Restrict original ERP source access to a view exposing only PR/SC/PO lineage.
-- Do not grant compras_reader or bulk_sc_writer access to raw.source_rows.
CREATE OR REPLACE VIEW planning.v_pr_delivery_relations
WITH (security_barrier=true) AS
WITH current_snapshot AS (
  SELECT id FROM audit.snapshots WHERE state='validated'
  ORDER BY snapshot_date DESC,id DESC LIMIT 1
),
manual_pr AS (
  SELECT DISTINCT pr_no FROM planning.pr_hand_deliveries WHERE voided_at IS NULL
),
receipt_keys AS (
  SELECT DISTINCT r.snapshot_id,r.receipt_no,r.po_no,r.po_pos
  FROM core.receipts r JOIN manual_pr m ON m.pr_no=r.receipt_no
  WHERE r.snapshot_id=(SELECT id FROM current_snapshot)
),
po_keys AS (
  SELECT DISTINCT p.snapshot_id,p.company,p.po_no,p.po_pos
  FROM receipt_keys r JOIN core.po_lines p
    ON p.snapshot_id=r.snapshot_id AND p.po_no=r.po_no AND p.po_pos=r.po_pos
),
vendor_names AS (
  SELECT sr.snapshot_id,
    sr.fields->>'COMPAÑÍA__0' AS company,
    sr.fields->>'PEDIDO__16' AS po_no,
    sr.fields->>'POSICIÓN__17' AS po_pos,
    min(NULLIF(btrim(sr.fields->>'NOMBRE__24'),'')) AS supplier_name,
    count(DISTINCT NULLIF(btrim(sr.fields->>'NOMBRE__24'),'')) AS name_count
  FROM raw.source_rows sr JOIN po_keys k
    ON k.snapshot_id=sr.snapshot_id
   AND k.company=sr.fields->>'COMPAÑÍA__0'
   AND k.po_no=sr.fields->>'PEDIDO__16'
   AND k.po_pos=sr.fields->>'POSICIÓN__17'
  WHERE sr.source_name='SC_FAS.csv'
  GROUP BY 1,2,3,4
)
SELECT DISTINCT r.snapshot_id,r.receipt_no AS pr_no,r.po_no,r.po_pos,
  p.company,l.sc_no,l.sc_pos,l.allocation_status,
  s.description,s.project,v.supplier_name,v.name_count
FROM receipt_keys r
LEFT JOIN core.po_lines p ON p.snapshot_id=r.snapshot_id
 AND p.po_no=r.po_no AND p.po_pos=r.po_pos
LEFT JOIN core.sc_po_links l ON l.snapshot_id=r.snapshot_id
 AND l.company=p.company AND l.po_no=p.po_no AND l.po_pos=p.po_pos
LEFT JOIN core.sc_lines s ON s.snapshot_id=r.snapshot_id
 AND s.company=l.company AND s.sc_no=l.sc_no AND s.sc_pos=l.sc_pos
LEFT JOIN vendor_names v ON v.snapshot_id=r.snapshot_id
 AND v.company=p.company AND v.po_no=p.po_no AND v.po_pos=p.po_pos;
