"""src/common/config.py の単体テスト."""

from __future__ import annotations

import pytest


@pytest.mark.usefixtures("stub_env")
def test_settings_loads_from_env() -> None:
    """環境変数から Settings がロードされること."""
    from src.common.config import Settings

    settings = Settings()
    assert settings.app_env == "local"
    assert settings.gcp_project_id == "test-project"
    assert settings.anthropic_api_key == "sk-test"


@pytest.mark.usefixtures("stub_env")
def test_is_production_property() -> None:
    """is_production が APP_ENV に応じて切り替わること."""
    from src.common.config import Settings

    s_local = Settings(app_env="local")
    s_prod = Settings(app_env="prod")
    assert s_local.is_production is False
    assert s_prod.is_production is True


@pytest.mark.usefixtures("stub_env")
def test_target_id_lists_split_by_comma() -> None:
    """カンマ区切りの環境変数がリスト化されること."""
    from src.common.config import Settings

    settings = Settings(
        gdrive_target_folder_ids="folder1, folder2,folder3",
        slack_target_channel_ids="C001",
    )
    assert settings.gdrive_target_folder_id_list == ["folder1", "folder2", "folder3"]
    assert settings.slack_target_channel_id_list == ["C001"]


@pytest.mark.usefixtures("stub_env")
def test_empty_target_ids_returns_empty_list() -> None:
    """空文字列の場合は空リストを返すこと."""
    from src.common.config import Settings

    settings = Settings(gdrive_target_folder_ids="")
    assert settings.gdrive_target_folder_id_list == []
