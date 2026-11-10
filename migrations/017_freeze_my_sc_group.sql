-- Freeze the permanent Mis SC group without deleting its existing members.
REVOKE INSERT, DELETE ON TABLE planning.bulk_sc_groups FROM bulk_sc_writer;
REVOKE UPDATE (name,description,updated_at) ON TABLE planning.bulk_sc_groups FROM bulk_sc_writer;
-- Item-level INSERT/UPDATE/DELETE and group SELECT remain available.
