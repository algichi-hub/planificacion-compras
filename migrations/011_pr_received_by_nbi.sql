-- The NBI is an identifier, not a quantity. Keep leading zeros.
-- Existing deliveries remain untouched and show NBI pending completion.
ALTER TABLE planning.pr_hand_deliveries
 ADD COLUMN IF NOT EXISTS received_by_nbi TEXT;
ALTER TABLE planning.pr_hand_deliveries
 DROP CONSTRAINT IF EXISTS pr_hand_deliveries_nbi_numeric;
ALTER TABLE planning.pr_hand_deliveries
 ADD CONSTRAINT pr_hand_deliveries_nbi_numeric
 CHECK (received_by_nbi IS NULL OR received_by_nbi ~ '^[0-9]{1,40}$');
