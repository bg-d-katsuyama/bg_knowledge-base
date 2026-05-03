"""アプリケーション設定の一元管理モジュール.

環境変数の読み込みと型安全な参照を提供する。
直接 `os.getenv` を呼ばず、必ず本モジュールの `settings` 経由で参照すること。

ローカル開発: `.env` ファイルから読み込み
本番環境: 環境変数（Cloud Run経由でSecret Managerから注入）から読み込み
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全環境設定を集約するクラス.

    Pydantic Settings により、環境変数 → `.env` → デフォルト値の順で読み込まれる。
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 実行環境 ---
    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"

    # --- GCP ---
    gcp_project_id: str = ""
    gcp_region: str = "asia-northeast1"
    google_application_credentials: str = ""

    # --- Anthropic (Claude API) ---
    anthropic_api_key: str = ""
    anthropic_model_sonnet: str = "claude-sonnet-4-5"
    anthropic_model_haiku: str = "claude-haiku-4-5"

    # --- Notion ---
    notion_api_token: str = ""
    notion_db_knowledge_entry: str = ""
    notion_db_people: str = ""
    notion_db_organization: str = ""
    notion_db_project: str = ""
    notion_db_tag: str = ""

    # --- Google Workspace ---
    gdrive_target_folder_ids: str = ""
    gmeet_transcript_folder_id: str = ""

    # --- Slack ---
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""
    slack_target_channel_ids: str = ""
    slack_admin_usergroup: str = "kb-admins"

    # --- 取り込み設定 ---
    ingest_since: str = ""

    # --- Claude API コスト制御 ---
    claude_max_output_tokens: int = Field(default=2000, ge=1, le=8192)
    claude_batch_api_enabled: bool = True
    claude_prompt_caching_enabled: bool = True

    # --- 派生プロパティ ---
    @property
    def is_production(self) -> bool:
        """本番環境かどうか."""
        return self.app_env == "prod"

    @property
    def gdrive_target_folder_id_list(self) -> list[str]:
        """Drive対象フォルダIDのリスト."""
        if not self.gdrive_target_folder_ids:
            return []
        return [s.strip() for s in self.gdrive_target_folder_ids.split(",") if s.strip()]

    @property
    def slack_target_channel_id_list(self) -> list[str]:
        """Slack対象チャンネルIDのリスト."""
        if not self.slack_target_channel_ids:
            return []
        return [s.strip() for s in self.slack_target_channel_ids.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定オブジェクトをシングルトンで取得する.

    Returns:
        Settings: アプリケーション設定オブジェクト

    Note:
        テスト時は `get_settings.cache_clear()` でリセット可能。
    """
    return Settings()


# モジュールレベルでアクセスしやすいようエイリアスを提供
settings = get_settings()
