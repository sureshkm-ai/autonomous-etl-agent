"""
Typer CLI entry point for the Autonomous ETL Agent.
Used by `make demo` and for command-line usage.

Usage:
  uv run etl-agent run --story config/story_examples/rfm_analysis.yaml
  uv run etl-agent run --story config/story_examples/clean_nulls.yaml --no-deploy
"""

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel

from etl_agent.core.logging import configure_logging, get_logger
from etl_agent.core.models import UserStory

app = typer.Typer(
    name="etl-agent",
    help="Autonomous ETL Agent — from story to PR in one command.",
    add_completion=False,
)
console = Console()
logger = get_logger(__name__)


@app.command()
def run(
    story: Path = typer.Option(..., "--story", "-s", help="Path to the user story YAML file"),
    deploy: bool = typer.Option(
        True, "--deploy/--no-deploy", help="Trigger Airflow deployment after PR"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Parse and plan without executing agents"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full ETL agent pipeline for a given user story."""
    configure_logging(log_level="DEBUG" if verbose else "INFO")

    console.print(
        Panel.fit(
            f"[bold cyan]Autonomous ETL Agent[/bold cyan]\nStory: [yellow]{story}[/yellow]",
            border_style="cyan",
        )
    )

    # Load and validate the user story
    if not story.exists():
        console.print(f"[red]Error: Story file not found: {story}[/red]")
        raise typer.Exit(code=1)

    with open(story) as f:
        story_data = yaml.safe_load(f)

    user_story = UserStory(**story_data)
    console.print(f"✅ Loaded story: [bold]{user_story.title}[/bold]")

    if dry_run:
        console.print("[yellow]Dry run mode — no agents will execute.[/yellow]")
        console.print(user_story.model_dump_json(indent=2))
        return

    # Run the agent pipeline
    import asyncio

    from etl_agent.agents.orchestrator import run_pipeline

    result = asyncio.run(run_pipeline(user_story, deploy=deploy))

    if result.github_pr_url:
        console.print(f"\n✅ [bold green]PR created:[/bold green] {result.github_pr_url}")
    if result.airflow_dag_run_id:
        console.print(
            f"✅ [bold green]Airflow DAG triggered:[/bold green] {result.airflow_dag_run_id}"
        )
    if result.status.value == "FAILED":
        console.print(f"\n[red]Pipeline failed: {result.error_message}[/red]")
        raise typer.Exit(code=1)


@app.command()
def serve() -> None:
    """Start the FastAPI web server."""
    import uvicorn

    from etl_agent.core.config import get_settings

    settings = get_settings()
    configure_logging(json_logs=not settings.debug)
    uvicorn.run(
        "etl_agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    app()
