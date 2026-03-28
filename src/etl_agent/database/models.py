"""SQLAlchemy ORM models — governance-extended schema."""

from datetime import datetime

from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base: Any = declarative_base()


class UserStoryRecord(Base):
    __tablename__ = "user_stories"
    id = Column(String, primary_key=True)
    story_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    source_path = Column(String)
    source_format = Column(String)
    target_path = Column(String)
    target_format = Column(String)
    target_mode = Column(String)
    data_classification = Column(String, default="internal")
    tags = Column(String)
    raw_json = Column(Text)
    submitted_at = Column(DateTime, default=datetime.utcnow)


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String, primary_key=True)
    run_id = Column(String, unique=True, nullable=False)
    story_id = Column(String, nullable=False)
    story_title = Column(String)
    status = Column(String, default="PENDING")
    current_stage = Column(String)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    github_pr_url = Column(String)
    github_issue_url = Column(String)
    s3_artifact_url = Column(String)
    artifact_checksum = Column(String)
    commit_sha = Column(String)
    test_passed = Column(Boolean)
    test_total = Column(Integer)
    test_passed_count = Column(Integer)
    test_coverage_pct = Column(Float)
    model_name = Column(String)
    prompt_template_version = Column(String)
    system_prompt_hash = Column(String)
    task_prompt_hash = Column(String)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    budget_pct = Column(Float, default=0.0)
    token_steps_json = Column(Text)
    retry_count = Column(Integer, default=0)
    approval_required = Column(Boolean, default=False)
    approver_actor = Column(String)
    approval_timestamp = Column(DateTime)
    approval_rationale = Column(Text)
    data_classification = Column(String, default="internal")
    lineage_snapshot_json = Column(Text)
    error_message = Column(Text)


class AuditEventRecord(Base):
    """Append-only governance event log — records are never modified after insertion."""

    __tablename__ = "audit_events"
    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    run_id = Column(String)
    story_id = Column(String)
    actor = Column(String, default="system")
    trigger_source = Column(String, default="api")
    from_status = Column(String)
    to_status = Column(String)
    payload_json = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
