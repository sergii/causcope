CREATE ROLE pgbot_ro LOGIN PASSWORD 'pgbot_ro';
GRANT pg_monitor TO pgbot_ro;
GRANT CONNECT ON DATABASE causcope TO pgbot_ro;

CREATE ROLE causcope_app LOGIN PASSWORD 'causcope_app';
GRANT CONNECT ON DATABASE causcope TO causcope_app;
