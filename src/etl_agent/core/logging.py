"""Structured logging configuration with structlog."""

import logging
from typing import cast

import structlog


def configure_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog with optional JSON output."""
    logging.basicConfig(level=log_level)
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a logger instance."""
    return cast(structlog.BoundLogger, structlog.get_logger(name))
