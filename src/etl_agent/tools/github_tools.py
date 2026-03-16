"""GitHub API tool — wraps PyGitHub for branch, commit, issue, and PR operations."""
from github import Github  # type: ignore[import]
from github.ContentFile import ContentFile  # type: ignore[import]

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


class GitHubTools:
    """Wrapper around PyGitHub for ETL Agent repo operations."""

    def __init__(self, token: str, target_repo: str) -> None:
        self._gh = Github(token)
        self._repo = self._gh.get_repo(target_repo)
        self._default_branch = self._repo.default_branch

    def create_issue(self, title: str, body: str, labels: list[str] | None = None):  # type: ignore[no-untyped-def]
        """Create a GitHub Issue and return it."""
        valid_labels = []
        if labels:
            existing = {lbl.name for lbl in self._repo.get_labels()}
            for label in labels:
                if label not in existing:
                    self._repo.create_label(name=label, color="0075ca")
                valid_labels.append(label)

        issue = self._repo.create_issue(title=title, body=body, labels=valid_labels)
        logger.info("github_issue_created", number=issue.number, url=issue.html_url)
        return issue

    def create_branch(self, branch_name: str) -> None:
        """Create a new branch from the default branch."""
        main_sha = self._repo.get_branch(self._default_branch).commit.sha
        self._repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_sha)
        logger.info("branch_created", branch=branch_name)

    def commit_files(self, branch_name: str, files: dict[str, str], commit_message: str) -> None:
        """Commit multiple files to a branch in a single operation."""
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

    def create_pull_request(self, title: str, body: str, head_branch: str):  # type: ignore[no-untyped-def]
        """Open a Pull Request from head_branch to the default branch."""
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=self._default_branch,
        )
        logger.info("pr_created", pr_number=pr.number, url=pr.html_url)
        return pr
