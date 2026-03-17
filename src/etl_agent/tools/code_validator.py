"""Code validation tools — AST syntax check and basic import validation."""
import ast

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


def validate_python_syntax(code: str) -> tuple[bool, str | None]:
    """Validate that generated Python code is syntactically correct.

    Returns:
        (True, None)          — code is valid
        (False, error_message) — code has a syntax error
    """
    if not code or not code.strip():
        return False, "Code is empty"
    try:
        ast.parse(code)
        logger.debug("syntax_validation_passed", lines=len(code.splitlines()))
        return True, None
    except SyntaxError as e:
        msg = f"Syntax error at line {e.lineno}: {e.msg}"
        logger.debug("syntax_validation_failed", error=msg)
        return False, msg


def validate_pyspark_imports(code: str) -> tuple[bool, list[str]]:
    """Check that required PySpark imports are present.

    Returns:
        (True, [])             — all required imports found
        (False, [missing, …])  — list of missing import statements
    """
    required = ["from pyspark.sql import SparkSession"]
    missing = [req for req in required if req not in code]
    return len(missing) == 0, missing
