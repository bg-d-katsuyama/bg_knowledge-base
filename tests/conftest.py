"""pytest 共通フィクスチャ."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """各テストの前後で Settings のキャッシュをリセットする."""
    from src.common.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stub_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """テスト用の最小限の環境変数をセットする."""
    test_env = {
        "APP_ENV": "local",
        "GCP_PROJECT_ID": "test-project",
        "ANTHROPIC_API_KEY": "sk-test",
        "NOTION_API_TOKEN": "secret_test",
    }
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
        # .env を読まないよう既存値もクリア
        if key not in os.environ:
            monkeypatch.setenv(key, value)
    yield
