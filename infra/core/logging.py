from __future__ import annotations

import sys

from loguru import logger


def configure_logging(debug: bool = False) -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if debug else "INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        enqueue=False,
        backtrace=debug,
        diagnose=debug,
    )


def get_logger():
    return logger
