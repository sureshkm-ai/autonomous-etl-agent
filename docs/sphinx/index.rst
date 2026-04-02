Autonomous ETL Agent
====================

**Autonomous ETL Agent** is an AI-powered data pipeline platform that converts plain-English
user stories into production-ready PySpark ETL pipelines — fully automated, from schema
discovery through code generation, testing, GitHub PR creation, and artifact deployment.

A user submits a story describing what data transformation they need. The system reads the
AWS Glue Data Catalog, generates tested PySpark code, opens a pull request, uploads the
artifact to S3, and (optionally) triggers an Airflow DAG — with no manual coding required.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   architecture
   aws_services
   docker
   olist_data
   agents
   orchestration
   getting_started
   deployment
   api_reference
   configuration
   ci_cd

.. note::

   This documentation covers every aspect of the project: architecture, all AWS services,
   Docker setup, the Olist dataset, each agent, the LangGraph orchestration graph,
   local setup, cloud deployment, the REST API, and CI/CD pipeline.
