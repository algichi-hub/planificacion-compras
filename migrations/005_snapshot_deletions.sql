-- Preserve an independent audit trail when a validated non-active snapshot is removed.
CREATE TABLE IF NOT EXISTS audit.snapshot_deletions (
    deleted_snapshot_id BIGINT NOT NULL,
    snapshot_date DATE NOT NULL,
    importer_revision TEXT,
    source_hashes JSONB NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_by TEXT NOT NULL DEFAULT current_user,
    removed_rows JSONB NOT NULL,
    PRIMARY KEY(deleted_snapshot_id)
);
