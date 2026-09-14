BEGIN;
UPDATE contention_target SET value = value + 1 WHERE id = 1;
SELECT pg_sleep(300);
ROLLBACK;
