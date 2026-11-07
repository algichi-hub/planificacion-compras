-- P2: identify the parser revision that produced each snapshot.
-- Previous snapshots remain untouched and are marked legacy; reimport is required.
ALTER TABLE audit.snapshots
 ADD COLUMN IF NOT EXISTS importer_revision TEXT NOT NULL DEFAULT 'legacy_pre_p2';
