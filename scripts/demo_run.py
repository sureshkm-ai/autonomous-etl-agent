"""
One-command end-to-end demo of the Autonomous ETL Agent.
Run: uv run python scripts/demo_run.py
     or: make demo
"""
import asyncio
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

console = Console()

DEMO_STORY = "config/story_examples/rfm_analysis.yaml"


async def run_demo() -> None:
    from etl_agent.core.logging import configure_logging
    from etl_agent.core.models import UserStory
    import yaml

    configure_logging(log_level="INFO")

    console.print(Panel.fit(
        "[bold cyan]🤖 Autonomous ETL Agent — End-to-End Demo[/bold cyan]\n\n"
        "This demo will:\n"
        "  1. Parse a DevOps user story (RFM Analysis)\n"
        "  2. Generate a production PySpark pipeline\n"
        "  3. Auto-generate and run pytest tests\n"
        "  4. Create a GitHub Issue + Pull Request\n"
        "  5. (Optional) Trigger Airflow scheduling",
        border_style="cyan"
    ))

    # Load the demo story
    with open(DEMO_STORY) as f:
        story_data = yaml.safe_load(f)
    story = UserStory(**story_data)

    table = Table(title="Story Details", show_header=True)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("ID", story.id)
    table.add_row("Title", story.title)
    table.add_row("Operations", str([t.operation.value for t in story.transformations]))
    table.add_row("Source", story.source.path)
    table.add_row("Target", story.target.path)
    console.print(table)

    console.print("\n[yellow]Starting agent pipeline...[/yellow]\n")

    from etl_agent.agents.orchestrator import run_pipeline
    result = await run_pipeline(story, deploy=False)

    # Results table
    results_table = Table(title="Pipeline Run Results", show_header=True)
    results_table.add_column("Step", style="cyan")
    results_table.add_column("Result", style="white")
    results_table.add_row("Status", f"[bold green]{result.status.value}[/bold green]")
    results_table.add_row("GitHub Issue", result.github_issue_url or "N/A")
    results_table.add_row("GitHub PR", result.github_pr_url or "N/A")
    results_table.add_row("S3 Artifact", result.s3_artifact_url or "N/A")
    if result.test_result:
        results_table.add_row(
            "Tests",
            f"{result.test_result.passed_tests}/{result.test_result.total_tests} passed "
            f"({result.test_result.coverage_pct:.0f}% coverage)"
        )
    console.print(results_table)

    if result.github_pr_url:
        console.print(f"\n✅ [bold green]Demo complete! PR:[/bold green] {result.github_pr_url}")
    else:
        console.print(f"\n⚠️  [yellow]Demo completed with status: {result.status.value}[/yellow]")
        if result.error_message:
            console.print(f"[red]Error: {result.error_message}[/red]")


if __name__ == "__main__":
    asyncio.run(run_demo())
