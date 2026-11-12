-- Record the SC approval-date filter used by a snapshot.
-- NULL means an unfiltered import; this is metadata only, not a change to history.
ALTER TABLE audit.snapshots ADD COLUMN IF NOT EXISTS sc_approved_from DATE;
