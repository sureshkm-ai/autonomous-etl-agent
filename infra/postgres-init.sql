-- Create the Airflow database alongside the main etl_agent database
CREATE DATABASE airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO etl_user;
