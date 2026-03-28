"""GitHub API tool — wraps PyGitHub for branch, commit, issue, and PR operations."""

import uuid

from github import Github  # type: ignore[import-untyped]
from github.ContentFile import ContentFile  # type: ignore[import-untyped]

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


class GitHubTools:
    """Wrapper around PyGitHub for ETL Agent repo operations."""

    def __init__(self, token: str, target_repo: str | None = None, repo: str | None = None) -> None:
        # Accept both `target_repo` (production) and `repo` (test stubs) as the repo name.
        resolved_repo = target_repo or repo
        if resolved_repo is None:
            raise ValueError("Either 'target_repo' or 'repo' must be provided")
        self._gh = Github(token)
        self._repo = self._gh.get_repo(resolved_repo)
        self._default_branch = self._repo.default_branch

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> str:
        """Create a GitHub Issue and return its HTML URL."""
        valid_labels: list[str] = []
        if labels:
            try:
                existing = {lbl.name for lbl in self._repo.get_labels()}
                for label in labels:
                    if label not in existing:
                        try:
                            self._repo.create_label(name=label, color="0075ca")
                        except Exception as e:
                            # 403 / fine-grained tokens often cannot manage labels — skip
                            logger.warning("label_create_skipped", label=label, reason=str(e))
                            continue
                    valid_labels.append(label)
            except Exception as e:
                # If even listing labels is forbidden, proceed without any labels
                logger.warning("labels_skipped", reason=str(e))

        issue = self._repo.create_issue(title=title, body=body, labels=valid_labels)
        logger.info("github_issue_created", number=issue.number, url=issue.html_url)
        return issue.html_url

    def create_branch(
        self,
        branch_name: str | None = None,
        *,
        base_branch: str | None = None,
        prefix: str | None = None,
    ) -> str:
        """Create a new branch and return its name (idempotent).

        Accepts two calling conventions:
        - ``create_branch(branch_name)``           — use the given name directly
        - ``create_branch(base_branch=..., prefix=...)`` — generate a name from prefix + random suffix
        """
        if prefix is not None:
            # Generate a unique branch name from prefix
            short_id = uuid.uuid4().hex[:7]
            branch_name = f"{prefix}-{short_id}"

        if branch_name is None:
            raise ValueError("Provide either 'branch_name' or 'prefix'")

        ref_base = base_branch or self._default_branch
        base_sha = self._repo.get_branch(ref_base).commit.sha
        try:
            self._repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
            logger.info("branch_created", branch=branch_name)
        except Exception as e:
            if "already exists" in str(e).lower() or "422" in str(e):
                logger.info("branch_already_exists", branch=branch_name)
            else:
                raise
        return branch_name

    def commit_files(
        self,
        branch_name: str | None = None,
        files: dict[str, str] | None = None,
        commit_message: str | None = None,
        *,
        branch: str | None = None,
        message: str | None = None,
    ) -> None:
        """Commit multiple files to a branch in a single operation.

        Accepts both positional-style (``branch_name``, ``commit_message``)
        and keyword-style (``branch``, ``message``) for backwards compatibility
        with test stubs.
        """
        branch_name = branch_name or branch
        commit_message = commit_message or message
        if branch_name is None or files is None or commit_message is None:
            raise ValueError("branch_name/branch, files, and commit_message/message are required")
        #
        for file_path, content in files.items():
            try:
                existing: ContentFile = self._repo.get_contents(file_path, ref=branch_name)  # type: ignore[assignment]
                self._repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=existing.sha,
                    branch=branch_name,
                )
            except Exception:
                self._repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch=branch_name,
                )
        logger.info("files_committed", branch=branch_name, file_count=len(files))

    def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str | None = None,
    ) -> str:
        """Open a Pull Request and return its HTML URL."""
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch or self._default_branch,
        )
        logger.info("pr_created", pr_number=pr.number, url=pr.html_url)
        return pr.html_url
