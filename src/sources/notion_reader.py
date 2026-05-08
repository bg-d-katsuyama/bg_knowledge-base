"""Notion ページを読み取り、SourceDocument に変換する Reader.

Phase 1 では「指定された 1 ページを取得」する最小機能を提供する。
複数ページのバッチ読み取りや差分検出は後続のフェーズで追加する。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from src.common.logger import get_logger
from src.common.models import SourceDocument, SourceType

if TYPE_CHECKING:
    from notion_client import Client as NotionClient

logger = get_logger(__name__)


# プレーンテキスト抽出対象とするブロック型
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}


def _join_rich_text(rich_text: list[dict[str, Any]]) -> str:
    """rich_text 配列の plain_text を連結する."""
    return "".join(t.get("plain_text", "") for t in rich_text)


def _extract_block_text(block: dict[str, Any]) -> str:
    """単一ブロックからプレーンテキストを抽出する.

    対象外のブロック型（image, divider 等）は空文字を返す。
    """
    btype = block.get("type", "")
    if btype not in _TEXT_BLOCK_TYPES:
        return ""
    content = block.get(btype, {}) or {}
    rich = content.get("rich_text") or []
    text = _join_rich_text(rich)
    # 見出しはマークダウン的に強調
    if btype.startswith("heading_"):
        level = int(btype.split("_")[1])
        prefix = "#" * level
        return f"{prefix} {text}" if text else ""
    if btype in {"bulleted_list_item", "to_do"}:
        return f"- {text}" if text else ""
    if btype == "numbered_list_item":
        return f"1. {text}" if text else ""
    if btype == "quote":
        return f"> {text}" if text else ""
    return text


class NotionReader:
    """Notion ページから本文を抽出する Reader."""

    def __init__(self, client: NotionClient) -> None:
        """Args: client: 認証済み Notion クライアント."""
        self.client = client

    def _list_all_blocks(self, block_id: str) -> list[dict[str, Any]]:
        """指定ブロックの直下子ブロックをページネーション込みで全取得する."""
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = cast(dict[str, Any], self.client.blocks.children.list(**kwargs))
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        return results

    def _extract_text_recursive(self, block_id: str, depth: int = 0, max_depth: int = 3) -> str:
        """ブロックを再帰的に走査してプレーンテキストを抽出する.

        toggle 等の入れ子コンテンツも拾うため、有限深さで再帰する。
        """
        if depth > max_depth:
            return ""
        lines: list[str] = []
        for block in self._list_all_blocks(block_id):
            text = _extract_block_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                child_text = self._extract_text_recursive(block["id"], depth + 1, max_depth)
                if child_text:
                    lines.append(child_text)
        return "\n".join(lines)

    def _extract_title(self, page: dict[str, Any]) -> str:
        """ページレスポンスからタイトル文字列を抽出する."""
        for prop in (page.get("properties") or {}).values():
            if prop.get("type") == "title":
                return _join_rich_text(prop.get("title") or [])
        return ""

    def read_page(
        self, page_id: str, source_type: SourceType = SourceType.MANUAL
    ) -> SourceDocument:
        """指定 Notion ページを取得し、SourceDocument に変換する.

        Args:
            page_id: Notion ページ ID（ハイフン有無は問わない）
            source_type: 紐付けるソース種別

        Returns:
            読み取った本文・メタデータを含む SourceDocument
        """
        page = cast(dict[str, Any], self.client.pages.retrieve(page_id=page_id))
        title = self._extract_title(page)
        body = self._extract_text_recursive(page_id)
        last_edited = datetime.fromisoformat(page["last_edited_time"].replace("Z", "+00:00"))
        url = cast(str, page.get("url", ""))
        logger.info(
            "notion_page_read",
            page_id=page_id,
            title=title,
            body_chars=len(body),
            last_edited=last_edited.isoformat(),
        )
        return SourceDocument(
            source_id=page_id,
            title=title,
            source_url=url,
            body=body,
            last_edited_time=last_edited,
            source_type=source_type,
        )
