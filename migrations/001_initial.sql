CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS planning;
CREATE TABLE IF NOT EXISTS audit.snapshots(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 snapshot_date DATE NOT NULL UNIQUE,
 state TEXT NOT NULL DEFAULT 'loading' CHECK(state IN ('loading','validated','active','rejected')),
 source_hashes JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 activated_at TIMESTAMPTZ,
 notes TEXT
);
CREATE TABLE IF NOT EXISTS audit.source_files(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 source_name TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 rows_total INTEGER NOT NULL DEFAULT 0,
 rows_ok INTEGER NOT NULL DEFAULT 0,
 rows_invalid INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(snapshot_id,source_name)
);
CREATE TABLE IF NOT EXISTS audit.import_issues(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 source_name TEXT NOT NULL,
 line_number INTEGER,
 severity TEXT NOT NULL CHECK(severity IN('warning','error')),
 issue_code TEXT NOT NULL,
 details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.source_rows(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 source_name TEXT NOT NULL CHECK(source_name IN('SC_FAS.csv','INC_FAS.csv','Recepciones_Sevilla.csv')),
 source_line INTEGER NOT NULL,
 fields JSONB NOT NULL,
 PRIMARY KEY(snapshot_id,source_name,source_line)
);
CREATE TABLE IF NOT EXISTS core.sc_lines(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 company TEXT NOT NULL,
 sc_no TEXT NOT NULL,
 sc_pos TEXT NOT NULL,
 article TEXT,
 description TEXT,
 project TEXT,
 centre TEXT,
 project_director TEXT,
 requested_qty NUMERIC(20,6),
 qty_status TEXT NOT NULL DEFAULT 'verified',
 required_date DATE,
 PRIMARY KEY(snapshot_id,company,sc_no,sc_pos)
);
CREATE TABLE IF NOT EXISTS core.po_lines(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 company TEXT NOT NULL,
 po_no TEXT NOT NULL,
 po_pos TEXT NOT NULL,
 article TEXT,
 vendor TEXT,
 ordered_qty NUMERIC(20,6),
 planned_date DATE,
 PRIMARY KEY(snapshot_id,company,po_no,po_pos)
);
CREATE TABLE IF NOT EXISTS core.sc_po_links(
 snapshot_id BIGINT NOT NULL,
 company TEXT NOT NULL,
 sc_no TEXT NOT NULL,
 sc_pos TEXT NOT NULL,
 po_no TEXT NOT NULL,
 po_pos TEXT NOT NULL,
 allocation_qty NUMERIC(20,6),
 allocation_status TEXT NOT NULL DEFAULT 'unverified',
 PRIMARY KEY(snapshot_id,company,sc_no,sc_pos,po_no,po_pos),
 FOREIGN KEY(snapshot_id,company,sc_no,sc_pos) REFERENCES core.sc_lines(snapshot_id,company,sc_no,sc_pos),
 FOREIGN KEY(snapshot_id,company,po_no,po_pos) REFERENCES core.po_lines(snapshot_id,company,po_no,po_pos)
);
CREATE TABLE IF NOT EXISTS core.receipts(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 source_line INTEGER NOT NULL,
 company TEXT,
 po_no TEXT NOT NULL,
 po_pos TEXT NOT NULL,
 receipt_no TEXT NOT NULL,
 article TEXT,
 receipt_date DATE,
 delivered_qty NUMERIC(20,6),
 approved_qty NUMERIC(20,6),
 erp_status TEXT,
 PRIMARY KEY(snapshot_id,source_line)
);
CREATE INDEX IF NOT EXISTS ix_receipts_po ON core.receipts(snapshot_id,po_no,po_pos);
CREATE TABLE IF NOT EXISTS core.incidents(
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 source_line INTEGER NOT NULL,
 record_no TEXT,
 sequence_no TEXT,
 po_no TEXT,
 po_pos TEXT,
 article TEXT,
 category TEXT,
 resolved TEXT,
 detail TEXT,
 PRIMARY KEY(snapshot_id,source_line)
);
CREATE INDEX IF NOT EXISTS ix_incidents_po ON core.incidents(snapshot_id,po_no,po_pos);
CREATE INDEX IF NOT EXISTS ix_sc_article ON core.sc_lines(snapshot_id,article);
CREATE INDEX IF NOT EXISTS ix_sc_project ON core.sc_lines(snapshot_id,project);
CREATE VIEW planning.v_sc_coverage AS
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
 s.requested_qty, CASE WHEN s.qty_status='verified' AND coalesce(x.ambiguous,false)=false THEN x.ordered_qty END AS ordered_qty,
 CASE WHEN s.qty_status='verified' AND coalesce(x.ambiguous,false)=false THEN coalesce(x.received_qty,0) END AS received_qty,
 CASE WHEN s.qty_status='verified' AND coalesce(x.ambiguous,false)=false THEN coalesce(x.approved_qty,0) END AS approved_qty,
 CASE WHEN s.qty_status<>'verified' OR coalesce(x.ambiguous,false) THEN 'pending_reconciliation'
      WHEN s.requested_qty IS NULL OR s.requested_qty<=0 THEN 'pending_reconciliation'
      WHEN coalesce(x.approved_qty,0)=0 THEN 'no_approved_coverage'
      WHEN x.approved_qty>=s.requested_qty THEN 'complete'
      ELSE 'partial' END AS coverage_state,
 CASE WHEN s.qty_status='verified' AND NOT coalesce(x.ambiguous,false) AND s.requested_qty>0
      THEN least(100,round(100*coalesce(x.approved_qty,0)/s.requested_qty,2)) END AS coverage_pct
FROM core.sc_lines s LEFT JOIN per_sc x
ON (s.snapshot_id,s.company,s.sc_no,s.sc_pos)=(x.snapshot_id,x.company,x.sc_no,x.sc_pos);
CREATE VIEW planning.v_active_sc_coverage AS
SELECT c.* FROM planning.v_sc_coverage c
JOIN audit.snapshots s ON s.id=c.snapshot_id WHERE s.state='active';
