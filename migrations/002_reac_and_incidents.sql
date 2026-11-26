CREATE TABLE IF NOT EXISTS core.reac_refs (
 snapshot_id BIGINT NOT NULL REFERENCES audit.snapshots(id),
 company TEXT NOT NULL,
 sc_no TEXT NOT NULL,
 sc_pos TEXT NOT NULL,
 po_no TEXT NOT NULL DEFAULT '',
 po_pos TEXT NOT NULL DEFAULT '',
 reac_no TEXT NOT NULL,
 reac_article TEXT,
 PRIMARY KEY(snapshot_id,company,sc_no,sc_pos,po_no,po_pos,reac_no),
 FOREIGN KEY(snapshot_id,company,sc_no,sc_pos) REFERENCES core.sc_lines(snapshot_id,company,sc_no,sc_pos)
);
CREATE INDEX IF NOT EXISTS ix_reac_sc ON core.reac_refs(snapshot_id,sc_no,sc_pos);
CREATE VIEW planning.v_sc_reac AS SELECT snapshot_id,company,sc_no,sc_pos,
 count(*) AS referenced_reac_count,
 string_agg(DISTINCT reac_no,', ' ORDER BY reac_no) AS reac_numbers
 FROM core.reac_refs GROUP BY snapshot_id,company,sc_no,sc_pos;
CREATE VIEW planning.v_incidents_open AS
 SELECT i.*,CASE WHEN EXISTS (
 SELECT 1 FROM core.sc_po_links l WHERE l.snapshot_id=i.snapshot_id
   AND l.po_no=i.po_no AND l.po_pos=i.po_pos
 ) THEN 'po_position_match' ELSE 'unlinked' END AS linking_status
 FROM core.incidents i
 WHERE lower(coalesce(trim(i.resolved),'')) NOT IN ('sí','si','yes','true','1');
