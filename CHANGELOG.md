# Changelog

All notable changes to the Autonomous ETL Agent are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Domain 1 — Run Governance**: DB-backed  replaces in-memory dict.
  All pipeline runs now persist across restarts in SQLite (upgradeable to Postgres).
- **Domain 1**: Append-only  table via . Every run
  lifecycle event (STORY_SUBMITTED → RUN_CREATED → PARSING_STARTED → … → RUN_COMPLETED)
  is recorded with actor, trigger_source, and status transitions.
- **Domain 1**: New endpoints:  (paginated list),
   (per-run event trail),
   (gated deployment approval).
- **Domain 2 — Security**:  — rejects requests exceeding
   (default 32 KiB) with HTTP 413.
- **Domain 2**:  rate limiting — 120 requests/minute per IP by default.
- **Domain 2**: CORS origins now driven by  (replaces
  hard-coded ).
- **Domain 3 — LLM Governance**:  — 
  accumulates per-run token usage;  raises ;
   triggers human gate at configurable threshold (default 75%).
- **Domain 3**:  — wraps every Anthropic
  API call with token tracking, prompt hashing (SHA-256), and model allow-list
  enforcement. Unrecognised models are substituted with the configured fallback.
- **Domain 3**: Approval-gate LangGraph node — holds runs in 
  when data is confidential/restricted or token budget exceeds threshold.
- **Domain 4 — Data Governance**:  — every S3 object is tagged
  with , , , .
- **Domain 4**:  — S3 Lifecycle rules per
  classification: public/internal (1yr), confidential (2yr, Glacier@30d),
  restricted (7yr, Glacier@7d). KMS encryption and versioning also enabled.
- **Domain 5 — Release Governance**:  query param on
   — executes parse + code stages only, returning
  status  without touching tests, GitHub, S3, or Airflow.
- **Domain 6 — Reliability**:  and  propagated through
   to all agent nodes for correlated structured logging.

### Changed
-  — new governance settings: ,
  , , ,
  , , .
-  —  enum; Pydantic field constraints on
   (id pattern, description/tag length limits); 
  ; extended  with token and classification fields.
-  —  extended with AI-provenance columns
  (model_name, prompt hashes), token-budget columns, approval columns, and
  lineage_snapshot_json. New  table.
-  — uses  (file-based SQLite by
  default) instead of in-memory SQLite so state survives restarts.
-  — LangGraph graph rebuilt with approval gate node,
  dry_run short-circuit, and  initialised per run.

---

## [0.1.0] — 2026-01-15

### Added
- Initial release: LangGraph pipeline with story parsing, PySpark code
  generation, pytest test execution, GitHub PR creation, and S3 + Airflow
  deployment.
- FastAPI REST API with background pipeline execution and Server-Sent Events.
- Single-page UI for story submission with transformation builder.
- Docker + Amazon ECR/EC2 deployment with Terraform infrastructure.
