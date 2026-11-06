-- Additive, indexed derived results; source snapshots remain untouched.
CREATE TABLE IF NOT EXISTS planning.sc_workflow_status(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 company TEXT NOT NULL, sc_no TEXT NOT NULL, sc_pos TEXT NOT NULL,
 article TEXT, description TEXT, project TEXT,
 requested_qty NUMERIC, ordered_qty NUMERIC, received_qty NUMERIC, approved_qty NUMERIC,
 linked_po BIGINT NOT NULL, has_reac BOOLEAN NOT NULL, incident_open BOOLEAN NOT NULL,
 workflow_state TEXT NOT NULL, workflow_issue TEXT,
 computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(snapshot_id,company,sc_no,sc_pos)
);
CREATE INDEX IF NOT EXISTS ix_sc_workflow_by_state ON planning.sc_workflow_status(snapshot_id,workflow_state);
CREATE INDEX IF NOT EXISTS ix_sc_workflow_by_project ON planning.sc_workflow_status(snapshot_id,project);
