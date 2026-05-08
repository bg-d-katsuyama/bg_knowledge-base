"""ナレッジエントリ DB への書き込みクライアント.

Phase 1 の最小実装として「KnowledgeEntry を 1 件 UPSERT する」機能を提供する。
重複排除は ``外部キー``（SHA256）プロパティで行う。

設計上の不変条件:
    本クライアントは ``NOTION_DB_KNOWLEDGE_ENTRY`` 配下にのみ書き込みを行う。
    既存ドキュメントは一切変更しない。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.common.logger import get_logger
from src.common.models import KnowledgeEntry
from src.loaders.schema_manager import SYS_CREATED_AT, KnowledgeEntryProps  # noqa: F401

if TYPE_CHECKING:
    from notion_client import Client as NotionClient

logger = get_logger(__name__)


# Notion rich_text プロパティの 1 セグメント上限（2000 文字）
_RICH_TEXT_MAX = 2000


def _rich_text(text: str) -> list[dict[str, Any]]:
    """テキストを Notion rich_text 配列に変換する.

    2000 文字を超える場合は末尾を切り詰める（本文の全文保持は別タスク）。
    """
    truncated = text[:_RICH_TEXT_MAX]
    if not truncated:
        return []
    return [{"type": "text", "text": {"content": truncated}}]


def _title_value(text: str) -> list[dict[str, Any]]:
    """Notion title プロパティの値を組み立てる."""
    return [{"type": "text", "text": {"content": text[:_RICH_TEXT_MAX]}}]


class NotionWriter:
    """ナレッジエントリ DB への書き込みクライアント."""

    def __init__(self, client: NotionClient, knowledge_entry_db_id: str) -> None:
        """Args:
        client: 認証済み Notion クライアント
        knowledge_entry_db_id: ナレッジエントリ DB の ID
        """
        self.client = client
        self.db_id = knowledge_entry_db_id
        self._data_source_id: str | None = None

    def _get_data_source_id(self) -> str:
        """ナレッジエントリ DB のデータソース ID を取得（キャッシュ付き）."""
        if self._data_source_id:
            return self._data_source_id
        db = cast(
            dict[str, Any],
            self.client.databases.retrieve(database_id=self.db_id),
        )
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError(f"DB {self.db_id} has no data_sources (unexpected)")
        self._data_source_id = cast(str, sources[0]["id"])
        return self._data_source_id

    def _find_existing_by_external_key(self, external_key: str) -> str | None:
        """外部キーで既存エントリを検索する."""
        ds_id = self._get_data_source_id()
        result = cast(
            dict[str, Any],
            self.client.data_sources.query(
                data_source_id=ds_id,
                filter={
                    "property": KnowledgeEntryProps.EXTERNAL_KEY,
                    "rich_text": {"equals": external_key},
                },
                page_size=1,
            ),
        )
        results = result.get("results", [])
        if results:
            return cast(str, results[0]["id"])
        return None

    def _build_properties(self, entry: KnowledgeEntry) -> dict[str, Any]:
        """KnowledgeEntry を Notion プロパティ辞書へ変換する.

        Phase 1 最小版のため、Relation（人/企業/プロジェクト/タグ）は
        まだ書き込まない。Phase 1 の後続タスクで追加する。
        """
        props: dict[str, Any] = {
            KnowledgeEntryProps.TITLE: {"title": _title_value(entry.title)},
            KnowledgeEntryProps.OCCURRED_AT: {"date": {"start": entry.occurred_at.isoformat()}},
            KnowledgeEntryProps.SOURCE_TYPE: {"select": {"name": entry.source_type.value}},
            KnowledgeEntryProps.SOURCE_URL: {"url": str(entry.source_url)},
            KnowledgeEntryProps.SUMMARY: {"rich_text": _rich_text(entry.summary)},
            KnowledgeEntryProps.BODY_REVISED: {"rich_text": _rich_text(entry.body_revised)},
            KnowledgeEntryProps.BODY_ORIGINAL: {"rich_text": _rich_text(entry.body_original)},
            KnowledgeEntryProps.STATUS: {"select": {"name": entry.status.value}},
            KnowledgeEntryProps.EXTERNAL_KEY: {"rich_text": _rich_text(entry.external_key)},
        }
        if entry.confidence is not None:
            props[KnowledgeEntryProps.CONFIDENCE] = {"select": {"name": entry.confidence.value}}
        if entry.rationale:
            props[KnowledgeEntryProps.RATIONALE] = {"rich_text": _rich_text(entry.rationale)}
        return props

    def upsert_knowledge_entry(self, entry: KnowledgeEntry) -> tuple[str, bool]:
        """KnowledgeEntry を UPSERT する.

        - 同じ外部キーのエントリがあれば更新（プロパティ書き換え）
        - なければ新規作成

        Returns:
            (page_id, created): 作成された/更新された KB ページの ID と、新規作成かどうか
        """
        external_key = entry.external_key
        existing_id = self._find_existing_by_external_key(external_key)
        properties = self._build_properties(entry)

        if existing_id:
            self.client.pages.update(page_id=existing_id, properties=properties)
            logger.info(
                "kb_entry_updated",
                page_id=existing_id,
                external_key=external_key,
                title=entry.title,
            )
            return existing_id, False

        ds_id = self._get_data_source_id()
        response = cast(
            dict[str, Any],
            self.client.pages.create(
                parent={"type": "data_source_id", "data_source_id": ds_id},
                properties=properties,
            ),
        )
        new_id = cast(str, response["id"])
        logger.info(
            "kb_entry_created",
            page_id=new_id,
            external_key=external_key,
            title=entry.title,
        )
        return new_id, True
