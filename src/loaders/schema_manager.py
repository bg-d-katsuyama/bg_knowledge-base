"""Notion スキーマ定義と冪等的なスキーマ構築マネージャ.

本モジュールは以下を提供する:
1. 各DBのプロパティ名定数（ハードコードを避けるため）
2. `NotionSchemaManager`: 親ページ配下に5DBを冪等的に構築するクラス

スキーマ変更時は `docs/schema.md` と本ファイルを同時に更新すること。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from src.common.logger import get_logger

if TYPE_CHECKING:
    from notion_client import Client as NotionClient

logger = get_logger(__name__)


# ============================================================
# DB タイトル（親ページ配下での冪等性チェックに使用）
# ============================================================
DB_TITLE_KNOWLEDGE_ENTRY = "ナレッジエントリDB"
DB_TITLE_PEOPLE = "人DB"
DB_TITLE_ORGANIZATION = "企業・団体DB"
DB_TITLE_PROJECT = "プロジェクトDB"
DB_TITLE_TAG = "タグDB"


# システム自動プロパティ（クラス化するほどでないため文字列定数として配置）
SYS_CREATED_AT = "作成日時（システム）"
SYS_UPDATED_AT = "更新日時（システム）"


class KnowledgeEntryProps:
    """ナレッジエントリDBのプロパティ名."""

    TITLE = "タイトル"
    OCCURRED_AT = "日時"
    SOURCE_TYPE = "ソース種別"
    SOURCE_URL = "ソースURL"
    CREATOR = "作成者"
    RELATED_PEOPLE = "関係者（人）"
    RELATED_ORGS = "関係先（組織）"
    RELATED_PROJECTS = "関連プロジェクト"
    RELATED_FILES = "関連フォルダ/ファイル"
    TAGS = "内容タグ"
    SUMMARY = "要約"
    BODY_REVISED = "本文（補完済み）"
    BODY_ORIGINAL = "本文（原文）"
    RATIONALE = "背景・理由"
    STATUS = "処理ステータス"
    CONFIDENCE = "信頼度"
    EXTERNAL_KEY = "外部キー"
    # Slack 連携用プロパティ（メッセージ単位取り込み）
    SLACK_THREAD_PARENT = "スレッド親メッセージ"
    SLACK_CHANNEL = "Slackチャンネル"
    SLACK_THREAD_TS = "Slackスレッド ts"


class PersonProps:
    """人DBのプロパティ名."""

    NAME = "氏名"
    NAME_KANA = "よみがな"
    ORGANIZATION = "所属"
    EXPERTISE = "専門領域"
    INTERNAL_FLAG = "BG内/外"
    EMAIL = "連絡先"
    NOTES = "備考"


class OrganizationProps:
    """企業・団体DBのプロパティ名."""

    NAME = "名称"
    INDUSTRY = "業界"
    BG_RELATION = "BGとの関係"
    CONTACT = "連絡窓口"


class ProjectProps:
    """プロジェクト/テーマDBのプロパティ名."""

    NAME = "プロジェクト名"
    STATUS = "ステータス"
    OWNER = "主担当"
    PARENT = "親テーマ"


class TagProps:
    """タグDBのプロパティ名."""

    NAME = "タグ名"
    CATEGORY = "カテゴリ"
    PARENT = "親タグ"
    DESCRIPTION = "説明"


# ============================================================
# Notion スキーマ構築マネージャ
# ============================================================


def _title(text: str) -> list[dict[str, Any]]:
    """Notion API のタイトル用 rich_text 配列を組み立てる."""
    return [{"type": "text", "text": {"content": text}}]


def _select_options(*names: str) -> dict[str, Any]:
    """Select / Multi-select 用の options 辞書を組み立てる."""
    return {"options": [{"name": n} for n in names]}


def _single_relation(target_data_source_id: str) -> dict[str, Any]:
    """別データソースへの片方向 Relation プロパティ定義を返す.

    Notion API 2025-09-03 仕様で導入された data_source_id を参照先に使う。
    """
    return {
        "type": "relation",
        "relation": {
            "data_source_id": target_data_source_id,
            "type": "single_property",
            "single_property": {},
        },
    }


def _find_title_prop_name(props: dict[str, Any]) -> str | None:
    """プロパティ群からタイトル型プロパティの **現在の名前** を返す."""
    for name, schema in props.items():
        if schema.get("type") == "title":
            return name
    return None


def _desired_title_name(properties: dict[str, Any]) -> str | None:
    """プロパティ定義からタイトル型プロパティの **あるべき名前** を返す."""
    for name, schema in properties.items():
        if "title" in schema:
            return name
    return None


class NotionSchemaManager:
    """親ページ配下に5DBを冪等的に構築するマネージャ.

    `build_all()` を呼ぶと以下の手順で構築する:
        1. 企業・団体DB を作成（連絡窓口は後で追加）
        2. 人DB を作成（所属 → 企業 を含む）
        3. プロジェクトDB を作成（主担当 → 人 を含む、親テーマは後で追加）
        4. タグDB を作成（親タグは後で追加）
        5. 企業.連絡窓口 → 人 のリレーションを後付け追加
        6. プロジェクト.親テーマ（self-relation）を後付け追加
        7. タグ.親タグ（self-relation）を後付け追加
        8. ナレッジエントリDB を作成（4DBへのリレーションを含む）

    全ステップは冪等で、既存DB・既存プロパティはスキップする。

    Note:
        本マネージャは ``NOTION_PARENT_PAGE_ID`` で指定された親ページの **配下にのみ**
        書き込みを行う。既存ドキュメントは一切変更しない（設計上の不変条件）。
    """

    def __init__(self, client: NotionClient, parent_page_id: str) -> None:
        """マネージャを初期化する.

        Args:
            client: 認証済み Notion クライアント
            parent_page_id: 5DBを配置する親ページの ID
        """
        self.client = client
        self.parent_page_id = parent_page_id
        # ensure_*_db で取得した data_source_id を記録（後続のリレーション解決に使う）
        self._data_source_ids: dict[str, str] = {}

    # ---- 内部ヘルパ -------------------------------------------------

    def _get_data_source_id(self, db_id: str) -> str:
        """DBが保持する単一データソースの ID を取得する."""
        db = cast(dict[str, Any], self.client.databases.retrieve(database_id=db_id))
        sources = db.get("data_sources") or []
        if not sources:
            raise RuntimeError(f"DB {db_id} has no data_sources (unexpected for 2025-09-03 API)")
        return cast(str, sources[0]["id"])

    def _find_existing_db_id(self, db_title: str) -> str | None:
        """親ページ配下に同タイトルのDBが既に存在するか検索する.

        Args:
            db_title: 検索するDBのタイトル

        Returns:
            既存DBのID。存在しなければ None
        """
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "block_id": self.parent_page_id,
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor
            response = cast(dict[str, Any], self.client.blocks.children.list(**kwargs))
            for block in response.get("results", []):
                if block.get("type") != "child_database":
                    continue
                title = block.get("child_database", {}).get("title")
                if title == db_title:
                    return cast(str, block["id"])
            if not response.get("has_more"):
                return None
            cursor = response.get("next_cursor")

    def _create_db(self, db_title: str, properties: dict[str, Any]) -> tuple[str, str]:
        """新規DBをデータソース付きで作成し (db_id, data_source_id) を返す.

        Notion API 2025-09-03 仕様で、プロパティは ``initial_data_source`` に
        包んで送る必要がある（直接 ``properties`` で送ると無視される）。
        """
        response = cast(
            dict[str, Any],
            self.client.databases.create(
                parent={"type": "page_id", "page_id": self.parent_page_id},
                title=_title(db_title),
                initial_data_source={"properties": properties},
            ),
        )
        db_id = cast(str, response["id"])
        data_source_id = cast(str, response["data_sources"][0]["id"])
        logger.info(
            "db_created",
            db_title=db_title,
            db_id=db_id,
            data_source_id=data_source_id,
        )
        return db_id, data_source_id

    def _ensure_data_source_properties(
        self,
        data_source_id: str,
        desired_properties: dict[str, Any],
    ) -> None:
        """既存データソースに不足プロパティを追加し、必要ならタイトルをリネームする.

        - desired_properties に含まれるが既存にないプロパティを追加
        - 既存タイトル名と desired のタイトル名が異なれば、既存をリネーム
        - 既に揃っているプロパティは触らない（冪等）
        """
        ds = cast(
            dict[str, Any],
            self.client.data_sources.retrieve(data_source_id=data_source_id),
        )
        existing = ds.get("properties", {})

        update_payload: dict[str, Any] = {}

        # タイトル: 名前が違えば rename
        current_title = _find_title_prop_name(existing)
        desired_title = _desired_title_name(desired_properties)
        if current_title and desired_title and current_title != desired_title:
            update_payload[current_title] = {"name": desired_title}

        # 非タイトル: 不足分のみ追加
        for name, schema in desired_properties.items():
            if "title" in schema:
                continue  # タイトルは上で処理済み
            if name not in existing:
                update_payload[name] = schema

        if not update_payload:
            logger.info(
                "data_source_already_complete",
                data_source_id=data_source_id,
            )
            return

        self.client.data_sources.update(
            data_source_id=data_source_id,
            properties=update_payload,
        )
        logger.info(
            "data_source_updated",
            data_source_id=data_source_id,
            changed=list(update_payload.keys()),
        )

    def _ensure_db(self, db_title: str, properties: dict[str, Any]) -> tuple[str, str]:
        """同タイトルDBがあれば properties を補完、なければ新規作成し
        (db_id, data_source_id) を返す."""
        existing_id = self._find_existing_db_id(db_title)
        if existing_id:
            ds_id = self._get_data_source_id(existing_id)
            self._ensure_data_source_properties(ds_id, properties)
            logger.info(
                "db_existing_used",
                db_title=db_title,
                db_id=existing_id,
                data_source_id=ds_id,
            )
            return existing_id, ds_id
        return self._create_db(db_title, properties)

    def _add_relation_property(
        self,
        source_data_source_id: str,
        prop_name: str,
        target_data_source_id: str,
    ) -> None:
        """既存データソースに Relation プロパティを後付けで追加する（冪等）."""
        ds = cast(
            dict[str, Any],
            self.client.data_sources.retrieve(data_source_id=source_data_source_id),
        )
        if prop_name in ds.get("properties", {}):
            logger.info(
                "relation_exists_skip",
                source_data_source_id=source_data_source_id,
                prop=prop_name,
            )
            return
        self.client.data_sources.update(
            data_source_id=source_data_source_id,
            properties={prop_name: _single_relation(target_data_source_id)},
        )
        logger.info(
            "relation_added",
            source_data_source_id=source_data_source_id,
            prop=prop_name,
            target_data_source_id=target_data_source_id,
        )

    # ---- DB 別作成メソッド -----------------------------------------

    def ensure_organization_db(self) -> tuple[str, str]:
        """企業・団体 DB を作成する（連絡窓口 Relation はこの段階では含めない）."""
        properties: dict[str, Any] = {
            OrganizationProps.NAME: {"title": {}},
            OrganizationProps.INDUSTRY: {"select": _select_options()},
            OrganizationProps.BG_RELATION: {
                "multi_select": _select_options("取引先", "研究パートナー", "専門家所属先")
            },
        }
        return self._ensure_db(DB_TITLE_ORGANIZATION, properties)

    def ensure_people_db(self, organization_data_source_id: str) -> tuple[str, str]:
        """人 DB を作成する."""
        properties: dict[str, Any] = {
            PersonProps.NAME: {"title": {}},
            PersonProps.NAME_KANA: {"rich_text": {}},
            PersonProps.ORGANIZATION: _single_relation(organization_data_source_id),
            PersonProps.EXPERTISE: {
                "multi_select": _select_options(
                    "土壌",
                    "堆肥",
                    "LCA",
                    "クレジット",
                    "流通",
                    "開示",
                    "戦略",
                    "R&D",
                    "その他",
                )
            },
            PersonProps.INTERNAL_FLAG: {"select": _select_options("内部", "外部")},
            PersonProps.EMAIL: {"email": {}},
            PersonProps.NOTES: {"rich_text": {}},
        }
        return self._ensure_db(DB_TITLE_PEOPLE, properties)

    def ensure_project_db(self, people_data_source_id: str) -> tuple[str, str]:
        """プロジェクト/テーマ DB を作成する（親テーマ self-relation は後付け）."""
        properties: dict[str, Any] = {
            ProjectProps.NAME: {"title": {}},
            ProjectProps.STATUS: {"select": _select_options("計画中", "進行中", "完了", "保留")},
            ProjectProps.OWNER: _single_relation(people_data_source_id),
        }
        return self._ensure_db(DB_TITLE_PROJECT, properties)

    def ensure_tag_db(self) -> tuple[str, str]:
        """タグ DB を作成する（親タグ self-relation は後付け）."""
        properties: dict[str, Any] = {
            TagProps.NAME: {"title": {}},
            TagProps.CATEGORY: {
                "select": _select_options("技術", "戦略", "運用", "顧客", "その他")
            },
            TagProps.DESCRIPTION: {"rich_text": {}},
        }
        return self._ensure_db(DB_TITLE_TAG, properties)

    def ensure_knowledge_entry_db(
        self,
        people_data_source_id: str,
        organization_data_source_id: str,
        project_data_source_id: str,
        tag_data_source_id: str,
    ) -> tuple[str, str]:
        """ナレッジエントリ DB（メイン）を作成する."""
        properties: dict[str, Any] = {
            KnowledgeEntryProps.TITLE: {"title": {}},
            KnowledgeEntryProps.OCCURRED_AT: {"date": {}},
            KnowledgeEntryProps.SOURCE_TYPE: {
                "select": _select_options(
                    "Meet議事録", "手動メモ", "Slack", "Driveファイル", "その他"
                )
            },
            KnowledgeEntryProps.SOURCE_URL: {"url": {}},
            KnowledgeEntryProps.CREATOR: _single_relation(people_data_source_id),
            KnowledgeEntryProps.RELATED_PEOPLE: _single_relation(people_data_source_id),
            KnowledgeEntryProps.RELATED_ORGS: _single_relation(organization_data_source_id),
            KnowledgeEntryProps.RELATED_PROJECTS: _single_relation(project_data_source_id),
            # 「URL複数可」を Files & media 型で表現（複数URL/ファイルを格納可能）
            KnowledgeEntryProps.RELATED_FILES: {"files": {}},
            KnowledgeEntryProps.TAGS: _single_relation(tag_data_source_id),
            KnowledgeEntryProps.SUMMARY: {"rich_text": {}},
            KnowledgeEntryProps.BODY_REVISED: {"rich_text": {}},
            KnowledgeEntryProps.BODY_ORIGINAL: {"rich_text": {}},
            KnowledgeEntryProps.RATIONALE: {"rich_text": {}},
            KnowledgeEntryProps.STATUS: {
                "select": _select_options("未処理", "AI加工済", "人検証済")
            },
            KnowledgeEntryProps.CONFIDENCE: {"select": _select_options("高", "中", "低")},
            KnowledgeEntryProps.EXTERNAL_KEY: {"rich_text": {}},
            # Slack 連携用（self-relation の SLACK_THREAD_PARENT は後付け追加）
            KnowledgeEntryProps.SLACK_CHANNEL: {"rich_text": {}},
            KnowledgeEntryProps.SLACK_THREAD_TS: {"rich_text": {}},
            SYS_CREATED_AT: {"created_time": {}},
            SYS_UPDATED_AT: {"last_edited_time": {}},
        }
        return self._ensure_db(DB_TITLE_KNOWLEDGE_ENTRY, properties)

    # ---- オーケストレーション --------------------------------------

    def build_all(self) -> dict[str, str]:
        """全DBと必要なリレーションを冪等的に構築する.

        Returns:
            環境変数キー（例: ``NOTION_DB_PEOPLE``）から DB ID への辞書
        """
        logger.info("schema_build_start", parent_page_id=self.parent_page_id)

        organization_db_id, organization_ds_id = self.ensure_organization_db()
        people_db_id, people_ds_id = self.ensure_people_db(organization_ds_id)
        project_db_id, project_ds_id = self.ensure_project_db(people_ds_id)
        tag_db_id, tag_ds_id = self.ensure_tag_db()

        # 後付けリレーション（data_source 単位で操作）
        self._add_relation_property(organization_ds_id, OrganizationProps.CONTACT, people_ds_id)
        self._add_relation_property(project_ds_id, ProjectProps.PARENT, project_ds_id)
        self._add_relation_property(tag_ds_id, TagProps.PARENT, tag_ds_id)

        knowledge_entry_db_id, knowledge_entry_ds_id = self.ensure_knowledge_entry_db(
            people_data_source_id=people_ds_id,
            organization_data_source_id=organization_ds_id,
            project_data_source_id=project_ds_id,
            tag_data_source_id=tag_ds_id,
        )

        # Slack 連携用 self-relation（KB→KB の親メッセージ）を後付け追加
        self._add_relation_property(
            knowledge_entry_ds_id,
            KnowledgeEntryProps.SLACK_THREAD_PARENT,
            knowledge_entry_ds_id,
        )

        logger.info("schema_build_complete")
        return {
            "NOTION_DB_KNOWLEDGE_ENTRY": knowledge_entry_db_id,
            "NOTION_DB_PEOPLE": people_db_id,
            "NOTION_DB_ORGANIZATION": organization_db_id,
            "NOTION_DB_PROJECT": project_db_id,
            "NOTION_DB_TAG": tag_db_id,
        }
