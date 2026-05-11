"""Slack メッセージ → ナレッジエントリ DB のパイプライン.

設計方針:
- **メッセージ単位** で 1 KB エントリ化
- スレッド返信は ``スレッド親メッセージ`` Self-Relation で親 KB エントリに紐付け
- 親メッセージを先に取り込む順序を保証（``SlackReader.iter_messages`` の挙動を活用）
- external_key は通常通り SHA256(source_url + occurred_at) で一意化（Slack permalink がメッセージ ts を含むため一意）
- bot 自身のシステムメッセージ（``channel_join`` 等の subtype 付き）は SKIP
- 空テキスト＆ファイルなしのメッセージは SKIP

既存の `KnowledgeIngestionPipeline` の processor / loader を再利用し、Slack 固有の
入力（`SlackMessage`）→ 出力（`KnowledgeEntry`）変換だけを本モジュールが担う。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from anthropic import Anthropic
from notion_client import Client as NotionClient
from slack_sdk import WebClient

from src.common.config import settings
from src.common.logger import get_logger
from src.common.models import KnowledgeEntry, ProcessingStatus, SourceType
from src.loaders.master_db_writer import MasterDbWriter
from src.loaders.notion_writer import NotionWriter
from src.processors.entity_extractor import EntityExtractor
from src.processors.rewriter import BodyReviser
from src.processors.summarizer import Summarizer
from src.processors.tagger import Tagger
from src.sources.slack_reader import SlackMessage, SlackReader

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


# 取り込み対象から除外する subtype（システムメッセージ）
_SKIP_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "channel_archive",
    "channel_unarchive",
    "pinned_item",
    "unpinned_item",
    "bot_add",
    "bot_remove",
    "reminder_add",
}


@dataclass
class SlackIngestionResult:
    """1 メッセージの取り込み結果."""

    kb_page_id: str
    created: bool
    is_thread_parent: bool
    parent_kb_page_id: str | None
    n_people: int
    n_organizations: int
    n_projects: int
    n_tags: int
    body_chars_original: int
    body_chars_revised: int


def _build_title(msg: SlackMessage) -> str:
    """Slack メッセージから KB エントリのタイトルを組み立てる.

    フォーマット例:
        ``[400-bg-rd-method] 2025-11-19 鈴木: 鈴鹿農園のSN実証...``
    """
    date_str = msg.occurred_at.strftime("%Y-%m-%d")
    user = msg.user_name or msg.user_id or "?"
    head = (msg.text_resolved or "(添付のみ)").strip().splitlines()[0]
    head = head[:80]
    prefix = "↳ " if msg.parent_ts else ""
    return f"[{msg.channel_name}] {date_str} {user}: {prefix}{head}"


def _build_body(msg: SlackMessage) -> str:
    """Slack メッセージから KnowledgeEntry の本文（原文）を組み立てる.

    本文 + リアクション + 添付ファイル一覧 を 1 つのテキストにまとめる。
    """
    parts: list[str] = []
    if msg.text_resolved.strip():
        parts.append(msg.text_resolved.strip())

    if msg.reactions:
        rx = " ".join(f":{name}: x{cnt}" for name, cnt in msg.reactions)
        parts.append(f"\n[リアクション] {rx}")

    if msg.files:
        file_lines = [
            f"  - {f.get('name', '')} ({f.get('mimetype', '')}) {f.get('url', '')}"
            for f in msg.files
        ]
        parts.append("\n[添付ファイル]\n" + "\n".join(file_lines))

    if msg.edited_at:
        parts.append(f"\n[編集済み] {msg.edited_at.isoformat()}")

    return "\n".join(parts).strip()


def _is_skippable(msg: SlackMessage) -> tuple[bool, str]:
    """取り込みスキップ判定."""
    if msg.subtype and msg.subtype in _SKIP_SUBTYPES:
        return True, f"subtype={msg.subtype}"
    if not msg.text_resolved.strip() and not msg.files:
        return True, "empty body without files"
    return False, ""


class SlackKnowledgeIngestionPipeline:
    """Slack メッセージ → KB エントリの取り込みパイプライン.

    既存 `KnowledgeIngestionPipeline` と同じ processor / loader 構成を持つが、
    入力が `SlackMessage` で、スレッド親 Relation を解決する点が異なる。
    """

    def __init__(
        self,
        *,
        enable_entity_extraction: bool = True,
        enable_tagging: bool = True,
        enable_body_revision: bool = True,
    ) -> None:
        if not settings.slack_bot_token:
            raise RuntimeError("SLACK_BOT_TOKEN が未設定です")
        if not settings.notion_api_token:
            raise RuntimeError("NOTION_API_TOKEN が未設定です")
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY が未設定です")

        self.slack_client = WebClient(token=settings.slack_bot_token)
        self.notion_client = NotionClient(auth=settings.notion_api_token)
        self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

        self.reader = SlackReader(self.slack_client)
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

        # スレッド ts → 親 KB ページ ID（同一バッチ内のメモリキャッシュ）
        self._thread_parent_kb: dict[str, str] = {}

    def ingest_message(self, msg: SlackMessage) -> SlackIngestionResult | None:
        """1 つの Slack メッセージを取り込む.

        Returns:
            取り込み結果。SKIP 判定だった場合は ``None``。
        """
        skip, reason = _is_skippable(msg)
        if skip:
            logger.info(
                "slack_msg_skipped",
                ts=msg.ts,
                channel=msg.channel_name,
                reason=reason,
            )
            return None

        title = _build_title(msg)
        body_original = _build_body(msg)

        # 1. 要約
        summary = self.summarizer.summarize(title=title, body=body_original)

        # 2. エンティティ
        entities = (
            self.entity_extractor.extract(title=title, body=body_original)
            if self.enable_entity_extraction
            else None
        )

        # 3. タグ
        tags_result = (
            self.tagger.generate(title=title, body=body_original)
            if self.enable_tagging
            else None
        )

        # 4. 本文リライト
        body_revised = (
            self.reviser.revise(title=title, body=body_original)
            if self.enable_body_revision
            else body_original
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

        # 6. スレッド親 KB ID 解決（このメッセージが返信なら親の kb_page_id を引く）
        parent_kb_id: str | None = None
        if msg.parent_ts:
            parent_kb_id = self._thread_parent_kb.get(msg.parent_ts)
            if parent_kb_id is None:
                logger.warning(
                    "slack_thread_parent_not_found",
                    parent_ts=msg.parent_ts,
                    msg_ts=msg.ts,
                )

        # 7. KB エントリ作成
        # 投稿者（Slack ユーザー名）も人マスタに登録し関係者へ追加
        if msg.user_name:
            poster_id = self.master_writer.people.ensure(msg.user_name)
            if poster_id and poster_id not in related_people:
                related_people.append(poster_id)

        # チャンネル名（例: 400-bg-rd-method）をタグとして自動付与
        ch_tag_id = self.master_writer.tags.ensure(
            f"#{msg.channel_name}",
            extra_properties={"カテゴリ": {"select": {"name": "運用"}}},
        )
        if ch_tag_id and ch_tag_id not in related_tags:
            related_tags.append(ch_tag_id)

        entry = KnowledgeEntry(
            title=title,
            occurred_at=msg.occurred_at,
            source_type=SourceType.SLACK,
            source_url=msg.permalink,
            summary=summary,
            body_revised=body_revised,
            body_original=body_original,
            related_people=related_people,
            related_organizations=related_orgs,
            related_projects=related_projects,
            tags=related_tags,
            status=ProcessingStatus.AI_PROCESSED,
            slack_channel=msg.channel_name,
            slack_thread_ts=msg.thread_ts or msg.ts,
            slack_thread_parent_kb_id=parent_kb_id,
        )

        kb_page_id, created = self.kb_writer.upsert_knowledge_entry(entry)

        # スレッド親なら子から参照されるためキャッシュ
        if msg.is_thread_parent or msg.thread_ts == msg.ts:
            self._thread_parent_kb[msg.ts] = kb_page_id

        result = SlackIngestionResult(
            kb_page_id=kb_page_id,
            created=created,
            is_thread_parent=msg.is_thread_parent,
            parent_kb_page_id=parent_kb_id,
            n_people=len(related_people),
            n_organizations=len(related_orgs),
            n_projects=len(related_projects),
            n_tags=len(related_tags),
            body_chars_original=len(body_original),
            body_chars_revised=len(body_revised),
        )
        logger.info(
            "slack_ingest_complete",
            channel=msg.channel_name,
            ts=msg.ts,
            parent_ts=msg.parent_ts,
            kb_page_id=kb_page_id,
            created=created,
            n_people=result.n_people,
            n_orgs=result.n_organizations,
            n_projects=result.n_projects,
            n_tags=result.n_tags,
            external_key=entry.external_key,
        )
        return result

    def prime_thread_parents(self, channel_id: str) -> int:
        """既に KB に存在するスレッド親メッセージの kb_page_id をキャッシュにプリロードする.

        途中再開（``--skip-existing``）で親メッセージは取り込み済み・返信は未取り込み、
        という状況に対応するため、KB から source_url 経由で逆引きする。

        Notion API がタイムアウトしても全体バッチは止めないよう、上位で例外を握り潰す前提。

        Returns:
            プリロードした件数
        """
        from typing import Any, cast

        ds_id = self.kb_writer._get_data_source_id()
        loaded = 0
        cursor: str | None = None
        meta = self.reader.get_channel_meta(channel_id)
        ch_name = cast(str, meta.get("name") or channel_id)
        while True:
            kwargs: dict[str, Any] = {
                "data_source_id": ds_id,
                "page_size": 100,
                "filter": {
                    "property": "Slackチャンネル",
                    "rich_text": {"equals": ch_name},
                },
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            r = cast(
                dict[str, Any],
                self.notion_client.data_sources.query(**kwargs),
            )
            for row in r.get("results", []):
                props = row.get("properties", {}) or {}
                ts_arr = (props.get("Slackスレッド ts") or {}).get("rich_text") or []
                ts = "".join(t.get("plain_text", "") for t in ts_arr)
                # 親自身は SLACK_THREAD_PARENT relation が空。子メッセージは親 KB ID を持つ。
                parent_rel = (props.get("スレッド親メッセージ") or {}).get("relation") or []
                if not parent_rel and ts:
                    self._thread_parent_kb[ts] = row["id"]
                    loaded += 1
            if not r.get("has_more"):
                break
            cursor = r.get("next_cursor")
            if not cursor:
                break
        logger.info("slack_thread_parent_primed", count=loaded, channel=ch_name)
        return loaded
