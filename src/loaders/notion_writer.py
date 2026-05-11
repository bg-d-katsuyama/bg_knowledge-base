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


# Notion rich_text プロパティの 1 セグメント上限（2000 UTF-16 code units）
_RICH_TEXT_MAX = 2000
# Notion blocks.children.append で 1 リクエストに含められる子ブロック数の上限
_BLOCKS_APPEND_BATCH = 100
# 本文の rich_text プロパティに残すスニペット末尾の省略マーカー
_TRUNCATION_MARKER = "...（続きはページ本体）"


def _utf16_len(text: str) -> int:
    """文字列の UTF-16 code unit 長を返す."""
    return len(text.encode("utf-16-le")) // 2


def _truncate_utf16(text: str, max_units: int = _RICH_TEXT_MAX) -> str:
    """UTF-16 code unit 単位で安全に切り詰める.

    Notion API の content.length は UTF-16 code unit でカウントされる。
    Python の ``len(str)`` は code point 単位なので、サロゲートペア
    （絵文字や CJK 拡張 B 等）を含むと 1 code point = 2 code units と
    なってずれる。Notion 側の制約に合わせて切る。
    """
    encoded = text.encode("utf-16-le")
    # 1 code unit = 2 bytes
    truncated_bytes = encoded[: max_units * 2]
    # サロゲートペアの片割れを切り落とさないよう、デコードエラーを許容して落とす
    return truncated_bytes.decode("utf-16-le", errors="ignore")


def _rich_text(text: str) -> list[dict[str, Any]]:
    """テキストを Notion rich_text 配列に変換する（プロパティ用、上限切り詰め）."""
    truncated = _truncate_utf16(text)
    if not truncated:
        return []
    return [{"type": "text", "text": {"content": truncated}}]


def _rich_text_body_snippet(text: str) -> list[dict[str, Any]]:
    """本文プロパティ用 rich_text。2000 単位超過時は末尾省略マーカー付きで返す.

    ページ本体ブロックに全文が複製される前提。
    """
    if not text:
        return []
    if _utf16_len(text) <= _RICH_TEXT_MAX:
        return [{"type": "text", "text": {"content": text}}]
    marker_len = _utf16_len(_TRUNCATION_MARKER)
    head = _truncate_utf16(text, _RICH_TEXT_MAX - marker_len)
    return [{"type": "text", "text": {"content": head + _TRUNCATION_MARKER}}]


def _title_value(text: str) -> list[dict[str, Any]]:
    """Notion title プロパティの値を組み立てる."""
    return [{"type": "text", "text": {"content": _truncate_utf16(text)}}]


def _chunk_for_blocks(text: str, max_units: int = _RICH_TEXT_MAX) -> list[str]:
    """ページ本体ブロック用に、UTF-16 安全な ≤2000 単位チャンクへ分割する.

    可能なら改行境界で区切り、なければ強制切り詰め。
    """
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while remaining:
        if _utf16_len(remaining) <= max_units:
            chunks.append(remaining)
            break
        candidate = _truncate_utf16(remaining, max_units)
        # 直近 200 code points 内に改行があれば、そこで区切る
        nl = candidate.rfind("\n", max(0, len(candidate) - 200))
        if nl > 0:
            candidate = candidate[: nl + 1]
        if not candidate:
            # 1 code point が極端に大きい不測の事態に備えて、強制 1 code point 進める
            candidate = remaining[:1]
        chunks.append(candidate)
        remaining = remaining[len(candidate):]
    return chunks


