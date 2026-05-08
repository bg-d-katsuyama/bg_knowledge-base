"""Notion 5DB 構築スクリプト.

`docs/schema.md` に従い、`NOTION_PARENT_PAGE_ID` で指定された親ページの
配下に5つのDB（企業・団体／人／プロジェクト／タグ／ナレッジエントリ）を
冪等的に構築する。

実行方法:
    uv run python scripts/build_notion_schema.py

不変条件:
    本スクリプトは ``NOTION_PARENT_PAGE_ID`` 配下にのみ書き込みを行う。
    既存のドキュメント・データベースは一切変更しない。
"""

from __future__ import annotations

import sys

from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

from src.common.config import settings
from src.common.logger import get_logger
from src.loaders.schema_manager import NotionSchemaManager

logger = get_logger(__name__)


def main() -> int:
    """5DBを構築し、取得した各DBの ID を標準出力に表示する."""
    if not settings.notion_api_token:
        logger.error("notion_token_missing")
        return 1
    if not settings.notion_parent_page_id:
        logger.error("notion_parent_page_id_missing")
        return 1

    client = NotionClient(auth=settings.notion_api_token)
    manager = NotionSchemaManager(client, settings.notion_parent_page_id)

    try:
        db_ids = manager.build_all()
    except APIResponseError as e:
        logger.error(
            "schema_build_failed",
            error=str(e),
            code=getattr(e, "code", "unknown"),
        )
        return 1

    # ユーザーが `.env` に貼り付けるための plain text 出力
    print("\n--- 取得した DB ID（.env に貼り付けてください）---")
    for key, value in db_ids.items():
        print(f"{key}={value}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
