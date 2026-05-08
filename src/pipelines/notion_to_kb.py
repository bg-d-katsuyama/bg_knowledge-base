"""Notion 既存メモ → ナレッジエントリDB のパイプライン.

Phase 1 の最小エンドツーエンド実装:
    1. 指定ページを `NotionReader` で取得
    2. `Summarizer` で Claude 要約を生成
    3. `KnowledgeEntry` を組み立て、`NotionWriter` で KB DB に UPSERT

タグ生成・エンティティ抽出・主述補完は Phase 1 の後続タスクで追加する。
"""

from __future__ import annotations

from anthropic import Anthropic
from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger
from src.common.models import KnowledgeEntry, ProcessingStatus, SourceType
from src.loaders.notion_writer import NotionWriter
from src.processors.summarizer import Summarizer
from src.sources.notion_reader import NotionReader

logger = get_logger(__name__)


def ingest_notion_page(
    page_id: str,
    source_type: SourceType = SourceType.MANUAL,
) -> tuple[str, bool]:
    """Notion ページを 1 件取り込み、ナレッジエントリ DB に UPSERT する.

    Args:
        page_id: 取り込み元の Notion ページ ID
        source_type: 紐付けるソース種別

    Returns:
        (kb_page_id, created): 作成/更新された KB ページの ID と、新規作成かのフラグ
    """
    if not settings.notion_api_token:
        raise RuntimeError("NOTION_API_TOKEN が未設定です")
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定です")
    if not settings.notion_db_knowledge_entry:
        raise RuntimeError("NOTION_DB_KNOWLEDGE_ENTRY が未設定です")

    notion_client = NotionClient(auth=settings.notion_api_token)
    anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

    reader = NotionReader(notion_client)
    summarizer = Summarizer(
        client=anthropic_client,
        model=settings.anthropic_model_sonnet,
        max_output_tokens=settings.claude_max_output_tokens,
        enable_prompt_caching=settings.claude_prompt_caching_enabled,
    )
    writer = NotionWriter(
        client=notion_client,
        knowledge_entry_db_id=settings.notion_db_knowledge_entry,
    )

    logger.info("ingest_start", page_id=page_id)

    source = reader.read_page(page_id, source_type=source_type)
    if not source.body.strip():
        logger.warning(
            "ingest_skipped_empty_body",
            page_id=page_id,
            title=source.title,
        )
        raise RuntimeError(f"ページ本文が空のため取り込みをスキップしました: {source.title}")

    summary = summarizer.summarize(title=source.title, body=source.body)

    entry = KnowledgeEntry(
        title=source.title,
        occurred_at=source.last_edited_time,
        source_type=source.source_type,
        source_url=source.source_url,
        summary=summary,
        body_revised=source.body,  # 主述補完は後続タスクで実装。MVP では原文をコピー
        body_original=source.body,
        status=ProcessingStatus.AI_PROCESSED,
    )

    kb_page_id, created = writer.upsert_knowledge_entry(entry)

    logger.info(
        "ingest_complete",
        source_page_id=page_id,
        kb_page_id=kb_page_id,
        created=created,
        external_key=entry.external_key,
    )
    return kb_page_id, created
