-- Snapshot vigency is derived from latest validated snapshot_date/id.
-- Keep historical snapshots and the existing view contract.
UPDATE audit.snapshots SET state='validated' WHERE state='active';
ALTER TABLE audit.snapshots DROP CONSTRAINT snapshots_state_check;
ALTER TABLE audit.snapshots ADD CONSTRAINT snapshots_state_check
  CHECK (state IN ('loading','validated','rejected'));
CREATE OR REPLACE VIEW planning.v_active_sc_coverage AS
  SELECT c.snapshot_id,c.company,c.sc_no,c.sc_pos,c.article,c.description,
         c.project,c.centre,c.requested_qty,c.ordered_qty,c.received_qty,
         c.approved_qty,c.coverage_state,c.coverage_pct
  FROM planning.v_sc_coverage c
  WHERE c.snapshot_id=(
    SELECT id FROM audit.snapshots
    WHERE state='validated'
    ORDER BY snapshot_date DESC,id DESC
    LIMIT 1
  );
