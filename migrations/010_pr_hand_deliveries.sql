-- Physical handover register, independent of snapshot and ERP receipt records.
-- A PR may have any number of partial deliveries on different or identical dates.
CREATE TABLE IF NOT EXISTS planning.pr_hand_deliveries (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 pr_no TEXT NOT NULL CHECK (pr_no ~ '^[0-9]{1,40}$'),
 quantity NUMERIC(20,6) NOT NULL CHECK (quantity > 0),
 delivery_date DATE NOT NULL,
 created_by TEXT NOT NULL CHECK (length(btrim(created_by)) BETWEEN 3 AND 320),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 voided_by TEXT,
 voided_at TIMESTAMPTZ,
 CONSTRAINT pr_void_consistency CHECK ((voided_by IS NULL) = (voided_at IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_pr_hand_deliveries_active
 ON planning.pr_hand_deliveries(pr_no,delivery_date,id) WHERE voided_at IS NULL;
GRANT SELECT ON planning.pr_hand_deliveries TO compras_reader;
GRANT SELECT, INSERT, UPDATE ON planning.pr_hand_deliveries TO bulk_sc_writer;
GRANT USAGE, SELECT ON SEQUENCE planning.pr_hand_deliveries_id_seq TO bulk_sc_writer;
