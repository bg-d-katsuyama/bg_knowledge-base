"""構造化ロガーの初期化モジュール.

structlog を使い、JSON形式の構造化ログを出力する。
Cloud Logging との親和性を重視している。

Usage:
    >>> from src.common.logger import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("event_name", key="value")
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.common.config import settings


def _configure() -> None:
    """structlog の初期設定を行う.

    本番環境では JSON 出力、ローカルでは人間可読な色付き出力を使う。
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        # Cloud Logging で構造化ログとして処理されるよう JSON 形式
        processors.append(structlog.processors.JSONRenderer())
    else:
        # ローカルでは人間可読な色付き出力
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """名前付き構造化ロガーを取得する.

    Args:
        name: ロガー名（通常は `__name__`）

    Returns:
        bound logger
    """
    return structlog.get_logger(name)
