-- Persistent user-defined Bulk SC lists. No ERP or snapshot records are modified.
CREATE TABLE IF NOT EXISTS planning.bulk_sc_groups (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 160),
 description TEXT NOT NULL DEFAULT '',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning.bulk_sc_items (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 group_id BIGINT NOT NULL REFERENCES planning.bulk_sc_groups(id) ON DELETE CASCADE,
 sc_no TEXT NOT NULL CHECK (length(btrim(sc_no)) BETWEEN 1 AND 40),
 context_description TEXT NOT NULL CHECK (length(btrim(context_description)) BETWEEN 1 AND 500),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(group_id, sc_no)
);
CREATE INDEX IF NOT EXISTS ix_bulk_sc_items_group ON planning.bulk_sc_items(group_id);
