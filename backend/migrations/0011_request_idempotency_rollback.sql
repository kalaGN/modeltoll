-- Stop new code and export before dropping: late retries can execute again afterward.
DROP TABLE IF EXISTS request_idempotency;
