"""Notion 既存メモ → ナレッジエントリDB のパイプライン.

Phase 1（拡張版）の処理:
    1. 指定ページを `NotionReader` で取得
    2. `Summarizer` で要約を生成（Sonnet 4.x）
    3. `EntityExtractor` で人/企業/プロジェクトを抽出（Haiku 4.5）
    4. `Tagger` でタグ候補を生成（Haiku 4.5）
    5. `BodyReviser` で本文を主述補完（Sonnet 4.x、長文は原文をそのまま採用）
    6. マスタ DB にエンティティ・タグを UPSERT（人/企業/プロジェクト/タグ）
    7. `KnowledgeEntry` を組み立て、`NotionWriter` で KB DB に UPSERT（Relation付き）

バッチ実行用に ``KnowledgeIngestionPipeline`` クラスを提供する。クラスは内部で
`MasterDbWriter` のキャッシュを保持するため、複数ページの処理を通じて
人/企業/プロジェクト/タグの探索コストを最小化できる。

短い本文（< 30 文字）はリライトをスキップして原文をそのまま採用する。
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic
from notion_client import Client as NotionClient

from src.common.config import settings
from src.common.logger import get_logger
from src.common.models import KnowledgeEntry, ProcessingStatus, SourceType
from src.loaders.master_db_writer import MasterDbWriter
from src.loaders.notion_writer import NotionWriter
from src.processors.entity_extractor import EntityExtractor
from src.processors.rewriter import BodyReviser
from src.processors.summarizer import Summarizer
from src.processors.tagger import Tagger
from src.sources.notion_reader import NotionReader

logger = get_logger(__name__)


@dataclass
class IngestionResult:
    """1 ページの取り込み結果."""

    kb_page_id: str
    created: bool
    n_people: int
    n_organizations: int
    n_projects: int
    n_tags: int
    body_chars_original: int
    body_chars_revised: int


def _validate_settings() -> None:
    if not settings.notion_api_token:
        raise RuntimeError("NOTION_API_TOKEN が未設定です")
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定です")
    if not settings.notion_db_knowledge_entry:
        raise RuntimeError("NOTION_DB_KNOWLEDGE_ENTRY が未設定です")
    if not settings.notion_db_people:
        raise RuntimeError("NOTION_DB_PEOPLE が未設定です")
    if not settings.notion_db_organization:
        raise RuntimeError("NOTION_DB_ORGANIZATION が未設定です")
    if not settings.notion_db_project:
        raise RuntimeError("NOTION_DB_PROJECT が未設定です")
    if not settings.notion_db_tag:
        raise RuntimeError("NOTION_DB_TAG が未設定です")


class KnowledgeIngestionPipeline:
    """ページ→KB エントリの取り込みパイプライン（バッチ用、リソース共有あり）."""

    def __init__(
        self,
        *,
        enable_entity_extraction: bool = True,
        enable_tagging: bool = True,
        enable_body_revision: bool = True,
    ) -> None:
        _validate_settings()
        self.notion_client = NotionClient(auth=settings.notion_api_token)
        self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

        self.reader = NotionReader(self.notion_client)
        self.summarizer = Summarizer(
            client=self.anthropic_client,
            model=settings.anthropic_model_sonnet,
            max_output_tokens=settings.claude_max_output_tokens,
            enable_prompt_caching=settings.claude_prompt_caching_enabled,
        )
        self.entity_extractor = EntityExtractor(
            client=self.anthropic_client,
            model=settings.anthropic_model_haiku,
            max_output_tokens=1000,
            enable_prompt_caching=settings.claude_prompt_caching_enabled,
        )
        self.tagger = Tagger(
            client=self.anthropic_client,
            model=settings.anthropic_model_haiku,
            max_output_tokens=500,
            enable_prompt_caching=settings.claude_prompt_caching_enabled,
        )
        self.reviser = BodyReviser(
            client=self.anthropic_client,
            model=settings.anthropic_model_sonnet,
            max_output_tokens=4000,
            enable_prompt_caching=settings.claude_prompt_caching_enabled,
        )
        self.master_writer = MasterDbWriter(
            client=self.notion_client,
            people_db_id=settings.notion_db_people,
            organization_db_id=settings.notion_db_organization,
            project_db_id=settings.notion_db_project,
            tag_db_id=settings.notion_db_tag,
        )
        self.kb_writer = NotionWriter(
            client=self.notion_client,
            knowledge_entry_db_id=settings.notion_db_knowledge_entry,
        )

        self.enable_entity_extraction = enable_entity_extraction
        self.enable_tagging = enable_tagging
        self.enable_body_revision = enable_body_revision

    def ingest(
        self,
        page_id: str,
        source_type: SourceType = SourceType.MANUAL,
    ) -> IngestionResult:
        """1 ページを取り込み、KB DB に UPSERT する."""
        logger.info("ingest_start", page_id=page_id)

        source = self.reader.read_page(page_id, source_type=source_type)
        if not source.body.strip():
            logger.warning(
                "ingest_skipped_empty_body",
                page_id=page_id,
                title=source.title,
            )
            raise RuntimeError(f"ページ本文が空のため取り込みをスキップしました: {source.title}")

        # 1. 要約
        summary = self.summarizer.summarize(title=source.title, body=source.body)

        # 2. エンティティ抽出
        entities = (
            self.entity_extractor.extract(title=source.title, body=source.body)
            if self.enable_entity_extraction
            else None
        )

        # 3. タグ生成
        tags_result = (
            self.tagger.generate(title=source.title, body=source.body)
            if self.enable_tagging
            else None
        )

        # 4. 本文リライト
        body_revised = (
            self.reviser.revise(title=source.title, body=source.body)
            if self.enable_body_revision
            else source.body
        )

        # 5. マスタDB UPSERT
        related_people: list[str] = []
        related_orgs: list[str] = []
        related_projects: list[str] = []
        if entities is not None:
            related_people = self.master_writer.ensure_people(entities.people)
            related_orgs = self.master_writer.ensure_organizations(entities.organizations)
            related_projects = self.master_writer.ensure_projects(entities.projects)

        related_tags: list[str] = []
        if tags_result is not None:
            related_tags = self.master_writer.ensure_tags(
                [(t.name, t.category) for t in tags_result.tags]
            )

        # 6. KB エントリ作成
        entry = KnowledgeEntry(
            title=source.title,
            occurred_at=source.last_edited_time,
            source_type=source.source_type,
            source_url=source.source_url,
            summary=summary,
            body_revised=body_revised,
            body_original=source.body,
            related_people=related_people,
            related_organizations=related_orgs,
            related_projects=related_projects,
            tags=related_tags,
            status=ProcessingStatus.AI_PROCESSED,
        )

        kb_page_id, created = self.kb_writer.upsert_knowledge_entry(entry)

        result = IngestionResult(
            kb_page_id=kb_page_id,
            created=created,
            n_people=len(related_people),
            n_organizations=len(related_orgs),
            n_projects=len(related_projects),
            n_tags=len(related_tags),
            body_chars_original=len(source.body),
            body_chars_revised=len(body_revised),
        )

        logger.info(
            "ingest_complete",
            source_page_id=page_id,
            kb_page_id=kb_page_id,
            created=created,
            external_key=entry.external_key,
            n_people=result.n_people,
            n_orgs=result.n_organizations,
            n_projects=result.n_projects,
            n_tags=result.n_tags,
        )
        return result


def ingest_notion_page(
    page_id: str,
    source_type: SourceType = SourceType.MANUAL,
) -> tuple[str, bool]:
    """1 ページ取り込みの薄いラッパー（後方互換）."""
    pipeline = KnowledgeIngestionPipeline()
    result = pipeline.ingest(page_id=page_id, source_type=source_type)
    return result.kb_page_id, result.created