def _heading_block(text: str, level: int = 2) -> dict[str, Any]:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _build_body_blocks(body_revised: str, body_original: str) -> list[dict[str, Any]]:
    """本文（補完済み）／本文（原文）の全文を保持するページ本体ブロック列を組み立てる.

    どちらの本文も 2000 単位以下なら空配列を返す（rich_text プロパティで十分）。
    両本文が同一なら原文セクションは省略する。
    """
    rev_long = _utf16_len(body_revised) > _RICH_TEXT_MAX
    orig_long = _utf16_len(body_original) > _RICH_TEXT_MAX
    if not (rev_long or orig_long):
        return []

    blocks: list[dict[str, Any]] = []
    if body_revised:
        blocks.append(_heading_block("本文（補完済み）"))
        for chunk in _chunk_for_blocks(body_revised):
            blocks.append(_paragraph_block(chunk))
    if body_original and body_original != body_revised:
        blocks.append(_heading_block("本文（原文）"))
        for chunk in _chunk_for_blocks(body_original):
            blocks.append(_paragraph_block(chunk))
    return blocks


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

        ``related_people`` / ``related_organizations`` / ``related_projects`` /
        ``tags`` の各リストは、マスタDBの page_id（ハイフン付/なし問わず）を渡す。
        """
        props: dict[str, Any] = {
            KnowledgeEntryProps.TITLE: {"title": _title_value(entry.title)},
            KnowledgeEntryProps.OCCURRED_AT: {"date": {"start": entry.occurred_at.isoformat()}},
            KnowledgeEntryProps.SOURCE_TYPE: {"select": {"name": entry.source_type.value}},
            KnowledgeEntryProps.SOURCE_URL: {"url": str(entry.source_url)},
            KnowledgeEntryProps.SUMMARY: {"rich_text": _rich_text(entry.summary)},
            KnowledgeEntryProps.BODY_REVISED: {"rich_text": _rich_text_body_snippet(entry.body_revised)},
            KnowledgeEntryProps.BODY_ORIGINAL: {"rich_text": _rich_text_body_snippet(entry.body_original)},
            KnowledgeEntryProps.STATUS: {"select": {"name": entry.status.value}},
            KnowledgeEntryProps.EXTERNAL_KEY: {"rich_text": _rich_text(entry.external_key)},
        }
        if entry.related_people:
            props[KnowledgeEntryProps.RELATED_PEOPLE] = {
                "relation": [{"id": pid} for pid in entry.related_people]
            }
        if entry.related_organizations:
            props[KnowledgeEntryProps.RELATED_ORGS] = {
                "relation": [{"id": pid} for pid in entry.related_organizations]
            }
        if entry.related_projects:
            props[KnowledgeEntryProps.RELATED_PROJECTS] = {
                "relation": [{"id": pid} for pid in entry.related_projects]
            }
        if entry.tags:
            props[KnowledgeEntryProps.TAGS] = {
                "relation": [{"id": tid} for tid in entry.tags]
            }
        if entry.confidence is not None:
            props[KnowledgeEntryProps.CONFIDENCE] = {"select": {"name": entry.confidence.value}}
        if entry.rationale:
            props[KnowledgeEntryProps.RATIONALE] = {"rich_text": _rich_text(entry.rationale)}
        if entry.slack_channel:
            props[KnowledgeEntryProps.SLACK_CHANNEL] = {
                "rich_text": _rich_text(entry.slack_channel)
            }
        if entry.slack_thread_ts:
            props[KnowledgeEntryProps.SLACK_THREAD_TS] = {
                "rich_text": _rich_text(entry.slack_thread_ts)
            }
        if entry.slack_thread_parent_kb_id:
            props[KnowledgeEntryProps.SLACK_THREAD_PARENT] = {
                "relation": [{"id": entry.slack_thread_parent_kb_id}]
            }
        return props

    def _list_page_children(self, page_id: str) -> list[dict[str, Any]]:
        """ページ直下の子ブロックを全件取得（ページネーション対応）."""
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = cast(
                dict[str, Any],
                self.client.blocks.children.list(**kwargs),
            )
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def _sync_body_blocks(
        self,
        page_id: str,
        new_blocks: list[dict[str, Any]],
        clear_existing: bool,
    ) -> None:
        """ページ本体ブロックを `new_blocks` で同期する.

        ``clear_existing=True`` の場合、既存子ブロックをすべて archive してから追加。
        ``new_blocks`` が空でも、``clear_existing=True`` なら既存はクリアする
        （短い本文に書き換えられたケースに対応）。
        """
        if clear_existing:
            existing = self._list_page_children(page_id)
            for block in existing:
                try:
                    self.client.blocks.delete(block_id=block["id"])
                except Exception as e:
                    logger.warning(
                        "block_delete_failed",
                        block_id=block.get("id"),
                        error=str(e)[:200],
                    )
        if not new_blocks:
            return
        for i in range(0, len(new_blocks), _BLOCKS_APPEND_BATCH):
            self.client.blocks.children.append(
                block_id=page_id,
                children=new_blocks[i : i + _BLOCKS_APPEND_BATCH],
            )

    def upsert_knowledge_entry(self, entry: KnowledgeEntry) -> tuple[str, bool]:
        """KnowledgeEntry を UPSERT する.

        - 同じ外部キーのエントリがあれば更新（プロパティ書き換え + ページ本体ブロック同期）
        - なければ新規作成（プロパティ + ページ本体ブロック）

        本文（補完済み）／本文（原文）の **どちらかが 2000 UTF-16 単位を超える場合** のみ
        ページ本体に paragraph ブロックで全文を保存する。短い本文は rich_text プロパティ
        だけで完結する。

        Returns:
            (page_id, created): 作成された/更新された KB ページの ID と、新規作成かどうか
        """
        external_key = entry.external_key
        existing_id = self._find_existing_by_external_key(external_key)
        properties = self._build_properties(entry)
        body_blocks = _build_body_blocks(entry.body_revised, entry.body_original)

        if existing_id:
            self.client.pages.update(page_id=existing_id, properties=properties)
            # 既存ページは過去に書いたブロックがある可能性があるため常にクリア
            self._sync_body_blocks(existing_id, body_blocks, clear_existing=True)
            logger.info(
                "kb_entry_updated",
                page_id=existing_id,
                external_key=external_key,
                title=entry.title,
                n_body_blocks=len(body_blocks),
            )
            return existing_id, False

        ds_id = self._get_data_source_id()
        # 新規作成は children を一度に渡せるが、ブロック数が多い場合に備えて
        # 100 個までは children に渡し、残りは追加 append でケアする
        first_batch = body_blocks[:_BLOCKS_APPEND_BATCH]
        rest_batches = body_blocks[_BLOCKS_APPEND_BATCH:]
        create_kwargs: dict[str, Any] = {
            "parent": {"type": "data_source_id", "data_source_id": ds_id},
            "properties": properties,
        }
        if first_batch:
            create_kwargs["children"] = first_batch
        response = cast(dict[str, Any], self.client.pages.create(**create_kwargs))
        new_id = cast(str, response["id"])
        # 残りブロックを追加
        for i in range(0, len(rest_batches), _BLOCKS_APPEND_BATCH):
            self.client.blocks.children.append(
                block_id=new_id,
                children=rest_batches[i : i + _BLOCKS_APPEND_BATCH],
            )
        logger.info(
            "kb_entry_created",
            page_id=new_id,
            external_key=external_key,
            title=entry.title,
            n_body_blocks=len(body_blocks),
        )
        return new_id, True
