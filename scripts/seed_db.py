"""
Seed the database with demo pipeline runs for the web UI.
Run: uv run python scripts/seed_db.py
     or: make seed-db
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def seed() -> None:
    from etl_agent.database.session import create_all_tables, get_session_factory
    from etl_agent.database.models import UserStoryRecord, PipelineRunRecord
    import uuid

    print("Creating tables...")
    await create_all_tables()

    async with get_session_factory()() as session:
        stories = [
            {"story_id": "story-001", "title": "Clean nulls in customer data", "tags": "data-quality,customers"},
            {"story_id": "story-002", "title": "Join customers with orders", "tags": "join,aggregation"},
            {"story_id": "story-004", "title": "RFM Analysis", "tags": "rfm,analytics,marketing"},
            {"story_id": "story-006", "title": "iPhone 17 Campaign Performance", "tags": "campaign,iphone-17,roi"},
        ]
        statuses = ["DONE", "DONE", "DONE", "FAILED"]

        for story_data, status in zip(stories, statuses):
            story_rec = UserStoryRecord(
                id=str(uuid.uuid4()),
                story_id=story_data["story_id"],
                title=story_data["title"],
                description=f"Demo story: {story_data['title']}",
                raw_yaml="{}",
                tags=story_data["tags"],
            )
            session.add(story_rec)

            run = PipelineRunRecord(
                id=str(uuid.uuid4()),
                run_id=str(uuid.uuid4()),
                story_id=story_data["story_id"],
                status=status,
                github_pr_url=f"https://github.com/demo/etl-pipelines-demo/pull/{len(stories)}" if status == "DONE" else None,
                started_at=datetime.utcnow() - timedelta(hours=len(stories)),
                completed_at=datetime.utcnow() - timedelta(hours=len(stories) - 1) if status == "DONE" else None,
            )
            session.add(run)

        await session.commit()
    print("✅ Database seeded with demo data")


if __name__ == "__main__":
    asyncio.run(seed())
