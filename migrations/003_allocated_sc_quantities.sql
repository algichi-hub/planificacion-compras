-- P1: recognize reconciled SC demand formed by distinct PO allocations.
CREATE OR REPLACE VIEW planning.v_sc_coverage AS
WITH links AS (
 SELECT l.*,count(*) OVER(PARTITION BY l.snapshot_id,l.po_no,l.po_pos) AS sc_count
 FROM core.sc_po_links l
), receipt_sum AS (
 SELECT snapshot_id,po_no,po_pos,
        sum(delivered_qty) AS received_qty,sum(approved_qty) AS approved_qty,
        bool_or(delivered_qty IS NULL OR approved_qty IS NULL) AS incomplete
 FROM core.receipts GROUP BY snapshot_id,po_no,po_pos
), per_sc AS (
 SELECT l.snapshot_id,l.company,l.sc_no,l.sc_pos,
        count(*) AS linked_po,
        bool_or(l.sc_count>1 OR l.allocation_status<>'verified' OR r.incomplete IS TRUE) AS ambiguous,
        sum(CASE WHEN l.sc_count=1 AND l.allocation_status='verified' THEN p.ordered_qty ELSE NULL END) AS ordered_qty,
        sum(CASE WHEN l.sc_count=1 AND l.allocation_status='verified' THEN coalesce(r.received_qty,0) ELSE NULL END) AS received_qty,
        sum(CASE WHEN l.sc_count=1 AND l.allocation_status='verified' THEN coalesce(r.approved_qty,0) ELSE NULL END) AS approved_qty
 FROM links l
 JOIN core.po_lines p ON (p.snapshot_id,p.company,p.po_no,p.po_pos)=(l.snapshot_id,l.company,l.po_no,l.po_pos)
 LEFT JOIN receipt_sum r ON r.snapshot_id=l.snapshot_id AND r.po_no=l.po_no AND r.po_pos=l.po_pos
 GROUP BY l.snapshot_id,l.company,l.sc_no,l.sc_pos
)
SELECT s.snapshot_id,s.company,s.sc_no,s.sc_pos,s.article,s.description,s.project,s.centre,
 s.requested_qty, CASE WHEN s.qty_status IN ('verified','verified_allocated_sum') AND coalesce(x.ambiguous,false)=false THEN x.ordered_qty END AS ordered_qty,
 CASE WHEN s.qty_status IN ('verified','verified_allocated_sum') AND coalesce(x.ambiguous,false)=false THEN coalesce(x.received_qty,0) END AS received_qty,
 CASE WHEN s.qty_status IN ('verified','verified_allocated_sum') AND coalesce(x.ambiguous,false)=false THEN coalesce(x.approved_qty,0) END AS approved_qty,
 CASE WHEN s.qty_status NOT IN ('verified','verified_allocated_sum') OR coalesce(x.ambiguous,false) THEN 'pending_reconciliation'
      WHEN s.requested_qty IS NULL OR s.requested_qty<=0 THEN 'pending_reconciliation'
      WHEN coalesce(x.approved_qty,0)=0 THEN 'no_approved_coverage'
      WHEN x.approved_qty>=s.requested_qty THEN 'complete'
      ELSE 'partial' END AS coverage_state,
 CASE WHEN s.qty_status IN ('verified','verified_allocated_sum') AND NOT coalesce(x.ambiguous,false) AND s.requested_qty>0
      THEN least(100,round(100*coalesce(x.approved_qty,0)/s.requested_qty,2)) END AS coverage_pct
FROM core.sc_lines s LEFT JOIN per_sc x
ON (s.snapshot_id,s.company,s.sc_no,s.sc_pos)=(x.snapshot_id,x.company,x.sc_no,x.sc_pos);
