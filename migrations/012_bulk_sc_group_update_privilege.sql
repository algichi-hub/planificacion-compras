-- Minimal writer privilege for authenticated Group SC administration.
-- The writer may edit group metadata, but not ERP/snapshot rows.
-- Applied to Neon production on 2026-11-08 after verifying missing privilege.
GRANT UPDATE (name, description, updated_at)
ON TABLE planning.bulk_sc_groups TO bulk_sc_writer;
