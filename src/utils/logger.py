"""
Logging utilities for the UPSC Shorts pipeline.
"""

import sys
from pathlib import Path

from loguru import logger

_logger_configured = False


def setup_logger(
    log_level: str = "INFO",
    log_file: str = None,
    rotation: str = "10 MB",
    retention: str = "7 days"
) -> None:
    global _logger_configured
    if _logger_configured:
        return

    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <cyan>{extra[name]}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
        # stderr on Windows can be cp1252; never let a stray glyph kill the run
        backtrace=False,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {extra[name]} - {message}",
            level=log_level,
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
        )

    _logger_configured = True


def get_logger(name: str = None):
    if not _logger_configured:
        setup_logger()
    return logger.bind(name=name or "app")
