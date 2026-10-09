-- Export audit history and explicitly accept its loss before running this file.
-- Restoring code does not restore disabled users or revoked API Keys.
DROP TABLE IF EXISTS admin_audit_events;
