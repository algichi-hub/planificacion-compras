-- 019: accelerate FK checks when removing a snapshot's PO positions.
-- The existing sc_po_links PK starts with SC columns, so it cannot efficiently
-- locate rows by (snapshot_id, company, po_no, po_pos).
-- Additive and non-destructive. Run off-peak due to index build/write lock.
CREATE INDEX IF NOT EXISTS ix_sc_po_links_by_po_fk
 ON core.sc_po_links(snapshot_id,company,po_no,po_pos);
