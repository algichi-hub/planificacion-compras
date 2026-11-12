-- 020: permit repeated ZIP reference dates; snapshot ID defines import chronology.
-- Preserves every existing snapshot and its primary-key/foreign-key relationships.
-- The date remains NOT NULL; only the redundant per-date uniqueness is removed.
ALTER TABLE audit.snapshots DROP CONSTRAINT IF EXISTS snapshots_snapshot_date_key;
