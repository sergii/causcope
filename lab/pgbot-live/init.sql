CREATE EXTENSION pg_stat_statements;

CREATE ROLE pgbot_ro LOGIN PASSWORD 'pgbot_ro';
GRANT pg_monitor TO pgbot_ro;
GRANT CONNECT ON DATABASE causcope TO pgbot_ro;

CREATE ROLE causcope_app LOGIN PASSWORD 'causcope_app';
GRANT CONNECT ON DATABASE causcope TO causcope_app;

CREATE TABLE contention_target (
  id integer PRIMARY KEY,
  value integer NOT NULL
);
INSERT INTO contention_target (id, value) VALUES (1, 0);
GRANT SELECT, UPDATE ON contention_target TO causcope_app;
