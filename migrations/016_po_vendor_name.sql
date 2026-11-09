-- Materialize supplier name once per PO during snapshot import.
-- Backfill existing snapshots using source export, preserving vendor-code and
-- purchase/receipt quantities without modification.
ALTER TABLE core.po_lines
  ADD COLUMN IF NOT EXISTS vendor_name TEXT,
  ADD COLUMN IF NOT EXISTS vendor_name_count INTEGER NOT NULL DEFAULT 0;

WITH vendor_data AS (
  SELECT r.snapshot_id,
         r.fields->>'COMPAÑÍA__0' company,
         r.fields->>'PEDIDO__16' po_no,
         r.fields->>'POSICIÓN__17' po_pos,
         min(NULLIF(btrim(r.fields->>'NOMBRE__24'),'')) name,
         count(DISTINCT NULLIF(btrim(r.fields->>'NOMBRE__24'),'')) name_count
  FROM raw.source_rows r
  WHERE r.source_name='SC_FAS.csv'
    AND r.snapshot_id IN (SELECT id FROM audit.snapshots WHERE state='validated')
  GROUP BY 1,2,3,4
)
UPDATE core.po_lines p
SET vendor_name=CASE WHEN v.name_count=1 THEN v.name ELSE NULL END,
    vendor_name_count=v.name_count
FROM vendor_data v
WHERE p.snapshot_id=v.snapshot_id AND p.company=v.company
  AND p.po_no=v.po_no AND p.po_pos=v.po_pos
  AND p.vendor_name IS NULL;

-- Dynamic current-snapshot view now reads only normalized core tables.
-- The reader never needs raw-source permissions or a costly JSONB scan.
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
)
SELECT DISTINCT r.snapshot_id,r.receipt_no AS pr_no,r.po_no,r.po_pos,
  p.company,l.sc_no,l.sc_pos,l.allocation_status,
  s.description,s.project,p.vendor_name AS supplier_name,
  p.vendor_name_count::bigint AS name_count
FROM receipt_keys r
LEFT JOIN core.po_lines p ON p.snapshot_id=r.snapshot_id
 AND p.po_no=r.po_no AND p.po_pos=r.po_pos
LEFT JOIN core.sc_po_links l ON l.snapshot_id=r.snapshot_id
 AND l.company=p.company AND l.po_no=p.po_no AND l.po_pos=p.po_pos
LEFT JOIN core.sc_lines s ON s.snapshot_id=r.snapshot_id
 AND s.company=l.company AND s.sc_no=l.sc_no AND s.sc_pos=l.sc_pos;
