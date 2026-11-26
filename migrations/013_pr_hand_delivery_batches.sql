-- Manual PR handover batches; never alter ERP receipt or snapshot data.
-- One immutable digest per confirmed batch guards against reruns/double clicks.
CREATE TABLE IF NOT EXISTS planning.pr_hand_delivery_batches (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  digest TEXT NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  item_count INTEGER NOT NULL CHECK (item_count BETWEEN 1 AND 200),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE planning.pr_hand_deliveries
  ADD COLUMN IF NOT EXISTS batch_id BIGINT
  REFERENCES planning.pr_hand_delivery_batches(id);
CREATE INDEX IF NOT EXISTS ix_pr_hand_deliveries_batch
  ON planning.pr_hand_deliveries(batch_id) WHERE batch_id IS NOT NULL;
GRANT SELECT, INSERT ON planning.pr_hand_delivery_batches TO bulk_sc_writer;
GRANT USAGE, SELECT ON SEQUENCE planning.pr_hand_delivery_batches_id_seq TO bulk_sc_writer;
GRANT SELECT ON planning.pr_hand_delivery_batches TO compras_reader;
