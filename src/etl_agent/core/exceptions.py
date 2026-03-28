"""Custom exception classes."""


class ETLAgentError(Exception):
    """Base exception for ETL Agent errors."""

    def __init__(self, message: str, context: dict | None = None):
        self.message = message
        self.context = context or {}
        super().__init__(message)


class StoryParseError(ETLAgentError):
    """Error parsing user story."""

    pass


class CodeGenerationError(ETLAgentError):
    """Error generating code."""

    pass


class CodeValidationError(ETLAgentError):
    """Error validating code."""

    pass


class TestGenerationError(ETLAgentError):
    """Error generating or running tests."""

    pass


class PRCreationError(ETLAgentError):
    """Error creating pull request."""

    pass


class S3UploadError(ETLAgentError):
    """Error uploading to S3."""

    pass


class ArtifactPackagingError(ETLAgentError):
    """Error packaging artifacts."""

    pass


class AirflowTriggerError(ETLAgentError):
    """Error triggering Airflow DAG."""

    pass
