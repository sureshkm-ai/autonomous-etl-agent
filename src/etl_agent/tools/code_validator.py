"""Code validation tools — AST syntax check and basic schema validation."""
import ast

from etl_agent.core.exceptions import CodeValidationError
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


def validate_python_syntax(code: str) -> None:
    """
    Validate that generated Python code is syntactically correct.
    Raises CodeValidationError if the code cannot be parsed.
    """
    try:
        ast.parse(code)
        logger.debug("syntax_validation_passed", lines=len(code.splitlines()))
    except SyntaxError as e:
        raise CodeValidationError(
            f"Generated code has syntax error at line {e.lineno}: {e.msg}",
            context={"line": e.lineno, "text": e.text},
        ) from e


def validate_pyspark_imports(code: str) -> list[str]:
    """Check that required PySpark imports are present. Returns list of warnings."""
    warnings = []
    required = ["from pyspark.sql import SparkSession"]
    for req in required:
        if req not in code:
            warnings.append(f"Missing expected import: {req}")
    return warnings
