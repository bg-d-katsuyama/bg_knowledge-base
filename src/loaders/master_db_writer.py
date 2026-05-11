"""人/企業/プロジェクト/タグ マスタDB への UPSERT ローダー.

エンティティ名（または表記揺れを含むタイトル）をキーに、各マスタDBへ
冪等的に UPSERT する。プロセスを跨いで使えるよう、初回読み出しで
DB 全件のタイトル → page_id インデックスをメモリにキャッシュする。

設計上の不変条件:
- 本クライアントは ``NOTION_PARENT_PAGE_ID`` 配下の各マスタDBにのみ書き込む
- 既存ドキュメント（取り込み元のページ・DB）は一切変更しない
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.common.logger import get_logger
from src.loaders.schema_manager import (
    OrganizationProps,
    PersonProps,
    ProjectProps,
    TagProps,
)

if TYPE_CHECKING:
    from notion_client import Client as NotionClient

logger = get_logger(__name__)


_RICH_TEXT_MAX = 2000


def _normalize_name(name: str) -> str:
    """名前を比較用に正規化（trim + 全角空白除去 + 小文字化なし）."""
    return name.strip().replace("　", " ")


def _truncate_utf16(text: str, max_units: int = _RICH_TEXT_MAX) -> str:
    """UTF-16 code unit 単位で安全に切り詰める."""
    encoded = text.encode("utf-16-le")
    truncated_bytes = encoded[: max_units * 2]
    return truncated_bytes.decode("utf-16-le", errors="ignore")


def _title_value(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": _truncate_utf16(text)}}]


def _extract_title_text(properties: dict[str, Any]) -> str:
    for prop in properties.values():
        if prop.get("type") == "title":
            arr = prop.get("title") or []
            return "".join(t.get("plain_text", "") for t in arr)
    return ""


class MasterDbCache:
    """1 つのマスタ DB に対する name → page_id キャッシュ.

    呼び出し元が長時間ジョブで使うため、初回 ``ensure`` 呼び出し時に
    DB 全件をスキャンしてメモリ常駐辞書を構築する。
    """

    def __init__(
        self,
        client: NotionClient,
        db_id: str,
        title_prop_name: str,
    ) -> None:
        self.client = client
        self.db_id = db_id
        self.title_prop_name = title_prop_name
        self._data_source_id: str | None = None
        self._loaded = False
        self._index: dict[str, str] = {}

    def _get_data_source_id(self) -> str:
        if self._data_source_id:
            return self._data_source_id
        db = cast(
            dict[str, Any],
            self.client.databases.retrieve(database_id=self.db_id),
        )
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError(f"DB {self.db_id} has no data_sources")
        self._data_source_id = cast(str, sources[0]["id"])
        return self._data_source_id

    def _load_index(self) -> None:
        if self._loaded:
            return
        ds_id = self._get_data_source_id()
        cursor: str | None = None
        n = 0
        while True:
            kwargs: dict[str, Any] = {"data_source_id": ds_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            res = cast(
                dict[str, Any],
                self.client.data_sources.query(**kwargs),
            )
            for row in res.get("results", []):
                title = _extract_title_text(row.get("properties") or {})
                key = _normalize_name(title)
                if key:
                    self._index.setdefault(key, cast(str, row["id"]))
                    n += 1
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
        self._loaded = True
        logger.info(
            "master_db_index_loaded",
            db_id=self.db_id,
            count=n,
        )

    def ensure(
        self,
        name: str,
        extra_properties: dict[str, Any] | None = None,
    ) -> str | None:
        """name に対応するエントリの page_id を返す。なければ作成する.

        Args:
            name: マスタDB のタイトル（例: 人名）
            extra_properties: 新規作成時のみ追加で書き込むプロパティ。
                既存エントリには触らない（冪等性保証）。

        Returns:
            page_id。空文字や ``None`` が渡されれば ``None``。
        """
        if not name:
            return None
        norm = _normalize_name(name)
        if not norm:
            return None
        self._load_index()
        existing = self._index.get(norm)
        if existing:
            return existing

        # 新規作成
        ds_id = self._get_data_source_id()
        properties: dict[str, Any] = {
            self.title_prop_name: {"title": _title_value(norm)},
        }
        if extra_properties:
            properties.update(extra_properties)
        try:
            response = cast(
                dict[str, Any],
                self.client.pages.create(
                    parent={"type": "data_source_id", "data_source_id": ds_id},
                    properties=properties,
                ),
            )
        except Exception as e:
            logger.warning(
                "master_db_create_failed",
                db_id=self.db_id,
                name=norm,
                error=str(e)[:200],
            )
            return None
        new_id = cast(str, response["id"])
        self._index[norm] = new_id
        logger.info(
            "master_db_entry_created",
            db_id=self.db_id,
            name=norm,
            page_id=new_id,
        )
        return new_id


class MasterDbWriter:
    """人/企業/プロジェクト/タグの 4 マスタ DB をまとめて扱うラッパー."""

    def __init__(
        self,
        client: NotionClient,
        people_db_id: str,
        organization_db_id: str,
        project_db_id: str,
        tag_db_id: str,
    ) -> None:
        self.people = MasterDbCache(client, people_db_id, PersonProps.NAME)
        self.organizations = MasterDbCache(client, organization_db_id, OrganizationProps.NAME)
        self.projects = MasterDbCache(client, project_db_id, ProjectProps.NAME)
        self.tags = MasterDbCache(client, tag_db_id, TagProps.NAME)

    def ensure_people(self, names: list[str]) -> list[str]:
        ids: list[str] = []
        for name in names:
            pid = self.people.ensure(name)
            if pid:
                ids.append(pid)
        return ids

    def ensure_organizations(self, names: list[str]) -> list[str]:
        ids: list[str] = []
        for name in names:
            pid = self.organizations.ensure(name)
            if pid:
                ids.append(pid)
        return ids

    def ensure_projects(self, names: list[str]) -> list[str]:
        ids: list[str] = []
        for name in names:
            pid = self.projects.ensure(name)
            if pid:
                ids.append(pid)
        return ids

    def ensure_tags(self, tags: list[tuple[str, str]]) -> list[str]:
        """タグ（名前 + カテゴリ）の UPSERT.

        Args:
            tags: ``[(name, category), ...]`` のリスト。

        Returns:
            タグの page_id リスト。
        """
        ids: list[str] = []
        for name, category in tags:
            extra = {TagProps.CATEGORY: {"select": {"name": category}}}
            pid = self.tags.ensure(name, extra_properties=extra)
            if pid:
                ids.append(pid)
        return ids
