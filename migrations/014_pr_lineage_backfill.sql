-- Restrict original ERP source access to a view exposing only PR/SC/PO lineage.
-- Do not grant compras_reader or bulk_sc_writer access to raw.source_rows.
CREATE OR REPLACE VIEW planning.v_pr_delivery_relations
WITH (security_barrier=true) AS
WITH manual_pr AS (
  SELECT DISTINCT pr_no FROM planning.pr_hand_deliveries WHERE voided_at IS NULL
),
receipt_keys AS (
  SELECT DISTINCT r.snapshot_id,r.receipt_no,r.po_no,r.po_pos
  FROM core.receipts r JOIN manual_pr m ON m.pr_no=r.receipt_no
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

GRANT SELECT ON planning.v_pr_delivery_relations TO compras_reader;

-- Backfill metadata only. Never modify pr_no, quantity, delivery_date,
-- received_by_nbi, voided_at, created_by or original ledger identity.
ALTER TABLE planning.pr_hand_deliveries
  ADD COLUMN IF NOT EXISTS erp_description TEXT,
  ADD COLUMN IF NOT EXISTS erp_project TEXT,
  ADD COLUMN IF NOT EXISTS erp_po_no TEXT,
  ADD COLUMN IF NOT EXISTS erp_po_pos TEXT,
  ADD COLUMN IF NOT EXISTS erp_supplier_name TEXT,
  ADD COLUMN IF NOT EXISTS erp_source_snapshot_id BIGINT,
  ADD COLUMN IF NOT EXISTS erp_traceability_comment TEXT;

-- Only unambiguous, verified active PRs are backfilled. Every existing manual
-- entry stays intact; unmatched/ambiguous entries remain unfilled for audit.
WITH candidates AS (
  SELECT pr_no,
    min(description) AS description,
    min(project) AS project,
    min(po_no) AS po_no,
    min(po_pos) AS po_pos,
    min(supplier_name) AS supplier_name,
    count(DISTINCT (po_no,po_pos)) AS n_po,
    count(DISTINCT (company,sc_no,sc_pos)) AS n_sc,
    count(DISTINCT (description,project,supplier_name)) AS n_desc,
    bool_and(allocation_status='verified' AND name_count=1) AS all_verified,
    bool_and(NULLIF(btrim(description),'') IS NOT NULL
      AND NULLIF(btrim(project),'') IS NOT NULL
      AND NULLIF(btrim(supplier_name),'') IS NOT NULL) AS all_named
  FROM planning.v_pr_delivery_relations
  WHERE snapshot_id=11 GROUP BY pr_no
)
UPDATE planning.pr_hand_deliveries m
SET erp_description=c.description,
    erp_project=c.project,
    erp_po_no=c.po_no,
    erp_po_pos=c.po_pos,
    erp_supplier_name=c.supplier_name,
    erp_source_snapshot_id=11,
    erp_traceability_comment='Se rellenan campos faltantes desde snapshot #11'
FROM candidates c
WHERE m.pr_no=c.pr_no AND m.voided_at IS NULL
  AND m.erp_source_snapshot_id IS NULL
  AND c.n_po=1 AND c.n_sc=1 AND c.n_desc=1
  AND c.all_verified AND c.all_named;
