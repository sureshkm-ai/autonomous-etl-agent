"""
PR Agent — creates a GitHub Issue, commits generated code, and opens a PR.
Uses Claude to write intelligent commit messages.
"""
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import PRCreationError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus
from etl_agent.core.state import GraphState
from etl_agent.tools.github_tools import GitHubTools  # module-level import for patching

logger = get_logger(__name__)


class _LLMWrapper:
    """Thin LangChain-style wrapper so tests can mock agent._llm.ainvoke."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    async def ainvoke(self, messages: list[dict]) -> Any:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        response = await client.messages.create(
            model=self._settings.llm_model,
            max_tokens=self._settings.llm_max_tokens,
            temperature=self._settings.llm_temperature,
            messages=messages,
        )
        text = response.content[0].text

        class _Resp:
            content = text

        return _Resp()


class PRAgent:
    """Agent 4: Creates GitHub Issue + branch + commit + PR."""

    _llm: Any = None  # class-level default; lazy-init in _generate_commit_message

    def __init__(self) -> None:
        self.settings = get_settings()
        # Do NOT set self._llm here; lazy-init in _generate_commit_message so
        # the class-level patch applied by integration tests remains visible.

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        """Make the agent callable as ``await agent(state)``."""
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("pr_agent_call_failed", error=str(e))
            return {"status": RunStatus.FAILED, "error_message": str(e)}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60), reraise=True)
    async def _generate_commit_message(self, state: GraphState) -> str:
        """Use Claude to generate an intelligent commit message."""
        if self._llm is None:
            self._llm = _LLMWrapper(self.settings)
        etl_spec = state["etl_spec"]
        prompt = (
            f"Write a concise, professional git commit message for a PySpark ETL pipeline.\n\n"
            f"Pipeline: {etl_spec.pipeline_name}\n"
            f"Description: {etl_spec.description}\n"
            f"Operations: {[op.value for op in etl_spec.operations]}\n\n"
            f"Format: <type>(<scope>): <subject>\n\n"
            f"Where type is feat/fix/refactor/test. Keep it under 72 characters."
        )
        response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
        return response.content.strip()

    async def run(self, state: GraphState) -> dict[str, Any]:
        from github import GithubException  # type: ignore[import]

        etl_spec = state["etl_spec"]
        # user_story is optional — tests may not provide it
        story = state.get("user_story")
        logger.info("pr_agent_started", pipeline=etl_spec.pipeline_name)

        try:
            gh = GitHubTools(
                token=self.settings.github_token,
                target_repo=self.settings.github_target_repo,
            )

            # Step 1: Create GitHub Issue
            if story:
                issue_title = f"[ETL] {story.title}"
                issue_body = (
                    f"## User Story\n{story.description}\n\n"
                    f"## Acceptance Criteria\n"
                    + "\n".join(f"- {c}" for c in story.acceptance_criteria)
                    + f"\n\n## Story ID\n`{story.id}`\n\n"
                    f"*Auto-created by Autonomous ETL Agent*"
                )
                issue_labels = story.tags
                branch_name = f"etl-agent/{story.id}-{etl_spec.pipeline_name}"
                pr_title = f"[ETL Agent] {story.title}"
                story_ref = f"Story: `{story.id}`"
            else:
                issue_title = f"[ETL] {etl_spec.pipeline_name}"
                issue_body = (
                    f"## Pipeline\n`{etl_spec.pipeline_name}`\n\n"
                    f"*Auto-created by Autonomous ETL Agent*"
                )
                issue_labels = []
                branch_name = f"etl-agent/{etl_spec.pipeline_name}"
                pr_title = f"[ETL Agent] {etl_spec.pipeline_name}"
                story_ref = f"Pipeline: `{etl_spec.pipeline_name}`"

            issue_url = gh.create_issue(
                title=issue_title,
                body=issue_body,
                labels=issue_labels,
            )
            logger.info("github_issue_created", url=issue_url)

            # Step 2: Create branch (returns name; idempotent)
            branch_name = gh.create_branch(branch_name)

            # Step 3: Generate commit message via Claude
            commit_message = await self._generate_commit_message(state)

            # Step 4: Commit generated files
            files: dict[str, str] = {}
            if state.get("generated_code"):
                files[f"src/generated_pipelines/{etl_spec.pipeline_name}.py"] = state["generated_code"]
            if state.get("generated_tests"):
                files[f"tests/generated_tests/test_{etl_spec.pipeline_name}.py"] = state["generated_tests"]
            if state.get("generated_readme"):
                files[f"src/generated_pipelines/{etl_spec.pipeline_name}_README.md"] = state["generated_readme"]
            if files:
                gh.commit_files(branch_name, files, commit_message)

            # Step 5: Open PR
            test_summary = ""
            if state.get("test_results"):
                tr = state["test_results"]
                test_summary = (
                    f"\n\n## Test Results\n"
                    f"✅ {tr.passed_tests}/{tr.total_tests} tests passed | "
                    f"Coverage: {tr.coverage_pct:.0f}%"
                )

            pr_url = gh.create_pull_request(
                title=pr_title,
                body=(
                    f"## Summary\nAuto-generated PySpark pipeline: **{etl_spec.pipeline_name}**\n\n"
                    f"## Pipeline\n`{etl_spec.pipeline_name}`\n\n"
                    f"## Operations\n{', '.join(op.value for op in etl_spec.operations)}"
                    + test_summary
                    + f"\n\n*Auto-generated by Autonomous ETL Agent | {story_ref}*"
                ),
                head_branch=branch_name,
            )
            logger.info("pr_created", url=pr_url)

            return {
                "github_issue_url": issue_url,
                "github_branch_name": branch_name,
                "github_pr_url": pr_url,
                "status": RunStatus.DEPLOYING,
            }

        except GithubException as e:
            logger.error("pr_agent_failed", error=str(e))
            raise PRCreationError(f"PR creation failed: {e}") from e
