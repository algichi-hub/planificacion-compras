-- 018: purely additive dates from optional RecepcionesTotales.csv
CREATE TABLE core.pr_approval_dates (
 snapshot_id bigint NOT NULL REFERENCES audit.snapshots(id),
 pr_no text NOT NULL,
 po_no text NOT NULL,
 po_pos text NOT NULL,
 approval_date date NOT NULL,
 source_line integer NOT NULL CHECK (source_line > 1),
 PRIMARY KEY (snapshot_id,pr_no,po_no,po_pos)
);
CREATE INDEX pr_approval_dates_by_po
 ON core.pr_approval_dates(snapshot_id,po_no,po_pos);

-- Least privilege: the import role may populate dates; dashboard is read-only.
GRANT SELECT, INSERT ON core.pr_approval_dates TO compras_importer;
GRANT SELECT ON core.pr_approval_dates TO compras_reader;
