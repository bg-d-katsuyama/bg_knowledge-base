"""Notion / Anthropic API 接続テストスクリプト.

Phase 1 着手前に、`.env` に設定された認証情報で外部APIへ疎通できることを確認する。

実行方法:
    uv run python scripts/check_connections.py

検証内容:
    1. Notion API: Integration トークンの有効性 (`users.me`) と
       親ページへのアクセス権限 (`pages.retrieve`)
    2. Anthropic API: Haiku 4.5 への小さな ping リクエスト

    使用モデル: Haiku 4.5（接続確認のみ）
    推定コスト: 1回あたり $0.0001 未満
"""

from __future__ import annotations

import sys
from typing import Any

from anthropic import Anthropic, AnthropicError
from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


def _extract_page_title(page: dict[str, Any]) -> str:
    """Notion ページレスポンスからタイトル文字列を抽出する.

    Args:
        page: `pages.retrieve` のレスポンス

    Returns:
        タイトル文字列（取得できない場合は "(no title)"）
    """
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_array = prop.get("title", [])
            if title_array:
                return "".join(t.get("plain_text", "") for t in title_array)
    return "(no title)"


def check_notion() -> bool:
    """Notion API への接続と親ページへのアクセスを確認する.

    Returns:
        全チェックが成功した場合 True
    """
    if not settings.notion_api_token:
        logger.error(
            "notion_token_missing",
            hint="`.env` の NOTION_API_TOKEN を設定してください",
        )
        return False
    if not settings.notion_parent_page_id:
        logger.error(
            "notion_parent_page_id_missing",
            hint="`.env` の NOTION_PARENT_PAGE_ID を設定してください",
        )
        return False

    client = NotionClient(auth=settings.notion_api_token)

    try:
        user = client.users.me()
    except APIResponseError as e:
        logger.error(
            "notion_auth_failed",
            error=str(e),
            hint="トークンが正しいか、Integration が有効か確認してください",
        )
        return False
    bot_name = user.get("name", "(unknown)") if isinstance(user, dict) else "(unknown)"
    logger.info("notion_auth_ok", bot=bot_name)

    try:
        page = client.pages.retrieve(page_id=settings.notion_parent_page_id)
    except APIResponseError as e:
        logger.error(
            "notion_parent_page_unreachable",
            page_id=settings.notion_parent_page_id,
            error=str(e),
            hint=(
                "親ページの右上「…」→「接続」から、Integration "
                "(BG Knowledge Base) を追加してください"
            ),
        )
        return False
    title = _extract_page_title(page) if isinstance(page, dict) else "(unknown)"
    logger.info(
        "notion_parent_page_ok",
        page_id=settings.notion_parent_page_id,
        title=title,
    )
    return True


def check_anthropic() -> bool:
    """Anthropic API への接続を確認する.

    Returns:
        ping が成功した場合 True
    """
    if not settings.anthropic_api_key:
        logger.error(
            "anthropic_key_missing",
            hint="`.env` の ANTHROPIC_API_KEY を設定してください",
        )
        return False

    client = Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=settings.anthropic_model_haiku,
            max_tokens=20,
            messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        )
    except AnthropicError as e:
        logger.error(
            "anthropic_check_failed",
            model=settings.anthropic_model_haiku,
            error=str(e),
            hint="API キーの有効性とクレジット残高を確認してください",
        )
        return False

    text = ""
    if response.content:
        first = response.content[0]
        text = getattr(first, "text", "")
    logger.info(
        "anthropic_ok",
        model=settings.anthropic_model_haiku,
        response=text.strip(),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return True


def main() -> int:
    """全接続チェックを実行する."""
    logger.info("connection_check_start", env=settings.app_env)

    notion_ok = check_notion()
    anthropic_ok = check_anthropic()

    if notion_ok and anthropic_ok:
        logger.info("connection_check_all_ok")
        return 0

    logger.error(
        "connection_check_failed",
        notion=notion_ok,
        anthropic=anthropic_ok,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
