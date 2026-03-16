"""SQLAlchemy ORM models."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserStoryRecord(Base):
    """Stored user story."""
    __tablename__ = "user_stories"
    
    id = Column(String, primary_key=True)
    story_id = Column(String, unique=True)
    title = Column(String)
    description = Column(Text)
    raw_yaml = Column(Text)
    tags = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class PipelineRunRecord(Base):
    """Pipeline run history."""
    __tablename__ = "pipeline_runs"
    
    id = Column(String, primary_key=True)
    run_id = Column(String, unique=True)
    story_id = Column(String)
    status = Column(String)
    github_pr_url = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
