"""GCP Secret Manager 連携モジュール.

本番環境ではAPIキー等のシークレットを Secret Manager から取得する。
ローカル環境では `.env` の値をそのまま返す（Settingsオブジェクト経由）。

Usage:
    >>> from src.common.secrets import get_secret
    >>> api_key = get_secret("anthropic-api-key")
"""

from __future__ import annotations

from functools import lru_cache

import structlog
from google.api_core import exceptions as gcp_exceptions
from google.cloud import secretmanager

from src.common.config import settings

logger = structlog.get_logger(__name__)


class SecretAccessError(RuntimeError):
    """Secret Manager からの取得に失敗した場合の例外."""


@lru_cache(maxsize=64)
def _get_client() -> secretmanager.SecretManagerServiceClient:
    """Secret Manager クライアントをシングルトンで取得する."""
    return secretmanager.SecretManagerServiceClient()


def _build_resource_name(secret_id: str, version: str = "latest") -> str:
    """Secret Manager のリソース名を構築する.

    Args:
        secret_id: シークレット名
        version: バージョン（既定は "latest"）

    Returns:
        Secret Manager のフルリソースパス

    Raises:
        SecretAccessError: GCP_PROJECT_ID が未設定の場合
    """
    if not settings.gcp_project_id:
        raise SecretAccessError(
            "GCP_PROJECT_ID が未設定です。.env または環境変数を確認してください。"
        )
    return f"projects/{settings.gcp_project_id}/secrets/{secret_id}/versions/{version}"


def get_secret(secret_id: str, version: str = "latest") -> str:
    """Secret Manager からシークレット値を取得する.

    Args:
        secret_id: シークレット名（例: "anthropic-api-key"）
        version: バージョン（既定は "latest"）

    Returns:
        シークレット値の文字列

    Raises:
        SecretAccessError: 取得に失敗した場合
    """
    name = _build_resource_name(secret_id, version)

    try:
        client = _get_client()
        response = client.access_secret_version(request={"name": name})
    except gcp_exceptions.NotFound as e:
        raise SecretAccessError(f"シークレット '{secret_id}' が見つかりません。") from e
    except gcp_exceptions.PermissionDenied as e:
        raise SecretAccessError(
            f"シークレット '{secret_id}' へのアクセス権限がありません。"
            "サービスアカウントに roles/secretmanager.secretAccessor が付与されているか確認してください。"
        ) from e
    except Exception as e:
        raise SecretAccessError(f"シークレット '{secret_id}' の取得中にエラー: {e}") from e

    payload = response.payload.data.decode("UTF-8")
    logger.info("secret_accessed", secret_id=secret_id, version=version)
    return payload


def resolve_secret(env_value: str, secret_id: str | None = None) -> str:
    """環境変数 or Secret Manager からシークレット値を解決する.

    本番環境では Secret Manager から取得し、それ以外では `.env` の値を使う。

    Args:
        env_value: `.env` 由来の値（ローカル環境用）
        secret_id: Secret Manager 上のID（本番環境用）。Noneなら本番でも env_value を使う

    Returns:
        実際に使用するシークレット値

    Examples:
        >>> # config.py で読み込んだ値を本番では Secret Manager で上書き
        >>> api_key = resolve_secret(settings.anthropic_api_key, "anthropic-api-key")
    """
    if settings.is_production and secret_id:
        return get_secret(secret_id)
    return env_value
