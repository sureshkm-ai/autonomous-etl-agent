-- Create the Airflow database alongside the main etl_agent database
CREATE DATABASE airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO etl_user;

-- PostgreSQL 15+ requires explicit schema grants on public schema
\c airflow
GRANT ALL ON SCHEMA public TO etl_user;
ALTER SCHEMA public OWNER TO etl_user;
